"""Studio API for the read-only book audit: saved source, collection siblings, no writes."""

from pathlib import Path

from fastapi.testclient import TestClient

from puzzlepress import dump_project
from puzzlepress.studio.server import create_app
from tests.helpers import demo_variant


def _book(books: Path, key: str, collection: str | None, author: str) -> Path:
    def mutate(data: dict) -> None:
        data["book"]["id"] = key
        data["book"]["author"] = author
        data["output"] = {"directory": f"../../build/{key}"}
        if collection:
            data["catalog"] = {"collection": collection}

    folder = books / key
    folder.mkdir(parents=True)
    (folder / "book.yaml").write_text(dump_project(demo_variant(mutate)), encoding="utf-8")
    return folder


def _files(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_audit_reads_the_saved_book_compares_its_collection_and_writes_nothing(tmp_path):
    books = tmp_path / "books"
    _book(books, "first", "Seaside", "Synthetic Author")
    _book(books, "second", "Seaside", "Other Author")
    _book(books, "loner", None, "Synthetic Author")
    before = _files(tmp_path)
    client = TestClient(create_app(books, tmp_path / "frontend"))
    response = client.get("/api/projects/first/audit")
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["key"] == "first" and data["revision"].startswith("sha256-")
    assert data["collection"] == "Seaside" and data["compared"] == ["second"]
    audit = data["audit"]
    assert audit["kind"] == "puzzlepress-book-audit" and audit["compared_books"] == ["second"]
    found = {r["code"]: r for r in audit["recommendations"]}
    assert found["exact_duplicate_previous"]["priority"] == "high"  # Same demo puzzles.
    assert found["series_author"]["priority"] == "medium"
    assert data["markdown"].startswith("# Book audit: ")
    # Cached for identical bytes: the same object comes back.
    assert client.get("/api/projects/first/audit").json() == data
    alone = client.get("/api/projects/loner/audit").json()
    assert alone["compared"] == [] and alone["collection"] is None
    assert any("Series" in item for item in alone["audit"]["not_assessed"])
    assert _files(tmp_path) == before


def test_audit_follows_saved_edits_and_unknown_books_are_404(tmp_path):
    books = tmp_path / "books"
    folder = _book(books, "first", None, "Synthetic Author")
    client = TestClient(create_app(books, tmp_path / "frontend"))
    first = client.get("/api/projects/first/audit").json()
    text = (folder / "book.yaml").read_text(encoding="utf-8")
    edited = text.replace("title: Seaside Word Searches", "title: Seaside Word Searches Again")
    assert edited != text
    (folder / "book.yaml").write_text(edited, encoding="utf-8")
    second = client.get("/api/projects/first/audit").json()
    assert second["revision"] != first["revision"]
    assert second["audit"]["title"] == "Seaside Word Searches Again"
    assert client.get("/api/projects/missing/audit").status_code == 404


def test_audit_deep_link_serves_the_shell(tmp_path):
    books = tmp_path / "books"
    _book(books, "first", None, "Synthetic Author")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    client = TestClient(create_app(books, frontend))
    response = client.get("/books/first/audit")
    assert response.status_code == 200 and "<title>Studio</title>" in response.text
