"""Studio's New book: POST /api/projects and GET /api/project-types."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from puzzlepress.creation import CREATION_MARKER
from puzzlepress.studio.server import create_app


@pytest.fixture
def library(tmp_path: Path) -> Path:
    books = tmp_path / "books"
    books.mkdir()
    return books


@pytest.fixture
def client(library: Path, tmp_path: Path) -> TestClient:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    return TestClient(create_app(library, frontend))


def test_types_list_both_engines_and_the_print_profiles(client: TestClient) -> None:
    data = client.get("/api/project-types").json()
    assert [t["kind"] for t in data["types"]] == ["word_search", "coloring"]
    assert {p["paper"] for p in data["profiles"]} == {"white", "cream"}
    assert all(p["trim"] == {"width": 612, "height": 792} for p in data["profiles"])


def test_created_books_are_immediately_in_the_library(client: TestClient, library: Path) -> None:
    assert client.get("/api/projects").json()["projects"] == []
    response = client.post(
        "/api/projects",
        json={"kind": "coloring", "key": "", "title": "Woodland Coloring", "subject": "Nature"},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["key"] == "woodland-coloring" and created["recovered"] is False
    assert created["engine"]["kind"] == "coloring"
    assert created["source"]["catalog"] == {"subject": "Nature"}
    assert created["revision"].startswith("sha256-")
    listed = client.get("/api/projects").json()["projects"]
    assert [p["key"] for p in listed] == ["woodland-coloring"]
    # It opens like any project, and the SPA serves its pages.
    assert client.get("/api/projects/woodland-coloring").json() == {
        k: v for k, v in created.items() if k != "recovered"
    }
    assert client.get("/books/woodland-coloring/settings").status_code == 200
    assert client.get("/create").status_code == 200
    ws = client.post(
        "/api/projects", json={"kind": "word_search", "key": "words", "title": "Words"}
    ).json()
    assert ws["engine"]["kind"] == "word_search"
    assert ws["source"]["word_search"]["puzzles"][0]["id"] == "starter-puzzle"


def test_refusals_are_structured_and_write_nothing(client: TestClient, library: Path) -> None:
    client.post("/api/projects", json={"kind": "coloring", "key": "taken", "title": "T"})
    before = (library / "taken" / "book.yaml").read_bytes()
    for body, code in (
        ({"kind": "coloring", "key": "taken", "title": "T"}, "project_exists"),
        ({"kind": "coloring", "key": "../up", "title": "T"}, "invalid_key"),
        ({"kind": "coloring", "key": "a%2Fb", "title": "T"}, "invalid_key"),
        ({"kind": "maze", "key": "maze", "title": "T"}, "unsupported_type"),
        ({"kind": "coloring", "key": "x", "title": ""}, "type"),
    ):
        response = client.post("/api/projects", json=body)
        assert response.status_code == 422, (body, response.text)
        assert response.json()["error"]["issues"][0]["code"] == code
    assert (library / "taken" / "book.yaml").read_bytes() == before
    assert sorted(p.name for p in library.iterdir()) == ["taken"]
    unknown = client.post(
        "/api/projects", json={"kind": "coloring", "key": "k", "title": "T", "x": 1}
    )
    assert unknown.status_code == 422


def test_cross_site_creation_is_rejected(client: TestClient, library: Path) -> None:
    response = client.post(
        "/api/projects",
        json={"kind": "coloring", "key": "evil", "title": "T"},
        headers={"origin": "https://example.com"},
    )
    assert response.status_code == 403
    assert list(library.iterdir()) == []


def test_an_interrupted_creation_is_hidden_then_recovered(
    client: TestClient, library: Path
) -> None:
    folder = library / "crashed"
    folder.mkdir()
    (folder / CREATION_MARKER).write_text("{}", encoding="utf-8")
    assert client.get("/api/projects").json()["projects"] == []
    response = client.post(
        "/api/projects", json={"kind": "coloring", "key": "crashed", "title": "T"}
    )
    assert response.status_code == 201 and response.json()["recovered"] is True


def test_a_created_book_builds_with_its_own_paper(client: TestClient) -> None:
    created = client.post(
        "/api/projects",
        json={
            "kind": "word_search",
            "key": "cream-book",
            "title": "Cream",
            "profile": "paperback-8.5x11-cream",
        },
    ).json()
    revision = created["revision"]
    conflict = client.post(
        "/api/projects/cream-book/interior/build",
        json={"revision": revision, "profile": "paperback-8.5x11"},
    )
    assert conflict.status_code == 422
    assert conflict.json()["error"]["code"] == "profile_conflict"
    built = client.post("/api/projects/cream-book/interior/build", json={"revision": revision})
    assert built.status_code == 200, built.text
    status = built.json()
    assert status["build"] == {"success": True}
    assert status["profile"] == status["authored_profile"] == "paperback-8.5x11-cream"
