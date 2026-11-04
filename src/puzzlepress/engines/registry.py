"""The content engines this version can build, keyed by derived engine kind.

Only behavior that differs between engines goes through an engine: producing the
book's verified publication plan from its content. Composition, print, cover,
publishing and production stay shared and are not part of this interface.

A kind that loads but has no entry here (coloring, in this version) is reported as
not buildable by `engine_for`, so no command claims to plan, build or package it.
"""

from dataclasses import dataclass
from typing import Protocol

from .. import __version__
from ..batch import BatchReport
from ..errors import ProjectError, ValidationIssue
from ..models import Project
from ..publication import PublicationPlan, build_publication
from ..publication_verification import PlanVerification, verify_publication_plan
from .kind import LABELS, SECTIONS, EngineKind


class ContentEngine(Protocol):
    @property
    def kind(self) -> EngineKind: ...

    @property
    def label(self) -> str:
        """Human name of the book type, for listings."""
        ...

    def build_publication(self, project: Project) -> tuple[BatchReport, PublicationPlan]:
        """Generate or read the content and plan the book. Writes nothing."""
        ...

    def verify_publication(
        self, plan: PublicationPlan, project: Project, report: BatchReport
    ) -> PlanVerification:
        """Independently check a plan against the source and content it came from."""
        ...


@dataclass(frozen=True)
class WordSearchEngine:
    """Adapter over the existing word-search pipeline; it adds no behavior."""

    kind: EngineKind = EngineKind.WORD_SEARCH
    label: str = LABELS[EngineKind.WORD_SEARCH]

    def build_publication(self, project: Project) -> tuple[BatchReport, PublicationPlan]:
        return build_publication(project)

    def verify_publication(
        self, plan: PublicationPlan, project: Project, report: BatchReport
    ) -> PlanVerification:
        return verify_publication_plan(plan, project, report)


ENGINES: dict[EngineKind, ContentEngine] = {EngineKind.WORD_SEARCH: WordSearchEngine()}


def engine_for(project: Project) -> ContentEngine:
    """The engine that plans and builds this project, or an expected error."""
    engine = ENGINES.get(project.engine)
    if engine is None:
        label = LABELS[project.engine].lower()
        raise ProjectError(
            (
                ValidationIssue(
                    SECTIONS[project.engine],
                    "engine_not_buildable",
                    f"PuzzlePress {__version__} can validate this {label} and manage its "
                    f"artwork, but cannot plan, build or package {label}s yet.",
                ),
            )
        )
    return engine
