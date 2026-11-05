"""Studio adapter for `book produce`: start a run, follow it, read what it made.

The run is `puzzlepress.production.produce.produce`, unchanged: the same lock, the
same staging and verification, the same files as the CLI. Studio adds only:

- a background thread, so the browser can show the current step;
- the output folder, `<output.directory>-release` beside the build folder;
- a check before reporting success: every file `production.json` lists is read back
  and compared with its recorded SHA-256 and size. A run whose files do not match is
  reported as failed, never as complete;
- cancellation for coloring books only (staged; the previous release survives).
  Word-search production writes in place, so it is never cancelled midway.

A run belongs to the saved revision it started from: a different revision is
refused, and the release is reported as out of date once the source's build
identity differs from the one the release recorded.
"""

import hashlib
import json
import logging
import threading
import time
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from puzzlepress.errors import ProjectError
from puzzlepress.identity import build_identity
from puzzlepress.models import Project
from puzzlepress.project import load_project, resolve_output_directory

from .service import StudioError, StudioService, issue_dicts

LOGGER = logging.getLogger(__name__)
MANIFEST = "production.json"
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
    "swap": "Putting the release in place",
}


@dataclass
class Run:
    key: str
    revision: str
    cancellable: bool
    state: str = "running"  # running | complete | blocked | cancelled | failed
    step: str | None = None
    steps: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    error: dict[str, object] | None = None
    notes: list[str] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict[str, object]:
        end = self.finished if self.finished is not None else time.monotonic()
        return {
            "state": self.state,
            "revision": self.revision,
            "step": self.step,
            "step_label": STEP_LABELS.get(self.step or "", self.step),
            "steps": self.steps,
            "seconds": round(end - self.started, 1),
            "cancellable": self.cancellable and self.state == "running",
            "cancel_requested": self.cancel.is_set(),
            "error": self.error,
            "notes": self.notes,
        }


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


class ProducingService:
    def __init__(self, service: StudioService) -> None:
        self.service = service
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()
        # The release as checked when a run started, by book: while that run is active
        # the release on disk cannot change (a run only swaps at its very end), so the
        # browser's once-a-second polls reuse this instead of re-hashing every file.
        self._release_at_start: dict[str, dict[str, object] | None] = {}

    def _locate(self, key: str) -> tuple[Project, str, Path, Path]:
        project, revision = self.service.store.snapshot(key)
        source = self.service.store.source(key).parent
        try:
            directory = release_directory(project, source)
        except ProjectError as error:
            raise StudioError(
                503, "output_unavailable", "The output folder is unavailable."
            ) from error
        return project, revision, source, directory

    def status(self, key: str) -> dict[str, object]:
        project, revision, _, directory = self._locate(key)
        with self._lock:
            run = self._runs.get(key)
            if run is not None and run.state == "running" and key in self._release_at_start:
                cached = self._release_at_start[key]
                return self._presented(key, project, revision, directory, run, cached)
        release = self._release(project, directory)
        with self._lock:
            if run is not None and run.state == "running":
                self._release_at_start[key] = release
            else:
                self._release_at_start.pop(key, None)
        return self._presented(key, project, revision, directory, run, release)

    def _presented(
        self,
        key: str,
        project: Project,
        revision: str,
        directory: Path,
        run: "Run | None",
        release: dict[str, object] | None,
    ) -> dict[str, object]:
        if release is not None and "build_identity" in release:
            # Stale is about the saved source now, so it is never taken from a cache.
            release = {**release, "stale": release["build_identity"] != build_identity(project)}
        return {
            "key": key,
            "revision": revision,
            "directory": directory.name,
            "cancellable": project.coloring is not None,
            "run": run.to_dict() if run else None,
            "release": release,
        }

    def _release(self, project: Project, directory: Path) -> dict[str, object] | None:
        manifest, problem = verified_release(directory)
        release: dict[str, object] | None = None
        if manifest is not None:
            result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
            recorded = manifest.get("build_identity")
            release = {
                "verified": problem is None,
                "problem": problem,
                "engine": manifest.get("engine", "word_search"),
                "result": result,
                "build_identity": recorded,
                "stale": recorded != build_identity(project),
                "files": [
                    {"name": f["name"], "bytes": f["bytes"], "sha256": f["sha256"]}
                    for f in listed(manifest)
                ],
                "validation": self._validation(directory) if problem is None else None,
                "package": (directory / "publishing" / "package.json").is_file(),
            }
        elif problem is not None:
            release = {"verified": False, "problem": problem, "files": []}
        return release

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
        with self._lock:
            active = self._runs.get(key)
            if active is not None and active.state == "running":
                raise StudioError(
                    409, "production_in_progress", "A production run for this book is active."
                )
            run = Run(key, revision, cancellable=project.coloring is not None)
            self._runs[key] = run
        thread = threading.Thread(
            target=self._produce, args=(run, source, directory), daemon=True, name=f"produce-{key}"
        )
        thread.start()
        return self.status(key)

    def cancel(self, key: str) -> dict[str, object]:
        with self._lock:
            run = self._runs.get(key)
        if run is None or run.state != "running":
            raise StudioError(409, "no_active_run", "No production run is active.")
        if not run.cancellable:
            raise StudioError(
                409,
                "not_cancellable",
                "Word-search production writes in place and cannot stop safely midway; "
                "it finishes on its own.",
            )
        run.cancel.set()
        return self.status(key)

    def _produce(self, run: Run, source: Path, directory: Path) -> None:
        from puzzlepress.cover.issues import CoverError
        from puzzlepress.interior import InteriorError
        from puzzlepress.production.produce import ProductionCancelled, produce

        def progress(step: str) -> None:
            run.step = step
            run.steps.append(step)

        try:
            # The run reads book.yaml itself; refuse it if the source moved on since start.
            if self.service.store.snapshot(run.key)[1] != run.revision:
                raise StudioError(409, "source_changed", "Saved source changed before the run.")
            loaded_check = load_project(source)
            result = produce(
                loaded_check.source_path,
                directory,
                progress=progress,
                cancelled=run.cancel.is_set if run.cancellable else None,
            )
            run.notes = list(result.notes)
            _, problem = verified_release(result.directory)
            if problem is not None:
                run.state = "failed"
                run.error = {"code": "verification_failed", "message": problem, "issues": []}
            else:
                run.state = "complete" if result.ready else "blocked"
        except ProductionCancelled as cancelled:
            run.state = "cancelled"
            run.error = {"code": "cancelled", "message": str(cancelled), "issues": []}
        except (InteriorError, CoverError) as error:
            run.state = "failed"
            run.error = {
                "code": error.stage,
                "message": f"Production stopped at {error.stage}.",
                "issues": [{"code": i.code, "message": i.message} for i in error.issues],
            }
        except ProjectError as error:
            run.state = "failed"
            run.error = {
                "code": error.issues[0].code if error.issues else "invalid_project",
                "message": error.issues[0].message if error.issues else "Production refused.",
                "issues": issue_dicts(error),
            }
        except StudioError as error:
            run.state = "failed"
            run.error = {"code": error.code, "message": str(error), "issues": []}
        except Exception:  # Reported, logged with its traceback, never shown as success.
            LOGGER.exception("Production run failed")
            run.state = "failed"
            run.error = {
                "code": "server_error",
                "message": "Production failed unexpectedly. See the server log.",
                "issues": [],
            }
        finally:
            run.finished = time.monotonic()

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
