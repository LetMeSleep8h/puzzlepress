"""Line-art preparation: the original's pixels, adjusted for black-ink printing.

Nothing here reads or writes files. The original bytes are decoded (EXIF
orientation applied, transparency composited onto white) and processed in memory,
in a fixed order:

1. gray: luma, or the darkest channel when `grayscale` is false (keeps light
   colored lines dark: yellow is nearly white in luma, black in its darkest
   channel); the result is always grayscale, because the interior prints black ink;
2. invert, for white-on-black artwork;
3. brightness and contrast (one lookup table around mid-gray);
4. background cleanup: paper (the 95th-percentile level) is stretched to white,
   then levels within `cleanup x 64` of white become white;
5. despeckle: isolated ink marks (no other ink within SPECK_RADIUS pixels) up to
   SPECK_AREAS[despeckle] pixels are removed; marks near line work are never touched;
6. threshold (optional): pixels at or below `threshold x 255` become black, the
   rest white; without it, gray anti-aliased edges are kept;
7. line weight: a 3 or 5 pixel minimum filter thickens, a maximum filter thins.

Defaults (luma, no change elsewhere) return the original's gray levels exactly, so
an unadjusted drawing is never altered beyond flattening and gray conversion.
Every step is a Pillow lookup table, rank filter or the bounded region scan in
`components`, so identical bytes, settings, PREPARATION_VERSION and Pillow version
give identical pixels. The cache key names all four.

Measures compare the processed image with the reference: the same original with
only steps 1 and 2 applied (what the author drew). Thresholds are PuzzlePress
conventions calibrated on synthetic fixtures (tests/coloring_helpers.py); see
`calibration` in docs/coloring.md. They flag measurable damage, not print quality.
"""

import hashlib
import io
import json
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter
from PIL import __version__ as PILLOW_VERSION

from ..coloring_config import Adjustments
from .components import TooMuchInk, isolated_specks, label, paint_white, remove_isolated
from .inspection import INK_LEVEL, _edges, _reduced, flattened, open_artwork
from .issues import ArtworkError, ArtworkFinding, Severity

PREPARATION_VERSION = 1
MAX_PREPARE_PIXELS = 40_000_000  # 5100 x 6600 is 8.5 x 11 in at 600 DPI (33.7 MP).
# Ink pixels one region scan may visit (about 4 s here); beyond it, stroke counts are
# reported as not measured and despeckling refuses rather than guessing.
MAX_ANALYZED_INK = 3_000_000
SPECK_AREAS = (0, 4, 9, 16, 36, 64)  # Largest isolated mark removed at despeckle 0..5.
SPECK_LIMIT = SPECK_AREAS[-1]  # Isolated marks this small are dust when measuring.
SPECK_RADIUS = 6  # A mark with other ink this close may be part of a faint line.
PREVIEW_SIDE = 1200

# Calibrated conventions (see docs/coloring.md, "Calibration").
THIN_WARNING = 0.90  # Share of one- and two-pixel line work kept.
THIN_BLOCKING = 0.60
DETAIL_WARNING = 0.60  # Share of all original line work kept.
BLANK_INK = 0.001
HEAVY_INK_WARNING = 0.35
HEAVY_INK_BLOCKING = 0.60
STROKES_BROKEN = 1.25  # Stroke count growth (with an allowance of 3) that means breaks.
PAPER_WARNING = 240  # Median non-ink level below this prints as a tint.
# Clean fixtures measured 0-1.3 isolated marks per megapixel; a scan that looked
# visibly dusty in review measured 14.8 (despeckle 3 left its 13-21 px dots).
SPECKS_PER_MP_WARNING = 5.0
CHANGE_REVIEW = 40.0  # Mean absolute change (levels) worth a visual review.
# Faint lines: how dark the darkest tenth of the line work (gray at or below
# LINE_LEVEL) gets. Black strokes reach 0-48 (thin anti-aliased ones 43); a soft pencil
# page measured 96 and 77 after contrast 1.6, both visibly pale in print review, and
# one-pixel black lines reduced to half size 129-132.
LINE_LEVEL = 200
LINE_CORE_SHARE = 0.10
FAINT_CORE = 64  # 75% ink.


def cache_key(sha256: str, adjustments: Adjustments) -> str:
    """Content address of a preparation: source, settings and algorithm versions."""
    payload = {
        "preparation_version": PREPARATION_VERSION,
        "pillow": PILLOW_VERSION,
        "source_sha256": sha256,
        "adjustments": adjustments.to_dict(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "pp1-prepared-sha256-" + hashlib.sha256(encoded).hexdigest()


def _gray(rgb: Image.Image, luma: bool) -> Image.Image:
    if luma:
        return rgb.convert("L")
    red, green, blue = rgb.split()
    return ImageChops.darker(ImageChops.darker(red, green), blue)


def _tone(gray: Image.Image, brightness: float, contrast: float) -> Image.Image:
    if brightness == 0 and contrast == 1:
        return gray
    offset = brightness * 255
    table = [max(0, min(255, round((v - 128) * contrast + 128 + offset))) for v in range(256)]
    return gray.point(table)


def _percentile(histogram: list[int], share: float) -> int:
    target = sum(histogram) * share
    running = 0
    for level, count in enumerate(histogram):
        running += count
        if running >= target:
            return level
    return 255


def _cleanup(gray: Image.Image, amount: float) -> Image.Image:
    if amount == 0:
        return gray
    paper = max(1, _percentile(gray.histogram(), 0.95))
    lift = 255 - amount * 64
    table = []
    for v in range(256):
        stretched = min(255, round(v * 255 / paper))
        table.append(255 if stretched >= lift else stretched)
    return gray.point(table)


def _threshold(gray: Image.Image, threshold: float | None) -> Image.Image:
    if threshold is None:
        return gray
    level = round(threshold * 255)
    return gray.point(lambda v: 0 if v <= level else 255)


def _line_weight(gray: Image.Image, weight: int) -> Image.Image:
    if weight == 0:
        return gray
    size = 3 if abs(weight) == 1 else 5
    return gray.filter(ImageFilter.MinFilter(size) if weight > 0 else ImageFilter.MaxFilter(size))


def _mask(gray: Image.Image) -> Image.Image:
    return gray.point(lambda v: 255 if v <= INK_LEVEL else 0)


def _count(mask: Image.Image) -> int:
    return mask.histogram()[255]


@dataclass(frozen=True)
class PreparationMeasures:
    pixels: tuple[int, int]
    ink_before: float
    ink_after: float
    thin_line_pixels: int  # One- and two-pixel line work in the reference.
    thin_line_retention: float | None  # None when there is too little thin work.
    detail_retention: float | None
    strokes_before: int | None  # None when the region scan was over its bound.
    strokes_after: int | None
    specks_removed: int
    specks_per_megapixel_after: float | None
    paper_level_after: int
    mean_change: float  # Mean absolute gray change, 0..255.
    not_measured: tuple[str, ...] = ()  # Measures skipped because a scan bound was hit.
    new_edges: tuple[str, ...] = ()  # Image edges ink reaches only after preparation.
    # Gray of the darkest tenth of the prepared line work; None with no line work.
    line_core_level: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "not_measured": list(self.not_measured),
            "new_edges": list(self.new_edges),
            "pixels": list(self.pixels),
            "ink_before": self.ink_before,
            "ink_after": self.ink_after,
            "thin_line_pixels": self.thin_line_pixels,
            "thin_line_retention": self.thin_line_retention,
            "detail_retention": self.detail_retention,
            "strokes_before": self.strokes_before,
            "strokes_after": self.strokes_after,
            "specks_removed": self.specks_removed,
            "specks_per_megapixel_after": self.specks_per_megapixel_after,
            "paper_level_after": self.paper_level_after,
            "mean_change": self.mean_change,
            "line_core_level": self.line_core_level,
        }


@dataclass(frozen=True, eq=False)
class Prepared:
    key: str
    adjustments: Adjustments
    reference: Image.Image  # Steps 1-2 only: what the author drew, in gray.
    image: Image.Image  # The prepared grayscale pixels.
    measures: PreparationMeasures
    findings: tuple[ArtworkFinding, ...]

    @property
    def blocking(self) -> bool:
        return any(finding.severity is Severity.BLOCKING for finding in self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "preparation_version": PREPARATION_VERSION,
            "adjustments": self.adjustments.to_dict(),
            "measures": self.measures.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "blocking": self.blocking,
        }


def _pipeline(
    data: bytes, adjustments: Adjustments, name: str
) -> tuple[Image.Image, Image.Image, int]:
    """(unadjusted reference, prepared pixels, despeckled pixel count). Raises ArtworkError."""
    image = open_artwork(data, name)
    width, height = image.size
    if width * height > MAX_PREPARE_PIXELS:
        raise ArtworkError(
            "too_large_to_prepare",
            f"{width} x {height} px is more than {MAX_PREPARE_PIXELS:,} pixels to prepare. "
            "Export the drawing at 600 DPI or less.",
        )
    rgb, _, _ = flattened(image)
    reference = _gray(rgb, adjustments.grayscale)
    if adjustments.invert:
        reference = ImageChops.invert(reference)
    out = _tone(reference, adjustments.brightness, adjustments.contrast)
    out = _cleanup(out, adjustments.background_cleanup)
    removed = 0
    if adjustments.despeckle:
        try:
            out, removed = remove_isolated(
                out, INK_LEVEL, SPECK_AREAS[adjustments.despeckle], SPECK_RADIUS, MAX_ANALYZED_INK
            )
        except TooMuchInk as error:
            raise ArtworkError(
                "too_much_ink_to_despeckle",
                f"Despeckling needs a mostly white page: {error}. Lower the contrast or "
                "turn despeckle off.",
            ) from error
    out = _threshold(out, adjustments.threshold)
    out = _line_weight(out, adjustments.line_weight)
    return reference, out, removed


def prepare_artwork(data: bytes, adjustments: Adjustments, name: str = "") -> Prepared:
    """Prepare one original. Raises ArtworkError; never falls back to other settings."""
    reference, out, removed = _pipeline(data, adjustments, name)
    measures = _measure(reference, out, removed)
    key = cache_key(hashlib.sha256(data).hexdigest(), adjustments)
    return Prepared(key, adjustments, reference, out, measures, _findings(measures, adjustments))


def prepared_pixels(data: bytes, adjustments: Adjustments, name: str = "") -> Image.Image:
    """Exactly the pixels `prepare_artwork` prepares (mode L), without measuring them.

    Builds print these; quality measures are preflight's, computed by
    `prepare_artwork` over the same pipeline.
    """
    return _pipeline(data, adjustments, name)[1]


def pixel_digest(image: Image.Image) -> str:
    """`sha256-` over mode, size and raw bytes: what a page prints, independent of files."""
    header = f"{image.mode}:{image.width}x{image.height}:".encode("ascii")
    return "sha256-" + hashlib.sha256(header + image.tobytes()).hexdigest()


def _line_work(gray: Image.Image) -> tuple[int, int] | None:
    """(regions of line work, isolated specks) or None when over the scan bound.

    Line work is every ink region except isolated specks (SPECK_LIMIT pixels or less,
    nothing else within SPECK_RADIUS): those are dust, counted apart.
    """
    try:
        labeling = label(gray, INK_LEVEL, MAX_ANALYZED_INK, keep_up_to=SPECK_LIMIT)
    except TooMuchInk:
        return None
    specks = sum(1 for region in labeling.small if labeling.isolated(region, SPECK_RADIUS))
    return len(labeling.areas) - specks, specks


def _measure(reference: Image.Image, out: Image.Image, removed: int) -> PreparationMeasures:
    width, height = reference.size
    total = width * height
    not_measured: list[str] = []
    # The reference's line work: isolated specks removed, so dust never counts as fine
    # lines and despeckling (which removes only isolated specks) cannot lose any.
    try:
        dust = isolated_specks(reference, INK_LEVEL, SPECK_LIMIT, SPECK_RADIUS, MAX_ANALYZED_INK)
        lines = paint_white(reference, dust) if dust else reference
    except TooMuchInk:
        lines = reference
        not_measured.append("dust")
    before = _mask(lines)
    after = _mask(out)
    ink_before = _count(_mask(reference))
    ink_after = _count(after)
    line_ink = _count(before)
    # Fine lines: line work an opening (3 x 3 erosion, then dilation) cannot restore,
    # so strokes at most two pixels wide; edges of wider strokes come back.
    opened = lines.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    thin = ImageChops.subtract(before, _mask(opened))
    thin_pixels = _count(thin)
    thin_kept = _count(ImageChops.darker(thin, after))
    detail_kept = _count(ImageChops.darker(before, after))
    # Strokes are counted on the ink both images share, so growing marks (thickening)
    # can never look like breaks; cutting lines (thinning, a low threshold) can.
    counted_before = _line_work(reference)
    counted_after = (
        counted_before if out is reference else _line_work(ImageChops.lighter(reference, out))
    )
    produced = counted_before if out is reference else _line_work(out)
    strokes_before = strokes_after = None
    if counted_before is None or counted_after is None:
        not_measured.append("strokes")
    else:
        strokes_before, strokes_after = counted_before[0], counted_after[0]
    specks: float | None = None
    if produced is None:
        not_measured.append("specks")
    else:
        specks = round(produced[1] / (total / 1e6), 2)
    paper_level = _paper_median(out)
    edges_before = set(_edges(_reduced(reference)))
    new_edges = tuple(e for e in _edges(_reduced(out)) if e not in edges_before)
    change = ImageChops.difference(reference, out)
    mean_change = sum(level * count for level, count in enumerate(change.histogram())) / total
    core = _line_core(out.histogram(), total)
    return PreparationMeasures(
        pixels=(width, height),
        ink_before=round(ink_before / total, 4),
        ink_after=round(ink_after / total, 4),
        thin_line_pixels=thin_pixels,
        thin_line_retention=round(thin_kept / thin_pixels, 4) if thin_pixels >= 200 else None,
        detail_retention=round(detail_kept / line_ink, 4) if line_ink >= 200 else None,
        strokes_before=strokes_before,
        strokes_after=strokes_after,
        specks_removed=removed,
        specks_per_megapixel_after=specks,
        paper_level_after=paper_level,
        mean_change=round(mean_change, 2),
        not_measured=tuple(not_measured),
        new_edges=new_edges,
        line_core_level=core,
    )


def _line_core(levels: list[int], total: int) -> int | None:
    """The gray level the darkest LINE_CORE_SHARE of the line work reaches."""
    line_pixels = sum(levels[: LINE_LEVEL + 1])
    if line_pixels < BLANK_INK * total:
        return None
    need, seen = line_pixels * LINE_CORE_SHARE, 0
    for level in range(LINE_LEVEL + 1):
        seen += levels[level]
        if seen >= need:
            return level
    return LINE_LEVEL


def _paper_median(gray: Image.Image) -> int:
    """Median level of the non-ink pixels (255 when there are none)."""
    histogram = gray.histogram()[INK_LEVEL + 1 :]
    total = sum(histogram)
    if not total:
        return 255
    half, running = total // 2, 0
    for offset, count in enumerate(histogram):
        running += count
        if running > half:
            return INK_LEVEL + 1 + offset
    return 255


def _findings(m: PreparationMeasures, adjustments: Adjustments) -> tuple[ArtworkFinding, ...]:
    found: list[ArtworkFinding] = []

    def add(code: str, severity: Severity, message: str, actual: str, required: str) -> None:
        found.append(ArtworkFinding(code, severity, message, actual, required))

    if m.ink_after < BLANK_INK:
        if m.ink_before >= BLANK_INK:
            why = "The settings remove all line work: the prepared page is blank."
        elif adjustments.grayscale:
            why = (
                "The prepared page is blank. Light colored lines vanish in gray; turn off "
                "Grayscale (luma) to use each pixel's darkest channel."
            )
        else:
            why = "The prepared page is blank: the artwork has no dark line work."
        add(
            "prepared_blank",
            Severity.BLOCKING,
            why,
            f"{m.ink_after:.2%} ink",
            f"at least {BLANK_INK:.1%}",
        )
    if m.thin_line_retention is not None:
        if m.thin_line_retention < THIN_BLOCKING:
            add(
                "thin_lines_destroyed",
                Severity.BLOCKING,
                "Most fine lines (one or two pixels wide) are gone after preparation.",
                f"{m.thin_line_retention:.0%} kept",
                f"at least {THIN_BLOCKING:.0%}",
            )
        elif m.thin_line_retention < THIN_WARNING:
            add(
                "thin_lines_lost",
                Severity.WARNING,
                "Some fine lines (one or two pixels wide) are lost after preparation.",
                f"{m.thin_line_retention:.0%} kept",
                f"at least {THIN_WARNING:.0%}",
            )
    if m.detail_retention is not None and m.detail_retention < DETAIL_WARNING:
        add(
            "detail_lost",
            Severity.WARNING,
            "Part of the original line work is no longer printed as ink.",
            f"{m.detail_retention:.0%} kept",
            f"at least {DETAIL_WARNING:.0%}",
        )
    if m.ink_after > HEAVY_INK_BLOCKING:
        add(
            "excessive_ink",
            Severity.BLOCKING,
            "Most of the page would print solid black; there is little left to color."
            + (
                ""
                if adjustments.invert
                else " If the artwork is white lines on black, turn on Invert."
            ),
            f"{m.ink_after:.0%} ink",
            f"at most {HEAVY_INK_BLOCKING:.0%}",
        )
    elif m.ink_after > HEAVY_INK_WARNING:
        add(
            "heavy_ink",
            Severity.WARNING,
            "A large share of the page prints black; check that areas stay open to color.",
            f"{m.ink_after:.0%} ink",
            f"at most {HEAVY_INK_WARNING:.0%}",
        )
    if (
        m.strokes_before is not None
        and m.strokes_after is not None
        and m.strokes_after > m.strokes_before * STROKES_BROKEN + 3
    ):
        add(
            "strokes_broken",
            Severity.WARNING,
            "Lines appear broken into more separate pieces than the original has.",
            f"{m.strokes_after} pieces",
            f"about {m.strokes_before} (original)",
        )
    if m.paper_level_after < PAPER_WARNING:
        add(
            "background_tint",
            Severity.WARNING,
            "The paper is not white after preparation and would print as a gray tint. "
            "Raise background cleanup or set a threshold.",
            f"median {m.paper_level_after}",
            f"at least {PAPER_WARNING}",
        )
    if m.line_core_level is not None and m.line_core_level > FAINT_CORE:
        add(
            "faint_lines",
            Severity.WARNING,
            "The lines print as light gray, not black: even the darkest of them are pale. "
            "Raise the contrast, lower the brightness or set a threshold.",
            f"darkest lines gray {m.line_core_level}",
            f"at most {FAINT_CORE}",
        )
    if m.specks_per_megapixel_after is not None and (
        m.specks_per_megapixel_after > SPECKS_PER_MP_WARNING
    ):
        add(
            "specks_remaining",
            Severity.WARNING,
            "Many small specks remain; despeckle can remove isolated marks.",
            f"{m.specks_per_megapixel_after:g} per megapixel",
            f"at most {SPECKS_PER_MP_WARNING:g}",
        )
    if m.new_edges:
        add(
            "prepared_touches_edge",
            Severity.WARNING,
            f"After preparation, ink reaches the {', '.join(m.new_edges)} edge of the image, "
            "which the original did not; the drawing may be cut off when placed.",
            ", ".join(m.new_edges),
            "no new edge contact",
        )
    if m.mean_change > CHANGE_REVIEW:
        add(
            "large_change",
            Severity.WARNING,
            "The prepared page differs a lot from the original. Compare them before "
            "saving; this is a prompt to look, not a defect.",
            f"mean change {m.mean_change:g}",
            f"review above {CHANGE_REVIEW:g}",
        )
    return tuple(found)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _fit(image: Image.Image, side: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((side, side), Image.Resampling.BOX)
    return copy


KEPT_COLOR = (64, 64, 64)
REMOVED_COLOR = (214, 40, 40)
ADDED_COLOR = (36, 90, 214)


def difference_image(reference: Image.Image, prepared: Image.Image) -> Image.Image:
    """Ink kept in dark gray, ink removed in red, ink added in blue, paper white."""
    before = _mask(reference)
    after = _mask(prepared)
    image = Image.new("RGB", reference.size, (255, 255, 255))
    image.paste(KEPT_COLOR, mask=ImageChops.darker(before, after))
    image.paste(REMOVED_COLOR, mask=ImageChops.subtract(before, after))
    image.paste(ADDED_COLOR, mask=ImageChops.subtract(after, before))
    return image


def preview_png(prepared: Prepared, kind: str, side: int = PREVIEW_SIDE) -> bytes:
    """original | prepared | difference, reduced to at most `side` pixels, as PNG."""
    if kind == "original":
        return _png(_fit(prepared.reference, side))
    if kind == "prepared":
        return _png(_fit(prepared.image, side))
    if kind == "difference":
        return _png(_fit(difference_image(prepared.reference, prepared.image), side))
    raise ValueError(f"Unknown preview kind: {kind}")


def prepared_png(prepared: Prepared) -> bytes:
    """The full-resolution prepared pixels as an 8-bit grayscale PNG."""
    return _png(prepared.image)


__all__ = [
    "PREPARATION_VERSION",
    "Prepared",
    "PreparationMeasures",
    "cache_key",
    "difference_image",
    "prepare_artwork",
    "prepared_png",
    "preview_png",
]
