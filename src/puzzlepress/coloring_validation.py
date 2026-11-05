"""Validation of the optional `coloring` section (schema v1, coloring version 1).

Only interpretability is checked here. Image facts (format, pixels, resolution,
duplicates) need the files and are reported by `coloring.inspection`, never as
schema errors, so a project with a weak drawing still loads and can be fixed.
"""

import math
import re

from .coloring_config import (
    ARTWORK_DIRECTORY,
    CENTRED,
    COLORING_VERSION,
    MAX_ARTWORK,
    MAX_DIVIDER_TEXT,
    MAX_PAGES,
    MAX_TITLE,
    MIN_PLACEMENT_SCALE,
    Adjustments,
    Artwork,
    Border,
    ColoringBook,
    ColoringDivider,
    ColoringLayout,
    ColoringPage,
    Placement,
)
from .content_validation import _Reader
from .errors import ValidationIssue

# Content-addressed artwork names: lowercase stem, then the first 12 hex digits of
# the file's SHA-256, then the extension of its detected format.
ARTWORK_NAME = re.compile(r"(?:[a-z0-9]+-)*(?P<sha12>[0-9a-f]{12})\.(?:png|jpg)")
ARTWORK_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SHA256 = re.compile(r"[0-9a-f]{64}")

_ADJUSTMENT_FIELDS = {
    "grayscale",
    "threshold",
    "brightness",
    "contrast",
    "background_cleanup",
    "despeckle",
    "line_weight",
    "invert",
}


def _number(
    reader: _Reader, value: object, path: str, low: float, high: float, default: float
) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        reader.issue(path, "type", f"Expected a number from {low} to {high}.")
        return default
    if not low <= value <= high:
        reader.issue(path, "range", f"Expected a number from {low} to {high}.")
        return default
    return round(float(value), 4)


def _integer(reader: _Reader, value: object, path: str, low: int, high: int) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        reader.issue(path, "range", f"Expected a whole number from {low} to {high}.")
        return 0
    return value


def _flag(reader: _Reader, value: object, path: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        reader.issue(path, "type", "Expected true or false.")
        return default
    return value


def _list(reader: _Reader, value: object, path: str, maximum: int) -> list[object]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        reader.issue(path, "count", f"Expected a list with at most {maximum} entries.")
        return []
    return value


def _adjustments(reader: _Reader, raw: object, path: str) -> Adjustments:
    if raw is None:
        return Adjustments()
    data = reader.mapping(raw, path, _ADJUSTMENT_FIELDS)
    threshold = data.get("threshold")
    return Adjustments(
        grayscale=_flag(reader, data.get("grayscale"), f"{path}.grayscale", True),
        threshold=None
        if threshold is None
        else _number(reader, threshold, f"{path}.threshold", 0.05, 0.95, 0.5),
        brightness=_number(reader, data.get("brightness"), f"{path}.brightness", -1, 1, 0.0),
        contrast=_number(reader, data.get("contrast"), f"{path}.contrast", 0.25, 4, 1.0),
        background_cleanup=_number(
            reader, data.get("background_cleanup"), f"{path}.background_cleanup", 0, 1, 0.0
        ),
        despeckle=_integer(reader, data.get("despeckle"), f"{path}.despeckle", 0, 5),
        line_weight=_integer(reader, data.get("line_weight"), f"{path}.line_weight", -2, 2),
        invert=_flag(reader, data.get("invert"), f"{path}.invert", False),
    )


def _placement(reader: _Reader, raw: object, path: str) -> Placement | None:
    if raw is None:
        return None
    data = reader.mapping(raw, path, {"scale", "x", "y"})
    placement = Placement(
        _number(reader, data.get("scale"), f"{path}.scale", MIN_PLACEMENT_SCALE, 1.0, 1.0),
        _number(reader, data.get("x"), f"{path}.x", -1.0, 1.0, 0.0),
        _number(reader, data.get("y"), f"{path}.y", -1.0, 1.0, 0.0),
    )
    return None if placement == CENTRED else placement


def _title(reader: _Reader, value: object, path: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > MAX_TITLE
        or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        reader.issue(path, "text", f"Expected 1..{MAX_TITLE} characters on one line.")
        return None
    return value.strip()


def _artwork(reader: _Reader, raw: object, path: str) -> Artwork | None:
    data = reader.mapping(raw, path, {"id", "path", "sha256", "title", "adjustments"})
    if not isinstance(raw, dict):
        return None
    identifier = data.get("id")
    if not isinstance(identifier, str) or not ARTWORK_ID.fullmatch(identifier):
        reader.issue(f"{path}.id", "id", "Use lowercase ASCII letters/digits separated by hyphens.")
        identifier = None
    elif len(identifier) > 64:
        reader.issue(f"{path}.id", "id", "Use at most 64 characters.")
        identifier = None
    reference = data.get("path")
    match = None
    if isinstance(reference, str) and reference.startswith(f"{ARTWORK_DIRECTORY}/"):
        match = ARTWORK_NAME.fullmatch(reference.removeprefix(f"{ARTWORK_DIRECTORY}/"))
    if match is None:
        reader.issue(
            f"{path}.path",
            "path",
            f"Expected an imported file: {ARTWORK_DIRECTORY}/<name>-<12 hex>.png or .jpg. "
            "Import artwork with `puzzlepress coloring import` or Studio.",
        )
    digest = data.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        reader.issue(f"{path}.sha256", "sha256", "Expected 64 lowercase hexadecimal digits.")
        digest = None
    elif match is not None and not digest.startswith(match["sha12"]):
        reader.issue(
            f"{path}.sha256",
            "sha256_mismatch",
            "The digest does not match the file name; the path and digest name different files.",
        )
    title = _title(reader, data.get("title"), f"{path}.title")
    adjustments = _adjustments(reader, data.get("adjustments"), f"{path}.adjustments")
    if identifier is None or match is None or digest is None:
        return None
    return Artwork(identifier, str(reference), digest, title, adjustments)


def _divider(reader: _Reader, raw: object, path: str) -> ColoringDivider | None:
    data = reader.mapping(raw, path, {"title", "text"})
    if not isinstance(raw, dict):
        return None
    title = _title(reader, data.get("title"), f"{path}.title")
    if title is None and "title" not in data:
        reader.issue(f"{path}.title", "required", "Give the divider page a title.")
    text = data.get("text")
    if text is not None and (
        not isinstance(text, str)
        or not text.strip()
        or len(text.strip()) > MAX_DIVIDER_TEXT
        or any((ord(c) < 32 and c != "\n") or 0xD800 <= ord(c) <= 0xDFFF for c in text)
    ):
        reader.issue(
            f"{path}.text",
            "text",
            f"Expected 1..{MAX_DIVIDER_TEXT} characters of plain text; line breaks are allowed.",
        )
        text = None
    if title is None:
        return None
    return ColoringDivider(title, text.strip() if isinstance(text, str) else None)


def validate_coloring(value: object) -> tuple[ColoringBook | None, tuple[ValidationIssue, ...]]:
    reader = _Reader()
    path = "coloring"
    root = reader.mapping(value, path, {"version", "artwork", "pages", "layout"})
    if not isinstance(value, dict):
        return None, tuple(reader.issues)
    version = root.get("version")
    if type(version) is not int or version != COLORING_VERSION:
        reader.issue(
            f"{path}.version",
            "unsupported_version",
            f"Unsupported coloring version: {version!r}. Supported versions: {COLORING_VERSION}.",
        )
        return None, tuple(reader.issues)
    artwork: list[Artwork] = []
    raw_artwork = _list(reader, root.get("artwork"), f"{path}.artwork", MAX_ARTWORK)
    for index, raw in enumerate(raw_artwork):
        item = _artwork(reader, raw, f"{path}.artwork.{index}")
        if item is not None:
            artwork.append(item)
    reader.unique([item.id for item in artwork], f"{path}.artwork")
    known = {item.id for item in artwork}
    pages: list[ColoringPage] = []
    for index, raw in enumerate(_list(reader, root.get("pages"), f"{path}.pages", MAX_PAGES)):
        page_path = f"{path}.pages.{index}"
        if isinstance(raw, dict) and "divider" in raw:
            reader.mapping(raw, page_path, {"divider"})
            divider = _divider(reader, raw["divider"], f"{page_path}.divider")
            if divider is not None:
                pages.append(ColoringPage(divider=divider))
            continue
        data = reader.mapping(raw, page_path, {"artwork", "placement"})
        reference = data.get("artwork")
        placement = _placement(reader, data.get("placement"), f"{page_path}.placement")
        if not isinstance(reference, str) or not reference:
            reader.issue(
                f"{page_path}.artwork",
                "required",
                "Name the artwork for this page, or make it a divider: {divider: {title: ...}}.",
            )
        elif reference not in known:
            reader.issue(
                f"{page_path}.artwork",
                "unknown_artwork",
                f"No artwork has the ID {reference!r}.",
            )
        else:
            pages.append(ColoringPage(reference, placement=placement))
    layout_raw = root.get("layout")
    layout = ColoringLayout()
    if layout_raw is not None:
        data = reader.mapping(layout_raw, f"{path}.layout", {"blank_reverse", "border"})
        border = data.get("border", Border.NONE.value)
        if border not in {item.value for item in Border}:
            reader.issue(
                f"{path}.layout.border",
                "choice",
                "Expected one of: " + ", ".join(item.value for item in Border) + ".",
            )
            border = Border.NONE.value
        layout = ColoringLayout(
            _flag(reader, data.get("blank_reverse"), f"{path}.layout.blank_reverse", True),
            Border(str(border)),
        )
    if reader.issues:
        return None, tuple(reader.issues)
    return ColoringBook(COLORING_VERSION, tuple(artwork), tuple(pages), layout), ()


def validate_adjustments(
    value: object, path: str = "adjustments"
) -> tuple[Adjustments | None, tuple[ValidationIssue, ...]]:
    """Adjustment settings from a CLI or Studio request, with the schema's own rules."""
    reader = _Reader()
    adjustments = _adjustments(reader, value, path)
    return (None if reader.issues else adjustments), tuple(reader.issues)
