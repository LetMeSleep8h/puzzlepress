"""Physical print specification, units and centralized KDP paperback constraints.

All physical values are PDF points (1 inch = 72 points), converted once here.
Semantic composition never contains these values; renderers receive them separately.
"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum

from .issues import LayoutIssue

POINTS_PER_INCH = 72
# Geometric comparisons tolerate float rounding well below any printable distance.
TOLERANCE = 1e-6


def inches(value: float) -> float:
    """The single inch-to-point conversion used for authored physical values."""
    return value * POINTS_PER_INCH


def to_inches(points: float) -> float:
    return points / POINTS_PER_INCH


class Paper(StrEnum):
    """Interior paper stock. It sets cover spine width; it is never inferred."""

    WHITE = "white"
    CREAM = "cream"


@dataclass(frozen=True)
class KdpConstraints:
    """The one home of KDP paperback values. Provenance: docs/preflight.md.

    Checked 2026-10-07 against KDP help: "Set Trim Size, Bleed, and Margins"
    (gutter table, outside margins), "Paperback Submission Guidelines" (24-page
    minimum, 7 pt text, 0.75 pt lines, 300 DPI, embedded fonts, single pages, no
    marks/annotations/bookmarks/encryption, flattened transparency, even folios
    on left pages), "Fix Paperback and Hardcover Formatting Issues" (consecutive
    blank pages, "fully embedded" fonts) and "Print Options" (custom trim range).
    """

    min_font_size: float = 7.0
    # KDP states "0.75 point or 0.01 in (0.3 mm)"; 0.01 in is 0.72 pt, so the
    # stricter stated value is enforced.
    min_line_weight: float = 0.75
    min_pages: int = 24
    min_outside_margin: float = inches(0.25)
    min_outside_margin_with_bleed: float = inches(0.375)
    min_image_dpi: float = 300.0
    max_blank_run: int = 4  # Consecutive blank pages at the beginning or middle.
    max_trailing_blank_run: int = 10  # Consecutive blank pages at the end.
    # Paperback custom trim range (width, height) in points, inclusive.
    custom_trim_width: tuple[float, float] = (inches(4), inches(8.5))
    custom_trim_height: tuple[float, float] = (inches(6), inches(11.69))
    # Maximum black-ink page count per trim and paper (preflight ruleset 5). Read
    # 2026-11-05 on the official "Set Trim Size, Bleed, and Margins" page, whose table
    # now lists every row: 8.5 x 11 and 8.5 x 8.5 at 24-590 white / 24-550 cream,
    # 6 x 9 and 8 x 10 at 24-828 white / 24-776 cream. Rulesets 3-4 applied the lower
    # (cream) value to both papers because the 8.5 x 11 row was then missing.
    max_pages_by_print: tuple[tuple[str, Paper, int], ...] = (
        ("8.5x11", Paper.WHITE, 590),
        ("8.5x11", Paper.CREAM, 550),
        ("6x9", Paper.WHITE, 828),
        ("6x9", Paper.CREAM, 776),
        ("8x10", Paper.WHITE, 828),
        ("8x10", Paper.CREAM, 776),
        ("8.5x8.5", Paper.WHITE, 590),
        ("8.5x8.5", Paper.CREAM, 550),
    )
    # (maximum page count, minimum inside margin) in ascending order.
    gutter_table: tuple[tuple[int, float], ...] = (
        (150, inches(0.375)),
        (300, inches(0.5)),
        (500, inches(0.625)),
        (700, inches(0.75)),
        (828, inches(0.875)),
    )

    @property
    def max_pages(self) -> int:
        return self.gutter_table[-1][0]

    def required_gutter(self, page_count: int) -> float | None:
        """Minimum inside margin for a physical page count; None above the table.

        Counts below the 24-page minimum use the first row: the gutter requirement
        is still defined, and the page-count shortfall is reported separately.
        """
        for maximum, gutter in self.gutter_table:
            if page_count <= maximum:
                return gutter
        return None

    def max_pages_for(self, trim_name: str, paper: Paper) -> int | None:
        """KDP's black-ink maximum for this trim on this paper; None when not modeled."""
        for trim, stock, maximum in self.max_pages_by_print:
            if trim == trim_name and stock is paper:
                return maximum
        return None

    def trim_supported(self, width: float, height: float) -> bool:
        (low_w, high_w), (low_h, high_h) = self.custom_trim_width, self.custom_trim_height
        return (
            low_w - TOLERANCE <= width <= high_w + TOLERANCE
            and low_h - TOLERANCE <= height <= high_h + TOLERANCE
        )


KDP = KdpConstraints()


class FolioPlacement(StrEnum):
    CENTER = "center"
    OUTSIDE = "outside"


class Ink(StrEnum):
    BLACK = "black"


@dataclass(frozen=True)
class KdpCoverConstraints:
    """The one home of KDP paperback cover values. Provenance: docs/cover.md.

    Checked 2026-10-07 against KDP help "Create a Paperback Cover" (wrap formula,
    0.125 in bleed, spine multipliers, spine text page count and 0.0625 in spine
    clearance, text 0.125 in inside trim, 300 DPI, 7 pt, embedded fonts, flattened,
    no marks, CMYK recommended, 650 MB limit, 40 MB recommended), "Low-Content
    Book Barcode Details" (2 x 1.2 in barcode box, lower right of the back cover)
    and "Paperback Submission Guidelines" (24-page minimum).
    """

    bleed: float = inches(0.125)
    # Inches of spine per interior page for black ink. KDP lists no groundwood value.
    spine_per_page: tuple[tuple[Paper, float], ...] = (
        (Paper.WHITE, 0.002252),
        (Paper.CREAM, 0.0025),
    )
    # The page says both "more than 79 pages" and "at least 79 pages"; the stricter
    # reading (80 or more) applies. Ambiguity recorded in docs/cover.md.
    spine_text_min_pages: int = 80
    spine_text_clearance: float = inches(0.0625)
    text_safe_inset: float = inches(0.125)
    barcode_width: float = inches(2)
    barcode_height: float = inches(1.2)
    min_image_dpi: float = 300.0
    min_font_size: float = 7.0
    max_file_bytes: int = 650_000_000
    recommended_file_bytes: int = 40_000_000

    def spine_width(self, page_count: int, paper: Paper) -> float:
        """Spine width in points: page count times the paper's per-page thickness."""
        return inches(page_count * dict(self.spine_per_page)[paper])


KDP_COVER = KdpCoverConstraints()


@dataclass(frozen=True)
class TrimSize:
    name: str
    width: float
    height: float


@dataclass(frozen=True)
class Margins:
    """Inside is the binding edge: left on recto pages, right on verso pages."""

    inside: float
    outside: float
    top: float
    bottom: float


@dataclass(frozen=True)
class Typography:
    """Point sizes per role. Grid letters scale within [minimum, maximum]."""

    title: float = 30.0
    subtitle: float = 16.0
    author: float = 14.0
    imprint: float = 11.0
    heading: float = 22.0
    body: float = 11.5
    copyright: float = 9.5
    puzzle_title: float = 22.0
    theme: float = 12.0
    word_list: float = 13.0
    grid_letter_max: float = 20.0
    grid_letter_min: float = 9.0
    solution_letter_max: float = 14.0
    solution_letter_min: float = 7.0
    caption: float = 9.5
    folio: float = 10.0


@dataclass(frozen=True)
class Strokes:
    grid_frame: float = 1.0
    solution_mark: float = 1.0
    rule: float = 0.75
    notes_line: float = 0.75


@dataclass(frozen=True)
class PrintSpecification:
    """Renderer-facing physical choices; independent of the publication plan."""

    profile_id: str
    profile_version: int
    description: str
    trim: TrimSize
    margins: Margins
    ink: Ink
    paper: Paper
    bleed: bool = False
    folio_placement: FolioPlacement = FolioPlacement.CENTER
    typography: Typography = field(default_factory=Typography)
    strokes: Strokes = field(default_factory=Strokes)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["folio_placement"] = self.folio_placement.value
        data["ink"] = self.ink.value
        data["paper"] = self.paper.value
        return data


# Trim sizes the renderer has templates for. More sizes are added here, not in layout.
# 8.5 x 11 stays first: it is the default and the cover templates' reference trim.
# The others are on KDP's standard paperback list (read 2026-11-05) for black ink on
# white or cream paper; none uses bleed (see docs/print-interior.md, Print profiles).
SUPPORTED_TRIMS = (
    TrimSize("8.5x11", inches(8.5), inches(11)),
    TrimSize("6x9", inches(6), inches(9)),
    TrimSize("8x10", inches(8), inches(10)),
    TrimSize("8.5x8.5", inches(8.5), inches(8.5)),
)

# Fixed, explicit margins. The 0.75 in inside margin meets KDP gutters up to 700
# pages; it is validated against the final page count, never enlarged.
_LETTER_MARGINS = Margins(
    inside=inches(0.75), outside=inches(0.5), top=inches(0.625), bottom=inches(0.625)
)
# Version 2 states ink and paper explicitly (version 1 left paper unmodeled). The
# page layout is unchanged; paper matters to the cover's spine width.
PAPERBACK_LETTER = PrintSpecification(
    profile_id="paperback-8.5x11",
    profile_version=2,
    description="8.5 x 11 in paperback interior, black ink on white paper, no bleed",
    trim=SUPPORTED_TRIMS[0],
    margins=_LETTER_MARGINS,
    ink=Ink.BLACK,
    paper=Paper.WHITE,
)
PAPERBACK_LETTER_CREAM = PrintSpecification(
    profile_id="paperback-8.5x11-cream",
    profile_version=1,
    description="8.5 x 11 in paperback interior, black ink on cream paper, no bleed",
    trim=SUPPORTED_TRIMS[0],
    margins=_LETTER_MARGINS,
    ink=Ink.BLACK,
    paper=Paper.CREAM,
)


def _profile(trim: TrimSize, paper: Paper, margins: Margins) -> PrintSpecification:
    suffix = "" if paper is Paper.WHITE else f"-{paper.value}"
    inches_name = trim.name.replace("x", " x ")
    return PrintSpecification(
        profile_id=f"paperback-{trim.name}{suffix}",
        profile_version=1,
        description=f"{inches_name} in paperback interior, black ink on {paper.value} paper, "
        "no bleed",
        trim=trim,
        margins=margins,
        ink=Ink.BLACK,
        paper=paper,
    )


# The same 0.75 in gutter (KDP's minimum up to 700 pages) and 0.5 in outside margin as
# 8.5 x 11; 6 x 9 has 0.5 in top and bottom so its pages keep usable height.
_SMALL_MARGINS = Margins(
    inside=inches(0.75), outside=inches(0.5), top=inches(0.5), bottom=inches(0.5)
)
_ADDED = tuple(
    _profile(trim, paper, _SMALL_MARGINS if trim.name == "6x9" else _LETTER_MARGINS)
    for trim in SUPPORTED_TRIMS[1:]
    for paper in (Paper.WHITE, Paper.CREAM)
)
PROFILES = {spec.profile_id: spec for spec in (PAPERBACK_LETTER, PAPERBACK_LETTER_CREAM, *_ADDED)}
DEFAULT_PROFILE = PAPERBACK_LETTER.profile_id
# Content boxes narrower or shorter than this cannot hold any supported template.
MIN_CONTENT_EXTENT = inches(3)


def print_profile(profile_id: str) -> PrintSpecification | LayoutIssue:
    spec = PROFILES.get(profile_id)
    if spec is None:
        return LayoutIssue(
            "unsupported_profile",
            f"Unknown print profile {profile_id!r}. Supported: {', '.join(sorted(PROFILES))}.",
            region="print.profile",
        )
    return spec


def validate_print_spec(spec: PrintSpecification) -> tuple[LayoutIssue, ...]:
    """Page-count-independent checks. Gutter versus page count is checked at layout."""
    issues: list[LayoutIssue] = []
    trim = spec.trim
    if not any(
        abs(trim.width - s.width) <= TOLERANCE and abs(trim.height - s.height) <= TOLERANCE
        for s in SUPPORTED_TRIMS
    ):
        issues.append(
            LayoutIssue(
                "unsupported_trim_size",
                "Trim size has no supported page templates.",
                region="print.trim",
                actual=f"{to_inches(trim.width):g}x{to_inches(trim.height):g} in",
                required=", ".join(s.name for s in SUPPORTED_TRIMS),
            )
        )
    if spec.bleed:
        issues.append(
            LayoutIssue(
                "unsupported_bleed_configuration",
                "Bleed is not supported: no puzzle-book element prints to the trim edge.",
                region="print.bleed",
            )
        )
    minimum = KDP.min_outside_margin_with_bleed if spec.bleed else KDP.min_outside_margin
    margins = spec.margins
    for name in ("outside", "top", "bottom"):
        value = getattr(margins, name)
        if value < minimum - TOLERANCE:
            issues.append(
                LayoutIssue(
                    "margin_too_small",
                    f"The {name} margin is below the KDP minimum.",
                    region=f"print.margins.{name}",
                    actual=_inch_text(value),
                    required=_inch_text(minimum),
                )
            )
    first_gutter = KDP.gutter_table[0][1]
    if margins.inside < first_gutter - TOLERANCE:
        issues.append(
            LayoutIssue(
                "gutter_too_small",
                "The inside margin is below the smallest KDP gutter.",
                region="print.margins.inside",
                actual=_inch_text(margins.inside),
                required=_inch_text(first_gutter),
            )
        )
    width = trim.width - margins.inside - margins.outside
    height = trim.height - margins.top - margins.bottom
    if width < MIN_CONTENT_EXTENT or height < MIN_CONTENT_EXTENT:
        issues.append(
            LayoutIssue(
                "invalid_page_geometry",
                "Margins leave too little live area for page templates.",
                region="print.margins",
                actual=f"{to_inches(width):g}x{to_inches(height):g} in",
                required=f"at least {_inch_text(MIN_CONTENT_EXTENT)} each way",
            )
        )
    for name, value in asdict(spec.typography).items():
        if value < KDP.min_font_size - TOLERANCE:
            issues.append(
                LayoutIssue(
                    "font_too_small",
                    f"Typography role {name} is below the minimum text size.",
                    region=f"print.typography.{name}",
                    actual=f"{value:g} pt",
                    required=f"{KDP.min_font_size:g} pt",
                )
            )
    typography = spec.typography
    for low, high in (
        ("grid_letter_min", "grid_letter_max"),
        ("solution_letter_min", "solution_letter_max"),
    ):
        if getattr(typography, low) > getattr(typography, high):
            issues.append(
                LayoutIssue(
                    "invalid_typography",
                    f"{low} exceeds {high}.",
                    region=f"print.typography.{low}",
                )
            )
    for name, value in asdict(spec.strokes).items():
        if value < KDP.min_line_weight - TOLERANCE:
            issues.append(
                LayoutIssue(
                    "line_weight_too_small",
                    f"Stroke {name} is below the minimum line weight.",
                    region=f"print.strokes.{name}",
                    actual=f"{value:g} pt",
                    required=f"{KDP.min_line_weight:g} pt",
                )
            )
    return tuple(issues)


def _inch_text(points: float) -> str:
    return f"{to_inches(points):.4g} in"
