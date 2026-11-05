"""The coloring-book preflight ruleset (`puzzlepress-kdp-coloring`).

A separate ruleset, so word-search reports keep their bytes and version. Shared
print checks (artifacts, identity, page boxes, fonts, margins, KDP page limits)
reuse the word-search evaluators unchanged under the same stable codes; coloring
adds rules for its artwork, image integrity, parity and line quality.

Severities: `error` blocks its scope; `warning` is a measured problem worth
fixing; `info` is a manual-review prompt, never a verdict (Studio and the CLI say
"manual review"): PuzzlePress measures lines, ink and paper, but whether a drawing
is good is a person's judgement. The shared severity scale is unchanged, so cover,
publishing and word-search reports keep their bytes. Every
threshold here is a PuzzlePress convention (docs/coloring.md), not a KDP value,
and no result guarantees acceptance by Amazon KDP.

Preflight observes: it reads the artifacts and the artwork, rebuilds the expected
interior in memory, and never writes, repairs or re-prepares anything on disk.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..cancellation import checkpoint
from ..coloring.content import ColoringContent
from ..coloring.duplicates import DuplicateReport, find_duplicates
from ..coloring.inspection import Inspection, inspect_artwork
from ..coloring.issues import ArtworkError, ArtworkFinding
from ..coloring.prepare import PreparationMeasures, measure_artwork
from ..coloring_config import Border, Placement
from ..interior.build import toolchain
from ..interior.coloring import (
    ART_ROLE,
    EmbeddedImage,
    bleed_crop,
    coloring_toolchain,
    image_integrity,
    validate_coloring_layout,
)
from ..interior.issues import LayoutIssue
from ..interior.model import ImageBlock
from ..interior.spec import KDP
from ..models import Project
from ..publication import REVERSE_BLANK_REASON, PageKind
from .context import Context
from .model import Basis, Category, Measure, Outcome, Scope, Severity
from .model import Rule as PreflightRule
from .rules import (
    CATALOGUE,
    CONTRACT,
    MARGINS,
    NO_LAYOUT,
    NO_PDF,
    SUBMISSION,
    Check,
    Evaluator,
    _finding,
    _matches,
    _na,
    _skip,
    kdp_safe_area,
)

RULESET_ID = "puzzlepress-kdp-coloring"
# 2: line quality also reports light strokes of the original that preparation erased.
# 3: line measures read each image relative to its own paper (measures version 2), so
#    background cleanup of tinted scans is no longer reported as fine-line loss.
# 4: full bleed (Interval 9): `coloring_bleed_art`, and the shared page-box, page-size,
#    margin, live-area and printer-mark rules judge full-bleed pages by their own boxes.
RULESET_VERSION = 4
BLEED_INK_NOTICE = 0.001  # Share of a drawing's ink worth a trimming note.
COLORING_CONTRACT = "PuzzlePress coloring interior contract (docs/coloring.md)"
QUALITY = "PuzzlePress line-art conventions (docs/coloring.md#calibration)"


@dataclass(frozen=True)
class ArtworkCheck:
    """One drawing as preflight read it: its preparation's measures and findings, and
    its inspection. No pixels are kept, so memory stays flat however long the book.
    """

    measures: PreparationMeasures | None = None  # None: the drawing could not be read.
    findings: tuple[ArtworkFinding, ...] = ()
    inspection: Inspection | None = None
    error: ArtworkError | None = None


@dataclass(frozen=True)
class ColoringContext(Context):
    artwork: dict[str, ArtworkCheck] = field(default_factory=dict)
    duplicates: DuplicateReport | None = None
    images: tuple[EmbeddedImage, ...] | LayoutIssue | None = None

    @property
    def content(self) -> ColoringContent | None:
        report = self.expected.report if self.expected is not None else None
        return report if isinstance(report, ColoringContent) else None

    @property
    def border(self) -> Border:
        book = self.project.coloring
        return book.layout.border if book is not None else Border.NONE

    @property
    def placements(self) -> dict[int, Placement]:
        book = self.project.coloring
        return book.placements if book is not None else {}

    def environment_change(self) -> list[tuple[str, object, object]]:
        """(field, recorded, running) for each deflate or image-library difference."""
        recorded = self.manifest.get("coloring") if self.manifest else None
        if not isinstance(recorded, dict):
            return []
        running = coloring_toolchain()
        return [
            (key, recorded.get(key), running[key])
            for key in ("zlib", "image_library")
            if recorded.get(key) != running[key]
        ]

    def pages_of(self, artwork_id: str) -> list[int]:
        """Physical pages of the current plan that print this drawing."""
        if self.expected is None:
            return []
        return [
            p.index
            for p in self.expected.plan.pages
            if p.artwork is not None and p.artwork.id == artwork_id
        ]


def load_artwork(project_directory: Path | None, project: Project) -> dict[str, ArtworkCheck]:
    """Read, verify, prepare (with measures) and inspect every drawing a page uses."""
    from ..coloring.assets import read_artwork

    book = project.coloring
    if book is None:
        return {}
    checks: dict[str, ArtworkCheck] = {}
    total = len({artwork_id for _, artwork_id in book.artwork_pages})
    for _, artwork_id in book.artwork_pages:
        if artwork_id in checks:
            continue
        checkpoint("measure_artwork", len(checks), total)
        artwork = book.artwork_by_id(artwork_id)
        assert artwork is not None
        if project_directory is None:
            error = ArtworkError("project_folder_required", "No project folder to read.")
            checks[artwork_id] = ArtworkCheck(error=error.about(artwork.path))
            continue
        try:
            data = read_artwork(project_directory, artwork)
            measures, findings = measure_artwork(data, artwork.adjustments, artwork.path)
            checks[artwork_id] = ArtworkCheck(
                measures, findings, inspect_artwork(data, artwork.path)
            )
        except ArtworkError as error:
            checks[artwork_id] = ArtworkCheck(error=error.about(artwork.path))
    return checks


def duplicate_report(project: Project, checks: dict[str, ArtworkCheck]) -> DuplicateReport | None:
    if project.coloring is None:
        return None
    inspections = {key: check.inspection for key, check in checks.items()}
    return find_duplicates(project.coloring, inspections)


# ------------------------------------------------------------------- catalogue

COLORING_CATALOGUE: list[tuple[PreflightRule, Evaluator]] = []
_SHARED = {definition.code: (definition, evaluate) for definition, evaluate in CATALOGUE}


def shared(code: str, title: str | None = None, description: str | None = None) -> None:
    """Reuse a word-search rule's evaluator, with coloring wording where it differs."""
    definition, evaluate = _SHARED[code]
    if title or description:
        definition = PreflightRule(
            definition.code,
            definition.scope,
            definition.category,
            definition.severity,
            title or definition.title,
            description or definition.description,
            definition.basis,
            definition.source,
        )
    COLORING_CATALOGUE.append((definition, evaluate))


def rule(
    code: str,
    scope: Scope,
    category: Category,
    title: str,
    description: str,
    source: str,
    basis: Basis | None = None,
    severity: Severity = Severity.ERROR,
) -> Callable[[Evaluator], Evaluator]:
    if basis is None:
        basis = Basis.PUZZLEPRESS_CONTRACT if scope is Scope.STRUCTURAL else Basis.KDP_REQUIREMENT
    definition = PreflightRule(code, scope, category, severity, title, description, basis, source)

    def register(evaluate: Evaluator) -> Evaluator:
        COLORING_CATALOGUE.append((definition, evaluate))
        return evaluate

    return register


def _coloring(ctx: Context) -> ColoringContext:
    assert isinstance(ctx, ColoringContext)
    return ctx


# ----------------------------------------------------------------- structural

for _code in (
    "interior_artifacts",
    "manifest_format",
    "manifest_book",
    "manifest_pdf_digest",
    "interior_identity",
    "source_current",
    "print_profile_current",
):
    shared(_code)


@rule(
    "toolchain_current",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Renderer and fonts current",
    "Renderer, engine, PDF library, pinned fonts, coloring renderer and preparation "
    "versions equal the running toolchain.",
    CONTRACT,
)
def _toolchain(r: PreflightRule, ctx: Context) -> Check:
    manifest = ctx.manifest
    if manifest is None:
        return _skip("No readable manifest.")
    recorded = manifest.get("coloring")
    if not isinstance(recorded, dict):
        return Check(
            (_finding(r, "The manifest is not a coloring interior's.", region="coloring"),)
        )
    findings = []
    expected: list[tuple[str, object, object]] = [
        (key, manifest.get(key), value) for key, value in toolchain().items()
    ]
    running = coloring_toolchain()
    expected += [
        (f"coloring.{key}", recorded.get(key), running[key])
        for key in ("renderer_version", "preparation_version")
    ]
    for key, actual, value in expected:
        import json

        if actual != json.loads(json.dumps(value)):
            shown = actual if isinstance(actual, int | str) else "pinned font set"
            want = value if isinstance(value, int | str) else "pinned font set"
            findings.append(
                _finding(
                    r,
                    f"{key.replace('_', ' ').capitalize()} changed after this interior was built.",
                    region=key,
                    measure=Measure(shown, want, None, "equal"),
                )
            )
    return Check(tuple(findings), note="Renderer, preparation, ReportLab and fonts unchanged.")


@rule(
    "coloring_rendering_environment",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Rendering environment compatible",
    "The interior was rendered with this environment's deflate implementation (zlib or "
    "zlib-ng) and image library. Deflate output differs between implementations, so a "
    "PDF made under another one cannot be reproduced and compared byte for byte here.",
    COLORING_CONTRACT,
)
def _environment(r: PreflightRule, ctx: Context) -> Check:
    c = _coloring(ctx)
    if c.manifest is None:
        return _skip("No readable manifest.")
    changes = c.environment_change()
    return Check(
        tuple(
            _finding(
                r,
                f"This interior was rendered with {recorded or 'an unrecorded ' + key}; this "
                f"environment has {running}. Its bytes cannot be reproduced here. Rebuild the "
                "interior in this environment, or run preflight where it was built.",
                region=f"coloring.{key}",
                measure=Measure(str(recorded), str(running), None, "equal"),
            )
            for key, recorded, running in changes
        ),
        note="Rendered with this environment's zlib and Pillow.",
    )


shared(
    "source_buildable",
    description="The current source prepares every drawing and lays out without diagnostics.",
)


@rule(
    "plan_current",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Plan current",
    "The manifest's plan digest equals the digest of the current verified plan, which "
    "names every page's prepared pixels.",
    CONTRACT,
)
def _plan_current(r: PreflightRule, ctx: Context) -> Check:
    if ctx.manifest is None or ctx.expected is None:
        return _skip("No readable manifest or no current layout.")
    expected = ctx.expected.layout.plan_digest
    if ctx.manifest["plan_digest"] != expected:
        return Check(
            (
                _finding(
                    r,
                    "The artwork, its preparation, the page order or the composition changed "
                    "after this interior was built.",
                    region="plan_digest",
                    measure=Measure(str(ctx.manifest["plan_digest"]), expected, None, "equal"),
                ),
            )
        )
    return Check(note="Plan digest unchanged.")


@rule(
    "pdf_matches_layout",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "PDF equals deterministic render",
    "The PDF's bytes equal a fresh render of the current verified layout. Geometry "
    "rules apply to the PDF only when this holds. Not evaluated, and therefore never "
    "passing, when the rendering environment differs.",
    CONTRACT,
)
def _coloring_matches(r: PreflightRule, ctx: Context) -> Check:
    changes = _coloring(ctx).environment_change()
    if changes and ctx.expected is not None and not ctx.matches_layout:
        names = ", ".join(f"{recorded} (here {running})" for _, recorded, running in changes)
        return _skip(
            f"Not comparable: rendered with {names}. Rebuild in this environment, or "
            "preflight where it was built."
        )
    return _matches(r, ctx)


for _code in (
    "pdf_readable",
    "page_count",
    "page_boxes",
    "page_rotation",
    "pdf_interactive_features",
    "fonts_bundled",
):
    shared(_code)


@rule(
    "raster_images",
    Scope.STRUCTURAL,
    Category.CONTENT,
    "Raster images are the layout's",
    "Raster images appear only where the verified layout places a drawing (one per "
    "coloring page); any other image is foreign.",
    CONTRACT,
)
def _images(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    if ctx.expected is None:
        return _skip("No current layout to attribute the images to.")
    placed = {
        page.number: sum(isinstance(e, ImageBlock) for e in page.elements)
        for page in ctx.expected.layout.pages
    }
    return Check(
        tuple(
            _finding(
                r,
                f"{p.images} image(s) on the page; the layout places {placed.get(p.number, 0)}.",
                ctx,
                p.number,
                region="images",
            )
            for p in ctx.facts.pages
            if p.images != placed.get(p.number, 0)
        ),
        note=f"{sum(placed.values())} drawing(s), as the layout places them.",
    )


@rule(
    "coloring_image_integrity",
    Scope.STRUCTURAL,
    Category.CONTENT,
    "Drawings embedded losslessly",
    "Each coloring page embeds exactly its prepared pixels: Flate-compressed DeviceGray "
    "at the prepared size and bit depth, decoding to the prepared pixel digest. No JPEG, "
    "resampling or other image. Checked by decoding the PDF's own image streams.",
    COLORING_CONTRACT,
)
def _integrity(r: PreflightRule, ctx: Context) -> Check:
    c = _coloring(ctx)
    if c.artifacts.pdf is None or c.facts is None:
        return _skip(NO_PDF)
    content = c.content
    if c.expected is None or content is None:
        return _skip("No current layout to compare the images with.")
    if c.facts.page_count != len(c.expected.layout.pages):
        return _skip("The PDF's page count differs from the current layout.")
    images = c.images
    if isinstance(images, LayoutIssue):
        return Check((_finding(r, images.message, region="images"),))
    assert images is not None
    issues = image_integrity(images, c.expected.layout, content)
    drawings = sum(1 for p in c.expected.layout.pages for e in p.elements if e.role == ART_ROLE)
    return Check(
        tuple(
            _finding(r, i.message, ctx, i.physical_page, region=i.code, subject=i.subject)
            for i in issues
        ),
        note=f"{drawings} drawing(s) embedded losslessly and pixel-identical to their "
        "prepared pixels.",
    )


@rule(
    "coloring_artwork_sources",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Artwork present and unaltered",
    "Every drawing a page uses is in coloring-assets and still matches the SHA-256 the "
    "source pins for it.",
    COLORING_CONTRACT,
)
def _sources(r: PreflightRule, ctx: Context) -> Check:
    c = _coloring(ctx)
    if not c.artwork:
        return Check(note="No drawings are used.")
    findings = tuple(
        _finding(r, f"{check.error.message}", subject=key, region=check.error.code)
        for key, check in sorted(c.artwork.items())
        if check.error is not None
    )
    return Check(findings, note=f"{len(c.artwork)} drawing(s) present and unchanged.")


@rule(
    "coloring_page_parity",
    Scope.STRUCTURAL,
    Category.PAGE,
    "Page order and parity",
    "Coloring pages follow coloring.pages; the artwork section starts on a right-hand "
    "page when asked; with blank reverses every coloring page is a right-hand page whose "
    "back is blank; section dividers start on a right-hand page.",
    COLORING_CONTRACT,
)
def _parity(r: PreflightRule, ctx: Context) -> Check:
    from ..coloring.plan import verify_coloring_plan

    c = _coloring(ctx)
    plan, content = c.plan, c.content
    if plan is None or content is None or c.facts is None:
        return _skip(NO_LAYOUT)
    findings = [
        _finding(r, issue.message, region=f"{issue.path}:{issue.code}")
        for issue in verify_coloring_plan(plan, c.project, content).issues
    ]
    for page in plan.pages:
        printed = c.facts.pages[page.index - 1]
        if page.blank_reason == REVERSE_BLANK_REASON and (printed.painted or printed.text.strip()):
            findings.append(
                _finding(r, "A reverse blank page has content.", ctx, page.index, region="reverse")
            )
    art = [p for p in plan.pages if p.kind is PageKind.COLORING]
    reverses = sum(p.blank_reason == REVERSE_BLANK_REASON for p in plan.pages)
    recto = sum(p.index % 2 == 1 for p in art)
    return Check(
        tuple(findings),
        note=f"{recto} of {len(art)} coloring page(s) on right-hand pages; {reverses} blank "
        "reverse(s).",
        measure=Measure(recto, len(art), "pages", "equal") if art else None,
    )


@rule(
    "coloring_art_placement",
    Scope.STRUCTURAL,
    Category.GEOMETRY,
    "Artwork placement",
    "Each drawing prints whole: uniformly scaled, unclipped, inside its art box (the live "
    "area above the page number, inside any border), with the border clear of it.",
    COLORING_CONTRACT,
)
def _placement(r: PreflightRule, ctx: Context) -> Check:
    c = _coloring(ctx)
    if c.layout is None or c.plan is None or c.content is None:
        return _skip(NO_LAYOUT)
    issues = validate_coloring_layout(c.layout, c.plan, c.content, c.border, c.placements)
    return Check(
        tuple(_finding(r, i.message, ctx, i.physical_page, region=i.code) for i in issues),
        note="Every drawing whole, uniformly scaled and inside its art box.",
    )


@rule(
    "coloring_bleed_art",
    Scope.KDP,
    Category.CONTENT,
    "Full-bleed drawings and trimming",
    "On a full-bleed page, a drawing that fills the page covers the bleed edges (top, "
    "bottom, outside) and the inside margin. Reported for review: line work cropped off "
    "the page, printed only in the bleed (cut at trimming), or inside the trim but outside "
    "KDP's safe area (0.375 in, gutter by page count), each above 0.1 % of the drawing's "
    "ink. Nothing is moved or rescaled to avoid it.",
    MARGINS,
    severity=Severity.WARNING,
)
def _bleed_art(r: PreflightRule, ctx: Context) -> Check:
    c = _coloring(ctx)
    if c.layout is None or c.content is None:
        return _skip(NO_LAYOUT)
    filled = [
        (page, element)
        for page in c.layout.pages
        for element in page.elements
        if isinstance(element, ImageBlock) and element.bleed
    ]
    if not filled:
        return _na("No drawing fills a page.")
    count = len(c.layout.pages)
    findings = []
    for page, block in filled:
        art = next(
            (a for a in c.content.art.values() if a.digest == block.sha256),
            None,
        )
        safe = kdp_safe_area(c.layout.spec, count, page.frame.recto, page.frame.trim)
        if art is None or safe is None:
            continue
        crop = bleed_crop(art.image(), block, page.frame.trim, safe)
        for share, what in (
            (crop.hidden, "is cropped off the page (outside the bleed)"),
            (crop.trimmed, "prints only in the bleed and is cut off at trimming"),
            (crop.unsafe, "lies inside the trim but outside the safe area"),
        ):
            if share > BLEED_INK_NOTICE:
                findings.append(
                    _finding(
                        r,
                        f"{share:.1%} of the drawing's line work {what}; check the crop "
                        "in Pages and move or zoom the drawing if that detail matters.",
                        ctx,
                        page.number,
                        region="bleed_art",
                        bounds=block.box,
                        measure=Measure(
                            round(share * 100, 2), BLEED_INK_NOTICE * 100, "%", "at_most"
                        ),
                    )
                )
    return Check(
        tuple(findings),
        note=f"{len(filled)} drawing(s) fill their page; trimming effects measured.",
    )


for _code in ("blank_pages", "folios_printed", "content_in_live_area"):
    shared(_code)

# ------------------------------------------------------------------------ KDP

for _code in (
    "kdp_minimum_page_count",
    "kdp_maximum_page_count",
    "kdp_trim_size",
    "kdp_page_size",
    "kdp_no_bleed",
    "kdp_gutter",
    "kdp_outside_margins",
):
    shared(_code)
shared(
    "kdp_minimum_font_size",
    description=f"All text (titles, matter and page numbers) is at least {KDP.min_font_size:g} pt.",
)
shared(
    "kdp_minimum_line_weight",
    description=f"Rules and page borders are at least {KDP.min_line_weight:g} pt (KDP also "
    "states 0.01 in, which is 0.72 pt; the stricter value applies). Line weights inside a "
    "drawing are measured by the line-quality rules, not here.",
)
for _code in (
    "kdp_fonts_embedded",
    "kdp_full_font_embedding",
    "kdp_no_annotations",
    "kdp_not_encrypted",
    "kdp_flattened",
    "kdp_no_printer_marks",
):
    shared(_code)


@rule(
    "kdp_image_resolution",
    Scope.KDP,
    Category.CONTENT,
    "Image resolution",
    f"Each drawing prints at {KDP.min_image_dpi:g} DPI or more: its prepared pixels per "
    "printed inch at its placement.",
    SUBMISSION,
)
def _resolution(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    if ctx.layout is None:
        if not any(p.images for p in ctx.facts.pages):
            return Check(note="No drawings.")
        return _skip(NO_LAYOUT)
    blocks = [
        (page.number, e) for page in ctx.layout.pages for e in page.elements
        if isinstance(e, ImageBlock)
    ]  # fmt: skip
    if not blocks:
        return Check(note="No drawings.")
    lowest = min(block.effective_dpi for _, block in blocks)
    findings = []
    for number, block in blocks:
        if block.effective_dpi + 1e-9 >= KDP.min_image_dpi:
            continue
        need = (
            round(block.placement.width / 72 * KDP.min_image_dpi),
            round(block.placement.height / 72 * KDP.min_image_dpi),
        )
        findings.append(
            _finding(
                r,
                f"The drawing prints at {block.effective_dpi:.0f} DPI. Supply at least "
                f"{need[0]} x {need[1]} pixels for this placement.",
                ctx,
                number,
                region=block.role,
                bounds=block.box,
                measure=Measure(
                    round(block.effective_dpi, 1), KDP.min_image_dpi, "dpi", "at_least"
                ),
            )
        )
    return Check(
        tuple(findings),
        note=f"Lowest effective resolution {lowest:.0f} DPI.",
        measure=Measure(round(lowest, 1), KDP.min_image_dpi, "dpi", "at_least"),
    )


for _code in ("kdp_blank_page_runs", "kdp_page_number_parity", "kdp_no_metadata"):
    shared(_code)


# ---------------------------------------------------------------- line quality


def _quality(r: PreflightRule, ctx: Context, codes: tuple[str, ...], passed: str) -> Check:
    """Findings of the preparation measures (`coloring.prepare`) for these codes."""
    c = _coloring(ctx)
    if not c.artwork:
        return Check(note="No drawings are used.")
    unreadable = sorted(k for k, check in c.artwork.items() if check.measures is None)
    findings = []
    unmeasured: set[str] = set()
    for key, check in sorted(c.artwork.items()):
        if check.measures is None:
            continue
        unmeasured.update(check.measures.not_measured)
        for item in check.findings:
            if item.code not in codes:
                continue
            pages: list[int | None] = [*c.pages_of(key)] or [None]
            for page in pages:
                findings.append(
                    _finding(
                        r,
                        item.message,
                        ctx,
                        page,
                        subject=key,
                        region=item.code,
                        measure=Measure(item.actual, item.required) if item.actual else None,
                    )
                )
    if unreadable:
        return Check(
            tuple(findings),
            outcome=Outcome.NOT_EVALUATED,
            note=f"Not measured for unreadable drawing(s): {', '.join(unreadable)}.",
        )
    note = passed
    if unmeasured:
        note += f" Not measured on very dense drawings: {', '.join(sorted(unmeasured))}."
    return Check(tuple(findings), note=note)


def _quality_rule(
    code: str,
    severity: Severity,
    title: str,
    description: str,
    codes: tuple[str, ...],
    passed: str,
) -> None:
    def evaluate(r: PreflightRule, ctx: Context) -> Check:
        return _quality(r, ctx, codes, passed)

    register = rule(
        code, Scope.KDP, Category.CONTENT, title, description, QUALITY,
        Basis.PUZZLEPRESS_CONTRACT, severity,
    )  # fmt: skip
    register(evaluate)


_quality_rule(
    "coloring_blank_artwork",
    Severity.ERROR,
    "No blank coloring pages",
    "A coloring page's prepared drawing has at least 0.1% ink; an intentional blank is a "
    "plan blank page, never an empty drawing.",
    ("prepared_blank",),
    "Every drawing has line work.",
)
_quality_rule(
    "coloring_excessive_ink",
    Severity.ERROR,
    "Ink coverage",
    "A prepared drawing is at most 60% ink: more prints as a dark page with little to "
    "color (often white-on-black art that needs Invert).",
    ("excessive_ink",),
    "No drawing is mostly ink.",
)
_quality_rule(
    "coloring_thin_lines",
    Severity.ERROR,
    "Fine lines kept",
    "Preparation keeps at least 60% of the original one- and two-pixel line work.",
    ("thin_lines_destroyed",),
    "Fine line work survives preparation.",
)
_quality_rule(
    "coloring_heavy_ink",
    Severity.WARNING,
    "Heavy ink",
    "A prepared drawing over 35% ink prints heavy and leaves little to color.",
    ("heavy_ink",),
    "No drawing is heavily inked.",
)
_quality_rule(
    "coloring_gray_background",
    Severity.WARNING,
    "White paper",
    "The paper around the line work prints white (median 240 or lighter), not as a gray "
    "tint; use background cleanup to lift a scanned page.",
    ("background_tint",),
    "Every drawing's paper prints white.",
)
_quality_rule(
    "coloring_faint_lines",
    Severity.WARNING,
    "Lines print dark",
    "The darkest tenth of a drawing's line work (gray 200 or darker) reaches gray 64 "
    "(75% ink) or darker; paler lines print as light gray that is hard to color inside.",
    ("faint_lines",),
    "Every drawing's lines print dark.",
)
_quality_rule(
    "coloring_line_quality",
    Severity.WARNING,
    "Line quality",
    "Measured damage from preparation: fine lines thinned (under 90% kept), detail lost "
    "(under 60%), light strokes of the original erased (under 50% of gray 129-200 "
    "strokes still printed), strokes broken apart, isolated specks left (over 5 per "
    "megapixel) or ink pushed to an image edge.",
    (
        "thin_lines_lost",
        "detail_lost",
        "faint_strokes_erased",
        "strokes_broken",
        "specks_remaining",
        "prepared_touches_edge",
    ),
    "No measured line damage.",
)


@rule(
    "coloring_duplicate_artwork",
    Scope.KDP,
    Category.CONTENT,
    "Duplicate artwork",
    "The same drawing (byte-identical file) appears under two artwork entries or on more "
    "than one page.",
    QUALITY,
    Basis.PUZZLEPRESS_CONTRACT,
    Severity.WARNING,
)
def _duplicates(r: PreflightRule, ctx: Context) -> Check:
    report = _coloring(ctx).duplicates
    if report is None:
        return Check(note="No drawings are used.")
    findings = [
        _finding(
            r,
            f"The same file is used as {', '.join(group.artwork)} (coloring.pages entries "
            f"{', '.join(map(str, group.pages)) or 'none'}).",
            subject=group.artwork[0],
            region="same_file",
        )
        for group in report.same_file
    ]
    findings += [
        _finding(
            r,
            f"'{repeat.artwork}' is printed more than once (coloring.pages entries "
            f"{', '.join(map(str, repeat.pages))}).",
            subject=repeat.artwork,
            region="repeated_page",
        )
        for repeat in report.repeated_pages
    ]
    return Check(tuple(findings), note="No drawing is used twice.")


@rule(
    "coloring_similar_artwork",
    Scope.KDP,
    Category.CONTENT,
    "Possibly duplicate artwork",
    "Two different files look alike (difference hash and reduced ink map). A prompt to "
    "compare them, not a verdict.",
    QUALITY,
    Basis.PUZZLEPRESS_CONTRACT,
    Severity.INFO,
)
def _similar(r: PreflightRule, ctx: Context) -> Check:
    report = _coloring(ctx).duplicates
    if report is None:
        return Check(note="No drawings are used.")
    return Check(
        tuple(
            _finding(
                r,
                f"'{pair.artwork[0]}' and '{pair.artwork[1]}' look alike (hash distance "
                f"{pair.hash_distance}, ink map difference {pair.map_difference}). Compare them.",
                subject=pair.artwork[0],
                region="similar",
                measure=Measure(pair.hash_distance, None, "bits"),
            )
            for pair in report.similar
        ),
        note="No two drawings look alike.",
    )


_quality_rule(
    "coloring_visual_review",
    Severity.INFO,
    "Visual review of large changes",
    "Preparation changed a drawing a lot (mean change over 40 gray levels). Compare the "
    "original and prepared drawing; this is a prompt, not a defect. Artwork quality is "
    "always a person's judgement.",
    ("large_change",),
    "No drawing changed enough to prompt a comparison.",
)

COLORING_RULES = tuple(definition for definition, _ in COLORING_CATALOGUE)
if len({r.code for r in COLORING_RULES}) != len(COLORING_RULES):
    raise RuntimeError("Coloring preflight rule codes must be unique")
