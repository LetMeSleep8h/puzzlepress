"""Studio production jobs: a worker process per job, followed, cancelled, recovered.

Every job runs `python -m puzzlepress.production.worker` (or, where a test needs a
slow, crashing or tampering worker, `tests/worker_harness.py`, the same worker with
injected faults). Books are SYNTHETIC.
"""

import hashlib
import io
import json
import shutil
import sys
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from puzzlepress.production import jobs
from puzzlepress.production.lock import production_lock
from puzzlepress.studio import producing
from puzzlepress.studio.server import create_app
from tests.coloring_helpers import composed_coloring_book
from tests.helpers import DEMO

MEDIUM = (1088, 1463)
HARNESS = Path(__file__).resolve().parents[1] / "worker_harness.py"
ACTIVE = {"queued", "starting", "running", "cancelling"}


@pytest.fixture
def library(tmp_path: Path) -> Path:
    books = tmp_path / "books"
    composed_coloring_book(books / "colors", 2, size=MEDIUM)
    words = books / "words"
    words.mkdir()
    shutil.copyfile(DEMO / "book.yaml", words / "book.yaml")
    return books


def app(library: Path, tmp_path: Path) -> TestClient:
    frontend = tmp_path / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return TestClient(create_app(library, frontend))


@pytest.fixture
def client(library: Path, tmp_path: Path) -> TestClient:
    return app(library, tmp_path)


def harness(monkeypatch: pytest.MonkeyPatch, *options: str) -> None:
    """Run jobs with the fault-injecting worker."""

    def command(job: Path) -> list[str]:
        return [sys.executable, str(HARNESS), *options, str(job)]

    monkeypatch.setattr(producing, "worker_command", command)


def release_folder(book: Path) -> Path:
    from puzzlepress.project import load_project

    return producing.release_directory(load_project(book).project, book)


def revision(client: TestClient, key: str) -> str:
    return client.get(f"/api/projects/{key}").json()["revision"]


def start(client: TestClient, key: str) -> dict:
    response = client.post(f"/api/projects/{key}/produce", json={"revision": revision(client, key)})
    assert response.status_code == 200, response.text
    return response.json()


def wait(client: TestClient, key: str, done: Callable[[dict], bool], limit: float = 240) -> dict:
    deadline = time.monotonic() + limit
    while True:
        status = client.get(f"/api/projects/{key}/produce").json()
        if done(status):
            return status
        assert time.monotonic() < deadline, status
        time.sleep(0.1)


def finish(client: TestClient, key: str, limit: float = 240) -> dict:
    return wait(client, key, lambda s: bool(s["run"]) and s["run"]["state"] not in ACTIVE, limit)


def at_step(client: TestClient, key: str, step: str) -> dict:
    return wait(client, key, lambda s: s["run"]["step"] == step or s["run"]["state"] not in ACTIVE)


def leftovers(book: Path) -> list[str]:
    """Dot-entries beside the release other than its job records."""
    release = release_folder(book)
    return sorted(
        p.name
        for p in release.parent.iterdir()
        if p.name.startswith(".") and p.name != jobs.jobs_directory(release).name
    )


# ---------------------------------------------------------------- the normal path


def test_a_coloring_job_is_reported_only_after_its_files_verify(
    client: TestClient, library: Path
) -> None:
    first = client.get("/api/projects/colors/produce").json()
    assert first["run"] is None and first["release"] is None and first["cancellable"]
    stale = client.post("/api/projects/colors/produce", json={"revision": "sha256-old"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "source_changed"
    started = start(client, "colors")
    assert started["run"]["state"] in {"starting", "running"}
    assert started["run"]["job_id"] and started["run"]["seq"] >= 0
    status = finish(client, "colors")
    run, release = status["run"], status["release"]
    assert run["state"] == "completed" and run["outcome"] in {"ready", "blocked"}, run
    assert run["steps"][:2] == ["interior", "interior_preflight"]
    assert run["steps"][-2:] == ["release_verify", "release_swap"]
    assert run["limits"]["memory_mb"] == 4096 and run["limits"]["priority"]
    assert run["result"]["manifest_sha256"] == release["manifest_sha256"]
    assert run["pid"] and run["seconds"] > 0
    assert release["verified"] and not release["stale"] and release["engine"] == "coloring"
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
    assert leftovers(library / "colors") == []

    # A changed file is never served or called verified.
    directory = release_folder(library / "colors")
    (directory / "preflight.json").write_bytes(b"{}")
    damaged = client.get("/api/projects/colors/produce").json()["release"]
    assert damaged["verified"] is False and "preflight.json" in damaged["problem"]
    assert (
        client.get("/api/projects/colors/produce/file", params={"name": "interior.pdf"}).status_code
        == 404
    )


def test_the_release_goes_stale_when_the_source_changes(client: TestClient) -> None:
    start(client, "colors")
    finish(client, "colors")
    detail = client.get("/api/projects/colors").json()
    source = detail["source"]
    source["coloring"]["layout"]["border"] = "thin"
    saved = client.post(
        "/api/projects/colors/draft/save", json={"source": source, "revision": detail["revision"]}
    )
    assert saved.status_code == 200, saved.text
    assert client.get("/api/projects/colors/produce").json()["release"]["stale"] is True


def test_word_search_jobs_produce_the_cli_files(client: TestClient) -> None:
    start(client, "words")
    status = finish(client, "words")
    assert status["run"]["state"] == "completed", status["run"]
    assert status["release"]["verified"]
    names = {f["name"] for f in status["release"]["files"]}
    assert {"interior.pdf", "preflight.json", "publishing-validation.json"} <= names
    manifest = client.get("/api/projects/words/produce/file", params={"name": "production.json"})
    assert manifest.status_code == 200 and b"puzzlepress-production-run" in manifest.content
    assert client.get("/api/projects/words/produce/package.zip").status_code == 404


def test_the_package_zip_holds_the_verified_package(tmp_path: Path) -> None:
    from tests.coloring_production import write_book

    books = tmp_path / "ready"
    write_book(books)  # SYNTHETIC decisions, in books/book.
    ready = app(books, tmp_path)
    start(ready, "book")
    status = finish(ready, "book", 300)
    assert status["run"]["state"] == "completed" and status["run"]["outcome"] == "ready"
    assert status["release"]["package"]
    data = ready.get("/api/projects/book/produce/package.zip").content
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert "publishing/interior.pdf" in names and "publishing/package.json" in names
        listed = {f["name"]: f["sha256"] for f in status["release"]["files"]}
        for name in names:
            assert hashlib.sha256(archive.read(name)).hexdigest() == listed[name]


# ---------------------------------------------------------------- cancellation


def test_a_cancelled_coloring_job_keeps_the_previous_release(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start(client, "colors")
    before = finish(client, "colors")["release"]
    harness(monkeypatch, "--slow", "duplicates", "30")
    start(client, "colors")
    assert at_step(client, "colors", "duplicates")["run"]["state"] == "running"
    again = client.post(
        "/api/projects/colors/produce", json={"revision": revision(client, "colors")}
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "production_in_progress"
    requested = client.post("/api/projects/colors/produce/cancel", json={}).json()["run"]
    assert requested["cancel_requested"] and requested["state"] == "cancelling"
    assert not requested["cancellable"]
    status = finish(client, "colors")
    run = status["run"]
    assert run["state"] == "cancelled" and run["error"]["code"] == "cancelled"
    assert "release_swap" not in run["steps"] and run["release_preserved"] == "unchanged"
    assert status["release"]["verified"] and status["release"]["files"] == before["files"]
    assert status["release"]["manifest_sha256"] == before["manifest_sha256"]
    assert leftovers(library / "colors") == []


def test_cancellation_lands_inside_a_step(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Word-search jobs are staged too, so they can stop midway: here inside page drawing,
    at a checkpoint, without waiting for the step to end."""
    harness(monkeypatch, "--slow-stage", "render_pages", "0.5")
    start(client, "words")
    running = wait(
        client,
        "words",
        lambda s: (
            (s["run"]["progress"] or {}).get("stage") == "render_pages"
            or s["run"]["state"] not in ACTIVE
        ),
    )
    progress = running["run"]["progress"]
    assert progress["total"] and progress["done"] < progress["total"]
    assert progress["label"] == "pages drawn"
    asked = time.monotonic()
    client.post("/api/projects/words/produce/cancel", json={})
    status = finish(client, "words")
    latency = time.monotonic() - asked
    assert status["run"]["state"] == "cancelled", status["run"]
    assert status["run"]["error"]["stage"] == "render_pages"
    assert latency < 10, latency  # Half a second per page here; far less than the step.
    assert status["release"] is None and leftovers(library / "words") == []


def test_cancelling_without_an_active_job_is_refused(client: TestClient) -> None:
    refused = client.post("/api/projects/colors/produce/cancel", json={})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "no_active_run"


# ---------------------------------------------------------------- concurrency


def test_one_writer_per_release_and_independent_books(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness(monkeypatch, "--slow", "interior", "4")
    start(client, "colors")
    start(client, "words")  # A different release: runs beside it (two workers allowed).
    both = wait(
        client,
        "colors",
        lambda s: (
            s["run"]["state"] == "running"
            and client.get("/api/projects/words/produce").json()["run"]["state"] == "running"
        ),
        60,
    )
    assert both["workers"]["running"] == 2
    refused = client.post(
        "/api/projects/words/produce", json={"revision": revision(client, "words")}
    )
    assert refused.json()["error"]["code"] == "production_in_progress"
    assert finish(client, "colors")["run"]["state"] == "completed"
    assert finish(client, "words")["run"]["state"] == "completed"


def test_jobs_beyond_the_worker_limit_wait_their_turn(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(producing, "default_workers", lambda: 1)
    client = app(library, tmp_path)
    harness(monkeypatch, "--slow", "interior", "3")
    start(client, "colors")
    queued = start(client, "words")["run"]
    assert queued["state"] == "queued" and queued["queue_position"] == 1
    assert finish(client, "colors")["run"]["state"] == "completed"
    assert finish(client, "words")["run"]["state"] == "completed"


def test_a_queued_job_can_be_cancelled_before_it_starts(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(producing, "default_workers", lambda: 1)
    client = app(library, tmp_path)
    harness(monkeypatch, "--slow", "interior", "3")
    start(client, "colors")
    start(client, "words")
    cancelled = client.post("/api/projects/words/produce/cancel", json={}).json()["run"]
    assert cancelled["state"] == "cancelled" and cancelled["release_preserved"] == "none"
    assert finish(client, "colors")["run"]["state"] == "completed"


def test_a_command_line_run_holding_the_lock_is_respected(
    client: TestClient, library: Path
) -> None:
    release = release_folder(library / "colors")
    release.parent.mkdir(parents=True, exist_ok=True)
    with production_lock(jobs.lock_path(release)):
        refused = client.post(
            "/api/projects/colors/produce", json={"revision": revision(client, "colors")}
        )
    assert (
        refused.status_code == 409 and refused.json()["error"]["code"] == "production_in_progress"
    )
    assert "command line" in refused.json()["error"]["message"]


# ---------------------------------------------------------------- failures and recovery


def test_a_crashed_worker_is_interrupted_and_the_next_job_cleans_up(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start(client, "colors")
    before = finish(client, "colors")["release"]
    original = producing.worker_command
    harness(monkeypatch, "--crash", "duplicates")
    start(client, "colors")
    status = finish(client, "colors")
    run = status["run"]
    assert run["state"] == "interrupted" and run["error"]["code"] == "worker_exited"
    assert "exit code 9" in run["error"]["message"]
    assert run["release_preserved"] == "unchanged"
    assert status["release"]["verified"] and status["release"]["files"] == before["files"]
    # The killed worker left its staging directory; the next job removes it and says so.
    assert any(".job-staging-" in name for name in leftovers(library / "colors"))
    monkeypatch.setattr(producing, "worker_command", original)
    start(client, "colors")
    again = finish(client, "colors")["run"]
    assert again["state"] == "completed"
    assert any("interrupted run" in note for note in again["notes"])
    assert leftovers(library / "colors") == []


def test_a_worker_that_cannot_start_fails_the_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = str(tmp_path / "no-such-python.exe")
    monkeypatch.setattr(producing, "worker_command", lambda job: [missing, str(job)])
    status = start(client, "colors")
    assert status["run"]["state"] == "failed"
    assert status["run"]["error"]["code"] == "worker_start_failed"
    monkeypatch.setattr(
        producing, "worker_command", lambda job: [sys.executable, "-c", "raise SystemExit(2)"]
    )
    start(client, "colors")
    exited = finish(client, "colors")["run"]
    assert exited["state"] == "failed" and exited["error"]["code"] == "worker_start_failed"


def test_a_staged_release_that_does_not_verify_is_never_swapped_in(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start(client, "colors")
    before = finish(client, "colors")["release"]
    harness(monkeypatch, "--tamper")
    start(client, "colors")
    run = finish(client, "colors")["run"]
    assert run["state"] == "failed" and run["error"]["code"] == "verification_failed"
    after = client.get("/api/projects/colors/produce").json()["release"]
    assert after["manifest_sha256"] == before["manifest_sha256"] and after["verified"]
    assert run["release_preserved"] == "unchanged" and leftovers(library / "colors") == []


def test_a_source_saved_after_the_request_is_refused_by_the_worker(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness(monkeypatch, "--hold", "2")
    start(client, "colors")
    book = library / "colors" / "book.yaml"
    book.write_text(book.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    run = finish(client, "colors")["run"]
    assert run["state"] == "failed" and run["error"]["code"] == "source_changed"


def test_jobs_survive_a_studio_restart(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = app(library, tmp_path)
    harness(monkeypatch, "--slow", "duplicates", "30")
    job = start(first, "colors")["run"]["job_id"]
    at_step(first, "colors", "duplicates")
    # A new Studio process: no memory of the job, only its record and the lock.
    second = app(library, tmp_path)
    seen = second.get("/api/projects/colors/produce").json()["run"]
    assert seen["job_id"] == job and seen["state"] == "running" and seen["step"] == "duplicates"
    refused = second.post(
        "/api/projects/colors/produce", json={"revision": revision(second, "colors")}
    )
    assert refused.json()["error"]["code"] == "production_in_progress"
    second.post("/api/projects/colors/produce/cancel", json={})
    assert finish(second, "colors")["run"]["state"] == "cancelled"


def test_a_job_whose_worker_is_gone_is_interrupted_after_a_restart(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from puzzlepress.project import load_project

    client = app(library, tmp_path)
    release = release_folder(library / "colors")
    spec = jobs.JobSpec(
        jobs.new_job_id(),
        "colors",
        load_project(library / "colors").project.book.id,
        "coloring",
        str(library / "colors" / "book.yaml"),
        revision(client, "colors"),
        str(release),
        jobs.now(),
    )
    running = jobs.create_job(spec)
    jobs.append_event(running, {"event": "state", "state": "starting", "pid": 1}, True)
    jobs.append_event(running, {"event": "state", "state": "running"}, True)
    run = client.get("/api/projects/colors/produce").json()["run"]
    assert run["state"] == "interrupted" and run["error"]["code"] == "worker_lost"
    queued = jobs.create_job(jobs.JobSpec(**{**spec.__dict__, "job_id": jobs.new_job_id()}))
    # Within the start-up grace another Studio may still be launching its worker
    # (Interval 9); after it, a queued job nobody started is recorded as stopped.
    assert client.get("/api/projects/colors/produce").json()["run"]["state"] == "queued"
    monkeypatch.setattr(producing, "STARTING_GRACE", 0.0)
    run = client.get("/api/projects/colors/produce").json()["run"]
    assert run["job_id"] == queued.name and run["error"]["code"] == "studio_stopped"
    history = client.get("/api/projects/colors/produce").json()["history"]
    assert [h["state"] for h in history] == ["interrupted", "interrupted"]
    lines = (running / jobs.EVENTS_NAME).read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1])["state"] == "interrupted"


def test_studio_answers_while_a_worker_renders(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness(monkeypatch, "--slow", "interior", "2")
    start(client, "colors")
    wait(client, "colors", lambda s: s["run"]["state"] == "running")
    timings = []
    while client.get("/api/projects/colors/produce").json()["run"]["state"] in ACTIVE:
        begun = time.monotonic()
        assert client.get("/api/projects").status_code == 200
        timings.append(time.monotonic() - begun)
        time.sleep(0.05)
    timings.sort()
    assert timings and timings[len(timings) // 2] < 1.0, timings


# ---------------------------------------------------------------- cheap polling (Interval 9)


def test_the_job_poll_reads_no_release_file_and_never_vouches_for_one(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start(client, "colors")
    full = finish(client, "colors")
    directory = release_folder(library / "colors")

    def refuse(*args: object) -> None:
        raise AssertionError("the job poll must not verify the release")

    monkeypatch.setattr(producing, "verified_release", refuse)
    poll = client.get("/api/projects/colors/produce/job").json()
    monkeypatch.undo()
    assert "release" not in poll and poll["release_checked"] is False
    assert poll["run"]["job_id"] == full["run"]["job_id"]
    assert poll["release_manifest_sha256"] == full["release"]["manifest_sha256"]
    # A tampered file leaves production.json alone; only full verification sees it.
    (directory / "interior.pdf").write_bytes(b"%PDF-1.4 changed")
    assert (
        client.get("/api/projects/colors/produce/job").json()["release_manifest_sha256"]
        == (full["release"]["manifest_sha256"])
    )
    damaged = client.get("/api/projects/colors/produce").json()["release"]
    assert damaged["verified"] is False and "interior.pdf" in damaged["problem"]
    blocked = client.get("/api/projects/colors/produce/file", params={"name": "interior.pdf"})
    assert blocked.status_code == 404


def test_the_parse_cache_follows_the_exact_bytes_of_book_yaml(
    client: TestClient, library: Path
) -> None:
    before = client.get("/api/projects/colors/produce/job").json()["revision"]
    book = library / "colors" / "book.yaml"
    book.write_text(book.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    after = client.get("/api/projects/colors/produce/job").json()["revision"]
    assert after != before
    assert after == client.get("/api/projects/colors").json()["revision"]
    assert client.get("/api/projects/colors/produce").json()["revision"] == after


# ---------------------------------------------------------------- worker hardening (Interval 9)


@pytest.mark.parametrize(
    "step", ["interior", "interior_preflight", "duplicates", "manifest", "release_verify"]
)
def test_a_worker_killed_at_any_step_leaves_the_release_unchanged(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    start(client, "colors")
    before = finish(client, "colors")["release"]
    harness(monkeypatch, "--crash", step)
    start(client, "colors")
    status = finish(client, "colors")
    assert status["run"]["state"] == "interrupted", status["run"]
    assert status["run"]["release_preserved"] == "unchanged"
    assert status["release"]["manifest_sha256"] == before["manifest_sha256"]
    assert status["release"]["verified"]


def test_a_worker_killed_inside_the_swap_is_restored_by_the_next_job(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start(client, "colors")
    before = finish(client, "colors")["release"]
    original = producing.worker_command
    harness(monkeypatch, "--crash-in-swap")
    start(client, "colors")
    status = finish(client, "colors")
    assert status["run"]["state"] == "interrupted"
    assert status["release"] is None and status["recovery_pending"] is True
    assert status["run"]["release_preserved"] == "pending_recovery"
    assert client.get("/api/projects/colors/produce/job").json()["recovery_pending"] is True
    monkeypatch.setattr(producing, "worker_command", original)
    start(client, "colors")
    again = finish(client, "colors")
    assert again["run"]["state"] == "completed", again["run"]
    assert any("Restored the previous output" in n for n in again["run"]["notes"])
    assert again["release"]["verified"] and again["recovery_pending"] is False
    assert again["release"]["files"] == before["files"]  # Same source, same bytes.
    assert leftovers(library / "colors") == []


def test_two_workers_racing_for_one_release_never_both_write(library: Path) -> None:
    """Two job records for one release, both workers started at once (as two Studio
    processes could): the lock lets exactly one produce; the other is refused."""
    import subprocess

    from puzzlepress.project import load_project
    from puzzlepress.source_store import source_revision

    book = library / "colors"
    target = release_folder(book)
    project = load_project(book).project
    specs = [
        jobs.JobSpec(
            jobs.new_job_id(),
            "colors",
            project.book.id,
            "coloring",
            str(book / "book.yaml"),
            source_revision(book / "book.yaml"),
            str(target),
            jobs.now(),
        )
        for _ in range(2)
    ]
    directories = [jobs.create_job(spec) for spec in specs]
    workers = [
        subprocess.Popen([sys.executable, "-m", "puzzlepress.production.worker", str(d)])
        for d in directories
    ]
    codes = sorted(w.wait(timeout=300) for w in workers)
    views = [jobs.read_job(d) for d in directories]
    states = sorted(v.state for v in views)
    assert codes == [0, 1] and states == ["completed", "failed"], [v.error for v in views]
    refused = next(v for v in views if v.state == "failed")
    assert refused.error and refused.error["code"] == "production_in_progress"
    from puzzlepress.production import release

    assert release.verify_release(target)["book_id"] == project.book.id


def test_a_second_studio_waits_for_a_job_another_one_is_starting(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = app(library, tmp_path)
    harness(monkeypatch, "--hold", "4")  # The worker takes 4 s to report anything.
    start(first, "colors")
    second = app(library, tmp_path)
    seen = second.get("/api/projects/colors/produce/job").json()["run"]
    assert seen["state"] == "queued"  # Not called interrupted while it may be starting.
    refused = second.post(
        "/api/projects/colors/produce", json={"revision": revision(second, "colors")}
    )
    assert refused.json()["error"]["code"] == "production_in_progress"
    assert finish(second, "colors")["run"]["state"] == "completed"


def test_a_starting_job_whose_worker_never_came_is_interrupted_after_the_grace(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from puzzlepress.project import load_project

    client = app(library, tmp_path)
    book = library / "colors"
    spec = jobs.JobSpec(
        jobs.new_job_id(),
        "colors",
        load_project(book).project.book.id,
        "coloring",
        str(book / "book.yaml"),
        revision(client, "colors"),
        str(release_folder(book)),
        jobs.now(),
    )
    job = jobs.create_job(spec)
    jobs.append_event(job, {"event": "state", "state": "starting", "pid": 1}, True)
    assert client.get("/api/projects/colors/produce/job").json()["run"]["state"] == "starting"
    monkeypatch.setattr(producing, "STARTING_GRACE", 0.0)
    run = client.get("/api/projects/colors/produce/job").json()["run"]
    assert run["state"] == "interrupted" and run["error"]["code"] == "worker_lost"


def test_the_memory_cap_fails_the_job_and_keeps_the_release(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def capped(service: object) -> producing.ProducingService:
        return producing.ProducingService(service, memory_limit_mb=1024)  # type: ignore[arg-type]

    frontend = tmp_path / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(library, frontend, capped))
    start(client, "colors")
    before = finish(client, "colors")["release"]
    harness(monkeypatch, "--allocate", "duplicates", "2048")
    start(client, "colors")
    run = finish(client, "colors")["run"]
    assert run["limits"]["memory_mb"] == 1024
    assert run["state"] == "failed" and run["error"]["code"] == "memory_limit", run
    after = client.get("/api/projects/colors/produce").json()["release"]
    assert after["manifest_sha256"] == before["manifest_sha256"] and after["verified"]
    assert leftovers(library / "colors") == []


def test_worker_logs_are_bounded(
    client: TestClient, library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness(monkeypatch, "--noise", "1500")
    start(client, "colors")
    run = finish(client, "colors")["run"]
    job = next(
        d
        for d in jobs.job_directories(release_folder(library / "colors"))
        if d.name == run["job_id"]
    )
    deadline = time.monotonic() + 15  # Bounded by the monitor once the worker exited.
    while len(data := (job / jobs.LOG_NAME).read_bytes()) > producing.LOG_LIMIT + 100:
        assert time.monotonic() < deadline, len(data)
        time.sleep(0.1)
    assert data.startswith(b"[worker.log: the first ")
