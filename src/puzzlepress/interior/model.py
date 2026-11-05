"""Immutable physical layout model consumed by the PDF renderer.

Coordinates are PDF points with the origin at the bottom-left corner of the
trim box and y increasing upward. The layout engine decides every position;
the renderer draws exactly these elements and nothing else.
"""

from dataclasses import dataclass
from enum import StrEnum

from .design import CLASSIC, InteriorDesign
from .issues import LayoutIssue
from .spec import PrintSpecification


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y + self.height

    def expanded(self, margin: float) -> "Box":
        return Box(
            self.x - margin, self.y - margin, self.width + 2 * margin, self.height + 2 * margin
        )

    def intersection(self, other: "Box") -> "Box | None":
        """The overlap of two boxes, or None when they do not overlap."""
        left, bottom = max(self.x, other.x), max(self.y, other.y)
        right, top = min(self.right, other.right), min(self.top, other.top)
        if right <= left or top <= bottom:
            return None
        return Box(left, bottom, right - left, top - bottom)

    def contains(self, other: "Box", tolerance: float) -> bool:
        return (
            other.x >= self.x - tolerance
            and other.y >= self.y - tolerance
            and other.right <= self.right + tolerance
            and other.top <= self.top + tolerance
        )

    def overlaps(self, other: "Box", tolerance: float) -> bool:
        return (
            self.x < other.right - tolerance
            and other.x < self.right - tolerance
            and self.y < other.top - tolerance
            and other.y < self.top - tolerance
        )


class Face(StrEnum):
    REGULAR = "regular"
    BOLD = "bold"
    ITALIC = "italic"


class Anchor(StrEnum):
    START = "start"
    MIDDLE = "middle"
    END = "end"


@dataclass(frozen=True)
class TextLine:
    """One measured line. `bounds` covers the font's full ascent and descent."""

    role: str
    text: str
    face: Face
    size: float
    x: float
    baseline: float
    anchor: Anchor
    bounds: Box
    gray: float = 0.0  # DeviceGray ink: 0 is black.


@dataclass(frozen=True)
class Rule:
    role: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    bounds: Box
    gray: float = 0.0


@dataclass(frozen=True)
class SolutionMark:
    """A capsule outline joining the centers of a target's first and last cells."""

    target_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    radius: float
    line_width: float


@dataclass(frozen=True)
class LetterGrid:
    """Authoritative letters drawn centered in square cells; row 0 is the top row."""

    role: str
    rows: tuple[str, ...]
    origin_x: float  # Left edge of the cell area.
    top: float  # Top edge of the cell area.
    cell: float
    letter_size: float
    face: Face
    frame: Box
    frame_width: float
    baseline_offset: float  # Center-to-baseline distance for capital letters.
    emphasized: frozenset[tuple[int, int]] = frozenset()  # (column, row) cells.
    emphasized_face: Face = Face.BOLD
    muted_gray: float = 0.0  # Gray for letters outside `emphasized` when marks exist.
    marks: tuple[SolutionMark, ...] = ()
    frame_radius: float = 0.0  # Rounded frame corners; never more than the cell padding.

    @property
    def columns(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    def center(self, column: int, row: int) -> tuple[float, float]:
        return (
            self.origin_x + (column + 0.5) * self.cell,
            self.top - (row + 0.5) * self.cell,
        )

    @property
    def bounds(self) -> Box:
        """Painted extent: the frame stroke is centered, so half of it lies outside."""
        return self.frame.expanded(self.frame_width / 2)


@dataclass(frozen=True)
class Panel:
    """A tinted block or a ruled frame inside the live area (DeviceGray, opaque).

    `box` is the rectangle path; a stroke is centred on its edges, so the painted
    extent (`bounds`) grows by half the stroke. Panels are background: text may sit
    on them, grids never do.
    """

    role: str
    box: Box
    fill_gray: float | None  # None: no fill. 1.0 is paper white.
    stroke_gray: float | None = None
    stroke_width: float = 0.0
    radius: float = 0.0  # Rounded corners.

    @property
    def bounds(self) -> Box:
        if self.stroke_gray is None:
            return self.box
        return self.box.expanded(self.stroke_width / 2)


class ImageEncoding(StrEnum):
    """How an image's pixels are embedded; each has its own renderer branch."""

    JPEG = "jpeg"  # A styled grayscale photograph (DCTDecode).
    LOSSLESS = "lossless"  # Prepared coloring line art, embedded exactly (FlateDecode).


@dataclass(frozen=True)
class ImageBlock:
    """A grayscale image: the source window `pixels`, drawn at `placement`.

    It is clipped to `box`, its printed area, which lies inside the live area.
    `effective_dpi` is source pixels per printed inch (uniform on both axes).
    `sha256` names the source: a photograph's file digest, or for line art the
    `sha256-` digest of its prepared pixels.
    """

    role: str
    box: Box
    sha256: str
    placement: Box
    pixels: tuple[int, int, int, int]
    effective_dpi: float
    max_dpi: float
    encoding: ImageEncoding = ImageEncoding.JPEG
    # True only for a coloring drawing that fills a full-bleed page: its box is the
    # fill area, which extends past the trim on purpose. Margin and live-area rules
    # skip it; the coloring validator and bleed preflight rules check it instead.
    bleed: bool = False

    @property
    def bounds(self) -> Box:
        return self.box


@dataclass(frozen=True)
class Polygon:
    """A filled decorative shape (DeviceGray, opaque) in its own reserved box.

    Decoration never touches text, grids or photographs: `bounds` is the box the
    engine reserved for it, and layout validation keeps every other element out.
    """

    role: str
    points: tuple[tuple[float, float], ...]
    fill_gray: float
    bounds: Box


Element = TextLine | Rule | LetterGrid | Panel | ImageBlock | Polygon


@dataclass(frozen=True)
class PageFrame:
    """Media, trim and live (content) boxes for one physical page."""

    media: Box
    trim: Box
    content: Box
    recto: bool


@dataclass(frozen=True)
class PhysicalPage:
    number: int  # 1-based physical PDF page.
    plan_index: int
    kind: str
    frame: PageFrame
    elements: tuple[Element, ...]
    folio: str | None  # Displayed label, exactly as the plan states it.


@dataclass(frozen=True)
class InteriorLayout:
    spec: PrintSpecification
    book_id: str
    identity: str
    plan_digest: str
    pages: tuple[PhysicalPage, ...]
    warnings: tuple[LayoutIssue, ...]
    design: InteriorDesign = CLASSIC  # The resolved interior style it was laid out with.
