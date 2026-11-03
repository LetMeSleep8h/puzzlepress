"""Terminal adapters: puzzle inventories, duplicate comparison, photo checks and
the one-command production run. All behavior lives in reusable modules."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PREVIOUS_HELP = (
    "Previous book: its book.yaml (or folder), its interior PDF, a release folder holding "
    "interior.pdf, or a saved inventory .json. Repeat for several books. Read only."
)


def _thresholds(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("near-duplicate thresholds")
    group.add_argument("--near-jaccard", type=float, default=0.6, help="Word Jaccard (0.6)")
    group.add_argument("--near-overlap", type=float, default=0.8, help="Word overlap (0.8)")
    group.add_argument("--min-shared", type=int, default=3, help="Shared words for overlap (3)")
    group.add_argument("--near-grid", type=float, default=0.5, help="Grid agreement (0.5)")


def _expected(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--expected-puzzles",
        type=int,
        metavar="N",
        help="How many puzzles a previous PDF holds; required to claim complete coverage",
    )


def add_puzzle_actions(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    inventory = actions.add_parser(
        "inventory", help="List a book's puzzles (word sets and grids) from source or PDF"
    )
    inventory.add_argument("source", help=PREVIOUS_HELP)
    _expected(inventory)
    inventory.add_argument("--label", help="Name for this book in reports")
    inventory.add_argument("--output", metavar="FILE", help="Write the inventory JSON here")
    compare = actions.add_parser(
        "compare", help="Compare a project's puzzles with previous books and with each other"
    )
    compare.add_argument("project", help="YAML file or directory containing book.yaml")
    compare.add_argument("--previous", action="append", default=[], help=PREVIOUS_HELP)
    _expected(compare)
    _thresholds(compare)
    compare.add_argument("--output", metavar="DIR", help="Write duplicate-report.json and .md")
    compare.add_argument("--json", action="store_true", help="Print the report JSON")


def add_cover_actions(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    photos = actions.add_parser(
        "photos", help="Check explicitly listed photographs for print; optionally import them"
    )
    photos.add_argument("project", help="YAML file or directory containing book.yaml")
    photos.add_argument("--manifest", help="YAML/JSON list of approved photo paths")
    photos.add_argument("--photo", action="append", default=[], help="One photo (repeatable)")
    photos.add_argument("--role", choices=("cover", "interior"), default="cover")
    photos.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="Copy usable photos into the project's cover-assets (originals are untouched)",
    )
    photos.add_argument("--json", action="store_true", help="Print the report JSON")


def add_book_actions(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    produce = actions.add_parser(
        "produce",
        help="Build interior, solutions, cover, duplicate and validation reports, and a "
        "manifest into a separate directory",
    )
    produce.add_argument("project", help="YAML file or directory containing book.yaml")
    produce.add_argument("--output", required=True, metavar="DIR", help="New output directory")
    produce.add_argument("--previous", action="append", default=[], help=PREVIOUS_HELP)
    _expected(produce)
    _thresholds(produce)
    produce.add_argument("--photos", metavar="MANIFEST", help="Photo manifest to check")
    produce.add_argument("--profile", help="Print profile (default paperback-8.5x11)")
    produce.add_argument("--json", action="store_true", help="Print the validation JSON")


def _make_thresholds(args: argparse.Namespace) -> object:
    from .duplicates import Thresholds

    return Thresholds(args.near_jaccard, args.near_overlap, args.min_shared, args.near_grid)


def _dump(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))


def run_inventory(args: argparse.Namespace) -> int:
    from .inventory import inventory_json, load_inventory

    inventory = load_inventory(args.source, args.expected_puzzles, args.label)
    text = inventory_json(inventory)
    if args.output:
        target = Path(args.output).expanduser().resolve()
        source = Path(args.source).expanduser().resolve()
        guard = source if source.is_dir() else source.parent
        if target.is_relative_to(guard):
            print(
                "Refusing to write inside the source folder; choose another path.", file=sys.stderr
            )
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"Inventory: {target}")
    else:
        sys.stdout.write(text)
        return 0 if inventory.coverage.complete else 1
    c = inventory.coverage
    print(
        f"Puzzles: {len(inventory.puzzles)} ({len(inventory.verified)} verified, "
        f"{len(inventory.unverified)} unverified) | coverage {c.status}"
    )
    for note in c.notes:
        print(f"  {note}")
    return 0 if c.complete else 1


def run_compare(args: argparse.Namespace) -> int:
    from .duplicates import compare_inventories, report_json, report_markdown
    from .inventory import inventory_from_project, load_inventory
    from .production.candidates import replacement_candidates
    from .production.produce import check_disjoint, write_file
    from .project import load_project

    loaded = load_project(args.project)
    new = inventory_from_project(loaded.source_path)
    previous = [load_inventory(p, args.expected_puzzles) for p in args.previous]
    report = compare_inventories(
        new,
        previous,
        _make_thresholds(args),  # type: ignore[arg-type]
        replacement_candidates(loaded.project, previous),
    )
    if args.output:
        protected = [loaded.source_path.parent, *(Path(p) for p in args.previous)]
        directory = check_disjoint(Path(args.output), protected)
        directory.mkdir(parents=True, exist_ok=True)
        write_file(directory, "duplicate-report.json", report_json(report).encode())
        write_file(directory, "duplicate-report.md", report_markdown(report).encode())
    if args.json:
        sys.stdout.write(report_json(report))
    else:
        sys.stdout.write(report_markdown(report))
    if not args.previous:
        print("No --previous book given: only repeats within this book were checked.")
    return 0 if report.clean or (not args.previous and not report.matches) else 1


def run_photos(args: argparse.Namespace) -> int:
    from .photo_manifest import PhotoEntry, PhotoManifest, check_photos, load_manifest
    from .project import load_project

    loaded = load_project(args.project)
    entries: list[PhotoEntry] = []
    base = None
    folder: Path | None = None
    if args.manifest:
        manifest, folder = load_manifest(args.manifest)
        entries += manifest.entries
        base = manifest.base_directory
    entries += [PhotoEntry(p, args.role) for p in args.photo]
    if not entries:
        print("Name photos with --photo or --manifest; folders are never scanned.", file=sys.stderr)
        return 2
    report = check_photos(
        PhotoManifest(tuple(entries), base),
        folder,
        loaded.source_path.parent if args.do_import else None,
    )
    if args.json:
        _dump(report.to_dict())
    else:
        for check in report.checks:
            size = f"{check.pixels[0]}x{check.pixels[1]}" if check.pixels else "-"
            dpi = f"{check.max_dpi:.0f} DPI" if check.max_dpi else "-"
            print(f"[{check.status}] {check.entry.path} ({check.entry.role}): {size}, {dpi}")
            for code, message in check.issues:
                print(f"    {code}: {message}")
            if check.imported:
                verb = "already in" if check.reused else "copied to"
                print(f"    {verb} {check.imported} (sha256 {check.sha256})")
        print(f"Errors: {report.errors} | warnings: {report.warnings}")
    return 1 if report.errors else 0


def run_produce(args: argparse.Namespace) -> int:
    from .cover.issues import CoverError
    from .interior import InteriorError
    from .production.produce import produce, validation_markdown

    try:
        result = produce(
            args.project,
            args.output,
            args.previous,
            args.expected_puzzles,
            _make_thresholds(args),
            args.photos,
            args.profile,
        )
    except (InteriorError, CoverError) as error:
        print(f"Production stopped at {error.stage}:", file=sys.stderr)
        for issue in error.issues:
            print(f"  [{issue.code}] {issue.message}", file=sys.stderr)
        return 1
    if args.json:
        _dump(result.validation.to_dict())
    else:
        sys.stdout.write(validation_markdown(result.validation))
        print(f"\nOutput: {result.directory}")
        for name, digest, size in result.files:
            print(f"  {name}  {size} bytes  sha256 {digest[:16]}")
    return 0 if result.ready else 1
