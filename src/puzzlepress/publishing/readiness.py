"""Publishing readiness: metadata, artifact integrity and preflight verdicts together.

Readiness observes. It reads interior.pdf/interior.json and cover.pdf/cover.json
by fixed name from a boundary-checked build directory, runs the authoritative
interior and cover preflight afresh (saved reports are compared, never trusted)
and keeps every verdict separate: metadata, disclosure, attestations, interior
structure and KDP readiness, cover structure and KDP readiness, artifact
currency, and the package. Preflight warnings stay warnings and rules that were
not evaluated stay unevaluated. Nothing is written, rebuilt or repaired.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..cover.build import PREFLIGHT_NAME as COVER_PREFLIGHT_NAME
from ..cover.layout import CoverCopy, same_words
from ..cover.preflight import CoverPreflightReport, preflight_cover
from ..cover.preflight import report_bytes as cover_report_bytes
from ..identity import build_identity
from ..interior.build import PREFLIGHT_NAME, check_output_directory
from ..interior.issues import InteriorError
from ..interior.spec import to_inches
from ..models import Project
from ..preflight import InteriorArtifacts, read_interior_artifacts
from ..preflight import report_bytes as interior_report_bytes
from ..preflight.engine import PreflightResult, preflight_interior
from ..preflight.model import Finding as PreflightFinding
from ..preflight.model import Outcome as PreflightOutcome
from ..preflight.model import RuleResult as PreflightRuleResult
from ..preflight.model import Scope as PreflightScope
from .metadata import MetadataReport, validate_metadata
from .model import Area, Collector, Finding, Outcome, RuleResult, Severity
from .rules import CODES, RULES, ruleset_for

# 2: confirmations carry the review identity they apply to and their state.
REPORT_VERSION = 2
# Interior preflight rules whose failure means the interior predates its inputs.
INTERIOR_STALE_RULES = (
    "source_current",
    "plan_current",
    "print_profile_current",
    "toolchain_current",
)
ARTIFACT_CODES = tuple(
    code for code in CODES if RULES[code].scope.value in ("interior", "cover", "artifacts")
) + ("cover_text_matches", "cover_text_omitted", "cover_matches_interior")


@dataclass(frozen=True)
class PublishingReadinessReport:
    """Immutable, deterministic readiness of one book for manual KDP submission."""

    project: Project
    metadata: MetadataReport
    interior: PreflightResult | None
    interior_artifacts: InteriorArtifacts | None
    interior_state: str  # missing, current, stale, invalid, unavailable
    cover: CoverPreflightReport | None
    cover_state: str  # no_config, missing, current, stale, invalid, unavailable
    findings: tuple[Finding, ...]
    results: tuple[RuleResult, ...]

    # ------------------------------------------------------------ verdicts

    @property
    def book_id(self) -> str:
        return self.project.book.id

    @property
    def package_ready(self) -> bool:
        """No error rule failed or went unevaluated, in any scope."""
        return not any(
            r.rule.severity is Severity.ERROR
            and r.outcome in (Outcome.FAILED, Outcome.NOT_EVALUATED)
            for r in self.results
        )

    def _artifacts(self) -> str:
        states = (self.interior_state, self.cover_state)
        if "unavailable" in states:
            return "unavailable"
        if any(s in ("missing", "no_config") for s in states):
            return "missing"
        if "invalid" in states:
            return "mismatched"
        if "stale" in states or any(
            f.rule.code in ("cover_matches_interior", "cover_text_matches") for f in self.findings
        ):
            return "stale"
        return "current"

    def verdicts(self) -> dict[str, object]:
        interior = self.interior.report if self.interior else None
        cover = self.cover
        return {
            **self.metadata.verdicts(),
            "interior": {
                "state": self.interior_state,
                "structural": "missing"
                if interior is None
                else "valid"
                if interior.structurally_valid
                else "invalid",
                "kdp": "missing"
                if interior is None
                else "ready"
                if interior.kdp_ready
                else "not_ready",
            },
            "cover": {
                "state": self.cover_state,
                "structural": "missing"
                if cover is None or self.cover_state in ("no_config", "missing")
                else "valid"
                if cover.structurally_valid
                else "invalid",
                "kdp": "missing"
                if cover is None or self.cover_state in ("no_config", "missing")
                else "ready"
                if cover.kdp_ready
                else "not_ready",
            },
            "artifacts": self._artifacts(),
            "package": "ready" if self.package_ready else "not_ready",
        }

    # ------------------------------------------------------------ facts

    def interior_bytes(self) -> tuple[bytes, bytes] | None:
        a = self.interior_artifacts
        return (a.pdf, a.manifest) if a and a.pdf is not None and a.manifest is not None else None

    def cover_bytes(self) -> tuple[bytes, bytes] | None:
        a = self.cover.context.artifacts if self.cover else None
        return (a.pdf, a.manifest) if a and a.pdf is not None and a.manifest is not None else None

    def interior_report_bytes(self) -> bytes | None:
        return interior_report_bytes(self.interior.report) if self.interior else None

    def cover_report_bytes(self) -> bytes | None:
        if self.cover is None or self.cover_state == "no_config":
            return None
        return cover_report_bytes(self.cover)

    def identities(self) -> dict[str, object]:
        interior = _manifest(self.interior_bytes())
        cover = self.cover.context.manifest if self.cover else None
        expected_cover = self.cover.context.expected if self.cover else None
        expected_interior = self.interior.report.artifacts if self.interior else {}
        return {
            "source": build_identity(self.project),
            "publishing": self.metadata.publishing_identity,
            "interior": {
                "recorded": interior.get("interior_identity") if interior else None,
                "expected": expected_interior.get("expected_interior_identity"),
            },
            "cover": {
                "recorded": cover.get("cover_identity") if cover else None,
                "expected": expected_cover.manifest["cover_identity"] if expected_cover else None,
            },
        }

    def print_configuration(self) -> dict[str, object] | None:
        """The physical edition KDP must be told about, from the verified artifacts."""
        interior = _manifest(self.interior_bytes())
        if interior is None or self.interior is None or not self.interior.report.page_count:
            return None
        profile = interior["print_profile"]
        assert isinstance(profile, dict)
        trim = interior["trim"]
        assert isinstance(trim, dict)
        data: dict[str, object] = {
            "format": "paperback",
            "profile": {"id": profile["profile_id"], "version": profile["profile_version"]},
            "trim_in": [trim["width_in"], trim["height_in"]],
            "ink": profile["ink"],
            "paper": profile["paper"],
            "interior_bleed": bool(trim["bleed"]),
            "page_count": self.interior.report.page_count,
            "cover": None,
        }
        expected = self.cover.context.expected if self.cover else None
        if expected is not None and self.cover_state == "current":
            g = expected.layout.geometry
            data["cover"] = {
                "width_in": round(to_inches(g.media.width), 4),
                "height_in": round(to_inches(g.media.height), 4),
                "spine_width_in": round(to_inches(g.spine_width), 4),
                "bleed_in": round(to_inches(g.bleed), 4),
            }
        return data

    def statement(self) -> str:
        if self.package_ready:
            return (
                "Ready for manual KDP submission: the supported KDP checks passed and the "
                "author's confirmations are complete. Amazon KDP reviews and decides."
            )
        blocking = sum(1 for f in self.findings if f.severity is Severity.ERROR)
        unevaluated = sum(
            1
            for r in self.results
            if r.rule.severity is Severity.ERROR and r.outcome is Outcome.NOT_EVALUATED
        )
        return (
            f"Not ready: {blocking} blocking finding(s) and {unevaluated} unevaluated required "
            "check(s) remain."
        )

    def to_dict(self) -> dict[str, object]:
        counts: dict[str, dict[str, int]] = {
            "severity": {s.value: 0 for s in Severity},
            "outcome": {o.value: 0 for o in Outcome},
        }
        for finding in self.findings:
            counts["severity"][finding.severity.value] += 1
        for result in self.results:
            counts["outcome"][result.outcome.value] += 1
        interior_report = self.interior_report_bytes()
        cover_report = self.cover_report_bytes()
        interior = self.interior_bytes()
        cover = self.cover_bytes()
        return {
            "report_version": REPORT_VERSION,
            "ruleset": {
                "id": self.metadata.ruleset.id,
                "version": self.metadata.ruleset.version,
                "kdp_rules_checked": self.metadata.ruleset.checked,
            },
            "book_id": self.book_id,
            "statement": self.statement(),
            "verdicts": self.verdicts(),
            "confirmations": [c.to_dict() for c in self.metadata.confirmations],
            "identities": self.identities(),
            "print": self.print_configuration(),
            "artifacts": {
                "interior_pdf": _digest(interior[0]) if interior else None,
                "interior_manifest": _digest(interior[1]) if interior else None,
                "cover_pdf": _digest(cover[0]) if cover else None,
                "cover_manifest": _digest(cover[1]) if cover else None,
            },
            "preflight": {
                "interior": None
                if interior_report is None
                else {"ruleset": _ruleset(interior_report), "report": _digest(interior_report)},
                "cover": None
                if cover_report is None
                else {"ruleset": _ruleset(cover_report), "report": _digest(cover_report)},
            },
            "counts": counts,
            "findings": [finding.to_dict() for finding in self.findings],
            "rules": [result.to_dict() for result in self.results],
        }


def readiness_bytes(report: PublishingReadinessReport) -> bytes:
    """Canonical JSON: sorted keys, ASCII, no timestamps or paths."""
    text = json.dumps(
        report.to_dict(), sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False
    )
    return (text + "\n").encode("ascii")


def _digest(data: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _ruleset(report: bytes) -> object:
    return json.loads(report)["ruleset"]


def _manifest(pair: tuple[bytes, bytes] | None) -> dict[str, object] | None:
    if pair is None:
        return None
    try:
        value = json.loads(pair[1].decode("utf-8"))
    except (UnicodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------- evaluation


def evaluate_readiness(
    project: Project, project_directory: Path, output: Path
) -> PublishingReadinessReport:
    """Validate metadata, then inspect the interior and cover in `output`. Writes nothing."""
    metadata = validate_metadata(project)
    c = Collector(metadata.ruleset.rules)
    try:
        directory = check_output_directory(output, project_directory)
    except InteriorError as error:
        c.fail(
            "output_directory",
            f"The build directory is unavailable: {error.issues[0].message}",
            action="Check output.directory in book.yaml.",
            area=Area.PRINT,
        )
        for code in ARTIFACT_CODES:
            c.skip(code, "No build directory.")
        return _assemble(project, metadata, c, None, None, "unavailable", None, "unavailable")
    interior, artifacts, interior_state = _interior(c, project, directory, project_directory)
    cover, cover_state = _cover(c, project, project_directory, directory)
    _saved_reports(c, directory, interior, cover, cover_state)
    _consistency(c, project, cover, cover_state)
    return _assemble(project, metadata, c, interior, artifacts, interior_state, cover, cover_state)


def _assemble(
    project: Project,
    metadata: MetadataReport,
    c: Collector,
    interior: PreflightResult | None,
    artifacts: InteriorArtifacts | None,
    interior_state: str,
    cover: CoverPreflightReport | None,
    cover_state: str,
) -> PublishingReadinessReport:
    artifact_results = c.results(ARTIFACT_CODES)
    order = {code: i for i, code in enumerate(ruleset_for(project.coloring is not None).codes)}
    results = tuple(
        sorted((*metadata.results, *artifact_results), key=lambda r: order[r.rule.code])
    )
    findings = tuple(sorted((*metadata.findings, *c.findings), key=Finding.sort_key))
    return PublishingReadinessReport(
        project,
        metadata,
        interior,
        artifacts,
        interior_state,
        cover,
        cover_state,
        findings,
        results,
    )


def _measure(finding: PreflightFinding) -> tuple[object, object]:
    m = finding.measure
    return (m.actual, m.required) if m else (None, None)


def _consume(
    c: Collector,
    results: tuple[PreflightRuleResult, ...],
    findings: tuple[PreflightFinding, ...],
    prefix: str,
    codes: tuple[str, str, str],
    artifact: str,
    area: Area,
    structurally_valid: bool,
) -> None:
    """Carry preflight verdicts over unchanged: errors block, warnings warn."""
    structural, kdp, warnings = codes
    for finding in findings:
        actual, required = _measure(finding)
        page = f" (PDF page {finding.page.physical_page})" if finding.page else ""
        target = (
            warnings
            if finding.severity.value != "error"
            else structural
            if finding.rule.scope is PreflightScope.STRUCTURAL
            else kdp
        )
        if finding.severity.value == "info":
            continue
        c.fail(
            target,
            f"{prefix}{finding.message}{page}",
            artifact=artifact,
            actual=actual if isinstance(actual, int | float | str) else None,
            required=required if isinstance(required, int | float | str) else None,
            action=f"Open {area.value.capitalize()} to review or rebuild.",
            area=area,
            related=finding.rule.code,
        )
    for scope, code in ((PreflightScope.STRUCTURAL, structural), (PreflightScope.KDP, kdp)):
        unevaluated = [
            r.rule.code
            for r in results
            if r.rule.scope is scope
            and r.rule.severity.value == "error"
            and r.outcome is PreflightOutcome.NOT_EVALUATED
        ]
        if scope is PreflightScope.KDP and not structurally_valid:
            c.skip(code, "KDP readiness is only judged for a structurally valid artifact.")
        elif unevaluated and not any(f.rule.code == code for f in c.findings):
            c.fail(
                code,
                f"{prefix}required checks could not be evaluated: {', '.join(unevaluated)}.",
                artifact=artifact,
                area=area,
            )


def _interior(
    c: Collector, project: Project, directory: Path, project_directory: Path
) -> tuple[PreflightResult | None, InteriorArtifacts | None, str]:
    codes = ("interior_structural", "interior_kdp", "interior_warnings")
    if project.composition is None:
        c.fail(
            "interior_present",
            "The project has no book composition, so there is no interior to publish.",
            action="Compose the book in Book.",
            area=Area.BOOK,
        )
        for code in codes:
            c.skip(code, "No composition.")
        return None, None, "missing"
    artifacts = read_interior_artifacts(directory)
    if artifacts.pdf is None and artifacts.manifest is None:
        c.fail(
            "interior_present",
            "No interior has been built.",
            artifact="interior.pdf",
            action="Build the interior in Print.",
            area=Area.PRINT,
        )
        for code in codes:
            c.skip(code, "No interior.")
        return None, artifacts, "missing"
    result = preflight_interior(project, artifacts, source_directory=project_directory)
    report = result.report
    outcomes = {r.rule.code: r.outcome for r in report.results}
    stale = any(outcomes.get(code) is PreflightOutcome.FAILED for code in INTERIOR_STALE_RULES)
    state = "stale" if stale else "current" if report.structurally_valid else "invalid"
    prefix = (
        "Interior is out of date: "
        if state == "stale"
        else "Interior files do not agree: "
        if state == "invalid"
        else "Interior: "
    )
    _consume(
        c,
        report.results,
        report.findings,
        prefix,
        codes,
        "interior.pdf",
        Area.PRINT,
        report.structurally_valid,
    )
    return result, artifacts, state


def _cover(
    c: Collector, project: Project, project_directory: Path, directory: Path
) -> tuple[CoverPreflightReport | None, str]:
    codes = ("cover_structural", "cover_kdp", "cover_warnings")
    if project.cover is None:
        c.fail(
            "cover_present",
            "The project has no cover section.",
            action="Design the cover in Cover.",
            area=Area.COVER,
        )
        for code in codes:
            c.skip(code, "No cover.")
        return None, "no_config"
    report = preflight_cover(project, project_directory, directory)
    if report.state == "missing":
        c.fail(
            "cover_present",
            "No cover has been built.",
            artifact="cover.pdf",
            action="Build the cover in Cover.",
            area=Area.COVER,
        )
        for code in codes:
            c.skip(code, "No cover.")
        return report, "missing"
    prefix = (
        "Cover is out of date: "
        if report.state == "stale"
        else "Cover files do not agree: "
        if report.state == "invalid"
        else "Cover: "
    )
    _consume(
        c,
        report.results,
        report.findings,
        prefix,
        codes,
        "cover.pdf",
        Area.COVER,
        report.structurally_valid,
    )
    return report, report.state


def _saved_reports(
    c: Collector,
    directory: Path,
    interior: PreflightResult | None,
    cover: CoverPreflightReport | None,
    cover_state: str,
) -> None:
    """Saved reports are evidence of an earlier run, never a verdict."""
    pairs: list[tuple[str, bytes]] = []
    if interior is not None:
        pairs.append((PREFLIGHT_NAME, interior_report_bytes(interior.report)))
    if cover is not None and cover_state != "missing":
        pairs.append((COVER_PREFLIGHT_NAME, cover_report_bytes(cover)))
    for name, fresh in pairs:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            c.fail(
                "saved_reports",
                f"{name} is missing. This evaluation ran preflight afresh; the package "
                "includes the fresh report.",
                artifact=name,
            )
            continue
        try:
            saved = path.read_bytes()
        except OSError:
            saved = b""
        if saved != fresh:
            c.fail(
                "saved_reports",
                f"{name} does not match a fresh preflight of the current files (an earlier "
                "run or ruleset). It was not trusted; the package includes the fresh report.",
                artifact=name,
            )


def _displayed(
    c: Collector,
    manifest: dict[str, object],
    recorded: dict[str, object],
    details: dict[str, object],
) -> None:
    """What the built cover prints for each book detail against the details themselves.

    Manifests written before cover display overrides have no `display` record; they
    printed the details as they were (already compared through `copy`).
    """
    display = manifest.get("display")
    if not isinstance(display, dict):
        return
    for key in ("title", "subtitle", "author", "imprint"):
        shown, detail = display.get(key), details.get(key)
        if shown is not None and shown == recorded.get(key):
            continue  # The details as built; a later change is reported through `copy`.
        if shown is None:
            if key in ("title", "author") and isinstance(detail, str) and detail:
                c.fail(
                    "cover_text_omitted",
                    f"The built cover does not print the {key} ({detail!r}); the book "
                    f"details still hold it. KDP requires cover information to match the "
                    f"book details but does not state that the {key} must appear; "
                    "confirm this is intended.",
                    field=f"cover.text.{key}",
                    artifact="cover.pdf",
                    action=f"Show the {key} in Cover, or keep it hidden deliberately.",
                    area=Area.COVER,
                )
            continue
        if not isinstance(shown, str) or not same_words(shown, str(detail or "")):
            c.fail(
                "cover_text_matches",
                f"The built cover prints {key} {shown!r}; the book details say {detail!r}. "
                "KDP requires the cover to match the book details.",
                field=f"cover.text.{key}.text",
                artifact="cover.pdf",
                actual=str(shown),
                required=str(detail),
                action=f"Use the book's {key} on the cover (Reset to book {key}).",
                area=Area.COVER,
            )


def _consistency(
    c: Collector, project: Project, cover: CoverPreflightReport | None, cover_state: str
) -> None:
    manifest = cover.context.manifest if cover else None
    if cover is None or manifest is None or cover_state == "missing":
        reason = "No readable cover manifest."
        c.skip("cover_text_matches", reason)
        c.skip("cover_text_omitted", reason)
        c.skip("cover_matches_interior", reason)
        return
    recorded = manifest["copy"]
    assert isinstance(recorded, dict)
    current = CoverCopy.from_project(project).to_dict()
    for key in sorted(current):
        if recorded.get(key) != current[key]:
            c.fail(
                "cover_text_matches",
                f"The built cover prints {key} {recorded.get(key)!r}; the book details say "
                f"{current[key]!r}. KDP requires the cover to match the book details.",
                field=f"book.{key}",
                artifact="cover.pdf",
                action="Rebuild the cover in Cover.",
                area=Area.COVER,
            )
    _displayed(c, manifest, recorded, current)
    interior = cover.context.interior
    if interior is None:
        c.skip("cover_matches_interior", "No current interior to compare.")
        return
    built_for = manifest["interior"]
    assert isinstance(built_for, dict)
    facts = interior.physical()
    labels = {
        "page_count": "interior page count",
        "paper": "interior paper",
        "profile_id": "interior print profile",
        "profile_version": "interior print profile version",
        "trim_in": "trim size",
        "ink": "ink",
    }
    for key, label in labels.items():
        if built_for.get(key) != json.loads(json.dumps(facts[key])):
            c.fail(
                "cover_matches_interior",
                f"Cover is out of date because the {label} changed "
                f"({built_for.get(key)} -> {facts[key]}).",
                artifact="cover.pdf",
                actual=str(built_for.get(key)),
                required=str(facts[key]),
                action="Rebuild the cover in Cover.",
                area=Area.COVER,
            )
