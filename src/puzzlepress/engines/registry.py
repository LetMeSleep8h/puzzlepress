"""The content engines this version can build, keyed by derived engine kind.

Only behavior that differs between engines goes through an engine: producing the
book's verified publication plan from its content, and presenting that plan.
Composition, print, cover, publishing and production stay shared and are not
part of this interface.

An engine's content is what its plan binds to: word search's generated batch
(`BatchReport`), or a coloring book's prepared drawings (`ColoringContent`).
Callers that need one engine's content narrow it explicitly; nothing treats one
engine's content as another's. Coloring books build interiors; their covers,
publishing metadata and packages are not available in this version.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeAlias

from .. import __version__
from ..batch import BatchReport
from ..errors import ProjectError, ValidationIssue
from ..models import Project
from ..publication import PublicationPlan, build_publication
from ..publication_verification import (
    PlanVerification,
    publication_payload,
    verify_publication_plan,
)
from ..validation import validate_project
from .kind import LABELS, SECTIONS, EngineKind

if TYPE_CHECKING:
    # Imported lazily at run time: coloring artwork reads share the cover asset
    # module, which imports the interior package that imports this registry.
    from ..coloring.content import ColoringContent

EngineContent: TypeAlias = "BatchReport | ColoringContent"


class ContentEngine(Protocol):
    @property
    def kind(self) -> EngineKind: ...

    @property
    def label(self) -> str:
        """Human name of the book type, for listings."""
        ...

    def build_publication(
        self, project: Project, source_directory: Path | None = None
    ) -> tuple[EngineContent, PublicationPlan]:
        """Produce or read the content and plan the book. Writes nothing.

        `source_directory` is the project folder, for engines whose content lives
        in files (coloring artwork); word search ignores it.
        """
        ...

    def verify_publication(
        self, plan: PublicationPlan, project: Project, content: EngineContent
    ) -> PlanVerification:
        """Independently check a plan against the source and content it came from."""
        ...

    def payload(
        self, content: EngineContent, plan: PublicationPlan, verification: PlanVerification
    ) -> dict[str, object]:
        """The verified plan and a content summary, as JSON-ready data."""
        ...


def _wrong_content(engine: EngineKind) -> TypeError:
    return TypeError(f"{engine.value} plans bind only to {engine.value} content")


@dataclass(frozen=True)
class WordSearchEngine:
    """Adapter over the existing word-search pipeline; it adds no behavior."""

    kind: EngineKind = EngineKind.WORD_SEARCH
    label: str = LABELS[EngineKind.WORD_SEARCH]

    def build_publication(
        self, project: Project, source_directory: Path | None = None
    ) -> tuple[BatchReport, PublicationPlan]:
        return build_publication(project)

    def verify_publication(
        self, plan: PublicationPlan, project: Project, content: EngineContent
    ) -> PlanVerification:
        if not isinstance(content, BatchReport):
            raise _wrong_content(self.kind)
        return verify_publication_plan(plan, project, content)

    def payload(
        self, content: EngineContent, plan: PublicationPlan, verification: PlanVerification
    ) -> dict[str, object]:
        if not isinstance(content, BatchReport):
            raise _wrong_content(self.kind)
        return publication_payload(content, plan, verification)


@dataclass(frozen=True)
class ColoringEngine:
    """Coloring books: prepared drawings in authored order, with explicit parity."""

    kind: EngineKind = EngineKind.COLORING
    label: str = LABELS[EngineKind.COLORING]

    def build_publication(
        self, project: Project, source_directory: Path | None = None
    ) -> tuple[ColoringContent, PublicationPlan]:
        from ..coloring.content import prepare_content
        from ..coloring.plan import plan_coloring, require_coloring_composition

        project = validate_project(project.to_dict()).require_project()
        require_coloring_composition(project)
        content = prepare_content(project, source_directory)
        return content, plan_coloring(project, content)

    def verify_publication(
        self, plan: PublicationPlan, project: Project, content: EngineContent
    ) -> PlanVerification:
        from ..coloring.content import ColoringContent
        from ..coloring.plan import verify_coloring_plan

        if not isinstance(content, ColoringContent):
            raise _wrong_content(self.kind)
        return verify_coloring_plan(plan, project, content)

    def payload(
        self, content: EngineContent, plan: PublicationPlan, verification: PlanVerification
    ) -> dict[str, object]:
        from ..coloring.content import ColoringContent

        if not isinstance(content, ColoringContent):
            raise _wrong_content(self.kind)
        return {
            "plan": plan.to_dict(),
            "verification": {
                "valid": verification.valid,
                "issues": [
                    {"path": i.path, "code": i.code, "message": i.message}
                    for i in verification.issues
                ],
            },
            "artwork": {
                "preparation_version": content.preparation_version,
                "prepared": [
                    {
                        "id": art.artwork.id,
                        "pixels": [art.width, art.height],
                        "bits": art.bits,
                        "prepared": art.digest,
                    }
                    for art in content.art.values()
                ],
                "failures": [
                    {"id": key, **error.to_dict()} for key, error in content.failures.items()
                ],
            },
        }


ENGINES: dict[EngineKind, ContentEngine] = {
    EngineKind.WORD_SEARCH: WordSearchEngine(),
    EngineKind.COLORING: ColoringEngine(),
}


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
                    f"PuzzlePress {__version__} cannot plan, build or package {label}s yet.",
                ),
            )
        )
    return engine


def word_search_publication(project: Project) -> tuple[BatchReport, PublicationPlan]:
    """Generation and plan of a word-search book, for word-search-only features."""
    engine = engine_for(project)
    if engine.kind is not EngineKind.WORD_SEARCH:
        raise ProjectError(
            (
                ValidationIssue(
                    SECTIONS[engine.kind],
                    "not_available_for_engine",
                    "This feature applies to word-search books only.",
                ),
            )
        )
    return build_publication(project)
