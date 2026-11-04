"""Studio API for coloring-book artwork: listing, upload, removal, thumbnails."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from puzzlepress import dump_project
from puzzlepress.studio.server import create_app
from tests.coloring_helpers import png, write_coloring_book

SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


@pytest.fixture
def library(tmp_path, garden) -> Path:
    books = tmp_path / "books"
    write_coloring_book(books / "colors")
    (books / "garden").mkdir(parents=True)
    (books / "garden" / "book.yaml").write_text(dump_project(garden), encoding="utf-8")
    return books


@pytest.fixture
def client(library, tmp_path) -> TestClient:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    return TestClient(create_app(library, frontend))


def upload(client, data: bytes, name: str, revision: str, kind: str = "image/png"):
    return client.post(
        "/api/projects/colors/coloring/artwork",
        params={"name": name, "revision": revision},
        content=data,
        headers={"Content-Type": kind},
    )


def listing(client) -> dict:
    response = client.get("/api/projects/colors/coloring")
    assert response.status_code == 200, response.text
    return response.json()


def test_detail_and_library_name_the_coloring_engine(client):
    detail = client.get("/api/projects/colors").json()
    assert detail["engine"] == {"kind": "coloring", "label": "Coloring book"}
    assert detail["source"]["coloring"]["artwork"] == []
    kinds = {p["key"]: p["engine"]["kind"] for p in client.get("/api/projects").json()["projects"]}
    assert kinds == {"colors": "coloring", "garden": "word_search"}


def test_upload_lists_inspects_and_thumbnails_artwork(client, library):
    empty = listing(client)
    assert empty["report"]["artwork"] == [] and empty["report"]["pages"] == 0
    response = upload(client, png(1), "Fox in the Ferns.png", empty["revision"])
    assert response.status_code == 200, response.text
    data = response.json()
    (imported,) = data["imported"]
    assert imported["id"] == "fox-in-the-ferns" and imported["page"] == 1
    (entry,) = data["report"]["artwork"]
    assert entry["inspection"]["info"]["effective_dpi"] == 300.0
    assert entry["adjustments_applied"] is False and entry["pages"] == [1]
    assert data["revision"] != empty["revision"]
    stored = library / "colors" / imported["path"]
    assert stored.read_bytes() == png(1)
    thumb = client.get("/api/projects/colors/coloring/thumbnail", params={"artwork": entry["id"]})
    assert thumb.status_code == 200 and thumb.content.startswith(b"\x89PNG")
    assets = client.post("/api/projects/colors/assets/list", json={}).json()["assets"]
    assert [(a["kind"], a["path"], a["in_use"]) for a in assets] == [
        ("artwork", imported["path"], True)
    ]


def test_a_stale_revision_is_refused_before_anything_is_written(client, library):
    revision = listing(client)["revision"]
    assert upload(client, png(1), "a.png", revision).status_code == 200
    response = upload(client, png(2), "b.png", revision)
    assert response.status_code == 409 and response.json()["error"]["code"] == "source_changed"
    assert len(list((library / "colors" / "coloring-assets").glob("*.png"))) == 1


def test_svg_reaches_python_and_is_explained(client, library):
    revision = listing(client)["revision"]
    response = upload(client, SVG, "vector.svg", revision, "image/svg+xml")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "svg_not_supported" and "PNG" in error["message"]
    assert error["issues"] == [
        {"path": "vector.svg", "code": "svg_not_supported", "message": error["message"]}
    ]
    assert not (library / "colors" / "coloring-assets").exists()
    disguised = upload(client, SVG, "vector.png", revision, "application/octet-stream")
    assert disguised.json()["error"]["code"] == "svg_not_supported"


@pytest.mark.parametrize("kind", ["text/plain", "application/json", "multipart/form-data"])
def test_other_upload_types_are_rejected_at_the_boundary(client, kind):
    revision = listing(client)["revision"]
    response = upload(client, png(1), "a.png", revision, kind)
    assert response.status_code in (403, 422)
    if kind != "application/json":
        assert response.json()["error"]["code"] == "origin_rejected"


def test_cross_origin_uploads_are_rejected(client):
    revision = listing(client)["revision"]
    response = client.post(
        "/api/projects/colors/coloring/artwork",
        params={"name": "a.png", "revision": revision},
        content=png(1),
        headers={"Content-Type": "image/png", "Origin": "https://example.com"},
    )
    assert response.status_code == 403


def test_cover_uploads_still_admit_only_photographs(client):
    response = client.post(
        "/api/projects/garden/cover/assets",
        params={"name": "x.svg"},
        content=SVG,
        headers={"Content-Type": "image/svg+xml"},
    )
    assert response.status_code == 403


def test_upload_names_are_titles_never_paths(client, library):
    revision = listing(client)["revision"]
    response = upload(client, png(1), "../../../escape.png", revision)
    assert response.status_code == 200
    path = response.json()["imported"][0]["path"]
    assert path.startswith("coloring-assets/escape-")
    assert not (library.parent / "escape.png").exists()


def test_removal_needs_its_pages_and_keeps_the_file(client, library):
    revision = listing(client)["revision"]
    imported = upload(client, png(1), "a.png", revision).json()
    revision = imported["revision"]
    body = {"artwork": "a", "revision": revision}
    refused = client.post("/api/projects/colors/coloring/remove", json=body)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "artwork_in_use"
    removed = client.post(
        "/api/projects/colors/coloring/remove", json={**body, "with_pages": True}
    ).json()
    assert removed["removed"]["pages_removed"] == [1] and removed["report"]["artwork"] == []
    assert removed["report"]["unreferenced_files"] == [imported["imported"][0]["path"]]
    assert (library / "colors" / imported["imported"][0]["path"]).is_file()
    unknown = client.post(
        "/api/projects/colors/coloring/remove",
        json={"artwork": "nope", "revision": removed["revision"]},
    )
    assert unknown.status_code == 404


def test_word_search_books_have_no_artwork(client):
    response = client.get("/api/projects/garden/coloring")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "not_a_coloring_book"
    detail = client.get("/api/projects/garden").json()
    response = client.post(
        "/api/projects/garden/coloring/artwork",
        params={"name": "a.png", "revision": detail["revision"]},
        content=png(1),
        headers={"Content-Type": "image/png"},
    )
    assert response.json()["error"]["code"] == "not_a_coloring_book"


def test_artwork_shell_route_serves_the_app(client):
    assert client.get("/books/colors/artwork").status_code == 200
