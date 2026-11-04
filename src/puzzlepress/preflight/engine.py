"""Run every preflight rule over an interior and assemble a deterministic report.

Preflight observes: it reads artifact bytes, rebuilds the expected interior in
memory with the same pure pipeline as `book build`, and compares. It never
writes, repairs, pads, regroups or re-renders anything on disk.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ..engines.kind import EngineKind
from ..identity import build_identity
from ..interior.build import InteriorBuild, build_interior
from ..interior.design import resolve_design
from ..interior.inspection import PdfFacts, read_pdf_facts
from ..interior.issues import InteriorError, LayoutIssue
from ..interior.model import InteriorLayout
from ..interior.spec import PROFILES, PrintSpecification, to_inches
from ..models import Project
from ..publication import PublicationPlan
from .context import Context, InteriorArtifacts, parse_manifest
from .model import KDP_PAPERBACK, Finding, Outcome, PreflightReport, RuleResult, Ruleset
from .model import Rule as PreflightRule
from .rules import CATALOGUE, Evaluator


@dataclass(frozen=True)
class PreflightResult:
    report: PreflightReport
    # Present only when the PDF is byte-identical to the verified layout's render.
    layout: InteriorLayout | None
    plan: PublicationPlan | None


def _spec(manifest: dict[str, object] | None) -> PrintSpecification | None:
    if manifest is None:
        return None
    profile = manifest["print_profile"]
    assert isinstance(profile, dict)
    return PROFILES.get(str(profile.get("profile_id")))


def preflight_interior(
    project: Project,
    artifacts: InteriorArtifacts,
    expected: InteriorBuild | None = None,
    source_directory: Path | None = None,
) -> PreflightResult:
    """Inspect artifacts against the project. `expected` may reuse a fresh build.

    A supplied build is used only if it was produced from this project with the
    manifest's profile and style; otherwise the expected interior is rebuilt
    (reading the style's photographs from `source_directory`, the project folder).
    """
    source_identity = build_identity(project)
    manifest, manifest_problem = (
        parse_manifest(artifacts.manifest) if artifacts.manifest is not None else (None, None)
    )
    spec = _spec(manifest)
    build_error: InteriorError | None = None
    if spec is not None and not (
        expected is not None
        and expected.layout.spec == spec
        and expected.plan.identity == source_identity
        and expected.layout.design == resolve_design(project.interior)
    ):
        try:
            expected = build_interior(project, spec, source_directory)
        except InteriorError as error:
            expected, build_error = None, error
    elif spec is None:
        expected = None
    facts_or_issue: PdfFacts | LayoutIssue | None = None
    if artifacts.pdf is not None:
        # Facts are a function of the bytes alone: identical bytes reuse the fresh build's.
        same = expected is not None and expected.facts is not None and expected.pdf == artifacts.pdf
        facts_or_issue = expected.facts if same and expected else read_pdf_facts(artifacts.pdf)
    facts = None if isinstance(facts_or_issue, LayoutIssue) else facts_or_issue
    fields = {
        "project": project,
        "source_identity": source_identity,
        "artifacts": artifacts,
        "manifest": manifest,
        "manifest_problem": manifest_problem,
        "spec": spec,
        "facts": facts,
        "facts_problem": facts_or_issue if isinstance(facts_or_issue, LayoutIssue) else None,
        "expected": expected,
        "build_error": build_error,
    }
    catalogue: list[tuple[PreflightRule, Evaluator]] = CATALOGUE
    ruleset = KDP_PAPERBACK
    ctx: Context
    if project.engine is EngineKind.COLORING:
        from . import coloring

        checks = coloring.load_artwork(source_directory, project)
        from ..interior.coloring import embedded_images

        images = (
            embedded_images(artifacts.pdf)
            if artifacts.pdf is not None and facts is not None
            else None
        )
        ctx = coloring.ColoringContext(
            **fields,  # type: ignore[arg-type]
            artwork=checks,
            duplicates=coloring.duplicate_report(project, checks),
            images=images,
        )
        catalogue = coloring.COLORING_CATALOGUE
        ruleset = Ruleset(
            coloring.RULESET_ID, coloring.RULESET_VERSION, KDP_PAPERBACK.kdp_rules_checked
        )
    else:
        ctx = Context(**fields)  # type: ignore[arg-type]
    results: list[RuleResult] = []
    findings: list[Finding] = []
    for definition, evaluate in catalogue:
        check = evaluate(definition, ctx)
        outcome = check.outcome or (Outcome.FAILED if check.findings else Outcome.PASSED)
        results.append(
            RuleResult(
                definition,
                outcome,
                len(check.findings),
                None if outcome is Outcome.FAILED else check.note,
                check.measure,
            )
        )
        findings.extend(check.findings)
    report = PreflightReport(
        book_id=project.book.id,
        source_identity=source_identity,
        profile=_profile(spec),
        artifacts=_artifacts(ctx),
        page_count=facts.page_count if facts else None,
        pages=tuple(ctx.page(n) for n in range(1, facts.page_count + 1)) if facts else (),
        results=tuple(results),
        findings=tuple(sorted(findings, key=Finding.sort_key)),
        ruleset=ruleset,
    )
    return PreflightResult(report, ctx.layout, ctx.plan)


def ruleset_for(project: Project) -> tuple[str, int]:
    """(id, version) of the rule set that preflights this project's interior."""
    if project.engine is EngineKind.COLORING:
        from .coloring import RULESET_ID, RULESET_VERSION

        return RULESET_ID, RULESET_VERSION
    return KDP_PAPERBACK.id, KDP_PAPERBACK.version


def _profile(spec: PrintSpecification | None) -> dict[str, object] | None:
    if spec is None:
        return None
    return {
        "id": spec.profile_id,
        "version": spec.profile_version,
        "description": spec.description,
        "trim": {
            "name": spec.trim.name,
            "width_in": to_inches(spec.trim.width),
            "height_in": to_inches(spec.trim.height),
        },
        "bleed": spec.bleed,
    }


def _artifacts(ctx: Context) -> dict[str, object]:
    """Identify exactly which bytes were inspected, so the report cannot be misapplied."""
    pdf, manifest = ctx.artifacts.pdf, ctx.artifacts.manifest
    return {
        "pdf": None
        if pdf is None
        else {"sha256": hashlib.sha256(pdf).hexdigest(), "bytes": len(pdf)},
        "manifest": None
        if manifest is None
        else {"sha256": hashlib.sha256(manifest).hexdigest(), "bytes": len(manifest)},
        "interior_identity": ctx.manifest["interior_identity"] if ctx.manifest else None,
        "expected_interior_identity": ctx.expected.manifest["interior_identity"]
        if ctx.expected
        else None,
        "matches_layout": ctx.matches_layout,
    }
