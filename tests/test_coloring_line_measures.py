"""Paper-relative line measures (measures version 2, Interval 8).

The Interval 7 real-artwork review found fine-line retention reported at 47-89 % on
tinted-paper scans whose ink still printed at 99.3-100 % after background cleanup:
the measure read absolute gray levels, so stretching the paper to white counted
every stroke rim lighter than 128 after the stretch as lost. These SYNTHETIC scans
(`aged_scan`) reproduce that case and the genuine losses the measure must still find.
No real artwork is used and no threshold changed.
"""

import pytest
from coloring_helpers import (
    aged_scan,
    dense_pattern,
    encode,
    fine_detail,
    line_art,
    pencil_sketch,
)
from PIL import Image, ImageDraw

from puzzlepress.coloring.prepare import (
    MEASURES_VERSION,
    _measure,
    difference_image,
    paper_background,
    paper_relative,
    prepare_artwork,
)
from puzzlepress.coloring_config import Adjustments

CLEANUP = Adjustments(background_cleanup=0.6, despeckle=2)
LINE_LOSS = {"thin_lines_destroyed", "thin_lines_lost", "detail_lost", "strokes_broken"}


def codes(prepared) -> set[str]:
    return {f.code for f in prepared.findings}


@pytest.fixture(scope="module")
def aged_226() -> bytes:
    return encode(aged_scan(226))


def test_white_paper_reads_exactly_as_before() -> None:
    page = fine_detail()
    assert paper_background(page) is None
    assert paper_relative(page) is page  # Same object: version 1 measures, unchanged.


def test_tinted_paper_is_divided_by_its_own_level() -> None:
    page = aged_scan(226, grain=0, blur=0)
    background = paper_background(page)
    assert background is not None
    low, high = background.getextrema()  # type: ignore[misc]
    assert 220 <= low and high <= 230
    relative = paper_relative(page)
    assert relative.getpixel((5, 5)) == 255  # Paper becomes white,
    assert relative.getpixel((150, 120)) == pytest.approx(70, abs=2)  # ink keeps its ratio.


@pytest.mark.parametrize(
    ("paper", "gradient", "grain"), [(226, 0, 14), (213, 30, 14), (158, 0, 20)]
)
def test_cleanup_of_tinted_scans_is_not_line_loss(paper: int, gradient: int, grain: int) -> None:
    """Interval 7 measured 47-89 % here (version 1 on this fixture: 21-70 %)."""
    prepared = prepare_artwork(encode(aged_scan(paper, gradient=gradient, grain=grain)), CLEANUP)
    m = prepared.measures
    assert m.thin_line_retention is not None and m.thin_line_retention >= 0.95
    assert m.detail_retention is not None and m.detail_retention >= 0.95
    assert not codes(prepared) & LINE_LOSS
    assert "background_tint" not in codes(prepared)  # Cleanup did whiten the paper.


def test_thinning_a_tinted_scan_is_still_destroyed(aged_226: bytes) -> None:
    prepared = prepare_artwork(aged_226, Adjustments(background_cleanup=0.6, line_weight=-1))
    assert prepared.measures.thin_line_retention == 0.0
    assert {"thin_lines_destroyed", "detail_lost"} <= codes(prepared)


def test_lightening_strokes_relative_to_paper_is_line_loss(aged_226: bytes) -> None:
    """Brightness lifts strokes, not just the paper: the ratio to paper falls."""
    prepared = prepare_artwork(aged_226, Adjustments(background_cleanup=0.6, brightness=0.35))
    m = prepared.measures
    assert m.thin_line_retention is not None and m.thin_line_retention < 0.6
    assert "thin_lines_destroyed" in codes(prepared)


def test_erased_line_work_is_detected_where_it_was_erased(aged_226: bytes) -> None:
    """Deliberate damage: half of the 1 and 2 px rules painted out after cleanup."""
    reference = Image.open(__import__("io").BytesIO(aged_226)).convert("L")
    clean = prepare_artwork(aged_226, CLEANUP).image
    damaged = clean.copy()
    ImageDraw.Draw(damaged).rectangle((0, 100, clean.width // 2, 2900), fill=255)
    whole = _measure(reference, clean, 0)
    half = _measure(reference, damaged, 0)
    assert whole.thin_line_retention is not None and whole.thin_line_retention >= 0.95
    assert half.thin_line_retention is not None and 0.3 < half.thin_line_retention < 0.75
    assert half.detail_retention is not None and half.detail_retention < 0.8


def test_dense_engraving_on_tinted_paper_keeps_its_lines_and_reports_ink() -> None:
    page = aged_scan(220, ink=40, blur=0.6, art=dense_pattern())
    prepared = prepare_artwork(encode(page), Adjustments(background_cleanup=0.6))
    m = prepared.measures
    assert m.detail_retention is not None and m.detail_retention >= 0.95
    assert not codes(prepared) & LINE_LOSS
    assert "heavy_ink" in codes(prepared) or m.ink_after <= 0.35


def test_pale_pencil_survives_cleanup_and_a_threshold_still_erases_it() -> None:
    pencil = encode(pencil_sketch(1))
    kept = prepare_artwork(pencil, Adjustments(background_cleanup=0.6))
    assert kept.measures.faint_line_retention == 1.0
    assert "faint_strokes_erased" not in codes(kept)
    erased = prepare_artwork(pencil, Adjustments(threshold=0.5))
    assert "faint_strokes_erased" in codes(erased)


def test_pale_hatching_on_tinted_paper_erased_by_a_threshold_is_reported(aged_226: bytes) -> None:
    """The blurred 1 px hatching never reaches ink darkness: a 0.5 threshold removes it,
    which is a real loss of light strokes, not a rim effect."""
    prepared = prepare_artwork(
        aged_226, Adjustments(background_cleanup=0.6, despeckle=2, threshold=0.5)
    )
    assert "faint_strokes_erased" in codes(prepared)
    assert not codes(prepared) & LINE_LOSS


def test_scanner_blur_rims_are_part_of_the_ink_line() -> None:
    """A black line blurred over two pixels: its gray rim is not a light stroke, so a
    threshold that trims the rim reports nothing."""
    page = aged_scan(255, ink=0, blur=1.2, grain=0, art=line_art(1))
    prepared = prepare_artwork(encode(page), Adjustments(threshold=0.5))
    assert "faint_strokes_erased" not in codes(prepared)


def test_difference_view_does_not_paint_cleanup_as_removal(aged_226: bytes) -> None:
    prepared = prepare_artwork(aged_226, CLEANUP)
    view = difference_image(prepared.reference, prepared.image)
    red = sum(1 for pixel in view.resize((435, 585)).getdata() if pixel == (214, 40, 40))
    assert red < 20


def test_measures_carry_their_version(aged_226: bytes) -> None:
    data = prepare_artwork(aged_226, CLEANUP).measures.to_dict()
    assert data["measures_version"] == MEASURES_VERSION == 3


def test_rim_flicker_is_not_line_loss_but_thinning_still_is(monkeypatch) -> None:
    """Measures version 3 (Interval 10). On the real tinted patent scans, version 2
    reported 86-88 % of fine lines kept after cleanup with every line visibly intact:
    single rim pixels flipped across the ink level. This JPEG-compressed scan-like page
    reproduces the mechanism (strokes inked near the ink level): the 1 px registration
    tolerance removes most of that loss, and thinning still loses every fine line."""
    from puzzlepress.coloring import prepare as module

    data = encode(aged_scan(226, ink=105, blur=0.7, grain=12), "JPEG", quality=60)
    cleanup = Adjustments(background_cleanup=0.6, despeckle=2)
    monkeypatch.setattr(module, "THIN_REGISTRATION", 0)  # Version 2's pixel-exact rule.
    exact = prepare_artwork(data, cleanup).measures.thin_line_retention
    monkeypatch.undo()
    tolerant = prepare_artwork(data, cleanup).measures.thin_line_retention
    assert exact is not None and tolerant is not None
    assert (1 - tolerant) < (1 - exact) / 2  # Most rim flicker is no longer counted.
    thinned = prepare_artwork(data, Adjustments(background_cleanup=0.6, line_weight=-1))
    assert thinned.measures.thin_line_retention == 0.0
    assert "thin_lines_destroyed" in codes(thinned)


def test_a_scan_frame_is_reported_but_art_at_the_edge_is_not() -> None:
    """Interval 10, from the real Otis elevator scan (a black scanner frame, 69-88 % ink
    in the outermost 1 % of every edge). SYNTHETIC: the same drawing with a 30 px black
    frame at its edges, with a thin drawn frame, and with lines that reach the edge."""
    from PIL import ImageDraw

    page = line_art(3)
    framed = page.copy()
    draw = ImageDraw.Draw(framed)
    width, height = framed.size
    for box in ((0, 0, width, 30), (0, height - 30, width, height), (0, 0, 30, height)):
        draw.rectangle(box, fill=0)
    flagged = prepare_artwork(encode(framed), Adjustments())
    found = [f for f in flagged.findings if f.code == "dark_edge_band"]
    assert found and "along the left, top, bottom edge" in found[0].message  # Not right.
    drawn = page.copy()
    ImageDraw.Draw(drawn).rectangle((4, 4, width - 5, height - 5), outline=0, width=6)
    reaching = page.copy()
    ImageDraw.Draw(reaching).line((0, height // 2, width, height // 3), fill=0, width=8)
    for image in (page, drawn, reaching):
        assert "dark_edge_band" not in codes(prepare_artwork(encode(image), Adjustments()))


def test_the_specks_warning_does_not_presume_dust() -> None:
    from puzzlepress.coloring.prepare import _findings

    measures = prepare_artwork(encode(line_art(2)), Adjustments()).measures
    from dataclasses import replace

    found = _findings(replace(measures, specks_per_megapixel_after=40.0), Adjustments())
    message = next(f.message for f in found if f.code == "specks_remaining")
    assert "stippling" in message
