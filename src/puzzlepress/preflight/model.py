"""Immutable preflight vocabulary: rules, findings, rule outcomes and the report.

A finding is an observation about an existing artifact. Nothing here can
change a plan, layout, PDF or manifest; the report only describes them.
"""

import json
from dataclasses import dataclass
from enum import StrEnum

from ..interior.model import Box

# Report layout version, and the version of the rule set whose verdicts it holds.
REPORT_VERSION = 1
RULESET_ID = "puzzlepress-kdp-paperback"
# 2: live-area containment is the structural `content_in_live_area` rule;
# `kdp_no_printer_marks` judges only the area beyond the trim.
# 3: styled photographs: `raster_images` accepts the layout's own images and
# `kdp_image_resolution` measures their effective DPI from the verified layout.
# 4: `design_legibility` warns about cramped solution letters, light accent text,
# low-contrast banners and heavy ink the verified layout reports.
RULESET_VERSION = 4
KDP_RULES_CHECKED = "2026-10-07"


class Severity(StrEnum):
    ERROR = "error"  # Blocks the status of its scope.
    WARNING = "warning"
    INFO = "info"  # Never blocks. The coloring ruleset uses it for manual-review prompts.


@dataclass(frozen=True)
class Ruleset:
    """Which rule set a report's verdicts come from."""

    id: str
    version: int
    kdp_rules_checked: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "version": self.version, "kdp_rules_checked": self.kdp_rules_checked}


KDP_PAPERBACK = Ruleset(RULESET_ID, RULESET_VERSION, KDP_RULES_CHECKED)


class Scope(StrEnum):
    STRUCTURAL = "structural"  # Is the artifact coherent with its authoritative inputs?
    KDP = "kdp"  # Does it meet the KDP constraints PuzzlePress models?


class Category(StrEnum):
    ARTIFACT = "artifact"
    INTEGRITY = "integrity"
    PAGE = "page"
    GEOMETRY = "geometry"
    TYPOGRAPHY = "typography"
    FONT = "font"
    CONTENT = "content"


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    NOT_EVALUATED = "not_evaluated"  # A prerequisite failed; never counted as passing.


class Basis(StrEnum):
    """Where a rule's value comes from (see docs/preflight.md)."""

    KDP_REQUIREMENT = "kdp_requirement"
    KDP_AMBIGUOUS = "kdp_ambiguous"  # Official wording conflicts or is incomplete.
    PUZZLEPRESS_CONTRACT = "puzzlepress_contract"


@dataclass(frozen=True)
class Rule:
    code: str
    scope: Scope
    category: Category
    severity: Severity  # Severity of this rule's findings.
    title: str
    description: str
    basis: Basis
    source: str  # Official KDP help page title, or the PuzzlePress contract.

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "scope": self.scope.value,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "basis": self.basis.value,
            "source": self.source,
            "help": "docs/preflight.md#rule-catalogue",
        }


Value = int | float | str


@dataclass(frozen=True)
class Measure:
    """A measured value against a requirement, in one unit."""

    actual: Value
    required: Value | None = None
    unit: str | None = None  # "in", "pt", "pages", "dpi"...
    comparison: str | None = None  # "at_least", "at_most", "equal"

    def to_dict(self) -> dict[str, object]:
        return {
            "actual": self.actual,
            "required": self.required,
            "unit": self.unit,
            "comparison": self.comparison,
        }


@dataclass(frozen=True)
class PageContext:
    """Physical page plus the plan meaning it carries when the PDF matches the layout."""

    physical_page: int
    logical_page: int | None = None
    kind: str | None = None
    side: str | None = None
    folio: str | None = None


@dataclass(frozen=True)
class Finding:
    rule: Rule
    message: str
    page: PageContext | None = None  # None: a book-level finding.
    subject: str | None = None  # Puzzle ID.
    region: str | None = None
    bounds: Box | None = None  # PDF points, origin at the trim's bottom-left.
    measure: Measure | None = None

    @property
    def severity(self) -> Severity:
        return self.rule.severity

    def sort_key(self) -> tuple[object, ...]:
        return (
            list(Severity).index(self.rule.severity),
            list(Scope).index(self.rule.scope),
            self.page.physical_page if self.page else 0,
            self.rule.code,
            self.region or "",
            self.subject or "",
            self.message,
        )

    def to_dict(self) -> dict[str, object]:
        page = self.page
        bounds = self.bounds
        return {
            "rule": self.rule.code,
            "severity": self.rule.severity.value,
            "scope": self.rule.scope.value,
            "category": self.rule.category.value,
            "message": self.message,
            "physical_page": page.physical_page if page else None,
            "logical_page": page.logical_page if page else None,
            "page_kind": page.kind if page else None,
            "side": page.side if page else None,
            "folio": page.folio if page else None,
            "subject": self.subject,
            "region": self.region,
            "bounds": None
            if bounds is None
            else {k: _round(getattr(bounds, k)) for k in ("x", "y", "width", "height")},
            "measure": self.measure.to_dict() if self.measure else None,
        }


@dataclass(frozen=True)
class RuleResult:
    rule: Rule
    outcome: Outcome
    findings: int
    note: str | None = None  # Why not applicable/evaluated, or what passed.
    measure: Measure | None = None  # Worst observed case, when one exists.

    def to_dict(self) -> dict[str, object]:
        return {
            **self.rule.to_dict(),
            "outcome": self.outcome.value,
            "findings": self.findings,
            "note": self.note,
            "measure": self.measure.to_dict() if self.measure else None,
        }


@dataclass(frozen=True)
class PreflightReport:
    book_id: str
    source_identity: str
    profile: dict[str, object] | None
    artifacts: dict[str, object]
    page_count: int | None
    pages: tuple[PageContext, ...]
    results: tuple[RuleResult, ...]
    findings: tuple[Finding, ...]
    ruleset: Ruleset = KDP_PAPERBACK

    def _blocking(self, scope: Scope) -> bool:
        # Unscreened error rules block as surely as failed ones; warnings never block.
        return any(
            r.rule.scope is scope
            and r.rule.severity is Severity.ERROR
            and r.outcome in (Outcome.FAILED, Outcome.NOT_EVALUATED)
            for r in self.results
        )

    @property
    def structurally_valid(self) -> bool:
        return not self._blocking(Scope.STRUCTURAL)

    @property
    def kdp_ready(self) -> bool:
        # KDP readiness is only claimed for a structurally valid artifact.
        return self.structurally_valid and not self._blocking(Scope.KDP)

    def to_dict(self) -> dict[str, object]:
        counts: dict[str, dict[str, int]] = {
            "severity": {s.value: 0 for s in Severity},
            "scope": {s.value: 0 for s in Scope},
            "category": {c.value: 0 for c in Category},
            "outcome": {o.value: 0 for o in Outcome},
        }
        for finding in self.findings:
            counts["severity"][finding.rule.severity.value] += 1
            counts["scope"][finding.rule.scope.value] += 1
            counts["category"][finding.rule.category.value] += 1
        for result in self.results:
            counts["outcome"][result.outcome.value] += 1
        per_page: dict[int, dict[str, int]] = {}
        for finding in self.findings:
            if finding.page is not None:
                tally = per_page.setdefault(finding.page.physical_page, {})
                key = finding.rule.severity.value
                tally[key] = tally.get(key, 0) + 1
        return {
            "report_version": REPORT_VERSION,
            "ruleset": self.ruleset.to_dict(),
            "book_id": self.book_id,
            "source_identity": self.source_identity,
            "profile": self.profile,
            "artifacts": self.artifacts,
            "page_count": self.page_count,
            "structural": {"status": "valid" if self.structurally_valid else "invalid"},
            "kdp": {"status": "ready" if self.kdp_ready else "not_ready"},
            "counts": counts,
            "findings": [finding.to_dict() for finding in self.findings],
            "rules": [result.to_dict() for result in self.results],
            "pages": [
                {
                    "physical_page": page.physical_page,
                    "logical_page": page.logical_page,
                    "kind": page.kind,
                    "side": page.side,
                    "folio": page.folio,
                    "findings": {
                        s.value: per_page.get(page.physical_page, {}).get(s.value, 0)
                        for s in Severity
                    },
                }
                for page in self.pages
            ],
        }


def report_bytes(report: PreflightReport) -> bytes:
    """Canonical, deterministic JSON. No timestamps or filesystem paths."""
    text = json.dumps(
        report.to_dict(), sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False
    )
    return (text + "\n").encode("ascii")


def _round(value: float) -> float:
    return round(value, 3)
