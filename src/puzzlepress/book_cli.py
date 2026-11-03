"""Terminal adapter for publication plans (read-only) and interior builds."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .production_cli import add_book_actions, run_produce
from .project import load_project
from .publication import PageKind, PlanPage, PublicationPlan, build_publication
from .publication_verification import publication_payload, verify_publication_plan

if TYPE_CHECKING:
    from .interior import LayoutIssue


def add_book_command(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    book = commands.add_parser("book", help="Book composition tools")
    actions = book.add_subparsers(dest="book_command", required=True)
    add_book_actions(actions)
    plan = actions.add_parser("plan", help="Plan and verify the logical publication order")
    plan.add_argument("project", help="YAML file or directory containing book.yaml")
    plan.add_argument("--json", action="store_true", help="Print the structured plan")
    build = actions.add_parser("build", help="Lay out and write the print interior PDF")
    build.add_argument("project", help="YAML file or directory containing book.yaml")
    build.add_argument(
        "--output", metavar="DIR", help="Output directory (default: the project's output.directory)"
    )
    build.add_argument(
        "--profile",
        help="Print profile: paperback-8.5x11 (white paper, default) or paperback-8.5x11-cream",
    )
    build.add_argument("--json", action="store_true", help="Print a structured build result")
    preflight = actions.add_parser(
        "preflight", help="Inspect a built interior: structural validity and KDP readiness"
    )
    preflight.add_argument("project", help="YAML file or directory containing book.yaml")
    preflight.add_argument(
        "--output",
        metavar="DIR",
        help="Interior directory (default: the project's output.directory)",
    )
    preflight.add_argument("--json", action="store_true", help="Print the preflight report JSON")
    preflight.add_argument(
        "--no-write", action="store_true", help="Do not write preflight.json beside the interior"
    )


def describe(page: PlanPage, plan: PublicationPlan) -> str:
    def label(index: int | None) -> str:
        return plan.pages[index - 1].number.label if index else "?"

    if page.kind is PageKind.BLANK:
        if page.blank_reason == "divider_recto_start":
            return "Blank: theme divider starts on recto"
        before = page.blank_before.value.replace("_", " ") if page.blank_before else "?"
        return f"Blank: {before} start on recto"
    if page.divider is not None:
        return f"Theme divider: {page.divider.title}"
    if page.puzzle is not None:
        ref = page.puzzle
        where = f"; solution p. {label(page.solution_page)}" if page.solution_page else ""
        return f"Puzzle {ref.ordinal}: {ref.title} [{ref.id}]{where}"
    if page.solutions:
        listed = ", ".join(
            f"{item.puzzle.ordinal} (p. {label(item.puzzle_page)})" for item in page.solutions
        )
        heading = f" | heading: {page.heading}" if page.heading else ""
        return f"Solutions for puzzle {listed}{heading}"
    name = page.kind.value.replace("_", " ").capitalize()
    title = page.matter.title if page.matter else None
    return f"{name}: {title}" if title else name


def run_book_command(args: argparse.Namespace) -> int:
    if args.book_command == "build":
        return run_build_command(args)
    if args.book_command == "preflight":
        return run_preflight_command(args)
    if args.book_command == "produce":
        return run_produce(args)
    project = load_project(args.project).project
    report, plan = build_publication(project)
    verification = verify_publication_plan(plan, project, report)
    if not verification.valid:
        raise RuntimeError(f"Publication plan failed verification: {verification.issues!r}")
    if args.json:
        print(
            json.dumps(
                publication_payload(report, plan, verification),
                ensure_ascii=True,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
        )
    else:
        stats = plan.statistics
        print(f"Build identity: {plan.identity}")
        print(
            f"Publication plan v{plan.plan_version} for {plan.book_id}: "
            f"{stats.logical_pages} logical pages, verified"
        )
        print(f"{'Page':>4}  {'Side':<5}  {'Folio':<7}  {'Section':<12}  Entry")
        for page in plan.pages:
            folio = page.number.label if page.number.displayed else f"({page.number.label})"
            section = page.section.value.replace("_", " ")
            print(
                f"{page.index:>4}  {page.side.value:<5}  {folio:<7}  {section:<12}  "
                f"{describe(page, plan)}"
            )
        print(
            f"\nFront matter: {stats.front_matter_pages} | puzzles: {stats.puzzle_pages} | "
            f"solution pages: {stats.solution_pages} ({stats.solutions} solutions) | "
            f"back matter: {stats.back_matter_pages} | blanks: {stats.blank_pages}"
        )
        first = stats.first_solution_page
        first_solution = f"page {first}" if first else "none"
        print(f"First puzzle: page {stats.first_puzzle_page} | first solution: {first_solution}")
        print(f"Quality findings: {len(report.findings)} (inspect with puzzle batch)")
        print("Parenthesized folios count but are not displayed.")
        print("Logical pages are not a final printed page count; layout is not planned.")
    for issue in plan.diagnostics:
        print(f"{issue.path} [{issue.code}]: {issue.message}", file=sys.stderr)
    return 0 if plan.complete else 1


def run_build_command(args: argparse.Namespace) -> int:
    # Imported here so read-only commands never load the PDF toolchain.
    from .interior import (
        DEFAULT_PROFILE,
        InteriorError,
        LayoutIssue,
        build_interior,
        print_profile,
        write_interior,
    )

    loaded = load_project(args.project)
    try:
        spec = print_profile(args.profile or DEFAULT_PROFILE)
        if isinstance(spec, LayoutIssue):
            raise InteriorError("print_spec", (spec,))
        build = build_interior(loaded.project, spec, loaded.source_path.parent)
        output = Path(args.output) if args.output else loaded.output_directory
        written = write_interior(build, output, loaded.source_path.parent)
    except InteriorError as error:
        if args.json:
            print(
                json.dumps(
                    {
                        "success": False,
                        "stage": error.stage,
                        "diagnostics": [issue.to_dict() for issue in error.issues],
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                    indent=2,
                )
            )
        print(f"Interior build failed at {error.stage}; no interior was written.", file=sys.stderr)
        for issue in error.issues:
            print(f"  {_describe_issue(issue)}", file=sys.stderr)
        return 1
    manifest = build.manifest
    if args.json:
        print(
            json.dumps(
                {
                    "success": True,
                    "output": {"pdf": str(written.pdf), "manifest": str(written.manifest)},
                    "manifest": manifest,
                },
                ensure_ascii=True,
                sort_keys=True,
                indent=2,
            )
        )
    else:
        trim = spec.trim
        print(f"Interior: {written.pdf}")
        print(f"Manifest: {written.manifest}")
        print(
            f"Pages: {manifest['page_count']} | trim {trim.name} in, no bleed | "
            f"{spec.ink.value} ink on {spec.paper.value} paper | "
            f"profile {spec.profile_id} v{spec.profile_version}"
        )
        print(f"Interior identity: {manifest['interior_identity']}")
        print(f"PDF SHA-256: {hashlib.sha256(build.pdf).hexdigest()}")
        print("Layout validated; PDF reopened and structurally verified.")
    for warning in build.layout.warnings:
        print(f"Warning: {_describe_issue(warning)}", file=sys.stderr)
    return 0


def run_preflight_command(args: argparse.Namespace) -> int:
    """Exit 0 only when structurally valid and KDP ready; 1 otherwise; 2 usage."""
    from .interior import InteriorError
    from .interior.build import check_output_directory, write_preflight_report
    from .preflight import Severity, preflight_interior, read_interior_artifacts, report_bytes

    loaded = load_project(args.project)
    source = loaded.source_path.parent
    try:
        directory = check_output_directory(
            Path(args.output) if args.output else loaded.output_directory, source
        )
    except InteriorError as error:
        for issue in error.issues:
            print(f"Preflight failed: {_describe_issue(issue)}", file=sys.stderr)
        return 1
    result = preflight_interior(
        loaded.project,
        read_interior_artifacts(directory),
        source_directory=loaded.source_path.parent,
    )
    report = result.report
    data = report_bytes(report)
    written: Path | None = None
    write_failed = False
    if not args.no_write:
        try:
            written = write_preflight_report(data, report.book_id, directory, source)
        except InteriorError as error:
            write_failed = error.issues[0].code == "write_failed"
            print(f"preflight.json not written: {error.issues[0].message}", file=sys.stderr)
    if args.json:
        # Exactly the bytes of preflight.json, without platform newline translation.
        binary = getattr(sys.stdout, "buffer", None)
        if binary is None:
            sys.stdout.write(data.decode("ascii"))
        else:
            sys.stdout.flush()
            binary.write(data)
            binary.flush()
    else:
        profile = report.profile or {}
        print(f"Preflight: {report.book_id} (ruleset {_ruleset()})")
        print(f"Interior: {directory}")
        if report.page_count is not None:
            print(f"Pages: {report.page_count} | profile {profile.get('id', 'unknown')}")
        pdf = report.to_dict()["artifacts"]
        assert isinstance(pdf, dict)
        if pdf["pdf"]:
            print(f"PDF SHA-256: {pdf['pdf']['sha256']}")
        print(f"Structural: {'VALID' if report.structurally_valid else 'INVALID'}")
        print(f"KDP readiness: {'READY' if report.kdp_ready else 'NOT READY'}")
        for severity, heading in ((Severity.ERROR, "Blocking"), (Severity.WARNING, "Warnings")):
            found = [f for f in report.findings if f.severity is severity]
            print(f"{heading}: {len(found) or 'none'}")
            for finding in found:
                where = f" [pdf page {finding.page.physical_page}]" if finding.page else ""
                print(
                    f"  {finding.rule.scope.value} [{finding.rule.code}] {finding.message}{where}"
                )
        outcomes = report.to_dict()["counts"]
        assert isinstance(outcomes, dict)
        tally = outcomes["outcome"]
        print(
            f"Rules: {tally['passed']} passed, {tally['failed']} with findings, "
            f"{tally['not_applicable']} not applicable, {tally['not_evaluated']} not evaluated"
        )
        if written:
            print(f"Report: {written}")
        print("Preflight checks the constraints PuzzlePress models; Amazon KDP decides acceptance.")
    return 0 if report.kdp_ready and not write_failed else 1


def _ruleset() -> str:
    from .preflight import RULESET_ID, RULESET_VERSION

    return f"{RULESET_ID} v{RULESET_VERSION}"


def _describe_issue(issue: "LayoutIssue") -> str:
    where = [
        f"page {issue.page}" if issue.page is not None else None,
        f"pdf page {issue.physical_page}" if issue.physical_page is not None else None,
        issue.kind,
        issue.subject,
        issue.region,
    ]
    context = ", ".join(part for part in where if part)
    measured = f" (actual {issue.actual}; required {issue.required})" if issue.actual else ""
    return f"[{issue.code}] {issue.message}{measured}" + (f" [{context}]" if context else "")
