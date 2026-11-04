"""Coloring artwork library operations on a project: import, report and remove.

Import is all-or-nothing per batch. Every file is decoded and inspected before
anything is written; one unreadable, unsupported or SVG file refuses the whole
batch with every failure listed. Then the originals are stored (identical bytes
once), and book.yaml is replaced once, revision-checked. If that write fails, the
files this batch created are removed again; files that already existed are never
touched.

Re-importing bytes the library already holds adds nothing: the existing artwork
entry is reported. Quality findings (resolution, blank, color) never stop an
import; they are reported beside it.

Removing an artwork entry removes only the reference in book.yaml. The original
file stays in coloring-assets; it can be moved to the project trash only through
the asset library, and only once nothing references it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from ..coloring_config import Adjustments, Artwork, ColoringBook, ColoringPage
from ..errors import ProjectError, ValidationIssue
from ..models import Project
from ..project import load_project
from ..source_store import replace_source, source_revision
from .assets import (
    artwork_stem,
    artwork_title,
    discard_created,
    read_artwork,
    store_artwork,
    stored_files,
)
from .duplicates import DuplicateReport, find_duplicates
from .inspection import FORMATS, Inspection, inspect_artwork
from .issues import ArtworkError, ImportRejected
from .prepare import Prepared, prepare_artwork


def require_coloring(project: Project) -> ColoringBook:
    if project.coloring is None:
        raise ProjectError(
            (
                ValidationIssue(
                    "coloring",
                    "not_a_coloring_book",
                    "This project is a word-search book; artwork belongs to coloring books.",
                ),
            )
        )
    return project.coloring


@dataclass(frozen=True)
class ImportedArtwork:
    original_name: str
    id: str
    path: str
    sha256: str
    added: bool  # A new artwork entry; False when the library already had these bytes.
    stored: bool  # A new file was written; False when identical bytes were stored.
    page: int | None  # The page number added for it, if any.
    inspection: Inspection

    def to_dict(self) -> dict[str, object]:
        return {
            "original_name": self.original_name,
            "id": self.id,
            "path": self.path,
            "sha256": self.sha256,
            "added": self.added,
            "stored": self.stored,
            "page": self.page,
            "inspection": self.inspection.to_dict(),
        }


def _unique_id(base: str, taken: set[str]) -> str:
    candidate, number = base, 2
    while candidate in taken:
        candidate = f"{base[:60]}-{number}"
        number += 1
    taken.add(candidate)
    return candidate


def import_into(
    project_directory: Path,
    project: Project,
    files: Sequence[tuple[str, bytes]],
    add_pages: bool = True,
) -> tuple[Project, tuple[ImportedArtwork, ...], tuple[tuple[str, str], ...]]:
    """Store the files and return the updated project, the results and what was created.

    Writes only into coloring-assets; the caller replaces book.yaml and, on failure,
    discards the created files (path, sha256).
    """
    book = require_coloring(project)
    if not files:
        raise ImportRejected((ArtworkError("no_files", "Name at least one file to import."),))
    inspections: list[Inspection] = []
    errors: list[ArtworkError] = []
    for name, data in files:
        try:
            inspections.append(inspect_artwork(data, name))
        except ArtworkError as error:
            errors.append(error.about(name))
    if errors:
        raise ImportRejected(tuple(errors))
    by_digest = {item.sha256: item for item in book.artwork}
    taken = {item.id for item in book.artwork}
    artwork = list(book.artwork)
    pages = list(book.pages)
    results: list[ImportedArtwork] = []
    created: list[tuple[str, str]] = []
    try:
        for (name, data), inspection in zip(files, inspections, strict=True):
            digest = inspection.info.sha256
            known = by_digest.get(digest)
            if known is not None:
                results.append(
                    ImportedArtwork(
                        name, known.id, known.path, digest, False, False, None, inspection
                    )
                )
                continue
            extension = FORMATS["JPEG" if inspection.info.format == "jpeg" else "PNG"]
            stored = store_artwork(project_directory, data, name, extension)
            if stored.created:
                created.append((stored.path, digest))
            entry = Artwork(
                _unique_id(artwork_stem(name), taken), stored.path, digest, artwork_title(name)
            )
            artwork.append(entry)
            by_digest[digest] = entry
            page = None
            if add_pages:
                pages.append(ColoringPage(entry.id))
                page = len(pages)
            results.append(
                ImportedArtwork(
                    name, entry.id, entry.path, digest, True, stored.created, page, inspection
                )
            )
    except ArtworkError as error:
        for path, digest in created:
            discard_created(project_directory, path, digest)
        raise ImportRejected((error,)) from error
    updated = replace(project, coloring=replace(book, artwork=tuple(artwork), pages=tuple(pages)))
    return updated, tuple(results), tuple(created)


def import_files(
    source: Path, files: Sequence[tuple[str, bytes]], add_pages: bool = True
) -> tuple[ImportedArtwork, ...]:
    """Import into the project at `source` (book.yaml or its folder) and save it."""
    loaded = load_project(source)
    path = loaded.source_path
    revision = source_revision(path)
    updated, results, created = import_into(path.parent, loaded.project, files, add_pages)
    if updated == loaded.project:
        return results  # Every file was already in the library: nothing to write.
    try:
        replace_source(path, updated, revision)
    except BaseException:
        for reference, digest in created:
            discard_created(path.parent, reference, digest)
        raise
    return results


@dataclass(frozen=True)
class ArtworkEntryReport:
    artwork: Artwork
    pages: tuple[int, ...]
    inspection: Inspection | None
    error: ArtworkError | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.artwork.id,
            "title": self.artwork.title,
            "path": self.artwork.path,
            "sha256": self.artwork.sha256,
            "adjustments": self.artwork.adjustments.to_dict(),
            "adjustments_applied": False,
            "pages": list(self.pages),
            "inspection": self.inspection.to_dict() if self.inspection else None,
            "error": self.error.to_dict() if self.error else None,
        }


@dataclass(frozen=True)
class LibraryReport:
    book_id: str
    entries: tuple[ArtworkEntryReport, ...]
    page_count: int
    unreferenced: tuple[str, ...]  # Stored files no artwork entry names.
    duplicates: DuplicateReport

    @property
    def blocking(self) -> int:
        return sum(
            1
            for entry in self.entries
            if entry.error is not None or (entry.inspection and entry.inspection.blocking)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "report_version": 1,
            "book_id": self.book_id,
            "artwork": [entry.to_dict() for entry in self.entries],
            "pages": self.page_count,
            "unreferenced_files": list(self.unreferenced),
            "blocking": self.blocking,
            "duplicates": self.duplicates.to_dict(),
        }


def library_report(
    project_directory: Path,
    project: Project,
    inspect: Callable[[bytes, str], Inspection] = inspect_artwork,
) -> LibraryReport:
    """Every artwork entry with its pages, file facts and findings, plus duplicates.

    `inspect` may be a cache over `inspect_artwork` keyed by the verified bytes.
    """
    book = require_coloring(project)
    pages: dict[str, list[int]] = {}
    for number, artwork in book.artwork_pages:
        pages.setdefault(artwork, []).append(number)
    entries: list[ArtworkEntryReport] = []
    inspections: dict[str, Inspection | None] = {}
    for item in book.artwork:
        inspection: Inspection | None = None
        failure: ArtworkError | None = None
        try:
            inspection = inspect(read_artwork(project_directory, item), item.path)
        except ArtworkError as error:
            failure = error.about(item.path)
        inspections[item.id] = inspection
        entries.append(ArtworkEntryReport(item, tuple(pages.get(item.id, ())), inspection, failure))
    referenced = {item.path for item in book.artwork}
    try:
        files = stored_files(project_directory)
    except ArtworkError:
        files = ()
    unreferenced = tuple(path for path in files if path not in referenced)
    return LibraryReport(
        project.book.id,
        tuple(entries),
        len(book.pages),
        unreferenced,
        find_duplicates(book, inspections),
    )


@dataclass(frozen=True)
class RemovedArtwork:
    artwork: Artwork
    pages: tuple[int, ...]  # Page numbers removed with it.
    file_still_referenced: bool  # Another entry pins the same file.

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.artwork.id,
            "path": self.artwork.path,
            "sha256": self.artwork.sha256,
            "pages_removed": list(self.pages),
            "file_kept": True,
            "file_still_referenced": self.file_still_referenced,
        }


def without_artwork(
    project: Project, artwork_id: str, with_pages: bool = False
) -> tuple[Project, RemovedArtwork]:
    """The project without one artwork entry (and, if asked, the pages showing it)."""
    book = require_coloring(project)
    item = book.artwork_by_id(artwork_id)
    if item is None:
        raise ArtworkError("unknown_artwork", f"No artwork has the ID {artwork_id!r}.", artwork_id)
    used = tuple(n for n, page in enumerate(book.pages, start=1) if page.artwork == artwork_id)
    if used and not with_pages:
        listed = ", ".join(str(n) for n in used)
        raise ArtworkError(
            "artwork_in_use",
            f"'{artwork_id}' is on page {listed}. Remove those pages too "
            "(CLI --with-pages, Studio 'Also remove its pages'), or reassign them first.",
            artwork_id,
        )
    remaining = tuple(a for a in book.artwork if a.id != artwork_id)
    pages = tuple(page for page in book.pages if page.artwork != artwork_id)
    updated = replace(project, coloring=replace(book, artwork=remaining, pages=pages))
    shared = any(other.path == item.path for other in remaining)
    return updated, RemovedArtwork(item, used, shared)


def remove_artwork(source: Path, artwork_id: str, with_pages: bool = False) -> RemovedArtwork:
    """Remove one artwork reference from the project at `source` and save it."""
    loaded = load_project(source)
    revision = source_revision(loaded.source_path)
    updated, removed = without_artwork(loaded.project, artwork_id, with_pages)
    replace_source(loaded.source_path, updated, revision)
    return removed


def _artwork(project: Project, artwork_id: str) -> Artwork:
    item = require_coloring(project).artwork_by_id(artwork_id)
    if item is None:
        raise ArtworkError("unknown_artwork", f"No artwork has the ID {artwork_id!r}.", artwork_id)
    return item


def prepare_entry(
    project_directory: Path,
    project: Project,
    artwork_id: str,
    adjustments: Adjustments | None = None,
    prepare: Callable[[bytes, Adjustments, str], Prepared] = prepare_artwork,
) -> Prepared:
    """Prepare one artwork from its verified original, with its saved settings unless
    `adjustments` previews others. Nothing is written."""
    item = _artwork(project, artwork_id)
    data = read_artwork(project_directory, item)
    return prepare(data, adjustments or item.adjustments, item.path)


def with_adjustments(
    project: Project, artwork_id: str, adjustments: Adjustments
) -> tuple[Project, Artwork]:
    """The project with one artwork's settings replaced (defaults reset them)."""
    book = require_coloring(project)
    item = _artwork(project, artwork_id)
    updated_item = replace(item, adjustments=adjustments)
    artwork = tuple(updated_item if a.id == artwork_id else a for a in book.artwork)
    return replace(project, coloring=replace(book, artwork=artwork)), updated_item


def adjust_artwork(
    source: Path, artwork_id: str, adjustments: Adjustments, revision: str | None = None
) -> Artwork:
    """Save one artwork's settings in the project at `source`; the original is untouched.

    `revision` (when given) must be the saved byte revision the caller last saw.
    """
    loaded = load_project(source)
    current = source_revision(loaded.source_path)
    if revision is not None and revision != current:
        raise ProjectError(
            (
                ValidationIssue(
                    "book.yaml",
                    "source_changed",
                    "book.yaml changed since it was read; reload it, then save the settings.",
                ),
            )
        )
    updated, item = with_adjustments(loaded.project, artwork_id, adjustments)
    if updated != loaded.project:
        replace_source(loaded.source_path, updated, current)
    return item
