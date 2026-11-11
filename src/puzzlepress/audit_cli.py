"""Terminal adapter for `book audit`: a read-only review of an existing book."""

import argparse
import json
import os
import sys
from pathlib import Path

from .audit import AUDIT_KIND, OtherBook, Priority, audit_book, audit_bytes, audit_markdown
from .errors import ProjectError, ValidationIssue
from .inventory import inventory_from_project
from .project import load_project

REPORT_FILES = ("audit.json", "audit.md")


def add_audit_action(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    audit = actions.add_parser(
        "audit",
        help="Read-only review of a book: listing, print, content, series and evidence, "
        "as prioritized recommendations",
    )
    audit.add_argument("project", help="YAML file or directory containing book.yaml")
    audit.add_argument(
        "--output",
        metavar="DIR",
        help="Built interior and cover directory (default: the project's output.directory)",
    )
    audit.add_argument(
        "--previous",
        metavar="PROJECT",
        action="append",
        default=[],
        help="An earlier or sibling book to compare with (repeatable; read only)",
    )
    audit.add_argument("--json", action="store_true", help="Print the audit JSON")
    audit.add_argument(
        "--report",
        metavar="DIR",
        help="Also write audit.json and audit.md into DIR (outside every book folder)",
    )


def _fail(code: str, message: str) -> ProjectError:
    return ProjectError((ValidationIssue("report", code, message),))


def _check_report_directory(directory: Path, sources: list[Path]) -> Path:
    resolved = directory.resolve()
    for source in sources:
        root = source.resolve()
        if resolved.is_relative_to(root) or root.is_relative_to(resolved):
            raise _fail("source_overlap", f"--report must be outside {root}.")
    if resolved.exists() and not resolved.is_dir():
        raise _fail("not_directory", f"Not a directory: {resolved}")
    for name in REPORT_FILES:
        path = resolved / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise _fail("output_collision", f"Refusing to replace {path}.")
    existing = resolved / "audit.json"
    if existing.exists():
        try:
            kind = json.loads(existing.read_text(encoding="utf-8")).get("kind")
        except (OSError, ValueError, AttributeError):
            kind = None
        if kind != AUDIT_KIND:
            raise _fail("output_collision", f"{existing} is not a PuzzlePress audit.")
    return resolved


def _write(directory: Path, name: str, data: bytes) -> None:
    staged = directory / f".{name}.staged"
    with open(staged, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(staged, directory / name)
    if (directory / name).read_bytes() != data:
        raise _fail("write_failed", f"{directory / name} did not read back as written.")


def run_audit(args: argparse.Namespace) -> int:
    """Exit 0 with no high-priority recommendation, 1 otherwise; 2 usage."""
    loaded = load_project(args.project)
    source = loaded.source_path.parent
    output = Path(args.output) if args.output else loaded.output_directory
    others: list[OtherBook] = []
    sources = [source]
    for path in args.previous:
        other = load_project(path)
        if other.source_path.resolve() == loaded.source_path.resolve():
            raise _fail("same_book", f"{path} is the audited book itself.")
        sources.append(other.source_path.parent)
        inventory = (
            inventory_from_project(path, other.project.book.id)
            if other.project.word_search is not None
            else None
        )
        others.append(OtherBook(other.project.book.id, other.project, inventory))
    report_directory = _check_report_directory(Path(args.report), sources) if args.report else None
    report = audit_book(loaded.project, source, output, others)
    data = audit_bytes(report)
    markdown = audit_markdown(report)
    if report_directory is not None:
        report_directory.mkdir(parents=True, exist_ok=True)
        _write(report_directory, "audit.json", data)
        _write(report_directory, "audit.md", markdown.encode("utf-8"))
    if args.json:
        binary = getattr(sys.stdout, "buffer", None)
        if binary is None:
            sys.stdout.write(data.decode("ascii"))
        else:
            sys.stdout.flush()
            binary.write(data)
            binary.flush()
    else:
        sys.stdout.write(markdown)
        if report_directory is not None:
            print(f"Report: {report_directory / 'audit.md'}")
    return 1 if report.counts()[Priority.HIGH.value] else 0
