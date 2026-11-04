"""Coloring books: covers, template variables, publishing metadata and rights (Interval 5)."""

import copy
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pypdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coloring_production import publishing, write_book  # noqa: E402

from puzzlepress import dump_project, validate_project  # noqa: E402
from puzzlepress.cover.build import build_cover, write_cover  # noqa: E402
from puzzlepress.cover.issues import CoverError  # noqa: E402
from puzzlepress.cover.preflight import preflight_cover  # noqa: E402
from puzzlepress.cover_template import BINDINGS, template_values  # noqa: E402
from puzzlepress.interior import build_interior, print_profile, write_interior  # noqa: E402
from puzzlepress.interior.spec import KDP_COVER  # noqa: E402
from puzzlepress.project import load_project  # noqa: E402
from puzzlepress.publishing import evaluate_readiness, validate_metadata  # noqa: E402
from puzzlepress.publishing.review import review_identity  # noqa: E402
from puzzlepress.publishing.rules import (  # noqa: E402
    COLORING_RULESET,
    RULESET_ID,
    WORD_SEARCH_RULESET,
)


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic production coloring book with a built interior (shared, read-only)."""
    return write_book(tmp_path_factory.mktemp("coloring-production"))


@pytest.fixture
def book(made: Path, tmp_path: Path) -> Path:
    """A private copy of the book and its build directory."""
    shutil.copytree(made.parent, tmp_path / "copy")
    return tmp_path / "copy" / "book"


def _save(path: Path, data: dict[str, object]) -> None:
    project = validate_project(data).require_project()
    (path / "book.yaml").write_text(dump_project(project), encoding="utf-8")


def _cover_text(directory: Path) -> str:
    return pypdf.PdfReader(directory / "cover.pdf").pages[0].extract_text()


def _rebuild(book: Path, build: Path, profile: str = "paperback-8.5x11") -> None:
    project = load_project(book).project
    spec = print_profile(profile)
    write_interior(build_interior(project, spec, book), build, book)  # type: ignore[arg-type]


# ---------------------------------------------------------------- cover


def test_coloring_cover_builds_with_the_built_page_count_and_spine(book: Path) -> None:
    build = book.parent / "build"
    project = load_project(book).project
    cover = build_cover(project, book, build)
    write_cover(cover, build, book)
    interior = json.loads((build / "interior.json").read_text(encoding="utf-8"))
    manifest = json.loads((build / "cover.json").read_text(encoding="utf-8"))
    pages = interior["page_count"]
    assert pages == 28  # 3 front matter + blank, then 12 drawings each with a blank back
    assert manifest["interior"]["page_count"] == pages
    spine = KDP_COVER.spine_width(pages, cover.layout.geometry.paper)
    assert cover.layout.geometry.spine_width == pytest.approx(spine)
    # Live variables are filled in from the built interior, never from the source.
    assert "Twelve drawings to color, 28 pages, 8.5 x 11 in" in _cover_text(build)
    report = preflight_cover(project, book, build)
    assert report.state == "current"
    assert report.structurally_valid and report.kdp_ready


def test_cream_paper_changes_the_spine_and_nothing_is_guessed(book: Path) -> None:
    build = book.parent / "build"
    project = load_project(book).project
    white = build_cover(project, book, build).layout.geometry
    _rebuild(book, build, "paperback-8.5x11-cream")
    cream = build_cover(project, book, build).layout.geometry
    assert white.paper.value == "white" and cream.paper.value == "cream"
    assert cream.spine_width == pytest.approx(KDP_COVER.spine_width(28, cream.paper))
    assert cream.spine_width > white.spine_width


def test_page_count_change_makes_the_cover_stale_until_rebuilt(book: Path) -> None:
    build = book.parent / "build"
    project = load_project(book).project
    write_cover(build_cover(project, book, build), build, book)
    data = project.to_dict()
    data["coloring"]["pages"] = data["coloring"]["pages"][:-2]  # two fewer drawings
    _save(book, data)
    _rebuild(book, build)
    project = load_project(book).project
    assert json.loads((build / "interior.json").read_text())["page_count"] == 24
    report = preflight_cover(project, book, build)
    assert report.state == "stale"
    assert not report.kdp_ready
    readiness = evaluate_readiness(project, book, build)
    assert any(f.rule.code == "cover_matches_interior" for f in readiness.findings)
    assert not readiness.package_ready
    write_cover(build_cover(project, book, build), build, book)
    assert "24 pages" in _cover_text(build)
    assert preflight_cover(project, book, build).state == "current"


def test_cover_needs_a_current_interior(book: Path) -> None:
    build = book.parent / "build"
    data = load_project(book).project.to_dict()
    data["book"]["subtitle"] = "Changed"
    _save(book, data)
    with pytest.raises(CoverError) as raised:
        build_cover(load_project(book).project, book, build)
    assert raised.value.issues[0].code == "interior_stale"


def test_template_values_are_engine_neutral(made: Path) -> None:
    project = load_project(made).project
    values = template_values(project)
    assert values["title"] == project.book.title
    assert values["artwork_count"] == "12"
    # Live variables pass through apply unchanged; word-search bindings have no value.
    assert values["page_count"] == "{page_count}"
    assert values["trim_size"] == "{trim_size}"
    assert "puzzle_count" not in values and "solutions" not in values
    assert {"artwork_count", "page_count", "trim_size"} <= set(BINDINGS)


def test_word_search_template_values_gain_only_live_passthroughs(garden) -> None:
    values = template_values(garden)
    assert "artwork_count" not in values
    assert values["page_count"] == "{page_count}"
    assert values["puzzle_count"] == str(len(garden.word_search.puzzles))


def test_binding_typed_into_a_text_box_is_reported(made: Path) -> None:
    from puzzlepress.studio.covering import display_checks

    project = load_project(made).project
    data = project.to_dict()
    data["cover"]["elements"][-1]["text"] = "{artwork_count} drawings, {page_count} pages"
    checks = display_checks(validate_project(data).require_project())
    (found,) = [c for c in checks if c["code"] == "template_binding_in_text"]
    assert "{artwork_count}" in found["message"] and "{page_count} is" not in found["message"]
    assert not [c for c in display_checks(project) if c["code"] == "template_binding_in_text"]


# ---------------------------------------------------------------- publishing


def _codes(report) -> set[str]:
    return {f.rule.code for f in report.findings}


def _with(made: Path, **overrides: object):
    data = load_project(made).project.to_dict()
    data["publishing"] = publishing(**overrides)
    return validate_project(data).require_project()


def test_coloring_metadata_uses_its_own_ruleset(made: Path, garden) -> None:
    report = validate_metadata(load_project(made).project)
    assert report.ruleset is COLORING_RULESET
    assert report.to_dict()["ruleset"]["id"] == "puzzlepress-kdp-publishing-coloring"
    assert report.valid, [f.message for f in report.findings]
    word_search = validate_metadata(garden)
    assert word_search.ruleset is WORD_SEARCH_RULESET
    assert word_search.to_dict()["ruleset"]["id"] == RULESET_ID
    assert not set(COLORING_RULESET.codes) - set(WORD_SEARCH_RULESET.codes) & {
        r.rule.code for r in word_search.results
    }


def test_artwork_rights_must_be_declared(made: Path) -> None:
    data = load_project(made).project.to_dict()
    del data["publishing"]["content_rights"]
    report = validate_metadata(validate_project(data).require_project())
    assert "content_rights_declared" in _codes(report)
    assert not report.valid
    project = _with(made, content_rights={"interior_artwork": "own_work"})
    findings = [f for f in validate_metadata(project).findings]
    undecided = {f.field for f in findings if f.rule.code == "content_rights_declared"}
    assert undecided == {
        "publishing.content_rights.cover_artwork",
        "publishing.content_rights.text",
    }


@pytest.mark.parametrize(
    ("basis", "phrase"),
    [
        ("licensed", "licence"),
        ("public_domain", "proof"),
        ("ai_tool_terms", "terms"),
        ("commissioned", "agreement"),
    ],
)
def test_rights_that_need_evidence_are_warnings(made: Path, basis: str, phrase: str) -> None:
    rights = {"interior_artwork": basis, "cover_artwork": "none", "text": "own_work"}
    report = validate_metadata(_with(made, content_rights=rights))
    (warning,) = [f for f in report.findings if f.rule.code == "content_rights_review"]
    assert warning.severity.value == "warning" and phrase in warning.message
    assert "content_rights_declared" not in _codes(report)


def test_ai_generated_artwork_declared_own_work_is_questioned(made: Path) -> None:
    project = _with(
        made,
        ai_disclosure={
            "text": "human",
            "images": "ai_generated",
            "translations": "none",
            "interior_artwork": "ai_generated",
            "cover_artwork": "none",
        },
    )
    report = validate_metadata(project)
    messages = [f.message for f in report.findings if f.rule.code == "content_rights_review"]
    assert any("AI-generated and your own work" in m for m in messages)
    required = [f for f in report.findings if f.rule.code == "ai_disclosure_required"]
    assert required and "images" in required[0].message


def test_artwork_origin_must_be_declared_and_agree_with_images(made: Path) -> None:
    project = _with(
        made, ai_disclosure={"text": "human", "images": "human", "translations": "none"}
    )
    report = validate_metadata(project)
    fields = {f.field for f in report.findings if f.rule.code == "artwork_origin_declared"}
    assert fields == {
        "publishing.ai_disclosure.interior_artwork",
        "publishing.ai_disclosure.cover_artwork",
    }
    assert not report.disclosure_complete
    # The cover is AI-generated: KDP's single images answer must say so.
    project = _with(
        made,
        ai_disclosure={
            "text": "human",
            "images": "human",
            "translations": "none",
            "interior_artwork": "human",
            "cover_artwork": "ai_generated",
        },
    )
    (finding,) = [
        f for f in validate_metadata(project).findings if f.rule.code == "artwork_origin_consistent"
    ]
    assert finding.required == "ai_generated" and finding.actual == "human"
    # AI-assisted artwork needs no disclosure, and agrees with an ai_assisted answer.
    project = _with(
        made,
        ai_disclosure={
            "text": "ai_assisted",
            "images": "ai_assisted",
            "translations": "none",
            "interior_artwork": "ai_assisted",
            "cover_artwork": "human",
        },
    )
    report = validate_metadata(project)
    assert report.disclosure_complete, [f.message for f in report.findings]


def test_coloring_declarations_are_refused_for_word_search(garden) -> None:
    data = garden.to_dict()
    data["composition"] = data.get("composition") or {}
    data["publishing"] = {
        "version": 2,
        "content_rights": {"interior_artwork": "own_work"},
        "ai_disclosure": {"interior_artwork": "human"},
    }
    issues = {(i.path, i.code) for i in validate_project(data).issues}
    assert ("publishing.content_rights", "not_applicable_for_engine") in issues
    assert ("publishing.ai_disclosure.interior_artwork", "not_applicable_for_engine") in issues


def test_schema_refuses_none_outside_cover_artwork(made: Path) -> None:
    data = load_project(made).project.to_dict()
    data["publishing"]["content_rights"]["text"] = "none"
    data["publishing"]["ai_disclosure"]["interior_artwork"] = "none"
    issues = {(i.path, i.code) for i in validate_project(data).issues}
    assert ("publishing.content_rights.text", "choice") in issues
    assert ("publishing.ai_disclosure.interior_artwork", "choice") in issues


def test_coloring_low_content_and_isbn_rules(made: Path) -> None:
    report = validate_metadata(_with(made, low_content=None))
    (finding,) = [f for f in report.findings if f.rule.code == "low_content_decided"]
    assert "coloring books" in finding.message and "puzzle" not in finding.message
    report = validate_metadata(_with(made, low_content=True))
    codes = _codes(report)
    assert {"low_content_review", "isbn_eligibility"} <= codes  # no free ISBN when low-content
    report = validate_metadata(_with(made, isbn={"mode": "none", "value": None}))
    assert "isbn_eligibility" in _codes(report)
    report = validate_metadata(_with(made, isbn={"mode": "own", "value": "9780306406157"}))
    assert "isbn_valid" not in _codes(report)
    assert "isbn_imprint" in _codes(report)  # an own ISBN needs the registered imprint
    report = validate_metadata(_with(made, isbn={"mode": "undecided", "value": None}))
    assert "isbn_decided" in _codes(report)


@pytest.mark.parametrize(
    ("description", "fails"),
    [
        ("Twelve drawings to color.", False),
        ("12 coloring pages of shapes.", False),
        ("Fifty beautiful coloring pages.", True),
        ("40 designs to relax with.", True),
        ("Answers at the back.", True),
        ("Printed on 8.5 x 11 pages.", False),
    ],
)
def test_description_drawing_claims(made: Path, description: str, fails: bool) -> None:
    report = validate_metadata(_with(made, description=description))
    assert ("description_claims" in _codes(report)) is fails


def test_rights_review_covers_artwork_bytes_captions_and_declarations(made: Path) -> None:
    project = load_project(made).project
    rights = review_identity(project, "rights")
    book = project.coloring
    assert book is not None
    # Reordering pages is composition, not content: the confirmation still applies.
    reordered = replace(project, coloring=replace(book, pages=tuple(reversed(book.pages))))
    assert review_identity(reordered, "rights") == rights
    captioned = replace(
        project,
        coloring=replace(
            book, artwork=(replace(book.artwork[0], title="Renamed"), *book.artwork[1:])
        ),
    )
    assert review_identity(captioned, "rights") != rights
    swapped = replace(
        project,
        coloring=replace(
            book, artwork=(replace(book.artwork[0], sha256="0" * 64), *book.artwork[1:])
        ),
    )
    assert review_identity(swapped, "rights") != rights
    data = project.to_dict()
    data["publishing"]["content_rights"]["interior_artwork"] = "licensed"
    declared = validate_project(data).require_project()
    assert review_identity(declared, "rights") != rights
    report = validate_metadata(declared)
    states = {c.name: c.state for c in report.confirmations}
    assert states["rights"] == "stale" and states["metadata"] == "confirmed"
    statement = next(c for c in report.confirmations if c.name == "rights").statement
    assert "artwork" in statement and "word lists" not in statement


def test_word_search_publishing_section_bytes_are_unchanged(garden) -> None:
    from puzzlepress.publishing_config import PublishingConfig

    data = PublishingConfig().to_dict()
    assert "content_rights" not in data
    assert set(data["ai_disclosure"]) == {"text", "images", "translations"}
    assert copy.deepcopy(data) == data
