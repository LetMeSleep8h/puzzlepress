"""The coloring preflight ruleset: structure, environment, integrity and line quality.

Every drawing is SYNTHETIC. Thresholds are PuzzlePress conventions (docs/coloring.md);
these tests pin which measured situations they report, not real print quality.
"""

import io
import json
import re
import zlib
from pathlib import Path

import pytest
from coloring_helpers import (
    FULL_SIZE,
    composed_coloring_book,
    encode,
    fine_detail,
    line_art,
    noisy_scan,
    white_on_black,
)
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

from puzzlepress import dump_project, validate_project
from puzzlepress.cli import main
from puzzlepress.coloring.content import ColoringContent
from puzzlepress.interior import DEFAULT_PROFILE, build_interior, print_profile, write_interior
from puzzlepress.interior import coloring as interior_coloring
from puzzlepress.preflight import (
    RULESET_ID,
    InteriorArtifacts,
    Outcome,
    Severity,
    preflight_interior,
    read_interior_artifacts,
    report_bytes,
)
from puzzlepress.preflight.coloring import COLORING_RULES
from puzzlepress.preflight.coloring import RULESET_ID as COLORING_ID
from puzzlepress.project import load_project

SPEC = print_profile(DEFAULT_PROFILE)
MEDIUM = (1088, 1463)
ROOT = Path(__file__).resolve().parents[1]


def written(directory: Path, output: Path):  # Build, write, return the preflight result.
    project = load_project(directory).project
    build = build_interior(project, SPEC, directory)
    write_interior(build, output, directory)
    return build, preflight_interior(project, read_interior_artifacts(output), build, directory)


def outcome(report, code: str) -> Outcome:
    return next(r.outcome for r in report.results if r.rule.code == code)


def codes(report, severity: Severity | None = None) -> list[str]:
    return sorted(
        f.rule.code for f in report.findings if severity is None or f.severity is severity
    )


def save(directory: Path, data: dict) -> None:
    (directory / "book.yaml").write_text(
        dump_project(validate_project(data).require_project()), encoding="utf-8"
    )


@pytest.fixture(scope="module")
def ready(tmp_path_factory):
    """Eleven full-size drawings, single-sided: 24 pages, every check satisfied."""
    root = tmp_path_factory.mktemp("ready")
    directory = composed_coloring_book(
        root / "book", 11, images=[line_art(seed, FULL_SIZE) for seed in range(11)]
    )
    build, result = written(directory, root / "out")
    return directory, root / "out", build, result


# -------------------------------------------------------------------- the ruleset


def test_a_clean_coloring_interior_is_valid_and_ready(ready):
    _, _, build, result = ready
    report = result.report
    assert len(build.layout.pages) == 24
    assert report.structurally_valid and report.kdp_ready
    assert report.findings == () or codes(report) == ["kdp_full_font_embedding"]
    data = report.to_dict()
    assert data["ruleset"]["id"] == COLORING_ID == "puzzlepress-kdp-coloring"
    assert data["ruleset"]["version"] == 1
    assert set(data["counts"]["severity"]) == {"error", "warning", "info"}
    assert all(set(page["findings"]) == {"error", "warning", "info"} for page in data["pages"])
    for code in ("coloring_image_integrity", "coloring_page_parity", "coloring_art_placement"):
        assert outcome(report, code) is Outcome.PASSED
    parity = next(r for r in report.results if r.rule.code == "coloring_page_parity")
    assert parity.note == "11 of 11 coloring page(s) on right-hand pages; 11 blank reverse(s)."
    text = report_bytes(report).decode("ascii")
    assert not re.search(r"\b(puzzles?|solutions?|word lists?|grids?|photographs?)\b", text, re.I)


def test_rule_codes_are_stable_and_separate_from_word_search():
    assert [rule.code for rule in COLORING_RULES] == [
        "interior_artifacts",
        "manifest_format",
        "manifest_book",
        "manifest_pdf_digest",
        "interior_identity",
        "source_current",
        "print_profile_current",
        "toolchain_current",
        "coloring_rendering_environment",
        "source_buildable",
        "plan_current",
        "pdf_matches_layout",
        "pdf_readable",
        "page_count",
        "page_boxes",
        "page_rotation",
        "pdf_interactive_features",
        "fonts_bundled",
        "raster_images",
        "coloring_image_integrity",
        "coloring_artwork_sources",
        "coloring_page_parity",
        "coloring_art_placement",
        "blank_pages",
        "folios_printed",
        "content_in_live_area",
        "kdp_minimum_page_count",
        "kdp_maximum_page_count",
        "kdp_trim_size",
        "kdp_page_size",
        "kdp_no_bleed",
        "kdp_gutter",
        "kdp_outside_margins",
        "kdp_minimum_font_size",
        "kdp_minimum_line_weight",
        "kdp_fonts_embedded",
        "kdp_full_font_embedding",
        "kdp_no_annotations",
        "kdp_not_encrypted",
        "kdp_flattened",
        "kdp_no_printer_marks",
        "kdp_image_resolution",
        "kdp_blank_page_runs",
        "kdp_page_number_parity",
        "kdp_no_metadata",
        "coloring_blank_artwork",
        "coloring_excessive_ink",
        "coloring_thin_lines",
        "coloring_heavy_ink",
        "coloring_gray_background",
        "coloring_line_quality",
        "coloring_duplicate_artwork",
        "coloring_similar_artwork",
        "coloring_visual_review",
    ]
    severities = {rule.code: rule.severity for rule in COLORING_RULES}
    assert severities["coloring_similar_artwork"] is Severity.INFO
    assert severities["coloring_visual_review"] is Severity.INFO
    assert severities["coloring_blank_artwork"] is Severity.ERROR
    assert severities["coloring_line_quality"] is Severity.WARNING
    assert "design_legibility" not in severities
    assert RULESET_ID == "puzzlepress-kdp-paperback"


def test_word_search_reports_keep_their_ruleset_and_severities():
    project = load_project(ROOT / "books" / "composition-demo").project
    build = build_interior(project, SPEC)
    artifacts = InteriorArtifacts(build.pdf, json.dumps(build.manifest).encode("ascii"))
    data = preflight_interior(project, artifacts, build).report.to_dict()
    assert data["ruleset"] == {
        "id": "puzzlepress-kdp-paperback",
        "version": 4,
        "kdp_rules_checked": "2026-10-07",
    }
    assert set(data["counts"]["severity"]) == {"error", "warning", "info"}
    assert not any(r["code"].startswith("coloring_") for r in data["rules"])


def test_preflight_with_a_fresh_build_equals_one_reusing_the_build(ready):
    directory, output, build, result = ready
    project = load_project(directory).project
    fresh = preflight_interior(project, read_interior_artifacts(output), None, directory)
    assert report_bytes(fresh.report) == report_bytes(result.report)
    assert fresh.layout is not None and fresh.layout.pages == build.layout.pages


def test_cli_exit_codes_and_report_bytes(ready, tmp_path, capsys):
    directory, output, _, result = ready
    assert main(["book", "preflight", str(directory), "--output", str(output), "--json"]) == 0
    out = capsys.readouterr().out
    assert out.encode("ascii") == report_bytes(result.report)
    assert (output / "preflight.json").read_bytes() == report_bytes(result.report)
    assert main(["book", "preflight", str(directory), "--output", str(output)]) == 0
    text = capsys.readouterr().out
    assert "ruleset puzzlepress-kdp-coloring v1" in text and "Manual review: none" in text


# --------------------------------------------------------------- stale and altered


def test_changed_settings_make_the_interior_stale(ready, tmp_path):
    directory, output, _, _ = ready
    project = load_project(directory).project
    data = project.to_dict()
    data["coloring"]["artwork"][0]["adjustments"]["line_weight"] = 1
    changed = validate_project(data).require_project()
    report = preflight_interior(changed, read_interior_artifacts(output), None, directory).report
    assert {"source_current", "plan_current", "pdf_matches_layout"} <= set(codes(report))
    assert not report.structurally_valid
    # Geometry rules never claim to have checked a PDF that is not the current render.
    assert outcome(report, "coloring_art_placement") is Outcome.NOT_EVALUATED


def test_missing_or_altered_artwork_is_reported(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 2, size=MEDIUM)
    written(directory, tmp_path / "out")
    project = load_project(directory).project
    assert project.coloring is not None
    first, second = project.coloring.artwork
    (directory / first.path).unlink()
    (directory / second.path).write_bytes(encode(line_art(77, MEDIUM)))
    report = preflight_interior(
        project, read_interior_artifacts(tmp_path / "out"), None, directory
    ).report
    sources = [f for f in report.findings if f.rule.code == "coloring_artwork_sources"]
    assert sorted(f.subject for f in sources) == [first.id, second.id]
    assert {f.region for f in sources} == {"artwork_missing", "artwork_changed"}
    assert "source_buildable" in codes(report)
    assert outcome(report, "coloring_line_quality") is Outcome.NOT_EVALUATED
    assert not report.structurally_valid and not report.kdp_ready


def test_tampered_pixels_are_caught_by_decoding_the_pdf(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 2, size=MEDIUM)
    build, _ = written(directory, tmp_path / "out")
    reader = PdfReader(io.BytesIO(build.pdf))
    writer = PdfWriter(clone_from=reader)
    page = writer.pages[2]
    ((_, ref),) = page["/Resources"]["/XObject"].items()
    stream = ref.get_object()
    raw = bytearray(zlib.decompress(stream._data))
    raw[len(raw) // 2] ^= 0xFF  # One byte of pixels changed.
    stream.set_data(bytes(raw))
    buffer = io.BytesIO()
    writer.write(buffer)
    project = load_project(directory).project
    artifacts = InteriorArtifacts(buffer.getvalue(), json.dumps(build.manifest).encode("ascii"))
    report = preflight_interior(project, artifacts, build, directory).report
    integrity = [f for f in report.findings if f.rule.code == "coloring_image_integrity"]
    assert [(f.page.physical_page if f.page else None, f.region) for f in integrity] == [
        (3, "pdf_image_pixels")
    ]
    assert not report.structurally_valid


def test_an_incompatible_rendering_environment_is_never_reported_as_passing(tmp_path, monkeypatch):
    """A build under another deflate implementation: different bytes, same pixels."""
    directory = composed_coloring_book(tmp_path / "book", 2, size=MEDIUM)
    from puzzlepress.coloring import content as coloring_content

    with monkeypatch.context() as patched:
        patched.setattr(interior_coloring, "zlib_implementation", lambda: "zlib-ng 2.2.4")
        patched.setattr(coloring_content, "DEFLATE_LEVEL", 1)  # Other deflate output.
        build, _ = written(directory, tmp_path / "out")
    assert build.manifest["coloring"]["zlib"] == "zlib-ng 2.2.4"
    project = load_project(directory).project
    report = preflight_interior(
        project, read_interior_artifacts(tmp_path / "out"), None, directory
    ).report
    environment = [f for f in report.findings if f.rule.code == "coloring_rendering_environment"]
    assert [f.region for f in environment] == ["coloring.zlib"]
    assert "Rebuild the interior in this environment" in environment[0].message
    matches = next(r for r in report.results if r.rule.code == "pdf_matches_layout")
    assert matches.outcome is Outcome.NOT_EVALUATED
    assert "zlib-ng 2.2.4" in (matches.note or "")
    assert not report.structurally_valid
    # Pixels are still verifiable: the drawings decode to the prepared digests.
    assert outcome(report, "coloring_image_integrity") is Outcome.PASSED


# ------------------------------------------------------------------ line quality


def blank() -> Image.Image:
    image = Image.new("L", MEDIUM, 255)
    ImageDraw.Draw(image).point((5, 5), fill=0)
    return image


def test_quality_rules_report_measured_problems_at_their_severities(tmp_path):
    images = [
        blank(),  # Nothing to color.
        white_on_black(3, MEDIUM),  # Mostly ink without Invert.
        noisy_scan(4, MEDIUM),  # Gray paper and dust.
        fine_detail(MEDIUM),  # Thinned below: fine lines destroyed.
    ]
    directory = composed_coloring_book(tmp_path / "book", 4, images=images)
    data = load_project(directory).project.to_dict()
    data["coloring"]["artwork"][3]["adjustments"]["line_weight"] = -1
    save(directory, data)
    _, result = written(directory, tmp_path / "out")
    report = result.report
    found = {
        (f.rule.code, f.subject, f.page.physical_page if f.page else None): f.severity
        for f in report.findings
        if f.rule.code.startswith("coloring_")
    }
    assert found[("coloring_blank_artwork", "drawing-1", 3)] is Severity.ERROR
    assert found[("coloring_excessive_ink", "drawing-2", 5)] is Severity.ERROR
    assert found[("coloring_gray_background", "drawing-3", 7)] is Severity.WARNING
    assert found[("coloring_line_quality", "drawing-3", 7)] is Severity.WARNING
    assert found[("coloring_thin_lines", "drawing-4", 9)] is Severity.ERROR
    excessive = next(f for f in report.findings if f.rule.code == "coloring_excessive_ink")
    assert "Invert" in excessive.message
    assert report.structurally_valid and not report.kdp_ready


def test_review_prompts_never_block(tmp_path):
    a = line_art(5, MEDIUM)
    b = a.copy()
    ImageDraw.Draw(b).line((10, 10, 40, 10), fill=0, width=2)  # A near-copy.
    directory = composed_coloring_book(tmp_path / "book", 2, images=[a, b])
    _, result = written(directory, tmp_path / "out")
    report = result.report
    reviews = codes(report, Severity.INFO)
    assert "coloring_similar_artwork" in reviews
    review = [r for r in report.results if r.rule.severity is Severity.INFO]
    assert all(r.rule.scope.value == "kdp" for r in review)
    # Only DPI and the page minimum block this small book: reviews never do.
    blocking = codes(report, Severity.ERROR)
    assert set(blocking) <= {"kdp_image_resolution", "kdp_minimum_page_count"}


def test_duplicates_are_warnings(tmp_path):
    drawing = line_art(9, MEDIUM)
    directory = composed_coloring_book(tmp_path / "book", 1, images=[drawing])
    data = load_project(directory).project.to_dict()
    data["coloring"]["pages"].append({"artwork": "drawing-1"})  # Printed twice.
    save(directory, data)
    _, result = written(directory, tmp_path / "out")
    duplicates = [f for f in result.report.findings if f.rule.code == "coloring_duplicate_artwork"]
    assert [(f.subject, f.region, f.severity) for f in duplicates] == [
        ("drawing-1", "repeated_page", Severity.WARNING)
    ]


def test_low_resolution_names_the_pixels_needed(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1, size=(600, 800))
    _, result = written(directory, tmp_path / "out")
    (finding,) = [f for f in result.report.findings if f.rule.code == "kdp_image_resolution"]
    assert finding.measure is not None and finding.measure.required == 300
    assert "Supply at least" in finding.message and "pixels" in finding.message
    assert finding.page is not None and finding.page.kind == "coloring"


def test_preflight_never_writes_beside_the_artwork(ready):
    directory, _, _, _ = ready
    before = sorted(p.relative_to(directory) for p in directory.rglob("*"))
    project = load_project(directory).project
    content = build_interior(project, SPEC, directory).report
    assert isinstance(content, ColoringContent)
    assert sorted(p.relative_to(directory) for p in directory.rglob("*")) == before
