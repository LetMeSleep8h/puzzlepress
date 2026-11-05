"""Production jobs, the worker and cooperative cancellation, below Studio (Interval 8)."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from puzzlepress.cancellation import Cancelled, checkpoint, watching
from puzzlepress.production import jobs, release, worker
from puzzlepress.production.lock import lock_held, production_lock
from puzzlepress.production.produce import produce
from tests.helpers import DEMO


def spec(tmp_path: Path, **changes: object) -> jobs.JobSpec:
    base = jobs.JobSpec(
        jobs.new_job_id(),
        "book",
        "book-id",
        "word_search",
        str(tmp_path / "book" / "book.yaml"),
        "sha256-x",
        str(tmp_path / "out" / "book-release"),
        jobs.now(),
    )
    return jobs.JobSpec(**{**base.__dict__, **changes})


# ---------------------------------------------------------------- cancellation


def test_checkpoints_do_nothing_without_a_watcher() -> None:
    checkpoint("anything", 1, 2)  # No watcher: returns, records nothing.


def test_a_watcher_hears_checkpoints_and_cancellation_is_not_swallowed() -> None:
    heard: list[tuple[str, int | None, int | None]] = []

    def hook(stage: str, done: int | None, total: int | None) -> None:
        heard.append((stage, done, total))
        if done == 2:
            raise Cancelled(stage)

    with pytest.raises(Cancelled) as raised, watching(hook):
        for index in range(5):
            try:
                checkpoint("pages", index, 5)
            except Exception:  # noqa: BLE001 - a broad handler must not catch it.
                pytest.fail("Cancelled was caught as an Exception")
    assert raised.value.stage == "pages" and heard == [
        ("pages", 0, 5),
        ("pages", 1, 5),
        ("pages", 2, 5),
    ]
    checkpoint("after", 0, 1)  # The watcher is gone once the block ends.
    assert len(heard) == 3


def test_outputs_are_byte_identical_with_a_watcher(tmp_path: Path) -> None:
    plain = produce(DEMO / "book.yaml", tmp_path / "plain")
    stages: set[str] = set()
    with watching(lambda stage, done, total: stages.add(stage)):
        watched = produce(DEMO / "book.yaml", tmp_path / "watched")
    assert plain.files == watched.files
    assert {"generate_puzzles", "render_pages", "inspect_pdf"} <= stages


# ---------------------------------------------------------------- job records


def test_a_job_folds_its_events_and_ignores_a_half_written_line(tmp_path: Path) -> None:
    job = jobs.create_job(spec(tmp_path))
    with pytest.raises(FileExistsError):
        jobs.create_job(jobs.read_spec(job))
    assert jobs.read_job(job).state == "queued"
    jobs.append_event(job, {"event": "state", "state": "starting", "pid": 42}, True)
    jobs.append_event(job, {"event": "state", "state": "running", "limits": {"memory_mb": 1}})
    jobs.append_event(job, {"event": "step", "step": "interior"})
    jobs.append_event(job, {"event": "progress", "stage": "render_pages", "done": 3, "total": 9})
    with open(job / jobs.EVENTS_NAME, "a", encoding="utf-8") as stream:
        stream.write('{"event": "state", "state": "comp')  # A writer mid-line.
    view = jobs.read_job(job)
    assert (view.state, view.pid, view.step, view.seq) == ("running", 42, "interior", 4)
    assert view.progress == {"stage": "render_pages", "done": 3, "total": 9}
    assert view.limits == {"memory_mb": 1}
    jobs.request_cancel(job)
    assert jobs.read_job(job).to_dict()["state"] == "cancelling"


def test_a_terminal_state_is_final(tmp_path: Path) -> None:
    job = jobs.create_job(spec(tmp_path))
    jobs.append_event(job, {"event": "state", "state": "running"})
    jobs.append_event(job, {"event": "state", "state": "completed", "outcome": "ready"}, True)
    jobs.append_event(job, {"event": "state", "state": "interrupted"}, True)
    jobs.append_event(job, {"event": "step", "step": "late"})
    view = jobs.read_job(job)
    assert view.state == "completed" and view.outcome == "ready" and view.terminal
    assert view.steps == () and view.finished


def test_job_ids_sort_by_creation_and_old_jobs_are_pruned(tmp_path: Path) -> None:
    created = []
    for index in range(13):
        job = jobs.create_job(spec(tmp_path))
        if index != 1:  # One unfinished job is never pruned.
            jobs.append_event(job, {"event": "state", "state": "failed"}, True)
        created.append(job)
    target = Path(spec(tmp_path).release)
    assert jobs.job_directories(target) == sorted(created)
    (jobs.jobs_directory(target) / "not-a-job").mkdir()
    jobs.prune(target)
    kept = jobs.job_directories(target)
    assert created[1] in kept and len(kept) == jobs.KEEP_JOBS + 1
    assert kept[-jobs.KEEP_JOBS :] == created[-jobs.KEEP_JOBS :]
    assert (jobs.jobs_directory(target) / "not-a-job").is_dir()


def test_damaged_job_records_are_refused(tmp_path: Path) -> None:
    job = jobs.create_job(spec(tmp_path))
    (job / jobs.SPEC_NAME).write_text(json.dumps({"job_version": 99}), encoding="utf-8")
    with pytest.raises(ValueError):
        jobs.read_job(job)


# ---------------------------------------------------------------- the lock probe


def test_the_lock_probe_sees_a_holder_and_leaves_the_file(tmp_path: Path) -> None:
    path = tmp_path / ".out.produce.lock"
    assert not lock_held(path)
    with production_lock(path):
        assert lock_held(path) and path.exists()
    assert not lock_held(path)


def test_a_lock_held_by_another_process_is_seen_and_freed_when_it_dies(tmp_path: Path) -> None:
    path = tmp_path / ".out.produce.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path; "
            "from puzzlepress.production.lock import production_lock\n"
            f"with production_lock(Path({str(path)!r})):\n"
            "    print('held', flush=True); time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        assert lock_held(path)
    finally:
        holder.kill()
        holder.wait()
    # The kernel releases it with the process (Windows may take a moment to).
    deadline = time.monotonic() + 10
    while lock_held(path):
        assert time.monotonic() < deadline
        time.sleep(0.05)


# ---------------------------------------------------------------- limits


def test_the_memory_limit_turns_an_oversized_allocation_into_memory_error() -> None:
    script = (
        "from puzzlepress.production.limits import apply_limits\n"
        "applied = apply_limits(256)\n"
        "assert applied['memory_mb'] == 256, applied\n"
        "try:\n"
        "    block = bytearray(1024 * 1024 * 1024)\n"
        "except MemoryError:\n"
        "    print('refused')\n"
        "else:\n"
        "    print('allocated')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert result.stdout.strip() == "refused", result.stderr


# ---------------------------------------------------------------- the worker in this process


def test_the_worker_refuses_a_changed_source_and_cleans_up(tmp_path: Path) -> None:
    book = tmp_path / "book"
    book.mkdir()
    (book / "book.yaml").write_bytes((DEMO / "book.yaml").read_bytes())
    job = jobs.create_job(spec(tmp_path, revision="sha256-not-this"))
    with pytest.raises(Exception, match="") as raised:
        worker.run(job, jobs.read_spec(job), {})
    assert raised.value.issues[0].code == "source_changed"  # type: ignore[attr-defined]
    target = Path(jobs.read_spec(job).release)
    assert not target.exists() and not list(target.parent.glob(".*job-staging-*"))


def test_a_cancel_request_stops_the_worker_before_anything_is_written(tmp_path: Path) -> None:
    from puzzlepress.source_store import source_revision

    book = tmp_path / "book"
    book.mkdir()
    (book / "book.yaml").write_bytes((DEMO / "book.yaml").read_bytes())
    job = jobs.create_job(spec(tmp_path, revision=source_revision(book / "book.yaml")))
    jobs.request_cancel(job)
    with pytest.raises(Cancelled):
        worker.run(job, jobs.read_spec(job), {})
    target = Path(jobs.read_spec(job).release)
    assert not target.exists() and not list(target.parent.glob(".*job-staging-*"))
    assert not lock_held(jobs.lock_path(target))


def test_the_worker_produces_a_verified_release_in_place(tmp_path: Path) -> None:
    from puzzlepress.source_store import source_revision

    book = tmp_path / "book"
    book.mkdir()
    (book / "book.yaml").write_bytes((DEMO / "book.yaml").read_bytes())
    from puzzlepress.project import load_project

    book_id = load_project(book / "book.yaml").project.book.id
    job = jobs.create_job(
        spec(tmp_path, revision=source_revision(book / "book.yaml"), book_id=book_id)
    )
    final = worker.run(job, jobs.read_spec(job), {})
    target = Path(jobs.read_spec(job).release)
    manifest = release.verify_release(target)
    assert final["state"] == "completed" and manifest["book_id"]
    direct = produce(DEMO / "book.yaml", tmp_path / "direct")
    assert {name: digest for name, digest, _ in direct.files} == {
        f["name"]: f["sha256"]
        for f in manifest["files"]  # type: ignore[union-attr]
    }
