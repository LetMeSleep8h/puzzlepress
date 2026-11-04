"""Artwork files in the project's `coloring-assets/` folder.

Originals are stored byte-for-byte under content-addressed names
(`<stem>-<sha12>.png|jpg`, extension from the detected format) and are never
rewritten: identical bytes are stored once, a different file under an existing
name is refused, and every write is staged, fsynced, read back and linked into
place without replacing anything. Every read re-checks that the folder is a real
directory directly inside the resolved project and that the bytes still match the
pinned SHA-256, so one project never reads another project's files.
"""

import hashlib
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..coloring_config import ARTWORK_DIRECTORY, MAX_TITLE, Artwork
from ..coloring_validation import ARTWORK_NAME
from ..cover.assets import MAX_ASSET_BYTES
from .issues import ArtworkError

TRASH = ".trash"


def artwork_directory(project_directory: Path, create: bool = False) -> Path:
    """The real coloring-assets directory directly inside the resolved project folder."""
    project = Path(project_directory).resolve()
    directory = project / ARTWORK_DIRECTORY
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ArtworkError("asset_unsafe", f"{ARTWORK_DIRECTORY} must be a real directory.")
    if create:
        directory.mkdir(exist_ok=True)
    if directory.exists() and directory.resolve().parent != project:
        raise ArtworkError("asset_unsafe", f"{ARTWORK_DIRECTORY} resolves outside the project.")
    return directory


def _plain(name: str) -> str:
    """The last path component of an uploaded or command-line name, never a path."""
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def artwork_stem(original_name: str) -> str:
    """ASCII stem for file names and IDs: accents folded, everything else a hyphen."""
    stem = Path(_plain(original_name)).stem
    folded = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:40].strip("-")
    return slug or "artwork"


def artwork_title(original_name: str) -> str | None:
    """A readable title from the original name, Unicode kept, controls removed."""
    stem = Path(_plain(original_name)).stem
    cleaned = "".join(
        " " if unicodedata.category(c).startswith(("C", "Z")) else c
        for c in unicodedata.normalize("NFC", stem)
    )
    cleaned = re.sub(r"[ _]+", " ", cleaned).strip()[:MAX_TITLE].strip()
    return cleaned or None


def artwork_name(original_name: str, sha256: str, extension: str) -> str:
    return f"{artwork_stem(original_name)}-{sha256[:12]}.{extension}"


def _managed(path: Path) -> bool:
    return bool(ARTWORK_NAME.fullmatch(path.name)) and not path.is_symlink() and path.is_file()


def find_stored(directory: Path, data: bytes, sha256: str) -> str | None:
    """The name of a file already holding these exact bytes, if any."""
    if not directory.is_dir():
        return None
    for candidate in sorted(directory.glob(f"*{sha256[:12]}.*")):
        if _managed(candidate) and candidate.read_bytes() == data:
            return candidate.name
    return None


@dataclass(frozen=True)
class StoredArtwork:
    path: str  # Project-relative reference: coloring-assets/<name>.
    created: bool  # False when the identical bytes were already stored.


def store_artwork(
    project_directory: Path, data: bytes, original_name: str, extension: str
) -> StoredArtwork:
    """Copy validated bytes into coloring-assets without overwriting anything."""
    sha256 = hashlib.sha256(data).hexdigest()
    directory = artwork_directory(project_directory, create=True)
    existing = find_stored(directory, data, sha256)
    if existing is not None:
        return StoredArtwork(f"{ARTWORK_DIRECTORY}/{existing}", False)
    name = artwork_name(original_name, sha256, extension)
    target = directory / name
    reference = f"{ARTWORK_DIRECTORY}/{name}"
    if target.exists() or target.is_symlink():
        raise ArtworkError("asset_collision", f"{reference} already exists with other content.")
    handle, staged_name = tempfile.mkstemp(prefix=".artwork-import-", suffix=".tmp", dir=directory)
    staged = Path(staged_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if staged.read_bytes() != data:
            raise ArtworkError("write_failed", "The staged copy does not match the file.")
        try:
            os.link(staged, target)  # Atomic, and never replaces an existing file.
        except FileExistsError:
            if _managed(target) and target.read_bytes() == data:
                return StoredArtwork(reference, False)
            raise ArtworkError(
                "asset_collision", f"{reference} already exists with other content."
            ) from None
    except OSError as error:
        raise ArtworkError("write_failed", f"Cannot store the artwork: {error}") from error
    finally:
        staged.unlink(missing_ok=True)
    return StoredArtwork(reference, True)


def discard_created(project_directory: Path, reference: str, sha256: str) -> None:
    """Undo a store that created `reference`, only if it still holds those bytes."""
    path = artwork_directory(project_directory) / reference.removeprefix(f"{ARTWORK_DIRECTORY}/")
    try:
        if _managed(path) and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
            path.unlink()
    except OSError:
        pass  # Left as an unreferenced, content-addressed file: harmless and listed.


def artwork_path(project_directory: Path, reference: str) -> Path:
    """Resolve a validated reference inside this project's coloring-assets."""
    name = reference.removeprefix(f"{ARTWORK_DIRECTORY}/")
    if reference != f"{ARTWORK_DIRECTORY}/{name}" or not ARTWORK_NAME.fullmatch(name):
        raise ArtworkError("asset_unsafe", f"{reference} is not an imported artwork file.")
    return artwork_directory(project_directory) / name


def read_artwork(project_directory: Path, artwork: Artwork) -> bytes:
    """The original bytes of one artwork entry, verified against its pinned digest."""
    path = artwork_path(project_directory, artwork.path)
    try:
        if path.is_symlink() or not path.is_file():
            raise ArtworkError("artwork_missing", f"{artwork.path} is missing from the project.")
        if path.stat().st_size > MAX_ASSET_BYTES:
            raise ArtworkError("file_too_large", f"{artwork.path} is larger than artwork may be.")
        data = path.read_bytes()
    except OSError as error:
        raise ArtworkError("artwork_missing", f"Cannot read {artwork.path}: {error}") from error
    actual = hashlib.sha256(data).hexdigest()
    if actual != artwork.sha256:
        raise ArtworkError(
            "artwork_changed",
            f"{artwork.path} no longer matches the SHA-256 recorded for '{artwork.id}'. "
            "The original was replaced outside PuzzlePress; import the intended file again.",
        )
    return data


def stored_files(project_directory: Path) -> tuple[str, ...]:
    """References of every managed artwork file (the trash is never listed)."""
    directory = artwork_directory(project_directory)
    if not directory.is_dir():
        return ()
    return tuple(
        f"{ARTWORK_DIRECTORY}/{path.name}"
        for path in sorted(directory.iterdir(), key=lambda p: p.name)
        if _managed(path)
    )
