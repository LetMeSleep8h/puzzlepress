"""Immutable cover layout consumed by the cover renderer and its preview.

Coordinates are PDF points, origin at the bottom-left of the media box (outer
bleed corner), y upward. The layout engine decides every position and every
pixel used from the photograph; the renderer draws exactly these elements.
"""

import math
from dataclasses import dataclass

from ..cover_config import CoverConfig
from ..interior.issues import LayoutIssue
from ..interior.model import Anchor, Box
from .crop import CropWindow
from .geometry import CoverGeometry
from .watermark import PlacedWatermark

RGB = tuple[float, float, float]


@dataclass(frozen=True)
class Fill:
    """An opaque rectangle (background, region or legibility panel).

    `gradient` is (end color, direction): a linear blend from `color` at the top
    (vertical) or left (horizontal) to the end color, drawn as a PDF shading.
    """

    role: str
    box: Box
    color: RGB
    gradient: tuple[RGB, str] | None = None


@dataclass(frozen=True)
class CoverText:
    """One measured line. Spine lines turn 90 degrees clockwise (read top to bottom).

    `origin` is the anchor point on the baseline; `bounds` covers the font's full
    ascent and descent in page coordinates after rotation.
    """

    role: str
    text: str
    face: str  # A bundled CoverFace value or an imported font's registered name.
    size: float
    origin: tuple[float, float]
    anchor: Anchor
    rotated: bool
    bounds: Box
    color: RGB
    tracking: float = 0.0  # Points added between characters (PDF Tc).
    # Rich text: the filled underline box, inside `bounds` (never a stroke).
    underline: Box | None = None


@dataclass(frozen=True)
class ShadeBand:
    """Pixels behind text pulled toward `toward`, baked into the photograph.

    Full `strength` between `core` (y range in points), fading linearly to zero
    over `fade` points beyond it, within the band's x range. No PDF transparency.
    """

    x0: float
    x1: float
    core: tuple[float, float]
    fade: float
    strength: float
    toward: tuple[int, int, int]

    def weight(self, y: float) -> float:
        low, high = self.core
        distance = low - y if y < low else y - high if y > high else 0.0
        if distance <= 0:
            return self.strength
        if self.fade <= 0 or distance >= self.fade:
            return 0.0
        return self.strength * (1 - distance / self.fade)


@dataclass(frozen=True)
class CoverPhoto:
    """The photograph: the source window shown in `region`, drawn at `placement`."""

    sha256: str
    region: Box  # Clip: exactly the area the photo prints in.
    placement: Box  # Whole-pixel crop drawn here, overhanging the region by < 1 px.
    window: CropWindow
    pixels: tuple[int, int, int, int]  # (x0, y0, x1, y1) of the upright photo.
    shade: tuple[ShadeBand, ...] = ()
    role: str = "photo"  # Version 3: `element:<id>`.
    # Translucent shapes flattened into these pixels, bottom to top (version 3).
    baked: tuple["CoverShape", ...] = ()
    # A watermark composited into these pixels last (version 2+).
    watermark: PlacedWatermark | None = None


@dataclass(frozen=True)
class CoverShape:
    """A rectangle, ellipse or line (a thin rectangle), drawn only with fills.

    `box` is the unrotated shape in page points; it turns `rotation` degrees
    counterclockwise about its centre. A stroke is a filled outline inside the
    box, so a cover never strokes a path. `bounds` is the painted extent.
    """

    role: str
    kind: str  # rect, ellipse or line.
    box: Box
    rotation: float
    fill: RGB | None
    stroke: RGB | None
    stroke_width: float
    bounds: Box
    opacity: float = 1.0  # Below 1 only when baked into a photograph.

    def outline(self, steps: int = 96) -> tuple[tuple[float, float], ...]:
        """Polygon of the painted shape in page points (rotation applied)."""
        box = self.box
        cx, cy = box.x + box.width / 2, box.y + box.height / 2
        if self.kind == "ellipse":
            points = [
                (
                    cx + box.width / 2 * math.cos(2 * math.pi * i / steps),
                    cy + box.height / 2 * math.sin(2 * math.pi * i / steps),
                )
                for i in range(steps)
            ]
        else:
            points = [(box.x, box.y), (box.right, box.y), (box.right, box.top), (box.x, box.top)]
        if not self.rotation:
            return tuple(points)
        angle = math.radians(self.rotation)
        cos, sin = math.cos(angle), math.sin(angle)
        return tuple(
            (cx + (x - cx) * cos - (y - cy) * sin, cy + (x - cx) * sin + (y - cy) * cos)
            for x, y in points
        )


@dataclass(frozen=True)
class CoverTextBox:
    """Where a version 3 text box's lines are drawn in the stack (lines in `texts`)."""

    role: str
    box: Box  # The authored box in page points.


@dataclass(frozen=True)
class ImageResolution:
    source_pixels: tuple[int, int]  # Upright photo.
    used_pixels: tuple[float, float]  # Source pixels inside the visible window.
    printed_inches: tuple[float, float]  # Physical size of the photo region.
    effective_dpi: float
    max_dpi: float  # With no zoom: the most this photo can deliver here.
    minimum_dpi: float  # KDP minimum.

    @property
    def sufficient(self) -> bool:
        return self.effective_dpi + 1e-9 >= self.minimum_dpi

    @property
    def status(self) -> str:
        """`ok`, `image_low_effective_dpi` (zoom out to fix) or `image_too_small`."""
        if self.sufficient:
            return "ok"
        if self.max_dpi + 1e-9 >= self.minimum_dpi:
            return "image_low_effective_dpi"
        return "image_too_small"

    def to_dict(self) -> dict[str, object]:
        return {
            "source_pixels": list(self.source_pixels),
            "used_pixels": [round(v, 2) for v in self.used_pixels],
            "printed_inches": [round(v, 4) for v in self.printed_inches],
            "effective_dpi": round(self.effective_dpi, 2),
            "max_dpi": round(self.max_dpi, 2),
            "minimum_dpi": self.minimum_dpi,
            "status": self.status,
        }


@dataclass(frozen=True)
class SpineStatus:
    allowed_by_page_count: bool
    rendered: bool
    reason: str | None  # Why spine text is absent: authored, page_count, spine_too_narrow.
    size: float | None  # Point size when rendered.

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed_by_page_count": self.allowed_by_page_count,
            "rendered": self.rendered,
            "reason": self.reason,
            "size": self.size,
        }


StackItem = CoverPhoto | CoverShape | CoverTextBox


@dataclass(frozen=True)
class CoverLayout:
    """Drawing order: background, region fills, the stack (bottom to top) with the
    legibility panels directly above its topmost photograph, then book text.

    Versions 1 and 2 have one photograph and no region fills, which is exactly
    their original order. `texts` holds every line (book text and text boxes) for
    validation; text-box lines are drawn at their stack position.
    """

    book_id: str
    config: CoverConfig
    geometry: CoverGeometry
    background: Fill
    stack: tuple[StackItem, ...]
    panels: tuple[Fill, ...]  # Drawn over the topmost photo, under later elements.
    texts: tuple[CoverText, ...]
    spine: SpineStatus
    resolutions: tuple[ImageResolution, ...]  # One per photograph, in stack order.
    fonts: tuple[str, ...] = ()  # PostScript names of imported fonts the text uses.
    region_fills: tuple[Fill, ...] = ()  # Version 3, when regions differ.
    watermark: PlacedWatermark | None = None  # Placed; baked into a photo if one holds it.
    # Findings that never block a build (spine variance, elements under the barcode).
    warnings: tuple[LayoutIssue, ...] = ()

    @property
    def photos(self) -> tuple[CoverPhoto, ...]:
        return tuple(item for item in self.stack if isinstance(item, CoverPhoto))

    @property
    def photo(self) -> CoverPhoto:
        """The first photograph (versions 1 and 2 have exactly one)."""
        photos = self.photos
        if not photos:
            raise ValueError("This cover places no photograph")
        return photos[0]

    @property
    def resolution(self) -> ImageResolution | None:
        """The lowest effective resolution of any photograph; None without photos."""
        if not self.resolutions:
            return None
        return min(self.resolutions, key=lambda r: (r.effective_dpi, r.max_dpi))

    def is_stack_text(self, text: CoverText) -> bool:
        return "_element:" in text.role
