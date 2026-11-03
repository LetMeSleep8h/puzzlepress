"""Terminal adapter for paperback covers: inspect, import, build and preflight.

Production cover settings live in the project's cover section; the CLI exposes
no geometry flags. Cover modules are imported lazily, like the interior engine.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from .production_cli import add_cover_actions, run_photos
from .project import LoadedProject, load_project

if TYPE_CHECKING:
    from .cover.issues import CoverError


def add_cover_command(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    cover = commands.add_parser("cover", help="Paperback cover tools")
    actions = cover.add_subparsers(dest="cover_command", required=True)
    add_cover_actions(actions)
    output_help = "Interior/cover directory (default: the project's output.directory)"
    inspect = actions.add_parser(
        "inspect", help="Show wrap geometry, spine and photo resolution (read-only)"
    )
    inspect.add_argument("project", help="YAML file or directory containing book.yaml")
    inspect.add_argument("--output", metavar="DIR", help=output_help)
    inspect.add_argument("--json", action="store_true", help="Print structured facts")
    imported = actions.add_parser(
        "import",
        help="Copy a photograph (JPEG, PNG) or font (.ttf, .otf) into the project's cover-assets",
    )
    imported.add_argument("project", help="YAML file or directory containing book.yaml")
    imported.add_argument("photo", help="JPEG or PNG photograph, or a .ttf/.otf font")
    imported.add_argument("--json", action="store_true", help="Print a structured result")
    build = actions.add_parser("build", help="Build and write cover.pdf and cover.json")
    build.add_argument("project", help="YAML file or directory containing book.yaml")
    build.add_argument("--output", metavar="DIR", help=output_help)
    build.add_argument("--json", action="store_true", help="Print a structured build result")
    preflight = actions.add_parser(
        "preflight", help="Inspect a built cover: structural validity and KDP readiness"
    )
    preflight.add_argument("project", help="YAML file or directory containing book.yaml")
    preflight.add_argument("--output", metavar="DIR", help=output_help)
    preflight.add_argument("--json", action="store_true", help="Print the report JSON")
    preflight.add_argument(
        "--no-write", action="store_true", help="Do not write cover-preflight.json"
    )


def _json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=True, sort_keys=True, indent=2))


def _failure(error: "CoverError", as_json: bool, what: str) -> int:
    if as_json:
        _json(
            {
                "success": False,
                "stage": error.stage,
                "diagnostics": [issue.to_dict() for issue in error.issues],
            }
        )
    print(f"{what} failed at {error.stage}; nothing was written.", file=sys.stderr)
    for issue in error.issues:
        measured = f" (actual {issue.actual}; required {issue.required})" if issue.actual else ""
        where = f" [{issue.region}]" if issue.region else ""
        print(f"  [{issue.code}] {issue.message}{measured}{where}", file=sys.stderr)
    return 1


def _directory(loaded: LoadedProject, output: str | None) -> Path:
    from .cover.issues import CoverError
    from .interior.build import check_output_directory
    from .interior.issues import InteriorError

    try:
        return check_output_directory(
            Path(output) if output else loaded.output_directory, loaded.source_path.parent
        )
    except InteriorError as error:
        raise CoverError("output", error.issues) from error


def run_cover_command(args: argparse.Namespace) -> int:
    from .cover.issues import CoverError

    command = args.cover_command
    if command == "photos":
        return run_photos(args)
    loaded = load_project(args.project)
    try:
        if command == "import":
            return _import(loaded, args)
        if command == "inspect":
            return _inspect(loaded, args)
        if command == "build":
            return _build(loaded, args)
        return _preflight(loaded, args)
    except CoverError as error:
        return _failure(error, args.json, f"Cover {command}")


def _import(loaded: LoadedProject, args: argparse.Namespace) -> int:
    from .cover.assets import import_photo
    from .cover.issues import cover_error

    path = Path(args.photo)
    if path.suffix.lower() in (".ttf", ".otf"):
        return _import_font(loaded, args, path)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise cover_error("asset", "image_missing", f"Cannot read {path}: {error}") from error
    imported = import_photo(loaded.source_path.parent, data, path.name)
    info = imported.info
    if args.json:
        _json({"success": True, "path": imported.path, "reused": imported.reused} | info.to_dict())
        return 0
    verb = "Already present" if imported.reused else "Imported"
    print(f"{verb}: {imported.path}")
    print(
        f"Pixels: {info.width}x{info.height} upright, {info.format}, orientation {info.orientation}"
    )
    print("Reference it in book.yaml (the original bytes are kept unchanged):")
    print("cover:\n  image:")
    print(f"    path: {imported.path}\n    sha256: {info.sha256}")
    return 0


def _import_font(loaded: LoadedProject, args: argparse.Namespace, path: Path) -> int:
    from .cover.font_assets import import_font
    from .cover.issues import cover_error

    try:
        data = path.read_bytes()
    except OSError as error:
        raise cover_error("asset", "font_missing", f"Cannot read {path}: {error}") from error
    imported = import_font(loaded.source_path.parent, data, path.name)
    info = imported.info
    if args.json:
        _json({"success": True, "path": imported.path, "reused": imported.reused} | info.to_dict())
        return 0
    print(f"{'Already present' if imported.reused else 'Imported'}: {imported.path}")
    print(
        f"Font: {info.full_name} ({info.postscript_name}), {info.glyphs} characters, "
        f"embedding {info.embedding.replace('_', ' ')}"
    )
    print("Reference it in book.yaml (cover version 2) and record its license and source:")
    for line in (
        "cover:",
        "  fonts:",
        "  - id: my-font",
        f"    path: {imported.path}",
        f"    sha256: {info.sha256}",
        "    license: null  # e.g. SIL Open Font License 1.1",
        "    source: null  # where you obtained it",
    ):
        print(line)
    return 0


def _inspect(loaded: LoadedProject, args: argparse.Namespace) -> int:
    from .cover.assets import inspect_photo, read_asset
    from .cover.build import read_interior_facts
    from .cover.font_assets import load_cover_fonts
    from .cover.geometry import cover_geometry
    from .cover.issues import cover_error
    from .cover.layout import CoverCopy, layout_cover

    project = loaded.project
    if project.cover is None:
        raise cover_error("config", "cover_missing", "This project has no cover section.")
    directory = _directory(loaded, args.output)
    interior = read_interior_facts(directory, project)
    geometry = cover_geometry(
        interior.page_count, interior.trim_width, interior.trim_height, interior.paper
    )
    photos = {
        image.sha256: inspect_photo(read_asset(loaded.source_path.parent, image))
        for image in project.cover.images()
    }
    fonts = load_cover_fonts(loaded.source_path.parent, project.cover)
    layout = layout_cover(
        project.book.id, CoverCopy.from_project(project), project.cover, geometry, photos, fonts
    )
    resolution = layout.resolution
    data: dict[str, object] = {
        "success": True,
        "interior": interior.physical() | {"interior_identity": interior.interior_identity},
        "geometry": geometry.to_dict(),
        "resolution": None if resolution is None else resolution.to_dict(),
        "spine_text": layout.spine.to_dict(),
    }
    if project.cover.image is not None:
        data["photo"] = photos[project.cover.image.sha256].to_dict()
    else:
        data["photos"] = [
            {"role": item.role, **photos[item.sha256].to_dict(), "resolution": res.to_dict()}
            for item, res in zip(layout.photos, layout.resolutions, strict=True)
        ]
    if args.json:
        _json(data)
        return 0
    g, res, spine = geometry.to_dict(), layout.resolution, layout.spine
    print(f"Cover for {project.book.id}: {interior.page_count} pages, {interior.paper.value} paper")
    print(
        f"Full wrap: {g['width_in']:.4f} x {g['height_in']:.4f} in "
        f"(0.125 in bleed; spine {g['spine_width_in']:.4f} in)"
    )
    shown = {
        None: "printed",
        "page_count": "omitted (KDP prints spine text only from 80 pages)",
        "spine_too_narrow": "omitted (the spine cannot hold 7 pt type)",
        "authored": "omitted (spine_text: none)",
    }
    print(f"Spine text: {shown[spine.reason]}")
    for item, each in zip(layout.photos, layout.resolutions, strict=True):
        width, height = each.source_pixels
        name = "Photo" if item.role == "photo" else f"Photo {item.role.split(':', 1)[1]}"
        print(
            f"{name}: {width}x{height} px; effective {each.effective_dpi:.0f} DPI "
            f"(at most {each.max_dpi:.0f}); KDP minimum {each.minimum_dpi:g}: {each.status}"
        )
    if res is None:
        print("Photo: the design places no photograph")
    return 0


def _build(loaded: LoadedProject, args: argparse.Namespace) -> int:
    from .cover.build import build_cover, write_cover

    source = loaded.source_path.parent
    directory = _directory(loaded, args.output)
    build = build_cover(loaded.project, source, directory)
    written = write_cover(build, directory, source)
    manifest = build.manifest
    if args.json:
        _json(
            {
                "success": True,
                "output": {"pdf": str(written.pdf), "manifest": str(written.manifest)},
                "manifest": manifest,
            }
        )
        return 0
    g, res = build.layout.geometry.to_dict(), build.layout.resolution
    print(f"Cover: {written.pdf}")
    print(f"Manifest: {written.manifest}")
    print(
        f"Full wrap {g['width_in']:.4f} x {g['height_in']:.4f} in | spine "
        f"{g['spine_width_in']:.4f} in | {g['page_count']} pages, {g['paper']} paper"
    )
    if res is not None:
        print(f"Photo: {res.effective_dpi:.0f} DPI effective ({res.status})")
    print(f"Cover identity: {manifest['cover_identity']}")
    pdf = manifest["pdf"]
    assert isinstance(pdf, dict)
    print(f"PDF SHA-256: {pdf['sha256']}")
    print("Layout validated; PDF reopened and structurally verified. Run cover preflight next.")
    return 0


def _preflight(loaded: LoadedProject, args: argparse.Namespace) -> int:
    """Exit 0 only when structurally valid and KDP ready; 1 otherwise; 2 usage."""
    from .cover.build import write_cover_preflight
    from .cover.issues import CoverError
    from .cover.preflight import RULESET_ID, RULESET_VERSION, preflight_cover, report_bytes
    from .preflight import Severity

    source = loaded.source_path.parent
    directory = _directory(loaded, args.output)
    report = preflight_cover(loaded.project, source, directory)
    data = report_bytes(report)
    written: Path | None = None
    write_failed = False
    if not args.no_write and report.context.artifacts.manifest is not None:
        try:
            written = write_cover_preflight(data, report.book_id, directory, source)
        except CoverError as error:
            write_failed = error.issues[0].code == "write_failed"
            print(f"cover-preflight.json not written: {error.issues[0].message}", file=sys.stderr)
    if args.json:
        binary = getattr(sys.stdout, "buffer", None)
        if binary is None:
            sys.stdout.write(data.decode("ascii"))
        else:
            sys.stdout.flush()
            binary.write(data)
            binary.flush()
    else:
        print(f"Cover preflight: {report.book_id} ({RULESET_ID} v{RULESET_VERSION})")
        print(f"State: {report.state}")
        print(f"Structural: {'VALID' if report.structurally_valid else 'INVALID'}")
        print(f"KDP readiness: {'READY' if report.kdp_ready else 'NOT READY'}")
        for severity, heading in ((Severity.ERROR, "Blocking"), (Severity.WARNING, "Warnings")):
            found = [f for f in report.findings if f.severity is severity]
            print(f"{heading}: {len(found) or 'none'}")
            for finding in found:
                print(f"  {finding.rule.scope.value} [{finding.rule.code}] {finding.message}")
        if written:
            print(f"Report: {written}")
        print("Preflight checks the cover rules PuzzlePress models; Amazon KDP decides acceptance.")
    return 0 if report.kdp_ready and not write_failed else 1
