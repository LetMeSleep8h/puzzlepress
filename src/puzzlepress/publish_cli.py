"""Terminal adapter for KDP publishing: validate, inspect and package.

Every decision is made by `puzzlepress.publishing`; this module presents it.
Nothing here contacts Amazon. Exit codes: 0 success, 1 expected validation or
readiness failure, 2 usage (argparse).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .project import LoadedProject, load_project

if TYPE_CHECKING:
    from .publishing.metadata import Confirmation
    from .publishing.model import Finding

BOUNDARY = (
    "PuzzlePress checks the KDP rules it models. Upload and submit in KDP yourself; "
    "Amazon KDP reviews and decides."
)


def add_publish_command(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    publish = commands.add_parser("publish", help="KDP paperback metadata, readiness and package")
    actions = publish.add_subparsers(dest="publish_command", required=True)
    output_help = "Build directory with the interior and cover (default: output.directory)"
    validate = actions.add_parser(
        "validate", help="Validate publishing metadata, disclosure and confirmations (no files)"
    )
    validate.add_argument("project", help="YAML file or directory containing book.yaml")
    validate.add_argument("--json", action="store_true", help="Print the metadata report JSON")
    inspect = actions.add_parser(
        "inspect", help="Report publishing readiness of metadata and built files (read-only)"
    )
    inspect.add_argument("project", help="YAML file or directory containing book.yaml")
    inspect.add_argument("--output", metavar="DIR", help=output_help)
    inspect.add_argument("--json", action="store_true", help="Print the readiness report JSON")
    package = actions.add_parser(
        "package", help="Write the verified publishing package for manual KDP upload"
    )
    package.add_argument("project", help="YAML file or directory containing book.yaml")
    package.add_argument("--output", metavar="DIR", help=output_help)
    package.add_argument("--zip", action="store_true", help="Also write publishing.zip")
    package.add_argument("--json", action="store_true", help="Print a structured result")


def _bytes(data: bytes) -> None:
    """Exact bytes on stdout, without platform newline translation."""
    binary = getattr(sys.stdout, "buffer", None)
    if binary is None:
        sys.stdout.write(data.decode("ascii"))
    else:
        sys.stdout.flush()
        binary.write(data)
        binary.flush()


def _json_bytes(data: object) -> bytes:
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
    return (text + "\n").encode("ascii")


def _show(finding: "Finding") -> str:
    where = finding.field or finding.artifact
    measured = (
        f" (actual {finding.actual}; required {finding.required})"
        if finding.actual is not None and finding.required is not None
        else ""
    )
    return f"  [{finding.rule.code}] {finding.message}{measured}" + (f" [{where}]" if where else "")


def _findings(findings: "tuple[Finding, ...]") -> None:
    for severity, heading in (("error", "Blocking"), ("warning", "Review"), ("info", "Notes")):
        found = [f for f in findings if f.severity.value == severity]
        print(f"{heading}: {len(found) or 'none'}")
        for finding in found:
            print(_show(finding))


def _directory(loaded: LoadedProject, output: str | None) -> Path:
    return Path(output) if output else loaded.output_directory


def run_publish_command(args: argparse.Namespace) -> int:
    loaded = load_project(args.project)
    if args.publish_command == "validate":
        return _validate(loaded, args)
    if args.publish_command == "inspect":
        return _inspect(loaded, args)
    return _package(loaded, args)


def _validate(loaded: LoadedProject, args: argparse.Namespace) -> int:
    from .publishing import validate_metadata

    report = validate_metadata(loaded.project)
    if args.json:
        _bytes(_json_bytes(report.to_dict()))
        return 0 if report.valid else 1
    verdicts = report.verdicts()
    ruleset = report.ruleset
    print(f"Publishing metadata: {report.book_id} ({ruleset.id} v{ruleset.version})")
    print(f"Metadata: {verdicts['metadata'].upper()}")
    print(f"AI disclosure: {verdicts['disclosure'].upper()}")
    print(f"Author confirmations: {verdicts['attestations'].upper()}")
    if report.publishing_identity:
        print(f"Publishing identity: {report.publishing_identity}")
    _confirmations(loaded, report.confirmations)
    _findings(report.findings)
    print("Built files are not checked here; run `puzzlepress publish inspect`.")
    return 0 if report.valid else 1


def _confirmations(loaded: LoadedProject, states: "tuple[Confirmation, ...]") -> None:
    """Each required confirmation's state, and what to record once a person has reviewed."""
    required = [c for c in states if c.required]
    if not required:
        return
    publishing = loaded.project.publishing
    legacy = publishing is not None and publishing.attestations.legacy is not None
    print("Confirmations:")
    for c in required:
        print(f"  {c.name}: {c.state.upper()}. {c.message}")
    pending = [c for c in required if c.state != "confirmed"]
    if not pending:
        return
    print(
        "Only you can confirm. After reviewing, record each statement's current review "
        "identity in book.yaml"
        + (" (first set publishing.version to 2 and every confirmation to null)" if legacy else "")
        + ":"
    )
    for c in pending:
        print(f"  publishing.attestations.{c.name}: {c.current}")


def _inspect(loaded: LoadedProject, args: argparse.Namespace) -> int:
    from .publishing import evaluate_readiness, readiness_bytes
    from .publishing.package import PackageError, assemble_package, export_state

    source = loaded.source_path.parent
    output = _directory(loaded, args.output)
    report = evaluate_readiness(loaded.project, source, output)
    if args.json:
        _bytes(readiness_bytes(report))
        return 0 if report.package_ready else 1
    current = None
    if report.package_ready:
        try:
            current = assemble_package(report).identity
        except PackageError:
            current = None
    exported = export_state(output, source, report.book_id, current)
    v = report.verdicts()
    interior, cover = v["interior"], v["cover"]
    assert isinstance(interior, dict) and isinstance(cover, dict)
    ruleset = report.metadata.ruleset
    print(f"Publishing readiness: {report.book_id} ({ruleset.id} v{ruleset.version})")
    print(
        f"Metadata: {v['metadata']} | AI disclosure: {v['disclosure']} | "
        f"confirmations: {v['attestations']}"
    )
    print(
        f"Interior: {interior['state']} | structural {interior['structural']} | "
        f"KDP {interior['kdp']}"
    )
    print(f"Cover: {cover['state']} | structural {cover['structural']} | KDP {cover['kdp']}")
    print(f"Artifacts: {v['artifacts']}")
    printing = report.print_configuration()
    if printing:
        size = printing.get("cover")
        spine = f", spine {size['spine_width_in']} in" if isinstance(size, dict) else ""
        print(
            f"Print: {printing['page_count']} pages, {printing['ink']} ink on "
            f"{printing['paper']} paper, 8.5 x 11 in, no interior bleed{spine}"
        )
    print(f"Package: {'READY' if report.package_ready else 'NOT READY'}")
    print(report.statement())
    if exported.state != "none":
        print(
            f"Exported package: {exported.state}"
            + (f" ({exported.problem})" if exported.problem else "")
        )
    _findings(report.findings)
    print(BOUNDARY)
    return 0 if report.package_ready else 1


def _package(loaded: LoadedProject, args: argparse.Namespace) -> int:
    from .publishing import evaluate_readiness
    from .publishing.package import PackageError, assemble_package, write_package

    source = loaded.source_path.parent
    output = _directory(loaded, args.output)
    report = evaluate_readiness(loaded.project, source, output)
    try:
        package = assemble_package(report)
        written = write_package(package, output, source, archive=args.zip)
    except PackageError as error:
        if args.json:
            _bytes(
                _json_bytes(
                    {
                        "success": False,
                        "code": error.code,
                        "message": str(error),
                        "blocking": [
                            f.to_dict() for f in report.findings if f.severity.value == "error"
                        ],
                    }
                )
            )
        print(f"No package was written: {error}", file=sys.stderr)
        for finding in report.findings:
            if finding.severity.value == "error":
                print(_show(finding), file=sys.stderr)
        return 1
    warnings = [f for f in report.findings if f.severity.value == "warning"]
    if args.json:
        _bytes(
            _json_bytes(
                {
                    "success": True,
                    "package_identity": package.identity,
                    "output": {
                        "directory": str(written.directory),
                        "archive": str(written.archive) if written.archive else None,
                    },
                    "files": package.manifest["files"],
                    "warnings": [f.to_dict() for f in warnings],
                }
            )
        )
        return 0
    print(f"Package: {written.directory}")
    if written.archive:
        print(f"Archive: {written.archive}")
    print(f"Package identity: {package.identity}")
    files = package.manifest["files"]
    assert isinstance(files, list)
    for entry in files:
        print(f"  {entry['name']:<24} {entry['sha256'][:16]}  {entry['purpose']}")
    print(f"Warnings to review before upload: {len(warnings) or 'none'}")
    for finding in warnings:
        print(_show(finding))
    print("Follow kdp-checklist.md. Nothing has been uploaded or submitted.")
    print(BOUNDARY)
    return 0
