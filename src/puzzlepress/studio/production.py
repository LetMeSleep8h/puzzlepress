"""Studio adapter for the production overview and dependency-aware rebuilds.

The overview and the assessment come from `puzzlepress.production`; this module
caches them by the bytes they depend on (saved source, every artifact, every
referenced photo, reviews.yaml and proofs.yaml) and serializes rebuilds with
other builds. A rebuild runs only for the saved revision the author confirmed
and stops before any write if the saved source changes during the run; the
result always reports the state recomputed afterwards, never a hoped-for one.
"""

import hashlib
from collections import OrderedDict
from pathlib import Path

from puzzlepress.interior import DEFAULT_PROFILE, InteriorError
from puzzlepress.interior.build import check_output_directory
from puzzlepress.interior.spec import PROFILES
from puzzlepress.models import Project
from puzzlepress.preflight import read_interior_artifacts
from puzzlepress.production.artifacts import assess
from puzzlepress.production.guidance import overview
from puzzlepress.production.rebuild import SourceChanged, rebuild
from puzzlepress.project import resolve_output_directory
from puzzlepress.publishing import evaluate_readiness

from .printing import _built_profile
from .service import StudioError, StudioService

LOCK_WAIT = 60.0
WATCHED = (
    "interior.pdf",
    "interior.json",
    "preflight.json",
    "cover.pdf",
    "cover.json",
    "cover-preflight.json",
    "publishing/package.json",
)


def _digest(path: Path) -> str:
    try:
        if path.is_file() and not path.is_symlink():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "?"
    return "-"


class ProductionService:
    def __init__(self, service: StudioService) -> None:
        self.service = service
        self.store = service.store
        self._cache: OrderedDict[tuple[str, ...], dict[str, object]] = OrderedDict()

    def _folders(self, key: str, project: Project) -> tuple[Path, Path]:
        source = self.store.source(key).parent
        try:
            directory = check_output_directory(resolve_output_directory(project, source), source)
        except InteriorError as error:
            raise StudioError(
                503, "output_unavailable", "The project's output directory is unavailable."
            ) from error
        return source, directory

    def _key(
        self, key: str, revision: str, project: Project, source: Path, directory: Path
    ) -> tuple[str, ...]:
        photos = []
        if project.cover is not None:
            photos += [source / image.path for image in project.cover.images()]
        if project.interior is not None:
            photos += [source / image.path for image in project.interior.images()]
        return (
            key,
            revision,
            *(_digest(directory / name) for name in WATCHED),
            *(_digest(path) for path in photos),
            _digest(source / "reviews.yaml"),
            _digest(source / "proofs.yaml"),
            _digest(source / "planning.yaml"),
        )

    def status(self, key: str) -> dict[str, object]:
        with self.service.exclusive(wait=LOCK_WAIT):
            return self._status(key)

    def _status(self, key: str) -> dict[str, object]:
        project, revision = self.store.snapshot(key)
        source, directory = self._folders(key, project)
        cache_key = self._key(key, revision, project, source, directory)
        cached = self._cache.get(cache_key)
        if cached is None:
            cached = overview(project, source, directory)
            self._cache[cache_key] = cached
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
        return {"key": key, "revision": revision, **cached}

    def rebuild(self, key: str, revision: str) -> dict[str, object]:
        """Rebuild every outdated artifact of the saved source exactly at `revision`."""
        with self.service.exclusive(wait=LOCK_WAIT):
            project, current = self.store.snapshot(key)
            if current != revision:
                raise StudioError(
                    409, "source_changed", "Saved source changed. Reload before rebuilding."
                )
            source, directory = self._folders(key, project)
            assessment = assess(
                project, evaluate_readiness(project, source, directory), source, directory
            )
            profile = (project.printing.profile if project.printing else None) or _built_profile(
                read_interior_artifacts(directory).manifest
            )
            spec = PROFILES[profile or DEFAULT_PROFILE]

            def unchanged() -> None:
                if self.store.snapshot(key)[1] != revision:
                    raise SourceChanged

            try:
                results = rebuild(
                    project,
                    source,
                    directory,
                    spec,
                    tuple(step.action for step in assessment.steps),
                    unchanged,
                )
                outcome: dict[str, object] = {
                    "success": all(r.status != "failed" for r in results),
                    "results": [r.to_dict() for r in results],
                }
            except SourceChanged as error:
                done = len(error.completed)
                outcome = {
                    "success": False,
                    "code": "source_changed",
                    "message": f"The saved source changed during the rebuild. {done} earlier "
                    "step(s) finished; it stopped before writing anything else. Review the "
                    "change, then rebuild again.",
                    "results": [r.to_dict() for r in error.completed],
                }
            return {"rebuild": outcome, **self._status(key)}
