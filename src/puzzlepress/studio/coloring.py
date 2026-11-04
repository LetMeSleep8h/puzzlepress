"""Studio adapter for coloring-book artwork: listing, import, removal, thumbnails.

Every decision is `puzzlepress.coloring`'s. Imports and removals change the saved
book.yaml, so they hold the source save lock, refuse when the saved revision is not
the one the browser last saw, and write through the same revision-checked writer
as the CLI. The browser names artwork by ID only; no path it sends is joined onto
the filesystem, and an uploaded file's name is used for its title and file stem
only. Inspections are cached by the SHA-256 of the verified bytes.
"""

import hashlib
from collections import OrderedDict
from threading import Lock

from puzzlepress.coloring.assets import read_artwork
from puzzlepress.coloring.inspection import Inspection, inspect_artwork, thumbnail_png
from puzzlepress.coloring.issues import ArtworkError, ImportRejected
from puzzlepress.coloring.library import (
    import_files,
    library_report,
    remove_artwork,
    require_coloring,
)
from puzzlepress.errors import ProjectError

from .editing import _SAVE_LOCK
from .service import StudioError, StudioService

CACHE_ENTRIES = 512
STATUS = {"artwork_in_use": 409, "unknown_artwork": 404, "asset_collision": 409}


def _rejected(error: ImportRejected) -> StudioError:
    first = error.errors[0]
    count = len(error.errors)
    message = (
        first.message
        if count == 1
        else f"{count} files cannot be imported; nothing was imported. {first.message}"
    )
    studio = StudioError(422, first.code, message)
    studio.issues = [  # type: ignore[attr-defined]
        {"path": failure.subject, "code": failure.code, "message": failure.message}
        for failure in error.errors
    ]
    return studio


def _source_error(error: ProjectError) -> StudioError | None:
    codes = {issue.code for issue in error.issues}
    if "source_changed" in codes:
        return StudioError(
            409, "source_changed", "The saved book changed. Reload it, then import again."
        )
    if "not_a_coloring_book" in codes:
        return StudioError(422, "not_a_coloring_book", error.issues[0].message)
    return None


class ColoringService:
    def __init__(self, service: StudioService) -> None:
        self.store = service.store
        self._cache: OrderedDict[str, Inspection] = OrderedDict()
        self._cache_lock = Lock()

    def _inspect(self, data: bytes, name: str) -> Inspection:
        digest = hashlib.sha256(data).hexdigest()
        with self._cache_lock:
            cached = self._cache.get(digest)
            if cached is not None:
                self._cache.move_to_end(digest)
                return cached
        inspection = inspect_artwork(data, name)
        with self._cache_lock:
            self._cache[digest] = inspection
            while len(self._cache) > CACHE_ENTRIES:
                self._cache.popitem(last=False)
        return inspection

    def listing(self, key: str) -> dict[str, object]:
        project, revision = self.store.snapshot(key)
        try:
            require_coloring(project)
        except ProjectError as error:
            raise _source_error(error) or error from error
        report = library_report(self.store.source(key).parent, project, self._inspect)
        return {"revision": revision, "report": report.to_dict()}

    def _check(self, key: str, revision: str) -> None:
        _, current = self.store.snapshot(key)
        if current != revision:
            raise StudioError(
                409, "source_changed", "The saved book changed. Reload it, then try again."
            )

    def import_artwork(self, key: str, data: bytes, name: str, revision: str) -> dict[str, object]:
        with _SAVE_LOCK:
            self._check(key, revision)
            try:
                results = import_files(self.store.source(key), [(name, data)])
            except ImportRejected as error:
                raise _rejected(error) from error
            except ProjectError as error:
                raise _source_error(error) or error from error
        return {"imported": [result.to_dict() for result in results], **self.listing(key)}

    def remove(self, key: str, artwork: str, revision: str, with_pages: bool) -> dict[str, object]:
        with _SAVE_LOCK:
            self._check(key, revision)
            try:
                removed = remove_artwork(self.store.source(key), artwork, with_pages)
            except ArtworkError as error:
                raise StudioError(STATUS.get(error.code, 422), error.code, error.message) from error
            except ProjectError as error:
                raise _source_error(error) or error from error
        return {"removed": removed.to_dict(), **self.listing(key)}

    def thumbnail(self, key: str, artwork: str) -> bytes:
        project = self.store.load(key)
        try:
            book = require_coloring(project)
        except ProjectError as error:
            raise _source_error(error) or error from error
        item = book.artwork_by_id(artwork)
        if item is None:
            raise StudioError(404, "unknown_artwork", "No artwork has this ID.")
        try:
            return thumbnail_png(read_artwork(self.store.source(key).parent, item))
        except ArtworkError as error:
            raise StudioError(404, error.code, error.message) from error
