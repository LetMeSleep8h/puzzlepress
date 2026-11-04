"""The project's imported assets: what exists, where each is used, and safe removal.

Photographs live in `cover-assets/`, imported fonts in `cover-assets/fonts/` and
coloring-book artwork in `coloring-assets/`, under content-addressed names (import
reuses identical bytes, so duplicates are never stored twice). References are read
from authored source only: the cover (any version), the interior style and the
coloring artwork library. Studio also passes the unsaved draft, so
an asset the draft uses is protected before it is saved.

Removal is never immediate deletion. An unreferenced asset is moved, with one
atomic rename inside the same directory tree, to `cover-assets/.trash/`
(`.trash/fonts/` for fonts; artwork to `coloring-assets/.trash/`), which no
listing or import enumerates. It can be
restored under its original name, or purged from the trash as a second,
explicit step. Every path is derived from a validated asset reference and
re-checked against the resolved project folder; symlinks, other folders and
bundled fonts are never touched. A digest the caller saw must still match, so a
file replaced in the meantime is not moved.
"""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .coloring.assets import artwork_directory, stored_files
from .coloring.inspection import header_facts
from .coloring.issues import ArtworkError
from .coloring_config import ARTWORK_DIRECTORY
from .coloring_validation import ARTWORK_NAME
from .cover.assets import _checked_directory, inspect_photo, list_assets
from .cover.font_assets import font_directory, inspect_font, list_fonts
from .cover.issues import CoverError
from .cover_config import ASSET_DIRECTORY, FONT_DIRECTORY, CoverImage
from .cover_design import PhotoElement
from .models import Project

TRASH = ".trash"
PHOTO_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.(?:jpg|png)")
FONT_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.(?:ttf|otf)")
MAX_TRASH = 200  # Entries kept; older items are listed, never silently purged.


class AssetError(Exception):
    def __init__(self, code: str, message: str, uses: tuple["AssetUse", ...] = ()) -> None:
        self.code = code
        self.uses = uses
        super().__init__(message)


@dataclass(frozen=True)
class AssetUse:
    """One authored reference to an asset."""

    source: str  # "saved" (book.yaml on disk) or "draft" (Studio's unsaved draft).
    path: str  # Configuration path, e.g. cover.elements.0.image.
    label: str  # Where it is used, in words.
    area: str  # The Studio section to open: cover, book or artwork.

    def to_dict(self) -> dict[str, object]:
        return {"source": self.source, "path": self.path, "label": self.label, "area": self.area}


def _image_uses(project: Project) -> list[tuple[str, CoverImage, str, str]]:
    uses: list[tuple[str, CoverImage, str, str]] = []
    cover = project.cover
    if cover is not None:
        if cover.image is not None:
            uses.append(("cover.image", cover.image, "Cover photograph", "cover"))
        for index, element in enumerate(cover.elements):
            if isinstance(element, PhotoElement):
                hidden = "" if element.visible else " (hidden)"
                label = f"Cover {element.region.value} photograph '{element.id}'{hidden}"
                uses.append((f"cover.elements.{index}.image", element.image, label, "cover"))
    style = project.interior
    if style is not None:
        if style.title_page.photo is not None:
            uses.append(
                (
                    "interior.title_page.photo.image",
                    style.title_page.photo.image,
                    "Title page photograph",
                    "book",
                )
            )
        for index, divider in enumerate(style.dividers.photos):
            uses.append(
                (
                    f"interior.dividers.photos.{index}.image",
                    divider.photo.image,
                    f"Divider photograph for '{divider.theme}'",
                    "book",
                )
            )
    return uses


def asset_uses(
    reference: str, saved: Project, draft: Project | None = None
) -> tuple[AssetUse, ...]:
    """Every saved and draft reference to `reference` (a cover-assets path)."""
    found: list[AssetUse] = []
    for source, project in (("saved", saved), ("draft", draft)):
        if project is None:
            continue
        for path, image, label, area in _image_uses(project):
            if image.path == reference:
                found.append(AssetUse(source, path, label, area))
        if project.cover is not None:
            for index, font in enumerate(project.cover.fonts):
                if font.path == reference:
                    found.append(
                        AssetUse(source, f"cover.fonts.{index}", f"Cover font '{font.id}'", "cover")
                    )
        if project.coloring is not None:
            for index, art in enumerate(project.coloring.artwork):
                if art.path == reference:
                    found.append(
                        AssetUse(
                            source, f"coloring.artwork.{index}", f"Artwork '{art.id}'", "artwork"
                        )
                    )
    return tuple(found)


@dataclass(frozen=True)
class LibraryEntry:
    kind: str  # photo, font or artwork
    path: str
    name: str
    bytes: int
    sha256: str | None
    facts: dict[str, object]
    problem: str | None
    uses: tuple[AssetUse, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "path": self.path,
            "name": self.name,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "facts": self.facts,
            "problem": self.problem,
            "uses": [use.to_dict() for use in self.uses],
            "in_use": bool(self.uses),
        }


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def library(
    source_directory: Path, saved: Project, draft: Project | None = None
) -> tuple[LibraryEntry, ...]:
    """Every managed photograph and font with its facts and current references."""
    entries: list[LibraryEntry] = []
    try:
        photos = list_assets(source_directory)
        fonts = list_fonts(source_directory)
    except CoverError as error:
        raise AssetError(error.issues[0].code, error.issues[0].message) from error
    for photo in photos:
        file = source_directory / photo.path
        entries.append(
            LibraryEntry(
                "photo",
                photo.path,
                photo.path.rsplit("/", 1)[1],
                photo.info.bytes if photo.info else _size(file),
                photo.info.sha256 if photo.info else None,
                photo.info.to_dict() if photo.info else {},
                photo.problem,
                asset_uses(photo.path, saved, draft),
            )
        )
    for font in fonts:
        file = source_directory / font.path
        entries.append(
            LibraryEntry(
                "font",
                font.path,
                font.path.rsplit("/", 1)[1],
                font.info.bytes if font.info else _size(file),
                font.info.sha256 if font.info else None,
                font.info.to_dict() if font.info else {},
                font.problem,
                asset_uses(font.path, saved, draft),
            )
        )
    try:
        artwork = stored_files(source_directory)
    except ArtworkError as error:
        raise AssetError(error.code, error.message) from error
    for reference in artwork:
        file = source_directory / reference
        facts: dict[str, object] = {}
        problem = None
        try:
            facts = header_facts(file.read_bytes())
        except ArtworkError as error:
            problem = error.code
        except OSError:
            problem = "artwork_missing"
        digest = facts.get("sha256")
        entries.append(
            LibraryEntry(
                "artwork",
                reference,
                reference.rsplit("/", 1)[1],
                _size(file),
                digest if isinstance(digest, str) else None,
                facts,
                problem,
                asset_uses(reference, saved, draft),
            )
        )
    return tuple(entries)


def unmanaged(source_directory: Path) -> tuple[str, ...]:
    """Files in cover-assets that are not importable names (never listed or removed)."""
    directory = source_directory / ASSET_DIRECTORY
    if not directory.is_dir() or directory.is_symlink():
        return ()
    names = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if path.name in (TRASH, "fonts") or path.name.startswith("."):
            continue
        if not PHOTO_NAME.fullmatch(path.name):
            names.append(path.name)
    return tuple(names)


# ------------------------------------------------------------------ resolution


@dataclass(frozen=True)
class _Located:
    kind: str
    name: str
    directory: Path  # The real asset directory (photos or fonts).
    trash: Path  # Its trash directory (not yet created).


def _locate(source_directory: Path, reference: str) -> _Located:
    """Resolve a reference to its real directory; never trust a caller's path."""
    if reference.startswith(f"{ARTWORK_DIRECTORY}/"):
        name = reference.removeprefix(f"{ARTWORK_DIRECTORY}/")
        if not ARTWORK_NAME.fullmatch(name):
            raise AssetError("asset_unsafe", "This is not imported artwork in the project.")
        try:
            directory = artwork_directory(source_directory)
        except ArtworkError as error:
            raise AssetError(error.code, error.message) from error
        return _Located("artwork", name, directory, directory / TRASH)
    try:
        if reference.startswith(f"{FONT_DIRECTORY}/"):
            name = reference.removeprefix(f"{FONT_DIRECTORY}/")
            if not FONT_NAME.fullmatch(name):
                raise AssetError("asset_unsafe", "This is not an imported font in the project.")
            directory = font_directory(source_directory)
            trash = directory.parent / TRASH / "fonts"
            return _Located("font", name, directory, trash)
        name = reference.removeprefix(f"{ASSET_DIRECTORY}/")
        if reference != f"{ASSET_DIRECTORY}/{name}" or not PHOTO_NAME.fullmatch(name):
            raise AssetError("asset_unsafe", "This is not an imported photograph in the project.")
        directory = _checked_directory(source_directory, create=False)
        return _Located("photo", name, directory, directory / TRASH)
    except CoverError as error:
        raise AssetError(error.issues[0].code, error.issues[0].message) from error


def _real_directory(path: Path, project: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise AssetError("asset_unsafe", f"{path.name} must be a real directory.")
    if path.exists() and not path.resolve().is_relative_to(project):
        raise AssetError("asset_unsafe", f"{path.name} resolves outside the project.")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class TrashedAsset:
    reference: str  # Where it was.
    trashed: str  # Project-relative path in the trash.
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"reference": self.reference, "trashed": self.trashed, "sha256": self.sha256}


def trash_asset(
    source_directory: Path,
    reference: str,
    sha256: str,
    saved: Project,
    draft: Project | None = None,
) -> TrashedAsset:
    """Move one unreferenced asset to the project's trash. Raises AssetError.

    Refuses: unsafe references, missing files, a digest that no longer matches
    what the caller saw (`asset_changed`) and any saved or draft use
    (`asset_in_use`, with every use). Callers hold the source save lock so no
    Studio save can add a reference between this check and the move.
    """
    project = Path(source_directory).resolve()
    located = _locate(project, reference)
    path = located.directory / located.name
    if path.is_symlink() or not path.is_file():
        raise AssetError("asset_missing", f"{reference} is not in the project.")
    if _digest(path) != sha256:
        raise AssetError(
            "asset_changed", f"{reference} changed since it was listed. Reload the asset library."
        )
    uses = asset_uses(reference, saved, draft)
    if uses:
        raise AssetError(
            "asset_in_use",
            f"{reference} is used by " + "; ".join(f"{u.label} ({u.source})" for u in uses) + ".",
            uses,
        )
    for directory in (located.trash.parent, located.trash):
        _real_directory(directory, project)
    located.trash.mkdir(parents=True, exist_ok=True)
    _real_directory(located.trash, project)
    target = located.trash / located.name
    if target.exists() or target.is_symlink():
        if target.is_file() and not target.is_symlink() and _digest(target) == sha256:
            os.remove(path)  # The identical bytes are already in the trash.
            return TrashedAsset(reference, _relative(target, project), sha256)
        stem, suffix = located.name.rsplit(".", 1)
        n = 2
        while (located.trash / f"{stem}-{n}.{suffix}").exists():
            n += 1
        target = located.trash / f"{stem}-{n}.{suffix}"
    os.replace(path, target)  # One atomic rename; the bytes are never rewritten.
    if _digest(target) != sha256:
        os.replace(target, path)
        raise AssetError("asset_changed", f"{reference} changed while it was being moved.")
    return TrashedAsset(reference, _relative(target, project), sha256)


def _relative(path: Path, project: Path) -> str:
    return path.resolve().relative_to(project).as_posix()


@dataclass(frozen=True)
class TrashEntry:
    kind: str
    trashed: str  # Project-relative path in the trash.
    restores_to: str  # The asset reference it restores to.
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "trashed": self.trashed,
            "restores_to": self.restores_to,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }


def list_trash(source_directory: Path) -> tuple[TrashEntry, ...]:
    project = Path(source_directory).resolve()
    trash = project / ASSET_DIRECTORY / TRASH
    entries: list[TrashEntry] = []
    for kind, directory, pattern, prefix in (
        ("photo", trash, PHOTO_NAME, ASSET_DIRECTORY),
        ("font", trash / "fonts", FONT_NAME, FONT_DIRECTORY),
        ("artwork", project / ARTWORK_DIRECTORY / TRASH, ARTWORK_NAME, ARTWORK_DIRECTORY),
    ):
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.iterdir(), key=lambda p: p.name)[:MAX_TRASH]:
            if path.is_symlink() or not path.is_file() or not pattern.fullmatch(path.name):
                continue
            original = re.sub(r"-\d+(\.[a-z]+)$", r"\1", path.name)
            restore = path.name if _content_named(path.name) else original
            entries.append(
                TrashEntry(
                    kind,
                    _relative(path, project),
                    f"{prefix}/{restore}",
                    path.stat().st_size,
                    _digest(path),
                )
            )
    return tuple(entries)


def _content_named(name: str) -> bool:
    """Imported names end with a 12-digit hex digest prefix: <stem>-<sha12>.<ext>."""
    return bool(re.search(r"-[0-9a-f]{12}\.[a-z]+$", name))


def _trashed(source_directory: Path, trashed: str) -> tuple[Path, str, _Located]:
    project = Path(source_directory).resolve()
    entry = next((e for e in list_trash(project) if e.trashed == trashed), None)
    if entry is None:
        raise AssetError("not_in_trash", f"{trashed} is not in the project's trash.")
    located = _locate(project, entry.restores_to)
    return project / trashed, entry.restores_to, located


def restore_asset(source_directory: Path, trashed: str) -> str:
    """Move a trashed asset back under its original reference; never overwrite."""
    path, reference, located = _trashed(source_directory, trashed)
    target = located.directory / located.name
    if target.exists() or target.is_symlink():
        raise AssetError("asset_collision", f"{reference} already exists; nothing was restored.")
    located.directory.mkdir(parents=True, exist_ok=True)
    os.link(path, target)  # Never replaces an existing file.
    os.remove(path)
    return reference


def purge_asset(source_directory: Path, trashed: str, sha256: str) -> None:
    """Permanently delete one trashed asset whose digest the caller confirmed."""
    path, _, _ = _trashed(source_directory, trashed)
    if _digest(path) != sha256:
        raise AssetError("asset_changed", f"{trashed} changed; nothing was deleted.")
    os.remove(path)


def facts_of(source_directory: Path, reference: str) -> dict[str, object]:
    """Header facts of one managed asset (for confirmation dialogs)."""
    located = _locate(Path(source_directory).resolve(), reference)
    path = located.directory / located.name
    if path.is_symlink() or not path.is_file():
        raise AssetError("asset_missing", f"{reference} is not in the project.")
    data = path.read_bytes()
    if located.kind == "artwork":
        try:
            return header_facts(data)
        except ArtworkError as error:
            return {"problem": error.code, "sha256": hashlib.sha256(data).hexdigest()}
    try:
        if located.kind == "photo":
            return inspect_photo(data).to_dict()
        info, _ = inspect_font(data, located.name.rsplit(".", 1)[1])
        return info.to_dict()
    except CoverError as error:
        return {"problem": error.issues[0].code, "sha256": hashlib.sha256(data).hexdigest()}
