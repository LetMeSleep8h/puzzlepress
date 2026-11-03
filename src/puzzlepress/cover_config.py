"""Authored paperback cover configuration.

The cover is presentation of the printed edition, so it is excluded from the
project build identity (an edited crop never stales the interior). Its own
cover identity covers it instead. Cover text comes from `book` metadata; only
the optional back-cover text is authored here.

Version 1 holds semantic choices only. Version 2 adds per-layer text overrides
(visibility, display text, font, size, color, alignment, spacing and an offset
in points from the layout's own position), extra text layers and imported fonts.
A layer override never changes book metadata: hiding the title on the cover
leaves `book.title` untouched. Every override is optional; a version 2 cover
without overrides lays out exactly like version 1.

Version 3 (`cover_design`) replaces the single layout, photograph and fill with
independent back, spine and front regions and an ordered stack of design
elements; it keeps version 2's text layers, extra layers and fonts. Versions 1
and 2 are never upgraded implicitly; conversion is an explicit action.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cover_design import CoverRegions, Element
    from .cover_richtext import RichText

COVER_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
# Project-relative directory for imported photographs, beside book.yaml.
ASSET_DIRECTORY = "cover-assets"
# Imported cover fonts live one level below it.
FONT_DIRECTORY = f"{ASSET_DIRECTORY}/fonts"
MAX_BACK_TEXT = 1200
MAX_ZOOM = 4.0
# Crop values are normalized to this many decimal places.
CROP_DECIMALS = 4
# Version 2 bounds. Sizes in points; KDP's 7 pt minimum is a layout finding.
MAX_LAYER_TEXT = 300
MAX_EXTRA_LAYERS = 8
MAX_FONTS = 8
MIN_TEXT_SIZE = 4.0
MAX_TEXT_SIZE = 160.0
MAX_OFFSET = 1200.0  # Points; wider than any supported wrap.
LINE_SPACING = (0.8, 3.0)
LETTER_SPACING = (-2.0, 20.0)


class CoverLayoutKind(StrEnum):
    FULL_WRAP = "full_wrap"  # One photograph across back, spine and front, bleed to bleed.
    FRONT_PHOTO = "front_photo"  # Photograph on the front; spine and back in the fill color.


class CoverStyle(StrEnum):
    EDITORIAL = "editorial"  # Newsreader serif.
    BOLD = "bold"  # Uppercase Vera Sans Bold.
    MINIMAL = "minimal"  # Restrained Vera Sans.


class TitlePosition(StrEnum):
    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


class TextAlign(StrEnum):
    CENTER = "center"
    LEFT = "left"


class TextTone(StrEnum):
    LIGHT = "light"
    DARK = "dark"


class Legibility(StrEnum):
    NONE = "none"
    SHADE = "shade"  # Photo pixels behind text are darkened (or lightened) toward it.
    PANEL = "panel"  # An opaque band of the fill color behind text.


class LayerAlign(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class LetterCase(StrEnum):
    AS_WRITTEN = "as_written"
    UPPER = "upper"


class TextRole(StrEnum):
    """Cover text that comes from the book (title, subtitle, author, imprint) or
    from the cover section (back_text)."""

    TITLE = "title"
    SUBTITLE = "subtitle"
    AUTHOR = "author"
    BACK_TEXT = "back_text"
    IMPRINT = "imprint"


# Roles whose words come from book metadata; their display text may be overridden.
METADATA_ROLES = (TextRole.TITLE, TextRole.SUBTITLE, TextRole.AUTHOR, TextRole.IMPRINT)


class LayerPanel(StrEnum):
    FRONT = "front"
    BACK = "back"


class SpineText(StrEnum):
    AUTO = "auto"  # Title and author when KDP's page count and the spine width allow.
    NONE = "none"


@dataclass(frozen=True)
class CoverImage:
    """A photograph in the project's cover-assets directory, pinned by content."""

    path: str  # Project-relative, forward slashes: cover-assets/<name>.jpg
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class Crop:
    """Focal point (0..1 of the upright photo; y downward) and zoom beyond cover-fit."""

    x: float = 0.5
    y: float = 0.5
    zoom: float = 1.0

    def to_dict(self) -> dict[str, object]:
        return {"x": self.x, "y": self.y, "zoom": self.zoom}


@dataclass(frozen=True)
class CoverType:
    style: CoverStyle = CoverStyle.EDITORIAL
    position: TitlePosition = TitlePosition.TOP
    align: TextAlign = TextAlign.CENTER
    tone: TextTone = TextTone.LIGHT

    def to_dict(self) -> dict[str, object]:
        return {
            "style": self.style.value,
            "position": self.position.value,
            "align": self.align.value,
            "tone": self.tone.value,
        }


@dataclass(frozen=True)
class TextLayer:
    """Overrides for one cover text layer; None keeps the layout's own choice.

    `offset` moves the layer from where the layout puts it, in PDF points (x to
    the right, y upward). `font` names a bundled face or an imported font's id.
    """

    visible: bool = True
    text: str | None = None
    font: str | None = None
    size: float | None = None
    color: str | None = None
    align: LayerAlign | None = None
    line_spacing: float | None = None  # Multiple of the size, baseline to baseline.
    letter_spacing: float | None = None  # Points added between characters.
    case: LetterCase | None = None
    offset: tuple[float, float] = (0.0, 0.0)

    @property
    def is_default(self) -> bool:
        return self == TextLayer()

    def to_dict(self) -> dict[str, object]:
        """Only the overrides, so the canonical form stays minimal."""
        data: dict[str, object] = {}
        if not self.visible:
            data["visible"] = False
        for key in ("text", "font", "size", "color", "line_spacing", "letter_spacing"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        if self.align is not None:
            data["align"] = self.align.value
        if self.case is not None:
            data["case"] = self.case.value
        if self.offset != (0.0, 0.0):
            data["offset"] = {"x": self.offset[0], "y": self.offset[1]}
        return data


@dataclass(frozen=True)
class ExtraLayer:
    """An additional line or paragraph of the author's own text on one panel."""

    id: str
    panel: LayerPanel
    text: str
    layer: TextLayer = field(default_factory=TextLayer)

    def to_dict(self) -> dict[str, object]:
        overrides = self.layer.to_dict()
        overrides.pop("text", None)
        return {"id": self.id, "panel": self.panel.value, "text": self.text, **overrides}


@dataclass(frozen=True)
class CoverFont:
    """An imported font file, pinned by content, with author-stated provenance.

    `license` and `source` are what the author records (None: unknown); they are
    never inferred from the file. Embedding permission is read from the font.
    """

    id: str
    path: str  # cover-assets/fonts/<name>.ttf|otf
    sha256: str
    license: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"id": self.id, "path": self.path, "sha256": self.sha256}
        if self.license is not None:
            data["license"] = self.license
        if self.source is not None:
            data["source"] = self.source
        return data


class WatermarkPosition(StrEnum):
    TOP_LEFT = "top-left"
    TOP_CENTER = "top-center"
    TOP_RIGHT = "top-right"
    MIDDLE_LEFT = "middle-left"
    CENTER = "center"
    MIDDLE_RIGHT = "middle-right"
    BOTTOM_LEFT = "bottom-left"
    BOTTOM_CENTER = "bottom-center"
    BOTTOM_RIGHT = "bottom-right"


@dataclass(frozen=True)
class Watermark:
    """Text baked into the front photograph's derived pixels (version 2+).

    `scale` is the text width as a fraction of the front trim width; `margin` is
    points from the front trim edges. The source photograph is never changed.
    """

    enabled: bool = True
    text: str = ""
    opacity: float = 0.35
    position: WatermarkPosition = WatermarkPosition.BOTTOM_RIGHT
    scale: float = 0.25
    margin: float = 27.0
    shadow: bool = False
    color: str = "#ffffff"

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "text": self.text,
            "opacity": self.opacity,
            "position": self.position.value,
            "scale": self.scale,
            "margin": self.margin,
            "shadow": self.shadow,
            "color": self.color,
        }


@dataclass(frozen=True)
class CoverConfig:
    image: CoverImage | None  # Versions 1 and 2; version 3 places photographs as elements.
    layout: CoverLayoutKind = CoverLayoutKind.FULL_WRAP
    crop: Crop = field(default_factory=Crop)
    type: CoverType = field(default_factory=CoverType)
    legibility: Legibility = Legibility.SHADE
    background: str = "#26302b"  # sRGB fill wherever the photograph does not print.
    spine_text: SpineText = SpineText.AUTO
    back_text: str | None = None
    version: int = 1
    # Version 2: overrides by role (book order), extra layers and imported fonts.
    text: tuple[tuple[TextRole, TextLayer], ...] = ()
    extra: tuple[ExtraLayer, ...] = ()
    fonts: tuple[CoverFont, ...] = ()
    # Version 3: region backgrounds and the element stack (bottom to top).
    regions: "CoverRegions | None" = None
    elements: "tuple[Element, ...]" = ()
    # Version 2+: the back text as a rich text document; `back_text` is its plain text.
    back_rich: "RichText | None" = None
    # Version 2+: an optional watermark baked into the front photograph's pixels.
    watermark: Watermark | None = None

    @property
    def designed(self) -> bool:
        """A version 3 cover with independent regions and elements."""
        return self.version >= 3

    def images(self) -> tuple[CoverImage, ...]:
        """Every photograph the configuration references, in stack order, once each."""
        if self.image is not None:
            return (self.image,)
        seen: dict[str, CoverImage] = {}
        for element in self.elements:
            image = getattr(element, "image", None)
            if isinstance(image, CoverImage):
                seen.setdefault(image.sha256 + image.path, image)
        return tuple(seen.values())

    def layer(self, role: TextRole) -> TextLayer:
        return dict(self.text).get(role, TextLayer())

    def font(self, font_id: str) -> CoverFont | None:
        return next((f for f in self.fonts if f.id == font_id), None)

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"version": self.version}
        if self.designed:
            assert self.regions is not None
            data |= {
                "type": self.type.to_dict(),
                "legibility": self.legibility.value,
                "spine_text": self.spine_text.value,
                "regions": self.regions.to_dict(),
                "elements": [element.to_dict() for element in self.elements],
            }
        else:
            assert self.image is not None
            data |= {
                "layout": self.layout.value,
                "image": self.image.to_dict(),
                "crop": self.crop.to_dict(),
                "type": self.type.to_dict(),
                "legibility": self.legibility.value,
                "background": self.background,
                "spine_text": self.spine_text.value,
            }
        if self.back_rich is not None:
            data["back_text"] = self.back_rich.to_dict()
        elif self.back_text is not None:
            data["back_text"] = self.back_text
        text = {role.value: layer.to_dict() for role, layer in self.text if not layer.is_default}
        if text:
            data["text"] = text
        if self.extra:
            data["extra"] = [layer.to_dict() for layer in self.extra]
        if self.fonts:
            data["fonts"] = [font.to_dict() for font in self.fonts]
        if self.watermark is not None:
            data["watermark"] = self.watermark.to_dict()
        return data

    def rgb(self) -> tuple[float, float, float]:
        return hex_rgb(self.background)


def hex_rgb(value: str) -> tuple[float, float, float]:
    return (int(value[1:3], 16) / 255, int(value[3:5], 16) / 255, int(value[5:7], 16) / 255)
