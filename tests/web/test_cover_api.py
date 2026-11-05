"""Cover API: draft previews, photo import, saves, builds, staleness and safe rasters."""

import hashlib
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from puzzlepress.studio import server
from puzzlepress.studio.server import create_app
from tests.cover_helpers import cover_project, photo_bytes


def _output(data):
    data["output"] = {"directory": "../../build/book"}


@pytest.fixture
def studio(tmp_path):
    books = tmp_path / "books"
    source, _ = cover_project(books, mutate=_output, build_interior=False)
    client = TestClient(create_app(books, tmp_path / "frontend"))
    return client, source, tmp_path / "build" / "book"


def detail(client):
    return client.get("/api/projects/book").json()


def build_interior(client, profile=None):
    body = {"revision": detail(client)["revision"]}
    if profile:
        body["profile"] = profile
    return client.post("/api/projects/book/interior/build", json=body)


def draft(client, source):
    return client.post("/api/projects/book/draft/cover", json={"source": source})


def upload(client, data, name="Dawn.jpg", kind="image/jpeg", **headers):
    return client.post(
        "/api/projects/book/cover/assets",
        params={"name": name},
        content=data,
        headers={"content-type": kind, **headers},
    )


def test_cover_needs_a_built_interior(studio):
    client, _, output = studio
    status = client.get("/api/projects/book/cover").json()
    assert status["state"] == "missing"
    assert "interior_current" in {
        r["code"] for r in status["report"]["rules"] if r["outcome"] == "failed"
    }
    preview = draft(client, detail(client)["source"]).json()
    assert preview["success"] is False and preview["stage"] == "interior"
    assert preview["diagnostics"][0]["code"] == "interior_missing"
    assert not output.exists()


def test_draft_preview_is_a_real_pdf_raster_and_writes_nothing(studio):
    client, source, output = studio
    assert build_interior(client).status_code == 200
    before = (source / "book.yaml").read_bytes(), sorted(p.name for p in output.iterdir())
    project = detail(client)["source"]
    data = draft(client, project).json()
    assert data["success"] and data["interior"]["page_count"] == 11
    assert data["interior"]["stale"] is None
    layout = data["layout"]
    assert layout["geometry"]["spine_width_in"] == pytest.approx(0.024772)
    assert layout["spine_text"]["reason"] == "page_count"
    assert {c["code"] for c in data["checks"]} >= {"kdp_minimum_page_count", "spine_text_omitted"}
    digest = data["preview"]["pdf_sha256"]
    image = client.get(
        "/api/projects/book/cover/preview", params={"pdf": digest, "size": "preview"}
    )
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    width = layout["geometry"]["regions"]["media"]["width"]
    assert Image.open(io.BytesIO(image.content)).size == (round(width), 810)
    project["cover"]["crop"] = {"x": 0.9, "y": 0.5, "zoom": 1.4}
    moved = draft(client, project).json()
    assert moved["preview"]["pdf_sha256"] != digest
    assert moved["layout"]["photo"]["window"]["left"] > layout["photo"]["window"]["left"]
    assert moved["layout"]["resolution"]["status"] == "image_low_effective_dpi"
    assert ((source / "book.yaml").read_bytes(), sorted(p.name for p in output.iterdir())) == before


def test_invalid_draft_crop_is_a_field_error(studio):
    client, _, _ = studio
    build_interior(client)
    project = detail(client)["source"]
    project["cover"]["crop"] = {"x": 1.5}
    response = draft(client, project)
    assert response.status_code == 422
    assert [(i["path"], i["code"]) for i in response.json()["error"]["issues"]] == [
        ("cover.crop.x", "crop_out_of_bounds")
    ]


def test_draft_against_a_stale_interior_previews_and_says_so(studio):
    client, _, _ = studio
    build_interior(client)
    project = detail(client)["source"]
    project["word_search"]["puzzles"][0]["title"] = "Renamed"
    data = draft(client, project).json()
    assert data["success"] and "predates the current source" in data["interior"]["stale"]


def test_photo_import_is_safe_and_content_addressed(studio, monkeypatch):
    client, source, _ = studio
    photo = photo_bytes(900, 600, private=True)
    response = upload(client, photo, name="../../escape.jpg")
    assert response.status_code == 200, response.text
    asset = response.json()["asset"]
    assert asset["path"] == f"cover-assets/escape-{hashlib.sha256(photo).hexdigest()[:12]}.jpg"
    assert (source / asset["path"]).read_bytes() == photo
    assert asset["path"] in [
        a["path"] for a in client.get("/api/projects/book/cover/assets").json()["assets"]
    ]
    assert upload(client, photo).json()["asset"]["reused"] is True
    bad = upload(client, b"not an image")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "image_unsupported"
    assert upload(client, photo, kind="text/plain").status_code == 403
    assert upload(client, photo, origin="https://example.com").status_code == 403
    monkeypatch.setattr(server, "MAX_ASSET_BYTES", 100)
    assert upload(client, photo).status_code == 413
    assert client.post(
        "/api/projects/..%2Fbook/cover/assets", content=photo, headers={"content-type": "image/png"}
    ).status_code in (403, 404)
    # JSON elsewhere still requires JSON; image types are accepted only for uploads.
    other = client.post(
        "/api/projects/book/draft/cover", content=photo, headers={"content-type": "image/jpeg"}
    )
    assert other.status_code == 403


def test_save_reload_build_and_stale_cover(studio):
    client, source, output = studio
    build_interior(client)
    imported = upload(client, photo_bytes(5400, 3600, orientation=3), "Other.jpg").json()["asset"]
    saved = detail(client)
    project = saved["source"]
    project["cover"]["image"] = {"path": imported["path"], "sha256": imported["sha256"]}
    project["cover"]["crop"] = {"x": 0.4, "y": 0.6, "zoom": 1.0}
    response = client.post(
        "/api/projects/book/draft/save", json={"source": project, "revision": saved["revision"]}
    )
    assert response.status_code == 200, response.text
    reloaded = detail(client)
    assert reloaded["source"]["cover"] == project["cover"] | {
        "crop": {"x": 0.4, "y": 0.6, "zoom": 1.0}
    }
    stale = client.post("/api/projects/book/cover/build", json={"revision": saved["revision"]})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_changed"
    built = client.post("/api/projects/book/cover/build", json={"revision": reloaded["revision"]})
    data = built.json()
    assert data["build"] == {"success": True} and data["state"] == "current"
    assert data["report"]["structural"]["status"] == "valid"
    assert data["report"]["kdp"]["status"] == "not_ready"
    assert {"cover.pdf", "cover.json", "cover-preflight.json"} <= {p.name for p in output.iterdir()}
    digest = data["preview"]["pdf_sha256"]
    assert digest == hashlib.sha256((output / "cover.pdf").read_bytes()).hexdigest()
    raster = client.get(
        "/api/projects/book/cover/preview", params={"pdf": digest, "size": "detail"}
    )
    assert raster.status_code == 200
    # Changing the crop after building makes the built cover stale.
    project = reloaded["source"]
    project["cover"]["crop"]["x"] = 0.1
    client.post(
        "/api/projects/book/draft/save", json={"source": project, "revision": reloaded["revision"]}
    )
    status = client.get("/api/projects/book/cover").json()
    assert status["state"] == "stale"
    assert any("crop changed" in f["message"] for f in status["report"]["findings"])


def test_preview_requests_are_bounded(studio):
    client, _, _ = studio
    get = client.get
    assert (
        get(
            "/api/projects/book/cover/preview", params={"pdf": "0" * 64, "size": "preview"}
        ).status_code
        == 409
    )
    assert (
        get(
            "/api/projects/book/cover/preview", params={"pdf": "0" * 64, "size": "huge"}
        ).status_code
        == 404
    )
    assert (
        get(
            "/api/projects/book/cover/preview", params={"pdf": "../x", "size": "preview"}
        ).status_code
        == 422
    )


def test_interior_profile_choice_is_kept_between_builds(studio):
    client, _, output = studio
    data = build_interior(client, "paperback-8.5x11-cream").json()
    assert data["profile"] == "paperback-8.5x11-cream"
    assert [p["paper"] for p in data["profiles"]] == ["white", "cream"] * 4
    assert build_interior(client).json()["profile"] == "paperback-8.5x11-cream"
    assert draft(client, detail(client)["source"]).json()["interior"]["paper"] == "cream"
    bad = build_interior(client, "paperback-7x10")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "unsupported_profile"


def test_cover_route_serves_the_shell(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>shell</html>")
    client = TestClient(create_app(tmp_path / "books", frontend))
    assert client.get("/books/demo/cover").text == "<html>shell</html>"


def test_draft_preview_is_byte_identical_to_the_built_cover(studio):
    client, _, output = studio
    build_interior(client)
    saved = detail(client)
    preview = draft(client, saved["source"]).json()["preview"]["pdf_sha256"]
    built = client.post("/api/projects/book/cover/build", json={"revision": saved["revision"]})
    assert built.json()["preview"]["pdf_sha256"] == preview
    assert hashlib.sha256((output / "cover.pdf").read_bytes()).hexdigest() == preview
