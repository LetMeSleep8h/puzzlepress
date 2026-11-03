"""One reproducible production run into a separate output directory.

    book.yaml ──> interior.pdf/.json (puzzles + solutions) ──> preflight.json
              ──> cover.pdf/.json (when a cover is configured) ──> cover-preflight.json
    previous book(s) ──> duplicate-report.json/.md
    photo manifest (optional) ──> photo-check.json
    all of the above + an independent answer-key read-back ──> publishing-validation.json/.md
    every file's SHA-256 ──> production.json

Every step reuses the existing single writers and checks; this module adds no new
rendering. Findings are sorted into blocking failures, warnings and checks that
need a person; nothing is called KDP compliant here, and unevaluated rules block.
The output directory must be disjoint from the project, every previous book
source and the photo archive (the manifest's base folder, else its own folder),
and is reused only for the same book. No times are recorded, so the same source,
seed and toolchain give byte-identical files.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .. import __version__
from ..errors import ProjectError, ValidationIssue

MANIFEST_NAME = "production.json"
KIND = "puzzlepress-production-run"
VERSION = 1

MANUAL_REVIEW = (
    (
        "content_review",
        "Read every word list, title and matter text for spelling, terminology and "
        "suitability; automated checks verify placement, not meaning.",
    ),
    (
        "print_previewer",
        "Upload interior.pdf and cover.pdf to KDP yourself and review them in Print "
        "Previewer; KDP decides acceptance.",
    ),
    ("physical_proof", "Order and inspect a printed proof before publishing."),
    (
        "cover_appearance",
        "Check photo crop, text legibility, watermark visibility and RGB-to-CMYK color "
        "in the proof.",
    ),
    (
        "rights_and_metadata",
        "Confirm photo rights, AI disclosure, ISBN and metadata with `puzzlepress publish "
        "inspect`; PuzzlePress never decides these for the author.",
    ),
)


class ProductionError(ProjectError):
    pass


def _fail(code: str, message: str) -> ProductionError:
    return ProductionError((ValidationIssue("output", code, message),))


@dataclass(frozen=True)
class Item:
    source: str  # interior_preflight, cover_preflight, duplicates, photos, answer_key, run
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class Validation:
    blocking: tuple[Item, ...]
    warnings: tuple[Item, ...]
    manual: tuple[Item, ...]
    verified: tuple[str, ...]  # Properties actually checked and passing.

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "puzzlepress-publishing-validation",
            "version": 1,
            "blocking": [i.to_dict() for i in self.blocking],
            "warnings": [i.to_dict() for i in self.warnings],
            "manual_review": [i.to_dict() for i in self.manual],
            "verified": list(self.verified),
            "note": "Checks cover the constraints PuzzlePress models; Amazon KDP decides "
            "acceptance. Nothing here is a KDP approval.",
        }


@dataclass(frozen=True)
class ProductionResult:
    directory: Path
    validation: Validation
    files: tuple[tuple[str, str, int], ...] = field(default=())  # (name, sha256, bytes)

    @property
    def ready(self) -> bool:
        return not self.validation.blocking


def check_disjoint(output: Path, protected: Sequence[Path]) -> Path:
    """Refuse an output inside, equal to, or containing any protected path."""
    resolved = output.expanduser().resolve()
    for path in protected:
        guard = path.expanduser().resolve()
        guard = guard if guard.is_dir() or not guard.exists() else guard.parent
        if resolved.is_relative_to(guard) or guard.is_relative_to(resolved):
            raise _fail(
                "protected_overlap",
                f"Output {resolved} overlaps a protected source folder ({guard}); choose a "
                "separate output directory.",
            )
    if resolved.exists() and not resolved.is_dir():
        raise _fail("not_directory", f"Output is not a directory: {resolved}")
    return resolved


def _owned(directory: Path, book_id: str) -> None:
    manifest = directory / MANIFEST_NAME
    if not manifest.exists():
        return
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise _fail("output_collision", f"{MANIFEST_NAME} is unreadable: {error}") from error
    if not isinstance(data, dict) or data.get("kind") != KIND or data.get("book_id") != book_id:
        raise _fail("output_collision", f"{MANIFEST_NAME} belongs to another book or tool.")


def write_file(directory: Path, name: str, data: bytes) -> Path:
    """Stage beside the target, verify, then replace atomically."""
    target = directory / name
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise _fail("output_collision", f"Refusing to replace {name}.")
    handle, staged = tempfile.mkstemp(prefix=".production-", suffix=".tmp", dir=directory)
    path = Path(staged)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != data:
            raise _fail("write_failed", f"Staged {name} does not match.")
        os.replace(path, target)
    finally:
        path.unlink(missing_ok=True)
    return target


def _preflight_items(source: str, report: object) -> tuple[list[Item], list[Item], list[Item]]:
    from ..preflight.model import Outcome, Severity

    blocking: list[Item] = []
    warnings: list[Item] = []
    manual: list[Item] = []
    for result in getattr(report, "results", ()):
        rule = result.rule
        if result.outcome is Outcome.NOT_EVALUATED:
            target = blocking if rule.severity is Severity.ERROR else manual
            target.append(Item(source, rule.code, f"Not evaluated: {result.note or rule.title}"))
    for finding in getattr(report, "findings", ()):
        target = blocking if finding.severity is Severity.ERROR else warnings
        target.append(Item(source, finding.rule.code, finding.message))
    return blocking, warnings, manual


def classify(
    interior_report: object | None,
    cover_report: object | None,
    cover_configured: bool,
    duplicates: object | None,
    photos: object | None,
    answer_key: object | None,
) -> Validation:
    """Sort every check's outcome; `verified` names only properties that passed."""
    blocking: list[Item] = []
    warnings: list[Item] = []
    manual: list[Item] = []
    verified: list[str] = []
    if interior_report is not None:
        b, w, m = _preflight_items("interior_preflight", interior_report)
        blocking += b
        warnings += w
        manual += m
        if getattr(interior_report, "kdp_ready", False):
            verified.append(
                "Interior: trim, margins and gutter, no bleed, page count, font sizes and "
                "embedding, line weights, PDF integrity under the modeled KDP rules."
            )
    if not cover_configured:
        blocking.append(
            Item("cover", "cover_not_configured", "No cover is configured; KDP needs one.")
        )
    elif cover_report is not None:
        b, w, m = _preflight_items("cover_preflight", cover_report)
        blocking += b
        warnings += w
        manual += m
        if getattr(cover_report, "kdp_ready", False):
            verified.append(
                "Cover: wrap dimensions, spine width from the built page count, safe areas, "
                "barcode area, photo resolution, PDF structure under the modeled KDP rules."
            )
    if answer_key is not None:
        if answer_key.complete:  # type: ignore[attr-defined]
            verified.append(
                f"Answer key: all {answer_key.puzzles} puzzles have one matching solution "  # type: ignore[attr-defined]
                "grid marking every listed word (read back from interior.pdf)."
            )
        else:
            for issue in answer_key.issues[:50] or ("incomplete answer key",):  # type: ignore[attr-defined]
                blocking.append(Item("answer_key", "answer_key_mismatch", issue))
    if duplicates is None:
        warnings.append(
            Item(
                "duplicates",
                "no_previous_book",
                "No previous book was compared; pass --previous to check for repeats.",
            )
        )
    else:
        verdict = duplicates.verdict  # type: ignore[attr-defined]
        for match in duplicates.matches:  # type: ignore[attr-defined]
            blocking.append(
                Item(
                    "duplicates",
                    f"{match.severity}_duplicate",
                    f"{match.new_label} vs {match.other_source} {match.other_label}: "
                    + ", ".join(match.reasons),
                )
            )
        for inventory in (duplicates.new, *duplicates.previous):  # type: ignore[attr-defined]
            if not inventory.coverage.complete:
                blocking.append(
                    Item(
                        "duplicates",
                        "incomplete_coverage",
                        f"{inventory.label}: coverage {inventory.coverage.status}; "
                        + " ".join(inventory.coverage.notes),
                    )
                )
        if verdict == "clean":
            verified.append(
                "Duplicates: no exact or near-duplicate puzzles against the previous book(s) "
                "or within this book, with complete coverage."
            )
    if photos is not None:
        for check in photos.checks:  # type: ignore[attr-defined]
            for code, message in check.issues:
                target = blocking if check.status == "error" else warnings
                target.append(Item("photos", code, f"{check.entry.path}: {message}"))
    manual += [Item("manual", code, message) for code, message in MANUAL_REVIEW]
    return Validation(tuple(blocking), tuple(warnings), tuple(manual), tuple(verified))


def validation_markdown(validation: Validation) -> str:
    lines = ["# Publishing validation", ""]
    lines.append(
        "Result: **" + ("blocked" if validation.blocking else "no blocking failures") + "**. "
        "Amazon KDP decides acceptance; this is not a KDP approval."
    )
    for title, items in (
        ("Blocking failures", validation.blocking),
        ("Warnings", validation.warnings),
        ("Manual review", validation.manual),
    ):
        lines += ["", f"## {title} ({len(items)})", ""]
        lines += [f"- [{i.source}] {i.code}: {i.message}" for i in items] or ["None."]
    lines += ["", "## Verified", ""]
    lines += [f"- {v}" for v in validation.verified] or ["Nothing verified."]
    return "\n".join(lines) + "\n"


def _json_bytes(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def produce(
    project_path: str | Path,
    output: str | Path,
    previous: Sequence[str | Path] = (),
    expected_puzzles: int | None = None,
    thresholds: object | None = None,
    photo_manifest: str | Path | None = None,
    profile: str | None = None,
) -> ProductionResult:
    """Build everything into `output`; raises only for unusable inputs or outputs."""
    from ..answer_key import check_answer_key
    from ..cover.build import build_cover, write_cover, write_cover_preflight
    from ..cover.issues import CoverError
    from ..cover.preflight import preflight_cover
    from ..cover.preflight import report_bytes as cover_report_bytes
    from ..duplicates import Thresholds, compare_inventories, report_json, report_markdown
    from ..interior import (
        DEFAULT_PROFILE,
        InteriorError,
        LayoutIssue,
        build_interior,
        print_profile,
        write_interior,
    )
    from ..interior.build import write_preflight_report
    from ..inventory import inventory_from_project, load_inventory
    from ..photo_manifest import check_photos, load_manifest
    from ..preflight import preflight_interior, read_interior_artifacts, report_bytes
    from ..project import load_project
    from .candidates import replacement_candidates

    loaded = load_project(project_path)
    project = loaded.project
    source = loaded.source_path.parent
    protected = [source, *(Path(p) for p in previous)]
    manifest = None
    if photo_manifest is not None:
        manifest, folder = load_manifest(photo_manifest)
        # The photo archive is protected; the manifest file itself is only read.
        protected.append(Path(manifest.base_directory) if manifest.base_directory else folder)
    directory = check_disjoint(Path(output), protected)
    directory.mkdir(parents=True, exist_ok=True)
    _owned(directory, project.book.id)

    spec = print_profile(profile or DEFAULT_PROFILE)
    if isinstance(spec, LayoutIssue):
        raise InteriorError("print_spec", (spec,))
    build = build_interior(project, spec, source)
    written = write_interior(build, directory, source)
    interior = preflight_interior(
        project, read_interior_artifacts(directory), build, source_directory=source
    )
    write_preflight_report(report_bytes(interior.report), project.book.id, directory, source)
    answer_key = check_answer_key(written.pdf)

    cover_report = None
    cover_error: str | None = None
    if project.cover is not None:
        try:
            cover = build_cover(project, source, directory)
            write_cover(cover, directory, source)
        except CoverError as error:
            cover_error = "; ".join(f"{i.code}: {i.message}" for i in error.issues)
        cover_report = preflight_cover(project, source, directory)
        if cover_report.context.artifacts.manifest is not None:
            write_cover_preflight(
                cover_report_bytes(cover_report), project.book.id, directory, source
            )

    duplicates = None
    if previous:
        new = inventory_from_project(loaded.source_path)
        others = [load_inventory(p, expected_puzzles) for p in previous]
        duplicates = compare_inventories(
            new,
            others,
            thresholds if isinstance(thresholds, Thresholds) else None,
            replacement_candidates(project, others),
        )
        write_file(directory, "duplicate-report.json", report_json(duplicates).encode())
        write_file(directory, "duplicate-report.md", report_markdown(duplicates).encode())

    photos = None
    if manifest is not None:
        photos = check_photos(manifest, folder)
        write_file(directory, "photo-check.json", _json_bytes(photos.to_dict()))

    validation = classify(
        interior.report, cover_report, project.cover is not None, duplicates, photos, answer_key
    )
    if cover_error:
        validation = Validation(
            (Item("cover", "cover_build_failed", cover_error), *validation.blocking),
            validation.warnings,
            validation.manual,
            validation.verified,
        )
    write_file(directory, "publishing-validation.json", _json_bytes(validation.to_dict()))
    write_file(directory, "publishing-validation.md", validation_markdown(validation).encode())

    names = sorted(
        p.name
        for p in directory.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.name != MANIFEST_NAME
    )
    files = tuple(
        (name, hashlib.sha256(data).hexdigest(), len(data))
        for name in names
        for data in ((directory / name).read_bytes(),)
    )
    from ..identity import build_identity
    from ..interior.build import toolchain

    manifest_data = {
        "kind": KIND,
        "version": VERSION,
        "book_id": project.book.id,
        "engine_version": __version__,
        "build_identity": build_identity(project),
        "seed": str(project.build.seed),
        "profile": spec.profile_id,
        "toolchain": toolchain(),
        "inputs": {
            "previous": [
                {"label": o.label, "kind": o.source_kind, "sha256": o.source_sha256}
                for o in (duplicates.previous if duplicates else ())
            ],
            "expected_puzzles": expected_puzzles,
            "thresholds": (duplicates.thresholds.to_dict() if duplicates else None),
            "photo_manifest": photos is not None,
        },
        "result": {
            "blocking": len(validation.blocking),
            "warnings": len(validation.warnings),
            "manual_review": len(validation.manual),
        },
        "files": [{"name": n, "sha256": h, "bytes": b} for n, h, b in files],
    }
    write_file(directory, MANIFEST_NAME, _json_bytes(manifest_data))
    return ProductionResult(directory, validation, files)
