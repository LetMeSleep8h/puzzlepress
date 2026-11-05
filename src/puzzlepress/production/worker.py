"""The production worker: one job, in its own operating-system process.

    python -m puzzlepress.production.worker JOB_DIRECTORY

Studio starts one per job (`studio.producing`), so a heavy build never shares the
server's interpreter, memory or GIL. The worker:

1. reports `starting`, applies its resource limits (`limits`);
2. takes the release's production lock, the same one `book produce` takes, so only
   one writer ever owns the release, and the kernel frees it if the worker dies;
3. finishes what an interrupted earlier job left (`release.recover`), then reports
   `running`;
4. refuses the job if book.yaml no longer has the requested revision;
5. runs the unchanged `produce()` into a private staging directory beside the
   release, reporting steps and work units (`cancellation.checkpoint`) and stopping
   at the next checkpoint once `cancel` exists in the job directory;
6. verifies the staged files against their production.json and checks the
   manifest's build identity is the requested source's, then (no longer
   cancellable) swaps the staged release in and verifies it again in place;
7. reports `completed` (ready or blocked), `cancelled` or `failed`, and removes its
   staging directory whatever happened.

The previous release is replaced only in step 6, by a verified release, and is
restored if the swap fails, so a failed, cancelled or killed worker leaves it as it
was. Exit status: 0 completed, 3 cancelled, 1 failed, 2 unusable job directory.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

from ..cancellation import Cancelled, watching
from . import jobs, release
from .limits import apply_limits, peak_memory_mb

PROGRESS_INTERVAL = 0.5  # Seconds between progress events of one step.
CANCEL_POLL = 0.2  # Seconds between checks for the cancel file.
EXIT_COMPLETED, EXIT_FAILED, EXIT_USAGE, EXIT_CANCELLED = 0, 1, 2, 3


class Reporter:
    """Writes the job's step and progress events and answers whether to stop."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.cancellable = True
        self._checked = 0.0
        self._requested = False
        self._last_progress = 0.0
        self._stage: str | None = None

    def requested(self) -> bool:
        clock = time.monotonic()
        if not self._requested and clock - self._checked >= CANCEL_POLL:
            self._checked = clock
            self._requested = jobs.cancel_requested(self.directory)
        return self._requested

    def stop_if_requested(self, stage: str) -> None:
        if self.cancellable and self.requested():
            raise Cancelled(stage)

    def step(self, name: str) -> None:
        self._checked = 0.0  # Always look at a step boundary.
        self.stop_if_requested(name)
        jobs.append_event(self.directory, {"event": "step", "step": name})
        self._stage = None

    def checkpoint(self, stage: str, done: int | None, total: int | None) -> None:
        self.stop_if_requested(stage)
        clock = time.monotonic()
        if stage != self._stage or clock - self._last_progress >= PROGRESS_INTERVAL:
            self._stage, self._last_progress = stage, clock
            jobs.append_event(
                self.directory, {"event": "progress", "stage": stage, "done": done, "total": total}
            )


def _revision(path: Path) -> str:
    return "sha256-" + hashlib.sha256(path.read_bytes()).hexdigest()


def _refuse(code: str, message: str) -> Exception:
    from ..errors import ProjectError, ValidationIssue

    return ProjectError((ValidationIssue("production", code, message),))


def _remove_staging(root: Path, target: Path) -> None:
    prefix = jobs.staging_prefix(target)
    if root.parent == target.parent and root.name.startswith(prefix) and not root.is_symlink():
        shutil.rmtree(root, ignore_errors=True)


def run(directory: Path, spec: jobs.JobSpec, limits: dict[str, object]) -> dict[str, object]:
    """Steps 2-6; returns the terminal event. Raises for failures and cancellation."""
    from ..identity import build_identity
    from ..project import load_project
    from .lock import production_lock
    from .produce import check_disjoint, produce

    target = Path(spec.release)
    project_path = Path(spec.project)
    reporter = Reporter(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    with production_lock(jobs.lock_path(target)) as lock:
        notes: list[str] = []
        if lock.recovered is not None:
            notes.append(f"Reclaimed an abandoned production lock ({lock.recovered.describe()}).")
        notes += release.recover(
            target, spec.book_id, jobs.staging_prefix(target), jobs.backup_prefix(target)
        )
        jobs.append_event(
            directory,
            {"event": "state", "state": "running", "limits": limits, "notes": notes},
            durable=True,
        )
        reporter.stop_if_requested("start")
        if _revision(project_path) != spec.revision:
            raise _refuse("source_changed", "Saved source changed after the job was requested.")
        project = load_project(project_path).project
        expected = build_identity(project)
        check_disjoint(target, [project_path.parent])
        root = Path(tempfile.mkdtemp(prefix=jobs.staging_prefix(target), dir=target.parent))
        try:
            staged = root / "release"
            with watching(reporter.checkpoint):
                result = produce(
                    project_path,
                    staged,
                    progress=reporter.step,
                    cancelled=reporter.requested,
                )
            reporter.step("release_verify")
            manifest = release.verify_release(staged)
            if manifest.get("build_identity") != expected or manifest.get("book_id") != (
                spec.book_id
            ):
                raise _refuse(
                    "source_changed", "The produced files are not those of the requested source."
                )
            reporter.step("release_swap")
            reporter.cancellable = False  # From here the verified release goes in.
            check_disjoint(target, [project_path.parent])
            release.swap_in(staged, target, jobs.backup_prefix(target))
            manifest = release.verify_release(target)
        finally:
            _remove_staging(root, target)
    outcome = "ready" if result.ready else "blocked"
    summary = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    data = (target / "production.json").read_bytes()
    return {
        "event": "state",
        "state": "completed",
        "outcome": outcome,
        "notes": notes + list(result.notes),
        "result": {
            **summary,  # type: ignore[dict-item]
            "files": len(result.files),
            "manifest_sha256": hashlib.sha256(data).hexdigest(),
            "peak_memory_mb": peak_memory_mb(),
        },
    }


def _failure(error: BaseException, limits: dict[str, object]) -> dict[str, object]:
    from ..cover.issues import CoverError
    from ..errors import ProjectError
    from ..interior import InteriorError

    if isinstance(error, (InteriorError, CoverError)):
        return {
            "code": error.stage,
            "message": f"Production stopped at {error.stage}.",
            "issues": [{"code": i.code, "message": i.message} for i in error.issues],
        }
    if isinstance(error, ProjectError):
        first = error.issues[0] if error.issues else None
        return {
            "code": first.code if first else "invalid_project",
            "message": first.message if first else "Production refused.",
            "issues": [{"code": i.code, "message": i.message} for i in error.issues],
        }
    if isinstance(error, MemoryError):
        return {
            "code": "memory_limit",
            "message": (
                f"The worker ran out of memory (limit {limits.get('memory_mb')} MB). Smaller "
                "or fewer drawings per run need less; the previous release is unchanged."
            ),
            "issues": [],
        }
    return {
        "code": "worker_error",
        "message": f"Production failed unexpectedly ({type(error).__name__}). See worker.log.",
        "issues": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m puzzlepress.production.worker")
    parser.add_argument("job", type=Path, help="The job directory Studio created.")
    args = parser.parse_args(argv)
    directory = args.job.resolve()
    try:
        spec = jobs.read_spec(directory)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Unusable job directory {directory}: {error}", file=sys.stderr)
        return EXIT_USAGE
    jobs.append_event(
        directory, {"event": "state", "state": "starting", "pid": os.getpid()}, durable=True
    )
    limits = apply_limits(spec.memory_limit_mb)
    try:
        final = run(directory, spec, limits)
    except BaseException as error:  # Every ending is recorded; tracebacks go to worker.log.
        from .produce import ProductionCancelled

        if isinstance(error, (Cancelled, ProductionCancelled)):
            stage = getattr(error, "stage", None) or getattr(error, "step", None)
            jobs.append_event(
                directory,
                {
                    "event": "state",
                    "state": "cancelled",
                    "error": {"code": "cancelled", "message": str(error), "stage": stage},
                },
                durable=True,
            )
            return EXIT_CANCELLED
        if not isinstance(error, Exception):  # KeyboardInterrupt, SystemExit
            jobs.append_event(
                directory,
                {
                    "event": "state",
                    "state": "interrupted",
                    "error": {
                        "code": "interrupted",
                        "message": f"Stopped by {type(error).__name__}.",
                    },
                },
                durable=True,
            )
            raise
        traceback.print_exc(file=sys.stderr)
        jobs.append_event(
            directory,
            {"event": "state", "state": "failed", "error": _failure(error, limits)},
            durable=True,
        )
        return EXIT_FAILED
    jobs.append_event(directory, final, durable=True)
    return EXIT_COMPLETED


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests.
    sys.exit(main())
