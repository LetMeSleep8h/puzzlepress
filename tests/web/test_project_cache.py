"""Studio's parsed-project cache (Interval 10): fast, never stale, never shared wrongly.

ProjectStore.snapshot always reads and hashes book.yaml; it reuses a parsed project
only for byte-identical source under the same key.
"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from puzzlepress.errors import ProjectError
from puzzlepress.studio import service as service_module
from puzzlepress.studio.editing import DraftStore
from puzzlepress.studio.server import create_app
from puzzlepress.studio.service import ProjectStore
from tests.helpers import DEMO


@pytest.fixture
def library(tmp_path: Path) -> Path:
    books = tmp_path / "books"
    for key in ("one", "two"):
        (books / key).mkdir(parents=True)
        shutil.copyfile(DEMO / "book.yaml", books / key / "book.yaml")
    return books


def count_parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = service_module.parse_project

    def counting(source: str):  # type: ignore[no-untyped-def]
        calls.append(source)
        return real(source)

    monkeypatch.setattr(service_module, "parse_project", counting)
    return calls


def test_unchanged_source_is_parsed_once(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = count_parses(monkeypatch)
    store = ProjectStore(library)
    first = store.snapshot("one")
    second = store.snapshot("one")
    assert first == second and len(calls) == 1
    assert second[0] is first[0]  # Immutable: the same object is safe to share.


def test_an_external_edit_is_seen_at_once(library: Path) -> None:
    store = ProjectStore(library)
    before, revision = store.snapshot("one")
    source = library / "one" / "book.yaml"
    text = source.read_text(encoding="utf-8").replace(
        f"title: {before.book.title}", "title: Edited Outside Studio", 1
    )
    source.write_text(text, encoding="utf-8")  # As the CLI or an editor would.
    after, changed = store.snapshot("one")
    assert changed != revision and after.book.title == "Edited Outside Studio"


def test_an_invalid_edit_is_never_served_from_the_cache(library: Path) -> None:
    store = ProjectStore(library)
    store.snapshot("one")
    (library / "one" / "book.yaml").write_text("schema_version: 99\n", encoding="utf-8")
    with pytest.raises(ProjectError):
        store.snapshot("one")
    with pytest.raises(ProjectError):  # Still invalid: nothing was remembered.
        store.snapshot("one")


def test_projects_never_leak_between_keys(library: Path) -> None:
    store = ProjectStore(library)
    source = library / "two" / "book.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace("id: ", "id: other-", 1), encoding="utf-8"
    )
    one, _ = store.snapshot("one")
    two, _ = store.snapshot("two")
    assert one.book.id != two.book.id
    assert store.snapshot("one")[0].book.id == one.book.id


def test_the_cache_is_bounded(library: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "PARSED_ENTRIES", 1)
    store = ProjectStore(library)
    store.snapshot("one")
    store.snapshot("two")
    assert list(store._parsed) == ["two"]


def test_saves_and_revision_checks_are_unchanged(library: Path) -> None:
    """Two Studio windows (one store) and a stale revision: the second save is refused,
    and every window then reads the saved bytes."""
    store = ProjectStore(library)
    drafts = DraftStore(store)
    project, revision = store.snapshot("one")
    source = project.to_dict()
    source["book"]["title"] = "Saved In Studio"
    drafts.save("one", source, revision)
    from puzzlepress.studio.service import StudioError

    stale = project.to_dict()
    stale["book"]["title"] = "From A Stale Window"
    with pytest.raises(StudioError) as refused:
        drafts.save("one", stale, revision)
    assert refused.value.status == 409
    assert store.snapshot("one")[0].book.title == "Saved In Studio"
    assert ProjectStore(library).snapshot("one")[0].book.title == "Saved In Studio"


def test_the_api_serves_edits_made_between_requests(library: Path, tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(library, frontend))
    first = client.get("/api/projects/one").json()
    source = library / "one" / "book.yaml"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            f"title: {first['source']['book']['title']}", "title: Changed Between Requests", 1
        ),
        encoding="utf-8",
    )
    second = client.get("/api/projects/one").json()
    assert second["revision"] != first["revision"]
    assert second["source"]["book"]["title"] == "Changed Between Requests"
