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


# ---------------------------------------------------------------- line-art preparation


def _imported(client) -> dict:
    revision = listing(client)["revision"]
    return upload(client, png(1), "a.png", revision).json()


def test_prepare_previews_with_findings_and_images(client, library):
    _imported(client)
    original = (library / "colors" / "coloring-assets").iterdir().__next__().read_bytes()
    response = client.post(
        "/api/projects/colors/coloring/prepare",
        json={"artwork": "a", "adjustments": {"line_weight": -2}},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["artwork"] == "a" and data["key"].startswith("pp1-prepared-sha256-")
    assert data["adjustments"]["line_weight"] == -2
    assert data["saved_adjustments"]["line_weight"] == 0
    assert "detail_lost" in [f["code"] for f in data["findings"]]
    for kind, url in data["images"].items():
        image = client.get(url)
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG"), kind
    folder = library / "colors" / "coloring-assets"
    assert [p.read_bytes() for p in folder.iterdir()] == [original]
    assert (library / "colors" / "book.yaml").read_text(encoding="utf-8").count(
        "line_weight: 0"
    ) == 1


def test_preview_images_belong_to_their_project(client, library):
    _imported(client)
    data = client.post("/api/projects/colors/coloring/prepare", json={"artwork": "a"}).json()
    prepared = data["key"]
    other = client.get(f"/api/projects/garden/coloring/prepared/{prepared}/prepared")
    assert other.status_code == 404 and other.json()["error"]["code"] == "preview_expired"
    assert client.get(f"/api/projects/colors/coloring/prepared/{prepared}/nope").status_code == 404


def test_invalid_adjustments_are_explained(client):
    _imported(client)
    response = client.post(
        "/api/projects/colors/coloring/prepare",
        json={"artwork": "a", "adjustments": {"contrast": 9, "sharpen": 1}},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_adjustments"
    assert {issue["code"] for issue in error["issues"]} == {"range", "unknown_field"}
    unknown = client.post("/api/projects/colors/coloring/prepare", json={"artwork": "zz"})
    assert unknown.status_code == 404


def test_adjustments_save_reset_and_refuse_stale_revisions(client, library):
    revision = _imported(client)["revision"]
    saved = client.post(
        "/api/projects/colors/coloring/adjustments",
        json={"artwork": "a", "revision": revision, "adjustments": {"threshold": 0.5}},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["adjustments"]["threshold"] == 0.5 and body["revision"] != revision
    assert body["report"]["artwork"][0]["adjustments"]["threshold"] == 0.5
    stale = client.post(
        "/api/projects/colors/coloring/adjustments",
        json={"artwork": "a", "revision": revision, "adjustments": {"threshold": 0.6}},
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_changed"
    preview = client.post("/api/projects/colors/coloring/prepare", json={"artwork": "a"}).json()
    assert preview["adjustments"]["threshold"] == 0.5  # Saved settings preview by default.
    reset = client.post(
        "/api/projects/colors/coloring/adjustments",
        json={"artwork": "a", "revision": body["revision"], "adjustments": None},
    ).json()
    assert reset["adjustments"]["threshold"] is None
    assert "threshold: null" in (library / "colors" / "book.yaml").read_text(encoding="utf-8")


def test_concurrent_saves_with_one_revision_let_exactly_one_win(client):
    from concurrent.futures import ThreadPoolExecutor

    revision = _imported(client)["revision"]

    def save(weight: int) -> int:
        return client.post(
            "/api/projects/colors/coloring/adjustments",
            json={"artwork": "a", "revision": revision, "adjustments": {"line_weight": weight}},
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = sorted(pool.map(save, [1, 2, -1, -2]))
    assert statuses == [200, 409, 409, 409]
    weight = listing(client)["report"]["artwork"][0]["adjustments"]["line_weight"]
    assert weight in (1, 2, -1, -2)
