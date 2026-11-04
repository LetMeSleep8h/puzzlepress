"""Independent structural checks of an InteriorLayout against plan, report and spec.

These restate the renderer contract instead of re-running the engine: one page
per plan entry in order, mirrored margins, authoritative folios, untouched grids,
exact solution groups, minimum sizes and strokes, containment and collisions.
"""

from collections.abc import Iterator
from itertools import combinations

from ..batch import BatchReport
from ..publication import PageKind, PublicationPlan
from .engine import page_count_checks
from .issues import LayoutIssue
from .model import (
    Box,
    Element,
    InteriorLayout,
    LetterGrid,
    Panel,
    PhysicalPage,
    Polygon,
    Rule,
    TextLine,
)
from .spec import KDP

# Containment tolerance in points (far below any visible distance).
EPSILON = 0.01


def validate_layout(
    layout: InteriorLayout, plan: PublicationPlan, report: BatchReport | None
) -> tuple[LayoutIssue, ...]:
    """`report` is None for books without generated puzzles (coloring books)."""
    issues: list[LayoutIssue] = []
    spec = layout.spec
    if len(layout.pages) != len(plan.pages):
        issues.append(
            LayoutIssue(
                "page_count_mismatch",
                "Layout page count differs from the plan.",
                actual=str(len(layout.pages)),
                required=str(len(plan.pages)),
            )
        )
        return tuple(issues)
    errors, _ = page_count_checks(spec, len(layout.pages))
    issues.extend(errors)
    puzzles = {r.id: r.puzzle for r in report.puzzles if r.puzzle is not None} if report else {}
    trim = Box(0.0, 0.0, spec.trim.width, spec.trim.height)
    margins = spec.margins
    spread = {
        p.puzzle.id for p in plan.pages if p.kind is PageKind.PUZZLE_WORDS and p.puzzle is not None
    }

    for position, (page, entry) in enumerate(zip(layout.pages, plan.pages, strict=True)):

        def fail(code: str, message: str, page: PhysicalPage = page) -> None:
            issues.append(
                LayoutIssue(
                    code, message, page=page.plan_index, physical_page=page.number, kind=page.kind
                )
            )

        if (page.number, page.plan_index, page.kind) != (position + 1, entry.index, entry.kind):
            fail("page_order", "Physical page does not match its plan entry.")
        frame = page.frame
        if frame.media != trim or frame.trim != trim:
            fail("invalid_page_geometry", "Media and trim boxes must equal the trim size.")
        recto = page.number % 2 == 1
        content = frame.content
        left, right = content.x, trim.width - content.right
        inside, outside = (left, right) if recto else (right, left)
        if frame.recto != recto or any(
            abs(actual - expected) > EPSILON
            for actual, expected in (
                (inside, margins.inside),
                (outside, margins.outside),
                (content.y, margins.bottom),
                (trim.height - content.top, margins.top),
            )
        ):
            fail("margin_mismatch", "Live area is not mirrored from the specification.")
        expected_folio = entry.number.label if entry.number.displayed else None
        folios = [e for e in page.elements if isinstance(e, TextLine) and e.role == "folio"]
        if page.folio != expected_folio or [f.text for f in folios] != (
            [expected_folio] if expected_folio else []
        ):
            fail("folio_mismatch", "Displayed page number differs from the plan.")
        if entry.kind is PageKind.BLANK and page.elements:
            fail("blank_not_blank", "Intentional blank pages must carry no marks.")
        grids = [e for e in page.elements if isinstance(e, LetterGrid)]
        if entry.kind in (PageKind.PUZZLE, PageKind.PUZZLE_WORDS):
            assert entry.puzzle is not None
            puzzle = puzzles.get(entry.puzzle.id)
            words = [
                e.text for e in page.elements if isinstance(e, TextLine) and e.role == "word_list"
            ]
            # A spread splits one puzzle: the word list on its own page, the grid facing it.
            has_words = entry.kind is PageKind.PUZZLE_WORDS or entry.puzzle.id not in spread
            has_grid = entry.kind is PageKind.PUZZLE
            if (
                puzzle is None
                or [g.rows for g in grids] != ([puzzle.grid.rows] if has_grid else [])
                or any(g.marks or g.emphasized for g in grids)
                or words != ([t.display for t in puzzle.targets] if has_words else [])
            ):
                fail("puzzle_content", "Puzzle grid or word list differs from generation.")
        elif entry.kind is PageKind.SOLUTIONS:
            expected = [puzzles.get(item.puzzle.id) for item in entry.solutions]
            if [g.rows for g in grids] != [p.grid.rows if p else None for p in expected] or any(
                p is None
                or [m.target_id for m in g.marks] != [pl.target_id for pl in p.solution.placements]
                for g, p in zip(grids, expected, strict=True)
            ):
                fail("solution_grouping", "Solution grids differ from the planned group.")
        elif grids:
            fail("unexpected_grid", "Only puzzle and solution pages carry grids.")

        for element in page.elements:
            for code, message in _element_checks(element, content):
                fail(code, message)
        # Panels are background: text may sit on them, but no grid may. Decoration
        # (polygons) keeps to its own reserved box, clear of every content element.
        panels = [e for e in page.elements if isinstance(e, Panel)]
        shapes = [e for e in page.elements if isinstance(e, Polygon)]
        drawn = [e for e in page.elements if not isinstance(e, Panel | Polygon)]
        boxes = [_bounds(e) for e in drawn]
        if any(a.overlaps(b, EPSILON) for a, b in combinations(boxes, 2)):
            fail("element_collision", "Layout elements overlap.")
        if any(_covers(p, g.bounds) for p in panels for g in grids):
            fail("panel_over_grid", "A tinted panel or frame overlaps a puzzle grid.")
        if any(_crosses(p, e.bounds) for p in panels for e in drawn):
            fail("frame_crosses_content", "A frame or banner outline crosses content.")
        if any(s.bounds.overlaps(b, EPSILON) for s in shapes for b in boxes):
            fail("decoration_overlap", "Decoration overlaps text, a grid or a photograph.")
    return tuple(issues)


def _covers(panel: Panel, box: Box) -> bool:
    """A filled panel under `box`, or an outline whose stroke crosses it."""
    if panel.fill_gray is not None:
        return panel.bounds.overlaps(box, EPSILON)
    return _crosses(panel, box)


def _crosses(panel: Panel, box: Box) -> bool:
    """True when a panel's stroke ring passes through `box` (inside or outside is fine)."""
    if panel.stroke_gray is None or not panel.bounds.overlaps(box, EPSILON):
        return False
    inner = panel.box.expanded(-panel.stroke_width / 2 - panel.radius * (1 - 0.7071))
    return not inner.contains(box, EPSILON)


def _bounds(element: Element) -> Box:
    return element.bounds


def _element_checks(element: Element, content: Box) -> Iterator[tuple[str, str]]:
    # Bounds are painted extents: text ink boxes, rule and frame strokes included.
    if not content.contains(element.bounds, EPSILON):
        yield "outside_live_area", f"Element {element.role} extends beyond the margins."
    if isinstance(element, TextLine) and element.size < KDP.min_font_size:
        yield "font_too_small", f"Text {element.role} is below the minimum size."
    if isinstance(element, Rule) and element.width < KDP.min_line_weight:
        yield "line_weight_too_small", f"Rule {element.role} is below the minimum weight."
    if (
        isinstance(element, Panel)
        and element.stroke_gray is not None
        and element.stroke_width < KDP.min_line_weight
    ):
        yield "line_weight_too_small", f"Frame {element.role} is below the minimum weight."
    if isinstance(element, LetterGrid):
        if element.letter_size < KDP.min_font_size:
            yield "font_too_small", "Grid letters are below the minimum size."
        widths = [element.frame_width, *(m.line_width for m in element.marks)]
        if min(widths) < KDP.min_line_weight:
            yield "line_weight_too_small", "Grid strokes are below the minimum weight."
        cells = Box(
            element.origin_x,
            element.top - element.cell * len(element.rows),
            element.cell * element.columns,
            element.cell * len(element.rows),
        )
        if not element.frame.contains(cells, EPSILON):
            yield "invalid_grid_geometry", "Grid cells extend beyond the grid frame."
        for mark in element.marks:
            # Painted capsule ends: the radius plus half the stroke.
            extent = mark.radius + mark.line_width / 2
            for x, y in (mark.start, mark.end):
                outline = Box(x - extent, y - extent, 2 * extent, 2 * extent)
                if not element.frame.contains(outline, EPSILON):
                    yield "invalid_grid_geometry", "A solution mark leaves the grid frame."
