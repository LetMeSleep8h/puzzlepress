"""Full-wrap geometry: KDP formula, spine width, eligibility, safe areas, barcode."""

import pytest

from puzzlepress.cover.geometry import cover_geometry
from puzzlepress.cover.issues import CoverError
from puzzlepress.interior.spec import KDP_COVER, Paper, inches, to_inches

TOL = 1e-9
W, H = inches(8.5), inches(11)


def wrap(pages, paper=Paper.WHITE):
    return cover_geometry(pages, W, H, paper)


def test_kdp_cover_constants_and_unit_conversion():
    assert KDP_COVER.bleed == inches(0.125) == 9
    assert KDP_COVER.text_safe_inset == 9 and KDP_COVER.spine_text_clearance == 4.5
    assert (KDP_COVER.barcode_width, KDP_COVER.barcode_height) == (144, pytest.approx(86.4))
    assert dict(KDP_COVER.spine_per_page) == {Paper.WHITE: 0.002252, Paper.CREAM: 0.0025}
    assert KDP_COVER.min_image_dpi == 300 and KDP_COVER.spine_text_min_pages == 80
    assert to_inches(inches(0.0625)) == 0.0625


@pytest.mark.parametrize(
    ("pages", "paper", "spine_in"),
    [
        (1, Paper.WHITE, 0.002252),
        (11, Paper.WHITE, 0.024772),
        (24, Paper.WHITE, 0.054048),
        (24, Paper.CREAM, 0.06),
        (79, Paper.WHITE, 0.177908),
        (80, Paper.CREAM, 0.2),
        (300, Paper.CREAM, 0.75),
        (550, Paper.WHITE, 1.2386),
    ],
)
def test_spine_width_is_page_count_times_paper_thickness(pages, paper, spine_in):
    g = wrap(pages, paper)
    assert to_inches(g.spine_width) == pytest.approx(spine_in, abs=TOL)
    assert g.spine_width == pytest.approx(KDP_COVER.spine_width(pages, paper), abs=TOL)


@pytest.mark.parametrize(("pages", "paper"), [(11, Paper.WHITE), (300, Paper.CREAM)])
def test_wrap_formula_and_region_order(pages, paper):
    g = wrap(pages, paper)
    bleed, spine = 9.0, g.spine_width
    assert g.media.width == pytest.approx(bleed + W + spine + W + bleed, abs=TOL)
    assert g.media.height == pytest.approx(bleed + H + bleed, abs=TOL)
    assert (g.media.x, g.media.y) == (0, 0)
    # Left to right: bleed | back | spine | front | bleed.
    assert g.back.x == bleed and g.back.width == W
    assert g.spine.x == pytest.approx(bleed + W) and g.spine.width == pytest.approx(spine)
    assert g.front.x == pytest.approx(bleed + W + spine) and g.front.width == W
    assert g.media.right - g.front.right == pytest.approx(bleed)
    for panel in (g.back, g.spine, g.front):
        assert (panel.y, panel.height) == (bleed, H)
    assert (g.trim.x, g.trim.y, g.trim.right, g.trim.top) == pytest.approx(
        (bleed, bleed, g.front.right, bleed + H)
    )


def test_exact_wrap_size_for_a_300_page_cream_book():
    g = wrap(300, Paper.CREAM)
    assert to_inches(g.media.width) == pytest.approx(18.0, abs=TOL)
    assert to_inches(g.media.height) == pytest.approx(11.25, abs=TOL)
    data = g.to_dict()
    assert (data["width_in"], data["height_in"], data["spine_width_in"]) == (18.0, 11.25, 0.75)


@pytest.mark.parametrize(("pages", "allowed"), [(24, False), (79, False), (80, True), (500, True)])
def test_spine_text_eligibility_uses_the_stricter_kdp_reading(pages, allowed):
    assert wrap(pages).spine_text_allowed is allowed


def test_safe_areas_are_exact_insets():
    g = wrap(300, Paper.CREAM)
    for panel, safe in ((g.front, g.front_safe), (g.back, g.back_safe)):
        assert (safe.x - panel.x, safe.y - panel.y) == (9, 9)
        assert (panel.right - safe.right, panel.top - safe.top) == pytest.approx((9, 9))
    assert g.spine_safe.x - g.spine.x == pytest.approx(4.5)
    assert g.spine.right - g.spine_safe.right == pytest.approx(4.5)
    assert (g.spine_safe.y - g.spine.y, g.spine.top - g.spine_safe.top) == pytest.approx((9, 9))
    assert g.front_design.x - g.front.x == 36 and g.front.top - g.front_design.top == 36
    assert g.front_safe.contains(g.front_design, TOL)


def test_barcode_region_sits_in_the_back_covers_lower_right_corner():
    g = wrap(300, Paper.CREAM)
    b, keep = g.barcode, g.barcode_keep_clear
    assert (b.width, b.height) == pytest.approx((144, 86.4))
    assert g.back.right - b.right == pytest.approx(18) and b.y - g.back.y == pytest.approx(18)
    assert keep.contains(b, TOL) and g.back.contains(keep, TOL)
    # The reserved corner runs to the bottom trim and the spine fold.
    assert keep.y == g.back.y and keep.right == pytest.approx(g.back.right)
    assert keep.top == pytest.approx(b.top + 9) and b.x - keep.x == pytest.approx(9)
    assert not keep.overlaps(g.spine, TOL)


def test_invalid_inputs_fail_in_the_geometry_stage():
    for call in (lambda: wrap(0), lambda: cover_geometry(10, inches(7), inches(10), Paper.WHITE)):
        with pytest.raises(CoverError) as error:
            call()
        assert error.value.stage == "geometry"
    with pytest.raises(CoverError) as error:
        cover_geometry(10, inches(7), inches(10), Paper.WHITE)
    assert error.value.issues[0].code == "unsupported_trim_size"
