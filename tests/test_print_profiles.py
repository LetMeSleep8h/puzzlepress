"""The added paperback profiles: KDP sizes, shared margins, real builds on each trim."""

from pathlib import Path

import pytest
from coloring_helpers import composed_coloring_book

from puzzlepress.cover.geometry import cover_geometry
from puzzlepress.interior import PROFILES, InteriorError, build_interior, write_interior
from puzzlepress.interior.spec import KDP, SUPPORTED_TRIMS, Paper, inches, validate_print_spec
from puzzlepress.preflight import preflight_interior, read_interior_artifacts
from puzzlepress.project import load_project
from puzzlepress.publication import PageKind
from tests.helpers import DEMO

ADDED = [
    pid for pid in PROFILES if not pid.startswith("paperback-8.5x11") and not PROFILES[pid].bleed
]
BLEED = [pid for pid in PROFILES if PROFILES[pid].bleed]


def test_added_profiles_are_kdp_sizes_with_the_letter_gutter() -> None:
    assert [t.name for t in SUPPORTED_TRIMS] == ["8.5x11", "6x9", "8x10", "8.5x8.5"]
    assert len(ADDED) == 6
    letter = PROFILES["paperback-8.5x11"]
    for pid in ADDED:
        spec = PROFILES[pid]
        assert validate_print_spec(spec) == ()
        assert not spec.bleed and spec.ink.value == "black"
        assert spec.paper is (Paper.CREAM if pid.endswith("-cream") else Paper.WHITE)
        assert KDP.trim_supported(spec.trim.width, spec.trim.height)
        assert KDP.max_pages_for(spec.trim.name, spec.paper) is not None
        # Same gutter as 8.5 x 11 (KDP's minimum up to 700 pages) and outside margin.
        assert spec.margins.inside == letter.margins.inside == inches(0.75)
        assert spec.margins.outside >= KDP.min_outside_margin
    # 8.5 x 11 is untouched.
    assert letter.profile_version == 2 and letter.trim.width == inches(8.5)


@pytest.mark.parametrize("pid", ADDED)
def test_word_search_builds_and_passes_structural_checks(pid: str, tmp_path: Path) -> None:
    project = load_project(DEMO).project
    build = build_interior(project, PROFILES[pid], DEMO)
    write_interior(build, tmp_path, DEMO)
    result = preflight_interior(
        project, read_interior_artifacts(tmp_path), build, source_directory=DEMO
    )
    assert result.report.structurally_valid
    # The demo is short; its only KDP error is the 24-page minimum, as on 8.5 x 11.
    errors = {f.rule for f in result.report.findings if f.severity.value == "error"}
    assert {getattr(r, "code", r) for r in errors} <= {"kdp_minimum_page_count"}
    spec = PROFILES[pid]
    assert all(page.frame.trim.width == spec.trim.width for page in build.layout.pages)


@pytest.mark.parametrize("pid", ["paperback-6x9", "paperback-8x10", "paperback-8.5x8.5"])
def test_coloring_keeps_parity_and_lossless_art_on_each_trim(pid: str, tmp_path: Path) -> None:
    book = composed_coloring_book(tmp_path / "book", 2, size=(1088, 1463))
    project = load_project(book).project
    build = build_interior(project, PROFILES[pid], book)
    out = tmp_path / "out"
    write_interior(build, out, book)
    result = preflight_interior(project, read_interior_artifacts(out), build, source_directory=book)
    assert result.report.structurally_valid
    passed = {r.rule.code: r.outcome.value for r in result.report.results}
    for rule in ("coloring_art_placement", "coloring_page_parity", "coloring_image_integrity"):
        assert passed.get(rule) == "passed", (rule, passed.get(rule))
    art = [p for p in build.plan.pages if p.kind is PageKind.COLORING]
    assert art and all(p.index % 2 == 1 for p in art)


@pytest.mark.parametrize("trim", SUPPORTED_TRIMS, ids=lambda t: t.name)
def test_cover_wraps_every_supported_trim(trim) -> None:  # type: ignore[no-untyped-def]
    geometry = cover_geometry(120, trim.width, trim.height, Paper.WHITE)
    assert geometry.front.width == trim.width and geometry.front.height == trim.height
    assert geometry.media.width == pytest.approx(
        2 * inches(0.125) + 2 * trim.width + inches(120 * 0.002252)
    )


@pytest.mark.parametrize(
    ("trim", "white", "cream"),
    [("8.5x11", 590, 550), ("8.5x8.5", 590, 550), ("6x9", 828, 776), ("8x10", 828, 776)],
)
def test_page_maximum_follows_trim_and_paper(trim: str, white: int, cream: int) -> None:
    """KDP's "Set Trim Size, Bleed, and Margins" table, read 2026-11-05 (ruleset 5)."""
    assert KDP.max_pages_for(trim, Paper.WHITE) == white
    assert KDP.max_pages_for(trim, Paper.CREAM) == cream
    assert KDP.max_pages_for("5x8", Paper.WHITE) is None  # Not a supported profile.


def test_every_trim_and_paper_has_a_full_bleed_profile_for_coloring_only() -> None:
    """Interval 9: a -bleed twin of each no-bleed profile (same trim, paper, margins);
    word-search builds refuse them with the reason; the no-bleed profiles are unchanged."""
    assert len(BLEED) == 8
    for pid in BLEED:
        spec = PROFILES[pid]
        twin = PROFILES[pid.removesuffix("-bleed")]
        assert (spec.trim, spec.paper, spec.margins) == (twin.trim, twin.paper, twin.margins)
        assert not twin.bleed and "no bleed" in twin.description
        assert "full bleed" in spec.description and validate_print_spec(spec) == ()
        assert min(spec.margins.outside, spec.margins.top, spec.margins.bottom) >= (
            KDP.min_outside_margin_with_bleed
        )
    project = load_project(DEMO).project
    with pytest.raises(InteriorError) as raised:
        build_interior(project, PROFILES["paperback-8.5x11-bleed"], DEMO)
    assert raised.value.issues[0].code == "unsupported_bleed_configuration"
