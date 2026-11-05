"""Measure Studio production jobs on SYNTHETIC books (Interval 8).

    python tests/production_benchmark.py WORK_DIR [--drawings 10 50 150 300]
        [--word-search] [--cancel-from 150] [--crash] [--concurrent]

For each workload a book is written into WORK_DIR/books (full-size synthetic line art,
2175 x 2925 px, or the word-search demos), and Studio's API (in this process, as the
server runs it) starts a job whose worker runs in its own process. While it runs, the
page's requests are timed (`GET /api/projects` and the produce status, every 0.5 s).
Reported per job, from the job's own event log: worker start (request to `starting`
and to `running`), seconds per step, total, the worker's peak memory, interior PDF
size, and whether every release file verified (package ZIP entries too when packaged).
Cancellation is measured from the request to the job's terminal state, asked during
`interior_preflight` (as Interval 7 did). Times depend on the machine and its load:
compare runs on one machine and day only.
"""

import argparse
import hashlib
import io
import json
import shutil
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from coloring_helpers import FULL_SIZE, composed_coloring_book  # noqa: E402

ACTIVE = {"queued", "starting", "running", "cancelling"}


def _at(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def timeline(job_dir: Path) -> dict[str, object]:
    """Worker start and per-step seconds from the job's events."""
    from puzzlepress.production import jobs

    spec = jobs.read_spec(job_dir)
    events = [
        json.loads(line)
        for line in (job_dir / jobs.EVENTS_NAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    created = _at(spec.created)
    marks: dict[str, float] = {}
    steps: list[tuple[str, float]] = []
    end = None
    for event in events:
        if event.get("event") == "state":
            marks.setdefault(str(event["state"]), _at(event["at"]))
            if event["state"] in jobs.TERMINAL:
                end = _at(event["at"])
        elif event.get("event") == "step":
            steps.append((str(event["step"]), _at(event["at"])))
    seconds: dict[str, float] = {}
    for index, (name, begun) in enumerate(steps):
        until = steps[index + 1][1] if index + 1 < len(steps) else (end or begun)
        seconds[name] = round(seconds.get(name, 0.0) + until - begun, 2)
    return {
        "request_to_starting_s": round(marks["starting"] - created, 2)
        if "starting" in marks
        else None,
        "request_to_running_s": round(marks["running"] - created, 2)
        if "running" in marks
        else None,
        "total_s": round((end or time.time()) - created, 1),
        "steps_s": seconds,
    }


def package_ok(client: object, key: str, release: dict) -> bool | None:
    if not release.get("package"):
        return None
    data = client.get(f"/api/projects/{key}/produce/package.zip").content  # type: ignore[attr-defined]
    listed = {f["name"]: f["sha256"] for f in release["files"]}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return all(
            hashlib.sha256(archive.read(name)).hexdigest() == listed.get(name)
            for name in archive.namelist()
        )


def run_job(client: object, library: Path, key: str, cancel_at: str | None = None) -> dict:
    from puzzlepress.production import jobs

    get = client.get  # type: ignore[attr-defined]
    post = client.post  # type: ignore[attr-defined]
    revision = get(f"/api/projects/{key}").json()["revision"]
    started = post(f"/api/projects/{key}/produce", json={"revision": revision}).json()
    job_id = started["run"]["job_id"]
    asked = None
    cancel_progress = None
    timed: dict[str, list[float]] = {"status": [], "detail": []}
    while True:
        begun = time.perf_counter()
        status = get(f"/api/projects/{key}/produce").json()
        timed["status"].append(time.perf_counter() - begun)
        begun = time.perf_counter()
        get(f"/api/projects/{key}")  # What the page shell reloads (Interval 7 timed both).
        timed["detail"].append(time.perf_counter() - begun)
        run = status["run"]
        if cancel_at and asked is None and run["step"] == cancel_at:
            post(f"/api/projects/{key}/produce/cancel", json={})
            asked = time.perf_counter()
            cancel_progress = run.get("progress")
        if run["state"] not in ACTIVE:
            stopped = time.perf_counter()
            break
        time.sleep(0.5)
    idle = {"status": [], "detail": []}
    for _ in range(10):  # The same requests with no job running, right after it.
        begun = time.perf_counter()
        get(f"/api/projects/{key}/produce")
        idle["status"].append(time.perf_counter() - begun)
        begun = time.perf_counter()
        get(f"/api/projects/{key}")
        idle["detail"].append(time.perf_counter() - begun)
    release = status["release"] or {}
    job_dir = next(d for d in jobs.job_directories(_release_dir(library, key)) if d.name == job_id)
    files = {f["name"]: f["bytes"] for f in release.get("files", [])}
    report = {
        "state": run["state"],
        "outcome": run.get("outcome"),
        **timeline(job_dir),
        "peak_worker_memory_mb": (run.get("result") or {}).get("peak_memory_mb"),
        "interior_pdf_mb": round(files["interior.pdf"] / 2**20, 2)
        if "interior.pdf" in files
        else None,
        "release_verified": release.get("verified"),
        "release_preserved": run.get("release_preserved"),
        "package_zip_verified": package_ok(client, key, release)
        if release.get("verified")
        else None,
        "studio_polls": len(timed["status"]),
        "during_job_ms": {name: _stats(values) for name, values in timed.items()},
        "idle_ms": {name: _stats(values) for name, values in idle.items()},
    }
    if asked is not None:
        report["cancel_to_stop_s"] = round(stopped - asked, 2)
        report["cancel_progress_at_request"] = cancel_progress
        report["cancel_stage"] = (run.get("error") or {}).get("stage")
    return report


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "median": round(1000 * ordered[len(ordered) // 2], 1),
        "p95": round(1000 * ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
        "max": round(1000 * ordered[-1], 1),
    }


def _release_dir(library: Path, key: str) -> Path:
    from puzzlepress.project import load_project
    from puzzlepress.studio.producing import release_directory

    book = library / key
    return release_directory(load_project(book).project, book)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--drawings", type=int, nargs="*", default=[10, 50, 150, 300])
    parser.add_argument("--word-search", action="store_true")
    parser.add_argument("--cancel-from", type=int, default=150)
    parser.add_argument("--crash", action="store_true")
    parser.add_argument("--concurrent", action="store_true")
    parser.add_argument(
        "--normal-priority", action="store_true", help="Run workers at normal priority."
    )
    args = parser.parse_args(argv)
    from fastapi.testclient import TestClient

    from puzzlepress.studio import producing
    from puzzlepress.studio.server import create_app

    library = args.work / "books"
    library.mkdir(parents=True, exist_ok=True)
    for count in args.drawings:
        book = library / f"coloring-{count}"
        if not book.exists():
            composed_coloring_book(book, count, size=FULL_SIZE)
            source = book / "book.yaml"
            source.write_text(
                source.read_text(encoding="utf-8").replace(
                    "../build/synthetic-coloring-book", f"../../build/coloring-{count}"
                ),
                encoding="utf-8",
            )
    keys = [f"coloring-{count}" for count in args.drawings]
    if args.word_search:
        from production_book import write_production_book

        for name in ("composition-demo", "publishing-demo"):
            if not (library / name).exists():
                shutil.copytree(ROOT / "books" / name, library / name)
        if not (library / "production-book").exists():
            write_production_book(library / "production-book")
        keys += ["composition-demo", "publishing-demo", "production-book"]
    frontend = args.work / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")

    def jobs(service: object) -> producing.ProducingService:
        return producing.ProducingService(
            service,  # type: ignore[arg-type]
            lower_priority=not args.normal_priority,
        )

    client = TestClient(create_app(library, frontend, jobs))
    report: dict[str, object] = {
        "machine_note": "Compare on one machine and day only.",
        "worker_priority": "normal" if args.normal_priority else "below_normal",
    }
    for key in keys:
        print(f"producing {key}", file=sys.stderr, flush=True)
        report[key] = run_job(client, library, key)
        if key.startswith("coloring-") and int(key.split("-")[1]) >= args.cancel_from:
            print(f"cancelling {key}", file=sys.stderr, flush=True)
            report[f"{key} cancelled"] = run_job(
                client, library, key, cancel_at="interior_preflight"
            )
    if args.crash and keys:
        key = keys[0]
        original = producing.worker_command
        harness = ROOT / "tests" / "worker_harness.py"
        producing.worker_command = lambda job: [  # type: ignore[assignment]
            sys.executable,
            str(harness),
            "--crash",
            "duplicates",
            str(job),
        ]
        crashed = run_job(client, library, key)
        producing.worker_command = original  # type: ignore[assignment]
        begun = time.perf_counter()
        recovered = run_job(client, library, key)
        status = client.get(f"/api/projects/{key}/produce").json()
        report["crash_recovery"] = {
            "crashed_state": crashed["state"],
            "crashed_release_preserved": crashed["release_preserved"],
            "next_job_state": recovered["state"],
            "next_job_seconds": round(time.perf_counter() - begun, 1),
            "next_job_notes": status["run"]["notes"],
            "release_verified": status["release"]["verified"],
        }
    if args.concurrent and len(keys) >= 2:
        first, second = keys[0], keys[-1]
        revisions = {
            k: client.get(f"/api/projects/{k}").json()["revision"] for k in (first, second)
        }
        begun = time.perf_counter()
        for k in (first, second):
            client.post(f"/api/projects/{k}/produce", json={"revision": revisions[k]})
        competing = client.post(
            f"/api/projects/{first}/produce", json={"revision": revisions[first]}
        )
        overlap = False
        while True:
            states = [
                client.get(f"/api/projects/{k}/produce").json()["run"]["state"]
                for k in (first, second)
            ]
            overlap = overlap or states == ["running", "running"]
            if not any(s in ACTIVE for s in states):
                break
            time.sleep(0.5)
        report["concurrent"] = {
            "books": [first, second],
            "ran_at_the_same_time": overlap,
            "states": states,
            "wall_seconds": round(time.perf_counter() - begun, 1),
            "competing_request": competing.json().get("error", {}).get("code"),
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
