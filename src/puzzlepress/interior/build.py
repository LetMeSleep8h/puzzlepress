"""Interior build pipeline and its only filesystem writer.

project -> generation -> plan -> plan verification -> digest binding -> layout
-> layout validation -> PDF -> PDF inspection -> atomic write of PDF + manifest.
`build_interior` is pure; `write_interior` is the single write boundary.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from reportlab import Version as REPORTLAB_VERSION

from .. import __version__
from ..batch import BatchReport
from ..engines.registry import engine_for
from ..identity import IDENTITY_VERSION
from ..models import Project
from ..publication import PublicationPlan
from .design import resolve_design, style_images, style_inputs
from .engine import RENDERER_VERSION, AnswerFit, answer_fits, layout_interior
from .fonts import font_manifest
from .inspection import PdfFacts, contract_issues, read_pdf_facts
from .issues import InteriorError, LayoutIssue
from .model import ImageBlock, InteriorLayout
from .render import render_pdf
from .spec import PrintSpecification, to_inches
from .validation import validate_layout

MANIFEST_VERSION = 1
PDF_NAME = "interior.pdf"
MANIFEST_NAME = "interior.json"
PREFLIGHT_NAME = "preflight.json"


@dataclass(frozen=True)
class InteriorBuild:
    report: BatchReport
    plan: PublicationPlan
    layout: InteriorLayout
    pdf: bytes
    manifest: dict[str, object]
    # What pypdf observed in exactly these PDF bytes. Preflight reuses it only for
    # artifact bytes equal to `pdf`; reading the same bytes again gives the same facts.
    facts: PdfFacts | None = None


@dataclass(frozen=True)
class InteriorOutput:
    pdf: Path
    manifest: Path


def _canonical(data: object) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def build_interior(
    project: Project, spec: PrintSpecification, source_directory: Path | None = None
) -> InteriorBuild:
    """Run the full pipeline in memory. Raises ProjectError or InteriorError.

    `source_directory` is the project folder; it is read only when the interior
    style prints photographs from cover-assets.
    """
    from .images import InteriorPhotos, encode_gray, load_photos

    engine = engine_for(project)
    report, plan = engine.build_publication(project)
    verification = engine.verify_publication(plan, project, report)
    if not verification.valid:
        raise RuntimeError(f"Publication plan failed verification: {verification.issues!r}")
    style = project.interior
    photos = load_photos(source_directory, style.images() if style else ())
    placed = InteriorPhotos(style_images(style), {k: v.info for k, v in photos.items()})
    layout = layout_interior(plan, report, spec, resolve_design(style), placed)
    layout_issues = validate_layout(layout, plan, report)
    if layout_issues:
        raise InteriorError("layout_validation", layout_issues)
    encoded = {
        (page.number, element.role): encode_gray(photos[element.sha256], element)
        for page in layout.pages
        for element in page.elements
        if isinstance(element, ImageBlock)
    }
    pdf = render_pdf(layout, encoded)
    facts = read_pdf_facts(pdf)
    pdf_issues = (facts,) if isinstance(facts, LayoutIssue) else contract_issues(facts, layout)
    if pdf_issues:
        raise InteriorError("pdf_verification", pdf_issues)
    assert not isinstance(facts, LayoutIssue)
    manifest = interior_manifest(layout, pdf, style_inputs(project.interior))
    return InteriorBuild(report, plan, layout, pdf, manifest, facts)


# Manifest fields that, together, are the interior identity's inputs. `style`
# (the resolved interior style) is an input only when the book has one, so
# interiors without a style keep their identities.
IDENTITY_INPUTS = (
    "identity",
    "plan_digest",
    "print_profile",
    "renderer_version",
    "engine_version",
    "pdf_library",
    "fonts",
)
OPTIONAL_INPUTS = ("style",)


def toolchain() -> dict[str, object]:
    """Output-affecting renderer inputs other than source, plan and profile."""
    return {
        "renderer_version": RENDERER_VERSION,
        "engine_version": __version__,
        "pdf_library": f"reportlab {REPORTLAB_VERSION}",
        "fonts": font_manifest(),
    }


def interior_identity(inputs: dict[str, object]) -> str:
    material = {key: inputs[key] for key in IDENTITY_INPUTS}
    material |= {key: inputs[key] for key in OPTIONAL_INPUTS if key in inputs}
    digest = hashlib.sha256(_canonical(material)).hexdigest()
    return f"pp{IDENTITY_VERSION}-interior-sha256-{digest}"


def interior_manifest(
    layout: InteriorLayout, pdf: bytes, style: dict[str, object] | None = None
) -> dict[str, object]:
    """Deterministic traceability record. It contains no timestamps or paths."""
    spec = layout.spec
    inputs = {
        "identity": layout.identity,
        "plan_digest": layout.plan_digest,
        "print_profile": spec.to_dict(),
        **toolchain(),
    }
    if style is not None:
        inputs["style"] = style
    return {
        "manifest_version": MANIFEST_VERSION,
        "book_id": layout.book_id,
        "interior_identity": interior_identity(inputs),
        **inputs,
        "trim": {
            "name": spec.trim.name,
            "width_in": to_inches(spec.trim.width),
            "height_in": to_inches(spec.trim.height),
            "bleed": spec.bleed,
        },
        "page_count": len(layout.pages),
        "pdf": {
            "file": PDF_NAME,
            "sha256": hashlib.sha256(pdf).hexdigest(),
            "bytes": len(pdf),
        },
        "warnings": [issue.to_dict() for issue in layout.warnings],
    }


def _output_issue(code: str, message: str) -> InteriorError:
    return InteriorError("output", (LayoutIssue(code, message, region="output"),))


def check_output_directory(output: Path, source_directory: Path) -> Path:
    """Resolve at write time and keep generated files disjoint from source."""
    try:
        resolved = output.resolve()
        source = source_directory.resolve()
    except (OSError, RuntimeError) as error:
        raise _output_issue("output_unavailable", f"Cannot resolve output: {error}") from error
    if resolved.is_relative_to(source) or source.is_relative_to(resolved):
        raise _output_issue("source_overlap", "Output and source directories must be disjoint.")
    if resolved.exists() and not resolved.is_dir():
        raise _output_issue("not_directory", f"Output is not a directory: {resolved}")
    return resolved


def _check_ownership(directory: Path, book_id: str) -> None:
    """Replace only an interior this book previously wrote; never unrelated files."""
    pdf, manifest = directory / PDF_NAME, directory / MANIFEST_NAME
    for path in (pdf, manifest):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise _output_issue("output_collision", f"Refusing to replace {path.name}.")
    if not manifest.exists():
        if pdf.exists():
            raise _output_issue(
                "output_collision",
                f"{PDF_NAME} exists without a PuzzlePress manifest; refusing to replace it.",
            )
        return
    try:
        existing = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise _output_issue(
            "output_collision", f"Existing {MANIFEST_NAME} is unreadable: {error}"
        ) from error
    if not isinstance(existing, dict) or existing.get("book_id") != book_id:
        raise _output_issue(
            "output_collision", f"{MANIFEST_NAME} belongs to another book; refusing to replace it."
        )


def _stage(directory: Path, data: bytes, suffix: str, prefix: str = ".interior-") -> Path:
    handle, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    path = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != data:
            raise _output_issue("write_failed", "Staged output does not match rendered bytes.")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def write_interior(build: InteriorBuild, output: Path, source_directory: Path) -> InteriorOutput:
    """Atomically replace interior.pdf and interior.json in the output directory.

    Files are staged beside their targets, verified, then moved with os.replace,
    so a failure never leaves a partial PDF under the final name.
    """
    directory = check_output_directory(output, source_directory)
    manifest_bytes = (
        json.dumps(build.manifest, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode("ascii")
    staged: list[Path] = []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Recheck after creation: a symlinked or racing directory must still be disjoint.
        directory = check_output_directory(directory, source_directory)
        _check_ownership(directory, build.layout.book_id)
        staged.append(_stage(directory, build.pdf, ".pdf.tmp"))
        staged.append(_stage(directory, manifest_bytes, ".json.tmp"))
        pdf, manifest = directory / PDF_NAME, directory / MANIFEST_NAME
        os.replace(staged[0], pdf)
        os.replace(staged[1], manifest)
        staged.clear()
    except OSError as error:
        raise _output_issue("write_failed", f"Cannot write interior: {error}") from error
    finally:
        for path in staged:
            path.unlink(missing_ok=True)
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != hashlib.sha256(build.pdf).hexdigest():
        raise _output_issue("write_failed", "Written PDF does not match the verified bytes.")
    return InteriorOutput(pdf, manifest)


def write_preflight_report(data: bytes, book_id: str, output: Path, source_directory: Path) -> Path:
    """Atomically replace preflight.json beside an interior this book owns.

    The report is written only next to an existing manifest naming the same
    book; it never creates an output directory or touches the PDF or manifest.
    """
    directory = check_output_directory(output, source_directory)
    manifest, target = directory / MANIFEST_NAME, directory / PREFLIGHT_NAME
    if not directory.is_dir() or not manifest.is_file() or manifest.is_symlink():
        raise _output_issue("output_missing", "No interior manifest to report beside.")
    _check_ownership(directory, book_id)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise _output_issue("output_collision", f"Refusing to replace {PREFLIGHT_NAME}.")
    staged: Path | None = None
    try:
        staged = _stage(directory, data, ".preflight.tmp")
        os.replace(staged, target)
        staged = None
    except OSError as error:
        raise _output_issue("write_failed", f"Cannot write preflight report: {error}") from error
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return target


def style_currency(manifest: dict[str, object], project: Project) -> str | None:
    """Why a recorded interior's style differs from the project's, or None."""
    recorded = manifest.get("style")
    current = style_inputs(project.interior)
    if json.loads(json.dumps(current)) == recorded:
        return None
    if current is None:
        return "The interior style was removed after this interior was built."
    if recorded is None:
        return "An interior style was added after this interior was built."
    return "The interior style changed after this interior was built."


@dataclass(frozen=True)
class SamplePage:
    """One rendered preview page and what it represents (`roles`)."""

    physical_page: int
    kind: str
    folio: str | None
    roles: tuple[str, ...]


@dataclass(frozen=True)
class InteriorSample:
    """A draft preview: the whole book laid out and validated, a few pages rendered."""

    pdf: bytes
    pages: tuple[SamplePage, ...]  # One per PDF page, in book order.
    page_count: int
    warnings: tuple[LayoutIssue, ...]


def answer_layouts(
    project: Project, spec: PrintSpecification, publication: tuple[BatchReport, PublicationPlan]
) -> tuple[AnswerFit, ...]:
    """How every solutions-per-page choice would print this book's solution grids."""
    report, plan = publication
    sizes = tuple(
        sorted(
            {
                (r.puzzle.config.size.width, r.puzzle.config.size.height)
                for r in report.puzzles
                if r.puzzle is not None
            }
        )
    )
    composition = project.composition
    heading = composition.solutions.title if composition is not None else None
    return answer_fits(spec, resolve_design(project.interior), sizes, heading)


def sample_roles(layout: InteriorLayout, plan: PublicationPlan) -> dict[int, list[str]]:
    """Representative pages by physical number: what a design preview should show.

    `spread_left`/`spread_right`: the first facing pair of puzzle pages (a word
    list and its grid in spread books); `puzzle`: the first grid page; `answers`:
    the first solution page holding the most solutions; `answers_last`: the final
    solution page when it holds fewer; and the first title, divider and
    instructions pages.
    """
    from ..publication import PageKind

    roles: dict[int, list[str]] = {}

    def mark(number: int | None, role: str) -> None:
        if number is not None:
            roles.setdefault(number, []).append(role)

    kinds = [page.kind for page in plan.pages]
    puzzle_kinds = (PageKind.PUZZLE, PageKind.PUZZLE_WORDS)
    for kind, role in (
        (PageKind.TITLE_PAGE, "title"),
        (PageKind.INSTRUCTIONS, "instructions"),
        (PageKind.DIVIDER, "divider"),
        (PageKind.PUZZLE, "puzzle"),
    ):
        mark(next((p.index for p in plan.pages if p.kind is kind), None), role)
    for left in plan.pages:
        index = left.index
        if left.side.value == "verso" and left.kind in puzzle_kinds and index < len(kinds):
            if kinds[index] is PageKind.PUZZLE:
                mark(index, "spread_left")
                mark(index + 1, "spread_right")
                break
    solutions = [p for p in plan.pages if p.kind is PageKind.SOLUTIONS]
    if solutions:
        most = max(len(p.solutions) for p in solutions)
        full = next(p for p in solutions if len(p.solutions) == most)
        mark(full.index, "answers")
        if len(solutions[-1].solutions) < most:
            mark(solutions[-1].index, "answers_last")
    assert len(layout.pages) == len(plan.pages)
    return roles


def sample_interior(
    project: Project,
    spec: PrintSpecification,
    source_directory: Path | None = None,
    publication: tuple[BatchReport, PublicationPlan] | None = None,
) -> InteriorSample:
    """Lay out every page, then render the representative pages `sample_roles` picks.

    The same engine, validation and renderer as `build_interior`; only the set of
    pages drawn differs, so a style edit never renders the whole book. Raises
    ProjectError or InteriorError. `publication` reuses a generation and plan
    made from this exact source (styles never change them).
    """
    from dataclasses import replace

    from .images import InteriorPhotos, encode_gray, load_photos

    engine = engine_for(project)
    report, plan = publication or engine.build_publication(project)
    verification = engine.verify_publication(plan, project, report)
    if not verification.valid:
        raise RuntimeError(f"Publication plan failed verification: {verification.issues!r}")
    style = project.interior
    photos = load_photos(source_directory, style.images() if style else ())
    placed = InteriorPhotos(style_images(style), {k: v.info for k, v in photos.items()})
    layout = layout_interior(plan, report, spec, resolve_design(style), placed)
    issues = validate_layout(layout, plan, report)
    if issues:
        raise InteriorError("layout_validation", issues)
    roles = sample_roles(layout, plan)
    chosen = [page for page in layout.pages if page.number in roles]
    sample = replace(layout, pages=tuple(chosen))
    encoded = {
        (page.number, element.role): encode_gray(photos[element.sha256], element)
        for page in chosen
        for element in page.elements
        if isinstance(element, ImageBlock)
    }
    return InteriorSample(
        render_pdf(sample, encoded),
        tuple(
            SamplePage(page.number, page.kind, page.folio, tuple(roles[page.number]))
            for page in chosen
        ),
        len(layout.pages),
        layout.warnings,
    )
