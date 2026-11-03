"""Optional cover section, versions 1, 2 and 3. Collects independent issues; never repairs."""

import math
import re
from typing import TypeVar

from .composition_validation import _body
from .content_validation import _Reader
from .cover_config import (
    ASSET_DIRECTORY,
    CROP_DECIMALS,
    FONT_DIRECTORY,
    LETTER_SPACING,
    LINE_SPACING,
    MAX_BACK_TEXT,
    MAX_EXTRA_LAYERS,
    MAX_FONTS,
    MAX_LAYER_TEXT,
    MAX_OFFSET,
    MAX_TEXT_SIZE,
    MAX_ZOOM,
    METADATA_ROLES,
    MIN_TEXT_SIZE,
    SUPPORTED_VERSIONS,
    CoverConfig,
    CoverFont,
    CoverImage,
    CoverLayoutKind,
    CoverStyle,
    CoverType,
    Crop,
    ExtraLayer,
    LayerAlign,
    LayerPanel,
    Legibility,
    LetterCase,
    SpineText,
    TextAlign,
    TextLayer,
    TextRole,
    TextTone,
    TitlePosition,
    Watermark,
    WatermarkPosition,
)
from .cover_design import Element, GradientDirection, Region
from .cover_richtext import is_rich, read_rich
from .errors import ValidationIssue

# A portable asset reference: one level below cover-assets, lowercase, no traversal.
ASSET_PATH = re.compile(rf"{ASSET_DIRECTORY}/[a-z0-9]+(?:-[a-z0-9]+)*\.(?:jpg|png)")
MAX_ASSET_PATH = 160
SHA256 = re.compile(r"[0-9a-f]{64}")
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
FONT_PATH = re.compile(rf"{FONT_DIRECTORY}/[a-z0-9]+(?:-[a-z0-9]+)*\.(?:ttf|otf)")
LAYER_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Bundled cover faces (cover.fonts.CoverFace values); imported font ids must differ.
BUNDLED_FACES = ("sans", "sans-bold", "sans-italic", "serif-display", "serif", "serif-italic")
Choice = TypeVar(
    "Choice",
    CoverLayoutKind,
    CoverStyle,
    TitlePosition,
    TextAlign,
    TextTone,
    Legibility,
    SpineText,
    LayerAlign,
    LayerPanel,
    LetterCase,
    GradientDirection,
    Region,
    WatermarkPosition,
)
V2_FIELDS = {"text", "extra", "fonts", "watermark"}
V3_FIELDS = {"regions", "elements"}
# Version 1/2 fields that version 3 replaces with regions and elements.
V3_REPLACED = {"layout", "image", "crop", "background"}
LAYER_FIELDS = {
    "visible",
    "text",
    "font",
    "size",
    "color",
    "align",
    "line_spacing",
    "letter_spacing",
    "case",
    "offset",
}
FIELDS = {
    *V2_FIELDS,
    *V3_FIELDS,
    "version",
    "layout",
    "image",
    "crop",
    "type",
    "legibility",
    "background",
    "spine_text",
    "back_text",
}


def validate_cover(
    value: object, has_composition: bool
) -> tuple[CoverConfig | None, tuple[ValidationIssue, ...]]:
    """Validate the cover section; `has_composition` states whether one is declared."""
    reader = _Reader()
    path = "cover"
    data = reader.mapping(value, path, FIELDS)
    if not isinstance(value, dict):
        return None, tuple(reader.issues)
    if not has_composition:
        reader.issue(
            path,
            "requires_composition",
            "A cover requires a book composition: its spine is sized by the built interior.",
        )
    version = data.get("version")
    if type(version) is not int or version not in SUPPORTED_VERSIONS:
        supported = ", ".join(str(v) for v in SUPPORTED_VERSIONS)
        reader.issue(
            f"{path}.version",
            "unsupported_version",
            f"Cover version {version!r} is not supported. Supported versions: {supported}.",
        )
        return None, tuple(reader.issues)
    if version == 1:
        for key in sorted(V2_FIELDS & set(data)):
            reader.issue(
                f"{path}.{key}",
                "requires_version_2",
                f"Cover version 1 has no {key!r}; set version: 2 to use text layers and fonts.",
            )
    if version < 3:
        for key in sorted(V3_FIELDS & set(data)):
            reader.issue(
                f"{path}.{key}",
                "requires_version_3",
                f"Cover version {version} has no {key!r}; convert the cover to a version 3 "
                "region design to use regions and elements.",
            )
    else:
        for key in sorted(V3_REPLACED & set(data)):
            reader.issue(
                f"{path}.{key}",
                "not_in_version_3",
                f"Cover version 3 has no {key!r}: photographs are elements and each region "
                "has its own background.",
            )
    designed = version >= 3
    image = (
        None if designed else _image(reader, data.get("image"), f"{path}.image", "image" in data)
    )
    crop = _crop(reader, {} if designed else data.get("crop", {}), f"{path}.crop")
    kind = _choice(
        reader,
        "full_wrap" if designed else data.get("layout", "full_wrap"),
        f"{path}.layout",
        CoverLayoutKind,
    )
    cover_type = _type(reader, data.get("type", {}), f"{path}.type")
    legibility = _choice(reader, data.get("legibility", "shade"), f"{path}.legibility", Legibility)
    spine = _choice(reader, data.get("spine_text", "auto"), f"{path}.spine_text", SpineText)
    background = (
        CoverConfig.background if designed else data.get("background", CoverConfig.background)
    )
    if not isinstance(background, str) or not HEX_COLOR.fullmatch(background):
        reader.issue(f"{path}.background", "color", "Use a #RRGGBB sRGB color.")
        background = CoverConfig.background
    fonts = _fonts(reader, data.get("fonts", []), f"{path}.fonts")
    font_ids = {font.id for font in fonts}
    back_text = None
    back_rich = None
    if is_rich(data.get("back_text")):
        if version < 2:
            reader.issue(
                f"{path}.back_text",
                "requires_version_2",
                "Cover version 1 has plain back text only; set version: 2 to format it.",
            )
        back_rich = read_rich(
            reader, data["back_text"], f"{path}.back_text", font_ids, MAX_BACK_TEXT
        )
        back_text = back_rich.plain() if back_rich is not None else None
    elif "back_text" in data:
        back_text = _body(reader, data["back_text"], f"{path}.back_text")
        if len(back_text) > MAX_BACK_TEXT:
            reader.issue(
                f"{path}.back_text", "text", f"Back-cover text is limited to {MAX_BACK_TEXT}."
            )
    text = _text_layers(reader, data.get("text", {}), f"{path}.text", font_ids)
    extra = _extra_layers(reader, data.get("extra", []), f"{path}.extra", font_ids)
    watermark = (
        _watermark(reader, data["watermark"], f"{path}.watermark") if "watermark" in data else None
    )
    regions = None
    elements: tuple[Element, ...] = ()
    if designed:
        from .cover_design_validation import read_elements, read_regions

        if "regions" not in data:
            reader.issue(f"{path}.regions", "required", "State the three region backgrounds.")
        else:
            regions = read_regions(reader, data["regions"], f"{path}.regions")
        elements = read_elements(reader, data.get("elements", []), f"{path}.elements", font_ids)
    if reader.issues or (image is None and not designed) or (designed and regions is None):
        return None, tuple(reader.issues)
    return (
        CoverConfig(
            image=image,
            layout=kind,
            crop=crop,
            type=cover_type,
            legibility=legibility,
            background=background.lower(),
            spine_text=spine,
            back_text=back_text,
            version=version,
            text=text,
            extra=extra,
            fonts=fonts,
            regions=regions,
            elements=elements,
            back_rich=back_rich,
            watermark=watermark,
        ),
        (),
    )


def _choice(reader: _Reader, value: object, path: str, enum: type[Choice]) -> Choice:
    names = [member.value for member in enum]
    if not isinstance(value, str) or value not in names:
        reader.issue(path, "choice", f"Use one of: {', '.join(names)}.")
        return next(iter(enum))
    return enum(value)


def _image(reader: _Reader, raw: object, path: str, present: bool) -> CoverImage | None:
    if not present:
        reader.issue(path, "required", "Choose a photograph from cover-assets.")
        return None
    data = reader.mapping(raw, path, {"path", "sha256"})
    asset = data.get("path")
    digest = data.get("sha256")
    valid = True
    if not isinstance(asset, str) or len(asset) > MAX_ASSET_PATH or not ASSET_PATH.fullmatch(asset):
        reader.issue(
            f"{path}.path",
            "asset_path",
            f"Use {ASSET_DIRECTORY}/<lowercase-name>.jpg or .png inside the project.",
        )
        valid = False
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        reader.issue(f"{path}.sha256", "digest", "Expected the photo's 64-character SHA-256.")
        valid = False
    if not valid:
        return None
    assert isinstance(asset, str) and isinstance(digest, str)
    return CoverImage(asset, digest)


def _number(reader: _Reader, raw: object, path: str, low: float, high: float, code: str) -> float:
    if not isinstance(raw, int | float) or isinstance(raw, bool) or not math.isfinite(raw):
        reader.issue(path, "crop_invalid", "Expected a number.")
        return low
    value = round(float(raw), CROP_DECIMALS)
    if not low <= value <= high:
        reader.issue(path, code, f"Expected a value from {low:g} to {high:g}.")
        return low
    return value


def _crop(reader: _Reader, raw: object, path: str) -> Crop:
    data = reader.mapping(raw, path, {"x", "y", "zoom"})
    return Crop(
        _number(reader, data.get("x", 0.5), f"{path}.x", 0.0, 1.0, "crop_out_of_bounds"),
        _number(reader, data.get("y", 0.5), f"{path}.y", 0.0, 1.0, "crop_out_of_bounds"),
        _number(reader, data.get("zoom", 1.0), f"{path}.zoom", 1.0, MAX_ZOOM, "crop_invalid"),
    )


def _type(reader: _Reader, raw: object, path: str) -> CoverType:
    data = reader.mapping(raw, path, {"style", "position", "align", "tone"})
    return CoverType(
        _choice(reader, data.get("style", "editorial"), f"{path}.style", CoverStyle),
        _choice(reader, data.get("position", "top"), f"{path}.position", TitlePosition),
        _choice(reader, data.get("align", "center"), f"{path}.align", TextAlign),
        _choice(reader, data.get("tone", "light"), f"{path}.tone", TextTone),
    )


def _bounded(
    reader: _Reader, raw: object, path: str, low: float, high: float, decimals: int = 2
) -> float | None:
    if not isinstance(raw, int | float) or isinstance(raw, bool) or not math.isfinite(raw):
        reader.issue(path, "number", "Expected a number.")
        return None
    value = round(float(raw), decimals)
    if not low <= value <= high:
        reader.issue(path, "range", f"Expected a value from {low:g} to {high:g}.")
        return None
    return value


def _layer_text(reader: _Reader, raw: object, path: str) -> str | None:
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or len(raw) > MAX_LAYER_TEXT
        or any(0xD800 <= ord(c) <= 0xDFFF for c in raw)
        or any((ord(c) < 32 and c != "\n") or ord(c) == 127 for c in raw)
    ):
        reader.issue(
            path,
            "text",
            f"Expected 1..{MAX_LAYER_TEXT} characters of plain text; line breaks are allowed.",
        )
        return None
    return raw.strip()


def _layer(
    reader: _Reader,
    raw: object,
    path: str,
    font_ids: set[str],
    fields: set[str] = LAYER_FIELDS,
) -> TextLayer:
    data = reader.mapping(raw, path, fields)
    visible = data.get("visible", True)
    if not isinstance(visible, bool):
        reader.issue(f"{path}.visible", "type", "Expected true or false.")
        visible = True
    text = _layer_text(reader, data["text"], f"{path}.text") if "text" in data else None
    font: str | None = None
    if "font" in data:
        value = data["font"]
        if not isinstance(value, str) or (value not in BUNDLED_FACES and value not in font_ids):
            reader.issue(
                f"{path}.font",
                "unknown_font",
                f"Use a bundled face ({', '.join(BUNDLED_FACES)}) or the id of a font in "
                "cover.fonts.",
            )
        else:
            font = value
    size = (
        _bounded(reader, data["size"], f"{path}.size", MIN_TEXT_SIZE, MAX_TEXT_SIZE)
        if "size" in data
        else None
    )
    color: str | None = None
    if "color" in data:
        value = data["color"]
        if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
            reader.issue(f"{path}.color", "color", "Use a #RRGGBB sRGB color.")
        else:
            color = value.lower()
    align = _choice(reader, data["align"], f"{path}.align", LayerAlign) if "align" in data else None
    case = _choice(reader, data["case"], f"{path}.case", LetterCase) if "case" in data else None
    line = (
        _bounded(reader, data["line_spacing"], f"{path}.line_spacing", *LINE_SPACING)
        if "line_spacing" in data
        else None
    )
    letter = (
        _bounded(reader, data["letter_spacing"], f"{path}.letter_spacing", *LETTER_SPACING)
        if "letter_spacing" in data
        else None
    )
    offset = (0.0, 0.0)
    if "offset" in data:
        point = reader.mapping(data["offset"], f"{path}.offset", {"x", "y"})
        x = _bounded(reader, point.get("x", 0), f"{path}.offset.x", -MAX_OFFSET, MAX_OFFSET)
        y = _bounded(reader, point.get("y", 0), f"{path}.offset.y", -MAX_OFFSET, MAX_OFFSET)
        offset = (x or 0.0, y or 0.0)
    return TextLayer(visible, text, font, size, color, align, line, letter, case, offset)


def _text_layers(
    reader: _Reader, raw: object, path: str, font_ids: set[str]
) -> tuple[tuple[TextRole, TextLayer], ...]:
    data = reader.mapping(raw, path, {role.value for role in TextRole})
    layers: list[tuple[TextRole, TextLayer]] = []
    for role in TextRole:  # Book order, independent of the authored key order.
        if role.value not in data:
            continue
        layer_path = f"{path}.{role.value}"
        fields = LAYER_FIELDS if role in METADATA_ROLES else LAYER_FIELDS - {"text"}
        layer = _layer(reader, data[role.value], layer_path, font_ids, fields)
        if not layer.is_default:
            layers.append((role, layer))
    return tuple(layers)


def _extra_layers(
    reader: _Reader, raw: object, path: str, font_ids: set[str]
) -> tuple[ExtraLayer, ...]:
    layers: list[ExtraLayer] = []
    seen: set[str] = set()
    for index, entry in enumerate(reader.sequence(raw, path, MAX_EXTRA_LAYERS, 0)):
        item = f"{path}.{index}"
        data = reader.mapping(entry, item, LAYER_FIELDS | {"id", "panel"})
        layer_id = data.get("id")
        if not isinstance(layer_id, str) or len(layer_id) > 40 or not LAYER_ID.fullmatch(layer_id):
            reader.issue(f"{item}.id", "id", "Use 1..40 lowercase letters, digits and hyphens.")
            layer_id = ""
        elif layer_id in seen:
            reader.issue(f"{item}.id", "duplicate", f"Layer id {layer_id!r} is used twice.")
        seen.add(layer_id)
        panel = _choice(reader, data.get("panel"), f"{item}.panel", LayerPanel)
        if "text" not in data:
            reader.issue(f"{item}.text", "required", "An extra layer needs its text.")
        overrides = {k: v for k, v in data.items() if k not in ("id", "panel")}
        layer = _layer(reader, overrides, item, font_ids)
        layers.append(ExtraLayer(layer_id, panel, layer.text or "", layer))
    return tuple(layers)


def _provenance_text(reader: _Reader, raw: object, path: str) -> str | None:
    if raw is None:
        return None
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or len(raw) > 300
        or any(ord(c) < 32 or ord(c) == 127 for c in raw)
    ):
        reader.issue(path, "text", "Expected 1..300 characters on one line, or null (unknown).")
        return None
    return raw.strip()


def _fonts(reader: _Reader, raw: object, path: str) -> tuple[CoverFont, ...]:
    fonts: list[CoverFont] = []
    seen: set[str] = set()
    for index, entry in enumerate(reader.sequence(raw, path, MAX_FONTS, 0)):
        item = f"{path}.{index}"
        data = reader.mapping(entry, item, {"id", "path", "sha256", "license", "source"})
        font_id = data.get("id")
        if (
            not isinstance(font_id, str)
            or len(font_id) > 40
            or not LAYER_ID.fullmatch(font_id)
            or font_id in BUNDLED_FACES
        ):
            reader.issue(
                f"{item}.id",
                "id",
                "Use 1..40 lowercase letters, digits and hyphens, not a bundled face name.",
            )
            continue
        if font_id in seen:
            reader.issue(f"{item}.id", "duplicate", f"Font id {font_id!r} is used twice.")
        seen.add(font_id)
        asset = data.get("path")
        digest = data.get("sha256")
        if (
            not isinstance(asset, str)
            or len(asset) > MAX_ASSET_PATH
            or not FONT_PATH.fullmatch(asset)
        ):
            reader.issue(
                f"{item}.path",
                "asset_path",
                f"Use {FONT_DIRECTORY}/<lowercase-name>.ttf or .otf inside the project.",
            )
            continue
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            reader.issue(f"{item}.sha256", "digest", "Expected the font's 64-character SHA-256.")
            continue
        fonts.append(
            CoverFont(
                font_id,
                asset,
                digest,
                _provenance_text(reader, data.get("license"), f"{item}.license"),
                _provenance_text(reader, data.get("source"), f"{item}.source"),
            )
        )
    return tuple(fonts)


WATERMARK_FIELDS = {"enabled", "text", "opacity", "position", "scale", "margin", "shadow", "color"}
MAX_WATERMARK_TEXT = 60
OPACITY = (0.05, 1.0, "range")
SCALE = (0.05, 0.8, "range")
MARGIN = (9.0, 216.0, "range")  # Points from the front trim edges; KDP safe is 9.


def _watermark(reader: _Reader, raw: object, path: str) -> Watermark | None:
    data = reader.mapping(raw, path, WATERMARK_FIELDS)
    if not isinstance(raw, dict):
        return None
    default = Watermark()
    flags = {}
    for key in ("enabled", "shadow"):
        value = data.get(key, getattr(default, key))
        if not isinstance(value, bool):
            reader.issue(f"{path}.{key}", "type", f"Use true or false for {key}.")
            value = getattr(default, key)
        flags[key] = value
    text = data.get("text", "")
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_WATERMARK_TEXT:
        reader.issue(
            f"{path}.text",
            "text",
            f"State the watermark text: 1..{MAX_WATERMARK_TEXT} characters on one line.",
        )
        text = ""
    elif any(not ch.isprintable() for ch in text):
        reader.issue(f"{path}.text", "text", "The watermark text must be one printable line.")
    color = data.get("color", default.color)
    if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
        reader.issue(f"{path}.color", "color", "Use a #RRGGBB sRGB color.")
        color = default.color
    position = _choice(
        reader, data.get("position", default.position.value), f"{path}.position", WatermarkPosition
    )
    return Watermark(
        enabled=flags["enabled"],
        text=text.strip() if isinstance(text, str) else "",
        opacity=_number(reader, data.get("opacity", default.opacity), f"{path}.opacity", *OPACITY),
        position=position,
        scale=_number(reader, data.get("scale", default.scale), f"{path}.scale", *SCALE),
        margin=_number(reader, data.get("margin", default.margin), f"{path}.margin", *MARGIN),
        shadow=flags["shadow"],
        color=color.lower(),
    )
