"""Derived engine kind, engine validation errors and the engine registry."""

import json
from pathlib import Path

import pytest

from puzzlepress import build_identity, canonical_build_inputs, load_project, validate_project
from puzzlepress.engines import LABELS, SECTIONS, EngineKind, detect_engine, registry
from puzzlepress.engines.registry import WordSearchEngine, engine_for
from puzzlepress.errors import ProjectError
from puzzlepress.publication import build_publication
from puzzlepress.yaml_io import load_yaml
from tests.helpers import CANONICAL_BOOKS, LEGACY_FIXTURE, ROOT

BOOKS = [ROOT / "books" / name for name in CANONICAL_BOOKS] + [LEGACY_FIXTURE]


def _source(path: Path) -> dict:
    return load_yaml((path / "book.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("folder", BOOKS, ids=lambda path: path.name)
def test_every_existing_book_is_a_word_search_book(folder):
    project = load_project(folder).project
    assert project.engine is EngineKind.WORD_SEARCH
    assert detect_engine(_source(folder)) == (EngineKind.WORD_SEARCH, ())
    assert engine_for(project) == WordSearchEngine()
    assert engine_for(project).label == "Word search"


def test_production_book_is_a_word_search_book(production_book):
    assert load_project(production_book).project.engine is EngineKind.WORD_SEARCH


@pytest.mark.parametrize("folder", BOOKS, ids=lambda path: path.name)
def test_engine_is_derived_and_never_serialized(folder):
    project = load_project(folder).project
    assert "engine" not in project.to_dict()
    assert b'engine"' not in canonical_build_inputs(project).replace(b"engine_version", b"")


def test_registry_dispatches_to_the_existing_word_search_pipeline():
    project = load_project(ROOT / "books" / "composition-demo").project
    engine = engine_for(project)
    report, plan = engine.build_publication(project)
    expected_report, expected_plan = build_publication(project)
    assert plan.to_dict() == expected_plan.to_dict()
    assert report.to_dict() == expected_report.to_dict()
    assert engine.verify_publication(plan, project, report).valid


def test_unregistered_engine_is_an_expected_error(monkeypatch):
    project = load_project(ROOT / "books" / "composition-demo").project
    monkeypatch.setattr(registry, "ENGINES", {})
    with pytest.raises(ProjectError) as raised:
        engine_for(project)
    (issue,) = raised.value.issues
    assert (issue.path, issue.code) == ("word_search", "engine_not_buildable")


def test_detection_rules():
    assert detect_engine({}) == (EngineKind.WORD_SEARCH, ())
    assert detect_engine({"content": {"items": ["A"]}}) == (EngineKind.WORD_SEARCH, ())
    assert detect_engine({"word_search": {}}) == (EngineKind.WORD_SEARCH, ())
    assert detect_engine({"coloring": {}}) == (EngineKind.COLORING, ())
    assert detect_engine(["not", "a", "mapping"]) == (None, ())
    kind, (issue,) = detect_engine({"word_search": {}, "coloring": {}})
    assert kind is None
    assert (issue.path, issue.code) == ("coloring", "engine_conflict")
    assert "word_search and coloring" in issue.message
    assert set(SECTIONS) == set(EngineKind) == set(LABELS)


def test_an_engine_this_version_cannot_load_is_reported(monkeypatch):
    """Interval 1 behavior for coloring, kept for any future recognised-but-absent engine."""
    from puzzlepress.engines import kind as kinds

    monkeypatch.setattr(kinds, "AVAILABLE", frozenset({EngineKind.WORD_SEARCH}))
    kind, (issue,) = kinds.detect_engine({"coloring": {}})
    assert kind is None
    assert (issue.path, issue.code) == ("coloring", "engine_unavailable")
    assert "Remove the coloring section" in issue.message


def test_a_coloring_section_is_read_with_coloring_rules_not_word_search():
    source = _source(ROOT / "books" / "garden-demo")
    del source["word_search"]
    source["coloring"] = {"version": 1}
    project = validate_project(source).require_project()
    assert project.engine is EngineKind.COLORING
    source["coloring"] = {"version": 1, "banks": []}
    issues = validate_project(source).issues
    assert [(i.path, i.code) for i in issues] == [("coloring.banks", "unknown_field")]


def test_two_engine_sections_conflict():
    source = _source(ROOT / "books" / "garden-demo")
    source["coloring"] = {"version": 1}
    issues = validate_project(source).issues
    assert [(i.path, i.code) for i in issues] == [("coloring", "engine_conflict")]


def test_word_search_validation_issues_are_unchanged():
    """Detection adds no issue, and changes no order, for word-search sources."""
    source = _source(ROOT / "books" / "composition-demo")
    source["word_search"]["puzzles"][0]["bank"] = "missing"
    source["book"]["id"] = "Bad Id"
    issues = validate_project(source).issues
    assert issues and all(
        issue.code not in {"engine_conflict", "engine_unavailable"} for issue in issues
    )
    assert [issue.path for issue in issues][0] == "book.id"


def test_cli_reports_the_engine(capsys):
    from puzzlepress.cli import main

    assert main(["inspect", str(LEGACY_FIXTURE)]) == 0
    out = capsys.readouterr().out
    assert "Engine: word_search (Word search)" in out
    project = load_project(LEGACY_FIXTURE).project
    assert build_identity(project) in out


def test_cli_reads_word_search_content_under_coloring_with_coloring_rules(tmp_path, capsys):
    from puzzlepress.cli import main
    from puzzlepress.yaml_io import dump_project

    project = load_project(ROOT / "books" / "garden-demo").project
    text = dump_project(project).replace("word_search:", "coloring:", 1)
    (tmp_path / "book.yaml").write_text(text, encoding="utf-8")
    assert main(["validate", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "coloring.banks [unknown_field]" in err
    assert "Traceback" not in err


def test_cli_inspect_names_a_coloring_book_without_puzzle_terms(tmp_path, capsys):
    from puzzlepress.cli import main
    from tests.coloring_helpers import write_coloring_book

    folder = write_coloring_book(tmp_path / "book")
    assert main(["inspect", str(folder)]) == 0
    out = capsys.readouterr().out
    assert "Engine: coloring (Coloring book)" in out
    assert "Artwork: 0" in out and "Coloring pages: 0" in out
    assert "Puzzle" not in out


def test_book_commands_refuse_a_coloring_book(tmp_path, capsys):
    from puzzlepress.cli import main
    from tests.coloring_helpers import write_coloring_book

    folder = write_coloring_book(tmp_path / "book")
    for command in (["book", "plan"], ["book", "build"], ["book", "preflight"]):
        assert main([*command, str(folder)]) == 1, command
        err = capsys.readouterr().err
        assert "Traceback" not in err


def test_engine_summary_is_json_safe():
    from puzzlepress.studio.service import engine_summary

    project = load_project(LEGACY_FIXTURE).project
    assert json.loads(json.dumps(engine_summary(project))) == {
        "kind": "word_search",
        "label": "Word search",
    }
