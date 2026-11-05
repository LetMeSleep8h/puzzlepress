"""Full-bleed coloring interiors (Interval 9). Every drawing is SYNTHETIC.

KDP ("Set Trim Size, Bleed, and Margins", read 2026-11-05): bleed is 0.125 in beyond
the trim at the top, bottom and outside edge, none at the inside edge; the page is
0.125 in wider and 0.25 in taller than the trim; outside, top and bottom margins are
at least 0.375 in with bleed.
"""

import io
from pathlib import Path

import pytest
from coloring_helpers import composed_coloring_book
from PIL import Image
from pypdf import PdfReader

from puzzlepress import dump_project, load_project, validate_project
from puzzlepress.cover.geometry import cover_geometry
from puzzlepress.interior import InteriorError, build_interior, write_interior
from puzzlepress.interior.coloring import (
    bleed_crop,
    embedded_images,
    fill_box,
    place_fill,
)
from puzzlepress.interior.geometry import page_frame
from puzzlepress.interior.model import Box, ImageBlock
from puzzlepress.interior.spec import KDP, PROFILES, inches
from puzzlepress.preflight import preflight_interior, read_interior_artifacts

BLEED = "paperback-8.5x11-bleed"
SIZE = (1088, 1463)


def book(tmp_path: Path, placements: dict[int, dict], profile: str = BLEED) -> Path:
    """A 3-drawing SYNTHETIC book; `placements` by artwork order (0, 1, 2)."""
    directory = composed_coloring_book(tmp_path / "book", 3, size=SIZE)
    data = load_project(directory).project.to_dict()
    data["print"] = {"profile": profile}
    data.setdefault("composition", {}).setdefault("page_numbers", {})["show_artwork"] = False
    art = [p for p in data["coloring"]["pages"] if "artwork" in p]
    for index, placement in placements.items():
        art[index]["placement"] = placement
    project = validate_project(data).require_project()
    (directory / "book.yaml").write_text(dump_project(project), encoding="utf-8")
    return directory


def boxes(page: object) -> dict[str, list[float]]:
    return {
        name: [round(float(v), 3) for v in getattr(page, name)]
        for name in ("mediabox", "trimbox", "bleedbox")
    }


# ---------------------------------------------------------------- geometry


@pytest.mark.parametrize("profile", [p for p in PROFILES if p.endswith("-bleed")])
def test_every_bleed_profile_has_kdp_page_boxes_by_parity(profile: str) -> None:
    spec = PROFILES[profile]
    width, height = spec.trim.width, spec.trim.height
    for number in (1, 2, 3, 4):
        frame = page_frame(spec, number)
        assert (frame.media.width, frame.media.height) == (width + 9, height + 18)
        assert frame.trim == Box(0.0 if frame.recto else 9.0, 9.0, width, height)
        # The binding edge has no bleed; the outside, top and bottom have 0.125 in.
        inside = (
            frame.trim.x - frame.media.x if frame.recto else frame.media.right - frame.trim.right
        )
        outside = frame.media.right - frame.trim.right if frame.recto else frame.trim.x
        assert (inside, outside) == (0.0, 9.0)
        assert frame.trim.y - frame.media.y == frame.media.top - frame.trim.top == 9.0
        # Margins from the trim box, at least KDP's 0.375 in with bleed.
        content = frame.content
        left = content.x - frame.trim.x
        right = frame.trim.right - content.right
        assert (left, right) == (
            (spec.margins.inside, spec.margins.outside)
            if frame.recto
            else (spec.margins.outside, spec.margins.inside)
        )
        assert min(spec.margins.outside, spec.margins.top, spec.margins.bottom) >= inches(0.375)


def test_no_bleed_frames_are_unchanged() -> None:
    spec = PROFILES["paperback-8.5x11"]
    for number in (1, 2):
        frame = page_frame(spec, number)
        assert frame.media == frame.trim == Box(0, 0, 612, 792)


def test_the_pdf_carries_the_boxes_the_layout_planned(tmp_path: Path) -> None:
    directory = book(tmp_path, {0: {"fit": "fill"}})
    project = load_project(directory).project
    build = build_interior(project, PROFILES[BLEED], directory)
    reader = PdfReader(io.BytesIO(build.pdf))
    assert len(reader.pages) == len(build.layout.pages)
    for page, planned in zip(reader.pages, build.layout.pages, strict=True):
        frame = planned.frame
        found = boxes(page)
        assert found["mediabox"] == found["bleedbox"] == [0, 0, 621.0, 810.0]
        assert found["trimbox"] == [frame.trim.x, 9.0, frame.trim.right, 801.0]
        assert frame.trim.x == (0.0 if planned.number % 2 else 9.0)


# ---------------------------------------------------------------- fill placement


def test_fill_covers_the_bleed_and_stops_at_the_inside_margin() -> None:
    spec = PROFILES[BLEED]
    recto, verso = page_frame(spec, 1), page_frame(spec, 2)
    a, b = fill_box(recto, spec), fill_box(verso, spec)
    assert (a.x, a.right, a.y, a.top) == (spec.margins.inside, 621.0, 0.0, 810.0)
    assert (b.x, b.right, b.y, b.top) == (0.0, 9.0 + 612 - spec.margins.inside, 0.0, 810.0)


@pytest.mark.parametrize(("x", "y"), [(-1, -1), (0, 0), (1, 1), (-1, 1)])
def test_place_fill_covers_its_box_uniformly_and_keeps_the_chosen_edges(x: int, y: int) -> None:
    from puzzlepress.coloring_config import Fit, Placement

    box = Box(54, 0, 567, 810)
    placed, dpi = place_fill(box, 1000, 1000, Placement(1.4, x, y, Fit.FILL))
    assert placed.contains(box, 1e-6)
    assert abs(placed.width - placed.height) < 1e-9  # A square drawing stays square.
    assert abs(dpi - 1000 * 72 / placed.width) < 1e-9
    if x == -1:
        assert abs(placed.x - box.x) < 1e-9  # Left edge of the drawing kept.
    if x == 1:
        assert abs(placed.right - box.right) < 1e-9
    if y == 1:
        assert abs(placed.top - box.top) < 1e-9


def test_a_filling_drawing_is_clipped_whole_and_lossless(tmp_path: Path) -> None:
    directory = book(tmp_path, {0: {"fit": "fill", "scale": 1.2, "x": 0.5}})
    project = load_project(directory).project
    build = build_interior(project, PROFILES[BLEED], directory)
    filled = [
        (page, e)
        for page in build.layout.pages
        for e in page.elements
        if isinstance(e, ImageBlock) and e.bleed
    ]
    assert len(filled) == 1
    page, block = filled[0]
    assert block.box == fill_box(page.frame, PROFILES[BLEED])
    assert block.placement.contains(block.box, 1e-6)
    # The embedded image is the whole prepared drawing, decoded back pixel for pixel.
    images = embedded_images(build.pdf)
    assert not isinstance(images, type(None))
    digests = {image.digest for image in images}  # type: ignore[union-attr]
    assert block.sha256 in digests


def test_contained_drawings_on_a_bleed_page_print_the_same_pixels(tmp_path: Path) -> None:
    directory = book(tmp_path, {})
    project = load_project(directory).project
    plain = build_interior(project, PROFILES["paperback-8.5x11"], directory)
    bleed = build_interior(project, PROFILES[BLEED], directory)
    for a, b in zip(plain.layout.pages, bleed.layout.pages, strict=True):
        dx, dy = b.frame.trim.x, b.frame.trim.y
        for e, f in zip(a.elements, b.elements, strict=True):
            if isinstance(e, ImageBlock):
                assert isinstance(f, ImageBlock) and not f.bleed and e.sha256 == f.sha256
                assert abs(f.placement.x - e.placement.x - dx) < 1e-6
                assert abs(f.placement.y - e.placement.y - dy) < 1e-6
                assert (f.placement.width, f.placement.height) == (
                    e.placement.width,
                    e.placement.height,
                )


def test_bleed_builds_are_deterministic(tmp_path: Path) -> None:
    directory = book(tmp_path, {0: {"fit": "fill"}, 2: {"fit": "fill", "y": 1}})
    project = load_project(directory).project
    first = build_interior(project, PROFILES[BLEED], directory)
    second = build_interior(project, PROFILES[BLEED], directory)
    assert first.pdf == second.pdf and first.manifest == second.manifest


# ---------------------------------------------------------------- refusals


def test_fill_without_a_bleed_profile_is_refused_not_converted(tmp_path: Path) -> None:
    directory = book(tmp_path, {0: {"fit": "fill"}}, profile="paperback-8.5x11")
    project = load_project(directory).project
    with pytest.raises(InteriorError) as raised:
        build_interior(project, PROFILES["paperback-8.5x11"], directory)
    assert [i.code for i in raised.value.issues] == ["fill_needs_bleed"]


def test_a_page_number_over_a_filling_drawing_is_refused(tmp_path: Path) -> None:
    directory = book(tmp_path, {0: {"fit": "fill"}})
    data = load_project(directory).project.to_dict()
    data["composition"]["page_numbers"]["show_artwork"] = True
    (directory / "book.yaml").write_text(
        dump_project(validate_project(data).require_project()), encoding="utf-8"
    )
    with pytest.raises(InteriorError) as raised:
        build_interior(load_project(directory).project, PROFILES[BLEED], directory)
    assert {i.code for i in raised.value.issues} == {"folio_over_bleed_art"}


@pytest.mark.parametrize(
    ("placement", "code"),
    [
        ({"fit": "fill", "scale": 0.8}, "range"),  # Fill zooms in only (1..3).
        ({"fit": "fill", "scale": 3.5}, "range"),
        ({"fit": "contain", "scale": 1.5}, "range"),  # Contain shrinks only (0.5..1).
        ({"fit": "stretch"}, "enum"),
        ({"fit": "fill", "x": 2}, "range"),
    ],
)
def test_fill_placement_values_are_validated(tmp_path: Path, placement: dict, code: str) -> None:
    directory = composed_coloring_book(tmp_path / "book", 1, size=SIZE)
    data = load_project(directory).project.to_dict()
    page = next(p for p in data["coloring"]["pages"] if "artwork" in p)
    page["placement"] = placement
    result = validate_project(data)
    assert result.project is None
    assert code in [i.code for i in result.issues]


def test_fill_is_written_only_when_set(tmp_path: Path) -> None:
    directory = book(tmp_path, {0: {"fit": "fill", "scale": 1.5}, 1: {"scale": 0.8}})
    text = (directory / "book.yaml").read_text(encoding="utf-8")
    assert text.count("fit: fill") == 1 and "fit: contain" not in text


def test_word_search_books_cannot_choose_a_bleed_profile() -> None:
    from tests.helpers import DEMO

    data = load_project(DEMO).project.to_dict()
    data["print"] = {"profile": BLEED}
    result = validate_project(data)
    assert result.project is None
    assert "bleed_not_for_engine" in [i.code for i in result.issues]


# ---------------------------------------------------------------- crop measure


def test_the_crop_measure_matches_hand_computed_geometry() -> None:
    """A 100 x 100 px drawing with ink in its left half only (x 0..50), one point per
    pixel, clipped to x 25..100: half the ink is hidden; of the rest, x 25..35 is beyond
    the trim (35..100) and x 35..45 outside the safe area (45..100)."""
    image = Image.new("L", (100, 100), 255)
    image.paste(0, (0, 0, 50, 100))  # Ink: the left half (5000 px).
    placement = Box(0, 0, 100, 100)  # One point per pixel.
    block = ImageBlock(
        "coloring_art",
        Box(25, 0, 75, 100),
        "sha256-x",
        placement,
        (0, 0, 100, 100),
        72,
        72,
        bleed=True,
    )
    crop = bleed_crop(image, block, trim=Box(35, 0, 65, 100), safe=Box(45, 0, 55, 100))
    assert crop.ink_pixels == 5000
    assert crop.hidden == 0.5  # x 0..25 clipped away.
    assert crop.trimmed == 0.2  # x 25..35: in the clip, beyond the trim.
    assert crop.unsafe == 0.2  # x 35..45: inside the trim, outside the safe area.
    assert crop.visible_area == 0.75  # 75 of 100 columns are inside the clip.


def test_preflight_reports_what_trimming_cuts_and_stays_quiet_otherwise(tmp_path: Path) -> None:
    directory = book(tmp_path, {0: {"fit": "fill"}, 1: {"fit": "fill", "scale": 2.5, "x": -1}})
    project = load_project(directory).project
    build = build_interior(project, PROFILES[BLEED], directory)
    write_interior(build, tmp_path / "out", directory)
    report = preflight_interior(
        project, read_interior_artifacts(tmp_path / "out"), build, source_directory=directory
    ).report
    assert report.structurally_valid
    bleed = [f for f in report.findings if f.rule.code == "coloring_bleed_art"]
    pages = {f.page.physical_page for f in bleed if f.page}
    zoomed = [
        p.number for p in build.layout.pages if any(getattr(e, "bleed", False) for e in p.elements)
    ]
    assert pages and pages <= set(zoomed)
    assert any("cropped off the page" in f.message for f in bleed)
    codes = {f.rule.code for f in report.findings}
    assert not codes & {
        "page_boxes",
        "kdp_page_size",
        "kdp_outside_margins",
        "kdp_gutter",
        "kdp_no_printer_marks",
        "content_in_live_area",
        "coloring_art_placement",
    }


# ---------------------------------------------------------------- cover and publishing


def test_the_cover_wraps_a_bleed_interior_like_its_no_bleed_twin() -> None:
    """The cover depends on trim, page count and paper; bleed changes none of them."""
    for profile in [p for p in PROFILES if p.endswith("-bleed")]:
        spec, twin = PROFILES[profile], PROFILES[profile.removesuffix("-bleed")]
        a = cover_geometry(120, spec.trim.width, spec.trim.height, spec.paper)
        b = cover_geometry(120, twin.trim.width, twin.trim.height, twin.paper)
        assert a == b


def test_the_kdp_checklist_names_the_bleed_setting() -> None:
    from puzzlepress.publishing.submission import bleed_setting

    assert bleed_setting({"interior_bleed": True}).startswith("Bleed settings: Bleed (PDF only)")
    assert bleed_setting({"interior_bleed": False}).startswith("Bleed settings: No bleed")
    assert KDP.interior_bleed == inches(0.125)
