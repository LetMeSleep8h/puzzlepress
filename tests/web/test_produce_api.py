"""Studio production: start, follow, verify, cancel (coloring only), download."""

import hashlib
import io
import shutil
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from puzzlepress.production import coloring as coloring_production
from puzzlepress.studio.server import create_app
from tests.coloring_helpers import composed_coloring_book
from tests.helpers import DEMO

MEDIUM = (1088, 1463)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    books = tmp_path / "books"
    composed_coloring_book(books / "colors", 2, size=MEDIUM)
    words = books / "words"
    words.mkdir()
    shutil.copyfile(DEMO / "book.yaml", words / "book.yaml")
    return books


@pytest.fixture
def client(library: Path, tmp_path: Path) -> TestClient:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return TestClient(create_app(library, frontend))


def release_folder(book: Path) -> Path:
    from puzzlepress.project import load_project
    from puzzlepress.studio.producing import release_directory

    return release_directory(load_project(book).project, book)


def revision(client: TestClient, key: str) -> str:
    return client.get(f"/api/projects/{key}").json()["revision"]


def finish(client: TestClient, key: str, limit: float = 180) -> dict:
    deadline = time.monotonic() + limit
    while True:
        status = client.get(f"/api/projects/{key}/produce").json()
        if status["run"] and status["run"]["state"] != "running":
            return status
        assert time.monotonic() < deadline, status
        time.sleep(0.2)


def test_a_coloring_run_is_reported_only_after_its_files_verify(
    client: TestClient, library: Path
) -> None:
    first = client.get("/api/projects/colors/produce").json()
    assert first["run"] is None and first["release"] is None and first["cancellable"]
    stale = client.post("/api/projects/colors/produce", json={"revision": "sha256-old"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_changed"
    started = client.post(
        "/api/projects/colors/produce", json={"revision": revision(client, "colors")}
    )
    assert started.status_code == 200 and started.json()["run"]["state"] == "running"
    status = finish(client, "colors")
    run, release = status["run"], status["release"]
    assert run["state"] in {"complete", "blocked"}, run
    assert run["steps"][:2] == ["interior", "interior_preflight"] and run["steps"][-1] == "swap"
    assert release["verified"] and not release["stale"] and release["engine"] == "coloring"
    assert release["validation"]["blocking"] is not None
    names = {f["name"] for f in release["files"]}
    assert {"interior.pdf", "preflight.json", "artwork-integrity.json"} <= names
    pdf = client.get("/api/projects/colors/produce/file", params={"name": "interior.pdf"})
    expected = next(f for f in release["files"] if f["name"] == "interior.pdf")
    assert hashlib.sha256(pdf.content).hexdigest() == expected["sha256"]
    assert pdf.headers["content-disposition"].startswith("attachment")
    assert (
        client.get("/api/projects/colors/produce/file", params={"name": "../book.yaml"}).status_code
        == 404
    )

    # A changed file is never served or called verified.
    directory = release_folder(library / "colors")
    assert directory.is_dir()
    (directory / "preflight.json").write_bytes(b"{}")
    damaged = client.get("/api/projects/colors/produce").json()["release"]
    assert damaged["verified"] is False and "preflight.json" in damaged["problem"]
    assert (
        client.get("/api/projects/colors/produce/file", params={"name": "interior.pdf"}).status_code
        == 404
    )


def test_the_release_goes_stale_when_the_source_changes(client: TestClient) -> None:
    client.post("/api/projects/colors/produce", json={"revision": revision(client, "colors")})
    finish(client, "colors")
    detail = client.get("/api/projects/colors").json()
    source = detail["source"]
    source["coloring"]["layout"]["border"] = "thin"
    saved = client.post(
        "/api/projects/colors/draft/save", json={"source": source, "revision": detail["revision"]}
    )
    assert saved.status_code == 200, saved.text
    assert client.get("/api/projects/colors/produce").json()["release"]["stale"] is True


def test_a_cancelled_coloring_run_keeps_the_previous_release(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/api/projects/colors/produce", json={"revision": revision(client, "colors")})
    before = finish(client, "colors")["release"]["files"]
    real = coloring_production._duplicates

    def slow(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        time.sleep(1.5)
        return real(*args, **kwargs)

    monkeypatch.setattr(coloring_production, "_duplicates", slow)
    client.post("/api/projects/colors/produce", json={"revision": revision(client, "colors")})
    deadline = time.monotonic() + 120
    while client.get("/api/projects/colors/produce").json()["run"]["step"] != "duplicates":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    again = client.post(
        "/api/projects/colors/produce", json={"revision": revision(client, "colors")}
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "production_in_progress"
    assert client.post("/api/projects/colors/produce/cancel", json={}).json()["run"][
        "cancel_requested"
    ]
    status = finish(client, "colors")
    assert status["run"]["state"] == "cancelled" and "swap" not in status["run"]["steps"]
    assert status["release"]["verified"] and status["release"]["files"] == before
    leftovers = [
        p.name
        for p in release_folder(library / "colors").parent.iterdir()
        if p.name.startswith(".")
    ]
    assert leftovers == []


def test_word_search_runs_are_not_cancelled_and_produce_the_cli_files(client: TestClient) -> None:
    client.post("/api/projects/words/produce", json={"revision": revision(client, "words")})
    refused = client.post("/api/projects/words/produce/cancel", json={})
    if client.get("/api/projects/words/produce").json()["run"]["state"] == "running":
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_cancellable"
    status = finish(client, "words")
    assert status["cancellable"] is False
    assert status["run"]["state"] in {"complete", "blocked"}, status["run"]
    assert status["release"]["verified"]
    names = {f["name"] for f in status["release"]["files"]}
    assert {"interior.pdf", "preflight.json", "publishing-validation.json"} <= names
    manifest = client.get("/api/projects/words/produce/file", params={"name": "production.json"})
    assert manifest.status_code == 200 and b"puzzlepress-production-run" in manifest.content
    assert client.get("/api/projects/words/produce/package.zip").status_code == 404


def test_the_package_zip_holds_the_verified_package(client: TestClient, tmp_path: Path) -> None:
    from tests.coloring_production import write_book

    books = tmp_path / "ready"
    write_book(books)  # SYNTHETIC decisions, in books/book.
    ready = TestClient(create_app(books, tmp_path / "frontend"))
    rev = ready.get("/api/projects/book").json()["revision"]
    ready.post("/api/projects/book/produce", json={"revision": rev})
    status = finish(ready, "book", 300)
    assert status["run"]["state"] == "complete", status["run"]
    assert status["release"]["package"]
    data = ready.get("/api/projects/book/produce/package.zip").content
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert "publishing/interior.pdf" in names and "publishing/package.json" in names
        listed = {f["name"]: f["sha256"] for f in status["release"]["files"]}
        for name in names:
            assert hashlib.sha256(archive.read(name)).hexdigest() == listed[name]
