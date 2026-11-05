"""Layout engine: verified PublicationPlan + batch report + print spec -> InteriorLayout.

One physical page per plan entry, in plan order. The engine decides positions
only. It never reorders, omits, inserts, regroups or repaginates entries, and it
rejects content that does not fit instead of shrinking it below profile limits.
"""

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from ..batch import BatchReport, puzzle_digest
from ..cover_config import Crop
from ..interior_style import (
    Align,
    Background,
    Banner,
    Corners,
    Density,
    DividerLayout,
    FolioStyle,
    Intensity,
    Motif,
    TitleLayout,
    Weight,
    WordPosition,
)
from ..publication import (
    NumberStyle,
    PageKind,
    PageNumber,
    PlanPage,
    PublicationPlan,
    PuzzleRef,
    Section,
)
from ..wordsearch import WordSearch, verify_word_search
from .design import CLASSIC, InteriorDesign, Look
from .fonts import ASCENT, CAP_HEIGHT, DESCENT, missing_characters, text_width
from .geometry import (
    LETTER_RATIO,
    SOLUTION_TEMPLATES,
    GridGeometry,
    fit_grid,
    max_cell_for_letter,
    page_frame,
    solution_slots,
    solution_template,
)
from .images import NO_PHOTOS, InteriorPhotos, place_photo
from .issues import InteriorError, LayoutIssue
from .model import (
    Anchor,
    Box,
    Element,
    Face,
    InteriorLayout,
    LetterGrid,
    PageFrame,
    Panel,
    PhysicalPage,
    Polygon,
    Rule,
    SolutionMark,
)
from .spec import KDP, FolioPlacement, PrintSpecification, to_inches, validate_print_spec
from .text import text_line, wrap_text

# 2: grid frames fit their region by painted extent (frame plus half its stroke).
RENDERER_VERSION = 2

# Template spacing (points). Changing any value changes output: bump RENDERER_VERSION.
FOLIO_BAND = 24.0  # Reserved at the bottom of every live area for the page number.
TEXT_MEASURE = 396.0  # 5.5 in reading measure for running text.
HEADING_GAP = 24.0
WORD_GAP = 22.0  # Between a puzzle grid's painted frame and its word list.
WORD_COLUMN_GAP = 36.0
MAX_WORD_COLUMNS = 5
WORD_LEADING = 1.5
SOLUTION_GAP_X = 24.0
SOLUTION_GAP_Y = 20.0
CAPTION_GAP = 6.0
NOTES_SPACING = 27.0
MARK_RADIUS = 0.4  # Capsule radius as a fraction of one cell.
MUTED_GRAY = 0.55  # Non-solution letters on solution pages.
NOTES_GRAY = 0.6
LABEL_GRAY = 0.35
# Styled pages (never used by the classic design).
FRAME_INSET = 12.0  # A ruled frame sits this far inside the live area.
FRAME_STROKE = 1.0
PANEL_PAD = 24.0  # Text inside a tinted block keeps this far from its edges.
DARK_PANEL = 0.45  # A panel this dark or darker takes white text.
MIN_CONTRAST = 0.55  # Text and panel grays closer than this read poorly in print.
HEAVY_TINT = 60  # Percent ink: a block this dark over a large area is heavy coverage.
HEAVY_SHARE = 0.25
# Version 2 themes (never used without a look; the classic look draws none of them).
DENSITY = {Density.COMPACT.value: 0.75, Density.BALANCED.value: 1.0, Density.SPACIOUS.value: 1.3}
BANNER_PAD_X = 12.0
BANNER_PAD_Y = 7.0
BANNER_RADIUS = 6.0
BANNER_RULE = 2.0  # The heavy rule of a `rule` banner.
OUTLINE_STROKE = 1.25
PAGE_FRAME_PAD = 14.0  # Content keeps this far inside a page frame's stroke.
PAGE_FRAME_RADIUS = 10.0
MOTIF_HEIGHT = {
    Intensity.SUBTLE.value: 10.0,
    Intensity.MEDIUM.value: 16.0,
    Intensity.BOLD.value: 22.0,
}
MOTIF_COUNT = {Intensity.SUBTLE.value: 3, Intensity.MEDIUM.value: 4, Intensity.BOLD.value: 5}
MOTIF_GAP = 12.0  # Between the motif band and the page header.
HEADER_BAND_GRAY = 0.93  # A 7% tint behind the header.
LIGHT_TEXT = 0.5  # Text lighter than 50% black reads poorly in print.
COMFORT_SOLUTION_LETTER = 7.5  # Below this, solution letters are legal but cramped.
FOOTER_GAP = 8.0  # Between a puzzle's answer reference and the content above it.
GRID_CORNER = 0.3  # Rounded grid corners: at most this share of a cell (padding is 0.35).
# Solution letters as a share of the cell, per density. Eight a page uses compact
# cells so small grids keep 7 pt letters; the others keep the original ratio.
SOLUTION_LETTER_RATIO = {8: 0.68}
THEMED_KINDS = frozenset(
    {PageKind.PUZZLE, PageKind.PUZZLE_WORDS, PageKind.SOLUTIONS, PageKind.DIVIDER}
)


def plan_digest(plan: PublicationPlan) -> str:
    material = json.dumps(
        plan.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    return "sha256-" + hashlib.sha256(material).hexdigest()


def verify_puzzle_bindings(
    plan: PublicationPlan, report: BatchReport
) -> tuple[dict[str, WordSearch], tuple[LayoutIssue, ...]]:
    """Bind every planned puzzle and solution to generated content by digest.

    Puzzle IDs alone are never trusted. Nothing is regenerated.
    """
    issues: list[LayoutIssue] = []
    if not plan.complete:
        issues.extend(
            LayoutIssue("incomplete_plan", d.message, region=d.path) for d in plan.diagnostics
        )
    if report.identity != plan.identity:
        issues.append(
            LayoutIssue(
                "identity_mismatch",
                "Batch report and plan come from different sources.",
                actual=report.identity,
                required=plan.identity,
            )
        )
    results = {result.id: result for result in report.puzzles}
    bound: dict[str, WordSearch] = {}
    for page in plan.pages:
        refs = [page.puzzle] if page.puzzle else [item.puzzle for item in page.solutions]
        for ref in refs:

            def fail(
                code: str,
                message: str,
                actual: str | None = None,
                required: str | None = None,
                page: PlanPage = page,
                subject: str = ref.id,
            ) -> None:
                issues.append(
                    LayoutIssue(
                        code,
                        message,
                        page=page.index,
                        kind=str(page.kind),
                        subject=subject,
                        actual=actual,
                        required=required,
                    )
                )

            result = results.get(ref.id)
            if result is None or result.puzzle is None or result.errors:
                fail("missing_puzzle", "No generated puzzle for entry.")
                continue
            actual = puzzle_digest(result.puzzle)
            if ref.digest != actual:
                fail(
                    "digest_mismatch",
                    "Generated puzzle content differs from the plan's digest.",
                    actual,
                    ref.digest,
                )
                continue
            if ref.id not in bound:
                if not verify_word_search(result.puzzle).valid:
                    fail("solution_invalid", "Generated solution failed independent verification.")
                    continue
                bound[ref.id] = result.puzzle
    return bound, tuple(issues)


def page_count_checks(
    spec: PrintSpecification, page_count: int
) -> tuple[tuple[LayoutIssue, ...], tuple[LayoutIssue, ...]]:
    """(errors, warnings) for the physical page count: gutter and KDP page limits."""
    errors: list[LayoutIssue] = []
    warnings: list[LayoutIssue] = []
    required = KDP.required_gutter(page_count)
    if required is None:
        errors.append(
            LayoutIssue(
                "page_count_unsupported",
                "Page count exceeds the KDP gutter table.",
                actual=str(page_count),
                required=f"at most {KDP.max_pages}",
            )
        )
    elif spec.margins.inside < required - 1e-6:
        errors.append(
            LayoutIssue(
                "gutter_too_small",
                f"Inside margin is below the KDP gutter for {page_count} pages.",
                region="print.margins.inside",
                actual=f"{to_inches(spec.margins.inside):.4g} in",
                required=f"{to_inches(required):.4g} in",
            )
        )
    if page_count < KDP.min_pages:
        warnings.append(
            LayoutIssue(
                "kdp_minimum_page_count",
                "KDP paperbacks need at least 24 pages; the plan, not the renderer, "
                "owns page count.",
                actual=str(page_count),
                required=f"at least {KDP.min_pages}",
            )
        )
    return tuple(errors), tuple(warnings)


@dataclass
class _Page:
    """Mutable per-page accumulator; frozen into a PhysicalPage when complete."""

    spec: PrintSpecification
    plan_page: PlanPage
    number: int
    frame: PageFrame
    design: InteriorDesign = CLASSIC
    photos: InteriorPhotos = NO_PHOTOS
    elements: list[Element] = field(default_factory=list)
    issues: list[LayoutIssue] = field(default_factory=list)
    warnings: list[LayoutIssue] = field(default_factory=list)

    @property
    def look(self) -> Look | None:
        return self.design.look

    @property
    def themed(self) -> bool:
        """Puzzle, word-list, solution and divider pages take theme decoration."""
        return self.design.look is not None and self.plan_page.kind in THEMED_KINDS

    @property
    def page_body(self) -> Box:
        """The live area above the folio band."""
        content = self.frame.content
        return Box(content.x, content.y + FOLIO_BAND, content.width, content.height - FOLIO_BAND)

    @property
    def body(self) -> Box:
        """Where content goes: inside any page frame and below any motif band."""
        body = self.page_body
        look = self.look
        if look is None or not self.themed:
            return body
        if look.background == Background.FRAME.value:
            inset = OUTLINE_STROKE + PAGE_FRAME_PAD
            body = Box(
                body.x + inset, body.y + inset, body.width - 2 * inset, body.height - 2 * inset
            )
        if look.motif != Motif.NONE.value:
            reserved = MOTIF_HEIGHT[look.motif_intensity] + MOTIF_GAP
            body = Box(body.x, body.y, body.width, body.height - reserved)
        return body

    def gap(self, value: float) -> float:
        """A template gap at the look's spacing density (classic: unchanged)."""
        look = self.look
        return value if look is None else value * DENSITY[look.density]

    @property
    def center_x(self) -> float:
        return self.frame.content.x + self.frame.content.width / 2

    def issue(self, code: str, message: str, **context: str | None) -> None:
        subject = context.pop("subject", None)
        if subject is None and self.plan_page.puzzle is not None:
            subject = self.plan_page.puzzle.id
        self.issues.append(
            LayoutIssue(
                code,
                message,
                page=self.plan_page.index,
                physical_page=self.number,
                kind=str(self.plan_page.kind),
                subject=subject,
                **context,
            )
        )

    def warn(self, code: str, message: str, region: str) -> None:
        self.warnings.append(
            LayoutIssue(
                code,
                message,
                page=self.plan_page.index,
                physical_page=self.number,
                kind=str(self.plan_page.kind),
                region=region,
            )
        )

    def check_glyphs(self, text: str, face: Face, region: str) -> None:
        missing = missing_characters(text, face)
        if missing:
            self.issue(
                "unsupported_character",
                "The bundled font cannot draw these characters.",
                region=region,
                actual=" ".join(f"U+{ord(c):04X}" for c in missing),
            )

    def line(
        self,
        role: str,
        text: str,
        face: Face,
        size: float,
        x: float,
        baseline: float,
        anchor: Anchor = Anchor.START,
        gray: float = 0.0,
    ) -> None:
        self.check_glyphs(text, face, role)
        self.elements.append(text_line(role, text, face, size, x, baseline, anchor, gray))

    def block(
        self,
        role: str,
        text: str,
        face: Face,
        size: float,
        leading: float,
        measure: Box,
        top: float,
        anchor: Anchor,
        gray: float = 0.0,
    ) -> float:
        """Place wrapped text from `top` downward; return the block's bottom edge."""
        wrapped = wrap_text(text, face, size, measure.width)
        if wrapped.overflow_word is not None:
            self.issue(
                "text_overflow",
                "A word is wider than the available measure.",
                region=role,
                actual=f"{wrapped.overflow_width:.2f} pt",
                required=f"at most {measure.width:.2f} pt",
            )
            return top
        x = {
            Anchor.START: measure.x,
            Anchor.MIDDLE: measure.x + measure.width / 2,
            Anchor.END: measure.right,
        }[anchor]
        baseline = top - ASCENT * size
        for index, text_value in enumerate(wrapped.lines):
            if index:
                baseline -= leading
            if text_value:
                self.line(role, text_value, face, size, x, baseline, anchor, gray)
        return baseline - DESCENT * size

    def require_within(self, role: str, bottom: float, floor: float, height: float) -> None:
        if bottom < floor - 1e-6:
            self.issue(
                "text_overflow",
                "Text does not fit its region.",
                region=role,
                actual=f"{height + (floor - bottom):.2f} pt tall",
                required=f"at most {height:.2f} pt",
            )

    def freeze(self) -> PhysicalPage:
        number = self.plan_page.number
        return PhysicalPage(
            number=self.number,
            plan_index=self.plan_page.index,
            kind=str(self.plan_page.kind),
            frame=self.frame,
            elements=tuple(self.elements),
            folio=number.label if number.displayed else None,
        )


def layout_interior(
    plan: PublicationPlan,
    report: BatchReport,
    spec: PrintSpecification,
    design: InteriorDesign = CLASSIC,
    photos: InteriorPhotos = NO_PHOTOS,
) -> InteriorLayout:
    """Lay out a plan that `verify_publication_plan` has already accepted.

    `design` holds the resolved interior style; the classic design draws exactly
    the original interior. Raises InteriorError with every collected diagnostic
    when the print spec is invalid, content is not bound to the plan, or any
    element does not fit. Style readability notes are returned as warnings.
    """
    spec_issues = validate_print_spec(spec)
    if spec.bleed:
        spec_issues += (
            LayoutIssue(
                "unsupported_bleed_configuration",
                "Full bleed is for coloring books; word-search pages have nothing that "
                "prints past the trim. Use the same trim without bleed.",
                region="print.bleed",
            ),
        )
    if spec_issues:
        raise InteriorError("print_spec", spec_issues)
    puzzles, binding_issues = verify_puzzle_bindings(plan, report)
    if binding_issues:
        raise InteriorError("integrity", binding_issues)
    count_errors, warnings = page_count_checks(spec, len(plan.pages))
    if count_errors:
        raise InteriorError("layout", count_errors)

    # One template for the whole book, from the plan's largest group; never regrouped.
    largest = max((len(p.solutions) for p in plan.pages), default=0)
    if largest > max(SOLUTION_TEMPLATES):
        raise InteriorError(
            "layout",
            (
                LayoutIssue(
                    "unsupported_solution_density",
                    "No solution page template holds this many solutions.",
                    actual=str(largest),
                    required=f"at most {max(SOLUTION_TEMPLATES)}",
                ),
            ),
        )
    density = solution_template(largest) if largest else 1
    unreadable = _unreadable_solutions(plan, puzzles, spec, design, density) if largest else None
    # Spreads put each word list on its own page, facing a grid-only page.
    spread = {p.puzzle.id for p in plan.pages if p.kind is PageKind.PUZZLE_WORDS and p.puzzle}
    renderers: dict[PageKind, Callable[[_Page], None]] = {
        PageKind.TITLE_PAGE: _title_page,
        PageKind.COPYRIGHT_PAGE: _copyright_page,
        PageKind.INSTRUCTIONS: _text_page,
        PageKind.ABOUT: _text_page,
        PageKind.NOTES: _notes_page,
        PageKind.PUZZLE: lambda page: _puzzle_page(page, puzzles, plan, spread),
        PageKind.PUZZLE_WORDS: lambda page: _word_page(page, puzzles),
        PageKind.SOLUTIONS: lambda page: _solution_page(
            page, puzzles, plan, density, unreadable is not None
        ),
        PageKind.BLANK: lambda page: None,
        PageKind.DIVIDER: _divider_page,
    }
    pages: list[PhysicalPage] = []
    issues: list[LayoutIssue] = [] if unreadable is None else [unreadable]
    style_warnings: list[LayoutIssue] = []
    for position, plan_page in enumerate(plan.pages):
        page = _Page(spec, plan_page, position + 1, page_frame(spec, position + 1), design, photos)
        if plan_page.index != page.number:
            page.issue("plan_order", "Plan indexes must equal physical page order.")
        renderer = renderers.get(plan_page.kind)
        if renderer is None:
            page.issue("unsupported_page_type", "The renderer cannot draw this entry kind.")
        else:
            if page.themed:
                _decorate(page)
            renderer(page)
            if plan_page.number.displayed:
                _folio(page)
        issues.extend(page.issues)
        style_warnings.extend(page.warnings)
        pages.append(page.freeze())
    if issues:
        raise InteriorError("layout", tuple(issues))
    return InteriorLayout(
        spec=spec,
        book_id=plan.book_id,
        identity=plan.identity,
        plan_digest=plan_digest(plan),
        pages=tuple(pages),
        warnings=warnings + tuple(style_warnings),
        design=design,
    )


# ------------------------------------------------------------------ answer layouts


@dataclass(frozen=True)
class AnswerFit:
    """How one solutions-per-page choice prints this book's largest solution grids."""

    per_page: int
    columns: int
    rows: int
    letter_size: float  # The smallest solution letter on any page, in points.
    minimum: float  # The profile's minimum solution letter size.
    grid: tuple[int, int] | None  # The (width, height) grid that sets `letter_size`.

    @property
    def fits(self) -> bool:
        return self.letter_size >= self.minimum - 1e-6

    @property
    def comfortable(self) -> bool:
        return self.letter_size >= COMFORT_SOLUTION_LETTER - 1e-6

    def to_dict(self) -> dict[str, object]:
        return {
            "per_page": self.per_page,
            "columns": self.columns,
            "rows": self.rows,
            "letter_size": round(self.letter_size, 2),
            "minimum": self.minimum,
            "grid": None if self.grid is None else list(self.grid),
            "fits": self.fits,
            "comfortable": self.comfortable,
        }


def _solution_probe(
    spec: PrintSpecification, design: InteriorDesign, heading: str | None, index: int
) -> _Page:
    """A throwaway solution page, so fit checks share the renderer's exact geometry."""
    plan_page = PlanPage(
        index=index,
        section=Section.SOLUTIONS,
        kind=PageKind.SOLUTIONS,
        number=PageNumber(index, NumberStyle.ARABIC, True),
        heading=heading,
    )
    return _Page(spec, plan_page, index, page_frame(spec, index), design)


def answer_fits(
    spec: PrintSpecification,
    design: InteriorDesign,
    sizes: tuple[tuple[int, int], ...],
    heading: str | None,
) -> tuple[AnswerFit, ...]:
    """Each supported density's smallest solution letter for these grid sizes.

    Computed with the solution renderer's own slot geometry on a page with the
    section heading and one without, so it agrees with what a build would draw.
    """
    t = spec.typography
    found: list[AnswerFit] = []
    for density, (columns, rows) in sorted(SOLUTION_TEMPLATES.items()):
        letter, worst = t.solution_letter_max, None
        probes = (_solution_probe(spec, design, heading, 1), _solution_probe(spec, design, None, 2))
        for probe in probes:
            slots, caption = _solution_slots(probe, density)
            for width, height in sizes:
                geometry = _solution_grid(probe, width, height, slots[0], caption, density)
                if geometry.letter_size < letter - 1e-9:
                    letter, worst = geometry.letter_size, (width, height)
        if worst is None and sizes:
            worst = max(sizes, key=lambda s: max(s))
        found.append(
            AnswerFit(density, columns, rows, max(letter, 0.0), t.solution_letter_min, worst)
        )
    return tuple(found)


def _unreadable_solutions(
    plan: PublicationPlan,
    puzzles: dict[str, WordSearch],
    spec: PrintSpecification,
    design: InteriorDesign,
    density: int,
) -> LayoutIssue | None:
    """The issue for a solutions-per-page choice that cannot print every grid legibly.

    One clear issue naming the densest choice that fits, instead of a page of
    per-grid failures. The author's count is never changed.
    """
    sizes = tuple(sorted({(p.config.size.width, p.config.size.height) for p in puzzles.values()}))
    heading = next((p.heading for p in plan.pages if p.kind is PageKind.SOLUTIONS), None)
    fits = {fit.per_page: fit for fit in answer_fits(spec, design, sizes, heading)}
    chosen = fits[density]
    if chosen.fits:
        return None
    viable = [n for n, fit in fits.items() if fit.fits]
    advice = (
        f"Choose {max(viable)} solutions a page or fewer."
        if viable
        else "No solutions-per-page choice fits these grids on this trim size."
    )
    width, height = chosen.grid or (0, 0)
    return LayoutIssue(
        "solution_layout_unreadable",
        f"{density} solutions a page print {width} x {height} grids with "
        f"{chosen.letter_size:.1f} pt letters, below the {chosen.minimum:g} pt "
        f"minimum. {advice}",
        kind=PageKind.SOLUTIONS.value,
        region="composition.solutions.per_page",
        actual=f"{chosen.letter_size:.2f} pt",
        required=f"at least {chosen.minimum:g} pt",
    )


def _folio(page: _Page) -> None:
    size = page.spec.typography.folio
    content = page.frame.content
    baseline = content.y + DESCENT * size
    placement = (
        page.spec.folio_placement
        if page.design.folio is None
        else FolioPlacement(page.design.folio)
    )
    style = FolioStyle.PLAIN.value if page.look is None else page.look.folio_style
    label = page.plan_page.number.label
    inset = 0.0
    if style == FolioStyle.OUTLINE.value:
        # The box's stroke stays inside the live area; the number sits inside the box.
        inset = 4.0 if placement is not FolioPlacement.CENTER else 0.0
        baseline += OUTLINE_STROKE / 2 + 2.5
    if placement is FolioPlacement.CENTER:
        x, anchor = page.center_x, Anchor.MIDDLE
    elif page.frame.recto:
        x, anchor = content.right - inset - OUTLINE_STROKE * bool(inset), Anchor.END
    else:
        x, anchor = content.x + inset + OUTLINE_STROKE * bool(inset), Anchor.START
    page.line("folio", label, Face.REGULAR, size, x, baseline, anchor)
    if style == FolioStyle.PLAIN.value:
        return
    look = page.look
    assert look is not None
    text = page.elements[-1].bounds
    if style == FolioStyle.RULE.value:
        y = text.top + 4.0
        middle = text.x + text.width / 2
        _rule(page, "folio_rule", middle - 12, middle + 12, y, _stroke_gray(look.accent_gray))
        return
    box = Box(
        text.x - 4.0,
        content.y + OUTLINE_STROKE / 2,
        text.width + 8.0,
        text.top + 2.0 - (content.y + OUTLINE_STROKE / 2),
    )
    radius = 3.0 if look.corners == Corners.ROUNDED.value else 0.0
    page.elements.insert(
        len(page.elements) - 1,
        Panel("folio_box", box, None, look.secondary_gray, OUTLINE_STROKE, radius),
    )


def _measure(page: _Page) -> Box:
    body = page.body
    width = min(TEXT_MEASURE, body.width)
    return Box(page.center_x - width / 2, body.y, width, body.height)


def _title_page(page: _Page) -> None:
    layout = page.design.title_layout
    if layout != TitleLayout.MINIMAL.value:
        _styled_title_page(page, TitleLayout(layout))
        return
    matter = page.plan_page.matter
    assert matter is not None and matter.title is not None
    t, body = page.spec.typography, page.body
    full = body
    size = t.title if page.design.title_size is None else page.design.title_size
    left = page.design.title_align == Align.LEFT.value
    anchor = Anchor.START if left else Anchor.MIDDLE
    bottom = page.block(
        "title",
        matter.title,
        Face.BOLD,
        size,
        size * 1.2,
        full,
        body.top - body.height * 0.22,
        anchor,
    )
    rule_y = bottom - 18
    width = page.spec.strokes.rule
    if page.design.title_rule:
        start = body.x if left else page.center_x - 36
        page.elements.append(
            Rule(
                "title_rule",
                start,
                rule_y,
                start + 72,
                rule_y,
                width,
                Box(start, rule_y - width / 2, 72, width),
            )
        )
    bottom = rule_y - 18
    if matter.subtitle:
        bottom = page.block(
            "subtitle",
            matter.subtitle,
            Face.REGULAR,
            t.subtitle,
            t.subtitle * 1.3,
            body if left else _measure(page),
            bottom,
            anchor,
        )
    if matter.author:
        bottom = page.block(
            "author",
            matter.author,
            Face.REGULAR,
            t.author,
            t.author * 1.3,
            full,
            bottom - 36,
            anchor,
        )
    floor = body.y
    if matter.imprint:
        wrapped = wrap_text(matter.imprint, Face.REGULAR, t.imprint, body.width)
        lines = max(len(wrapped.lines), 1)
        height = (lines - 1) * t.imprint * 1.3 + (ASCENT + DESCENT) * t.imprint
        page.block(
            "imprint",
            matter.imprint,
            Face.REGULAR,
            t.imprint,
            t.imprint * 1.3,
            full,
            body.y + height,
            Anchor.MIDDLE,
        )
        floor = body.y + height + 18
    page.require_within("title_page", bottom, floor, body.top - floor)


def _copyright_page(page: _Page) -> None:
    """A notice sits at the foot of its page, in authored lines."""
    matter = page.plan_page.matter
    assert matter is not None and matter.text is not None
    t, measure = page.spec.typography, _measure(page)
    size, leading = t.copyright, t.copyright * 1.4
    wrapped = wrap_text(matter.text, Face.REGULAR, size, measure.width)
    height = (len(wrapped.lines) - 1) * leading + (ASCENT + DESCENT) * size
    if wrapped.overflow_word is None and height > measure.height:
        page.issue(
            "text_overflow",
            "Text does not fit its region.",
            region="copyright",
            actual=f"{height:.2f} pt tall",
            required=f"at most {measure.height:.2f} pt",
        )
        return
    page.block(
        "copyright",
        matter.text,
        Face.REGULAR,
        size,
        leading,
        measure,
        measure.y + height,
        Anchor.START,
    )


def _heading(page: _Page, text: str) -> float:
    t = page.spec.typography
    body = page.body
    look = page.look
    if look is not None and look.banner != Banner.NONE.value:
        return _banner(page, "heading", text, t.heading, Face.BOLD, Anchor.MIDDLE, look.banner)
    return page.block(
        "heading", text, Face.BOLD, t.heading, t.heading * 1.2, body, body.top, Anchor.MIDDLE
    )


def _stroke_gray(gray: float) -> float:
    """Accent rules print at least 40% black so thin lines stay visible."""
    return min(gray, 0.6)


def _banner(
    page: _Page,
    role: str,
    text: str,
    size: float,
    face: Face,
    anchor: Anchor,
    style: str,
    badge: str | None = None,
) -> float:
    """A heading in a solid or outlined box, or over a heavy rule; returns its bottom.

    The box spans the body; text wraps inside its padding and never shrinks. A
    solid box takes paper-white type when it is dark, and contrast is checked.
    """
    look = page.look
    assert look is not None
    body = page.body
    radius = BANNER_RADIUS if look.corners == Corners.ROUNDED.value else 0.0
    badge_width = 0.0
    if badge is not None:
        badge_width = text_width(badge, Face.BOLD, size * 0.8) + BANNER_PAD_X
    boxed = style in (Banner.SOLID.value, Banner.OUTLINE.value)
    pad_x = BANNER_PAD_X if boxed else 0.0
    pad_y = BANNER_PAD_Y if boxed else 0.0
    stroke = OUTLINE_STROKE if style == Banner.OUTLINE.value else 0.0
    measure = Box(
        body.x + pad_x + stroke + (badge_width if anchor is Anchor.MIDDLE else 0.0),
        body.y,
        body.width - 2 * (pad_x + stroke) - badge_width * (2 if anchor is Anchor.MIDDLE else 1),
        body.height,
    )
    wrapped = wrap_text(text, face, size, measure.width)
    lines = max(len(wrapped.lines), 1)
    text_height = (lines - 1) * size * 1.2 + (ASCENT + DESCENT) * size
    height = text_height + 2 * pad_y + 2 * stroke
    box = Box(
        body.x + stroke / 2, body.top - height + stroke / 2, body.width - stroke, height - stroke
    )
    text_gray = 0.0
    panel: Panel | None = None
    if style == Banner.SOLID.value:
        panel = Panel(role + "_banner", box, look.secondary_gray, None, 0.0, radius)
        text_gray = _text_gray(look.secondary_gray)
    elif style == Banner.OUTLINE.value:
        panel = Panel(role + "_banner", box, None, look.secondary_gray, OUTLINE_STROKE, radius)
    if panel is not None:
        page.elements.append(panel)
    top = body.top - stroke - pad_y
    bottom = page.block(role, text, face, size, size * 1.2, measure, top, anchor, text_gray)
    if panel is not None and panel.fill_gray is not None:
        _contrast(page, panel, text_gray, role)
    if badge is not None:
        page.line(
            role + "_number",
            badge,
            Face.BOLD,
            size * 0.8,
            body.right - stroke - pad_x,
            top - ASCENT * size,
            Anchor.END,
            text_gray,
        )
    if style == Banner.RULE.value:
        y = bottom - 6.0 - BANNER_RULE / 2
        _rule(
            page,
            role + "_banner",
            body.x,
            body.right,
            y,
            _stroke_gray(look.accent_gray),
            BANNER_RULE,
        )
        return y - BANNER_RULE / 2
    return body.top - height


def _text_page(page: _Page) -> None:
    matter = page.plan_page.matter
    assert matter is not None and matter.title is not None and matter.text is not None
    t = page.spec.typography
    top = _heading(page, matter.title) - HEADING_GAP
    measure = _measure(page)
    bottom = page.block(
        "body", matter.text, Face.REGULAR, t.body, t.body * 1.45, measure, top, Anchor.START
    )
    page.require_within("body", bottom, measure.y, top - measure.y)


def _notes_page(page: _Page) -> None:
    matter = page.plan_page.matter
    assert matter is not None and matter.title is not None
    top = _heading(page, matter.title) - HEADING_GAP - NOTES_SPACING
    body, width = page.body, page.spec.strokes.notes_line
    y = top
    while y >= body.y + width / 2 - 1e-6:
        page.elements.append(
            Rule(
                "notes_line",
                body.x,
                y,
                body.right,
                y,
                width,
                Box(body.x, y - width / 2, body.width, width),
                NOTES_GRAY,
            )
        )
        y -= NOTES_SPACING


@dataclass(frozen=True)
class _WordTable:
    words: tuple[str, ...]
    columns: int
    rows: int
    widest: float
    height: float
    size: float
    face: Face
    leading: float
    gap: float


def _word_size(page: _Page) -> float:
    size = page.design.word_size
    return page.spec.typography.word_list if size is None else size


def _grid_stroke(page: _Page) -> float:
    stroke = page.design.grid_frame
    return page.spec.strokes.grid_frame if stroke is None else stroke


def _word_table(
    page: _Page,
    words: tuple[str, ...],
    size: float | None = None,
    leading: float | None = None,
) -> _WordTable | None:
    """Most columns (up to five, or the style's limit) whose uniform width fits."""
    look = page.look
    size = _word_size(page) if size is None else size
    face = Face.BOLD if look is not None and look.word_weight == Weight.BOLD.value else Face.REGULAR
    if leading is None:
        leading = WORD_LEADING if look is None else look.word_leading
    gap = page.gap(WORD_COLUMN_GAP)
    width = page.body.width
    widest = max(text_width(word, face, size) for word in words)
    if widest > width:
        page.issue(
            "word_list_overflow",
            "A word-list entry is wider than the page's live area.",
            region="word_list",
            actual=f"{widest:.2f} pt",
            required=f"at most {width:.2f} pt",
        )
        return None
    limit = min(MAX_WORD_COLUMNS, page.design.word_columns)
    columns = next(
        n for n in range(min(limit, len(words)), 0, -1) if n * widest + (n - 1) * gap <= width
    )
    rows = math.ceil(len(words) / columns)
    height = (rows - 1) * size * leading + (ASCENT + DESCENT) * size
    return _WordTable(words, columns, rows, widest, height, size, face, leading, gap)


def _table_span(table: _WordTable) -> float:
    return table.columns * table.widest + (table.columns - 1) * table.gap


def _table_left(page: _Page, table: _WordTable) -> float:
    look = page.look
    if look is not None and look.word_align == Align.LEFT.value:
        return page.body.x
    return page.center_x - _table_span(table) / 2


def _place_word_table(page: _Page, table: _WordTable, top: float) -> None:
    """Column-major, in authoritative target order, centered (or left) as one table."""
    left = _table_left(page, table)
    for index, word in enumerate(table.words):
        column, row = divmod(index, table.rows)
        x = left + column * (table.widest + table.gap)
        baseline = top - ASCENT * table.size - row * table.size * table.leading
        page.line("word_list", word, table.face, table.size, x, baseline)


def _grid_letters_fit(page: _Page, geometry: GridGeometry, minimum: float, region: str) -> bool:
    if geometry.cell <= 0 or geometry.letter_size < minimum - 1e-6:
        page.issue(
            "grid_too_small",
            "Grid letters would fall below the profile's minimum size.",
            region=region,
            actual=f"{max(geometry.letter_size, 0):.2f} pt",
            required=f"at least {minimum:g} pt",
        )
        return False
    return True


def _letter_grid(
    role: str,
    puzzle: WordSearch,
    geometry: GridGeometry,
    spec: PrintSpecification,
    marks: bool,
    design: InteriorDesign = CLASSIC,
) -> LetterGrid:
    placements = puzzle.solution.placements if marks else ()
    cells = frozenset((c.x, c.y) for p in placements for c in p.coordinates)

    def center(x: int, y: int) -> tuple[float, float]:
        return (
            geometry.origin_x + (x + 0.5) * geometry.cell,
            geometry.top - (y + 0.5) * geometry.cell,
        )

    look = design.look
    rounded = look is not None and look.corners == Corners.ROUNDED.value
    return LetterGrid(
        role=role,
        rows=puzzle.grid.rows,
        origin_x=geometry.origin_x,
        top=geometry.top,
        cell=geometry.cell,
        letter_size=geometry.letter_size,
        face=Face.REGULAR,
        frame=geometry.frame,
        frame_width=geometry.stroke,
        baseline_offset=CAP_HEIGHT * geometry.letter_size / 2,
        emphasized=cells,
        muted_gray=design.muted_gray if marks else 0.0,
        marks=tuple(
            SolutionMark(
                p.target_id,
                center(p.start.x, p.start.y),
                center(p.end.x, p.end.y),
                geometry.cell * MARK_RADIUS,
                spec.strokes.solution_mark if design.mark_width is None else design.mark_width,
            )
            for p in placements
        ),
        frame_radius=min(geometry.cell * GRID_CORNER, 8.0) if rounded else 0.0,
    )


def _label_gray(page: _Page, role: str) -> float:
    """Accent-toned labels when the look asks for them, warned when too light to read."""
    look = page.look
    if look is None or not look.accent_labels:
        return 0.0
    if look.accent_gray > LIGHT_TEXT + 1e-9:
        page.warn(
            "light_text",
            f"The accent prints as {_ink(look.accent_gray)}% black; {role.replace('_', ' ')} "
            "text this light may be hard to read. Choose a darker accent.",
            role,
        )
    return look.accent_gray


def _puzzle_header(page: _Page, ref: PuzzleRef) -> float:
    """Title (plain or in a banner), optional puzzle number, theme label and rule."""
    t, body, d, look = page.spec.typography, page.body, page.design, page.look
    anchor = Anchor.START if d.header_align == Align.LEFT.value else Anchor.MIDDLE
    title_size = t.puzzle_title if d.puzzle_title_size is None else d.puzzle_title_size
    face = Face.BOLD if d.puzzle_title_bold else Face.REGULAR
    number = str(ref.ordinal) if look is not None and look.puzzle_number else None
    start = len(page.elements)
    if look is not None and look.title_banner:
        style = Banner.SOLID.value if look.banner == Banner.NONE.value else look.banner
        bottom = _banner(page, "puzzle_title", ref.title, title_size, face, anchor, style, number)
    else:
        measure = body
        if number is not None:
            reserve = text_width(number, Face.BOLD, title_size * 0.8) + BANNER_PAD_X
            twice = anchor is Anchor.MIDDLE
            measure = Box(
                body.x + (reserve if twice else 0.0),
                body.y,
                body.width - reserve * (2 if twice else 1),
                body.height,
            )
        bottom = page.block(
            "puzzle_title", ref.title, face, title_size, title_size * 1.2, measure, body.top, anchor
        )
        if number is not None:
            page.line(
                "puzzle_title_number",
                number,
                Face.BOLD,
                title_size * 0.8,
                body.right,
                body.top - ASCENT * title_size,
                Anchor.END,
                _label_gray(page, "puzzle_number"),
            )
    if d.theme_label:
        theme_size = t.theme if d.theme_size is None else d.theme_size
        bottom = page.block(
            "theme",
            ref.theme,
            Face.ITALIC,
            theme_size,
            theme_size * 1.3,
            body,
            bottom - 6,
            anchor,
            _label_gray(page, "theme"),
        )
    if d.header_rule:
        rule_y = bottom - 10
        gray = 0.0 if look is None else _stroke_gray(look.accent_gray)
        _rule(page, "header_rule", body.x, body.right, rule_y, gray)
        bottom = rule_y - page.spec.strokes.rule / 2
    if look is not None and page.themed and look.background == Background.HEADER_BAND.value:
        bottom -= 6.0
        band = Box(body.x, bottom, body.width, body.top - bottom)
        page.elements.insert(start, Panel("header_band", band, HEADER_BAND_GRAY))
    return bottom


def _answer_reference(page: _Page, plan: PublicationPlan) -> float:
    """The authored "solution on page N" line at the foot of the body; returns its top."""
    body, look = page.body, page.look
    target = page.plan_page.solution_page
    if look is None or look.answer_reference is None or target is None:
        return body.y
    size = (
        page.spec.typography.caption
        if page.design.caption_size is None
        else (page.design.caption_size)
    )
    text = look.answer_reference.replace("{page}", plan.pages[target - 1].number.label)
    width = text_width(text, Face.ITALIC, size)
    if width > body.width:
        page.issue(
            "text_overflow",
            "The answer reference is wider than the page.",
            region="answer_reference",
            actual=f"{width:.2f} pt",
            required=f"at most {body.width:.2f} pt",
        )
        return body.y
    left = page.design.header_align == Align.LEFT.value
    page.line(
        "answer_reference",
        text,
        Face.ITALIC,
        size,
        body.x if left else page.center_x,
        body.y + DESCENT * size,
        Anchor.START if left else Anchor.MIDDLE,
        LABEL_GRAY,
    )
    return body.y + (ASCENT + DESCENT) * size + page.gap(FOOTER_GAP)


def _fit_puzzle_grid(page: _Page, puzzle: WordSearch, region: Box) -> GridGeometry:
    t, look = page.spec.typography, page.look
    ratio = LETTER_RATIO if look is None else look.letter_ratio
    if look is not None and look.grid_width < 100:
        width = region.width * look.grid_width / 100
        region = Box(region.x + (region.width - width) / 2, region.y, width, region.height)
    return fit_grid(
        puzzle.config.size.width,
        puzzle.config.size.height,
        region,
        t.grid_letter_max,
        _grid_stroke(page),
        max_cell_for_letter(t.grid_letter_max, ratio),
        ratio,
    )


def _puzzle_page(
    page: _Page, puzzles: dict[str, WordSearch], plan: PublicationPlan, spread: set[str]
) -> None:
    ref = page.plan_page.puzzle
    assert ref is not None
    puzzle = puzzles[ref.id]
    body, d, look = page.body, page.design, page.look
    region_top = _puzzle_header(page, ref) - page.gap(HEADING_GAP)
    if page.issues:
        return
    floor = _answer_reference(page, plan)
    available = region_top - floor
    if ref.id in spread:
        # A spread's grid page: the grid alone, centred in the space below the header.
        geometry = _fit_puzzle_grid(page, puzzle, Box(body.x, floor, body.width, available))
        if not _grid_letters_fit(
            page, geometry, page.spec.typography.grid_letter_min, "puzzle_grid"
        ):
            return
        geometry = geometry.moved(-(available - geometry.bounds.height) / 2)
        page.elements.append(_letter_grid("puzzle_grid", puzzle, geometry, page.spec, False, d))
        return
    table = _word_table(page, tuple(target.display for target in puzzle.targets))
    if table is None:
        return
    gap = page.gap(WORD_GAP)
    grid_height = available - table.height - gap
    if grid_height <= 0:
        page.issue(
            "word_list_overflow",
            "The word list leaves no room for the grid.",
            region="word_list",
            actual=f"{table.height:.2f} pt tall",
            required=f"less than {available - gap:.2f} pt",
        )
        return
    above = look is not None and look.word_position == WordPosition.ABOVE.value
    grid_top = region_top - (table.height + gap if above else 0.0)
    geometry = _fit_puzzle_grid(
        page, puzzle, Box(body.x, grid_top - grid_height, body.width, grid_height)
    )
    if not _grid_letters_fit(page, geometry, page.spec.typography.grid_letter_min, "puzzle_grid"):
        return
    # Center the painted grid and word list together in the space below the header.
    block = geometry.bounds.height + gap + table.height
    shift = (available - block) / 2
    geometry = geometry.moved(-shift)
    page.elements.append(_letter_grid("puzzle_grid", puzzle, geometry, page.spec, False, d))
    rule_gray = 0.0 if look is None else _stroke_gray(look.accent_gray)
    span = _table_span(table)
    left = _table_left(page, table)
    if above:
        if d.word_rule:
            _rule(page, "word_rule", left, left + span, geometry.bounds.top + gap / 2, rule_gray)
        _place_word_table(page, table, region_top - shift)
        return
    if d.word_rule:
        _rule(page, "word_rule", left, left + span, geometry.bounds.y - gap / 2, rule_gray)
    _place_word_table(page, table, geometry.bounds.y - gap)


def _word_page(page: _Page, puzzles: dict[str, WordSearch]) -> None:
    """A spread's left-hand page: the header and a large word list, centred."""
    ref = page.plan_page.puzzle
    assert ref is not None
    puzzle = puzzles[ref.id]
    region_top = _puzzle_header(page, ref) - page.gap(HEADING_GAP)
    if page.issues:
        return
    look = page.look
    leading = max(WORD_LEADING if look is None else look.word_leading, 1.8)
    size = min(_word_size(page) * 1.3, 20.0)
    table = _word_table(page, tuple(t.display for t in puzzle.targets), size, leading)
    if table is None:
        return
    available = region_top - page.body.y
    if table.height > available:
        page.issue(
            "word_list_overflow",
            "The word list does not fit its page.",
            region="word_list",
            actual=f"{table.height:.2f} pt tall",
            required=f"at most {available:.2f} pt",
        )
        return
    _place_word_table(page, table, region_top - (available - table.height) / 2)


def _solution_slots(page: _Page, density: int) -> tuple[tuple[Box, ...], float]:
    """The page's solution slots (below any section heading) and its caption size."""
    body = page.body
    top = body.top
    if page.plan_page.heading:
        top = _heading(page, page.plan_page.heading) - page.gap(HEADING_GAP) + 6
    region = Box(body.x, body.y, body.width, top - body.y)
    slots = solution_slots(density, region, page.gap(SOLUTION_GAP_X), page.gap(SOLUTION_GAP_Y))
    d = page.design
    caption = page.spec.typography.caption if d.caption_size is None else d.caption_size
    return slots, caption


def _solution_grid(
    page: _Page, width: int, height: int, slot: Box, caption: float, density: int
) -> GridGeometry:
    t = page.spec.typography
    caption_height = (ASCENT + DESCENT) * caption
    region = Box(slot.x, slot.y, slot.width, slot.height - caption_height - CAPTION_GAP)
    ratio = SOLUTION_LETTER_RATIO.get(density, LETTER_RATIO)
    return fit_grid(
        width,
        height,
        region,
        t.solution_letter_max,
        _grid_stroke(page),
        max_cell_for_letter(t.solution_letter_max, ratio),
        ratio,
    )


def _solution_page(
    page: _Page,
    puzzles: dict[str, WordSearch],
    plan: PublicationPlan,
    density: int,
    reported: bool = False,
) -> None:
    """`reported`: an unreadable density is already one issue; grids too small say no more."""
    t = page.spec.typography
    slots, caption = _solution_slots(page, density)
    d, look = page.design, page.look
    cramped = False
    for slot, item in zip(slots, page.plan_page.solutions, strict=False):
        puzzle = puzzles[item.puzzle.id]
        size = puzzle.config.size
        geometry = _solution_grid(page, size.width, size.height, slot, caption, density)
        if reported and geometry.letter_size < t.solution_letter_min - 1e-6:
            continue
        if not _grid_letters_fit(page, geometry, t.solution_letter_min, "solution_grid"):
            continue
        if geometry.letter_size < COMFORT_SOLUTION_LETTER - 1e-6 and not cramped:
            cramped = True
            page.warn(
                "dense_solution_page",
                f"Solution letters print at {geometry.letter_size:.1f} pt: legal, but cramped "
                f"below {COMFORT_SOLUTION_LETTER:g} pt. Fewer solutions a page read more easily.",
                "solution_grid",
            )
        label = plan.pages[item.puzzle_page - 1].number.label
        if look is not None and look.page_label is not None:
            label = look.page_label.replace("{page}", label)
        title_width = text_width(item.puzzle.title, Face.BOLD, caption)
        label_width = text_width(label, Face.REGULAR, caption)
        combined = title_width + CAPTION_GAP + label_width
        if combined > slot.width:
            page.issue(
                "text_overflow",
                "Solution caption is wider than its slot.",
                region="solution_caption",
                subject=item.puzzle.id,
                actual=f"{combined:.2f} pt",
                required=f"at most {slot.width:.2f} pt",
            )
            continue
        center = geometry.frame.x + geometry.frame.width / 2
        baseline = slot.top - ASCENT * caption
        start = center - combined / 2
        page.line("solution_caption", item.puzzle.title, Face.BOLD, caption, start, baseline)
        page.line(
            "solution_page_ref",
            label,
            Face.REGULAR,
            caption,
            start + title_width + CAPTION_GAP,
            baseline,
            gray=LABEL_GRAY,
        )
        page.elements.append(
            _letter_grid("solution_grid", puzzle, geometry, page.spec, marks=True, design=d)
        )


def _decorate(page: _Page) -> None:
    """A themed page's frame and motif, drawn first so content paints over nothing."""
    look = page.look
    assert look is not None
    base = page.page_body
    inner = base
    rounded = look.corners == Corners.ROUNDED.value
    if look.background == Background.FRAME.value:
        page.elements.append(
            Panel(
                "page_frame",
                base.expanded(-OUTLINE_STROKE / 2),
                None,
                look.secondary_gray,
                OUTLINE_STROKE,
                PAGE_FRAME_RADIUS if rounded else 0.0,
            )
        )
        inset = OUTLINE_STROKE + PAGE_FRAME_PAD
        inner = base.expanded(-inset)
    if look.motif != Motif.NONE.value:
        height = MOTIF_HEIGHT[look.motif_intensity]
        _motif(page, Box(inner.x, inner.top - height, inner.width, height))


def _motif(page: _Page, band: Box) -> None:
    """Angled stripes or chevrons at the outer corner, a hairline toward the gutter."""
    look = page.look
    assert look is not None
    count = MOTIF_COUNT[look.motif_intensity]
    h = band.height
    width, gap, slant = h * 0.55, h * 0.45, h * 0.7
    span = count * width + (count - 1) * gap + slant
    outward = page.frame.recto  # Recto pages point right, versos left: a mirrored spread.
    cluster = Box(band.right - span if outward else band.x, band.y, span, h)
    tone = look.accent_gray
    if look.motif_intensity == Intensity.SUBTLE.value:
        tone = 1 - (1 - tone) * 0.6
    for index in range(count):
        gray = (
            look.secondary_gray
            if look.motif_intensity == Intensity.BOLD.value and index % 2
            else tone
        )
        x = cluster.x + index * (width + gap)
        y0, y1 = band.y, band.top
        points: tuple[tuple[float, float], ...]
        if look.motif == Motif.STRIPES.value:
            if outward:
                points = ((x, y0), (x + width, y0), (x + width + slant, y1), (x + slant, y1))
            else:
                points = ((x + slant, y0), (x + width + slant, y0), (x + width, y1), (x, y1))
        else:
            thick, mid, tip = width * 0.55, (y0 + y1) / 2, width + slant * 0.5
            if outward:
                points = (
                    (x, y1),
                    (x + thick, y1),
                    (x + tip, mid),
                    (x + thick, y0),
                    (x, y0),
                    (x + tip - thick, mid),
                )
            else:
                right = x + tip
                points = (
                    (right, y1),
                    (right - thick, y1),
                    (right - tip, mid),
                    (right - thick, y0),
                    (right, y0),
                    (right - tip + thick, mid),
                )
        page.elements.append(Polygon("motif", points, gray, cluster))
    y = band.y + h / 2
    if outward:
        _rule(page, "motif_rule", band.x, cluster.x - gap, y, _stroke_gray(tone))
    else:
        _rule(page, "motif_rule", cluster.right + gap, band.right, y, _stroke_gray(tone))


# ------------------------------------------------------------------ styled pages


def _rule(
    page: _Page,
    role: str,
    x1: float,
    x2: float,
    y: float,
    gray: float = 0.0,
    width: float | None = None,
) -> None:
    width = page.spec.strokes.rule if width is None else width
    page.elements.append(
        Rule(role, x1, y, x2, y, width, Box(x1, y - width / 2, x2 - x1, width), gray)
    )


def _ink(gray: float) -> int:
    return round((1 - gray) * 100)


def _panel(
    page: _Page,
    role: str,
    box: Box,
    tint: int,
    stroke: bool = False,
) -> Panel:
    """A tinted block (tint > 0) and/or a ruled frame, with readability notes."""
    fill = None if tint <= 0 else 1 - tint / 100
    panel = Panel(role, box, fill, 0.0 if stroke else None, FRAME_STROKE if stroke else 0.0)
    page.elements.append(panel)
    trim = page.frame.trim
    share = box.width * box.height / (trim.width * trim.height)
    if tint >= HEAVY_TINT and share >= HEAVY_SHARE:
        page.warn(
            "heavy_ink_coverage",
            f"A {tint}% black block covers {share:.0%} of the page; heavy ink can show "
            "through thin paper and darken facing pages.",
            role,
        )
    return panel


def _image(page: _Page, role: str, box: Box, sha256: str, crop: Crop) -> None:
    block = place_photo(role, box, page.photos.info[sha256], crop)
    page.elements.append(block)
    if block.effective_dpi + 1e-9 < KDP.min_image_dpi:
        page.warn(
            "image_low_effective_dpi"
            if block.max_dpi + 1e-9 >= KDP.min_image_dpi
            else "image_too_small",
            f"This photograph prints at {block.effective_dpi:.0f} DPI; KDP needs "
            f"{KDP.min_image_dpi:g} (at most {block.max_dpi:.0f} available).",
            role,
        )


def _text_gray(panel_gray: float | None) -> float:
    """Black on light panels, paper white on dark ones."""
    return 1.0 if panel_gray is not None and panel_gray <= DARK_PANEL else 0.0


def _contrast(page: _Page, panel: Panel, text_gray: float, role: str) -> None:
    if panel.fill_gray is not None and abs(panel.fill_gray - text_gray) < MIN_CONTRAST:
        page.warn(
            "low_contrast_text",
            f"{role.replace('_', ' ').capitalize()} prints in {_ink(text_gray)}% black on a "
            f"{_ink(panel.fill_gray)}% panel; the difference may be hard to read in print. "
            "Choose a lighter or darker tint.",
            role,
        )


def _imprint_floor(page: _Page, anchor: Anchor, measure: Box, gray: float = 0.0) -> float:
    """Set the imprint at the foot of the body; return the space above it."""
    matter = page.plan_page.matter
    assert matter is not None
    t = page.spec.typography
    if not matter.imprint:
        return measure.y
    wrapped = wrap_text(matter.imprint, Face.REGULAR, t.imprint, measure.width)
    lines = max(len(wrapped.lines), 1)
    height = (lines - 1) * t.imprint * 1.3 + (ASCENT + DESCENT) * t.imprint
    page.block(
        "imprint",
        matter.imprint,
        Face.REGULAR,
        t.imprint,
        t.imprint * 1.3,
        measure,
        measure.y + height,
        anchor,
        gray,
    )
    return measure.y + height + 18


def _styled_title_page(page: _Page, layout: TitleLayout) -> None:
    """Editorial, colour block, framed and photo-feature title pages (no bleed).

    Every element stays inside the live area; tints are percentages of black ink.
    """
    matter = page.plan_page.matter
    assert matter is not None and matter.title is not None
    t, d, body = page.spec.typography, page.design, page.body
    size = d.title_size if d.title_size is not None else t.title
    left = d.title_align == Align.LEFT.value
    anchor = Anchor.START if left else Anchor.MIDDLE
    measure = body
    floor_measure = body
    title_top = body.top - body.height * 0.22
    text_gray = 0.0
    panel: Panel | None = None
    if layout is TitleLayout.EDITORIAL:
        rule_y = body.top - body.height * 0.16
        _rule(page, "title_rule", body.x, body.right, rule_y)
        title_top = rule_y - 24
    elif layout is TitleLayout.COLOR_BLOCK:
        height = body.height * 0.42
        block = Box(body.x, body.top - height, body.width, height)
        panel = _panel(page, "title_block", block, d.title_tint)
        text_gray = _text_gray(panel.fill_gray)
        measure = Box(
            block.x + PANEL_PAD, block.y + PANEL_PAD, block.width - 2 * PANEL_PAD, block.height
        )
        title_top = block.top - PANEL_PAD - block.height * 0.18
    elif layout is TitleLayout.PHOTO_FEATURE:
        photo = page.photos.images.title
        if photo is None or photo.image.sha256 not in page.photos.info:
            page.issue("photo_missing", "The photo feature has no photograph.", region="title")
            return
        height = body.height * 0.48
        box = Box(body.x, body.top - height, body.width, height)
        _image(page, "title_photo", box, photo.image.sha256, photo.crop)
        title_top = box.y - 30
    elif layout is TitleLayout.FRAMED:
        frame = Box(
            body.x + FRAME_INSET,
            page.frame.content.y + FRAME_INSET,
            body.width - 2 * FRAME_INSET,
            body.top - page.frame.content.y - 2 * FRAME_INSET,
        )
        panel = _panel(page, "title_frame", frame, d.title_tint, stroke=True)
        text_gray = _text_gray(panel.fill_gray)
        inner = FRAME_INSET + FRAME_STROKE + PANEL_PAD
        measure = Box(
            body.x + inner, body.y + inner, body.width - 2 * inner, body.height - 2 * inner
        )
        floor_measure = measure
        title_top = body.top - body.height * 0.3
    bottom = page.block(
        "title", matter.title, Face.BOLD, size, size * 1.2, measure, title_top, anchor, text_gray
    )
    if panel is not None:
        _contrast(page, panel, text_gray, "title")
    if d.title_rule and layout is not TitleLayout.EDITORIAL:
        rule_y = bottom - 18
        start = measure.x if left else page.center_x - 36
        width = page.spec.strokes.rule
        page.elements.append(
            Rule(
                "title_rule",
                start,
                rule_y,
                start + 72,
                rule_y,
                width,
                Box(start, rule_y - width / 2, 72, width),
                text_gray,
            )
        )
        bottom = rule_y - 18
    else:
        bottom -= 14
    if matter.subtitle:
        sub_measure = measure if left or layout is not TitleLayout.MINIMAL else _measure(page)
        bottom = page.block(
            "subtitle",
            matter.subtitle,
            Face.REGULAR,
            t.subtitle,
            t.subtitle * 1.3,
            sub_measure,
            bottom,
            anchor,
            text_gray,
        )
    if panel is not None and panel.fill_gray is not None and layout is TitleLayout.COLOR_BLOCK:
        if bottom < panel.box.y + PANEL_PAD - 1e-6:
            page.issue(
                "text_overflow",
                "The title and subtitle do not fit the tinted block.",
                region="title_block",
            )
            return
        text_gray = 0.0  # The author and imprint sit on paper below the block.
    floor = _imprint_floor(
        page, anchor, floor_measure, text_gray if layout is TitleLayout.FRAMED else 0.0
    )
    if matter.author:
        author_gray = text_gray if layout is TitleLayout.FRAMED else 0.0
        if layout in (TitleLayout.EDITORIAL, TitleLayout.COLOR_BLOCK):
            # The author sits low on the page, above the imprint.
            height = (ASCENT + DESCENT) * t.author
            author_top = floor + height
            if author_top > bottom - 24:
                author_top = bottom - 36
            page.block(
                "author",
                matter.author,
                Face.REGULAR,
                t.author,
                t.author * 1.3,
                measure if layout is TitleLayout.EDITORIAL else body,
                author_top,
                anchor,
                author_gray,
            )
            bottom = min(bottom, author_top - height)
        else:
            bottom = page.block(
                "author",
                matter.author,
                Face.REGULAR,
                t.author,
                t.author * 1.3,
                measure,
                bottom - 36,
                anchor,
                author_gray,
            )
    page.require_within("title_page", bottom, floor, body.top - floor)


def _divider_page(page: _Page) -> None:
    """A theme divider: its title, the author's description and quote, if any."""
    divider = page.plan_page.divider
    assert divider is not None
    t, d, body = page.spec.typography, page.design, page.body
    layout = DividerLayout(d.divider_layout)
    measure = _measure(page)
    title_top = body.top - body.height * 0.3
    text_gray = 0.0
    panel: Panel | None = None
    size = t.heading * 1.3
    photo = page.photos.images.theme(divider.theme)
    if photo is not None and photo.image.sha256 in page.photos.info:
        # A photograph takes the band's place; a frame keeps it inside.
        inset = FRAME_INSET + FRAME_STROKE + PANEL_PAD if layout is DividerLayout.FRAMED else 0.0
        if layout is DividerLayout.BAND:
            layout = DividerLayout.CENTERED
        height = body.height * 0.4
        box = Box(body.x + inset, body.top - inset - height, body.width - 2 * inset, height)
        _image(page, "divider_photo", box, photo.image.sha256, photo.crop)
        title_top = box.y - 30
    if layout is DividerLayout.BAND:
        height = body.height * 0.34
        band = Box(body.x, body.top - height, body.width, height)
        panel = _panel(page, "divider_band", band, d.divider_tint or 85)
        text_gray = _text_gray(panel.fill_gray)
        title_top = band.top - height * 0.38
    elif layout is DividerLayout.FRAMED:
        frame = Box(
            body.x + FRAME_INSET,
            body.y + FRAME_INSET,
            body.width - 2 * FRAME_INSET,
            body.height - 2 * FRAME_INSET,
        )
        panel = _panel(page, "divider_frame", frame, d.divider_tint, stroke=True)
        text_gray = _text_gray(panel.fill_gray)
    bottom = page.block(
        "divider_title",
        divider.title,
        Face.BOLD,
        size,
        size * 1.2,
        Box(measure.x, body.y, measure.width, body.height),
        title_top,
        Anchor.MIDDLE,
        text_gray,
    )
    if panel is not None:
        _contrast(page, panel, text_gray, "divider_title")
    rule_y = bottom - 16
    width = page.spec.strokes.rule
    page.elements.append(
        Rule(
            "divider_rule",
            page.center_x - 36,
            rule_y,
            page.center_x + 36,
            rule_y,
            width,
            Box(page.center_x - 36, rule_y - width / 2, 72, width),
            text_gray,
        )
    )
    bottom = rule_y - 18
    if layout is DividerLayout.BAND:
        assert panel is not None
        if bottom < panel.box.y + 12:
            page.issue(
                "text_overflow",
                "The divider title does not fit its band.",
                region="divider_band",
            )
            return
        bottom = panel.box.y - 30
        text_gray = 0.0
    floor = body.y + (FRAME_INSET + PANEL_PAD if layout is DividerLayout.FRAMED else 0.0)
    if divider.text:
        bottom = page.block(
            "divider_text",
            divider.text,
            Face.REGULAR,
            t.body,
            t.body * 1.45,
            measure,
            bottom,
            Anchor.MIDDLE,
            text_gray,
        )
    if divider.quote:
        bottom = page.block(
            "divider_quote",
            divider.quote,
            Face.ITALIC,
            t.body,
            t.body * 1.45,
            measure,
            bottom - 18,
            Anchor.MIDDLE,
            text_gray,
        )
        if divider.attribution:
            bottom = page.block(
                "divider_attribution",
                f"— {divider.attribution}",
                Face.REGULAR,
                t.caption,
                t.caption * 1.3,
                measure,
                bottom - 6,
                Anchor.MIDDLE,
                text_gray,
            )
    page.require_within("divider", bottom, floor, title_top - floor)
