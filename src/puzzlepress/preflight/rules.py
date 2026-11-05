"""The preflight rule catalogue. Each rule observes the context and reports.

Rules never repair: they return findings, or say why they do not apply or could
not be evaluated. KDP values come only from `interior.spec.KDP`; geometry comes
only from the verified InteriorLayout the PDF was drawn from.
"""

import hashlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from ..interior.build import interior_identity, style_currency, toolchain
from ..interior.fonts import BUNDLED_FAMILY
from ..interior.inspection import same_box
from ..interior.model import (
    Box,
    Element,
    ImageBlock,
    LetterGrid,
    Panel,
    PhysicalPage,
    Rule,
    TextLine,
)
from ..interior.spec import KDP, PrintSpecification, to_inches
from .context import Context
from .model import (
    Basis,
    Category,
    Finding,
    Measure,
    Outcome,
    Scope,
    Severity,
)
from .model import (
    Rule as PreflightRule,
)

SUBMISSION = "KDP help: Paperback Submission Guidelines"
MARGINS = "KDP help: Set Trim Size, Bleed, and Margins"
FORMATTING = "KDP help: Fix Paperback and Hardcover Formatting Issues"
PRINT_OPTIONS = "KDP help: Print Options"
CONTRACT = "PuzzlePress interior contract (docs/print-interior.md)"


@dataclass(frozen=True)
class Check:
    findings: tuple[Finding, ...] = ()
    outcome: Outcome | None = None  # None: passed or failed according to findings.
    note: str | None = None
    measure: Measure | None = None


def _skip(reason: str) -> Check:
    return Check(outcome=Outcome.NOT_EVALUATED, note=reason)


def _na(reason: str) -> Check:
    return Check(outcome=Outcome.NOT_APPLICABLE, note=reason)


def _in(points: float) -> float:
    return round(to_inches(points), 4)


NO_PDF = "The PDF is unavailable or unreadable."
NO_LAYOUT = "The PDF is not the rendering of the current verified layout."
NO_PROFILE = "The print profile is unknown."


Evaluator = Callable[[PreflightRule, Context], Check]
CATALOGUE: list[tuple[PreflightRule, Evaluator]] = []


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
        CATALOGUE.append((definition, evaluate))
        return evaluate

    return register


def _finding(
    definition: PreflightRule,
    message: str,
    ctx: Context | None = None,
    page: int | None = None,
    *,
    subject: str | None = None,
    region: str | None = None,
    bounds: Box | None = None,
    measure: Measure | None = None,
) -> Finding:
    context = ctx.page(page) if ctx is not None and page is not None else None
    return Finding(definition, message, context, subject, region, bounds, measure)


# ---------------------------------------------------------------- structural


@rule(
    "interior_artifacts",
    Scope.STRUCTURAL,
    Category.ARTIFACT,
    "Interior files present",
    "interior.pdf and interior.json exist as regular files in the output directory.",
    CONTRACT,
)
def _artifacts(r: PreflightRule, ctx: Context) -> Check:
    return Check(
        tuple(_finding(r, p.message, region=p.region) for p in ctx.artifacts.problems),
        note="Both build artifacts are present.",
    )


@rule(
    "manifest_format",
    Scope.STRUCTURAL,
    Category.ARTIFACT,
    "Manifest readable",
    "interior.json is a supported manifest version with every required field.",
    CONTRACT,
)
def _manifest_format(r: PreflightRule, ctx: Context) -> Check:
    if ctx.artifacts.manifest is None:
        return _skip("interior.json is unavailable.")
    if ctx.manifest_problem:
        return Check((_finding(r, ctx.manifest_problem, region="interior.json"),))
    return Check(note="Manifest version 1 with all required fields.")


@rule(
    "manifest_book",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Manifest names this book",
    "The manifest's book ID equals the project's book ID.",
    CONTRACT,
)
def _manifest_book(r: PreflightRule, ctx: Context) -> Check:
    manifest = ctx.manifest
    if manifest is None:
        return _skip("No readable manifest.")
    actual, expected = manifest["book_id"], ctx.project.book.id
    if actual != expected:
        return Check(
            (
                _finding(
                    r,
                    "The interior belongs to another book.",
                    measure=Measure(str(actual), expected, comparison="equal"),
                ),
            )
        )
    return Check(note=f"Book {expected}.")


@rule(
    "manifest_pdf_digest",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "PDF matches its manifest",
    "The PDF's SHA-256 and byte size equal the values recorded in interior.json.",
    CONTRACT,
)
def _pdf_digest(r: PreflightRule, ctx: Context) -> Check:
    manifest, pdf = ctx.manifest, ctx.artifacts.pdf
    if manifest is None or pdf is None:
        return _skip("The PDF or manifest is unavailable.")
    recorded = manifest["pdf"]
    assert isinstance(recorded, dict)
    actual = hashlib.sha256(pdf).hexdigest()
    findings = []
    if recorded["sha256"] != actual:
        findings.append(
            _finding(
                r,
                "interior.pdf is not the file this manifest describes.",
                region="pdf.sha256",
                measure=Measure(actual, str(recorded["sha256"]), comparison="equal"),
            )
        )
    if recorded["bytes"] != len(pdf):
        findings.append(
            _finding(
                r,
                "interior.pdf size differs from the manifest.",
                region="pdf.bytes",
                measure=Measure(len(pdf), int(recorded["bytes"]), "bytes", "equal"),
            )
        )
    return Check(tuple(findings), note="SHA-256 and size match the manifest.")


@rule(
    "interior_identity",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Interior identity consistent",
    "The manifest's interior identity recomputes from the inputs it records.",
    CONTRACT,
)
def _identity(r: PreflightRule, ctx: Context) -> Check:
    manifest = ctx.manifest
    if manifest is None:
        return _skip("No readable manifest.")
    recomputed = interior_identity(manifest)
    if manifest["interior_identity"] != recomputed:
        return Check(
            (
                _finding(
                    r,
                    "The recorded interior identity does not match the recorded inputs.",
                    measure=Measure(str(manifest["interior_identity"]), recomputed, None, "equal"),
                ),
            )
        )
    return Check(note="Identity recomputes from source, plan, profile and toolchain.")


@rule(
    "source_current",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Built from current source",
    "The interior was built from the project source as it is now (build identity).",
    CONTRACT,
)
def _source_current(r: PreflightRule, ctx: Context) -> Check:
    manifest = ctx.manifest
    if manifest is None:
        return _skip("No readable manifest.")
    if manifest["identity"] != ctx.source_identity:
        return Check(
            (
                _finding(
                    r,
                    "The project source changed after this interior was built. Rebuild it.",
                    region="identity",
                    measure=Measure(str(manifest["identity"]), ctx.source_identity, None, "equal"),
                ),
            )
        )
    style = style_currency(manifest, ctx.project)
    if style is not None:
        return Check((_finding(r, f"{style} Rebuild it.", region="style"),))
    return Check(note="Manifest identity and style equal the current source.")


@rule(
    "print_profile_current",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Print profile current",
    "The recorded print profile is a built-in profile with an unchanged definition.",
    CONTRACT,
)
def _profile_current(r: PreflightRule, ctx: Context) -> Check:
    manifest = ctx.manifest
    if manifest is None:
        return _skip("No readable manifest.")
    profile = manifest["print_profile"]
    assert isinstance(profile, dict)
    if ctx.spec is None:
        return Check(
            (
                _finding(
                    r,
                    f"Print profile {profile.get('profile_id')!r} is not built in.",
                    region="print_profile",
                ),
            )
        )
    current = json.loads(json.dumps(ctx.spec.to_dict()))
    if profile != current:
        return Check(
            (
                _finding(
                    r,
                    "The print profile definition changed after this interior was built.",
                    region="print_profile",
                    measure=Measure(
                        f"v{profile.get('profile_version')}",
                        f"v{ctx.spec.profile_version}",
                        None,
                        "equal",
                    ),
                ),
            )
        )
    return Check(note=f"{ctx.spec.profile_id} v{ctx.spec.profile_version}.")


@rule(
    "toolchain_current",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Renderer and fonts current",
    "Renderer, engine, PDF library and pinned font digests equal the running toolchain.",
    CONTRACT,
)
def _toolchain(r: PreflightRule, ctx: Context) -> Check:
    manifest = ctx.manifest
    if manifest is None:
        return _skip("No readable manifest.")

    def shown(value: object) -> str | int:
        return value if isinstance(value, int | str) else "pinned font set"

    findings = []
    for key, value in toolchain().items():
        if manifest[key] != json.loads(json.dumps(value)):
            findings.append(
                _finding(
                    r,
                    f"{key.replace('_', ' ').capitalize()} changed after this interior was built.",
                    region=key,
                    measure=Measure(shown(manifest[key]), shown(value), None, "equal"),
                )
            )
    return Check(tuple(findings), note="Renderer, engine, ReportLab and fonts unchanged.")


@rule(
    "source_buildable",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Current source builds",
    "The current source plans, binds puzzle digests and lays out without diagnostics.",
    CONTRACT,
)
def _buildable(r: PreflightRule, ctx: Context) -> Check:
    if ctx.spec is None:
        return _skip(NO_PROFILE)
    if ctx.build_error is not None:
        return Check(
            tuple(
                _finding(
                    r,
                    f"{issue.message} [{ctx.build_error.stage}: {issue.code}]",
                    subject=issue.subject,
                    region=issue.region or issue.code,
                    measure=Measure(issue.actual, issue.required) if issue.actual else None,
                )
                for issue in ctx.build_error.issues
            )
        )
    return Check(note="Plan verified, digests bound, layout validated.")


@rule(
    "plan_current",
    Scope.STRUCTURAL,
    Category.INTEGRITY,
    "Plan current",
    "The manifest's plan digest equals the digest of the current verified plan.",
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
                    "The book's composition or puzzles changed after this interior was built.",
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
    "rules apply to the PDF only when this holds.",
    CONTRACT,
)
def _matches(r: PreflightRule, ctx: Context) -> Check:
    if ctx.expected is None or ctx.artifacts.pdf is None:
        return _skip("No PDF or no current layout.")
    if not ctx.matches_layout:
        return Check(
            (
                _finding(
                    r,
                    "The PDF differs from a fresh render of the current source.",
                    region="pdf",
                    measure=Measure(
                        hashlib.sha256(ctx.artifacts.pdf).hexdigest(),
                        hashlib.sha256(ctx.expected.pdf).hexdigest(),
                        None,
                        "equal",
                    ),
                ),
            )
        )
    return Check(note="Byte-identical to the deterministic render.")


@rule(
    "pdf_readable",
    Scope.STRUCTURAL,
    Category.ARTIFACT,
    "PDF parses",
    "An independent parser (pypdf, strict) reads the PDF; it is not encrypted.",
    CONTRACT,
)
def _readable(r: PreflightRule, ctx: Context) -> Check:
    if ctx.artifacts.pdf is None:
        return _skip("interior.pdf is unavailable.")
    if ctx.facts is None:
        message = ctx.facts_problem.message if ctx.facts_problem else "The PDF does not parse."
        return Check((_finding(r, message, region="pdf"),))
    if ctx.facts.encrypted:
        return Check((_finding(r, "The PDF is encrypted.", region="pdf"),))
    return Check(note="Parsed strictly by pypdf.")


@rule(
    "page_count",
    Scope.STRUCTURAL,
    Category.PAGE,
    "Page count matches",
    "PDF pages equal the manifest's page count and the plan's logical pages.",
    CONTRACT,
)
def _page_count(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    actual = ctx.facts.page_count
    expected = {
        "manifest": ctx.manifest["page_count"] if ctx.manifest else None,
        "plan": len(ctx.expected.plan.pages) if ctx.expected else None,
    }
    findings = tuple(
        _finding(
            r,
            f"The PDF has {actual} pages; the {source} states {count}.",
            region=source,
            measure=Measure(actual, int(count), "pages", "equal"),
        )
        for source, count in expected.items()
        if isinstance(count, int) and count != actual
    )
    return Check(findings, note=f"{actual} pages.", measure=Measure(actual, unit="pages"))


@rule(
    "page_boxes",
    Scope.STRUCTURAL,
    Category.PAGE,
    "Page boxes match profile",
    "Every page's MediaBox and TrimBox equal the profile's trim; no larger BleedBox.",
    CONTRACT,
)
def _boxes(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None or ctx.spec is None:
        return _skip(NO_PDF if ctx.facts is None else NO_PROFILE)
    trim = Box(0.0, 0.0, ctx.spec.trim.width, ctx.spec.trim.height)
    findings = []
    for page in ctx.facts.pages:
        for name, box in (("MediaBox", page.media), ("TrimBox", page.trim)):
            if not same_box(box, trim):
                findings.append(
                    _finding(
                        r, f"{name} differs from the profile trim.", ctx, page.number, region=name
                    )
                )
        if page.bleed is not None and not same_box(page.bleed, trim):
            findings.append(
                _finding(
                    r, "BleedBox extends beyond the trim.", ctx, page.number, region="BleedBox"
                )
            )
    return Check(tuple(findings), note="Every page is exactly the trim size.")


@rule(
    "page_rotation",
    Scope.STRUCTURAL,
    Category.PAGE,
    "Pages unrotated",
    "No page carries a /Rotate entry.",
    CONTRACT,
)
def _rotation(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    return Check(
        tuple(
            _finding(
                r,
                "The page is rotated.",
                ctx,
                p.number,
                measure=Measure(p.rotation, 0, "degrees", "equal"),
            )
            for p in ctx.facts.pages
            if p.rotation
        ),
        note="No rotated pages.",
    )


@rule(
    "pdf_interactive_features",
    Scope.STRUCTURAL,
    Category.CONTENT,
    "No interactive features",
    "No annotations, links, forms, open actions, name trees or bookmarks.",
    CONTRACT,
)
def _interactive(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    facts = ctx.facts
    findings = [
        _finding(r, f"Unexpected catalog entry {key}.", region=key) for key in facts.interactive
    ]
    if facts.outline:
        findings.append(_finding(r, "The PDF contains bookmarks.", region="outline"))
    findings.extend(
        _finding(
            r, f"{p.annotations} annotation(s) on the page.", ctx, p.number, region="annotations"
        )
        for p in facts.pages
        if p.annotations
    )
    return Check(tuple(findings), note="No annotations, forms, actions or bookmarks.")


@rule(
    "fonts_bundled",
    Scope.STRUCTURAL,
    Category.FONT,
    "Bundled fonts only",
    "Every font is an embedded subset of the bundled, digest-pinned Vera Sans faces.",
    CONTRACT,
)
def _bundled(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    findings = []
    for page in ctx.facts.pages:
        for font in page.fonts:
            family = font.name.lstrip("/").split("+")[-1]
            if not font.embedded or not family.startswith(BUNDLED_FAMILY):
                findings.append(
                    _finding(
                        r,
                        f"Font {family} is not an embedded bundled face.",
                        ctx,
                        page.number,
                        region="fonts",
                    )
                )
    return Check(tuple(findings), note="Only embedded bundled Vera Sans subsets.")


@rule(
    "raster_images",
    Scope.STRUCTURAL,
    Category.CONTENT,
    "Raster images are the layout's",
    "Raster images appear only where the verified layout places a styled photograph "
    "(a photo-feature title page or a theme divider); any other image is foreign.",
    CONTRACT,
)
def _images(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    with_images = [p for p in ctx.facts.pages if p.images]
    # Compare with what the current verified layout places, even when the PDF's
    # bytes differ from it: an image the layout does not place is foreign.
    expected = ctx.expected.layout if ctx.expected is not None else None
    if expected is None:
        if not with_images:
            return Check(note="No raster images.")
        return _skip("No current layout to attribute the images to.")
    placed = {
        page.number: sum(isinstance(e, ImageBlock) for e in page.elements)
        for page in expected.pages
    }
    total = sum(placed.values())
    return Check(
        tuple(
            _finding(
                r,
                f"{p.images} raster image(s) on the page; the layout places "
                f"{placed.get(p.number, 0)}.",
                ctx,
                p.number,
                region="images",
            )
            for p in ctx.facts.pages
            if p.images != placed.get(p.number, 0)
        ),
        note=f"{total} styled photograph(s), as the layout places them."
        if total
        else "No raster images.",
    )


@rule(
    "blank_pages",
    Scope.STRUCTURAL,
    Category.CONTENT,
    "Intentional blanks are blank",
    "Plan blank pages carry no text or painting operators in the PDF.",
    CONTRACT,
)
def _blanks(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None or ctx.layout is None:
        return _skip(NO_PDF if ctx.facts is None else NO_LAYOUT)
    blanks = [p for p in ctx.layout.pages if not p.elements]
    if not blanks:
        return _na("The plan has no blank pages.")
    return Check(
        tuple(
            _finding(r, "An intentional blank page has content.", ctx, p.number)
            for p in blanks
            if ctx.facts.pages[p.number - 1].painted or ctx.facts.pages[p.number - 1].text.strip()
        ),
        note=f"{len(blanks)} intentional blank page(s) are empty.",
    )


@rule(
    "folios_printed",
    Scope.STRUCTURAL,
    Category.CONTENT,
    "Page numbers printed",
    "Every page number the plan displays appears in the page's PDF text.",
    CONTRACT,
)
def _folios(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None or ctx.layout is None:
        return _skip(NO_PDF if ctx.facts is None else NO_LAYOUT)
    return Check(
        tuple(
            _finding(
                r,
                "The displayed page number is missing.",
                ctx,
                p.number,
                measure=Measure("missing", p.folio, None, "equal"),
            )
            for p in ctx.layout.pages
            if p.folio is not None and p.folio not in ctx.facts.pages[p.number - 1].text.split()
        ),
        note="Every displayed page number is present.",
    )


@rule(
    "content_in_live_area",
    Scope.STRUCTURAL,
    Category.GEOMETRY,
    "Content inside the live area",
    "Every element's painted extent (text ink box, rule and frame strokes) lies inside "
    "the print profile's live area. KDP's own margins are separate rules.",
    CONTRACT,
)
def _live_area(r: PreflightRule, ctx: Context) -> Check:
    if ctx.layout is None:
        return _skip(NO_LAYOUT)
    findings = []
    for page in ctx.layout.pages:
        content = page.frame.content
        for element in page.elements:
            ink = ink_bounds(element)
            if not content.contains(ink, 0.01):
                overhang = max(
                    content.x - ink.x,
                    ink.right - content.right,
                    content.y - ink.y,
                    ink.top - content.top,
                )
                findings.append(
                    _finding(
                        r,
                        f"{element.role} extends {overhang:g} pt beyond the live area.",
                        ctx,
                        page.number,
                        region=element.role,
                        bounds=ink,
                        measure=Measure(round(overhang, 3), 0, "pt", "at_most"),
                    )
                )
    return Check(tuple(findings), note="Every element's painted extent is inside the live area.")


# Readability notes the layout engine reports for a design; none blocks a build.
DESIGN_NOTES = ("dense_solution_page", "light_text", "low_contrast_text", "heavy_ink_coverage")


@rule(
    "design_legibility",
    Scope.STRUCTURAL,
    Category.TYPOGRAPHY,
    "Design legibility",
    "The interior design keeps solution letters at a comfortable size (7.5 pt), "
    "label text dark enough to read, contrast between banners and their type, and "
    "dark tints off large areas. PuzzlePress conventions; they never block.",
    CONTRACT,
    severity=Severity.WARNING,
)
def _design_legibility(r: PreflightRule, ctx: Context) -> Check:
    if ctx.layout is None:
        return _skip(NO_LAYOUT)
    notes = [w for w in ctx.layout.warnings if w.code in DESIGN_NOTES]
    return Check(
        tuple(
            _finding(r, w.message, ctx, w.physical_page, region=w.region, subject=w.code)
            for w in notes
        ),
        note="No cramped solutions, light labels, low-contrast banners or heavy tints.",
    )


# ----------------------------------------------------------------------- KDP


@rule(
    "kdp_minimum_page_count",
    Scope.KDP,
    Category.PAGE,
    "Minimum page count",
    f"A KDP paperback has at least {KDP.min_pages} pages. PuzzlePress never pads.",
    SUBMISSION,
)
def _min_pages(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    count = ctx.facts.page_count
    measure = Measure(count, KDP.min_pages, "pages", "at_least")
    if count < KDP.min_pages:
        return Check(
            (
                _finding(
                    r,
                    f"{count} pages. The supported KDP paperback minimum is {KDP.min_pages} pages.",
                    measure=measure,
                ),
            )
        )
    return Check(note=f"{count} pages.", measure=measure)


@rule(
    "kdp_maximum_page_count",
    Scope.KDP,
    Category.PAGE,
    "Maximum page count",
    "Page count is within KDP's black-ink maximum for the trim on the profile's paper "
    "(8.5 x 11 and 8.5 x 8.5 in: 590 white, 550 cream; 6 x 9 and 8 x 10 in: 828 white, "
    "776 cream).",
    MARGINS,
)
def _max_pages(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None or ctx.spec is None:
        return _skip(NO_PDF if ctx.facts is None else NO_PROFILE)
    maximum = KDP.max_pages_for(ctx.spec.trim.name, ctx.spec.paper)
    if maximum is None:
        return _skip(
            f"No verified maximum for trim {ctx.spec.trim.name} on {ctx.spec.paper} paper."
        )
    count = ctx.facts.page_count
    measure = Measure(count, maximum, "pages", "at_most")
    if count > maximum:
        return Check(
            (
                _finding(
                    r, f"{count} pages exceed the modeled maximum of {maximum}.", measure=measure
                ),
            )
        )
    return Check(note=f"{count} of at most {maximum} pages.", measure=measure)


@rule(
    "kdp_trim_size",
    Scope.KDP,
    Category.GEOMETRY,
    "Supported trim size",
    "The trim is within KDP's paperback trim range (4-8.5 in wide, 6-11.69 in tall).",
    PRINT_OPTIONS,
)
def _trim(r: PreflightRule, ctx: Context) -> Check:
    if ctx.spec is None:
        return _skip(NO_PROFILE)
    trim = ctx.spec.trim
    actual = f"{to_inches(trim.width):g} x {to_inches(trim.height):g}"
    measure = Measure(actual, "4-8.5 x 6-11.69", "in", "within")
    if not KDP.trim_supported(trim.width, trim.height):
        return Check((_finding(r, "The trim size is outside KDP's range.", measure=measure),))
    return Check(note=f"{actual} in.", measure=measure)


@rule(
    "kdp_page_size",
    Scope.KDP,
    Category.GEOMETRY,
    "Single trim-size pages",
    "Each PDF page is one page at the trim size: no spreads or 2-up pages.",
    SUBMISSION,
)
def _page_size(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None or ctx.spec is None:
        return _skip(NO_PDF if ctx.facts is None else NO_PROFILE)
    width, height = ctx.spec.trim.width, ctx.spec.trim.height
    findings = []
    for page in ctx.facts.pages:
        if page.media is None:
            findings.append(_finding(r, "The page has no MediaBox.", ctx, page.number))
            continue
        w, h = page.media[2] - page.media[0], page.media[3] - page.media[1]
        if abs(w - width) > 0.01 or abs(h - height) > 0.01:
            spread = abs(w - 2 * width) <= 0.01
            findings.append(
                _finding(
                    r,
                    "The page is a two-page spread."
                    if spread
                    else "The page size differs from the trim size.",
                    ctx,
                    page.number,
                    region="MediaBox",
                    measure=Measure(
                        f"{_in(w):g} x {_in(h):g}",
                        f"{_in(width):g} x {_in(height):g}",
                        "in",
                        "equal",
                    ),
                )
            )
    return Check(tuple(findings), note="Every page is a single trim-size page.")


@rule(
    "kdp_no_bleed",
    Scope.KDP,
    Category.GEOMETRY,
    "No-bleed setup",
    "The profile is no-bleed, so pages must not be enlarged for bleed (no BleedBox "
    "beyond the trim) and outside margins of at least 0.25 in apply.",
    MARGINS,
)
def _no_bleed(r: PreflightRule, ctx: Context) -> Check:
    if ctx.spec is None or ctx.facts is None:
        return _skip(NO_PROFILE if ctx.spec is None else NO_PDF)
    if ctx.spec.bleed:
        return Check((_finding(r, "Bleed profiles are not modeled by this rule set."),))
    trim = Box(0.0, 0.0, ctx.spec.trim.width, ctx.spec.trim.height)
    return Check(
        tuple(
            _finding(
                r,
                "A BleedBox extends beyond the trim of a no-bleed interior.",
                ctx,
                p.number,
                region="BleedBox",
            )
            for p in ctx.facts.pages
            if p.bleed is not None and not same_box(p.bleed, trim)
        ),
        note="No-bleed interior; page size equals trim size.",
    )


def kdp_safe_area(spec: PrintSpecification, page_count: int, recto: bool) -> Box | None:
    """The area KDP's margin rules leave for content on a page; None beyond the table."""
    gutter = KDP.required_gutter(page_count)
    if gutter is None:
        return None
    outside = KDP.min_outside_margin
    left = gutter if recto else outside
    return Box(
        left,
        outside,
        spec.trim.width - gutter - outside,
        spec.trim.height - 2 * outside,
    )


def ink_bounds(element: Element) -> Box:
    """Painted extent: stroked frames extend half their line width beyond the frame."""
    if isinstance(element, LetterGrid):
        half = element.frame_width / 2
        frame = element.frame
        return Box(frame.x - half, frame.y - half, frame.width + 2 * half, frame.height + 2 * half)
    return element.bounds


def _clearances(
    page: PhysicalPage, spec: PrintSpecification
) -> Iterator[tuple[str, float, Element]]:
    """(edge, distance from the trim edge, nearest element) for each trim edge."""
    width, height = spec.trim.width, spec.trim.height
    inks = [(ink_bounds(e), e) for e in page.elements]
    left = min(inks, key=lambda item: item[0].x)
    right = min(inks, key=lambda item: width - item[0].right)
    bottom = min(inks, key=lambda item: item[0].y)
    top = min(inks, key=lambda item: height - item[0].top)
    inside, outside = (left, right) if page.frame.recto else (right, left)
    yield "inside", inside[0].x if page.frame.recto else width - inside[0].right, inside[1]
    yield "outside", width - outside[0].right if page.frame.recto else outside[0].x, outside[1]
    yield "top", height - top[0].top, top[1]
    yield "bottom", bottom[0].y, bottom[1]


def _margin_check(r: PreflightRule, ctx: Context, edges: tuple[str, ...], required: float) -> Check:
    layout = ctx.layout
    assert layout is not None
    findings = []
    worst: tuple[float, int, str] | None = None
    for page in layout.pages:
        if not page.elements:
            continue
        for edge, distance, element in _clearances(page, layout.spec):
            if edge not in edges:
                continue
            if worst is None or distance < worst[0]:
                worst = (distance, page.number, edge)
            if distance < required - 0.01:
                findings.append(
                    _finding(
                        r,
                        f"Content is {_in(distance):g} in from the {edge} edge; at least "
                        f"{_in(required):g} in is required.",
                        ctx,
                        page.number,
                        region=f"{edge}_margin:{element.role}",
                        bounds=ink_bounds(element),
                        measure=Measure(_in(distance), _in(required), "in", "at_least"),
                    )
                )
    if worst is None:
        return _na("No page carries content.")
    measure = Measure(_in(worst[0]), _in(required), "in", "at_least")
    return Check(
        tuple(findings),
        note=f"Smallest {worst[2]} clearance {_in(worst[0]):g} in on page {worst[1]}.",
        measure=measure,
    )


@rule(
    "kdp_gutter",
    Scope.KDP,
    Category.GEOMETRY,
    "Inside margin (gutter)",
    "Content clears the binding edge by KDP's gutter for the page count: 24-150 "
    "0.375 in, 151-300 0.5, 301-500 0.625, 501-700 0.75, 701-828 0.875.",
    MARGINS,
)
def _gutter(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None or ctx.layout is None:
        return _skip(NO_PDF if ctx.facts is None else NO_LAYOUT)
    required = KDP.required_gutter(ctx.facts.page_count)
    if required is None:
        return _skip(f"No KDP gutter is defined above {KDP.max_pages} pages.")
    return _margin_check(r, ctx, ("inside",), required)


@rule(
    "kdp_outside_margins",
    Scope.KDP,
    Category.GEOMETRY,
    "Outside, top and bottom margins",
    "Content clears the outside, top and bottom trim edges by at least 0.25 in (no bleed).",
    MARGINS,
)
def _outside(r: PreflightRule, ctx: Context) -> Check:
    if ctx.layout is None:
        return _skip(NO_LAYOUT)
    return _margin_check(r, ctx, ("outside", "top", "bottom"), KDP.min_outside_margin)


def _per_element(
    r: PreflightRule,
    ctx: Context,
    values: Callable[[Element], Iterator[tuple[str, float]]],
    minimum: float,
    noun: str,
) -> Check:
    layout = ctx.layout
    if layout is None:
        return _skip(NO_LAYOUT)
    findings = []
    smallest: float | None = None
    for page in layout.pages:
        worst: dict[str, tuple[float, Element]] = {}
        for element in page.elements:
            for label, value in values(element):
                smallest = value if smallest is None else min(smallest, value)
                if value < minimum - 1e-6 and (label not in worst or value < worst[label][0]):
                    worst[label] = (value, element)
        for label, (value, element) in sorted(worst.items()):
            findings.append(
                _finding(
                    r,
                    f"{noun.capitalize()} {value:g} pt is below the {minimum:g} pt minimum.",
                    ctx,
                    page.number,
                    region=label,
                    bounds=ink_bounds(element),
                    measure=Measure(round(value, 3), minimum, "pt", "at_least"),
                )
            )
    if smallest is None:
        return _na(f"No {noun} in the interior.")
    return Check(
        tuple(findings),
        note=f"Smallest {noun} {smallest:g} pt.",
        measure=Measure(round(smallest, 3), minimum, "pt", "at_least"),
    )


def _font_sizes(element: Element) -> Iterator[tuple[str, float]]:
    if isinstance(element, TextLine):
        yield element.role, element.size
    elif isinstance(element, LetterGrid):
        yield element.role, element.letter_size


def _line_weights(element: Element) -> Iterator[tuple[str, float]]:
    if isinstance(element, Rule):
        yield element.role, element.width
    elif isinstance(element, Panel) and element.stroke_gray is not None:
        yield element.role, element.stroke_width
    elif isinstance(element, LetterGrid):
        yield f"{element.role}_frame", element.frame_width
        for mark in element.marks:
            yield f"{element.role}_mark", mark.line_width


@rule(
    "kdp_minimum_font_size",
    Scope.KDP,
    Category.TYPOGRAPHY,
    "Minimum font size",
    f"All text, including grid letters, is at least {KDP.min_font_size:g} pt.",
    SUBMISSION,
)
def _font_size(r: PreflightRule, ctx: Context) -> Check:
    return _per_element(r, ctx, _font_sizes, KDP.min_font_size, "text size")


@rule(
    "kdp_minimum_line_weight",
    Scope.KDP,
    Category.GEOMETRY,
    "Minimum line weight",
    f"Rules, grid frames and solution marks are at least {KDP.min_line_weight:g} pt "
    "(KDP also states 0.01 in, which is 0.72 pt; the stricter value applies).",
    SUBMISSION,
)
def _line_weight(r: PreflightRule, ctx: Context) -> Check:
    return _per_element(r, ctx, _line_weights, KDP.min_line_weight, "line weight")


@rule(
    "kdp_fonts_embedded",
    Scope.KDP,
    Category.FONT,
    "Fonts embedded",
    "Every font used by a page has an embedded font program.",
    SUBMISSION,
)
def _embedded(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    return Check(
        tuple(
            _finding(
                r, f"Font {font.name.lstrip('/')} is not embedded.", ctx, p.number, region="fonts"
            )
            for p in ctx.facts.pages
            for font in p.fonts
            if not font.embedded
        ),
        note="Every font program is embedded.",
    )


@rule(
    "kdp_full_font_embedding",
    Scope.KDP,
    Category.FONT,
    "Full font embedding",
    "KDP's formatting help says fonts should be 'fully embedded'; its submission "
    "guidelines say 'embedded'. PuzzlePress embeds subsets, which carry every glyph used.",
    FORMATTING,
    basis=Basis.KDP_AMBIGUOUS,
    severity=Severity.WARNING,
)
def _full_embedding(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    subsets = sorted({f.name.lstrip("/") for p in ctx.facts.pages for f in p.fonts if f.subset})
    if subsets:
        return Check(
            (
                _finding(
                    r,
                    f"{len(subsets)} font(s) are subset-embedded. Review against KDP's "
                    "wording; subsets contain every glyph the interior uses.",
                    region="fonts",
                    measure=Measure("subset", "fully embedded", None, "equal"),
                ),
            )
        )
    return Check(note="No subset fonts.")


@rule(
    "kdp_no_annotations",
    Scope.KDP,
    Category.CONTENT,
    "No comments, annotations or bookmarks",
    "The file contains no annotations, comments, form fields or bookmarks.",
    SUBMISSION,
)
def _kdp_annotations(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    facts = ctx.facts
    findings = [
        _finding(r, f"{p.annotations} annotation(s).", ctx, p.number, region="annotations")
        for p in facts.pages
        if p.annotations
    ]
    if facts.outline:
        findings.append(_finding(r, "The PDF contains bookmarks.", region="outline"))
    if "/AcroForm" in facts.interactive:
        findings.append(_finding(r, "The PDF contains a form.", region="/AcroForm"))
    return Check(tuple(findings), note="None present.")


@rule(
    "kdp_not_encrypted",
    Scope.KDP,
    Category.ARTIFACT,
    "Not locked or encrypted",
    "The file is not locked or encrypted.",
    SUBMISSION,
)
def _encrypted(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    if ctx.facts.encrypted:
        return Check((_finding(r, "The PDF is encrypted.", region="pdf"),))
    return Check(note="Not encrypted.")


@rule(
    "kdp_flattened",
    Scope.KDP,
    Category.CONTENT,
    "Flattened transparency and layers",
    "No transparency groups, soft masks, blend modes, partial opacity or layers.",
    SUBMISSION,
)
def _flattened(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    findings = [
        _finding(r, "The page uses transparency.", ctx, p.number, region="transparency")
        for p in ctx.facts.pages
        if p.transparency
    ]
    if ctx.facts.optional_content:
        findings.append(_finding(r, "The PDF contains layers.", region="/OCProperties"))
    return Check(tuple(findings), note="No transparency or layers.")


@rule(
    "kdp_no_printer_marks",
    Scope.KDP,
    Category.CONTENT,
    "No crop or trim marks",
    "Pages have no area beyond the trim where crop, registration or other printer's "
    "marks could print. Content placement is judged by the margin rules.",
    SUBMISSION,
)
def _marks(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None or ctx.layout is None:
        return _skip(NO_PDF if ctx.facts is None else NO_LAYOUT)
    findings = [
        _finding(r, "The page extends beyond the trim.", ctx, page.number, region="MediaBox")
        for page in ctx.layout.pages
        if not same_box(ctx.facts.pages[page.number - 1].media, page.frame.trim)
    ]
    return Check(tuple(findings), note="No slug area beyond the trim.")


@rule(
    "kdp_image_resolution",
    Scope.KDP,
    Category.CONTENT,
    "Image resolution",
    f"Raster images are at least {KDP.min_image_dpi:g} DPI. Not applicable without images.",
    SUBMISSION,
)
def _resolution(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    pages = [p for p in ctx.facts.pages if p.images]
    if not pages:
        return _na("The interior contains no raster images.")
    if ctx.layout is None:
        # Without the verified layout, the images' printed sizes are unknown.
        return Check(
            tuple(
                _finding(
                    r,
                    "PuzzlePress cannot verify the effective resolution of raster images.",
                    ctx,
                    p.number,
                    region="images",
                    measure=Measure("unverified", KDP.min_image_dpi, "dpi", "at_least"),
                )
                for p in pages
            )
        )
    blocks = [
        (page.number, e)
        for page in ctx.layout.pages
        for e in page.elements
        if isinstance(e, ImageBlock)
    ]
    lowest = min(block.effective_dpi for _, block in blocks)
    return Check(
        tuple(
            _finding(
                r,
                f"The {block.role.replace('_', ' ')} prints at {block.effective_dpi:.0f} DPI "
                f"(at most {block.max_dpi:.0f} available from the photograph).",
                ctx,
                number,
                region=block.role,
                bounds=block.box,
                measure=Measure(
                    round(block.effective_dpi, 1), KDP.min_image_dpi, "dpi", "at_least"
                ),
            )
            for number, block in blocks
            if block.effective_dpi + 1e-9 < KDP.min_image_dpi
        ),
        note=f"Lowest effective resolution {lowest:.0f} DPI.",
        measure=Measure(round(lowest, 1), KDP.min_image_dpi, "dpi", "at_least"),
    )


@rule(
    "kdp_blank_page_runs",
    Scope.KDP,
    Category.PAGE,
    "Consecutive blank pages",
    f"At most {KDP.max_blank_run} consecutive blank pages at the beginning or middle, "
    f"and at most {KDP.max_trailing_blank_run} at the end.",
    FORMATTING,
)
def _blank_runs(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    pages = ctx.facts.pages
    findings = []
    longest = 0
    run_start: int | None = None
    for page in (*pages, None):
        blank = page is not None and not page.painted and not page.text.strip()
        if blank:
            assert page is not None
            run_start = run_start or page.number
            continue
        if run_start is not None:
            last = page.number - 1 if page is not None else len(pages)
            length = last - run_start + 1
            longest = max(longest, length)
            trailing = page is None
            limit = KDP.max_trailing_blank_run if trailing else KDP.max_blank_run
            if length > limit:
                findings.append(
                    _finding(
                        r,
                        f"{length} consecutive blank pages{' at the end' if trailing else ''}.",
                        ctx,
                        run_start,
                        region="blank_run",
                        measure=Measure(length, limit, "pages", "at_most"),
                    )
                )
            run_start = None
    return Check(tuple(findings), note=f"Longest blank run: {longest} page(s).")


@rule(
    "kdp_page_number_parity",
    Scope.KDP,
    Category.PAGE,
    "Even numbers on left pages",
    "Printed page numbers are even on left (verso) pages and odd on right (recto) pages.",
    SUBMISSION,
)
def _parity(r: PreflightRule, ctx: Context) -> Check:
    plan = ctx.plan
    if plan is None:
        return _skip(NO_LAYOUT)
    displayed = [p for p in plan.pages if p.number.displayed]
    if not displayed:
        return _na("No page numbers are printed.")
    return Check(
        tuple(
            _finding(
                r,
                f"Page number {p.number.label} is printed on a {p.side.value} page.",
                ctx,
                p.index,
                region="folio",
                measure=Measure(
                    p.side.value, "recto" if p.number.value % 2 else "verso", None, "equal"
                ),
            )
            for p in displayed
            if (p.number.value % 2 == 1) != (p.side.value == "recto")
        ),
        note=f"{len(displayed)} printed page numbers match their sides.",
    )


@rule(
    "kdp_no_metadata",
    Scope.KDP,
    Category.CONTENT,
    "No descriptive metadata",
    "KDP asks for files without metadata. Descriptive fields (title, author, subject, "
    "keywords) are checked; producer tool names are not interpreted as metadata.",
    SUBMISSION,
    basis=Basis.KDP_AMBIGUOUS,
    severity=Severity.WARNING,
)
def _metadata(r: PreflightRule, ctx: Context) -> Check:
    if ctx.facts is None:
        return _skip(NO_PDF)
    fields = ctx.facts.descriptive_metadata
    if fields:
        return Check(
            (_finding(r, f"Descriptive metadata present: {', '.join(fields)}.", region="metadata"),)
        )
    return Check(note="Title, author, subject and keywords are empty.")


RULES = tuple(definition for definition, _ in CATALOGUE)
if len({rule.code for rule in RULES}) != len(RULES):
    raise RuntimeError("Preflight rule codes must be unique")
