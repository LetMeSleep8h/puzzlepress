"""The publishing package: assembly in memory, verified export, optional ZIP.

A package is assembled only from a ready PublishingReadinessReport, using the
exact bytes readiness inspected. Its identity covers every file's digest plus
the book, publishing, interior and cover identities, print configuration and
rulesets; never timestamps or paths. Export stages all files in a temporary
sibling directory, verifies them, then swaps the directory into place, so a
reader sees the previous complete package or the new one. The only writer is
`write_package`; it replaces only a package directory this book wrote.
"""

import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..cancellation import checkpoint
from ..cover.preflight import RULESET_ID as COVER_RULESET_ID
from ..cover.preflight import RULESET_VERSION as COVER_RULESET_VERSION
from ..identity import IDENTITY_VERSION
from ..interior.build import check_output_directory
from ..interior.issues import InteriorError
from ..preflight.engine import ruleset_for as interior_ruleset_for
from .identity import canonical
from .provenance import provenance_record
from .readiness import PublishingReadinessReport, readiness_bytes
from .submission import checklist_markdown, kdp_metadata

PACKAGE_VERSION = 1
DIRECTORY = "publishing"
MANIFEST = "package.json"
ARCHIVE = "publishing.zip"
# Each file and why it is in the package. Source project files are never included.
PURPOSES: dict[str, str] = {
    "interior.pdf": "Upload as the manuscript in KDP (Paperback Content).",
    "cover.pdf": "Upload as the print-ready cover in KDP (Paperback Content).",
    "metadata.json": "Values to enter in KDP's Paperback Details, exactly as authored.",
    "kdp-checklist.md": "Manual submission steps for a person to follow in KDP.",
    "readiness.json": "Publishing readiness: every verdict, finding and rule with its source.",
    "interior-preflight.json": "Fresh interior preflight report for these exact bytes.",
    "cover-preflight.json": "Fresh cover preflight report for these exact bytes.",
    "provenance.json": "Machine facts and author declarations, kept separate.",
}
NAMES = tuple(sorted(PURPOSES))
ALL_NAMES = frozenset((*NAMES, MANIFEST))
# Fixed archive metadata: the earliest ZIP date, Unix attributes, stored entries.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


class PackageError(Exception):
    """An expected package failure: not ready, unsafe output or a failed write."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _json(data: object) -> bytes:
    return (
        json.dumps(data, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("ascii")


@dataclass(frozen=True)
class PublishingPackage:
    book_id: str
    identity: str
    files: tuple[tuple[str, bytes], ...]  # Sorted by name, package.json included.
    manifest: dict[str, object]

    def file(self, name: str) -> bytes:
        return dict(self.files)[name]


def identity_inputs(
    report: PublishingReadinessReport, entries: list[dict[str, object]]
) -> dict[str, object]:
    publishing = report.metadata.ruleset
    interior_id, interior_version = interior_ruleset_for(report.project)
    return {
        "package_version": PACKAGE_VERSION,
        "book_id": report.book_id,
        "identities": report.identities(),
        "print": report.print_configuration(),
        "rulesets": {
            "publishing": {"id": publishing.id, "version": publishing.version},
            "interior": {"id": interior_id, "version": interior_version},
            "cover": {"id": COVER_RULESET_ID, "version": COVER_RULESET_VERSION},
        },
        "files": entries,
    }


def package_identity(inputs: dict[str, object]) -> str:
    digest = hashlib.sha256(canonical(inputs)).hexdigest()
    return f"pp{IDENTITY_VERSION}-package-sha256-{digest}"


def assemble_package(report: PublishingReadinessReport) -> PublishingPackage:
    """Assemble from the exact inspected bytes. Raises PackageError when not ready."""
    if not report.package_ready:
        raise PackageError("not_ready", report.statement())
    interior = report.interior_bytes()
    cover = report.cover_bytes()
    interior_report = report.interior_report_bytes()
    cover_report = report.cover_report_bytes()
    if interior is None or cover is None or interior_report is None or cover_report is None:
        raise RuntimeError("A ready report must hold interior and cover bytes")
    contents = {
        "interior.pdf": interior[0],
        "cover.pdf": cover[0],
        "metadata.json": _json(kdp_metadata(report)),
        "kdp-checklist.md": checklist_markdown(report).encode("utf-8"),
        "readiness.json": readiness_bytes(report),
        "interior-preflight.json": interior_report,
        "cover-preflight.json": cover_report,
        "provenance.json": _json(provenance_record(report)),
    }
    entries: list[dict[str, object]] = [
        {
            "name": name,
            "sha256": hashlib.sha256(contents[name]).hexdigest(),
            "bytes": len(contents[name]),
        }
        for name in NAMES
    ]
    inputs = identity_inputs(report, entries)
    identity = package_identity(inputs)
    manifest: dict[str, object] = {
        "package_identity": identity,
        **inputs,
        "files": [entry | {"purpose": PURPOSES[str(entry["name"])]} for entry in entries],
        "status": "ready_for_manual_kdp_submission",
        "statement": "Assembled for manual upload. Not submitted to Amazon; KDP reviews the "
        "book and decides whether to publish it.",
    }
    contents[MANIFEST] = _json(manifest)
    return PublishingPackage(report.book_id, identity, tuple(sorted(contents.items())), manifest)


# ---------------------------------------------------------------- verification


@dataclass(frozen=True)
class ExportState:
    state: str  # none, current, stale, damaged
    identity: str | None = None
    problem: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"state": self.state, "identity": self.identity, "problem": self.problem}


def verify_package_files(files: dict[str, bytes]) -> tuple[dict[str, object] | None, str | None]:
    """(manifest, problem): every expected file present, digests and identity agree."""
    if set(files) != ALL_NAMES:
        extra = sorted(set(files) - ALL_NAMES)
        missing = sorted(ALL_NAMES - set(files))
        return None, f"Unexpected files {extra} or missing files {missing}."
    try:
        manifest = json.loads(files[MANIFEST].decode("ascii"))
    except (UnicodeError, ValueError):
        return None, "package.json is unreadable."
    if not isinstance(manifest, dict) or manifest.get("package_version") != PACKAGE_VERSION:
        return None, "package.json is not a supported package manifest."
    entries = manifest.get("files")
    if not isinstance(entries, list) or [
        e.get("name") for e in entries if isinstance(e, dict)
    ] != list(NAMES):
        return None, "package.json does not list the package files."
    for entry in entries:
        data = files[entry["name"]]
        if entry.get("sha256") != hashlib.sha256(data).hexdigest() or entry.get("bytes") != len(
            data
        ):
            return None, f"{entry['name']} is not the file package.json describes."
    inputs = {
        key: manifest.get(key)
        for key in ("package_version", "book_id", "identities", "print", "rulesets")
    }
    inputs["files"] = [{k: e[k] for k in ("name", "sha256", "bytes")} for e in entries]
    if package_identity(inputs) != manifest.get("package_identity"):
        return None, "package.json's identity does not recompute."
    return manifest, None


def _read_directory(target: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(target.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise PackageError(
                "output_collision", f"{DIRECTORY}/{path.name} is not a regular file."
            )
        files[path.name] = path.read_bytes()
    return files


def export_state(
    output: Path, source_directory: Path, book_id: str, current: str | None = None
) -> ExportState:
    """Inspect an existing export. `current` is the identity a fresh package would have."""
    try:
        directory = check_output_directory(output, source_directory)
    except InteriorError:
        return ExportState("none")
    target = directory / DIRECTORY
    if not target.exists() and not target.is_symlink():
        return ExportState("none")
    if target.is_symlink() or not target.is_dir():
        return ExportState("damaged", problem=f"{DIRECTORY} is not a directory.")
    try:
        manifest, problem = verify_package_files(_read_directory(target))
    except (PackageError, OSError) as error:
        return ExportState("damaged", problem=str(error))
    if manifest is None:
        return ExportState("damaged", problem=problem)
    identity = str(manifest["package_identity"])
    if manifest.get("book_id") != book_id:
        return ExportState("damaged", identity, "The package belongs to another book.")
    if current != identity:
        return ExportState(
            "stale", identity, "The exported package no longer matches the current book."
        )
    return ExportState("current", identity)


# ---------------------------------------------------------------- writing


@dataclass(frozen=True)
class PackageOutput:
    directory: Path
    archive: Path | None


def _owned(target: Path, book_id: str) -> None:
    """Replace only a package directory this book wrote, holding only package files."""
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise PackageError("output_collision", f"{DIRECTORY} exists and is not a directory.")
    if not target.exists():
        return
    names = {path.name for path in target.iterdir()}
    if not names <= ALL_NAMES:
        raise PackageError(
            "output_collision",
            f"{DIRECTORY} holds files PuzzlePress did not write: {sorted(names - ALL_NAMES)}.",
        )
    manifest = target / MANIFEST
    try:
        owner = (
            json.loads(manifest.read_text(encoding="ascii")).get("book_id") if names else book_id
        )
    except (OSError, UnicodeError, ValueError, AttributeError):
        owner = None
    if owner != book_id:
        raise PackageError("output_collision", f"{DIRECTORY} belongs to another book.")


def _write(path: Path, data: bytes) -> None:
    with open(path, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != data:
        raise PackageError("write_failed", f"{path.name} did not read back as written.")


def archive_bytes(package: PublishingPackage) -> bytes:
    """A deterministic ZIP: fixed order, date, attributes; stored (no compressor)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, data in package.files:
            info = zipfile.ZipInfo(f"{DIRECTORY}/{name}", ZIP_DATE)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buffer.getvalue()


def verify_archive(data: bytes, package: PublishingPackage) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            expected = [f"{DIRECTORY}/{name}" for name, _ in package.files]
            if names != expected:
                return "The archive's entries differ from the package."
            for name, content in package.files:
                if archive.read(f"{DIRECTORY}/{name}") != content:
                    return f"{name} differs inside the archive."
    except (zipfile.BadZipFile, OSError, KeyError) as error:
        return f"The archive is unreadable: {error}"
    return None


def write_package(
    package: PublishingPackage, output: Path, source_directory: Path, archive: bool = False
) -> PackageOutput:
    """Write `<output>/publishing/` (and optionally `<output>/publishing.zip`).

    Requires the output directory to hold this book's interior. Files are staged
    in a temporary sibling directory, fsynced, read back and verified; the old
    package directory (only if this book wrote it) is moved aside, the staged
    one renamed into place and the old one removed file by file. A failure
    leaves the previous complete package, never a mixed one.
    """
    try:
        directory = check_output_directory(output, source_directory)
    except InteriorError as error:
        raise PackageError("output_unavailable", error.issues[0].message) from error
    interior_manifest = directory / "interior.json"
    try:
        owner = json.loads(interior_manifest.read_text(encoding="utf-8")).get("book_id")
    except (OSError, UnicodeError, ValueError, AttributeError):
        owner = None
    if interior_manifest.is_symlink() or owner != package.book_id:
        raise PackageError("output_missing", "The build directory holds no interior for this book.")
    target = directory / DIRECTORY
    _owned(target, package.book_id)
    staged = Path(tempfile.mkdtemp(prefix=".publishing-", dir=directory))
    retired: Path | None = None
    try:
        for index, (name, data) in enumerate(package.files):
            checkpoint("write_package", index, len(package.files))
            _write(staged / name, data)
        _, problem = verify_package_files(_read_directory(staged))
        if problem:
            raise PackageError("write_failed", problem)
        # Recheck boundaries and ownership as close to replacement as portable APIs allow.
        check_output_directory(directory, source_directory)
        _owned(target, package.book_id)
        if target.exists():
            retired = staged.with_name(staged.name + "-old")
            os.replace(target, retired)
        try:
            os.replace(staged, target)
        except OSError:
            if retired is not None:
                os.replace(retired, target)
                retired = None
            raise
    except InteriorError as error:
        raise PackageError("output_unavailable", error.issues[0].message) from error
    except OSError as error:
        raise PackageError("write_failed", f"Cannot write the package: {error}") from error
    finally:
        if staged.exists():
            shutil.rmtree(staged, ignore_errors=True)
    if retired is not None:
        for name in ALL_NAMES:
            (retired / name).unlink(missing_ok=True)
        try:
            retired.rmdir()
        except OSError:
            pass  # Left beside the package with only package files; harmless and named.
    manifest, problem = verify_package_files(_read_directory(target))
    if manifest is None or manifest.get("package_identity") != package.identity:
        raise PackageError("write_failed", problem or "The written package differs.")
    written_archive = _write_archive(package, directory) if archive else None
    return PackageOutput(target, written_archive)


def _write_archive(package: PublishingPackage, directory: Path) -> Path:
    target = directory / ARCHIVE
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise PackageError("output_collision", f"{ARCHIVE} exists and is not a file.")
    if target.exists():
        try:
            with zipfile.ZipFile(target) as existing:
                owner = json.loads(existing.read(f"{DIRECTORY}/{MANIFEST}")).get("book_id")
        except (zipfile.BadZipFile, KeyError, OSError, ValueError, AttributeError):
            owner = None
        if owner != package.book_id:
            raise PackageError("output_collision", f"{ARCHIVE} was not written for this book.")
    data = archive_bytes(package)
    problem = verify_archive(data, package)
    if problem:
        raise PackageError("write_failed", problem)
    handle, name = tempfile.mkstemp(prefix=".publishing-", suffix=".zip.tmp", dir=directory)
    staged = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if staged.read_bytes() != data:
            raise PackageError("write_failed", "The archive did not read back as written.")
        os.replace(staged, target)
    except OSError as error:
        raise PackageError("write_failed", f"Cannot write the archive: {error}") from error
    finally:
        staged.unlink(missing_ok=True)
    return target
