"""HTTP and adapter tests, separate from the core/CLI regression suite."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from puzzlepress import build_identity, dump_project, validate_project
from puzzlepress.batch import generate_batch
from puzzlepress.studio.server import create_app
from puzzlepress.studio.service import ProjectStore, StudioError, StudioService

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def library(tmp_path, garden):
    books = tmp_path / "books"
    folder = books / "garden-demo"
    folder.mkdir(parents=True)
    (folder / "book.yaml").write_text(dump_project(garden), encoding="utf-8")
    return books


@pytest.fixture
def client(library, tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>Studio</title>", encoding="utf-8")
    (frontend / "assets").mkdir()
    (frontend / "assets" / "app.js").write_text("export {};", encoding="utf-8")
    return TestClient(create_app(library, frontend))


def generate(client, key="garden-demo"):
    detail = client.get(f"/api/projects/{key}").json()
    return client.post(f"/api/projects/{key}/generation", json={"identity": detail["identity"]})


def test_discovery_and_detail(client, garden, library):
    (library / "unrelated").mkdir()
    data = client.get("/api/projects").json()["projects"]
    assert [p["key"] for p in data] == ["garden-demo"]
    detail = client.get("/api/projects/garden-demo").json()
    assert data == [detail]
    assert detail["identity"] == build_identity(garden)
    assert detail["source"]["build"]["seed"] == "2026"
    assert detail["source"]["word_search"] == garden.word_search.to_dict()
    assert detail["validation"] == {"valid": True, "issues": []}
    assert detail["engine"] == {"kind": "word_search", "label": "Word search"}


def test_discover_added_project_and_invalid_source(client, library):
    folder = library / "another"
    folder.mkdir()
    source = (library / "garden-demo/book.yaml").read_text()
    (folder / "book.yaml").write_text(source.replace("Garden Word Searches", "Another Book"))
    bad = library / "broken"
    bad.mkdir()
    (bad / "book.yaml").write_text("schema_version: 999")
    entries = client.get("/api/projects").json()["projects"]
    assert [p["key"] for p in entries] == ["another", "broken", "garden-demo"]
    assert not entries[1]["validation"]["valid"]
    response = client.get("/api/projects/broken")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_project"
    assert response.json()["error"]["issues"]


@pytest.mark.parametrize(
    "key", ["..", "../outside", "a/b", "a\\b", "C:books", "%2e%2e", ".", "a\x00"]
)
def test_store_traversal_is_rejected(library, key):
    with pytest.raises(StudioError) as error:
        ProjectStore(library).load(key)
    assert error.value.status == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/projects/missing",
        "/api/projects/%2e%2e%2foutside",
        "/api/projects/%5coutside",
        "/api/nope",
    ],
)
def test_http_path_errors_are_structured(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert "error" in response.json()


@pytest.mark.parametrize("link_file", [True, False])
def test_source_symlink_escape(library, tmp_path, link_file):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "book.yaml").write_text((library / "garden-demo/book.yaml").read_text())
    link = library / "escape"
    try:
        if link_file:
            link.mkdir()
            (link / "book.yaml").symlink_to(outside / "book.yaml")
        else:
            link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires OS permission on this host")
    store = ProjectStore(library)
    with pytest.raises(StudioError):
        store.load("escape")
    assert [p["key"] for p in store.discover()] == ["garden-demo"]


def test_resolved_escape_without_symlink_permission(library, monkeypatch):
    original = Path.resolve

    def resolve(path, *args, **kwargs):
        if path.name == "book.yaml":
            return library.parent / "outside" / "book.yaml"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(StudioError):
        ProjectStore(library).source("garden-demo")


def test_generation_matches_core_and_authoritative_solutions(client, garden):
    first = generate(client)
    assert first.status_code == 200
    assert first.json() == generate(client).json()
    payload = first.json()
    core = generate_batch(garden)
    assert payload["report"] == json.loads(json.dumps(core.to_dict()))
    for result in core.puzzles:
        assert payload["verification"][result.id] == {"valid": True, "issues": []}
        assert isinstance(
            next(p for p in payload["report"]["puzzles"] if p["id"] == result.id)["seed"], str
        )
        for placement in result.puzzle.solution.placements:
            assert payload["solution_cells"][result.id][placement.target_id] == [
                {"x": c.x, "y": c.y} for c in placement.coordinates
            ]


def test_frontend_contract_fixtures_are_real_engine_output(garden):
    fixtures = ROOT / "studio/src/fixtures"
    service = StudioService(ProjectStore(ROOT / "books"))
    fixture = json.loads((fixtures / "project.json").read_text())
    detail = service.store.detail("garden-demo")
    # Byte revisions vary with checkout line endings; semantic transport does not.
    assert fixture.pop("revision").startswith("sha256-")
    assert detail.pop("revision").startswith("sha256-")
    assert fixture == detail
    assert json.loads((fixtures / "generation.json").read_text()) == json.loads(
        json.dumps(service.generate("garden-demo", build_identity(garden)))
    )


def test_full_precision_seed_and_stale_source(client, library):
    source = library / "garden-demo/book.yaml"
    old_identity = client.get("/api/projects/garden-demo").json()["identity"]
    source.write_text(source.read_text().replace("seed: 2026", "seed: 18446744073709551615"))
    detail = client.get("/api/projects/garden-demo").json()
    assert detail["source"]["build"]["seed"] == "18446744073709551615"
    response = client.post("/api/projects/garden-demo/generation", json={"identity": old_identity})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_changed"
    assert generate(client).status_code == 200


def test_quality_findings_and_partial_generation_failure(client, library, garden):
    data = garden.to_dict()
    data["word_search"]["profiles"][0]["max_attempts"] = 1
    data["word_search"]["quality"]["prohibited_words"] = ["MINT"]
    source = library / "garden-demo/book.yaml"
    source.write_text(dump_project(validate_project(data).require_project()))
    response = generate(client)
    assert response.status_code == 200  # Failure belongs to the complete batch report.
    payload = response.json()
    assert not payload["report"]["success"]
    flowers, herbs = payload["report"]["puzzles"]
    assert flowers["puzzle"] is None
    assert flowers["errors"][0]["code"] == "search_exhausted"
    assert flowers["failure_stats"]["attempts"] == 1
    assert payload["verification"]["flowers"] is None
    assert herbs["puzzle"] is not None
    assert herbs["quality"]["prohibited_screening_enabled"]
    assert any(f["code"] == "prohibited_word" for f in payload["report"]["findings"])


def test_busy_generation_releases_lock_on_failure(library, garden, monkeypatch):
    service = StudioService(ProjectStore(library))
    with service._generation_lock, pytest.raises(StudioError) as error:
        service.generate("garden-demo", build_identity(garden))
    assert error.value.code == "generation_busy"
    with pytest.raises(StudioError):
        service.generate("garden-demo", "stale")
    assert service.generate("garden-demo", build_identity(garden))["report"]


def test_unexpected_errors_visible_in_logs_and_hidden_in_http(client, monkeypatch, caplog):
    def broken(self):
        raise RuntimeError("private diagnostic")

    monkeypatch.setattr(ProjectStore, "discover", broken)
    with pytest.raises(RuntimeError, match="private diagnostic"):
        client.get("/api/projects")
    with TestClient(client.app, raise_server_exceptions=False) as safe_client:
        response = safe_client.get("/api/projects")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "server_error"
    assert "private diagnostic" not in response.text
    assert "private diagnostic" in caplog.text


def test_empty_missing_library_and_missing_frontend(tmp_path):
    books = tmp_path / "books"
    books.mkdir()
    with TestClient(create_app(books, tmp_path / "dist")) as client:
        assert client.get("/api/projects").json() == {"projects": []}
        assert client.get("/").json()["error"]["code"] == "frontend_missing"
    with TestClient(create_app(books / "missing", tmp_path / "dist")) as client:
        response = client.get("/api/projects")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "library_unavailable"


def test_legacy_project_no_implicit_puzzles(client, library, source):
    folder = library / "legacy"
    folder.mkdir()
    (folder / "book.yaml").write_text(source)
    response = generate(client, "legacy")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_puzzles"


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/books",
        "/books/garden-demo",
        "/books/garden-demo/puzzles",
        "/books/garden-demo/quality",
        "/books/garden-demo/puzzles/flowers",
        "/books/garden-demo/book",
    ],
)
def test_deep_links_serve_shell(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "<title>Studio</title>" in response.text
    assert "text/html" in response.headers["content-type"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_static_routes_do_not_expose_sources(client):
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/%2e%2e/book.yaml").status_code == 404
    assert client.get("/book.yaml").status_code == 404


def test_generation_request_boundary(client):
    url = "/api/projects/garden-demo/generation"
    assert client.get(url).status_code == 405
    assert client.post(url, json={}).json()["error"]["code"] == "invalid_request"
    assert client.post(url, json={"identity": "x", "seed": 1}).status_code == 422
    assert client.post(url, content="identity=x").status_code == 403
    assert (
        client.post(
            url, json={"identity": "x"}, headers={"Origin": "https://outside.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/projects", headers={"Host": "outside.example"}).status_code == 400


def test_generation_never_writes_source_or_output(client, library):
    before = {
        p.relative_to(library.parent): p.read_bytes()
        for p in library.parent.rglob("*")
        if p.is_file()
    }
    generate(client)
    after = {
        p.relative_to(library.parent): p.read_bytes()
        for p in library.parent.rglob("*")
        if p.is_file()
    }
    assert before == after
