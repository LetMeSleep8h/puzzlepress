"""Cover watermarks: text baked into a photograph's derived pixels.

Python decides the watermark's box from the front trim panel, the configured
position, margin and scale, and the bundled Vera Sans Bold metrics; the renderer
composites exactly that text into the cropped photograph before it is encoded, so
the PDF carries no transparency and the source photograph is never touched.
A watermark is reported, never moved, when it would cover cover text, leave the
front safe area or fall outside every photograph.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cache
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from ..cover_config import Watermark, WatermarkPosition
from ..interior.fonts import ASCENT, DESCENT, FONT_FILES, _font_path, _registered, text_width
from ..interior.fonts import missing_characters as _missing
from ..interior.issues import LayoutIssue

if TYPE_CHECKING:
    from .model import StackItem
from ..interior.model import Box, Face

MIN_SIZE = 6.0  # Points.
MAX_SIZE = 144.0
SHADOW_OFFSET = 0.06  # Of the size, down and to the right.
SHADOW_OPACITY = 0.6  # Of the watermark opacity.
TOLERANCE = 0.01
CLEARANCE = 4.0  # Points kept clear between a watermark and cover text.


@dataclass(frozen=True)
class PlacedWatermark:
    text: str
    size: float  # Points.
    box: Box  # Painted extent in page points (ascent to descent, plus shadow).
    origin: tuple[float, float]  # Baseline start in page points.
    color: tuple[int, int, int]
    opacity: float
    shadow: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "size": round(self.size, 4),
            "box": {k: round(getattr(self.box, k), 4) for k in ("x", "y", "width", "height")},
            "opacity": self.opacity,
            "shadow": self.shadow,
        }


def _rgb(value: str) -> tuple[int, int, int]:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def place_watermark(config: Watermark, front: Box) -> PlacedWatermark | None:
    """The watermark's box on the front trim panel; None when disabled."""
    if not config.enabled or not config.text:
        return None
    _registered()  # Verifies the pinned font digest before measuring.
    unit = text_width(config.text, Face.BOLD, 1.0)
    size = min(MAX_SIZE, max(MIN_SIZE, config.scale * front.width / unit))
    width = unit * size
    shadow = size * SHADOW_OFFSET if config.shadow else 0.0
    height = (ASCENT + DESCENT) * size
    margin = config.margin
    horizontal, vertical = _axes(config.position)
    x = {
        "left": front.x + margin,
        "center": front.x + (front.width - width) / 2,
        "right": front.right - margin - width - shadow,
    }[horizontal]
    y = {
        "bottom": front.y + margin + shadow,
        "middle": front.y + (front.height - height) / 2,
        "top": front.top - margin - height,
    }[vertical]
    box = Box(x, y - shadow, width + shadow, height + shadow)
    return PlacedWatermark(
        config.text,
        size,
        box,
        (x, y + DESCENT * size),
        _rgb(config.color),
        config.opacity,
        config.shadow,
    )


def _axes(position: WatermarkPosition) -> tuple[str, str]:
    if position is WatermarkPosition.CENTER:
        return "center", "middle"
    vertical, horizontal = position.value.split("-")
    return horizontal, vertical


def watermark_issues(
    placed: PlacedWatermark,
    safe: Box,
    photos: tuple[Box, ...],
    texts: tuple[tuple[str, Box], ...],
) -> list[LayoutIssue]:
    issues: list[LayoutIssue] = []
    missing = _missing(placed.text, Face.BOLD)
    if missing:
        issues.append(
            LayoutIssue(
                "watermark_glyphs",
                "The watermark font cannot draw: " + "".join(missing),
                region="cover.watermark",
            )
        )
    if not safe.contains(placed.box, TOLERANCE):
        issues.append(
            LayoutIssue(
                "watermark_outside_safe_area",
                "The watermark leaves the front safe area; increase the margin or reduce "
                "the scale.",
                region="cover.watermark",
            )
        )
    if not any(photo.contains(placed.box, TOLERANCE) for photo in photos):
        issues.append(
            LayoutIssue(
                "watermark_outside_photo",
                "The watermark is not entirely over one photograph, so it cannot be baked "
                "into photo pixels.",
                region="cover.watermark",
            )
        )
    for role, bounds in texts:
        if placed.box.expanded(CLEARANCE).overlaps(bounds, TOLERANCE):
            issues.append(
                LayoutIssue(
                    "watermark_overlaps_text",
                    f"The watermark would cover the cover's {role} text; move it or reduce "
                    "its scale.",
                    region="cover.watermark",
                )
            )
    return issues


@cache
def _font(pixels: int) -> ImageFont.FreeTypeFont:
    bold = next(f for f in FONT_FILES if f.face is Face.BOLD)
    return ImageFont.truetype(str(_font_path(bold)), pixels)


def bake_watermark(
    image: Image.Image, placement: Box, scale: float, placed: PlacedWatermark
) -> Image.Image:
    """Composite the text into cropped pixels; `placement`/`scale` map points to pixels."""
    pixels = max(1, round(placed.size / scale))
    font = _font(pixels)

    def layer(dx: float, dy: float, color: tuple[int, int, int], opacity: float) -> Image.Image:
        x = (placed.origin[0] + dx - placement.x) / scale
        y = (placement.top - (placed.origin[1] - dy)) / scale
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).text((x, y), placed.text, fill=255, font=font, anchor="ls")
        mask = mask.point(lambda v: round(v * opacity))
        return Image.composite(Image.new("RGB", image.size, color), image, mask)

    if placed.shadow:
        offset = placed.size * SHADOW_OFFSET
        image = layer(offset, offset, (0, 0, 0), placed.opacity * SHADOW_OPACITY)
    return layer(0.0, 0.0, placed.color, placed.opacity)


def attach(stack: tuple[StackItem, ...], placed: PlacedWatermark) -> tuple[StackItem, ...]:
    """Give the watermark to the topmost photograph that wholly contains it."""
    from .model import CoverPhoto

    for index in range(len(stack) - 1, -1, -1):
        item = stack[index]
        if isinstance(item, CoverPhoto) and item.region.contains(placed.box, TOLERANCE):
            return (*stack[:index], replace(item, watermark=placed), *stack[index + 1 :])
    return stack
