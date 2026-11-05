"""Studio print proofs for coloring books: build, preflight, previews, export, staleness.

Every drawing is SYNTHETIC (tests/coloring_helpers.py).
"""

import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import ImageDraw

from puzzlepress.studio.server import create_app
from tests.coloring_helpers import composed_coloring_book, line_art

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "studio" / "src" / "fixtures"
MEDIUM = (1088, 1463)


def drawings():  # Two near-identical drawings: a manual-review prompt.
    first = line_art(5, MEDIUM)
    second = first.copy()
    ImageDraw.Draw(second).line((10, 10, 40, 10), fill=0, width=2)
    return [first, second]


@pytest.fixture
def library(tmp_path) -> Path:
    books = tmp_path / "books"
    composed_coloring_book(books / "coloring-print", 2, images=drawings(), border="thin")
    return books


@pytest.fixture
def client(library, tmp_path) -> TestClient:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    return TestClient(create_app(library, frontend))


def build(client: TestClient) -> dict:
    revision = client.get("/api/projects/coloring-print").json()["revision"]
    response = client.post(
        "/api/projects/coloring-print/interior/build", json={"revision": revision}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_build_preflight_and_page_meanings(client):
    assert client.get("/api/projects/coloring-print/interior").json()["state"] == "missing"
    status = build(client)
    assert status["build"] == {"success": True}
    report = status["report"]
    assert report["ruleset"]["id"] == "puzzlepress-kdp-coloring"
    assert status["ruleset"] == 3  # 3: paper-relative line measures (Interval 8)
    assert report["structural"]["status"] == "valid"
    pages = status["preview"]["pages"]
    assert [(p["physical_page"], p["side"], p["kind"], p["folio"]) for p in pages] == [
        (1, "recto", "title_page", None),
        (2, "verso", "copyright_page", None),
        (3, "recto", "coloring", "3"),
        (4, "verso", "blank", None),
        (5, "recto", "coloring", "5"),
        (6, "verso", "blank", None),
    ]
    assert [p["description"] for p in pages[2:4]] == [
        "Coloring page 1: drawing 1 [drawing-1]",
        "Blank: back of the coloring page",
    ]
    roles = [e["role"] for e in status["preview"]["geometry"][2]["elements"]]
    assert roles == ["coloring_border_1", "coloring_art", "folio"]
    rules = {f["rule"] for f in report["findings"]}
    assert {"kdp_image_resolution", "kdp_minimum_page_count", "coloring_similar_artwork"} <= rules
    similar = next(f for f in report["findings"] if f["rule"] == "coloring_similar_artwork")
    assert similar["severity"] == "info"


def test_pdf_export_is_the_inspected_file(client, library):
    status = build(client)
    digest = status["preview"]["pdf_sha256"]
    response = client.get("/api/projects/coloring-print/interior/pdf", params={"pdf": digest})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="interior.pdf"'
    assert hashlib.sha256(response.content).hexdigest() == digest
    assert response.headers["cache-control"] == "no-store"
    stale = client.get("/api/projects/coloring-print/interior/pdf", params={"pdf": "0" * 64})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "preview_stale"
    bad = client.get("/api/projects/coloring-print/interior/pdf", params={"pdf": "../x"})
    assert bad.status_code == 422


def test_page_rasters_show_blank_reverse_pages(client):
    pytest.importorskip("pypdfium2")
    status = build(client)
    digest = status["preview"]["pdf_sha256"]
    for page in (3, 4):
        response = client.get(
            f"/api/projects/coloring-print/interior/pages/{page}",
            params={"size": "thumb", "pdf": digest},
        )
        assert response.status_code == 200 and response.headers["content-type"] == "image/png"


def test_saving_preparation_settings_marks_the_interior_stale(client):
    build(client)
    revision = client.get("/api/projects/coloring-print").json()["revision"]
    saved = client.post(
        "/api/projects/coloring-print/coloring/adjustments",
        json={"artwork": "drawing-1", "revision": revision, "adjustments": {"line_weight": 1}},
    )
    assert saved.status_code == 200, saved.text
    status = client.get("/api/projects/coloring-print/interior").json()
    assert status["state"] == "stale"
    stale = {f["rule"] for f in status["report"]["findings"]}
    assert {"source_current", "plan_current"} <= stale


def test_frontend_fixtures_match_the_engine_output(client):
    """The Studio fixtures are this API's output (binary digests aside)."""
    before = client.get("/api/projects/coloring-print/interior").json()
    status = build(client)
    project = client.get("/api/projects/coloring-print").json()
    stored = json.loads((FIXTURES / "coloring-interior.json").read_text(encoding="utf-8"))
    missing = json.loads((FIXTURES / "coloring-interior-missing.json").read_text(encoding="utf-8"))
    detail = json.loads((FIXTURES / "coloring-print-project.json").read_text(encoding="utf-8"))
    assert missing == {**before, "revision": missing["revision"]}

    def meaning(data: dict) -> object:
        return (
            [
                (p["kind"], p["side"], p["folio"], p.get("description"))
                for p in data["preview"]["pages"]
            ],
            sorted(
                (f["rule"], f["severity"], f["physical_page"]) for f in data["report"]["findings"]
            ),
            [r["code"] for r in data["report"]["rules"]],
            data["state"],
        )

    assert meaning(stored) == meaning(status)

    def without_digests(source: dict) -> dict:
        # The synthetic drawings are PNG-encoded on the machine running the test, and
        # Pillow's bundled deflate differs between platforms, so their content-addressed
        # names and digests do too (main's Linux CI, run 41849615371). Everything else
        # in the source must match.
        source = json.loads(json.dumps(source))
        for artwork in source["coloring"]["artwork"]:
            assert re.fullmatch(r"coloring-assets/drawing-\d-[0-9a-f]{12}\.png", artwork["path"])
            assert artwork["path"][-16:-4] == artwork["sha256"][:12]
            artwork["path"] = artwork["sha256"] = "<digest>"
        return source

    assert without_digests(detail["source"]) == without_digests(project["source"])
    assert detail["engine"] == project["engine"]


# ------------------------------------------------------------------ Pages composer (Interval 5)


def test_composer_plans_drafts_with_python_geometry(client):
    project = client.get("/api/projects/coloring-print").json()
    source = project["source"]
    response = client.post("/api/projects/coloring-print/draft/plan", json={"source": source})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["verification"]["valid"] and data["plan"]["complete"]
    geometry = data["geometry"]
    assert geometry["border"] == "thin" and geometry["trim"] == {"width": 612.0, "height": 792}
    recto, verso = geometry["sides"]["recto"], geometry["sides"]["verso"]
    # Mirrored margins: the gutter is on the inside of each page.
    assert recto["live"]["x"] > verso["live"]["x"]
    assert recto["art"]["width"] < recto["live"]["width"]  # inside the border
    # A reordered draft is planned as written; nothing is saved.
    reordered = json.loads(json.dumps(source))
    reordered["coloring"]["pages"].reverse()
    data = client.post("/api/projects/coloring-print/draft/plan", json={"source": reordered}).json()
    ids = [p["artwork"]["id"] for p in data["plan"]["pages"] if p["kind"] == "coloring"]
    assert ids == [p["artwork"] for p in reordered["coloring"]["pages"] if "artwork" in p]
    assert client.get("/api/projects/coloring-print").json()["revision"] == project["revision"]


def test_composer_gets_an_incomplete_plan_with_its_reasons(client):
    source = client.get("/api/projects/coloring-print").json()["source"]
    source["coloring"]["pages"] = []
    response = client.post("/api/projects/coloring-print/draft/plan", json={"source": source})
    assert response.status_code == 200, response.text
    data = response.json()
    assert not data["verification"]["valid"] or not data["plan"]["complete"]
    codes = {i["code"] for i in data["verification"]["issues"] + data["plan"]["diagnostics"]}
    assert "no_coloring_pages" in codes


def test_pages_route_serves_the_shell(client):
    assert client.get("/books/coloring-print/pages").status_code == 200
