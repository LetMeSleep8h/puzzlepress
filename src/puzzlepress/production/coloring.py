"""`book produce` for coloring books: one verified, all-or-nothing production run.

    book.yaml + coloring-assets ──> interior.pdf/.json ──> preflight.json
                                ──> cover.pdf/.json ──> cover-preflight.json
    interior manifest + preflight ──> artwork-integrity.json
    artwork library ──> artwork-duplicates.json/.md
    publishing section ──> publishing-readiness.json, kdp-metadata.json
                       ──> publishing/ (the KDP upload package, only when ready)
    everything above ──> publishing-validation.json/.md ──> production.json

Every step reuses the single writers and checks of the shared pipeline: the
interior and cover builders, their preflights, publishing readiness and the
package writer. Nothing is rendered here.

Unlike the word-search run, which writes into the output as it goes, the whole
run is staged in a sibling directory, every file is read back against the
manifest, and only then is the staged directory swapped into place. A failed or
interrupted run leaves the previous output as it was and removes its staging
directory; a run that finishes with blocking findings is complete but is never
reported as ready. A lock file next to the output refuses a second concurrent
run for the same output. Originals in coloring-assets/ are read and verified,
never written.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import __version__
from ..models import Project
from ..project import LoadedProject

if TYPE_CHECKING:
    from ..preflight.engine import PreflightResult

from .produce import (
    KIND,
    MANIFEST_NAME,
    Item,
    ProductionResult,
    Validation,
    _fail,
    _json_bytes,
    _owned,
    check_disjoint,
    validation_markdown,
    write_file,
)

# 2 adds the engine, the environment and nested package files to production.json.
COLORING_VERSION = 2
INTEGRITY_NAME = "artwork-integrity.json"
DUPLICATES_JSON = "artwork-duplicates.json"
DUPLICATES_MD = "artwork-duplicates.md"
READINESS_NAME = "publishing-readiness.json"
METADATA_NAME = "kdp-metadata.json"
STAGING_PREFIX = ".produce-staging-"
PREVIOUS_PREFIX = ".produce-previous-"

COLORING_MANUAL_REVIEW = (
    (
        "artwork_review",
        "Look at every drawing at print size: line weight, faint or broken strokes, clipped "
        "details, dense dark areas and whether it is enjoyable to color. Automated checks "
        "measure ink and lines; they cannot judge a drawing.",
    ),
    (
        "print_previewer",
        "Upload interior.pdf and cover.pdf to KDP yourself and review them in Print "
        "Previewer; KDP decides acceptance.",
    ),
    (
        "physical_proof",
        "Order and inspect a printed proof: thin and light lines print differently on paper "
        "than on screen.",
    ),
    (
        "cover_appearance",
        "Check cover text legibility, artwork placement and RGB-to-CMYK color in the proof.",
    ),
    (
        "rights_and_disclosure",
        "Keep the evidence for your artwork rights declaration (licences, agreements, AI tool "
        "terms) and answer KDP's AI-generated content question for text and images yourself.",
    ),
)
GUARANTEE = (
    "Automated checks cover what PuzzlePress models. They cannot guarantee that Amazon KDP "
    "accepts the book, and they do not replace a person's review of the artwork and a "
    "printed proof."
)


@dataclass(frozen=True)
class ColoringRun:
    """What the staged run produced, before the swap."""

    validation: Validation
    readiness_ready: bool
    packaged: bool


def environment() -> dict[str, object]:
    """The toolchain that rendered the files; deflate and Pillow decide coloring PDF bytes."""
    from ..interior.coloring import coloring_toolchain

    toolchain = coloring_toolchain()
    return {
        "python": platform.python_version(),
        "image_library": toolchain["image_library"],
        "zlib": toolchain["zlib"],
    }


def _lock(path: Path) -> int:
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise _fail(
            "production_in_progress",
            f"Another production run holds {path.name}. Wait for it to finish; if no run is "
            "active (for example after a crash), delete that file and run again.",
        ) from error


def _previous_environment(directory: Path) -> dict[str, object] | None:
    try:
        data = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    recorded = data.get("environment") if isinstance(data, dict) else None
    return recorded if isinstance(recorded, dict) else None


def produce_coloring(
    loaded: LoadedProject, output: str | Path, profile: str | None = None
) -> ProductionResult:
    """Produce a coloring book into `output`; raises for unusable inputs or outputs."""
    project = loaded.project
    assert project.coloring is not None
    source = loaded.source_path.parent
    directory = check_disjoint(Path(output), [source])
    parent = directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    if directory.exists():
        _owned(directory, project.book.id)
    lock_path = parent / f".{directory.name}.produce.lock"
    handle = _lock(lock_path)
    staging: Path | None = None
    try:
        staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=parent))
        previous_environment = _previous_environment(directory) if directory.exists() else None
        run = _run(project, source, staging, profile, previous_environment)
        files = _manifest(project, staging, run)
        _verify(staging, files)
        _swap(staging, directory)
        staging = None
        return ProductionResult(directory, run.validation, files)
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        os.close(handle)
        lock_path.unlink(missing_ok=True)


def _run(
    project: Project,
    source: Path,
    staging: Path,
    profile: str | None,
    previous_environment: dict[str, object] | None,
) -> ColoringRun:
    from ..cover.build import build_cover, write_cover, write_cover_preflight
    from ..cover.issues import CoverError
    from ..cover.preflight import preflight_cover
    from ..cover.preflight import report_bytes as cover_report_bytes
    from ..interior import (
        DEFAULT_PROFILE,
        InteriorError,
        LayoutIssue,
        build_interior,
        print_profile,
        write_interior,
    )
    from ..interior.build import write_preflight_report
    from ..preflight import preflight_interior, read_interior_artifacts, report_bytes
    from ..print_config import ProfileConflict, chosen_profile

    try:
        chosen = chosen_profile(project.printing, profile)
    except ProfileConflict as conflict:
        raise InteriorError(
            "print_spec",
            (LayoutIssue("profile_conflict", str(conflict), region="print.profile"),),
        ) from conflict
    spec = print_profile(chosen or DEFAULT_PROFILE)
    if isinstance(spec, LayoutIssue):
        raise InteriorError("print_spec", (spec,))
    build = build_interior(project, spec, source)
    write_interior(build, staging, source)
    interior = preflight_interior(
        project, read_interior_artifacts(staging), build, source_directory=source
    )
    write_preflight_report(report_bytes(interior.report), project.book.id, staging, source)
    write_file(staging, INTEGRITY_NAME, _json_bytes(artwork_integrity(project, staging, interior)))

    duplicates = _duplicates(project, source)
    write_file(staging, DUPLICATES_JSON, _json_bytes(duplicates))
    write_file(staging, DUPLICATES_MD, duplicates_markdown(duplicates).encode())

    cover_report = None
    cover_error: str | None = None
    if project.cover is not None:
        try:
            cover = build_cover(project, source, staging)
            write_cover(cover, staging, source)
        except CoverError as error:
            cover_error = "; ".join(f"{i.code}: {i.message}" for i in error.issues)
        cover_report = preflight_cover(project, source, staging)
        if cover_report.context.artifacts.manifest is not None:
            write_cover_preflight(
                cover_report_bytes(cover_report), project.book.id, staging, source
            )

    readiness = None
    packaged = False
    if project.publishing is not None:
        from ..publishing import evaluate_readiness, readiness_bytes
        from ..publishing.package import assemble_package, write_package
        from ..publishing.submission import kdp_metadata

        readiness = evaluate_readiness(project, source, staging)
        write_file(staging, READINESS_NAME, readiness_bytes(readiness))
        write_file(staging, METADATA_NAME, _json_bytes(kdp_metadata(readiness)))
        if readiness.package_ready:
            write_package(assemble_package(readiness), staging, source)
            packaged = True

    validation = classify_coloring(
        project,
        interior.report,
        cover_report,
        cover_error,
        duplicates,
        readiness,
        previous_environment,
    )
    write_file(staging, "publishing-validation.json", _json_bytes(validation.to_dict()))
    write_file(staging, "publishing-validation.md", validation_markdown(validation).encode())
    return ColoringRun(validation, bool(readiness and readiness.package_ready), packaged)


# ---------------------------------------------------------------- reports


def artwork_integrity(
    project: Project, directory: Path, interior: PreflightResult
) -> dict[str, object]:
    """Each printed drawing: pinned original, prepared pixels, placement and findings.

    Read from the interior manifest just written and the fresh preflight of those
    exact bytes; nothing is re-derived here.
    """
    from ..preflight.model import Outcome

    book = project.coloring
    assert book is not None
    manifest = json.loads((directory / "interior.json").read_text(encoding="utf-8"))
    report = interior.report
    outcomes = {r.rule.code: r.outcome.value for r in report.results}
    checks = {
        code: outcomes.get(code, Outcome.NOT_EVALUATED.value)
        for code in (
            "coloring_artwork_sources",
            "coloring_image_integrity",
            "coloring_page_parity",
            "coloring_art_placement",
            "kdp_image_resolution",
            "coloring_blank_artwork",
            "coloring_excessive_ink",
            "coloring_thin_lines",
            "coloring_faint_lines",
            "coloring_line_quality",
            "pdf_matches_layout",
        )
    }
    findings: dict[str, list[dict[str, object]]] = {}
    for finding in report.findings:
        if finding.subject:
            findings.setdefault(finding.subject, []).append(
                {
                    "code": finding.rule.code,
                    "severity": finding.severity.value,
                    "message": finding.message,
                }
            )
    records: dict[str, dict[str, object]] = {}
    for record in manifest.get("artwork", []):
        key = str(record["id"])
        entry = records.get(key)
        if entry is None:
            art = book.artwork_by_id(key)
            entry = {
                "id": key,
                "title": art.title if art else None,
                "source_sha256": record["source_sha256"],
                "prepared": record["prepared"],
                "pixels": record["pixels"],
                "bits": record["bits"],
                "effective_dpi": record["effective_dpi"],
                "placement_in": record["placement_in"],
                "pages": [],
                "findings": findings.get(key, []),
            }
            records[key] = entry
        pages = entry["pages"]
        assert isinstance(pages, list)
        pages.append(record["page"])
    return {
        "kind": "puzzlepress-artwork-integrity",
        "version": 1,
        "book_id": project.book.id,
        "interior_identity": manifest.get("interior_identity"),
        "ruleset": report.ruleset.to_dict() if hasattr(report.ruleset, "to_dict") else None,
        "checks": checks,
        "verified": all(checks[c] == Outcome.PASSED.value for c in tuple(checks)[:4]),
        "artwork": [records[key] for key in sorted(records)],
        "originals": "Read and verified against their pinned SHA-256; never written.",
        "note": "Integrity and measured line quality only. Whether a drawing is good to color "
        "is a person's judgement.",
    }


def _duplicates(project: Project, source: Path) -> dict[str, object]:
    from ..coloring.assets import read_artwork
    from ..coloring.duplicates import find_duplicates
    from ..coloring.inspection import Inspection, inspect_artwork
    from ..coloring.issues import ArtworkError

    book = project.coloring
    assert book is not None
    inspections: dict[str, Inspection | None] = {}
    for art in book.artwork:
        try:
            inspections[art.id] = inspect_artwork(read_artwork(source, art), art.path)
        except ArtworkError:
            inspections[art.id] = None
    report = find_duplicates(book, inspections)
    return {"book_id": project.book.id, **report.to_dict()}


def duplicates_markdown(data: dict[str, object]) -> str:
    confirmed = data["confirmed"]
    possible = data["possible"]
    assert isinstance(confirmed, dict) and isinstance(possible, dict)
    lines = ["# Artwork duplicates", ""]
    same = confirmed["same_file"]
    repeated = confirmed["repeated_pages"]
    similar = possible["similar"]
    assert isinstance(same, list) and isinstance(repeated, list) and isinstance(similar, list)
    lines += ["## Confirmed", ""]
    lines += [
        f"- Same file under {', '.join(g['artwork'])} (pages {_pages(g['pages'])})" for g in same
    ]
    lines += [f"- {r['artwork']} prints on pages {_pages(r['pages'])}" for r in repeated]
    if not same and not repeated:
        lines.append("None.")
    lines += ["", f"## Possible ({possible['method']})", ""]
    lines += [
        f"- {' and '.join(p['artwork'])}: hash distance {p['hash_distance']}, map difference "
        f"{p['map_difference']}"
        for p in similar
    ] or ["None."]
    missing = data["not_compared"]
    assert isinstance(missing, list)
    lines += ["", "## Not compared", ""]
    lines += [f"- {key}" for key in missing] or ["None: every drawing was compared."]
    return "\n".join(lines) + "\n"


def _pages(pages: object) -> str:
    return ", ".join(str(p) for p in pages) if isinstance(pages, list) else "?"


def classify_coloring(
    project: Project,
    interior_report: object,
    cover_report: object | None,
    cover_error: str | None,
    duplicates: dict[str, object],
    readiness: object | None,
    previous_environment: dict[str, object] | None,
) -> Validation:
    """Sort every outcome: blocking, warnings, manual review (preflight `info` prompts
    included) and what was verified. Unevaluated required rules block."""
    from ..preflight.model import Outcome, Severity

    blocking: list[Item] = []
    warnings: list[Item] = []
    manual: list[Item] = []
    verified: list[str] = []

    def preflight(source: str, report: object) -> None:
        for result in getattr(report, "results", ()):
            if result.outcome is Outcome.NOT_EVALUATED:
                target = blocking if result.rule.severity is Severity.ERROR else manual
                target.append(
                    Item(
                        source,
                        result.rule.code,
                        f"Not evaluated: {result.note or result.rule.title}",
                    )
                )
        for finding in getattr(report, "findings", ()):
            target = (
                blocking
                if finding.severity is Severity.ERROR
                else manual
                if finding.severity is Severity.INFO
                else warnings
            )
            page = f" (PDF page {finding.page.physical_page})" if finding.page else ""
            target.append(Item(source, finding.rule.code, finding.message + page))

    preflight("interior_preflight", interior_report)
    if getattr(interior_report, "kdp_ready", False):
        verified.append(
            "Interior: page boxes, margins, page count, fonts, parity of coloring pages and "
            "blank backs, lossless artwork matching its prepared pixels, 300 DPI art under the "
            "modeled KDP rules and PuzzlePress line-art conventions."
        )
    if project.cover is None:
        blocking.append(
            Item("cover", "cover_not_configured", "No cover is configured; KDP needs one.")
        )
    else:
        if cover_error:
            blocking.append(Item("cover", "cover_build_failed", cover_error))
        if cover_report is not None:
            preflight("cover_preflight", cover_report)
            if getattr(cover_report, "kdp_ready", False):
                verified.append(
                    "Cover: wrap dimensions and spine width from the built page count, safe "
                    "areas, barcode area and image resolution under the modeled KDP rules."
                )
    confirmed = duplicates["confirmed"]
    assert isinstance(confirmed, dict)
    for group in confirmed["same_file"]:
        warnings.append(
            Item(
                "artwork_duplicates",
                "same_file",
                f"The same file is imported as {', '.join(group['artwork'])}.",
            )
        )
    for repeat in confirmed["repeated_pages"]:
        manual.append(
            Item(
                "artwork_duplicates",
                "repeated_pages",
                f"{repeat['artwork']} prints on pages {_pages(repeat['pages'])}; confirm the "
                "repeat is intended.",
            )
        )
    possible = duplicates["possible"]
    assert isinstance(possible, dict)
    for pair in possible["similar"]:
        manual.append(
            Item(
                "artwork_duplicates",
                "similar_artwork",
                f"{' and '.join(pair['artwork'])} look alike (a heuristic); compare them.",
            )
        )
    if not duplicates.get("complete", False):
        missing = duplicates["not_compared"]
        assert isinstance(missing, list)
        blocking.append(
            Item(
                "artwork_duplicates",
                "incomplete_comparison",
                "Not every drawing could be read for comparison: "
                + ", ".join(str(k) for k in missing)
                + ".",
            )
        )
    if readiness is None:
        blocking.append(
            Item(
                "publishing",
                "publishing_not_configured",
                "No publishing metadata; add it in Publishing to make a KDP package.",
            )
        )
    else:
        for finding in getattr(readiness, "findings", ()):
            # Interior and cover findings were listed from their own preflight above.
            if finding.related is not None:
                continue
            target = (
                blocking
                if finding.severity.value == "error"
                else manual
                if finding.severity.value == "info"
                else warnings
            )
            target.append(Item("publishing", finding.rule.code, finding.message))
        for result in getattr(readiness, "results", ()):
            if result.rule.severity.value == "error" and result.outcome.value == "not_evaluated":
                if not any(i.code == result.rule.code for i in blocking):
                    blocking.append(
                        Item("publishing", result.rule.code, f"Not evaluated: {result.note}")
                    )
        if getattr(readiness, "package_ready", False):
            verified.append(
                "Publishing: metadata, AI disclosure and artwork rights declared, confirmations "
                "current, interior and cover current; package assembled from the inspected bytes."
            )
    current = environment()
    if previous_environment is not None and previous_environment != current:
        warnings.append(
            Item(
                "environment",
                "environment_changed",
                f"The previous run used {previous_environment}; this one used {current}. Coloring "
                "PDF bytes depend on zlib and Pillow, so the files differ from the previous run's.",
            )
        )
    manual += [Item("manual", code, message) for code, message in COLORING_MANUAL_REVIEW]
    return Validation(tuple(blocking), tuple(warnings), tuple(manual), tuple(verified))


# ---------------------------------------------------------------- manifest and swap


def _listing(staging: Path) -> list[str]:
    names = []
    for path in sorted(staging.rglob("*")):
        if path.is_file():
            relative = path.relative_to(staging).as_posix()
            if not any(part.startswith(".") for part in relative.split("/")):
                names.append(relative)
    return [name for name in names if name != MANIFEST_NAME]


def _manifest(
    project: Project, staging: Path, run: ColoringRun
) -> tuple[tuple[str, str, int], ...]:
    from ..identity import build_identity
    from ..interior.build import toolchain

    files = tuple(
        (name, hashlib.sha256(data).hexdigest(), len(data))
        for name in _listing(staging)
        for data in ((staging / name).read_bytes(),)
    )
    interior = json.loads((staging / "interior.json").read_text(encoding="utf-8"))
    profile = interior.get("print_profile", {})
    validation = run.validation
    data = {
        "kind": KIND,
        "version": COLORING_VERSION,
        "engine": "coloring",
        "book_id": project.book.id,
        "engine_version": __version__,
        "build_identity": build_identity(project),
        "seed": str(project.build.seed),
        "profile": profile.get("profile_id") if isinstance(profile, dict) else None,
        "toolchain": toolchain(),
        "environment": environment(),
        "result": {
            "status": "ready_for_manual_kdp_submission"
            if not validation.blocking and run.packaged
            else "blocked",
            "package": "publishing/" if run.packaged else None,
            "blocking": len(validation.blocking),
            "warnings": len(validation.warnings),
            "manual_review": len(validation.manual),
            "guarantee": GUARANTEE,
        },
        "files": [{"name": n, "sha256": h, "bytes": b} for n, h, b in files],
    }
    write_file(staging, MANIFEST_NAME, _json_bytes(data))
    return files


def _verify(staging: Path, files: tuple[tuple[str, str, int], ...]) -> None:
    """Every staged file is present with the bytes the manifest lists, and nothing else."""
    expected = {name: (digest, size) for name, digest, size in files}
    if set(_listing(staging)) != set(expected):
        raise _fail("verification_failed", "The staged files differ from the manifest's list.")
    for name, (digest, size) in expected.items():
        data = (staging / name).read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise _fail("verification_failed", f"Staged {name} does not match the manifest.")


def _swap(staging: Path, directory: Path) -> None:
    """Put the verified run in place; the previous output survives until it is."""
    if not directory.exists():
        os.replace(staging, directory)
        return
    backup = Path(tempfile.mkdtemp(prefix=PREVIOUS_PREFIX, dir=directory.parent))
    backup.rmdir()
    os.replace(directory, backup)
    try:
        os.replace(staging, directory)
    except OSError as error:
        os.replace(backup, directory)
        raise _fail("write_failed", f"Could not put the new output in place: {error}") from error
    shutil.rmtree(backup, ignore_errors=True)
