"""Studio adapter for production: start, follow, cancel and read production jobs.

A job runs `book produce` in its own process (`production.worker`), so the Studio
server stays responsive while a book renders. Studio adds only:

- the output folder, `<output.directory>-release` beside the build folder;
- the job record (`production.jobs`) beside it, which outlives Studio: after a
  restart the last job is still shown, a worker that is still running is followed,
  and one that is gone is reported as interrupted;
- at most `max_workers` workers at once (others wait as `queued`), and at most one
  job per release: a second request is refused while one is queued or running, and
  the worker itself takes the release's production lock, which `book produce` from
  the command line takes too;
- cancellation by request: the worker stops at its next checkpoint (inside page
  rendering, artwork preparation, measuring, PDF inspection and package writing,
  and between steps) and leaves the previous release untouched. Once a verified
  release is being swapped in, the job finishes;
- a check before reporting a release: every file `production.json` lists is read
  back and compared with its recorded SHA-256 and size.

A job belongs to the saved revision it started from: a different revision is
refused, and the release is reported as out of date once the source's build
identity differs from the one the release recorded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from puzzlepress.errors import ProjectError
from puzzlepress.identity import build_identity
from puzzlepress.models import Project
from puzzlepress.production import jobs
from puzzlepress.production.limits import DEFAULT_MEMORY_MB
from puzzlepress.production.lock import lock_held
from puzzlepress.production.release import pending_recovery
from puzzlepress.project import resolve_output_directory

from .service import StudioError, StudioService

LOGGER = logging.getLogger(__name__)
MANIFEST = "production.json"
STARTING_GRACE = 30.0  # Seconds a worker not started by this Studio may take to lock.
LOG_LIMIT = 1024 * 1024  # worker.log keeps at most its last megabyte.
# Windows refuses to replace a file another process has open (a reader of the log, an
# indexer): the bound retries briefly instead of leaving the log unbounded.
LOG_REPLACE_ATTEMPTS = 40
LOG_REPLACE_PAUSE = 0.05
STEP_LABELS = {
    "interior": "Building the interior PDF",
    "interior_preflight": "Checking the interior",
    "answer_key": "Reading the answers back from the PDF",
    "duplicates": "Looking for duplicates",
    "cover": "Building and checking the cover",
    "readiness": "Checking publishing readiness",
    "package": "Writing the upload package",
    "validation": "Sorting the findings",
    "manifest": "Recording every file",
    "verify": "Verifying every file",
    "swap": "Assembling the staged release",
    "release_verify": "Verifying the staged release",
    "release_swap": "Putting the release in place",
}
STAGE_LABELS = {
    "generate_puzzles": "puzzles generated",
    "prepare_artwork": "drawings prepared",
    "render_pages": "pages drawn",
    "inspect_pdf": "PDF pages inspected",
    "verify_images": "PDF pages' images verified",
    "measure_artwork": "drawings measured",
    "compare_artwork": "drawings compared",
    "read_pdf_text": "PDF pages read back",
    "write_package": "package files written",
}


def worker_command(job: Path) -> list[str]:
    """The command that runs one job (tests substitute their own)."""
    return [sys.executable, "-m", "puzzlepress.production.worker", str(job)]


def default_workers() -> int:
    return max(1, min(3, (os.cpu_count() or 2) // 2))


def release_directory(project: Project, source: Path) -> Path:
    output = resolve_output_directory(project, source)
    return output.parent / f"{output.name}-release"


def listed(manifest: dict[str, object] | None) -> list[dict[str, object]]:
    """The file records a production.json lists (none when it lists none)."""
    files = (manifest or {}).get("files")
    return [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []


def verified_release(directory: Path) -> tuple[dict[str, object] | None, str | None]:
    """(manifest, problem): the manifest when every listed file matches it."""
    path = directory / MANIFEST
    if not path.is_file():
        return None, None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        files = manifest["files"]
        for item in files:
            name = item["name"]
            target = (directory / name).resolve()
            if not target.is_relative_to(directory.resolve()) or not target.is_file():
                return manifest, f"{name} is missing."
            data = target.read_bytes()
            if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"]:
                return manifest, f"{name} differs from production.json."
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        return None, f"production.json is unreadable: {error}"
    return manifest, None


def _bound_log(path: Path) -> None:
    """Keep only the last LOG_LIMIT bytes of a finished worker's log (marked as cut)."""
    try:
        size = path.stat().st_size
        if size <= LOG_LIMIT:
            return
        with open(path, "rb") as stream:
            stream.seek(size - LOG_LIMIT)
            tail = stream.read()
        note = f"[worker.log: the first {size - LOG_LIMIT} bytes were removed]\n".encode()
        staged = path.with_name(path.name + ".tmp")
        staged.write_bytes(note + tail)
    except OSError:
        LOGGER.warning("Could not bound %s", path)
        return
    for attempt in range(LOG_REPLACE_ATTEMPTS):
        try:
            os.replace(staged, path)
            return
        except PermissionError:
            if attempt + 1 < LOG_REPLACE_ATTEMPTS:
                time.sleep(LOG_REPLACE_PAUSE)
        except OSError:
            break
    LOGGER.warning("Could not bound %s", path)
    try:
        staged.unlink()
    except OSError:
        pass


def _manifest_digest(release: Path) -> str | None:
    try:
        return hashlib.sha256((release / MANIFEST).read_bytes()).hexdigest()
    except OSError:
        return None


def _seconds(start: str | None, end: str | None) -> float | None:
    if start is None:
        return None
    try:
        begin = datetime.fromisoformat(start.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(UTC)
    except ValueError:
        return None
    return round(max(0.0, (finish - begin).total_seconds()), 1)


@dataclass
class _Worker:
    directory: Path
    process: subprocess.Popen[bytes] | None  # None while queued.


class ProducingService:
    def __init__(
        self,
        service: StudioService,
        max_workers: int | None = None,
        memory_limit_mb: int | None = DEFAULT_MEMORY_MB,
        lower_priority: bool = False,
    ) -> None:
        self.service = service
        self.max_workers = max_workers or default_workers()
        self.memory_limit_mb = memory_limit_mb
        self.lower_priority = lower_priority
        self._lock = threading.Lock()
        self._jobs: dict[str, _Worker] = {}  # By release directory; queued or running.
        self._queue: list[str] = []  # Release directories waiting for a worker.
        # Parsed sources by key: (revision, project, build identity), reused only for
        # the identical bytes.
        self._parsed: dict[str, tuple[str, Project, str]] = {}
        self._parsed_lock = threading.Lock()

    # ------------------------------------------------------------- locating

    def _locate(self, key: str) -> tuple[Project, str, Path, Path]:
        """(project, revision, book.yaml, release directory) for the saved source.

        `ProjectStore.snapshot` reads and hashes book.yaml on every call and reuses a
        parsed project only for byte-identical source, so polling stays cheap and
        never serves a project that differs from the file."""
        source = self.service.store.source(key)
        project, revision = self.service.store.snapshot(key)
        with self._parsed_lock:
            cached = self._parsed.get(key)
        if cached is None or cached[0] != revision:
            with self._parsed_lock:
                self._parsed[key] = (revision, project, build_identity(project))
        try:
            directory = release_directory(project, source.parent)
        except ProjectError as error:
            raise StudioError(
                503, "output_unavailable", "The output folder is unavailable."
            ) from error
        return project, revision, source, directory

    def _identity(self, key: str, revision: str, project: Project) -> str:
        with self._parsed_lock:
            cached = self._parsed.get(key)
        return (
            cached[2] if cached is not None and cached[0] == revision else build_identity(project)
        )

    # ------------------------------------------------------------- jobs

    def _reconcile(self, release: Path, view: jobs.JobView) -> jobs.JobView:
        """Record the end of a job whose worker is provably gone (caller holds _lock)."""
        if view.terminal or str(release) in self._jobs:
            return view
        if view.state == "queued" and (_seconds(view.spec.created, None) or 0) < STARTING_GRACE:
            return view  # Another Studio process may be starting its worker right now.
        if view.state == "queued":
            error = {
                "code": "studio_stopped",
                "message": "Studio stopped before this job started. Start it again.",
            }
        elif lock_held(jobs.lock_path(release)):
            return view  # A worker from an earlier Studio session is still at work.
        elif view.state == "starting" and (_seconds(view.last_event, None) or 0) < STARTING_GRACE:
            return view
        else:
            error = {
                "code": "worker_lost",
                "message": "The worker stopped without reporting an ending (Studio or the "
                "computer restarted, or the process was ended).",
            }
        jobs.append_event(
            view.directory, {"event": "state", "state": "interrupted", "error": error}, True
        )
        return jobs.read_job(view.directory)

    def _latest(self, release: Path) -> jobs.JobView | None:
        for directory in reversed(jobs.job_directories(release)):
            try:
                return self._reconcile(release, jobs.read_job(directory))
            except (OSError, ValueError, KeyError, TypeError):
                LOGGER.warning("Unreadable production job %s", directory)
                continue
        return None

    def _history(self, release: Path) -> list[dict[str, object]]:
        found = []
        for directory in reversed(jobs.job_directories(release)[-5:]):
            try:
                view = jobs.read_job(directory)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            found.append(
                {
                    "job_id": view.spec.job_id,
                    "state": view.state,
                    "outcome": view.outcome,
                    "created": view.spec.created,
                    "seconds": _seconds(view.started or view.spec.created, view.finished),
                    "error": view.error.get("code") if view.error else None,
                }
            )
        return found

    def _launch(self, release: str) -> None:
        """Start the queued job's worker (caller holds _lock)."""
        worker = self._jobs[release]
        try:
            log = open(worker.directory / jobs.LOG_NAME, "ab")  # noqa: SIM115 - closed by monitor.
        except OSError as error:
            self._start_failed(release, worker, error)
            return
        options: dict[str, object] = {}
        if sys.platform == "win32":
            options["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            options["start_new_session"] = True
        try:
            process = subprocess.Popen(  # noqa: S603 - our own interpreter and module.
                worker_command(worker.directory),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                close_fds=True,
                **options,  # type: ignore[call-overload]
            )
        except OSError as error:
            log.close()
            self._start_failed(release, worker, error)
            return
        worker.process = process
        threading.Thread(
            target=self._monitor,
            args=(release, worker, log),
            daemon=True,
            name=f"produce-monitor-{worker.directory.name}",
        ).start()

    def _start_failed(self, release: str, worker: _Worker, error: OSError) -> None:
        jobs.append_event(
            worker.directory,
            {
                "event": "state",
                "state": "failed",
                "error": {
                    "code": "worker_start_failed",
                    "message": f"The production worker could not be started: {error}",
                },
            },
            True,
        )
        self._jobs.pop(release, None)

    def _monitor(self, release: str, worker: _Worker, log: object) -> None:
        assert worker.process is not None
        code = worker.process.wait()
        try:
            log.close()  # type: ignore[attr-defined]
        except OSError:
            pass
        _bound_log(worker.directory / jobs.LOG_NAME)
        with self._lock:
            try:
                view = jobs.read_job(worker.directory)
                if not view.terminal:
                    started = view.state != "queued"
                    jobs.append_event(
                        worker.directory,
                        {
                            "event": "state",
                            "state": "interrupted" if started else "failed",
                            "error": {
                                "code": "worker_exited" if started else "worker_start_failed",
                                "message": (
                                    f"The worker stopped (exit code {code}) before finishing. "
                                    "The previous release is unchanged; see worker.log."
                                    if started
                                    else f"The worker exited (code {code}) before it started; "
                                    "see worker.log."
                                ),
                            },
                        },
                        True,
                    )
            except (OSError, ValueError, KeyError, TypeError):
                LOGGER.exception("Could not record the end of production job %s", worker.directory)
            if self._jobs.get(release) is worker:
                self._jobs.pop(release)
            self._dispatch()

    def _dispatch(self) -> None:
        """Start queued jobs while worker slots are free (caller holds _lock)."""
        running = sum(1 for w in self._jobs.values() if w.process is not None)
        while self._queue and running < self.max_workers:
            release = self._queue.pop(0)
            if release in self._jobs and self._jobs[release].process is None:
                self._launch(release)
                running += 1

    # ------------------------------------------------------------- API

    def job(self, key: str) -> dict[str, object]:
        """The cheap poll: the latest job as its record says, and production.json's
        digest so a client can tell the release changed. Nothing here verifies the
        release; files are offered only from `status`, which reads every one back."""
        _, revision, _, directory = self._locate(key)
        with self._lock:
            view = self._latest(directory)
            queued = str(directory) in self._queue
            position = self._queue.index(str(directory)) + 1 if queued else None
            worker = self._jobs.get(str(directory))
            launched = worker is not None and worker.process is not None
            running = sum(1 for w in self._jobs.values() if w.process is not None)
        return {
            "key": key,
            "revision": revision,
            "directory": directory.name,
            "run": self._run(view, directory, position, launched) if view else None,
            "release_manifest_sha256": _manifest_digest(directory),
            "release_checked": False,
            "recovery_pending": pending_recovery(directory, jobs.backup_prefix(directory)),
            "workers": {"running": running, "limit": self.max_workers},
        }

    def status(self, key: str) -> dict[str, object]:
        project, revision, _, directory = self._locate(key)
        with self._lock:
            view = self._latest(directory)
            queued = str(directory) in self._queue
            position = self._queue.index(str(directory)) + 1 if queued else None
            worker = self._jobs.get(str(directory))
            launched = worker is not None and worker.process is not None
            running = sum(1 for w in self._jobs.values() if w.process is not None)
        manifest, problem = verified_release(directory)
        release: dict[str, object] | None = None
        if manifest is not None:
            result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
            recorded = manifest.get("build_identity")
            release = {
                "verified": problem is None,
                "problem": problem,
                "engine": manifest.get("engine", "word_search"),
                "profile": manifest.get("profile"),
                "result": result,
                "build_identity": recorded,
                "stale": recorded != self._identity(key, revision, project),
                "manifest_sha256": _manifest_digest(directory),
                "files": [
                    {"name": f["name"], "bytes": f["bytes"], "sha256": f["sha256"]}
                    for f in listed(manifest)
                ],
                "validation": self._validation(directory) if problem is None else None,
                "package": (directory / "publishing" / "package.json").is_file(),
            }
        elif problem is not None:
            release = {"verified": False, "problem": problem, "files": []}
        recovery = pending_recovery(directory, jobs.backup_prefix(directory))
        return {
            "key": key,
            "revision": revision,
            "directory": directory.name,
            "cancellable": True,
            "run": self._run(view, directory, position, launched) if view else None,
            "release": release,
            "recovery_pending": recovery,
            "history": self._history(directory),
            "workers": {"running": running, "limit": self.max_workers},
        }

    def _run(
        self, view: jobs.JobView, directory: Path, position: int | None, launched: bool
    ) -> dict[str, object]:
        data = view.to_dict()
        if view.state == "queued" and launched:
            data["state"] = "starting"  # Its worker is up but has not reported yet.
        active = not view.terminal
        progress = view.progress
        if progress and isinstance(progress.get("stage"), str):
            progress = {**progress, "label": STAGE_LABELS.get(str(progress["stage"]))}
        preserved: str | None = None
        if view.terminal and not (view.state == "completed"):
            now = _manifest_digest(directory)
            preserved = (
                "pending_recovery"
                if pending_recovery(directory, jobs.backup_prefix(directory))
                else "none"
                if view.spec.previous_release is None and now is None
                else "unchanged"
                if now == view.spec.previous_release
                else "changed"
            )
        return {
            **data,
            "progress": progress,
            "step_label": STEP_LABELS.get(view.step or "", view.step),
            "seconds": _seconds(view.started or view.spec.created, view.finished),
            "cancellable": active and not view.cancel_requested and view.step != "release_swap",
            "queue_position": position,
            "release_preserved": preserved,
        }

    @staticmethod
    def _validation(directory: Path) -> dict[str, object] | None:
        try:
            data = json.loads((directory / "publishing-validation.json").read_text("utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def start(self, key: str, revision: str) -> dict[str, object]:
        project, current, source, directory = self._locate(key)
        if current != revision:
            raise StudioError(
                409, "source_changed", "Saved source changed. Reload before producing."
            )
        release = str(directory)
        with self._lock:
            view = self._latest(directory)
            if view is not None and view.terminal and release in self._jobs:
                # Its worker reported the ending and is exiting; its monitor lets go of
                # the slot (only this entry, never a newer job's).
                self._jobs.pop(release)
            if release in self._jobs or (view is not None and not view.terminal):
                raise StudioError(
                    409, "production_in_progress", "A production job for this book is active."
                )
            if lock_held(jobs.lock_path(directory)):
                raise StudioError(
                    409,
                    "production_in_progress",
                    "Another production run (for example `book produce` from the command line) "
                    "is writing this release. Wait for it to finish.",
                )
            spec = jobs.JobSpec(
                jobs.new_job_id(),
                key,
                project.book.id,
                "coloring" if project.coloring is not None else "word_search",
                str(source),
                revision,
                release,
                jobs.now(),
                self.memory_limit_mb,
                _manifest_digest(directory),
                self.lower_priority,
            )
            try:
                job = jobs.create_job(spec)
            except OSError as error:
                raise StudioError(
                    503, "output_unavailable", f"Could not record the job: {error}"
                ) from error
            jobs.prune(directory)
            self._jobs[release] = _Worker(job, None)
            self._queue.append(release)
            self._dispatch()
        return self.status(key)

    def cancel(self, key: str) -> dict[str, object]:
        _, _, _, directory = self._locate(key)
        release = str(directory)
        with self._lock:
            view = self._latest(directory)
            if view is None or view.terminal:
                raise StudioError(409, "no_active_run", "No production job is active.")
            if view.step == "release_swap":
                raise StudioError(
                    409,
                    "not_cancellable",
                    "The verified release is being put in place; the job finishes on its own.",
                )
            worker = self._jobs.get(release)
            if worker is not None and worker.process is None:
                # Never started: no worker will write this log, so record the ending here.
                self._queue.remove(release)
                self._jobs.pop(release)
                jobs.append_event(
                    view.directory,
                    {
                        "event": "state",
                        "state": "cancelled",
                        "error": {"code": "cancelled", "message": "Cancelled before it started."},
                    },
                    True,
                )
            else:
                jobs.request_cancel(view.directory)
        return self.status(key)

    def file(self, key: str, name: str) -> tuple[bytes, str]:
        """One file the verified release lists, by its listed name."""
        _, _, _, directory = self._locate(key)
        manifest, problem = verified_release(directory)
        names = {f["name"] for f in listed(manifest)}
        if name != MANIFEST and (manifest is None or problem or name not in names):
            raise StudioError(404, "file_not_found", "That file is not part of a verified release.")
        if name == MANIFEST and manifest is None:
            raise StudioError(404, "file_not_found", "No release has been produced.")
        return (directory / name).read_bytes(), Path(name).name

    def package_zip(self, key: str) -> bytes:
        """The upload package (publishing/) as a stored ZIP, from verified bytes only."""
        _, _, _, directory = self._locate(key)
        manifest, problem = verified_release(directory)
        if manifest is None or problem:
            raise StudioError(404, "file_not_found", "No verified release to download.")
        names = sorted(
            str(f["name"]) for f in listed(manifest) if str(f["name"]).startswith("publishing/")
        )
        if not names:
            raise StudioError(404, "no_package", "This release has no upload package.")
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            for name in names:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                archive.writestr(info, (directory / name).read_bytes())
        return buffer.getvalue()
