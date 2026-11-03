"""Explicitly selected photographs: a manifest of approved paths, checked for print.

PuzzlePress never scans a photo archive. The author lists each approved file in a
small manifest (YAML or JSON) or passes it on the command line; each entry is
read, never modified, and checked: present, a regular file, a supported JPEG or
PNG within the import limits, its upright pixel size and aspect ratio, and the
resolution it can deliver when printed. Importing copies the original bytes into
the project's `cover-assets/` through `cover.assets.import_photo` (content
addressed, never overwriting); crops stay configuration, so the original keeps its
aspect ratio and pixels.

```yaml
photo_manifest_version: 1
base_directory: 'E:\\cameras'     # optional; relative entries resolve from here
photos:
  - path: '2025\\Track day\\IMG_0412.JPG'
    role: cover                   # cover | interior
  - path: 'Événements/garage.png'
    role: interior
```

Without `base_directory`, relative entries resolve from the manifest's folder.
Resolution is reported at the largest size each role prints at cover-fit:
the front panel with bleed (cover) and the interior live area (interior).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from .errors import ProjectError, ValidationIssue

MANIFEST_VERSION = 1
MAX_PHOTOS = 200
ROLES = ("cover", "interior")
MIN_DPI = 300.0  # KDP's minimum image resolution for print.
POOR_DPI = 150.0  # Below this, a photo is reported as unsuitable, not just low.
# Inches each role must fill at cover-fit on the 8.5 x 11 in paperback.
PRINT_AREA = {
    "cover": (8.5 + 0.125, 11.0 + 0.25),  # Front panel with outside and top/bottom bleed.
    "interior": (8.5 - 0.75 - 0.5, 11.0 - 2 * 0.625),  # Live area inside the margins.
}


class ManifestError(ProjectError):
    """A malformed or unreadable photo manifest."""


def _fail(path: str, code: str, message: str) -> ManifestError:
    return ManifestError((ValidationIssue(path, code, message),))


@dataclass(frozen=True)
class PhotoEntry:
    path: str  # As authored.
    role: str = "cover"


@dataclass(frozen=True)
class PhotoManifest:
    entries: tuple[PhotoEntry, ...]
    base_directory: str | None = None


@dataclass(frozen=True)
class PhotoCheck:
    entry: PhotoEntry
    resolved: str
    status: str  # ok | warning | error
    issues: tuple[tuple[str, str], ...] = ()  # (code, message)
    sha256: str | None = None
    format: str | None = None
    pixels: tuple[int, int] | None = None
    aspect_ratio: float | None = None
    max_dpi: float | None = None
    imported: str | None = None
    reused: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.entry.path,
            "role": self.entry.role,
            "resolved": self.resolved,
            "status": self.status,
            "issues": [{"code": c, "message": m} for c, m in self.issues],
            "sha256": self.sha256,
            "format": self.format,
            "pixels": list(self.pixels) if self.pixels else None,
            "aspect_ratio": None if self.aspect_ratio is None else round(self.aspect_ratio, 4),
            "max_dpi": None if self.max_dpi is None else round(self.max_dpi, 1),
            "imported": self.imported,
            "reused": self.reused,
        }


@dataclass(frozen=True)
class PhotoReport:
    checks: tuple[PhotoCheck, ...] = field(default=())

    @property
    def errors(self) -> int:
        return sum(c.status == "error" for c in self.checks)

    @property
    def warnings(self) -> int:
        return sum(c.status == "warning" for c in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "puzzlepress-photo-check",
            "version": 1,
            "photos": [c.to_dict() for c in self.checks],
            "errors": self.errors,
            "warnings": self.warnings,
        }


def parse_manifest(text: str, name: str = "manifest") -> PhotoManifest:
    """YAML or JSON with `photo_manifest_version: 1` and a `photos` list."""
    from .yaml_io import load_yaml

    try:
        data = json.loads(text) if name.lower().endswith(".json") else load_yaml(text)
    except json.JSONDecodeError as error:
        raise _fail("manifest", "json", f"{name} is not valid JSON: {error.msg}") from error
    if not isinstance(data, dict):
        raise _fail("manifest", "type", "Expected a mapping with photo_manifest_version.")
    unknown = sorted(set(data) - {"photo_manifest_version", "base_directory", "photos"})
    if unknown:
        raise _fail(f"manifest.{unknown[0]}", "unknown_field", f"Unknown field {unknown[0]!r}.")
    if data.get("photo_manifest_version") != MANIFEST_VERSION:
        raise _fail("manifest.photo_manifest_version", "version", "Use photo_manifest_version: 1.")
    base = data.get("base_directory")
    if base is not None and (not isinstance(base, str) or not base.strip()):
        raise _fail("manifest.base_directory", "type", "Expected a folder path.")
    photos = data.get("photos")
    if not isinstance(photos, list) or not photos:
        raise _fail("manifest.photos", "required", "List at least one approved photo.")
    if len(photos) > MAX_PHOTOS:
        raise _fail("manifest.photos", "count", f"List at most {MAX_PHOTOS} photos.")
    entries: list[PhotoEntry] = []
    for index, raw in enumerate(photos):
        path = f"manifest.photos[{index}]"
        if isinstance(raw, str):
            raw = {"path": raw}
        if not isinstance(raw, dict):
            raise _fail(path, "type", "Expected a path or {path, role}.")
        extra = sorted(set(raw) - {"path", "role", "note"})
        if extra:
            raise _fail(f"{path}.{extra[0]}", "unknown_field", f"Unknown field {extra[0]!r}.")
        value = raw.get("path")
        if not isinstance(value, str) or not value.strip():
            raise _fail(f"{path}.path", "required", "Each photo needs a file path.")
        if any(ch in value for ch in "*?[]"):
            raise _fail(f"{path}.path", "pattern", "Name individual files; patterns are not read.")
        role = raw.get("role", "cover")
        if role not in ROLES:
            raise _fail(f"{path}.role", "choice", "Use cover or interior.")
        entries.append(PhotoEntry(value.strip(), role))
    return PhotoManifest(tuple(entries), base.strip() if isinstance(base, str) else None)


def load_manifest(path: str | Path) -> tuple[PhotoManifest, Path]:
    source = Path(path).expanduser()
    try:
        text = source.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise _fail("manifest", "io", f"Cannot read {source}: {error}") from error
    return parse_manifest(text, source.name), source.resolve().parent


def resolve_entry(raw: str, base: str | None, manifest_directory: Path | None) -> Path:
    """Absolute entries stay as written; relative ones join `base` or the manifest folder.

    Uses the running platform's paths (drive letters, spaces and Unicode on Windows).
    """
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    if base is not None:
        return Path(base).expanduser() / path
    return (manifest_directory or Path.cwd()) / path


def _windows_only(raw: str) -> bool:
    """A drive-letter path such as E:\\cameras\\x.jpg read on a non-Windows system."""
    return os.name != "nt" and bool(PureWindowsPath(raw).drive)


def check_photo(entry: PhotoEntry, resolved: Path) -> tuple[PhotoCheck, bytes | None]:
    """Read one file (never writing to it) and report its print suitability."""
    from .cover.assets import MAX_ASSET_BYTES, inspect_photo
    from .cover.issues import CoverError

    shown = str(resolved)

    def error(code: str, message: str) -> tuple[PhotoCheck, None]:
        return PhotoCheck(entry, shown, "error", ((code, message),)), None

    if _windows_only(entry.path) and not resolved.exists():
        return error(
            "windows_path",
            "This is a Windows drive path; run the command on that Windows computer.",
        )
    try:
        if resolved.is_dir():
            return error("directory", "Name individual files; folders are never scanned.")
        if not resolved.is_file():
            return error("missing", "The file does not exist.")
        if resolved.stat().st_size > MAX_ASSET_BYTES:
            return error("too_large", "The file is larger than 64 MB.")
        data = resolved.read_bytes()
    except OSError as failure:
        return error("unreadable", f"The file cannot be read: {failure.strerror or failure}")
    try:
        info = inspect_photo(data)
    except CoverError as failure:
        first = failure.issues[0]
        return error(first.code, first.message)
    width, height = info.width, info.height
    area_w, area_h = PRINT_AREA[entry.role]
    # Cover-fit: the photo scales uniformly until it fills the area; the tighter
    # axis decides how many pixels per printed inch remain.
    dpi = min(width / area_w, height / area_h)
    issues: list[tuple[str, str]] = []
    if dpi < POOR_DPI:
        issues.append(
            (
                "image_too_small",
                f"About {dpi:.0f} DPI at the {entry.role} size; KDP requires {MIN_DPI:.0f}. "
                "Choose a larger original.",
            )
        )
    elif dpi < MIN_DPI:
        issues.append(
            (
                "image_low_dpi",
                f"About {dpi:.0f} DPI at the full {entry.role} size (KDP minimum "
                f"{MIN_DPI:.0f}); it can still print smaller.",
            )
        )
    if info.color == "grayscale" and entry.role == "cover":
        issues.append(("grayscale", "A grayscale photograph on a color cover."))
    status = (
        "error"
        if any(c == "image_too_small" for c, _ in issues)
        else ("warning" if issues else "ok")
    )
    return (
        PhotoCheck(
            entry,
            shown,
            status,
            tuple(issues),
            info.sha256,
            info.format,
            (width, height),
            width / height,
            dpi,
        ),
        data,
    )


def check_photos(
    manifest: PhotoManifest,
    manifest_directory: Path | None,
    project_directory: Path | None = None,
) -> PhotoReport:
    """Check each listed photo; with `project_directory`, import the usable ones."""
    from dataclasses import replace

    from .cover.assets import import_photo
    from .cover.issues import CoverError

    checks: list[PhotoCheck] = []
    for entry in manifest.entries:
        resolved = resolve_entry(entry.path, manifest.base_directory, manifest_directory)
        check, data = check_photo(entry, resolved)
        if project_directory is not None and data is not None and check.status != "error":
            try:
                imported = import_photo(project_directory, data, resolved.name)
                check = replace(check, imported=imported.path, reused=imported.reused)
            except CoverError as failure:
                first = failure.issues[0]
                check = replace(
                    check,
                    status="error",
                    issues=(*check.issues, ("import_failed", first.message)),
                )
        checks.append(check)
    return PhotoReport(tuple(checks))
