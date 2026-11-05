"""Production jobs on disk: what was asked, what the worker reported, and what is left.

Each job is a directory under `.<release>.jobs/` beside the release it writes:

    <job-id>/job.json      the request (written once by Studio, exclusively)
    <job-id>/events.jsonl  one JSON object per line, appended by the worker
    <job-id>/cancel        present once cancellation was requested
    <job-id>/worker.log    the worker's standard error (tracebacks of failures)

Job IDs are a UTC timestamp and a random suffix, so they sort by creation and never
repeat. The event log is append-only: a reader folds it line by line and ignores a
last line that is still being written, so no reader ever sees a half-replaced file
(Windows refuses to replace a file another process is reading). Only one process
appends to a log at a time: the worker while it lives; Studio only once the worker
is known to be gone (its process exited, or the release lock is free), to record
that it was interrupted.

States: queued (no worker yet), starting (the worker is up, not yet holding the
lock), running, cancelling (running with a cancel request), and the terminal
states completed, failed, cancelled and interrupted. `completed` carries the
outcome `ready` or `blocked` (finished, but with blocking findings).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

JOB_VERSION = 1
SPEC_NAME = "job.json"
EVENTS_NAME = "events.jsonl"
CANCEL_NAME = "cancel"
LOG_NAME = "worker.log"
TERMINAL = frozenset({"completed", "failed", "cancelled", "interrupted"})
STATES = ("queued", "starting", "running", "cancelling", *sorted(TERMINAL))
KEEP_JOBS = 10  # Finished jobs kept per release; older ones are removed.
_JOB_ID = re.compile(r"^\d{8}T\d{6}\d{6}Z-[0-9a-f]{8}$")
_EVENT_LIMIT = 4 * 1024 * 1024  # A log larger than this is not a job's (progress is throttled).


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def jobs_directory(release: Path) -> Path:
    return release.parent / f".{release.name}.jobs"


def staging_prefix(release: Path) -> str:
    return f".{release.name}.job-staging-"


def backup_prefix(release: Path) -> str:
    return f".{release.name}.job-previous-"


def lock_path(release: Path) -> Path:
    """The same lock `book produce` takes for this output: one writer, CLI or Studio."""
    return release.parent / f".{release.name}.produce.lock"


def new_job_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(4)


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    key: str
    book_id: str
    engine: str
    project: str  # The book.yaml the job reads.
    revision: str  # `sha256-` of book.yaml's bytes when the job was requested.
    release: str  # The release directory the job replaces.
    created: str
    memory_limit_mb: int | None = None
    previous_release: str | None = None  # SHA-256 of the release's production.json then.
    lower_priority: bool = False  # Run below normal priority (Studio --worker-priority low).

    def to_dict(self) -> dict[str, object]:
        return {
            "job_version": JOB_VERSION,
            "job_id": self.job_id,
            "key": self.key,
            "book_id": self.book_id,
            "engine": self.engine,
            "project": self.project,
            "revision": self.revision,
            "release": self.release,
            "created": self.created,
            "memory_limit_mb": self.memory_limit_mb,
            "previous_release": self.previous_release,
            "lower_priority": self.lower_priority,
        }

    @staticmethod
    def from_dict(data: object) -> JobSpec:
        if not isinstance(data, dict) or data.get("job_version") != JOB_VERSION:
            raise ValueError("not a job record of this version")
        limit = data.get("memory_limit_mb")
        previous = data.get("previous_release")
        return JobSpec(
            str(data["job_id"]),
            str(data["key"]),
            str(data["book_id"]),
            str(data["engine"]),
            str(data["project"]),
            str(data["revision"]),
            str(data["release"]),
            str(data["created"]),
            int(limit) if isinstance(limit, int) else None,
            str(previous) if isinstance(previous, str) else None,
            # Interval 8 records lack the field; their workers ran below normal.
            data.get("lower_priority", True) is True,
        )


def create_job(spec: JobSpec) -> Path:
    """Write a new job's request; refuses an existing job directory."""
    root = jobs_directory(Path(spec.release))
    root.mkdir(parents=True, exist_ok=True)
    directory = root / spec.job_id
    directory.mkdir()
    staged = directory / f".{SPEC_NAME}.tmp"
    with open(staged, "x", encoding="utf-8") as stream:
        json.dump(spec.to_dict(), stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staged, directory / SPEC_NAME)
    return directory


def read_spec(directory: Path) -> JobSpec:
    return JobSpec.from_dict(json.loads((directory / SPEC_NAME).read_text(encoding="utf-8")))


def append_event(directory: Path, event: dict[str, object], durable: bool = False) -> None:
    """Append one event; `durable` events (states) are flushed to disk before returning."""
    line = json.dumps({"at": now(), **event}, sort_keys=True, separators=(",", ":")) + "\n"
    with open(directory / EVENTS_NAME, "a", encoding="utf-8", newline="\n") as stream:
        stream.write(line)
        stream.flush()
        if durable:
            os.fsync(stream.fileno())


def request_cancel(directory: Path) -> None:
    (directory / CANCEL_NAME).touch(exist_ok=True)


def cancel_requested(directory: Path) -> bool:
    return (directory / CANCEL_NAME).exists()


@dataclass(frozen=True)
class JobView:
    """A job as its request and event log describe it."""

    directory: Path
    spec: JobSpec
    seq: int  # Events folded; grows with every report, so newer views compare greater.
    state: str
    outcome: str | None = None  # completed: ready | blocked
    step: str | None = None
    steps: tuple[str, ...] = ()
    progress: dict[str, object] | None = None  # {stage, done, total} of the current step.
    pid: int | None = None
    started: str | None = None
    finished: str | None = None
    last_event: str | None = None
    error: dict[str, object] | None = None
    result: dict[str, object] | None = None
    notes: tuple[str, ...] = ()
    limits: dict[str, object] = field(default_factory=dict)
    cancel_requested: bool = False

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL

    def to_dict(self) -> dict[str, object]:
        state = "cancelling" if self.state == "running" and self.cancel_requested else self.state
        return {
            "job_id": self.spec.job_id,
            "seq": self.seq,
            "state": state,
            "outcome": self.outcome,
            "revision": self.spec.revision,
            "engine": self.spec.engine,
            "created": self.spec.created,
            "started": self.started,
            "finished": self.finished,
            "step": self.step,
            "steps": list(self.steps),
            "progress": self.progress,
            "pid": self.pid,
            "error": self.error,
            "result": self.result,
            "notes": list(self.notes),
            "limits": self.limits,
            "cancel_requested": self.cancel_requested,
        }


def _events(directory: Path) -> list[dict[str, object]]:
    path = directory / EVENTS_NAME
    try:
        if path.stat().st_size > _EVENT_LIMIT:
            raise ValueError(f"{path} is larger than a job's event log")
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    events: list[dict[str, object]] = []
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            break  # The last line is still being written; earlier lines are complete.
        if isinstance(event, dict):
            events.append(event)
    return events


def read_job(directory: Path) -> JobView:
    """Fold a job's request and events. Raises OSError/ValueError for a damaged job."""
    spec = read_spec(directory)
    state, outcome, step = "queued", None, None
    steps: list[str] = []
    progress: dict[str, object] | None = None
    pid: int | None = None
    started = finished = last = None
    error: dict[str, object] | None = None
    result: dict[str, object] | None = None
    notes: tuple[str, ...] = ()
    limits: dict[str, object] = {}
    events = _events(directory)
    for event in events:
        last = str(event.get("at")) if event.get("at") else last
        kind = event.get("event")
        if kind == "state" and event.get("state") in STATES:
            if state in TERMINAL:
                continue  # A terminal state is final; nothing later overrides it.
            state = str(event["state"])
            if state == "starting" and isinstance(event.get("pid"), int):
                pid = int(event["pid"])  # type: ignore[call-overload]
            if state == "running":
                started = last
                if isinstance(event.get("limits"), dict):
                    limits = event["limits"]  # type: ignore[assignment]
            listed = event.get("notes")
            if isinstance(listed, list):
                notes = tuple(str(n) for n in listed)
            if state in TERMINAL:
                finished = last
                progress = None
                outcome = str(event["outcome"]) if event.get("outcome") else None
                error = event.get("error") if isinstance(event.get("error"), dict) else None  # type: ignore[assignment]
                result = event.get("result") if isinstance(event.get("result"), dict) else None  # type: ignore[assignment]
        elif kind == "step" and state not in TERMINAL and isinstance(event.get("step"), str):
            step = str(event["step"])
            steps.append(step)
            progress = None
        elif kind == "progress" and state not in TERMINAL:
            progress = {
                "stage": event.get("stage"),
                "done": event.get("done"),
                "total": event.get("total"),
            }
    return JobView(
        directory,
        spec,
        len(events),
        state,
        outcome,
        step,
        tuple(steps),
        progress,
        pid,
        started,
        finished,
        last,
        error,
        result,
        notes,
        limits,
        cancel_requested(directory),
    )


def job_directories(release: Path) -> list[Path]:
    """This release's job directories, oldest first (only well-formed job IDs)."""
    root = jobs_directory(release)
    if not root.is_dir() or root.is_symlink():
        return []
    return sorted(
        p for p in root.iterdir() if _JOB_ID.match(p.name) and p.is_dir() and not p.is_symlink()
    )


def prune(release: Path, keep: int = KEEP_JOBS) -> None:
    """Remove the oldest finished jobs beyond `keep` (never an unfinished one)."""
    finished: list[Path] = []
    for directory in job_directories(release):
        try:
            if read_job(directory).terminal:
                finished.append(directory)
        except (OSError, ValueError, KeyError, TypeError):
            continue  # Damaged records are left for a person to look at.
    root = jobs_directory(release)
    for directory in finished[:-keep] if keep else finished:
        if directory.parent == root and not directory.is_symlink():
            shutil.rmtree(directory, ignore_errors=True)
