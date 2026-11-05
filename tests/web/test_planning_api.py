"""Planning API: status, draft checks, revision-aware saves, approval and isolation."""

import hashlib
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from puzzlepress.studio.server import create_app
from tests.helpers import ROOT
from tests.planning_helpers import complete_plan, variant
from tests.production_book import write_production_book

BASE = "/api/projects/production"


@pytest.fixture
def studio(tmp_path: Path) -> tuple[TestClient, Path]:
    books = tmp_path / "books"
    write_production_book(books / "production")  # SYNTHETIC 60-puzzle book with a plan.
    shutil.copytree(ROOT / "books" / "garden-demo", books / "garden-demo")
    return TestClient(create_app(books, tmp_path / "frontend")), books


def digest(path: Path) -> str:
    return "sha256-" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_status_of_the_demo_and_of_a_project_without_a_plan(
    studio: tuple[TestClient, Path],
) -> None:
    client, books = studio
    data = client.get(f"{BASE}/planning").json()
    assert data["revision"] == digest(books / "production" / "planning.yaml")
    assert data["book"] == {"id": "synthetic-production-book", "title": "Synthetic Production Book"}
    assert data["source"]["structure"]["target_puzzles"] == 60
    assert data["report"]["state"] == "needs_research"
    empty = client.get("/api/projects/garden-demo/planning").json()
    assert empty == {
        "key": "garden-demo",
        "book": {"id": "garden-demo", "title": empty["book"]["title"]},
        "revision": None,
        "source": None,
        "report": None,
        "options": data["options"],
    }
    assert [p["id"] for p in data["options"]["print_profiles"]] == sorted(
        f"paperback-{trim}{paper}"
        for trim in ("8.5x11", "6x9", "8x10", "8.5x8.5")
        for paper in ("", "-cream")
    )
    assert data["options"]["puzzle_types"] == ["word_search"]
    assert data["options"]["directions"][0] == "right" and len(data["options"]["directions"]) == 8
    assert client.get("/api/projects/missing/planning").status_code == 404


def test_draft_checks_are_python_authoritative_and_write_nothing(
    studio: tuple[TestClient, Path],
) -> None:
    client, books = studio
    before = {p.name: p.read_bytes() for p in (books / "production").iterdir()}
    response = client.post(f"{BASE}/draft/planning", json={"source": complete_plan()})
    assert response.status_code == 200
    assert response.json()["report"]["state"] == "ready_for_approval"
    bad = variant(structure__target_puzzles="sixty")
    response = client.post(f"{BASE}/draft/planning", json={"source": bad})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_planning"
    assert error["issues"][0]["path"] == "structure.target_puzzles"
    assert {p.name: p.read_bytes() for p in (books / "production").iterdir()} == before


def test_save_is_revision_aware_and_leaves_book_yaml_alone(
    studio: tuple[TestClient, Path],
) -> None:
    client, books = studio
    book = books / "production" / "book.yaml"
    book_before = book.read_bytes()
    detail_before = client.get(BASE).json()
    status = client.get(f"{BASE}/planning").json()
    plan = complete_plan()
    stale = client.post(
        f"{BASE}/planning/save", json={"source": plan, "revision": "sha256-" + "0" * 64}
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_changed"
    saved = client.post(
        f"{BASE}/planning/save", json={"source": plan, "revision": status["revision"]}
    )
    assert saved.status_code == 200
    data = saved.json()
    assert data["revision"] != status["revision"]
    assert data["report"]["state"] == "ready_for_approval"
    assert book.read_bytes() == book_before
    assert client.get(BASE).json()["revision"] == detail_before["revision"]  # Book draft intact.
    again = client.post(
        f"{BASE}/planning/save", json={"source": plan, "revision": status["revision"]}
    )
    assert again.status_code == 409  # The older revision is stale now.
    invalid = client.post(
        f"{BASE}/planning/save",
        json={"source": {"planning_version": 2}, "revision": data["revision"]},
    )
    assert invalid.status_code == 422
    assert client.get(f"{BASE}/planning").json()["revision"] == data["revision"]


def test_creating_a_plan_requires_that_none_exists(studio: tuple[TestClient, Path]) -> None:
    client, books = studio
    url = "/api/projects/garden-demo/planning/save"
    created = client.post(url, json={"source": {"planning_version": 1}, "revision": None})
    assert created.status_code == 200 and created.json()["report"]["state"] == "draft"
    assert (books / "garden-demo" / "planning.yaml").is_file()
    again = client.post(url, json={"source": {"planning_version": 1}, "revision": None})
    assert again.status_code == 409


def test_approval_is_explicit_identity_bound_and_goes_stale(
    studio: tuple[TestClient, Path],
) -> None:
    client, _ = studio
    status = client.get(f"{BASE}/planning").json()
    demo_identity = status["report"]["planning_identity"]
    refused = client.post(
        f"{BASE}/planning/approval",
        json={"revision": status["revision"], "identity": demo_identity},
    )
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_ready"
    saved = client.post(
        f"{BASE}/planning/save", json={"source": complete_plan(), "revision": status["revision"]}
    ).json()
    identity = saved["report"]["planning_identity"]
    for revision, ident, code in (
        ("sha256-" + "1" * 64, identity, "source_changed"),
        (saved["revision"], demo_identity, "identity_mismatch"),
    ):
        response = client.post(
            f"{BASE}/planning/approval", json={"revision": revision, "identity": ident}
        )
        assert response.status_code == 409 and response.json()["error"]["code"] == code
    approved = client.post(
        f"{BASE}/planning/approval", json={"revision": saved["revision"], "identity": identity}
    ).json()
    assert approved["source"]["approval"] == identity
    assert approved["report"]["state"] == "approved"
    edited = dict(approved["source"])
    edited["concept"] = {**edited["concept"], "summary": "Edited after approval."}
    stale = client.post(
        f"{BASE}/planning/save", json={"source": edited, "revision": approved["revision"]}
    ).json()
    assert stale["report"]["approval"]["status"] == "stale"
    assert stale["report"]["state"] == "ready_for_approval"
    withdrawn = client.post(
        f"{BASE}/planning/approval", json={"revision": stale["revision"], "identity": None}
    ).json()
    assert withdrawn["source"]["approval"] is None


def test_invalid_planning_file_and_invalid_book_are_reported(
    studio: tuple[TestClient, Path],
) -> None:
    client, books = studio
    (books / "production" / "planning.yaml").write_text("planning_version: 7\n", encoding="utf-8")
    response = client.get(f"{BASE}/planning")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_planning"
    (books / "production" / "book.yaml").write_text("schema_version: 9\n", encoding="utf-8")
    response = client.get(f"{BASE}/planning")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_project"


def test_planning_posts_are_json_and_same_origin_only(studio: tuple[TestClient, Path]) -> None:
    client, _ = studio
    response = client.post(
        f"{BASE}/draft/planning", content=b"{}", headers={"content-type": "text/plain"}
    )
    assert response.status_code == 403
    response = client.post(
        f"{BASE}/planning/save",
        json={"source": {}, "revision": None},
        headers={"origin": "https://example.com"},
    )
    assert response.status_code == 403
    response = client.post(f"{BASE}/planning/save", json={"source": {}})
    assert response.status_code == 422  # revision is required, even when null.


def test_planning_page_is_served_by_the_shell(studio: tuple[TestClient, Path]) -> None:
    client, _ = studio
    response = client.get("/books/production/planning")
    assert response.status_code == 503  # No built frontend in this test: the shell route exists.
    assert response.json()["error"]["code"] == "frontend_missing"
