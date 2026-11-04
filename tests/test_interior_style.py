"""Interior styles, theme dividers and grayscale photographs."""

import hashlib
import io
import os
import subprocess
import sys
from dataclasses import replace

import pytest
from pypdf import PdfReader

from puzzlepress.cover.assets import import_photo
from puzzlepress.errors import ProjectError
from puzzlepress.identity import build_identity
from puzzlepress.interior import build_interior, write_interior
from puzzlepress.interior.design import CLASSIC, PRESETS, resolve_design
from puzzlepress.interior.issues import InteriorError
from puzzlepress.interior.model import ImageBlock, Panel, Rule, TextLine
from puzzlepress.interior.spec import PAPERBACK_LETTER
from puzzlepress.interior_style import StylePreset
from puzzlepress.interior_style_validation import validate_interior_style
from puzzlepress.preflight import preflight_interior, read_interior_artifacts
from puzzlepress.publication import PageKind, build_publication
from puzzlepress.publication_verification import verify_publication_plan
from puzzlepress.validation import validate_project
from tests.cover_helpers import photo_bytes
from tests.helpers import ROOT, demo_variant

THEMES = ("Engines", "Engines", "Tools", "Tools", "Tools", "Racing")


def book(style=None, dividers=None, puzzles=None, themes=THEMES):
    def mutate(data):
        if puzzles is not None or dividers is not None:
            for puzzle, theme in zip(data["word_search"]["puzzles"], themes, strict=False):
                puzzle["theme"] = theme
        if dividers is not None:
            data["composition"]["puzzles"]["dividers"] = dividers
        if style is not None:
            data["interior"] = style

    return demo_variant(mutate, puzzles=puzzles)


def build(project, source=None):
    return build_interior(project, PAPERBACK_LETTER, source)


def elements(built, kind=None, page=1):
    found = built.layout.pages[page - 1].elements
    return [e for e in found if kind is None or isinstance(e, kind)]


def roles(built, page=1):
    return [e.role for e in elements(built, page=page)]


# ------------------------------------------------------------------ compatibility


def test_classic_style_draws_the_original_interior_but_records_its_style():
    plain = build(book())
    classic = build(book({"version": 1, "preset": "classic"}))
    assert classic.pdf == plain.pdf
    assert (
        "style" not in plain.manifest and classic.manifest["style"]["design"]["preset"] == "classic"
    )
    assert classic.manifest["interior_identity"] != plain.manifest["interior_identity"]


def test_style_is_outside_the_build_identity_and_plan():
    plain, styled = book(), book({"version": 1, "preset": "high_contrast"})
    assert build_identity(plain) == build_identity(styled)
    assert build(plain).manifest["plan_digest"] == build(styled).manifest["plan_digest"]
    assert [r.seed for r in build(styled).report.puzzles] == [
        r.seed for r in build(plain).report.puzzles
    ]


@pytest.mark.parametrize("preset", list(StylePreset))
def test_every_preset_builds_valid_deterministic_interiors(preset, tmp_path):
    project = book({"version": 1, "preset": preset.value}, puzzles=24)
    first, second = build(project), build(project)
    assert first.pdf == second.pdf and first.layout.design == PRESETS[preset]
    write_interior(first, tmp_path, ROOT / "books" / "composition-demo")
    report = preflight_interior(project, read_interior_artifacts(tmp_path)).report
    assert report.structurally_valid, [f.message for f in report.findings]


def test_resolved_design_applies_overrides_over_the_preset():
    style, _ = validate_interior_style(
        {
            "version": 1,
            "preset": "editorial",
            "folio": "center",
            "puzzle_pages": {"word_columns": 3, "theme_label": False},
            "solution_pages": {"muted_ink": 40},
        },
        True,
    )
    design = resolve_design(style)
    assert (design.header_align, design.header_rule) == ("left", True)
    assert (design.folio, design.word_columns, design.theme_label) == ("center", 3, False)
    assert design.muted_gray == pytest.approx(0.6)
    assert resolve_design(None) == CLASSIC


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        ({"version": 3}, ("interior.version", "unsupported_version")),
        ({"version": 1, "preset": "gothic"}, ("interior.preset", "choice")),
        (
            {"version": 1, "puzzle_pages": {"word_size": 9}},
            ("interior.puzzle_pages.word_size", "range"),
        ),
        (
            {"version": 1, "puzzle_pages": {"grid_frame": 0.5}},
            ("interior.puzzle_pages.grid_frame", "range"),
        ),
        (
            {"version": 1, "solution_pages": {"muted_ink": 80}},
            ("interior.solution_pages.muted_ink", "range"),
        ),
        ({"version": 1, "title_page": {"tint": 101}}, ("interior.title_page.tint", "range")),
        (
            {"version": 1, "title_page": {"layout": "photo_feature"}},
            ("interior.title_page.photo", "required"),
        ),
        ({"version": 1, "bleed": True}, ("interior.bleed", "unknown_field")),
    ],
)
def test_style_schema_refusals(style, expected):
    _, issues = validate_interior_style(style, True)
    assert expected in [(i.path, i.code) for i in issues]


# ------------------------------------------------------------------ title pages


def test_color_block_title_page_uses_white_type_on_a_dark_tint():
    built = build(book({"version": 1, "title_page": {"layout": "color_block", "tint": 80}}))
    (panel,) = elements(built, Panel)
    assert panel.fill_gray == pytest.approx(0.2) and panel.stroke_gray is None
    title = [e for e in elements(built, TextLine) if e.role == "title"]
    assert title and all(line.gray == 1.0 for line in title)
    assert all(panel.box.contains(line.bounds, 0.01) for line in title)
    content = built.layout.pages[0].frame.content
    assert content.contains(panel.bounds, 0.01)  # Never to the trimmed edge.
    assert {w.code for w in built.layout.warnings} >= {"heavy_ink_coverage"}


def test_mid_gray_tint_warns_about_contrast():
    built = build(book({"version": 1, "title_page": {"layout": "color_block", "tint": 50}}))
    assert "low_contrast_text" in {w.code for w in built.layout.warnings}


def test_framed_and_editorial_title_pages():
    framed = build(book({"version": 1, "title_page": {"layout": "framed"}}))
    (frame,) = elements(framed, Panel)
    assert frame.stroke_gray == 0.0 and frame.fill_gray is None and frame.stroke_width >= 0.75
    editorial = build(book({"version": 1, "title_page": {"layout": "editorial"}}))
    rules = [e for e in elements(editorial, Rule) if e.role == "title_rule"]
    body = editorial.layout.pages[0].frame.content
    assert (
        rules and rules[0].x1 == pytest.approx(body.x) and rules[0].x2 == pytest.approx(body.right)
    )
    title = [e for e in elements(editorial, TextLine) if e.role == "title"]
    assert all(line.anchor.value == "start" for line in title)


# ------------------------------------------------------------------ puzzle and solution pages


def test_puzzle_page_settings_change_presentation_not_content():
    style = {
        "version": 1,
        "puzzle_pages": {
            "header_align": "left",
            "header_rule": True,
            "theme_label": False,
            "grid_frame": 2,
            "word_size": 15,
            "word_columns": 2,
            "word_rule": True,
        },
    }
    plain, styled = build(book()), build(book(style))
    index = next(i for i, p in enumerate(plain.plan.pages) if p.kind is PageKind.PUZZLE) + 1
    found = roles(styled, index)
    assert "header_rule" in found and "word_rule" in found and "theme" not in found
    grid = next(e for e in elements(styled, page=index) if e.role == "puzzle_grid")
    original = next(e for e in elements(plain, page=index) if e.role == "puzzle_grid")
    assert grid.rows == original.rows and grid.frame_width == 2
    words = [e for e in elements(styled, TextLine, index) if e.role == "word_list"]
    assert {w.size for w in words} == {15} and len({round(w.x, 2) for w in words}) <= 2


def test_solution_marks_stay_readable_in_monochrome():
    styled = build(book({"version": 1, "preset": "high_contrast"}))
    pages = [i + 1 for i, p in enumerate(styled.plan.pages) if p.kind is PageKind.SOLUTIONS]
    grids = [e for page in pages for e in elements(styled, page=page) if e.role == "solution_grid"]
    assert grids and all(g.muted_gray == pytest.approx(0.62) for g in grids)
    assert all(m.line_width == 1.5 for g in grids for m in g.marks)
    assert all(g.emphasized_face.value == "bold" for g in grids)


# ------------------------------------------------------------------ theme dividers


DIVIDERS = {
    "start": "recto",
    "themes": [
        {
            "theme": "Engines",
            "text": "Pistons, valves and cams.",
            "quote": "Measure twice.",
            "attribution": "A. Mechanic",
        },
        {"theme": "Tools", "title": "In the Toolbox"},
    ],
}


def test_dividers_are_explicit_plan_pages_before_each_theme_group():
    project = book(dividers=DIVIDERS, puzzles=6)
    report, plan = build_publication(project)
    assert verify_publication_plan(plan, project, report).valid
    pages = plan.pages
    dividers = [p for p in pages if p.kind is PageKind.DIVIDER]
    assert [d.divider.title for d in dividers] == ["Engines", "In the Toolbox", "Racing"]
    for divider in dividers:
        following = pages[divider.index]
        assert following.puzzle is not None and following.puzzle.theme == divider.divider.theme
        assert divider.side.value == "recto" and not divider.number.displayed
    blanks = [p for p in pages if p.blank_reason == "divider_recto_start"]
    assert all(p.side.value == "verso" for p in blanks)
    assert plan.statistics.divider_pages == 3 and plan.to_dict()["statistics"]["divider_pages"] == 3
    # Cross-references follow the inserted pages.
    for page in pages:
        for item in page.solutions:
            assert pages[item.puzzle_page - 1].puzzle == item.puzzle
    # Without dividers, the same book keeps its earlier plan and pages.
    plain_report, plain = build_publication(book(puzzles=6, themes=THEMES, dividers=None))
    assert len(pages) > len(plain.pages)
    assert "divider_pages" not in plain.to_dict()["statistics"]


def test_divider_page_prints_only_the_authors_words():
    built = build(book(dividers=DIVIDERS, puzzles=6))
    index = next(i for i, p in enumerate(built.plan.pages) if p.kind is PageKind.DIVIDER) + 1
    text = PdfReader(io.BytesIO(built.pdf)).pages[index - 1].extract_text()
    assert "Engines" in text and "Pistons, valves and cams." in text
    assert "Measure twice." in text and "A. Mechanic" in text
    racing = [
        i + 1 for i, p in enumerate(built.plan.pages) if p.divider and p.divider.theme == "Racing"
    ]
    page = elements(built, page=racing[0])
    assert {e.role for e in page} == {"divider_title", "divider_rule"}  # No invented words.


def test_tampered_divider_plans_fail_verification():
    project = book(dividers=DIVIDERS, puzzles=6)
    report, plan = build_publication(project)
    index = next(i for i, p in enumerate(plan.pages) if p.kind is PageKind.DIVIDER)
    page = plan.pages[index]
    changed = replace(page, divider=replace(page.divider, text="Invented."))
    tampered = replace(plan, pages=plan.pages[:index] + (changed,) + plan.pages[index + 1 :])
    codes = {i.code for i in verify_publication_plan(tampered, project, report).issues}
    assert "divider" in codes
    dropped = replace(plan, pages=tuple(p for p in plan.pages if p.kind is not PageKind.DIVIDER))
    assert verify_publication_plan(dropped, project, report).issues


def test_divider_schema_and_theme_rules():
    with pytest.raises(ProjectError) as error:
        book(dividers={"themes": []}, puzzles=6, themes=("A", "B", "A", "B", "C", "C"))
    assert "themes_not_contiguous" in {i.code for i in error.value.issues}
    with pytest.raises(ProjectError) as error:
        book(dividers={"themes": [{"theme": "Nope"}]}, puzzles=6)
    assert "unknown_theme" in {i.code for i in error.value.issues}
    with pytest.raises(ProjectError) as error:
        book(dividers={"themes": [{"theme": "Tools", "attribution": "X"}]}, puzzles=6)
    assert "requires_quote" in {i.code for i in error.value.issues}


def test_dividers_change_page_count_and_stale_the_interior(tmp_path):
    source = tmp_path / "book"
    source.mkdir()
    plain = book(puzzles=6)
    built = build(plain)
    write_interior(built, tmp_path / "out", source)
    with_dividers = book(dividers=DIVIDERS, puzzles=6)
    report = preflight_interior(with_dividers, read_interior_artifacts(tmp_path / "out")).report
    outcomes = {r.rule.code: r.outcome.value for r in report.results}
    assert outcomes["source_current"] == "failed"
    assert len(build(with_dividers).layout.pages) > len(built.layout.pages)


# ------------------------------------------------------------------ photographs


def _photo_book(tmp_path, data=None, layout="photo_feature", divider_photo=False):
    source = tmp_path / "book"
    source.mkdir(parents=True)
    imported = import_photo(source, data or photo_bytes(3000, 2400), "lake.jpg")
    image = {"path": imported.path, "sha256": imported.info.sha256}
    style = {"version": 1, "title_page": {"layout": layout, "photo": {"image": image}}}
    if divider_photo:
        style = {"version": 1, "dividers": {"photos": [{"theme": "Tools", "image": image}]}}
    project = book(style, dividers=DIVIDERS if divider_photo else None, puzzles=6)
    return project, source


def test_photo_feature_prints_python_grayscale_pixels(tmp_path):
    project, source = _photo_book(tmp_path)
    built = build(project, source)
    (block,) = elements(built, ImageBlock)
    assert built.layout.pages[0].frame.content.contains(block.box, 0.01)
    assert block.effective_dpi > 300
    page = PdfReader(io.BytesIO(built.pdf)).pages[0]
    (image,) = page["/Resources"]["/XObject"].values()
    image = image.get_object()
    assert image["/ColorSpace"] == "/DeviceGray" and list(image["/Filter"]) == ["/DCTDecode"]
    assert b"Exif" not in built.pdf
    pdfium = pytest.importorskip("pypdfium2")
    raster = pdfium.PdfDocument(built.pdf)[0].render(scale=0.5).to_pil().convert("RGB")
    x, y = (block.box.x + 30) * 0.5, (792 - block.box.top + 30) * 0.5
    red, green, blue = raster.getpixel((int(x), int(y)))
    assert red == green == blue  # A colored photo prints as gray, not as an assumption.


def test_photo_interiors_need_their_project_folder_and_preflight_resolution(tmp_path):
    project, source = _photo_book(tmp_path)
    with pytest.raises(InteriorError) as error:
        build(project)
    assert error.value.issues[0].code == "interior_photo_unavailable"
    built = build(project, source)
    write_interior(built, tmp_path / "out", source)
    artifacts = read_interior_artifacts(tmp_path / "out")
    report = preflight_interior(project, artifacts, source_directory=source).report
    outcomes = {r.rule.code: r.outcome.value for r in report.results}
    assert outcomes["raster_images"] == "passed" and outcomes["kdp_image_resolution"] == "passed"
    small, small_source = _photo_book(tmp_path / "small", photo_bytes(400, 300))
    low = build(small, small_source)
    assert "image_too_small" in {w.code for w in low.layout.warnings}


def test_divider_photographs_print_on_their_theme_divider(tmp_path):
    project, source = _photo_book(tmp_path, divider_photo=True)
    built = build(project, source)
    blocks = [
        (page.number, e)
        for page in built.layout.pages
        for e in page.elements
        if isinstance(e, ImageBlock)
    ]
    assert len(blocks) == 1
    number, block = blocks[0]
    assert built.plan.pages[number - 1].divider.theme == "Tools" and block.role == "divider_photo"


def test_one_photograph_on_several_dividers_is_embedded_once(tmp_path):
    # Regression: the JPEG path registered a photograph again on every page that
    # showed it (ReportLab resets its per-page form list), which crashed the render.
    project, source = _photo_book(tmp_path, divider_photo=True)
    data = project.to_dict()
    (photo,) = data["interior"]["dividers"]["photos"]
    data["interior"]["dividers"]["photos"] = [photo, {**photo, "theme": "Engines"}]
    project = validate_project(data).require_project()
    built = build(project, source)
    pages = [
        page.number
        for page in built.layout.pages
        for e in page.elements
        if isinstance(e, ImageBlock)
    ]
    assert len(pages) == 2
    reader = PdfReader(io.BytesIO(built.pdf))
    references = {
        reader.pages[number - 1]["/Resources"]["/XObject"].raw_get(name).idnum
        for number in pages
        for name in reader.pages[number - 1]["/Resources"]["/XObject"]
    }
    assert len(references) == 1  # one image object, drawn on both divider pages
    assert build(project, source).pdf == built.pdf


def test_styled_interior_bytes_repeat_across_processes(tmp_path):
    project, source = _photo_book(tmp_path)
    expected = hashlib.sha256(build(project, source).pdf).hexdigest()
    yaml_path = source / "book.yaml"
    from puzzlepress.yaml_io import dump_project

    data = project.to_dict()
    data["output"] = {"directory": "../out"}
    yaml_path.write_text(dump_project(validate_project(data).require_project()), encoding="utf-8")
    script = (
        "import hashlib;from puzzlepress import load_project;"
        "from puzzlepress.interior import build_interior;"
        "from puzzlepress.interior.spec import PAPERBACK_LETTER;"
        f"l=load_project({str(source)!r});"
        "print(hashlib.sha256(build_interior(l.project,PAPERBACK_LETTER,"
        "l.source_path.parent).pdf).hexdigest())"
    )
    for seed in ("0", "777"):
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")},
            check=True,
        )
        assert result.stdout.strip() == expected


def test_style_change_stales_a_built_interior(tmp_path):
    source = tmp_path / "book"
    source.mkdir()
    write_interior(build(book()), tmp_path / "out", source)
    styled = book({"version": 1, "preset": "modern"})
    report = preflight_interior(styled, read_interior_artifacts(tmp_path / "out")).report
    stale = [f for f in report.findings if f.rule.code == "source_current"]
    assert stale and "style was added" in stale[0].message
