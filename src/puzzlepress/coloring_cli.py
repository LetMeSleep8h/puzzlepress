"""Terminal adapter for coloring-book artwork. All behavior lives in `coloring`.

`import` and `remove` rewrite book.yaml canonically (comments and formatting are
not preserved), revision-checked and atomically. Originals are never modified or
deleted: `remove --trash` moves an unreferenced file to the project trash, which
the asset library can restore.
"""

import argparse
import io
import json
import sys
from pathlib import Path

from .coloring.inspection import inspect_artwork
from .coloring.issues import ArtworkError, ArtworkFinding, ImportRejected
from .coloring.library import (
    LibraryReport,
    import_files,
    library_report,
    remove_artwork,
    require_coloring,
)
from .cover.assets import MAX_ASSET_BYTES
from .project import load_project


def add_coloring_command(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    coloring = commands.add_parser("coloring", help="Coloring-book artwork library")
    actions = coloring.add_subparsers(dest="coloring_command", required=True)
    project_help = "YAML file or directory containing book.yaml"

    imported = actions.add_parser(
        "import", help="Copy PNG/JPEG line art into the project and add it to the library"
    )
    imported.add_argument("project", help=project_help)
    imported.add_argument("files", nargs="+", metavar="FILE", help="PNG or JPEG files")
    imported.add_argument(
        "--no-page", action="store_true", help="Add to the library without adding a page"
    )
    imported.add_argument("--json", action="store_true", help="Print a structured result")

    listed = actions.add_parser("list", help="List artwork with its pages and status")
    listed.add_argument("project", help=project_help)
    listed.add_argument("--json", action="store_true", help="Print the library report JSON")

    inspected = actions.add_parser(
        "inspect", help="Facts and print findings for artwork or for files before import"
    )
    inspected.add_argument("project", help=project_help)
    inspected.add_argument("artwork", nargs="*", metavar="ID", help="Artwork IDs (default: all)")
    inspected.add_argument(
        "--file", action="append", default=[], metavar="FILE", help="Inspect a file (repeatable)"
    )
    inspected.add_argument("--json", action="store_true", help="Print structured results")

    duplicates = actions.add_parser(
        "duplicates", help="Confirmed duplicate artwork and pages, and possible look-alikes"
    )
    duplicates.add_argument("project", help=project_help)
    duplicates.add_argument("--json", action="store_true", help="Print the duplicate report")

    removed = actions.add_parser(
        "remove", help="Remove an artwork entry from book.yaml; the original file is kept"
    )
    removed.add_argument("project", help=project_help)
    removed.add_argument("artwork", metavar="ID", help="Artwork ID")
    removed.add_argument(
        "--with-pages", action="store_true", help="Also remove every page showing it"
    )
    removed.add_argument(
        "--trash",
        action="store_true",
        help="Then move the file to the project trash if nothing else uses it",
    )
    removed.add_argument("--json", action="store_true", help="Print a structured result")


def _dump(value: object) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))


def _finding_line(finding: ArtworkFinding) -> str:
    return f"  {finding.severity.value} [{finding.code}]: {finding.message}"


def _read_file(path: str) -> tuple[str, bytes]:
    file = Path(path)
    try:
        if not file.is_file():
            raise ArtworkError("not_a_file", "Not a readable file.", path)
        if file.stat().st_size > MAX_ASSET_BYTES:
            raise ArtworkError(
                "file_too_large", f"Artwork may be at most {MAX_ASSET_BYTES:,} bytes.", path
            )
        return file.name, file.read_bytes()
    except OSError as error:
        raise ArtworkError("not_a_file", f"Cannot read the file: {error}", path) from error


def _report_errors(errors: tuple[ArtworkError, ...]) -> int:
    print("Nothing was imported; book.yaml and coloring-assets are unchanged.", file=sys.stderr)
    for error in errors:
        print(f"{error.subject or 'import'} [{error.code}]: {error.message}", file=sys.stderr)
    return 1


def _tolerant_terminal() -> None:
    """Artwork titles keep Unicode; a console that cannot show a character gets an
    escape instead of a crash after the work is done. JSON output is ASCII anyway."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="backslashreplace")


def run_coloring_command(args: argparse.Namespace) -> int:
    _tolerant_terminal()
    command = args.coloring_command
    if command == "import":
        return _import(args)
    if command == "remove":
        return _remove(args)
    loaded = load_project(args.project)
    require_coloring(loaded.project)
    if command == "inspect" and args.file:
        return _inspect_files(args)
    report = library_report(loaded.source_path.parent, loaded.project)
    if command == "list":
        return _list(report, args.json)
    if command == "inspect":
        return _inspect(report, args)
    data = report.duplicates.to_dict()
    if args.json:
        _dump(data)
    else:
        duplicates = report.duplicates
        for group in duplicates.same_file:
            print(f"Same file: {', '.join(group.artwork)} (pages {_pages(group.pages)})")
        for repeat in duplicates.repeated_pages:
            print(f"Repeated: '{repeat.artwork}' is on pages {_pages(repeat.pages)}")
        for pair in duplicates.similar:
            print(
                f"Possible duplicate (heuristic): {pair.artwork[0]} ~ {pair.artwork[1]} "
                f"(hash {pair.hash_distance}/64, map {pair.map_difference}); "
                f"pages {_pages(pair.pages)}"
            )
        for name in duplicates.not_compared:
            print(f"Not compared (unreadable): {name}")
        if not (duplicates.confirmed or duplicates.similar or duplicates.not_compared):
            print("No duplicate artwork or pages found.")
    found = report.duplicates.confirmed or report.duplicates.similar
    return 1 if found or report.duplicates.not_compared else 0


def _pages(pages: tuple[int, ...]) -> str:
    return ", ".join(str(page) for page in pages) or "none"


def _import(args: argparse.Namespace) -> int:
    try:
        files = [_read_file(path) for path in args.files]
    except ArtworkError as error:
        return _report_errors((error,))
    try:
        results = import_files(Path(args.project), files, add_pages=not args.no_page)
    except ImportRejected as rejected:
        if args.json:
            _dump({"imported": False, "errors": [error.to_dict() for error in rejected.errors]})
            return 1
        return _report_errors(rejected.errors)
    if args.json:
        _dump({"imported": True, "artwork": [result.to_dict() for result in results]})
        return 0
    for result in results:
        if not result.added:
            print(f"{result.original_name}: already in the library as '{result.id}'")
        else:
            where = f" as page {result.page}" if result.page else ""
            print(f"{result.original_name}: added '{result.id}' ({result.path}){where}")
        info = result.inspection.info
        print(
            f"  {info.pixels[0]} x {info.pixels[1]} px, {info.effective_dpi:.0f} DPI at full size"
        )
        for finding in result.inspection.findings:
            print(_finding_line(finding))
    return 0


def _list(report: LibraryReport, as_json: bool) -> int:
    if as_json:
        _dump(report.to_dict())
        return 0
    print(f"{report.book_id}: {len(report.entries)} artwork, {report.page_count} pages")
    for entry in report.entries:
        if entry.error is not None:
            status = f"error [{entry.error.code}]"
            facts = ""
        else:
            assert entry.inspection is not None
            info = entry.inspection.info
            blocking = sum(f.severity.value == "blocking" for f in entry.inspection.findings)
            warnings = len(entry.inspection.findings) - blocking
            status = f"{blocking} blocking, {warnings} warnings"
            facts = f"{info.pixels[0]}x{info.pixels[1]} {info.effective_dpi:.0f} DPI, "
        print(
            f"  {entry.artwork.id}: {entry.artwork.title or '(untitled)'} | {facts}"
            f"pages {_pages(entry.pages)} | {status}"
        )
    for path in report.unreferenced:
        print(f"  unreferenced file: {path}")
    return 0


def _inspect(report: LibraryReport, args: argparse.Namespace) -> int:
    wanted = set(args.artwork)
    known = {entry.artwork.id for entry in report.entries}
    unknown = sorted(wanted - known)
    for identifier in unknown:
        print(f"{identifier} [unknown_artwork]: No artwork has this ID.", file=sys.stderr)
    entries = [e for e in report.entries if not wanted or e.artwork.id in wanted]
    if args.json:
        _dump({"artwork": [entry.to_dict() for entry in entries], "unknown": unknown})
    else:
        for entry in entries:
            print(f"{entry.artwork.id} ({entry.artwork.path})")
            if entry.error is not None:
                print(f"  error [{entry.error.code}]: {entry.error.message}")
                continue
            assert entry.inspection is not None
            _describe(entry.inspection.info.to_dict())
            for finding in entry.inspection.findings:
                print(_finding_line(finding))
    blocked = any(e.error or (e.inspection and e.inspection.blocking) for e in entries)
    return 1 if blocked or unknown else 0


def _describe(info: dict[str, object]) -> None:
    for key in (
        "format",
        "bytes",
        "mode",
        "pixels",
        "effective_dpi",
        "printed_inches",
        "aspect_ratio",
        "transparent_pixels",
        "in_color",
        "ink_coverage",
        "sha256",
    ):
        print(f"  {key}: {info[key]}")


def _inspect_files(args: argparse.Namespace) -> int:
    results: list[dict[str, object]] = []
    blocked = False
    for path in args.file:
        try:
            name, data = _read_file(path)
            inspection = inspect_artwork(data, name)
            results.append({"file": path, **inspection.to_dict()})
            blocked = blocked or inspection.blocking
            if not args.json:
                print(path)
                _describe(inspection.info.to_dict())
                for finding in inspection.findings:
                    print(_finding_line(finding))
        except ArtworkError as error:
            blocked = True
            results.append({"file": path, "error": error.about(path).to_dict()})
            if not args.json:
                print(f"{path} [{error.code}]: {error.message}")
    if args.json:
        _dump({"files": results})
    return 1 if blocked else 0


def _remove(args: argparse.Namespace) -> int:
    from .asset_library import AssetError, trash_asset

    try:
        removed = remove_artwork(Path(args.project), args.artwork, args.with_pages)
    except ArtworkError as error:
        print(f"{error.subject} [{error.code}]: {error.message}", file=sys.stderr)
        return 1
    result = removed.to_dict()
    trashed = None
    if args.trash and not removed.file_still_referenced:
        loaded = load_project(args.project)
        try:
            trashed = trash_asset(
                loaded.source_path.parent,
                removed.artwork.path,
                removed.artwork.sha256,
                loaded.project,
            ).to_dict()
        except AssetError as error:
            result["trash_error"] = {"code": error.code, "message": str(error)}
    result["trashed"] = trashed
    if args.json:
        _dump(result)
    else:
        pages = removed.pages
        print(f"Removed artwork '{removed.artwork.id}' from book.yaml.")
        if pages:
            print(f"  Removed pages: {_pages(pages)}")
        if removed.file_still_referenced:
            print(f"  {removed.artwork.path} is kept: other artwork uses the same file.")
        elif trashed is not None:
            print(f"  Moved {removed.artwork.path} to {trashed['trashed']} (restorable).")
        else:
            print(f"  {removed.artwork.path} is kept in the project; nothing was deleted.")
        if "trash_error" in result:
            print(f"  Not moved to the trash: {result['trash_error']}", file=sys.stderr)
    return 1 if "trash_error" in result else 0
