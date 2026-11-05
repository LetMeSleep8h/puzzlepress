"""Physical units, KDP constraints, print-spec validation and pure geometry."""

from dataclasses import replace
from itertools import combinations

import pytest

from puzzlepress.interior.engine import page_count_checks
from puzzlepress.interior.fonts import ASCENT, DESCENT, text_width
from puzzlepress.interior.geometry import (
    GRID_PADDING,
    fit_grid,
    max_cell_for_letter,
    page_frame,
    solution_slots,
    solution_template,
)
from puzzlepress.interior.issues import LayoutIssue
from puzzlepress.interior.model import Anchor, Box, Face
from puzzlepress.interior.spec import (
    KDP,
    PAPERBACK_LETTER,
    PROFILES,
    Ink,
    Margins,
    Paper,
    Strokes,
    TrimSize,
    Typography,
    inches,
    print_profile,
    to_inches,
    validate_print_spec,
)
from puzzlepress.interior.text import text_line, wrap_text

SPEC = PAPERBACK_LETTER
TOL = 1e-9


def codes(issues):
    return [issue.code for issue in issues]


def test_units_convert_once_and_exactly():
    assert inches(1) == 72 and inches(8.5) == 612 and inches(11) == 792
    assert inches(0.375) == 27 and inches(0.125) == 9
    assert to_inches(54) == 0.75


def test_default_profile_is_letter_without_bleed():
    assert print_profile("paperback-8.5x11") is SPEC
    assert (SPEC.trim.width, SPEC.trim.height, SPEC.bleed) == (612, 792, False)
    assert SPEC.margins == Margins(54, 36, 45, 45)
    assert validate_print_spec(SPEC) == ()
    assert codes([print_profile("6x9")]) == ["unsupported_profile"]


def test_profiles_state_ink_and_paper_explicitly():
    cream = print_profile("paperback-8.5x11-cream")
    assert not isinstance(cream, LayoutIssue)
    assert (SPEC.profile_version, SPEC.ink, SPEC.paper) == (2, Ink.BLACK, Paper.WHITE)
    assert (cream.profile_version, cream.ink, cream.paper) == (1, Ink.BLACK, Paper.CREAM)
    assert SPEC.to_dict()["paper"] == "white" and cream.to_dict()["paper"] == "cream"
    assert SPEC.to_dict()["ink"] == cream.to_dict()["ink"] == "black"
    # Paper changes no page geometry; only the spine width of a cover depends on it.
    assert (cream.trim, cream.margins, cream.bleed) == (SPEC.trim, SPEC.margins, SPEC.bleed)
    assert validate_print_spec(cream) == ()
    assert sorted(PROFILES) == sorted(
        f"paperback-{trim}{paper}{bleed}"
        for trim in ("8.5x11", "6x9", "8x10", "8.5x8.5")
        for paper in ("", "-cream")
        for bleed in ("", "-bleed")  # Full-bleed profiles (Interval 9).
    )


@pytest.mark.parametrize(
    ("pages", "gutter"),
    [(1, 0.375), (24, 0.375), (150, 0.375), (151, 0.5), (300, 0.5), (301, 0.625)]
    + [(500, 0.625), (501, 0.75), (700, 0.75), (701, 0.875), (828, 0.875)],
)
def test_kdp_gutter_table(pages, gutter):
    assert KDP.required_gutter(pages) == inches(gutter)


def test_gutter_and_page_count_are_checked_against_physical_count():
    assert KDP.required_gutter(829) is None
    narrow = replace(SPEC, margins=replace(SPEC.margins, inside=inches(0.375)))
    assert page_count_checks(narrow, 150) == ((), ())
    errors, _ = page_count_checks(narrow, 151)
    assert codes(errors) == ["gutter_too_small"]
    assert (errors[0].actual, errors[0].required) == ("0.375 in", "0.5 in")
    errors, warnings = page_count_checks(SPEC, 11)
    assert errors == () and codes(warnings) == ["kdp_minimum_page_count"]
    assert warnings[0].actual == "11"
    assert codes(page_count_checks(SPEC, 701)[0]) == ["gutter_too_small"]
    assert codes(page_count_checks(SPEC, 829)[0]) == ["page_count_unsupported"]
    assert page_count_checks(SPEC, 24) == ((), ())


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"margins": Margins(inches(0.25), 36, 45, 45)}, "gutter_too_small"),
        ({"margins": Margins(54, inches(0.2), 45, 45)}, "margin_too_small"),
        ({"margins": Margins(54, 36, 10, 45)}, "margin_too_small"),
        ({"margins": Margins(54, 36, 45, 17.9)}, "margin_too_small"),
        ({"margins": Margins(300, 200, 45, 45)}, "invalid_page_geometry"),
        ({"bleed": True, "margins": Margins(54, 26, 45, 45)}, "margin_too_small"),
        ({"trim": TrimSize("7x10", inches(7), inches(10))}, "unsupported_trim_size"),
        ({"typography": Typography(body=6.5)}, "font_too_small"),
        ({"typography": Typography(solution_letter_min=6.9)}, "font_too_small"),
        ({"typography": Typography(grid_letter_min=25)}, "invalid_typography"),
        ({"strokes": Strokes(rule=0.5)}, "line_weight_too_small"),
        ({"strokes": Strokes(solution_mark=0.7)}, "line_weight_too_small"),
    ],
)
def test_invalid_print_specifications_are_rejected(change, code):
    issues = validate_print_spec(replace(SPEC, **change))
    assert code in codes(issues)
    assert all(issue.region and issue.region.startswith("print.") for issue in issues)


def test_bleed_raises_the_outside_margin_minimum():
    """Interval 9: full bleed is a valid specification; KDP's 0.375 in minimum for
    outside, top and bottom margins applies (0.25 in without bleed)."""
    spec = replace(SPEC, bleed=True, margins=Margins(54, inches(0.3), 45, 45))
    issues = validate_print_spec(spec)
    assert codes(issues) == ["margin_too_small"]
    assert issues[0].required == "0.375 in"
    assert codes(validate_print_spec(replace(SPEC, margins=spec.margins))) == []
    assert validate_print_spec(replace(SPEC, bleed=True)) == ()


def test_recto_and_verso_mirror_inside_and_outside_margins():
    recto, verso = page_frame(SPEC, 1), page_frame(SPEC, 2)
    trim = Box(0, 0, 612, 792)
    for frame in (recto, verso):
        assert frame.media == trim and frame.trim == trim
        assert (frame.content.width, frame.content.height) == (522, 702)
        assert (frame.content.y, 792 - frame.content.top) == (45, 45)
    assert recto.recto and not verso.recto
    # Recto: binding (inside) is the left edge. Verso: binding is the right edge.
    assert recto.content.x == 54 and 612 - recto.content.right == 36
    assert verso.content.x == 36 and 612 - verso.content.right == 54
    assert page_frame(SPEC, 3) == recto and page_frame(SPEC, 10) == verso


def test_asymmetric_margins_expose_mirroring_bugs():
    spec = replace(SPEC, margins=Margins(inches(1), inches(0.25), 45, 45))
    assert page_frame(spec, 7).content.x == 72
    assert page_frame(spec, 8).content.x == 18
    assert page_frame(spec, 8).content.right == 612 - 72


@pytest.mark.parametrize(("columns", "rows"), [(5, 5), (10, 8), (8, 10), (15, 15), (20, 12)])
@pytest.mark.parametrize("stroke", [0.75, 1.0, 2.0])
def test_grid_cells_are_square_centered_and_paint_inside_the_region(columns, rows, stroke):
    region = Box(54, 100, 522, 500)
    geometry = fit_grid(columns, rows, region, 20, stroke, max_cell_for_letter(20))
    span_x, span_y = columns + 2 * GRID_PADDING, rows + 2 * GRID_PADDING
    expected = min((522 - stroke) / span_x, (500 - stroke) / span_y, max_cell_for_letter(20))
    assert abs(geometry.cell - expected) < TOL
    frame, painted = geometry.frame, geometry.bounds
    assert abs(frame.width - geometry.cell * span_x) < TOL
    assert abs(frame.height - geometry.cell * span_y) < TOL
    # The stroke is centered on the frame: half of it paints outside.
    half = stroke / 2
    assert (painted.x, painted.y) == (frame.x - half, frame.y - half)
    assert (painted.right, painted.top) == pytest.approx((frame.right + half, frame.top + half))
    assert region.contains(painted, TOL)
    assert abs((frame.x - region.x) - (region.right - frame.right)) < TOL  # centered
    assert abs(painted.top - region.top) < TOL  # top-aligned by painted extent
    assert abs(geometry.origin_x - (frame.x + geometry.cell * GRID_PADDING)) < TOL
    assert geometry.letter_size <= 20 and geometry.letter_size <= geometry.cell * 0.56 + TOL


@pytest.mark.parametrize(("columns", "rows"), [(14, 14), (25, 10), (8, 30)])
def test_a_grid_limited_by_the_region_paints_exactly_to_its_edge(columns, rows):
    """The cover-demo defect: a width-limited frame used to overhang by half its stroke."""
    region = Box(36, 69, 522, 600)
    geometry = fit_grid(columns, rows, region, 20, 1.0, max_cell_for_letter(20))
    painted = geometry.bounds
    assert region.contains(painted, 1e-9)
    limited = (painted.x, painted.right) if columns >= rows else (painted.y, painted.top)
    edges = (region.x, region.right) if columns >= rows else (region.y, region.top)
    assert limited == pytest.approx(edges, abs=1e-9)
    assert not region.contains(geometry.frame.expanded(0.5 + 1e-6), 1e-9)


def test_grid_letters_scale_down_and_report_tiny_sizes():
    region = Box(54, 69, 522, 600)
    assert fit_grid(10, 10, region, 20, 1.0, max_cell_for_letter(20)).letter_size == 20
    large = fit_grid(50, 50, region, 20, 1.0, max_cell_for_letter(20))
    assert large.letter_size < 9  # Callers must reject this against the profile minimum.
    moved = large.moved(-10)
    assert moved.frame.y == large.frame.y - 10 and moved.top == large.top - 10
    assert moved.stroke == large.stroke and moved.bounds.y == large.bounds.y - 10


@pytest.mark.parametrize(("density", "shape"), [(1, (1, 1)), (2, (1, 2)), (4, (2, 2)), (6, (2, 3))])
def test_solution_templates_tile_the_region_in_reading_order(density, shape):
    region = Box(54, 69, 522, 600)
    slots = solution_slots(density, region, 24, 20)
    assert len(slots) == density
    columns, rows = shape
    assert len({round(s.x, 6) for s in slots}) == columns
    assert len({round(s.y, 6) for s in slots}) == rows
    assert all(region.contains(slot, TOL) for slot in slots)
    assert not any(a.overlaps(b, TOL) for a, b in combinations(slots, 2))
    assert [(round(-s.top, 6), round(s.x, 6)) for s in slots] == sorted(
        (round(-s.top, 6), round(s.x, 6)) for s in slots
    )
    assert abs(slots[0].top - region.top) < TOL and abs(slots[-1].y - region.y) < TOL


def test_solution_template_never_shrinks_a_planned_group():
    assert [solution_template(n) for n in range(1, 9)] == [1, 2, 4, 4, 6, 6, 8, 8]
    with pytest.raises(ValueError):
        solution_template(9)


def test_wrapping_keeps_authored_breaks_and_rejects_unbreakable_words():
    wrapped = wrap_text("One two  three\n\nfour", Face.REGULAR, 12, 1000)
    assert wrapped.lines == ("One two three", "", "four") and wrapped.overflow_word is None
    narrow = wrap_text(
        "alpha beta gamma delta", Face.REGULAR, 12, text_width("gamma delta", Face.REGULAR, 12)
    )
    assert narrow.lines == ("alpha beta", "gamma delta")
    assert all(
        text_width(line, Face.REGULAR, 12) <= text_width("gamma delta", Face.REGULAR, 12)
        for line in narrow.lines
    )
    failed = wrap_text("short " + "x" * 80, Face.REGULAR, 12, 100)
    assert failed.overflow_word == "x" * 80 and failed.overflow_width > 100
    assert wrap_text("a b c", Face.BOLD, 9, 50) == wrap_text("a b c", Face.BOLD, 9, 50)


@pytest.mark.parametrize("anchor", list(Anchor))
def test_text_bounds_follow_anchor_and_font_extents(anchor):
    line = text_line("t", "WIDE", Face.REGULAR, 10, 100, 200, anchor)
    width = text_width("WIDE", Face.REGULAR, 10)
    expected = {Anchor.START: 100, Anchor.MIDDLE: 100 - width / 2, Anchor.END: 100 - width}
    assert abs(line.bounds.x - expected[anchor]) < TOL
    assert abs(line.bounds.y - (200 - DESCENT * 10)) < TOL
    assert abs(line.bounds.top - (200 + ASCENT * 10)) < TOL
