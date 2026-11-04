"""Schema-v1 optional `coloring` section: an artwork library, page order and layout.

Artwork files live in the project's `coloring-assets/` folder under content-addressed
names (`<stem>-<first 12 hex of SHA-256>.png|jpg`) and are never rewritten. The
source pins each file's full SHA-256. Adjustments are non-destructive settings over
the original bytes; nothing in this version applies them to pixels.

Normalized values always carry every default, so an omitted setting and the same
setting written out explicitly serialize, and therefore hash, identically.
"""

from dataclasses import dataclass
from enum import StrEnum

COLORING_VERSION = 1
ARTWORK_DIRECTORY = "coloring-assets"
# Provisional caps: no coloring interior is built yet, so these are not measured
# generation budgets. Interval 4 measures layout and rendering before raising them.
MAX_ARTWORK = 300
MAX_PAGES = 300
MAX_TITLE = 200


class Border(StrEnum):
    NONE = "none"
    THIN = "thin"
    DOUBLE = "double"


@dataclass(frozen=True)
class Adjustments:
    """Line-art preparation settings over the original, applied in Python by
    `coloring.prepare` (order and meaning are documented there). No build reads
    them yet; the defaults reproduce the original's gray levels.
    """

    grayscale: bool = True  # Luma; false takes each pixel's darkest channel.
    threshold: float | None = None  # None keeps gray levels; else 0.05..0.95 black point.
    brightness: float = 0.0  # -1..1
    contrast: float = 1.0  # 0.25..4
    background_cleanup: float = 0.0  # 0..1: paper stretched to white, then near-white lifted.
    despeckle: int = 0  # 0..5: isolated marks up to 0/4/9/16/36/64 pixels removed.
    line_weight: int = 0  # -2..2: thin (negative) or thicken (positive) lines.
    invert: bool = False  # For white-on-black artwork.

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "grayscale": self.grayscale,
            "threshold": self.threshold,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "background_cleanup": self.background_cleanup,
            "despeckle": self.despeckle,
            "line_weight": self.line_weight,
        }
        if self.invert:
            # Only when set, so books saved before `invert` existed keep their bytes.
            data["invert"] = True
        return data


@dataclass(frozen=True)
class Artwork:
    id: str
    path: str  # coloring-assets/<stem>-<sha12>.<png|jpg>
    sha256: str  # Full lowercase hex digest of the original bytes.
    title: str | None = None
    adjustments: Adjustments = Adjustments()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": self.path,
            "sha256": self.sha256,
            "title": self.title,
            "adjustments": self.adjustments.to_dict(),
        }


@dataclass(frozen=True)
class ColoringPage:
    artwork: str  # An artwork id.

    def to_dict(self) -> dict[str, object]:
        return {"artwork": self.artwork}


@dataclass(frozen=True)
class ColoringLayout:
    blank_reverse: bool = True  # Single-sided: every coloring page backed by a blank.
    border: Border = Border.NONE

    def to_dict(self) -> dict[str, object]:
        return {"blank_reverse": self.blank_reverse, "border": self.border.value}


@dataclass(frozen=True)
class ColoringBook:
    version: int = COLORING_VERSION
    artwork: tuple[Artwork, ...] = ()
    pages: tuple[ColoringPage, ...] = ()
    layout: ColoringLayout = ColoringLayout()

    def artwork_by_id(self, artwork_id: str) -> Artwork | None:
        return next((item for item in self.artwork if item.id == artwork_id), None)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "artwork": [item.to_dict() for item in self.artwork],
            "pages": [page.to_dict() for page in self.pages],
            "layout": self.layout.to_dict(),
        }
