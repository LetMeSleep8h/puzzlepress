"""Studio adapter for the Planning workspace: status, draft checks, saves and approval.

Every decision is made by `puzzlepress.planning`, exactly as for `puzzlepress
plan`; this module locates the project's planning.yaml, maps expected failures
to HTTP errors and presents reports. The plan has its own byte revision, so a
planning save never changes book.yaml and never conflicts with a book draft.
Approval records the planning identity of the saved plan the author reviewed.
"""

from pathlib import Path

from puzzlepress.errors import ProjectError
from puzzlepress.interior.spec import PROFILES
from puzzlepress.models import Project
from puzzlepress.planning import (
    ApprovalError,
    PlanningDocument,
    PlanningWriteError,
    approve_plan,
    evaluate_plan,
    read_planning,
    validate_planning,
    withdraw_approval,
    write_planning,
)
from puzzlepress.planning.feasibility import SUPPORTED_PUZZLE_TYPES
from puzzlepress.planning.model import direction_name
from puzzlepress.planning.store import LoadedPlan
from puzzlepress.wordsearch import Direction

from .service import StudioError, StudioService

ERRORS = {
    "source_changed": 409,
    "save_failed": 503,
    "save_unconfirmed": 503,
    "identity_mismatch": 409,
    "not_ready": 409,
}


# Choices Python supports today, for Studio's selects (never a second rule set).
OPTIONS = {
    "print_profiles": [
        {"id": spec.profile_id, "description": spec.description}
        for spec in sorted(PROFILES.values(), key=lambda s: s.profile_id)
        if not spec.bleed
    ],
    "puzzle_types": list(SUPPORTED_PUZZLE_TYPES),
    "directions": [direction_name(d) for d in Direction],
}


class PlanningInvalid(ProjectError):
    """planning.yaml or a planning draft does not satisfy the planning schema."""


class PlanningService:
    def __init__(self, service: StudioService) -> None:
        self.store = service.store

    def _open(self, key: str) -> tuple[Project, Path, LoadedPlan]:
        project = self.store.load(key)  # The plan needs a valid book.yaml for its book ID.
        folder = self.store.source(key).parent
        try:
            return project, folder, read_planning(folder)
        except ProjectError as error:
            raise PlanningInvalid(error.issues) from error

    def _present(self, key: str, project: Project, plan: LoadedPlan) -> dict[str, object]:
        report = evaluate_plan(project, plan.document) if plan.document else None
        return {
            "key": key,
            "book": {"id": project.book.id, "title": project.book.title},
            "revision": plan.revision,
            "source": plan.document.to_dict() if plan.document else None,
            "report": report.to_dict() if report else None,
            "options": OPTIONS,
        }

    def status(self, key: str) -> dict[str, object]:
        project, _, plan = self._open(key)
        return self._present(key, project, plan)

    def draft(self, key: str, source: object) -> dict[str, object]:
        """Python's report for an unsaved plan. Writes nothing."""
        project = self.store.load(key)
        document = _validated(source)
        return {"report": evaluate_plan(project, document).to_dict()}

    def save(self, key: str, source: object, revision: str | None) -> dict[str, object]:
        """Replace planning.yaml if it is still at `revision` (None: create it)."""
        project, folder, _ = self._open(key)
        document = _validated(source)
        try:
            saved = write_planning(folder, document, revision)
        except PlanningWriteError as error:
            raise StudioError(ERRORS[error.code], error.code, str(error)) from error
        return self._present(key, project, saved)

    def approval(self, key: str, revision: str, identity: str | None) -> dict[str, object]:
        """Approve the saved plan at `revision` as `identity`, or withdraw (None)."""
        project, folder, plan = self._open(key)
        if plan.document is None or plan.revision != revision:
            raise StudioError(
                409, "source_changed", "The saved plan changed. Reload it before approving."
            )
        try:
            document = (
                withdraw_approval(plan.document)
                if identity is None
                else approve_plan(project, plan.document, identity)
            )
            saved = write_planning(folder, document, plan.revision)
        except (ApprovalError, PlanningWriteError) as error:
            raise StudioError(ERRORS[error.code], error.code, str(error)) from error
        return self._present(key, project, saved)


def _validated(source: object) -> PlanningDocument:
    document, issues = validate_planning(source)
    if document is None:
        raise PlanningInvalid(issues)
    return document
