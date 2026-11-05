"""Per-page artwork placement: authored scale and position, still whole and lossless."""

import hashlib
from pathlib import Path

import pytest
from coloring_helpers import composed_coloring_book

from puzzlepress import dump_project, validate_project
from puzzlepress.coloring_config import CENTRED, Placement
from puzzlepress.identity import build_identity
from puzzlepress.interior import DEFAULT_PROFILE, InteriorError, build_interior, print_profile
from puzzlepress.interior.coloring import (
    art_box,
    embedded_images,
    layout_coloring,
    place_art,
    validate_coloring_layout,
)
from puzzlepress.interior.engine import FOLIO_BAND
from puzzlepress.interior.model import Box, ImageBlock
from puzzlepress.interior.spec import PrintSpecification
from puzzlepress.preflight import preflight_interior, read_interior_artifacts
from puzzlepress.project import load_project
from puzzlepress.publication import PageKind

SPEC = print_profile(DEFAULT_PROFILE)
assert isinstance(SPEC, PrintSpecification)
MEDIUM = (1088, 1463)


def place(directory: Path, placements: dict[int, dict | None]) -> Path:
    """Author placements on 0-based page entries of a copy's book.yaml."""
    data = load_project(directory).project.to_dict()
    for index, placement in placements.items():
        entry = data["coloring"]["pages"][index]  # type: ignore[index]
        if placement is None:
            entry.pop("placement", None)
        else:
            entry["placement"] = placement
    project = validate_project(data).require_project()
    (directory / "book.yaml").write_text(dump_project(project), encoding="utf-8")
    return directory


@pytest.fixture
def book(tmp_path: Path) -> Path:
    return composed_coloring_book(tmp_path / "book", 2, size=MEDIUM, border="thin")


def issues(data: dict) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate_project(data).issues}


def test_schema_normalizes_and_bounds_placement(book: Path) -> None:
    data = load_project(book).project.to_dict()
    pages = data["coloring"]["pages"]  # type: ignore[index]
    pages[0]["placement"] = {"scale": 0.75, "x": -1, "y": 0.5}
    project = validate_project(data).require_project()
    assert project.coloring is not None
    assert project.coloring.pages[0].placement == Placement(0.75, -1.0, 0.5)
    assert project.coloring.placements == {1: Placement(0.75, -1.0, 0.5)}
    # Explicit centred placement is no placement: same bytes, same identity.
    plain = load_project(book).project
    pages[0]["placement"] = {"scale": 1, "x": 0, "y": 0}
    centred = validate_project(data).require_project()
    assert centred == plain and dump_project(centred) == dump_project(plain)
    assert build_identity(centred) == build_identity(plain)
    assert "placement" not in dump_project(plain)
    pages[0]["placement"] = {"scale": 0.4, "x": 2, "y": "up", "rotate": 90}
    assert issues(data) == {
        ("coloring.pages.0.placement.scale", "range"),
        ("coloring.pages.0.placement.x", "range"),
        ("coloring.pages.0.placement.y", "type"),
        ("coloring.pages.0.placement.rotate", "unknown_field"),
    }
    pages[0] = {"divider": {"title": "D"}, "placement": {"scale": 0.9}}
    assert ("coloring.pages.0.placement", "unknown_field") in issues(data)


def test_place_art_keeps_the_drawing_whole_inside_its_box() -> None:
    box = Box(100, 100, 400, 600)
    centred, dpi = place_art(box, 1000, 1000)
    assert centred == Box(100, 200, 400, 400) and dpi == pytest.approx(180)
    corner, smaller_dpi = place_art(box, 1000, 1000, Placement(0.5, -1, 1))
    assert corner == Box(100, 500, 200, 200) and smaller_dpi == pytest.approx(360)
    for x in (-1, 0, 1):
        for y in (-1, 0, 1):
            placed, _ = place_art(box, 1000, 1500, Placement(0.6, x, y))
            assert box.contains(placed, 1e-9)
            assert placed.width * 1500 == pytest.approx(placed.height * 1000)


def test_a_placed_page_prints_the_same_pixels_smaller_and_elsewhere(book: Path) -> None:
    before = build_interior(load_project(book).project, SPEC, book)
    place(book, {0: {"scale": 0.6, "x": 1, "y": -1}})
    project = load_project(book).project
    after = build_interior(project, SPEC, book)
    blocks = {
        page.number: element
        for build in (after,)
        for page in build.layout.pages
        for element in page.elements
        if isinstance(element, ImageBlock)
    }
    old = {
        page.number: element
        for page in before.layout.pages
        for element in page.elements
        if isinstance(element, ImageBlock)
    }
    first, second = sorted(blocks)
    assert blocks[second] == old[second]  # The unplaced page is untouched.
    moved, was = blocks[first], old[first]
    assert moved.sha256 == was.sha256 and moved.pixels == was.pixels
    assert moved.placement.width == pytest.approx(was.placement.width * 0.6)
    assert moved.effective_dpi == pytest.approx(was.effective_dpi / 0.6)
    frame = after.layout.pages[first - 1].frame.content
    body = Box(frame.x, frame.y + FOLIO_BAND, frame.width, frame.height - FOLIO_BAND)
    region = art_box(body, project.coloring.layout.border)  # type: ignore[union-attr]
    assert moved.placement.x + moved.placement.width == pytest.approx(region.x + region.width)
    assert moved.placement.y == pytest.approx(region.y)
    # Lossless: the embedded stream decodes to the prepared digest.
    images = embedded_images(after.pdf)
    assert not isinstance(images, Exception)
    assert {image.digest for image in images} == {b.sha256 for b in blocks.values()}
    # Deterministic.
    again = build_interior(load_project(book).project, SPEC, book)
    assert hashlib.sha256(again.pdf).digest() == hashlib.sha256(after.pdf).digest()
    # Placement is layout, not plan (same pages); it is source, so identities differ.
    assert [p.to_dict() for p in after.plan.pages] == [p.to_dict() for p in before.plan.pages]
    assert after.manifest["interior_identity"] != before.manifest["interior_identity"]


def test_preflight_passes_placed_pages_and_rejects_a_misplaced_layout(
    book: Path, tmp_path: Path
) -> None:
    from puzzlepress.interior import write_interior

    place(book, {1: {"scale": 0.8, "x": -0.5, "y": 0.25}})
    project = load_project(book).project
    built = build_interior(project, SPEC, book)
    out = tmp_path / "out"
    write_interior(built, out, book)
    result = preflight_interior(project, read_interior_artifacts(out), source_directory=book)
    placement = next(r for r in result.report.results if r.rule.code == "coloring_art_placement")
    assert placement.outcome.value == "passed" and result.report.structurally_valid
    # The same layout judged against other placements is reported, never accepted.
    content, plan = built.report, built.plan
    from puzzlepress.coloring.content import ColoringContent

    assert isinstance(content, ColoringContent)
    border = project.coloring.layout.border  # type: ignore[union-attr]
    wrong = validate_coloring_layout(built.layout, plan, content, border, {})
    assert [i.code for i in wrong] == ["artwork_placement"]
    entry = next(p.artwork.entry for p in plan.pages if p.kind is PageKind.COLORING and p.artwork)
    laid = layout_coloring(plan, content, SPEC, border, {entry: Placement(0.5, 1, 1)})
    assert validate_coloring_layout(laid, plan, content, border, {entry: CENTRED})


def test_placement_never_crops_or_errors_at_its_bounds(book: Path) -> None:
    place(book, {0: {"scale": 0.5, "x": -1, "y": -1}, 1: {"scale": 0.5, "x": 1, "y": 1}})
    try:
        build_interior(load_project(book).project, SPEC, book)
    except InteriorError as error:  # pragma: no cover - a failure here is the bug
        pytest.fail(f"placement at its bounds failed: {error.issues}")
