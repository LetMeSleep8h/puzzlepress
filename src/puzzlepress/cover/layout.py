"""Cover layout engine: semantic configuration plus interior facts to CoverLayout.

Pure apart from font metrics. It decides the photo window, every text position,
spine eligibility and the legibility treatment. It never moves text outside its
safe area, squeezes type below its preset minimum or invents copy: front text is
the book's title, subtitle and author; back text is only what the cover authors.

Version 2 overrides (font, size, color, alignment, spacing, visibility, display
text, offsets and extra layers) are applied here and nowhere else; with none,
every position is computed exactly as in version 1.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from ..cover_config import (
    CoverConfig,
    CoverLayoutKind,
    CoverStyle,
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
    hex_rgb,
)
from ..cover_design import LineElement, PhotoElement, Region, ShapeElement, TextBoxElement
from ..cover_richtext import BlockAlign, RichText
from ..interior.issues import LayoutIssue
from ..interior.model import Anchor, Box
from ..interior.spec import KDP_COVER, inches
from ..models import Project
from .assets import PhotoInfo
from .crop import crop_window, image_placement
from .design import PlacedPhoto, design_warnings, element_role, flatten, page_box, region_fills
from .design import photo as design_photo
from .design import shape as design_shape
from .font_assets import NO_FONTS, CoverFonts
from .fonts import CoverFace, is_bundled, metrics, missing_characters, text_width
from .geometry import CoverGeometry
from .issues import CoverError
from .model import (
    RGB,
    CoverLayout,
    CoverPhoto,
    CoverText,
    CoverTextBox,
    Fill,
    ImageResolution,
    ShadeBand,
    SpineStatus,
)
from .richtext import Base, layout_rich
from .watermark import attach, place_watermark

LIGHT: RGB = (1.0, 1.0, 1.0)
DARK: RGB = (0.106, 0.118, 0.11)
TITLE_LINES = 3
SUBTITLE_LINES = 3
AUTHOR_LINES = 2
EXPLICIT_LINES = 6  # Line limit for a layer set at an author-chosen size.
TITLE_STEP = 2.0
BACK_MEASURE = inches(5.5)
FRONT_GAP = inches(0.25)  # Minimum space between the title block and the author.
BACK_GAP = inches(0.25)  # Back text keeps this far above the barcode area and imprint.
PANEL_PAD = inches(0.3)
SHADE_PAD = inches(0.35)
SHADE_FADE = inches(1.5)
EDGE_SNAP = inches(1.5)  # Shade reaches the media edge when text is this close to it.
SHADE_STRENGTH = {TextTone.LIGHT: 0.5, TextTone.DARK: 0.55}
SHADE_TOWARD = {TextTone.LIGHT: (0, 0, 0), TextTone.DARK: (255, 255, 255)}


@dataclass(frozen=True)
class Preset:
    title_face: CoverFace
    title_max: float
    title_min: float
    title_pitch: float  # Line pitch as a multiple of size (never tighter than the face).
    upper: bool  # Title, author and spine text in capitals.
    subtitle_face: CoverFace
    subtitle_size: float
    author_face: CoverFace
    author_size: float
    spine_face: CoverFace
    spine_max: float
    body_face: CoverFace
    body_size: float
    body_pitch: float
    imprint_face: CoverFace
    imprint_size: float


PRESETS = {
    CoverStyle.EDITORIAL: Preset(
        CoverFace.SERIF_DISPLAY, 62, 36, 1.02, False,
        CoverFace.SERIF_ITALIC, 20,
        CoverFace.SERIF, 17,
        CoverFace.SERIF, 14,
        CoverFace.SERIF, 12.5, 1.42,
        CoverFace.SERIF_ITALIC, 10.5,
    ),
    CoverStyle.BOLD: Preset(
        CoverFace.SANS_BOLD, 60, 34, 1.0, True,
        CoverFace.SANS, 17,
        CoverFace.SANS_BOLD, 14,
        CoverFace.SANS_BOLD, 13,
        CoverFace.SANS, 11.5, 1.5,
        CoverFace.SANS, 9.5,
    ),
    CoverStyle.MINIMAL: Preset(
        CoverFace.SANS, 42, 28, 1.1, False,
        CoverFace.SANS, 14,
        CoverFace.SANS, 12.5,
        CoverFace.SANS, 12,
        CoverFace.SANS, 11, 1.55,
        CoverFace.SANS, 9,
    ),
}  # fmt: skip


@dataclass(frozen=True)
class CoverCopy:
    """Every word a cover prints: book metadata plus the authored back text."""

    title: str
    subtitle: str | None
    author: str | None
    imprint: str | None
    back_text: str | None

    @classmethod
    def from_project(cls, project: Project) -> "CoverCopy":
        book, cover = project.book, project.cover
        return cls(
            book.title,
            book.subtitle,
            book.author,
            book.imprint,
            cover.back_text if cover else None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "author": self.author,
            "imprint": self.imprint,
            "back_text": self.back_text,
        }


def same_words(first: str, second: str) -> bool:
    """Equal apart from line breaks, spacing and letter case (presets set capitals)."""
    return " ".join(first.split()).casefold() == " ".join(second.split()).casefold()


def cover_display(config: CoverConfig, copy: CoverCopy) -> dict[str, str | None]:
    """The words each book-metadata role prints on the cover, before letter case.

    None means the layer is hidden or has no text. Book metadata is never changed:
    a display override only replaces what the cover prints.
    """
    values = {
        TextRole.TITLE: copy.title,
        TextRole.SUBTITLE: copy.subtitle,
        TextRole.AUTHOR: copy.author,
        TextRole.IMPRINT: copy.imprint,
    }
    display: dict[str, str | None] = {}
    for role, value in values.items():
        layer = config.layer(role)
        display[role.value] = (
            None if not layer.visible else layer.text if layer.text is not None else value
        )
    return display


def _fail(
    code: str, message: str, region: str, actual: str | None = None, required: str | None = None
) -> CoverError:
    return CoverError(
        "layout", (LayoutIssue(code, message, region=region, actual=actual, required=required),)
    )


def _check_glyphs(text: str, face: str, region: str) -> None:
    missing = missing_characters(text, face)
    if missing:
        listed = ", ".join(f"U+{ord(c):04X}" for c in missing)
        raise _fail(
            "unsupported_character",
            f"The cover font cannot draw: {listed}.",
            region,
            actual=listed,
            required="Latin-1 text" if is_bundled(face) else "characters the chosen font contains",
        )


def wrap(
    text: str, face: str, size: float, measure: float, tracking: float = 0.0
) -> list[str] | None:
    """Greedy wrap keeping authored line breaks; None if a word is wider than the measure."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = [word for word in paragraph.split(" ") if word]
        current = ""
        for word in words:
            if text_width(word, face, size, tracking) > measure:
                return None
            candidate = f"{current} {word}" if current else word
            if current and text_width(candidate, face, size, tracking) > measure:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


@dataclass(frozen=True)
class _Style:
    """How one layer is set: the preset's choices with the author's overrides applied."""

    role: str
    face: str
    size: float | None  # None: the preset decides (titles step down to fit).
    pitch: float
    upper: bool
    color: RGB
    tracking: float
    align: LayerAlign
    offset: tuple[float, float]

    def text(self, value: str) -> str:
        return value.upper() if self.upper else value


def _face(layer: TextLayer, default: str, fonts: CoverFonts) -> str:
    if layer.font is None:
        return default
    return layer.font if is_bundled(layer.font) else fonts.key(layer.font)


def _style(
    role: str,
    layer: TextLayer,
    fonts: CoverFonts,
    face: str,
    size: float | None,
    pitch: float,
    upper: bool,
    color: RGB,
    align: LayerAlign,
) -> _Style:
    return _Style(
        role,
        _face(layer, face, fonts),
        layer.size if layer.size is not None else size,
        layer.line_spacing if layer.line_spacing is not None else pitch,
        upper if layer.case is None else layer.case is LetterCase.UPPER,
        hex_rgb(layer.color) if layer.color is not None else color,
        layer.letter_spacing or 0.0,
        layer.align if layer.align is not None else align,
        layer.offset,
    )


def _default_align(config: CoverConfig) -> LayerAlign:
    return LayerAlign.CENTER if config.type.align is TextAlign.CENTER else LayerAlign.LEFT


@dataclass(frozen=True)
class _Line:
    text: str
    style: _Style
    size: float
    gap_before: float  # Space between this line box and the previous one.


def _group(lines: list[str], style: _Style, size: float, gap: float) -> list[_Line]:
    m = metrics(style.face)
    within = max(0.0, (style.pitch - m.ascent - m.descent) * size)
    return [
        _Line(text, style, size, gap if index == 0 else within) for index, text in enumerate(lines)
    ]


def _height(lines: list[_Line]) -> float:
    total = 0.0
    for index, line in enumerate(lines):
        m = metrics(line.style.face)
        total += (m.ascent + m.descent) * line.size + (line.gap_before if index else 0.0)
    return total


def _anchor(area: Box, align: LayerAlign) -> tuple[float, Anchor]:
    if align is LayerAlign.CENTER:
        return area.x + area.width / 2, Anchor.MIDDLE
    if align is LayerAlign.RIGHT:
        return area.right, Anchor.END
    return area.x, Anchor.START


def _place(lines: list[_Line], top: float, area: Box) -> list[CoverText]:
    placed: list[CoverText] = []
    cursor = top
    for index, line in enumerate(lines):
        m = metrics(line.style.face)
        if index:
            cursor -= line.gap_before
        baseline = cursor - m.ascent * line.size
        cursor = baseline - m.descent * line.size
        if line.text:
            x, anchor = _anchor(area, line.style.align)
            placed.append(_text(line.style, line.text, line.size, x, baseline, anchor))
    return placed


def _text(
    style: _Style, text: str, size: float, x: float, baseline: float, anchor: Anchor
) -> CoverText:
    width = text_width(text, style.face, size, style.tracking)
    m = metrics(style.face)
    left = {Anchor.START: x, Anchor.MIDDLE: x - width / 2, Anchor.END: x - width}[anchor]
    bounds = Box(left, baseline - m.descent * size, width, (m.ascent + m.descent) * size)
    return CoverText(
        style.role,
        text,
        style.face,
        size,
        (x, baseline),
        anchor,
        False,
        bounds,
        style.color,
        style.tracking,
    )


def _moved(box: Box, offset: tuple[float, float]) -> Box:
    if offset == (0.0, 0.0):
        return box
    return Box(box.x + offset[0], box.y + offset[1], box.width, box.height)


def _shift(texts: list[CoverText], offset: tuple[float, float]) -> list[CoverText]:
    if offset == (0.0, 0.0):
        return texts
    dx, dy = offset
    return [
        replace(t, origin=(t.origin[0] + dx, t.origin[1] + dy), bounds=_moved(t.bounds, offset))
        for t in texts
    ]


def _union(texts: list[CoverText], area: Box) -> Box:
    """A layer's vertical extent across the full width of its area."""
    low = min(t.bounds.y for t in texts)
    high = max(t.bounds.top for t in texts)
    return Box(area.x, low, area.width, high - low)


def _spine_text(
    role: str,
    text: str,
    face: str,
    size: float,
    x: float,
    y: float,
    anchor: Anchor,
    color: RGB,
) -> CoverText:
    """A line turned 90 degrees clockwise; `x` is the baseline, `y` the anchor point."""
    length = text_width(text, face, size)
    m = metrics(face)
    start = y - length if anchor is Anchor.START else y
    bounds = Box(x - m.descent * size, start, (m.ascent + m.descent) * size, length)
    return CoverText(role, text, face, size, (x, y), anchor, True, bounds, color)


def _set(
    text: str, style: _Style, measure: float, region: str, max_lines: int
) -> tuple[list[str], float]:
    """Wrap a layer at its explicit size; overflow is an expected failure."""
    assert style.size is not None
    _check_glyphs(text, style.face, region)
    lines = wrap(text, style.face, style.size, measure, style.tracking)
    if lines is None or len(lines) > max_lines:
        raise _fail(
            "text_overflow",
            f"{region.removeprefix('cover.').replace('_', ' ').capitalize()} does not fit "
            f"{max_lines} lines of its panel at {style.size:g} pt.",
            region,
            required=f"{max_lines} lines",
        )
    return lines, style.size


@dataclass(frozen=True)
class _Group:
    """Text printed over the photograph, for shading or panels: role, x range, bounds."""

    role: str
    x0: float
    x1: float
    box: Box


def _front(
    copy: CoverCopy,
    preset: Preset,
    config: CoverConfig,
    area: Box,
    color: RGB,
    fonts: CoverFonts,
) -> tuple[list[CoverText], list[tuple[str, Box]]]:
    """Front texts and the boxes their legibility treatment covers."""
    align = _default_align(config)
    title_layer = config.layer(TextRole.TITLE)
    sub_layer = config.layer(TextRole.SUBTITLE)
    author_layer = config.layer(TextRole.AUTHOR)
    title = _style(
        "title",
        title_layer,
        fonts,
        preset.title_face,
        None,
        preset.title_pitch,
        preset.upper,
        color,
        align,
    )
    block: list[_Line] = []
    size = preset.title_max
    if title_layer.visible:
        text = title.text(title_layer.text if title_layer.text is not None else copy.title)
        if title.size is not None:
            lines, size = _set(text, title, area.width, "cover.title", EXPLICIT_LINES)
        else:
            _check_glyphs(text, title.face, "cover.title")
            title_lines: list[str] | None = None
            while size >= preset.title_min - 1e-9:
                title_lines = wrap(text, title.face, size, area.width, title.tracking)
                if title_lines is not None and len(title_lines) <= TITLE_LINES:
                    break
                title_lines = None
                size -= TITLE_STEP
            if title_lines is None:
                raise _fail(
                    "text_overflow",
                    f"The title does not fit {TITLE_LINES} lines of the front cover at "
                    f"{preset.title_min:g} pt or larger.",
                    "cover.title",
                    required=f"{TITLE_LINES} lines",
                )
            lines = title_lines
        block = _group(lines, title, size, 0.0)
    subtitle_text = sub_layer.text if sub_layer.text is not None else copy.subtitle
    subtitle = _style(
        "subtitle",
        sub_layer,
        fonts,
        preset.subtitle_face,
        preset.subtitle_size,
        1.3,
        False,
        color,
        align,
    )
    if subtitle_text and sub_layer.visible:
        limit = SUBTITLE_LINES if sub_layer.size is None else EXPLICIT_LINES
        lines, sub_size = _set(subtitle_text, subtitle, area.width, "cover.subtitle", limit)
        block += _group(lines, subtitle, sub_size, 0.45 * size if block else 0.0)
    author: list[_Line] = []
    author_style = _style(
        "author",
        author_layer,
        fonts,
        preset.author_face,
        preset.author_size,
        1.3,
        preset.upper,
        color,
        align,
    )
    author_text = author_layer.text if author_layer.text is not None else copy.author
    if author_text and author_layer.visible:
        limit = AUTHOR_LINES if author_layer.size is None else EXPLICIT_LINES
        name = author_style.text(author_text)
        lines, author_size = _set(name, author_style, area.width, "cover.author", limit)
        author = _group(lines, author_style, author_size, 0.0)
    height, author_height = _height(block), _height(author)
    position = config.type.position
    if position is TitlePosition.BOTTOM:
        top, author_top = area.y + height, area.top
    elif position is TitlePosition.MIDDLE:
        top, author_top = area.y + (area.height + height) / 2, area.y + author_height
    else:
        top, author_top = area.top, area.y + author_height
    title_box = Box(area.x, top - height, area.width, height)
    author_box = Box(area.x, author_top - author_height, area.width, author_height)
    moved = any(layer.offset != (0.0, 0.0) for layer in (title_layer, sub_layer, author_layer))
    if author and block and not moved and title_box.overlaps(_grow(author_box, 0, FRONT_GAP), 0):
        raise _fail(
            "text_overflow",
            "The title block and author do not both fit the front cover.",
            "cover.front",
        )
    placed = _place(block, top, area)
    by_title = _shift([t for t in placed if t.role == "title"], title.offset)
    by_subtitle = _shift([t for t in placed if t.role == "subtitle"], subtitle.offset)
    by_author = _shift(_place(author, author_top, area), author_style.offset)
    boxes: list[tuple[str, Box]] = []
    if block:
        if not by_title or not by_subtitle or title.offset == subtitle.offset:
            shared = title.offset if by_title else subtitle.offset
            boxes.append(("front_title", _moved(title_box, shared)))
        else:
            boxes.append(("front_title", _union(by_title, area)))
            boxes.append(("front_subtitle", _union(by_subtitle, area)))
    if author:
        boxes.append(("front_author", _moved(author_box, author_style.offset)))
    return by_title + by_subtitle + by_author, boxes


def _rich(
    document: RichText,
    style: _Style,
    frame: Box,
    fonts: CoverFonts,
    region: str,
) -> tuple[list[CoverText], float]:
    """A rich text document set from the top of `frame`, inheriting `style`."""
    assert style.size is not None
    base = Base(
        style.face,
        style.size,
        style.color,
        style.pitch,
        style.tracking,
        style.upper,
        BlockAlign(style.align.value),
    )
    keys = {font_id: fonts.key(font_id) for font_id in fonts.by_id}
    return layout_rich(document, base, frame, frame.top, style.role, keys, region)


def _grow(box: Box, dx: float, dy: float) -> Box:
    return Box(box.x - dx, box.y - dy, box.width + 2 * dx, box.height + 2 * dy)


def _spine(
    copy: CoverCopy, preset: Preset, config: CoverConfig, geometry: CoverGeometry, color: RGB
) -> tuple[list[CoverText], SpineStatus]:
    allowed = geometry.spine_text_allowed
    if config.spine_text is SpineText.NONE:
        return [], SpineStatus(allowed, False, "authored", None)
    if not allowed:
        return [], SpineStatus(False, False, "page_count", None)
    safe = geometry.spine_safe
    m = metrics(preset.spine_face)
    across = m.ascent + m.descent
    size = min(preset.spine_max, math.floor(safe.width / across * 2) / 2)
    if size < KDP_COVER.min_font_size:
        return [], SpineStatus(True, False, "spine_too_narrow", None)
    title = copy.title.upper() if preset.upper else copy.title
    author = (copy.author.upper() if preset.upper else copy.author) if copy.author else None
    _check_glyphs(title + (author or ""), preset.spine_face, "cover.spine")
    while True:
        gap = max(2 * size, inches(0.5))
        length = text_width(title, preset.spine_face, size)
        if author:
            length += gap + text_width(author, preset.spine_face, size)
        if length <= safe.height:
            break
        if size - 0.5 < KDP_COVER.min_font_size:
            raise _fail(
                "spine_text_overflow",
                "Spine text does not fit the spine at 7 pt; shorten the title or "
                "set spine_text to none.",
                "cover.spine_text",
                actual=f"{length / 72:.3f} in",
                required=f"at most {safe.height / 72:.3f} in",
            )
        size -= 0.5
    baseline = safe.x + safe.width / 2 - (m.ascent - m.descent) / 2 * size
    texts = [
        _spine_text(
            "spine_title", title, preset.spine_face, size, baseline, safe.top, Anchor.START, color
        )
    ]
    if author:
        texts.append(
            _spine_text(
                "spine_author", author, preset.spine_face, size, baseline, safe.y, Anchor.END, color
            )
        )
    return texts, SpineStatus(True, True, None, size)


def _back(
    copy: CoverCopy,
    preset: Preset,
    config: CoverConfig,
    geometry: CoverGeometry,
    color: RGB,
    fonts: CoverFonts,
) -> tuple[list[CoverText], list[tuple[str, Box]]]:
    """Back texts and the boxes their legibility treatment covers (back text, imprint)."""
    area = geometry.back_design
    texts: list[CoverText] = []
    boxes: list[tuple[str, Box]] = []
    floor = geometry.barcode_keep_clear.top + BACK_GAP
    imprint_layer = config.layer(TextRole.IMPRINT)
    back_layer = config.layer(TextRole.BACK_TEXT)
    moved = imprint_layer.offset != (0.0, 0.0) or back_layer.offset != (0.0, 0.0)
    imprint = imprint_layer.text if imprint_layer.text is not None else copy.imprint
    if imprint and imprint_layer.visible:
        style = _style(
            "imprint",
            imprint_layer,
            fonts,
            preset.imprint_face,
            preset.imprint_size,
            1.3,
            False,
            color,
            LayerAlign.LEFT,
        )
        assert style.size is not None
        _check_glyphs(imprint, style.face, "cover.imprint")
        if "\n" in imprint:
            raise _fail("text_overflow", "The imprint is one line.", "cover.imprint")
        m = metrics(style.face)
        x, anchor = _anchor(area, style.align)
        line = _text(style, imprint, style.size, x, area.y + m.descent * style.size, anchor)
        if not moved and line.bounds.right > geometry.barcode_keep_clear.x - BACK_GAP:
            raise _fail(
                "text_overflow", "The imprint is too long for the back cover.", "cover.imprint"
            )
        floor = max(floor, line.bounds.top + BACK_GAP)
        (line,) = _shift([line], style.offset)
        texts.append(line)
        boxes.append(("imprint", line.bounds))
    if not copy.back_text or not back_layer.visible:
        return texts, boxes
    style = _style(
        "back_text",
        back_layer,
        fonts,
        preset.body_face,
        preset.body_size,
        preset.body_pitch,
        False,
        color,
        _default_align(config),
    )
    assert style.size is not None
    measure = min(area.width, BACK_MEASURE)
    x, _ = _anchor(area, style.align)
    left = {
        LayerAlign.CENTER: x - measure / 2,
        LayerAlign.LEFT: x,
        LayerAlign.RIGHT: x - measure,
    }[style.align]
    if config.back_rich is not None:
        frame = Box(left, area.y, measure, area.height)
        rich, height = _rich(config.back_rich, style, frame, fonts, "cover.back_text")
        if not moved and area.top - height < floor - 1e-6:
            raise _fail(
                "text_overflow",
                "The back-cover text is too long to stay clear of the barcode area.",
                "cover.back_text",
                actual=f"{height / 72:.2f} in",
                required=f"at most {(area.top - floor) / 72:.2f} in",
            )
        box = Box(left, area.top - height, measure, height)
        boxes.insert(0, ("back_text", _moved(box, style.offset)))
        return _shift(rich, style.offset) + texts, boxes
    _check_glyphs(copy.back_text, style.face, "cover.back_text")
    lines = wrap(copy.back_text, style.face, style.size, measure, style.tracking)
    if lines is None:
        raise _fail(
            "text_overflow", "A word in the back-cover text is too wide.", "cover.back_text"
        )
    block = _group(lines, style, style.size, 0.0)
    height = _height(block)
    if not moved and area.top - height < floor - 1e-6:
        raise _fail(
            "text_overflow",
            "The back-cover text is too long to stay clear of the barcode area.",
            "cover.back_text",
            actual=f"{height / 72:.2f} in",
            required=f"at most {(area.top - floor) / 72:.2f} in",
        )
    # Lines anchor on the area exactly as in version 1; the box spans the measure.
    placed = _shift(_place(block, area.top, area), style.offset)
    box = Box(left, area.top - height, measure, height)
    boxes.insert(0, ("back_text", _moved(box, style.offset)))
    return placed + texts, boxes


def _extra(
    config: CoverConfig,
    preset: Preset,
    geometry: CoverGeometry,
    color: RGB,
    fonts: CoverFonts,
) -> tuple[list[CoverText], list[tuple[str, str, Box]]]:
    """The author's additional layers, centered in their panel's type area, then moved."""
    texts: list[CoverText] = []
    boxes: list[tuple[str, str, Box]] = []
    for extra in config.extra:
        front = extra.panel is LayerPanel.FRONT
        area = geometry.front_design if front else geometry.back_design
        role = f"{extra.panel.value}_extra:{extra.id}"
        style = _style(
            role,
            extra.layer,
            fonts,
            preset.body_face,
            preset.body_size,
            preset.body_pitch,
            False,
            color,
            LayerAlign.CENTER,
        )
        if not extra.layer.visible:
            continue
        lines, size = _set(style.text(extra.text), style, area.width, f"cover.{role}", 8)
        block = _group(lines, style, size, 0.0)
        height = _height(block)
        top = area.y + (area.height + height) / 2
        placed = _shift(_place(block, top, area), style.offset)
        texts += placed
        boxes.append((extra.panel.value, role, _union(placed, area)))
    return texts, boxes


def _band(
    x0: float, x1: float, box: Box, media: Box, tone: TextTone, pad: float = SHADE_PAD
) -> ShadeBand:
    low, high = box.y - pad, box.top + pad
    if low - media.y <= EDGE_SNAP:
        low = media.y
    if media.top - high <= EDGE_SNAP:
        high = media.top
    return ShadeBand(x0, x1, (low, high), SHADE_FADE, SHADE_STRENGTH[tone], SHADE_TOWARD[tone])


def _panel(role: str, x0: float, x1: float, box: Box, media: Box, color: RGB) -> Fill:
    low = max(media.y, box.y - PANEL_PAD)
    high = min(media.top, box.top + PANEL_PAD)
    return Fill(role, Box(x0, low, x1 - x0, high - low), color)


def _text_box(
    element: TextBoxElement, preset: Preset, geometry: CoverGeometry, fonts: CoverFonts
) -> tuple[list[CoverText], CoverTextBox]:
    """A version 3 text box: wrapped to its width from its top edge, never truncated.

    Lines that do not fit the box's height are still placed (below it) so a draft
    can show them; validation reports `text_box_overflow` and builds refuse.
    """
    role = element_role(element)
    box = page_box(geometry, element.region, element.box)
    layer = TextLayer(
        font=element.font,
        size=element.size,
        color=element.color,
        align=element.align,
        line_spacing=element.line_spacing,
        letter_spacing=element.letter_spacing or None,
        case=element.case,
    )
    style = _style(
        role,
        layer,
        fonts,
        preset.body_face,
        element.size,
        element.line_spacing,
        False,
        hex_rgb(element.color),
        element.align,
    )
    if element.rich is not None:
        lines_rich, _ = _rich(element.rich, style, box, fonts, f"cover.{role}")
        return lines_rich, CoverTextBox(role, box)
    text = style.text(element.text)
    _check_glyphs(text, style.face, f"cover.{role}")
    lines = wrap(text, style.face, element.size, box.width, style.tracking)
    if lines is None:
        raise _fail(
            "text_overflow",
            "A word in this text box is wider than the box; widen it or set a smaller size.",
            f"cover.{role}",
        )
    placed = _place(_group(lines, style, element.size, 0.0), box.top, box)
    return placed, CoverTextBox(role, box)


def _over_photo_groups(
    geometry: CoverGeometry,
    front_boxes: list[tuple[str, Box]],
    back_boxes: list[tuple[str, Box]],
    extra_boxes: list[tuple[str, str, Box]],
) -> list[_Group]:
    """Every book-text group with the x range its legibility panel spans."""
    media = geometry.media
    groups = [_Group(role, geometry.front.x, media.right, box) for role, box in front_boxes]
    for role, box in back_boxes:
        right = geometry.barcode_keep_clear.x if role == "imprint" else geometry.back.right
        groups.append(_Group(role, media.x, right, box))
    for panel, role, box in extra_boxes:
        if panel == "front":
            groups.append(_Group(role, geometry.front.x, media.right, box))
        else:
            groups.append(_Group(role, media.x, geometry.back.right, box))
    return groups


def _layout_designed(
    book_id: str,
    config: CoverConfig,
    geometry: CoverGeometry,
    photos: Mapping[str, PhotoInfo],
    fonts: CoverFonts,
    preset: Preset,
    book_texts: list[CoverText],
    spine: list[CoverText],
    spine_status: SpineStatus,
    groups: list[_Group],
) -> CoverLayout:
    """Version 3: region fills, the element stack, then legibility over photographs."""
    regions = config.regions
    assert regions is not None
    background, fills = region_fills(geometry, regions)
    placed_items: list[object] = []
    stack_texts: list[CoverText] = []
    for element in config.elements:
        if not element.visible:
            continue
        if isinstance(element, PhotoElement):
            placed_items.append(design_photo(geometry, element, photos[element.image.sha256]))
        elif isinstance(element, ShapeElement | LineElement):
            placed_items.append(design_shape(geometry, element))
        else:
            lines, box = _text_box(element, preset, geometry, fonts)
            placed_items.append(box)
            stack_texts += lines
    resolutions = tuple(i.resolution for i in placed_items if isinstance(i, PlacedPhoto))
    items = flatten(
        [i.photo if isinstance(i, PlacedPhoto) else i for i in placed_items], geometry, regions
    )
    media, tone = geometry.media, config.type.tone
    placed = [item for item in items if isinstance(item, CoverPhoto)]
    over = [g for g in groups if any(p.region.overlaps(g.box, 0) for p in placed)]
    spine_over = bool(spine) and any(p.region.overlaps(geometry.spine, 0) for p in placed)
    panels: list[Fill] = []
    if config.legibility is Legibility.PANEL:
        for g in over:
            region = Region.BACK if g.x0 == media.x else Region.FRONT
            color = hex_rgb(regions.style(region).color)
            panels.append(_panel(f"panel_{g.role}", g.x0, g.x1, g.box, media, color))
        if spine_over:
            panels.append(Fill("panel_spine", geometry.spine, hex_rgb(regions.spine.color)))
    elif config.legibility is Legibility.SHADE:
        for index, item in enumerate(items):
            if not isinstance(item, CoverPhoto):
                continue
            area = item.region
            bands = [
                _band(area.x, area.right, g.box, media, tone)
                for g in over
                if area.overlaps(g.box, 0)
            ]
            if spine_over and area.overlaps(geometry.spine, 0):
                bands.append(
                    ShadeBand(
                        max(area.x, geometry.spine.x),
                        min(area.right, geometry.spine.right),
                        (media.y, media.top),
                        0.0,
                        SHADE_STRENGTH[tone],
                        SHADE_TOWARD[tone],
                    )
                )
            items[index] = replace(item, shade=tuple(bands))
    stack = tuple(items)
    texts = tuple(book_texts + stack_texts)
    used = {t.face for t in texts}
    custom = tuple(sorted(f.info.postscript_name for f in fonts.by_id.values() if f.key in used))
    return CoverLayout(
        book_id=book_id,
        config=config,
        geometry=geometry,
        background=background,
        stack=stack,  # type: ignore[arg-type]
        panels=tuple(panels),
        texts=texts,
        spine=spine_status,
        resolutions=resolutions,
        fonts=custom,
        region_fills=fills,
        warnings=tuple(design_warnings(config, stack, geometry)),
    )


def layout_cover(
    book_id: str,
    copy: CoverCopy,
    config: CoverConfig,
    geometry: CoverGeometry,
    photo: PhotoInfo | Mapping[str, PhotoInfo],
    fonts: CoverFonts = NO_FONTS,
) -> CoverLayout:
    """Raises CoverError(stage 'layout') when authored text cannot be set safely.

    `photo` is the decoded photograph (versions 1 and 2) or every photograph the
    configuration places, keyed by SHA-256. A configured watermark is placed on the
    front panel and handed to the photograph that holds it.
    """
    layout = _layout_cover(book_id, copy, config, geometry, photo, fonts)
    if config.watermark is None:
        return layout
    placed = place_watermark(config.watermark, geometry.front)
    if placed is None:
        return layout
    return replace(layout, stack=attach(layout.stack, placed), watermark=placed)


def _layout_cover(
    book_id: str,
    copy: CoverCopy,
    config: CoverConfig,
    geometry: CoverGeometry,
    photo: PhotoInfo | Mapping[str, PhotoInfo],
    fonts: CoverFonts = NO_FONTS,
) -> CoverLayout:
    """Raises CoverError(stage 'layout') when authored text cannot be set safely.

    `photo` is the decoded photograph (versions 1 and 2) or every photograph the
    configuration places, keyed by SHA-256.
    """
    preset = PRESETS[config.type.style]
    color = LIGHT if config.type.tone is TextTone.LIGHT else DARK
    media = geometry.media
    front, front_boxes = _front(copy, preset, config, geometry.front_design, color, fonts)
    spine, spine_status = _spine(copy, preset, config, geometry, color)
    back, back_boxes = _back(copy, preset, config, geometry, color, fonts)
    extra, extra_boxes = _extra(config, preset, geometry, color, fonts)
    if config.designed:
        photos = photo if isinstance(photo, Mapping) else {photo.sha256: photo}
        return _layout_designed(
            book_id,
            config,
            geometry,
            photos,
            fonts,
            preset,
            front + spine + back + extra,
            spine,
            spine_status,
            _over_photo_groups(geometry, front_boxes, back_boxes, extra_boxes),
        )
    assert config.image is not None
    if isinstance(photo, Mapping):
        photo = photo[config.image.sha256]
    full = config.layout is CoverLayoutKind.FULL_WRAP
    region = (
        media
        if full
        else Box(geometry.front.x, media.y, media.right - geometry.front.x, media.height)
    )
    window = crop_window(photo.width, photo.height, region, config.crop)

    fill = config.rgb()
    panels: list[Fill] = []
    bands: list[ShadeBand] = []
    tone = config.type.tone
    # (x range, text bounds) for every text group printed over the photograph.
    over_photo = [_Group(role, geometry.front.x, media.right, box) for role, box in front_boxes]
    if full:
        for role, box in back_boxes:
            right = geometry.barcode_keep_clear.x if role == "imprint" else geometry.back.right
            over_photo.append(_Group(role, media.x, right, box))
    for panel, role, box in extra_boxes:
        if panel == "front":
            over_photo.append(_Group(role, geometry.front.x, media.right, box))
        elif full:
            over_photo.append(_Group(role, media.x, geometry.back.right, box))
    if config.legibility is Legibility.PANEL:
        panels = [_panel(f"panel_{g.role}", g.x0, g.x1, g.box, media, fill) for g in over_photo]
        if full and spine:
            panels.append(Fill("panel_spine", geometry.spine, fill))
    elif config.legibility is Legibility.SHADE:
        # Across a full wrap, bands span the whole photo so no band edge lands mid-image.
        span = (region.x, region.right)
        bands = [_band(*(span if full else (g.x0, g.x1)), g.box, media, tone) for g in over_photo]
        if full and spine:
            bands.append(
                ShadeBand(
                    geometry.spine.x,
                    geometry.spine.right,
                    (media.y, media.top),
                    0.0,
                    SHADE_STRENGTH[tone],
                    SHADE_TOWARD[tone],
                )
            )
    # In front_photo layouts the back and spine are the solid fill: no treatment.

    photo_element = CoverPhoto(
        photo.sha256,
        region,
        image_placement(window, region),
        window,
        window.pixel_bounds(),
        tuple(bands),
    )
    resolution = ImageResolution(
        (photo.width, photo.height),
        (window.width, window.height),
        (region.width / 72, region.height / 72),
        window.effective_dpi,
        window.max_dpi,
        KDP_COVER.min_image_dpi,
    )
    texts = tuple(front + spine + back + extra)
    used = {t.face for t in texts}
    custom = tuple(sorted(f.info.postscript_name for f in fonts.by_id.values() if f.key in used))
    return CoverLayout(
        book_id=book_id,
        config=config,
        geometry=geometry,
        background=Fill("background", media, fill),
        stack=(photo_element,),
        panels=tuple(panels),
        texts=texts,
        spine=spine_status,
        resolutions=(resolution,),
        fonts=custom,
    )
