"""Read-only, root-scoped project access and presentation of core reports."""

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

from puzzlepress import __version__
from puzzlepress.batch import generate_batch
from puzzlepress.engines.kind import LABELS
from puzzlepress.engines.registry import engine_for
from puzzlepress.errors import ProjectError, ValidationIssue
from puzzlepress.identity import build_identity
from puzzlepress.models import Project
from puzzlepress.project import resolve_output_directory
from puzzlepress.wordsearch import verify_word_search
from puzzlepress.yaml_io import parse_project


class StudioError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        super().__init__(message)


def issue_dicts(error: ProjectError) -> list[dict[str, object]]:
    # Filesystem failures may contain absolute paths; keep those in server diagnostics.
    return [
        asdict(ValidationIssue(issue.path, issue.code, "Cannot read project source."))
        if issue.code in {"io", "not_found", "not_directory"}
        else asdict(issue)
        for issue in error.issues
    ]


@dataclass(frozen=True)
class ProjectStore:
    root: Path

    def source(self, key: str) -> Path:
        # Keys identify immediate folders, independently of authored book IDs.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", key):
            raise StudioError(404, "project_not_found", "Project not found in the book library.")
        try:
            root = self.root.resolve()
            folder = root / key
            source = folder / "book.yaml"
            resolved_folder = folder.resolve()
            resolved_source = source.resolve()
            if (
                resolved_folder.parent != root
                or resolved_source.parent != resolved_folder
                or folder.is_symlink()
                or source.is_symlink()
            ):
                raise StudioError(404, "project_not_found", "Project is outside the book library.")
            if not resolved_source.is_file():
                raise StudioError(
                    404, "project_not_found", "Project not found in the book library."
                )
            return resolved_source
        except (OSError, RuntimeError, ValueError) as error:
            raise StudioError(503, "source_unavailable", "Cannot access project source.") from error

    def load(self, key: str) -> Project:
        return self.snapshot(key)[0]

    def snapshot(self, key: str) -> tuple[Project, str]:
        path = self.source(key)
        try:
            raw = path.read_bytes()
            project = parse_project(raw.decode("utf-8-sig"))
        except (OSError, UnicodeError) as error:
            raise ProjectError(
                (ValidationIssue("source", "io", "Cannot read project source."),)
            ) from error
        resolve_output_directory(project, path.parent)
        return project, "sha256-" + hashlib.sha256(raw).hexdigest()

    def detail(self, key: str) -> dict[str, object]:
        project, revision = self.snapshot(key)
        return project_detail(key, project, revision)

    def discover(self) -> list[dict[str, object]]:
        if not self.root.exists():
            raise StudioError(
                503, "library_unavailable", "The configured books directory is missing."
            )
        try:
            keys = sorted(p.name for p in self.root.iterdir() if p.is_dir())
        except OSError as error:
            raise StudioError(
                503, "library_unavailable", "Cannot read the books directory."
            ) from error
        projects: list[dict[str, object]] = []
        for key in keys:
            try:
                projects.append(self.detail(key))
            except StudioError as error:
                if error.status != 404:
                    raise
            except ProjectError as error:
                projects.append(
                    {"key": key, "validation": {"valid": False, "issues": issue_dicts(error)}}
                )
        return projects


def engine_summary(project: Project) -> dict[str, str]:
    """The derived book type, named by the engine that builds it."""
    return {"kind": project.engine.value, "label": LABELS[project.engine]}


def project_detail(key: str, project: Project, revision: str | None = None) -> dict[str, object]:
    source = project.to_dict()
    source["build"] = {"seed": str(project.build.seed)}
    return {
        "key": key,
        "revision": revision,
        "source": source,
        "identity": build_identity(project),
        "engine_version": __version__,
        "engine": engine_summary(project),
        "validation": {"valid": True, "issues": []},
    }


class StudioService:
    """Serialize expensive requests; never cache stale authored source or write it."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self._generation_lock = Lock()

    def generate(self, key: str, identity: str) -> dict[str, object]:
        project = self.store.load(key)
        if build_identity(project) != identity:
            raise StudioError(
                409, "source_changed", "Source changed. Reload the project before generating."
            )
        return self.generate_project(project)

    @contextmanager
    def exclusive(self, wait: float = 0) -> Iterator[None]:
        """Run alone. Drafts fail fast when busy; print reads may `wait` seconds."""
        acquired = (
            self._generation_lock.acquire(timeout=wait)
            if wait > 0
            else self._generation_lock.acquire(blocking=False)
        )
        if not acquired:
            raise StudioError(409, "generation_busy", "Generation is running. Try again shortly.")
        try:
            yield
        finally:
            self._generation_lock.release()

    def plan_project(self, project: Project, source: Path | None = None) -> dict[str, object]:
        """Generate (or prepare) and plan the given source; the verified plan is the result.

        `source` is the project folder, where a coloring book's artwork lives.
        """
        with self.exclusive():
            if project.composition is None:
                raise StudioError(422, "no_composition", "This project has no book composition.")
            engine = engine_for(project)
            content, plan = engine.build_publication(project, source)
            verification = engine.verify_publication(plan, project, content)
            if not verification.valid:
                raise RuntimeError(f"Publication plan failed verification: {verification.issues!r}")
            return engine.payload(content, plan, verification)

    def generate_project(self, project: Project) -> dict[str, object]:
        with self.exclusive():
            if project.word_search is None:
                raise StudioError(422, "no_puzzles", "This project has no word-search definitions.")
            report = generate_batch(project)
            verification: dict[str, object] = {}
            for result in report.puzzles:
                if result.puzzle is None:
                    verification[result.id] = None
                else:
                    checked = verify_word_search(result.puzzle)
                    verification[result.id] = {"valid": checked.valid, **asdict(checked)}
            # Keep the CLI report intact; add independently verified web presentation data.
            return {
                "report": report.to_dict(),
                "verification": verification,
                "solution_cells": {
                    result.id: {
                        placement.target_id: [asdict(cell) for cell in placement.coordinates]
                        for placement in result.puzzle.solution.placements
                    }
                    for result in report.puzzles
                    if result.puzzle
                },
            }
