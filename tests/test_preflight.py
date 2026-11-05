"""Preflight: structural validity vs KDP readiness, integrity, rules and determinism."""

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText
from reportlab.pdfgen.canvas import Canvas

from puzzlepress import load_project
from puzzlepress.identity import build_identity
from puzzlepress.interior import RENDERER_VERSION, build_interior, write_interior
from puzzlepress.interior.build import interior_identity
from puzzlepress.interior.geometry import page_frame
from puzzlepress.interior.inspection import PdfFacts, PdfPageFacts
from puzzlepress.interior.model import (
    Anchor,
    Box,
    Face,
    InteriorLayout,
    LetterGrid,
    PhysicalPage,
    Rule,
    TextLine,
)
from puzzlepress.interior.spec import KDP, PAPERBACK_LETTER, inches
from puzzlepress.preflight import (
    RULES,
    InteriorArtifacts,
    Outcome,
    Scope,
    Severity,
    preflight_interior,
    read_interior_artifacts,
    report_bytes,
)
from puzzlepress.preflight.context import Context
from puzzlepress.preflight.rules import CATALOGUE
from tests.helpers import DEMO, ROOT, demo_variant

SPEC = PAPERBACK_LETTER


@pytest.fixture(scope="module")
def demo():
    project = load_project(DEMO).project
    return project, build_interior(project, SPEC)


@pytest.fixture
def written(demo, tmp_path):
    project, build = demo
    output = write_interior(build, tmp_path / "out", DEMO)
    return project, build, output.pdf.parent


def run(project, directory: Path):
    return preflight_interior(project, read_interior_artifacts(directory))


def by_rule(report):
    return {result.rule.code: result for result in report.results}


def codes(report, severity=None):
    return [f.rule.code for f in report.findings if severity is None or f.severity is severity]


def artifacts(build, pdf=None, manifest=None):
    data = dict(build.manifest)
    if manifest:
        manifest(data)
    pdf = build.pdf if pdf is None else pdf
    return InteriorArtifacts(pdf, json.dumps(data).encode())


def rewrite(build, edit):
    """A modified copy of the demo PDF, with a manifest that records its digest."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(build.pdf)))
    edit(writer)
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf = buffer.getvalue()

    def record(data):
        data["pdf"] = {**data["pdf"], "sha256": hashlib.sha256(pdf).hexdigest(), "bytes": len(pdf)}

    return artifacts(build, pdf, record)


# ------------------------------------------------------------- the two statuses


def test_composition_demo_is_structurally_valid_but_not_kdp_ready(written):
    project, build, directory = written
    report = run(project, directory).report
    assert report.structurally_valid and not report.kdp_ready
    assert codes(report, Severity.ERROR) == ["kdp_minimum_page_count"]
    assert codes(report, Severity.WARNING) == ["kdp_full_font_embedding"]
    finding = report.findings[0]
    assert finding.page is None  # Book-level: no invented page or region.
    assert finding.message == "11 pages. The supported KDP paperback minimum is 24 pages."
    assert (finding.measure.actual, finding.measure.required) == (11, 24)
    assert (finding.measure.unit, finding.measure.comparison) == ("pages", "at_least")
    results = by_rule(report)
    assert all(
        r.outcome in (Outcome.PASSED, Outcome.NOT_APPLICABLE)
        for r in results.values()
        if r.rule.scope is Scope.STRUCTURAL
    )
    assert results["kdp_image_resolution"].outcome is Outcome.NOT_APPLICABLE
    assert results["kdp_gutter"].measure.actual == 0.75
    data = report.to_dict()
    assert data["structural"] == {"status": "valid"} and data["kdp"] == {"status": "not_ready"}
    assert data["page_count"] == 11 and data["artifacts"]["matches_layout"] is True
    assert data["artifacts"]["pdf"]["sha256"] == build.manifest["pdf"]["sha256"]
    pages = data["pages"]
    assert [p["kind"] for p in pages][3:5] == ["blank", "puzzle"]
    assert (pages[4]["side"], pages[4]["folio"]) == ("recto", "1")


def test_kdp_ready_book_from_a_larger_variant(tmp_path):
    project = demo_variant(puzzles=16)
    source = tmp_path / "source"
    source.mkdir()
    build = build_interior(project, SPEC)
    directory = write_interior(build, tmp_path / "out", source).pdf.parent
    report = run(project, directory).report
    assert report.page_count >= KDP.min_pages
    assert report.structurally_valid and report.kdp_ready
    assert codes(report, Severity.ERROR) == []
    assert by_rule(report)["kdp_minimum_page_count"].outcome is Outcome.PASSED


def test_preflight_is_read_only_and_deterministic(written):
    project, build, directory = written
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    first = run(project, directory)
    second = run(project, directory)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    assert report_bytes(first.report) == report_bytes(second.report)
    assert first.layout == build.layout and first.plan == build.plan
    text = report_bytes(first.report).decode()
    assert "time" not in text.lower() and str(directory) not in text


def test_findings_are_ordered_by_severity_scope_page_and_rule(written):
    project, build, _ = written

    def annotate(writer):
        for index in (6, 2):
            writer.add_annotation(index, FreeText(text="x", rect=(50, 50, 100, 100)))

    report = preflight_interior(project, rewrite(build, annotate)).report
    keys = [f.sort_key() for f in report.findings]
    assert keys == sorted(keys)
    severities = [f.severity for f in report.findings]
    assert severities == sorted(severities, key=list(Severity).index)
    pages = [f.page.physical_page for f in report.findings if f.rule.code == "kdp_no_annotations"]
    assert pages == [3, 7]


# ------------------------------------------------------------- integrity


def test_manifest_pdf_mismatch_is_structurally_invalid(written):
    project, build, directory = written
    (directory / "interior.pdf").write_bytes(build.pdf + b"\n%tampered\n")
    report = run(project, directory).report
    assert not report.structurally_valid and not report.kdp_ready
    results = by_rule(report)
    assert results["manifest_pdf_digest"].outcome is Outcome.FAILED
    assert results["pdf_matches_layout"].outcome is Outcome.FAILED
    for code in ("kdp_gutter", "kdp_minimum_font_size", "blank_pages", "kdp_page_number_parity"):
        assert results[code].outcome is Outcome.NOT_EVALUATED


def test_pdf_from_another_build_beside_this_manifest(written, tmp_path):
    project, build, directory = written
    other = build_interior(demo_variant(lambda d: d["book"].update(title="Other")), SPEC)
    (directory / "interior.pdf").write_bytes(other.pdf)
    report = run(project, directory).report
    assert not report.kdp_ready
    assert {"manifest_pdf_digest", "pdf_matches_layout"} <= set(codes(report))


def test_stale_source_composition_and_renderer(written):
    project, build, directory = written
    edited = demo_variant(lambda d: d["composition"]["solutions"].update(per_page=4))
    report = run(edited, directory).report
    stale = set(codes(report, Severity.ERROR))
    assert {"source_current", "plan_current", "pdf_matches_layout"} <= stale
    assert not report.structurally_valid
    assert by_rule(report)["kdp_gutter"].outcome is Outcome.NOT_EVALUATED
    pages = report.to_dict()["pages"]
    assert pages[0]["kind"] is None and pages[1]["side"] == "verso"  # No borrowed meaning.

    def old_renderer(data):
        data["renderer_version"] = 1  # Before grid frames fit by painted extent.
        data["interior_identity"] = interior_identity(data)

    report = preflight_interior(project, artifacts(build, manifest=old_renderer)).report
    assert codes(report, Severity.ERROR) == ["toolchain_current", "kdp_minimum_page_count"]
    finding = report.findings[0]
    assert (finding.region, finding.measure.actual, finding.measure.required) == (
        "renderer_version",
        1,
        RENDERER_VERSION,
    )
    assert RENDERER_VERSION == 2


def test_manifest_identity_profile_and_book_corruption(demo):
    project, build = demo

    def forged(data):
        data["plan_digest"] = "sha256-" + "0" * 64

    report = preflight_interior(project, artifacts(build, manifest=forged)).report
    assert {"interior_identity", "plan_current"} <= set(codes(report))

    def unknown_profile(data):
        data["print_profile"] = {**data["print_profile"], "profile_id": "paperback-7x10"}

    report = preflight_interior(project, artifacts(build, manifest=unknown_profile)).report
    results = by_rule(report)
    assert results["print_profile_current"].outcome is Outcome.FAILED
    assert results["kdp_trim_size"].outcome is Outcome.NOT_EVALUATED
    assert not report.kdp_ready

    def foreign(data):
        data["book_id"] = "someone-else"

    report = preflight_interior(project, artifacts(build, manifest=foreign)).report
    assert "manifest_book" in codes(report)


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (b"not json", "not valid JSON"),
        (b"[]", "not a JSON object"),
        (b'{"manifest_version": 2}', "Unsupported manifest version"),
        (b'{"manifest_version": 1}', "missing or malformed"),
    ],
)
def test_malformed_manifest(demo, manifest, problem):
    project, build = demo
    report = preflight_interior(project, InteriorArtifacts(build.pdf, manifest)).report
    finding = next(f for f in report.findings if f.rule.code == "manifest_format")
    assert problem in finding.message and not report.structurally_valid


def test_missing_artifacts_and_unreadable_pdf(demo, tmp_path):
    project, build = demo
    report = run(project, tmp_path).report
    assert codes(report, Severity.ERROR) == ["interior_artifacts", "interior_artifacts"]
    assert report.page_count is None and report.pages == ()
    assert by_rule(report)["kdp_minimum_page_count"].outcome is Outcome.NOT_EVALUATED
    assert not report.structurally_valid and not report.kdp_ready
    report = preflight_interior(project, artifacts(build, pdf=b"%PDF-1.4 broken")).report
    assert "pdf_readable" in codes(report)


def test_artifacts_are_read_without_following_directories(tmp_path):
    (tmp_path / "interior.pdf").mkdir()
    found = read_interior_artifacts(tmp_path)
    assert found.pdf is None and found.manifest is None
    assert [p.code for p in found.problems] == ["artifact_not_file", "artifact_missing"]


# ------------------------------------------------------------- PDF features


def test_annotations_bookmarks_and_forms(written):
    project, build, _ = written

    def edit(writer):
        writer.add_annotation(4, FreeText(text="note", rect=(50, 50, 200, 100)))
        writer.add_outline_item("Start", 0)

    report = preflight_interior(project, rewrite(build, edit)).report
    assert {"pdf_interactive_features", "kdp_no_annotations"} <= set(codes(report))
    kdp = [f for f in report.findings if f.rule.code == "kdp_no_annotations"]
    assert [(f.page.physical_page if f.page else None) for f in kdp] == [None, 5]
    assert kdp[1].page.kind is None  # A modified PDF borrows no plan meaning.


def test_encryption_metadata_and_spreads(written):
    project, build, _ = written
    report = preflight_interior(
        project, rewrite(build, lambda w: w.encrypt("", owner_password="o", algorithm="RC4-128"))
    ).report
    assert "kdp_not_encrypted" in codes(report) and not report.kdp_ready
    report = preflight_interior(
        project, rewrite(build, lambda w: w.add_metadata({"/Title": "Seaside"}))
    ).report
    warning = next(f for f in report.findings if f.rule.code == "kdp_no_metadata")
    assert warning.severity is Severity.WARNING and "/Title" in warning.message

    def spread(writer):
        writer.pages[5].mediabox.upper_right = (1224, 792)

    report = preflight_interior(project, rewrite(build, spread)).report
    finding = next(f for f in report.findings if f.rule.code == "kdp_page_size")
    assert finding.message == "The page is a two-page spread." and finding.page.physical_page == 6
    assert finding.measure.actual == "17 x 11"


def _overlay(draw):
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(612, 792))
    draw(canvas)
    canvas.showPage()
    canvas.save()
    return PdfReader(io.BytesIO(buffer.getvalue())).pages[0]


def test_raster_images_and_transparency_are_observed(written):
    project, build, _ = written
    from PIL import Image

    image = Image.new("L", (30, 30), 128)

    def with_image(writer):
        writer.pages[4].merge_page(
            _overlay(lambda c: c.drawInlineImage(image, 100, 100, width=60, height=60))
        )

    report = preflight_interior(project, rewrite(build, with_image)).report
    results = by_rule(report)
    assert results["raster_images"].outcome is Outcome.FAILED
    assert results["kdp_image_resolution"].outcome is Outcome.FAILED
    finding = next(f for f in report.findings if f.rule.code == "kdp_image_resolution")
    assert finding.page.physical_page == 5 and finding.measure.required == 300

    def with_alpha(writer):
        def draw(c):
            c.setFillAlpha(0.5)
            c.rect(100, 100, 50, 50, fill=1)

        writer.pages[2].merge_page(_overlay(draw))

    report = preflight_interior(project, rewrite(build, with_alpha)).report
    assert [f.page.physical_page for f in report.findings if f.rule.code == "kdp_flattened"] == [3]


# ------------------------------------------------------------- plan-based KDP rules


def test_page_number_parity_on_the_wrong_side(tmp_path):
    def odd_front(data):
        data["composition"]["puzzles"]["start"] = "any"

    project = demo_variant(odd_front)
    build = build_interior(project, SPEC)
    report = preflight_interior(project, InteriorArtifacts(build.pdf, None)).report
    result = by_rule(report)
    assert result["kdp_page_number_parity"].outcome is Outcome.NOT_EVALUATED  # No manifest.
    source = tmp_path / "source"
    source.mkdir()
    directory = write_interior(build, tmp_path / "out", source).pdf.parent
    report = run(project, directory).report
    parity = [f for f in report.findings if f.rule.code == "kdp_page_number_parity"]
    assert parity and parity[0].page.physical_page == 4 and parity[0].page.folio == "1"
    assert parity[0].message == "Page number 1 is printed on a verso page."
    assert report.structurally_valid and not report.kdp_ready


# ------------------------------------------------------------- exact rule boundaries


def _context(demo, layout=None, page_count=None, pages=()):
    project, build = demo
    expected = replace(build, layout=layout or build.layout)
    count = page_count if page_count is not None else len(pages)
    facts = PdfFacts(count, False, False, (), False, (), tuple(pages))
    return Context(
        project=project,
        source_identity=build_identity(project),
        artifacts=InteriorArtifacts(build.pdf, None),
        manifest=None,
        manifest_problem=None,
        spec=SPEC,
        facts=facts,
        facts_problem=None,
        expected=expected,
        build_error=None,
    )


def _evaluate(code, ctx):
    definition, evaluate = next(item for item in CATALOGUE if item[0].code == code)
    check = evaluate(definition, ctx)
    return check.outcome or (Outcome.FAILED if check.findings else Outcome.PASSED), check


def _layout(*elements, number=1):
    page = PhysicalPage(number, number, "puzzle", page_frame(SPEC, number), elements, None)
    return InteriorLayout(SPEC, "b", "i", "d", (page,), ())


def _text(x, y=300.0, width=50.0, size=10.0):
    return TextLine("body", "X", Face.REGULAR, size, x, y, Anchor.START, Box(x, y, width, 12))


@pytest.mark.parametrize(
    ("count", "outcome"),
    [(1, Outcome.FAILED), (23, Outcome.FAILED), (24, Outcome.PASSED), (550, Outcome.PASSED)],
)
def test_minimum_page_count_boundary(demo, count, outcome):
    assert _evaluate("kdp_minimum_page_count", _context(demo, page_count=count))[0] is outcome


@pytest.mark.parametrize(("count", "outcome"), [(590, Outcome.PASSED), (591, Outcome.FAILED)])
def test_maximum_page_count_boundary(demo, count, outcome):
    """8.5 x 11 on white paper: 590 (ruleset 5; rulesets 3-4 applied cream's 550)."""
    assert _evaluate("kdp_maximum_page_count", _context(demo, page_count=count))[0] is outcome


@pytest.mark.parametrize(("count", "outcome"), [(550, Outcome.PASSED), (551, Outcome.FAILED)])
def test_maximum_page_count_on_cream_paper(demo, count, outcome):
    from puzzlepress.interior.spec import PROFILES

    context = replace(_context(demo, page_count=count), spec=PROFILES["paperback-8.5x11-cream"])
    assert _evaluate("kdp_maximum_page_count", context)[0] is outcome


@pytest.mark.parametrize(
    ("count", "gutter"),
    [(24, 0.375), (150, 0.375), (151, 0.5), (300, 0.5), (301, 0.625), (500, 0.625)]
    + [(501, 0.75), (700, 0.75), (701, 0.875), (828, 0.875)],
)
@pytest.mark.parametrize("number", [1, 2])  # Recto binds on the left, verso on the right.
def test_gutter_thresholds_on_both_sides(demo, count, gutter, number):
    def element(clearance):
        x = clearance if number == 1 else SPEC.trim.width - clearance - 50
        return _text(x)

    exact = _layout(element(inches(gutter)), number=number)
    outcome, check = _evaluate("kdp_gutter", _context(demo, exact, count))
    assert outcome is Outcome.PASSED and check.measure.required == gutter
    below = _layout(element(inches(gutter) - 0.05), number=number)
    outcome, check = _evaluate("kdp_gutter", _context(demo, below, count))
    assert outcome is Outcome.FAILED
    finding = check.findings[0]
    assert finding.region == "inside_margin:body" and finding.measure.unit == "in"
    assert (
        finding.measure.required == gutter and finding.bounds == below.pages[0].elements[0].bounds
    )


def test_gutter_above_the_table_is_not_evaluated(demo):
    outcome, check = _evaluate("kdp_gutter", _context(demo, _layout(_text(200)), 829))
    assert outcome is Outcome.NOT_EVALUATED and "828" in check.note


@pytest.mark.parametrize("edge", ["outside", "top", "bottom"])
def test_outside_top_and_bottom_margin_boundary(demo, edge):
    width, height = SPEC.trim.width, SPEC.trim.height

    def element(clearance):
        if edge == "outside":
            return _text(width - clearance - 50)
        if edge == "top":
            return TextLine(
                "t",
                "X",
                Face.REGULAR,
                10,
                200,
                0,
                Anchor.START,
                Box(200, height - clearance - 12, 50, 12),
            )
        return TextLine(
            "t", "X", Face.REGULAR, 10, 200, 0, Anchor.START, Box(200, clearance, 50, 12)
        )

    exact = _evaluate("kdp_outside_margins", _context(demo, _layout(element(18.0)), 30))
    assert exact[0] is Outcome.PASSED
    outcome, check = _evaluate("kdp_outside_margins", _context(demo, _layout(element(17.9)), 30))
    assert outcome is Outcome.FAILED and check.findings[0].region.startswith(f"{edge}_margin")
    assert check.findings[0].measure.required == 0.25


@pytest.mark.parametrize(("size", "outcome"), [(7.0, Outcome.PASSED), (6.99, Outcome.FAILED)])
def test_minimum_font_size_boundary(demo, size, outcome):
    layout = _layout(_text(200, size=size))
    result, check = _evaluate("kdp_minimum_font_size", _context(demo, layout, 30))
    assert result is outcome
    if outcome is Outcome.FAILED:
        assert check.findings[0].measure.to_dict() == {
            "actual": 6.99,
            "required": 7.0,
            "unit": "pt",
            "comparison": "at_least",
        }


@pytest.mark.parametrize(("width", "outcome"), [(0.75, Outcome.PASSED), (0.74, Outcome.FAILED)])
def test_minimum_line_weight_boundary(demo, width, outcome):
    line = Rule("rule", 100, 300, 200, 300, width, Box(100, 300 - width / 2, 100, width))
    result, _ = _evaluate("kdp_minimum_line_weight", _context(demo, _layout(line), 30))
    assert result is outcome


def _blank(number, painted=False):
    return PdfPageFacts(number, None, None, None, 0, 0, (), 0, False, painted, "")


def _pages(pattern):
    return [_blank(i, painted=c == "x") for i, c in enumerate(pattern, start=1)]


@pytest.mark.parametrize(
    ("pattern", "outcome"),
    [
        ("x" + "." * 4 + "x", Outcome.PASSED),
        ("x" + "." * 5 + "x", Outcome.FAILED),
        ("." * 4 + "x", Outcome.PASSED),
        ("." * 5 + "x", Outcome.FAILED),
        ("x" + "." * 10, Outcome.PASSED),
        ("x" + "." * 11, Outcome.FAILED),
    ],
)
def test_consecutive_blank_page_limits(demo, pattern, outcome):
    pages = _pages(pattern)
    assert _evaluate("kdp_blank_page_runs", _context(demo, pages=pages))[0] is outcome


# ------------------------------------------------------------- live area and marks


def _framed_grid(frame, stroke=1.0):
    cell = frame.width / 2
    return LetterGrid(
        "puzzle_grid", ("AB", "CD"), frame.x, frame.top, cell, 12.0, Face.REGULAR, frame, stroke, 4
    )


def _media_facts(number, media):
    return PdfPageFacts(number, media, media, None, 0, 0, (), 0, False, True, "")


@pytest.mark.parametrize("number", [1, 2])  # Recto and verso live areas differ.
def test_a_frame_stroke_past_the_live_area_is_structural_not_a_printer_mark(demo, number):
    """Interval 9's defect: a 1 pt frame on the live edge paints 0.5 pt beyond it."""
    content = page_frame(SPEC, number).content
    frame = Box(content.x, content.y + 100, content.width, 300)
    layout = _layout(_framed_grid(frame), number=number)
    trim = (0.0, 0.0, SPEC.trim.width, SPEC.trim.height)
    ctx = _context(demo, layout, 24, pages=[_media_facts(n, trim) for n in (1, 2)])
    outcome, check = _evaluate("content_in_live_area", ctx)
    assert outcome is Outcome.FAILED
    finding = check.findings[0]
    assert finding.rule.scope is Scope.STRUCTURAL and finding.region == "puzzle_grid"
    assert finding.bounds == frame.expanded(0.5) and finding.measure.actual == 0.5
    # KDP's own rules: no slug area, and 0.49 in still clears KDP's minimum margins.
    for code in ("kdp_no_printer_marks", "kdp_gutter", "kdp_outside_margins"):
        assert _evaluate(code, ctx)[0] is Outcome.PASSED, code
    inset = _layout(_framed_grid(Box(frame.x + 0.5, frame.y, frame.width - 1, 300)), number=number)
    assert _evaluate("content_in_live_area", _context(demo, inset, 24))[0] is Outcome.PASSED


def test_printer_marks_rule_judges_only_the_area_beyond_the_trim(demo):
    layout = _layout(_text(200))
    slug = (-9.0, -9.0, SPEC.trim.width + 9, SPEC.trim.height + 9)
    outcome, check = _evaluate(
        "kdp_no_printer_marks", _context(demo, layout, 24, [_media_facts(1, slug)])
    )
    assert outcome is Outcome.FAILED and check.findings[0].region == "MediaBox"
    assert _evaluate("content_in_live_area", _context(demo, layout, 24))[0] is Outcome.PASSED


def test_live_area_rule_needs_the_current_layout(demo):
    ctx = replace(_context(demo, page_count=24), expected=None)
    assert _evaluate("content_in_live_area", ctx)[0] is Outcome.NOT_EVALUATED


def test_cover_demo_interior_is_kdp_ready_after_the_grid_fix(tmp_path):
    """Renderer 1 failed ten verso pages here: 14 x 14 frames painted 0.5 pt past the
    live area. Renderer 2 fits the painted extent; nothing in the source changed."""
    source = ROOT / "books" / "cover-demo"
    project = load_project(source).project
    build = build_interior(project, SPEC)
    assert build_interior(project, SPEC).pdf == build.pdf
    directory = write_interior(build, tmp_path / "out", source).pdf.parent
    report = run(project, directory).report
    assert report.structurally_valid and report.kdp_ready
    assert codes(report) == ["kdp_full_font_embedding"]
    results = by_rule(report)
    for code in ("content_in_live_area", "kdp_no_printer_marks", "kdp_gutter"):
        assert results[code].outcome is Outcome.PASSED, code
    assert results["kdp_outside_margins"].outcome is Outcome.PASSED
    assert build.manifest["page_count"] == 35 and build.manifest["renderer_version"] == 2


# ------------------------------------------------------------- catalogue


def test_rule_catalogue_is_unique_documented_and_scoped():
    assert len({r.code for r in RULES}) == len(RULES)
    docs = (ROOT / "docs" / "preflight.md").read_text(encoding="utf-8")
    for rule in RULES:
        assert f"`{rule.code}`" in docs, rule.code
        assert rule.scope is Scope.KDP or rule.basis.value == "puzzlepress_contract"
        assert rule.scope is Scope.STRUCTURAL or rule.source.startswith("KDP help:")
    assert [r.code for r in RULES if r.severity is Severity.WARNING] == [
        "design_legibility",
        "kdp_full_font_embedding",
        "kdp_no_metadata",
    ]
