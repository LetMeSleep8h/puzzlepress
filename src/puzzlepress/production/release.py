"""A release directory: verified against its manifest, swapped in whole, recovered.

A release is a directory holding `production.json` and exactly the files it lists
(names relative to the directory; dot-names are never listed). Staged releases are
verified before they replace the previous one; the previous one survives until the
new one is in place, moved aside under a backup prefix and removed afterwards. A
process that dies between the two renames leaves the release missing and its
previous version in the backup: `recover` (run under the production lock) puts it
back. Only direct children of the release's parent with this release's own prefixes,
real directories (never links), are touched; backups must hold this book's manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .produce import KIND, MANIFEST_NAME, _fail


def listing(directory: Path) -> list[str]:
    """Every file below `directory` a manifest lists: no dot-names, not the manifest."""
    names = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            if not any(part.startswith(".") for part in relative.split("/")):
                names.append(relative)
    return [name for name in names if name != MANIFEST_NAME]


def verify(directory: Path, files: tuple[tuple[str, str, int], ...]) -> None:
    """Every listed file is present with its bytes, and nothing else is."""
    expected = {name: (digest, size) for name, digest, size in files}
    if set(listing(directory)) != set(expected):
        raise _fail("verification_failed", "The staged files differ from the manifest's list.")
    for name, (digest, size) in expected.items():
        data = (directory / name).read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise _fail("verification_failed", f"Staged {name} does not match the manifest.")


def manifest_files(directory: Path) -> tuple[dict[str, object], tuple[tuple[str, str, int], ...]]:
    """(manifest, its file records); raises when production.json is unusable."""
    try:
        manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
        files = tuple(
            (str(f["name"]), str(f["sha256"]), int(f["bytes"])) for f in manifest["files"]
        )
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        raise _fail("verification_failed", f"{MANIFEST_NAME} is unusable: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("kind") != KIND:
        raise _fail("verification_failed", f"{MANIFEST_NAME} is not a production manifest.")
    return manifest, files


def verify_release(directory: Path) -> dict[str, object]:
    """The manifest of a release whose files match it exactly; raises otherwise."""
    manifest, files = manifest_files(directory)
    verify(directory, files)
    return manifest


def swap_in(staged: Path, release: Path, backup_prefix: str) -> None:
    """Put the verified `staged` directory in place of `release`; the previous release
    survives until the new one is in place."""
    if not release.exists():
        os.replace(staged, release)
        return
    backup = Path(tempfile.mkdtemp(prefix=backup_prefix, dir=release.parent))
    backup.rmdir()
    os.replace(release, backup)
    try:
        os.replace(staged, release)
    except OSError as error:
        os.replace(backup, release)
        raise _fail("write_failed", f"Could not put the new output in place: {error}") from error
    shutil.rmtree(backup, ignore_errors=True)


def _ours(path: Path, parent: Path, prefix: str) -> bool:
    return (
        path.parent == parent
        and path.name.startswith(prefix)
        and not path.is_symlink()
        and path.is_dir()
    )


def _owned(path: Path, book_id: str) -> bool:
    try:
        data = json.loads((path / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return False
    return isinstance(data, dict) and data.get("kind") == KIND and data.get("book_id") == book_id


def recover(
    release: Path, book_id: str, staging_prefix: str, backup_prefix: str
) -> tuple[str, ...]:
    """Under the lock: finish what an interrupted earlier run left beside `release`."""
    parent = release.parent
    notes: list[str] = []
    entries = sorted(parent.iterdir())
    backups = [p for p in entries if _ours(p, parent, backup_prefix) and _owned(p, book_id)]
    if not release.exists() and len(backups) == 1:
        os.replace(backups[0], release)
        notes.append("Restored the previous output, which an interrupted run had moved aside.")
        backups = []
    for path in backups:
        if release.exists() and _ours(path, parent, backup_prefix):
            shutil.rmtree(path)
            notes.append(f"Removed {path.name}, a previous output an interrupted run kept.")
    for path in entries:
        if _ours(path, parent, staging_prefix):
            shutil.rmtree(path)
            notes.append(f"Removed {path.name}, the files of an interrupted run.")
    return tuple(notes)


def pending_recovery(release: Path, backup_prefix: str) -> bool:
    """True when the release is missing and a backup of it waits beside it."""
    parent = release.parent
    if release.exists() or not parent.is_dir():
        return False
    return any(_ours(p, parent, backup_prefix) for p in parent.iterdir())
