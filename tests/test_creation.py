"""Creating projects: starter sources, safe names, atomic creation and recovery."""

import os
from pathlib import Path

import pytest

from puzzlepress import creation
from puzzlepress.cli import main
from puzzlepress.creation import (
    CREATION_MARKER,
    STARTER_TITLE,
    NewProject,
    create_project,
    interrupted,
    project_types,
    suggest_key,
)
from puzzlepress.engines.kind import EngineKind
from puzzlepress.engines.registry import engine_for
from puzzlepress.errors import ProjectError
from puzzlepress.identity import build_identity
from puzzlepress.interior import PROFILES
from puzzlepress.print_config import PROFILE_IDS
from puzzlepress.project import load_project
from puzzlepress.source_store import source_revision


def code(raised: pytest.ExceptionInfo[ProjectError]) -> str:
    return raised.value.issues[0].code


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "books"
    root.mkdir()
    return root


def test_word_search_starter_is_valid_buildable_and_labelled(library: Path) -> None:
    created = create_project(library, NewProject("word_search", "my-words", "My Words"))
    assert created.path == library.resolve() / "my-words" / "book.yaml"
    assert created.revision == source_revision(created.path)
    assert not created.recovered
    project = load_project(created.path).project
    assert project == created.project and project.engine is EngineKind.WORD_SEARCH
    assert project.word_search is not None
    (puzzle,) = project.word_search.puzzles
    # A placeholder that announces itself on the printed page, never filler.
    assert puzzle.title == STARTER_TITLE and "replace" in puzzle.title.lower()
    assert project.composition is not None and project.composition.front_matter
    assert all(item.kind.value != "copyright_page" for item in project.composition.front_matter)
    assert project.output.directory == "../../build/my-words"
    assert project.catalog is None and project.printing is None
    # The seed is explicit in the file and derived from the key: reproducible.
    again = create_project(library, NewProject("word_search", "my-words-2", "My Words"))
    assert again.project.build.seed != project.build.seed
    assert str(project.build.seed) in created.path.read_text(encoding="utf-8")
    engine = engine_for(project)
    content, plan = engine.build_publication(project, created.path.parent)
    assert engine.verify_publication(plan, project, content).valid and plan.complete


def test_coloring_starts_empty_and_reports_why_it_is_incomplete(library: Path) -> None:
    created = create_project(
        library,
        NewProject(
            "coloring",
            "woodland",
            "Woodland Coloring",
            author="A. Artist",
            subject="Nature",
            collection="Forest series",
            profile="paperback-8.5x11-cream",
            template="with-notes",
        ),
    )
    project = created.project
    assert project.engine is EngineKind.COLORING and project.coloring is not None
    assert project.coloring.artwork == () and project.coloring.pages == ()
    assert project.book.author == "A. Artist"
    assert project.catalog is not None and project.catalog.collection == "Forest series"
    assert project.printing is not None and project.printing.profile == "paperback-8.5x11-cream"
    assert project.composition is not None
    assert [m.kind.value for m in project.composition.back_matter] == ["notes"]
    engine = engine_for(project)
    content, plan = engine.build_publication(project, created.path.parent)
    verification = engine.verify_publication(plan, project, content)
    assert not plan.complete
    assert "no_coloring_pages" in {d.code for d in plan.diagnostics} | {
        i.code for i in verification.issues
    }


@pytest.mark.parametrize(
    "key",
    [
        "",
        "My Book",
        "../escape",
        "..",
        "a/b",
        "a\\b",
        "C:",
        "dots.name",
        "-lead",
        "trail-",
        "double--hyphen",
        "UPPER",
        "x" * 65,
        "café",
    ],
)
def test_unsafe_names_are_refused_before_anything_is_written(library: Path, key: str) -> None:
    with pytest.raises(ProjectError) as raised:
        create_project(library, NewProject("coloring", key, "Title"))
    assert code(raised) == "invalid_key"
    assert list(library.iterdir()) == []
    assert list(library.parent.iterdir()) == [library]


@pytest.mark.parametrize("key", ["con", "nul", "com1", "lpt9"])
def test_windows_reserved_names_are_refused(library: Path, key: str) -> None:
    with pytest.raises(ProjectError) as raised:
        create_project(library, NewProject("coloring", key, "Title"))
    assert code(raised) == "reserved"


def test_invalid_values_report_paths_and_write_nothing(library: Path) -> None:
    for request, path, expected in (
        (NewProject("coloring", "a", " "), "book.title", "type"),
        (NewProject("coloring", "a", "T", language="not a tag"), "book.language", "format"),
        (NewProject("maze", "a", "T"), "kind", "unsupported_type"),
        (NewProject("coloring", "a", "T", template="starter"), "template", "unknown_template"),
        (NewProject("coloring", "a", "T", profile="a4"), "profile", "unsupported_profile"),
        (NewProject("coloring", "a", "T", subject="x" * 200), "catalog.subject", "text"),
    ):
        with pytest.raises(ProjectError) as raised:
            create_project(library, request)
        issue = raised.value.issues[0]
        assert (issue.path, issue.code) == (path, expected), request
    assert list(library.iterdir()) == []


def test_an_existing_folder_is_never_overwritten(library: Path) -> None:
    create_project(library, NewProject("coloring", "taken", "First"))
    before = (library / "taken" / "book.yaml").read_bytes()
    with pytest.raises(ProjectError) as raised:
        create_project(library, NewProject("word_search", "taken", "Second"))
    assert code(raised) == "project_exists"
    assert (library / "taken" / "book.yaml").read_bytes() == before
    # An unrelated folder (no marker) is not "recovered" either, even when empty.
    (library / "empty").mkdir()
    with pytest.raises(ProjectError) as raised:
        create_project(library, NewProject("coloring", "empty", "T"))
    assert code(raised) == "project_exists" and list((library / "empty").iterdir()) == []
    (library / "file").write_text("x", encoding="utf-8")
    with pytest.raises(ProjectError) as raised:
        create_project(library, NewProject("coloring", "file", "T"))
    assert code(raised) == "project_exists"


def test_a_failed_creation_removes_exactly_what_it_wrote(
    library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(creation.os, "replace", broken)
    with pytest.raises(OSError, match="disk full"):
        create_project(library, NewProject("coloring", "half", "Half"))
    assert list(library.iterdir()) == []


def test_an_interrupted_creation_is_recognised_and_replaced(library: Path) -> None:
    folder = library / "crashed"
    folder.mkdir()
    (folder / CREATION_MARKER).write_text("{}", encoding="utf-8")
    (folder / ".puzzlepress-abc.tmp").write_text("partial", encoding="utf-8")
    assert interrupted(folder)
    created = create_project(library, NewProject("coloring", "crashed", "Recovered"))
    assert created.recovered
    assert sorted(p.name for p in folder.iterdir()) == ["book.yaml"]
    # A marked folder holding anything else is someone's work: refused, untouched.
    other = library / "kept"
    other.mkdir()
    (other / CREATION_MARKER).write_text("{}", encoding="utf-8")
    (other / "drawing.png").write_bytes(b"art")
    assert not interrupted(other)
    with pytest.raises(ProjectError) as raised:
        create_project(library, NewProject("coloring", "kept", "T"))
    assert code(raised) == "project_exists"
    assert (other / "drawing.png").read_bytes() == b"art"


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_a_symlinked_destination_is_refused(library: Path, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    (library / "link").symlink_to(target, target_is_directory=True)
    with pytest.raises(ProjectError) as raised:
        create_project(library, NewProject("coloring", "link", "T"))
    assert code(raised) in {"project_exists", "invalid_key"}
    assert list(target.iterdir()) == []


def test_missing_library_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ProjectError) as raised:
        create_project(tmp_path / "missing", NewProject("coloring", "a", "T"))
    assert code(raised) == "library_unavailable"


def test_print_section_is_identity_and_catalog_is_not(library: Path) -> None:
    plain = create_project(library, NewProject("coloring", "plain", "T")).project
    filed = create_project(library, NewProject("coloring", "filed", "T", subject="Cars")).project
    cream = create_project(
        library, NewProject("coloring", "cream", "T", profile="paperback-8.5x11-cream")
    ).project

    def same_book(project: object) -> str:
        from dataclasses import replace

        from puzzlepress.models import Book, Build, Output

        assert hasattr(project, "book")
        return build_identity(
            replace(
                project,  # type: ignore[type-var]
                book=Book("x", "T", "en"),
                build=Build(1),
                output=Output("../out"),
            )
        )

    assert same_book(plain) == same_book(filed)
    assert same_book(plain) != same_book(cream)


def test_profile_ids_match_the_print_profiles() -> None:
    assert tuple(PROFILES) == PROFILE_IDS


def test_types_and_key_suggestions() -> None:
    types = {t["kind"]: t for t in project_types()}
    assert set(types) == {"word_search", "coloring"}
    assert types["coloring"]["default_template"] == "simple"
    assert suggest_key("Woodland Coloring: Vol. 2!") == "woodland-coloring-vol-2"
    assert suggest_key("¿¿") == "new-book"


def test_cli_book_new(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(["book", "new", str(library / "cli-book"), "--type", "coloring", "--title", "CLI"])
        == 0
    )
    assert "No artwork yet" in capsys.readouterr().out
    assert load_project(library / "cli-book").project.book.title == "CLI"
    assert (
        main(["book", "new", str(library / "cli-book"), "--type", "coloring", "--title", "X"]) == 1
    )
    assert "project_exists" in capsys.readouterr().err
