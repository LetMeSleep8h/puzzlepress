"""Pure physical geometry: page boxes, mirrored margins, grids and solution slots."""

from dataclasses import dataclass

from .model import Box, PageFrame
from .spec import KDP, PrintSpecification

# Frame padding around the cell area, as a fraction of one cell on each side.
GRID_PADDING = 0.35
# Letter cap size relative to the cell before clamping to typography limits.
LETTER_RATIO = 0.56
# Solution templates per density: (columns, rows), filled left-to-right, top-down.
SOLUTION_TEMPLATES = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3), 8: (2, 4)}


def page_frame(spec: PrintSpecification, physical_page: int) -> PageFrame:
    """Odd physical pages are recto (binding on the left); even pages are verso.

    Without bleed the media box equals the trim box. With bleed (KDP: 0.125 in at the
    top, bottom and outside edge, none at the binding edge) the media box is 0.125 in
    wider and 0.25 in taller, and the trim box sits against its inside edge: at x = 0
    on rectos, x = 0.125 in on versos, and 0.125 in up. Margins and the live area are
    measured from the trim box, never from the media box.
    """
    recto = physical_page % 2 == 1
    width, height = spec.trim.width, spec.trim.height
    if spec.bleed:
        bleed = KDP.interior_bleed
        media = Box(0.0, 0.0, width + bleed, height + 2 * bleed)
        trim = Box(0.0 if recto else bleed, bleed, width, height)
    else:
        media = trim = Box(0.0, 0.0, width, height)
    margins = spec.margins
    left = margins.inside if recto else margins.outside
    content = Box(
        trim.x + left,
        trim.y + margins.bottom,
        width - margins.inside - margins.outside,
        height - margins.top - margins.bottom,
    )
    return PageFrame(media=media, trim=trim, content=content, recto=recto)


@dataclass(frozen=True)
class GridGeometry:
    cell: float
    letter_size: float
    frame: Box  # Outer frame, including padding: the centerline of its stroke.
    origin_x: float  # Left of the cell area.
    top: float  # Top of the cell area.
    stroke: float  # Frame line width, painted centered on the frame.

    @property
    def bounds(self) -> Box:
        """Painted extent: the frame plus half its stroke on every side."""
        return self.frame.expanded(self.stroke / 2)

    def moved(self, dy: float) -> "GridGeometry":
        frame = self.frame
        return GridGeometry(
            self.cell,
            self.letter_size,
            Box(frame.x, frame.y + dy, frame.width, frame.height),
            self.origin_x,
            self.top + dy,
            self.stroke,
        )


def fit_grid(
    columns: int,
    rows: int,
    region: Box,
    max_letter: float,
    stroke: float,
    max_cell: float | None = None,
    letter_ratio: float = LETTER_RATIO,
) -> GridGeometry:
    """Largest square cells whose painted grid fits the region, centered, top-aligned.

    The whole painted extent, including the half of the frame stroke that lies
    outside the frame, fits the region. Letters scale with cells and are clamped to
    `max_letter`. Callers compare the resulting letter size with their minimum; this
    function never enforces one.
    """
    span_x = columns + 2 * GRID_PADDING
    span_y = rows + 2 * GRID_PADDING
    cell = min((region.width - stroke) / span_x, (region.height - stroke) / span_y)
    if max_cell is not None:
        cell = min(cell, max_cell)
    letter = min(cell * letter_ratio, max_letter)
    width, height = cell * span_x, cell * span_y
    frame = Box(
        region.x + (region.width - width) / 2, region.top - stroke / 2 - height, width, height
    )
    padding = cell * GRID_PADDING
    return GridGeometry(cell, letter, frame, frame.x + padding, frame.top - padding, stroke)


def max_cell_for_letter(max_letter: float, letter_ratio: float = LETTER_RATIO) -> float:
    """Cell size beyond which letters stop growing; grids do not grow past it."""
    return max_letter / letter_ratio


def solution_template(group_size: int) -> int:
    """Smallest supported density that holds a planned group of this size."""
    for density in sorted(SOLUTION_TEMPLATES):
        if group_size <= density:
            return density
    raise ValueError(f"No solution template holds {group_size} solutions")


def solution_slots(density: int, region: Box, gap_x: float, gap_y: float) -> tuple[Box, ...]:
    columns, rows = SOLUTION_TEMPLATES[density]
    width = (region.width - gap_x * (columns - 1)) / columns
    height = (region.height - gap_y * (rows - 1)) / rows
    return tuple(
        Box(
            region.x + column * (width + gap_x),
            region.top - (row + 1) * height - row * gap_y,
            width,
            height,
        )
        for row in range(rows)
        for column in range(columns)
    )
