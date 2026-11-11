"""Assemble a book audit and serialize it. Reads only; writes nothing."""

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..batch import BatchReport
from ..engines.kind import EngineKind
from ..engines.registry import engine_for
from ..interior.spec import DEFAULT_PROFILE, PROFILES
from ..inventory import inventory_from_report
from ..models import Project
from ..planning import read_planning
from ..preflight import read_interior_artifacts
from ..preflight.context import parse_manifest
from ..production.guidance import overview as production_overview
from ..publication import PageKind, PublicationPlan
from .content import content_recommendations, level_facts
from .evidence import evidence_recommendations, manual_checks
from .listing import BookFacts, claims_progression, listing_recommendations
from .model import AuditReport, LevelFacts, Priority, Recommendation
from .pages import page_recommendations
from .series import OtherBook, series_recommendations

UNAVAILABLE = (
    "Sales, royalties, advertising, search ranking, customer reviews and competitor "
    "listings: PuzzlePress has no access to Amazon data and does not estimate them."
)


def _profile_id(project: Project, directory: Path) -> str:
    if project.printing is not None and project.printing.profile:
        return project.printing.profile
    manifest = read_interior_artifacts(directory).manifest
    if manifest is not None:
        parsed, _ = parse_manifest(manifest)
        profile = parsed.get("print_profile") if parsed else None
        built = profile.get("profile_id") if isinstance(profile, dict) else None
        if isinstance(built, str) and built in PROFILES:
            return built
    return DEFAULT_PROFILE


def puzzle_pages(plan: PublicationPlan) -> dict[str, int]:
    """Physical page (1-based) of each puzzle's grid."""
    return {
        page.puzzle.id: page.index
        for page in plan.pages
        if page.kind is PageKind.PUZZLE and page.puzzle is not None
    }


def theme_base(theme: str) -> str:
    """The theme before a level suffix: "Engines · Warm-up" -> "engines"."""
    return re.split(r"\s+[—–·|/-]\s+|:\s", theme, maxsplit=1)[0].strip().casefold()


def _facts(project: Project, plan: PublicationPlan) -> BookFacts:
    stats = plan.statistics
    ws = project.word_search
    if ws is None:
        return BookFacts(None, None, None, stats.divider_pages or None, stats.artwork_pages)
    return BookFacts(
        len(ws.puzzles),
        (len({p.theme for p in ws.puzzles}), len({theme_base(p.theme) for p in ws.puzzles})),
        len({p.difficulty for p in ws.puzzles}),
        stats.divider_pages or None,
        None,
    )


def audit_book(
    project: Project,
    source_directory: Path,
    output_directory: Path,
    others: Sequence[OtherBook] = (),
    overview: Mapping[str, object] | None = None,
) -> AuditReport:
    """Audit the saved source against its plan, built files and earlier books.

    `overview` may be passed when the caller already computed the production
    overview for these exact bytes (Studio caches it); it is never trusted otherwise.
    """
    engine = engine_for(project)
    content, plan = engine.build_publication(project, source_directory)
    pages = puzzle_pages(plan)
    planning = read_planning(source_directory).document
    found: list[Recommendation] = []
    not_assessed = [UNAVAILABLE]
    found += listing_recommendations(project, _facts(project, plan), planning)
    profile = PROFILES[_profile_id(project, output_directory)]
    found += page_recommendations(project, plan, profile.paper)
    levels: tuple[LevelFacts, ...] = ()
    inventory = None
    if engine.kind is EngineKind.WORD_SEARCH:
        assert isinstance(content, BatchReport)
        levels = level_facts(content)
        found += content_recommendations(content, pages, claims_progression(project))
        inventory = inventory_from_report(project, content, "book.yaml")
    else:
        not_assessed.append(
            "Coloring artwork quality, duplicates and placement are assessed by coloring "
            "preflight (see Print proof); this audit covers listing, print and evidence."
        )
    if others:
        series, unassessed = series_recommendations(project, inventory, others, pages)
        found += series
        not_assessed += unassessed
    else:
        not_assessed.append("Series: no earlier or sibling books were given to compare.")
    data = (
        overview
        if overview is not None
        else production_overview(project, source_directory, output_directory)
    )
    found += evidence_recommendations(data)
    ordered = tuple(sorted(found, key=Recommendation.sort_key))
    return AuditReport(
        project.book.id,
        engine.kind.value,
        project.book.title,
        len(plan.pages),
        ordered,
        manual_checks(project, data),
        levels,
        tuple(o.label for o in others),
        tuple(not_assessed),
    )


def audit_bytes(report: AuditReport) -> bytes:
    """Deterministic JSON: sorted keys, ASCII, two-space indent, trailing newline."""
    text = json.dumps(report.to_dict(), ensure_ascii=True, sort_keys=True, indent=2)
    return (text + "\n").encode("ascii")


PRIORITY_HEADINGS = {
    Priority.HIGH: "High priority",
    Priority.MEDIUM: "Medium priority",
    Priority.LOW: "Low priority",
}


def audit_markdown(report: AuditReport) -> str:
    lines = [
        f"# Book audit: {report.title}",
        "",
        f"Book `{report.book_id}` ({report.engine}), {report.page_count} pages. "
        + ", ".join(f"{n} {p}" for p, n in report.counts().items())
        + " priority recommendation(s).",
        "",
        report.statement,
        "",
    ]
    for priority, heading in PRIORITY_HEADINGS.items():
        items = [r for r in report.recommendations if r.priority is priority]
        lines += [f"## {heading} ({len(items)})", ""]
        if not items:
            lines += ["None.", ""]
        for r in items:
            where = []
            if r.field:
                where.append(f"field `{r.field}`")
            if r.pages:
                shown = ", ".join(str(p) for p in r.pages[:12])
                where.append(f"pages {shown}{', ...' if len(r.pages) > 12 else ''}")
            lines += [
                f"- **{r.title}** ({r.category.value}, {r.basis.value}, `{r.code}`)",
                f"  - Evidence: {r.evidence}",
                f"  - Action: {r.action}",
            ]
            if where:
                lines.append(f"  - Where: {'; '.join(where)} (Studio: {r.area})")
            if r.source:
                lines.append(f"  - Source: {r.source}")
        lines.append("")
    if report.levels:
        lines += [
            "## Difficulty by level",
            "",
            "| Level | Puzzles | Grids | Words | Directions | Diagonal words | Backward words "
            "| Longest |",
            "| --- | ---: | --- | --- | ---: | --- | --- | ---: |",
        ]
        for level in report.levels:
            lines.append(
                f"| {level.profile} | {len(level.puzzles)} | {', '.join(level.grids)} | "
                f"{level.words[0]}-{level.words[1]} | {level.allowed_directions} | "
                f"{level.placed_diagonal[0]}-{level.placed_diagonal[1]} | "
                f"{level.placed_backward[0]}-{level.placed_backward[1]} | {level.longest_word} |"
            )
        lines.append("")
    lines += ["## Manual checks (printed proof and judgment)", ""]
    for check in report.manual_checks:
        lines.append(f"- [{check.status}] {check.title}. {check.why}")
    lines += ["", "## Not assessed", ""]
    lines += [f"- {item}" for item in report.not_assessed]
    if report.compared_books:
        lines += ["", f"Compared with: {', '.join(report.compared_books)}."]
    return "\n".join(lines) + "\n"
