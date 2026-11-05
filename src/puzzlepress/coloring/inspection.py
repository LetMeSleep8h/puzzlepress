"""Read-only facts and print findings for one line-art file (PNG or JPEG).

Nothing here converts or rewrites the original. Pixels are decoded into memory,
flattened onto white and reduced (box filter, at most 1,024 px on the long side)
for measuring only; every measure is rounded so reports are deterministic for a
given Pillow version.

Effective DPI is measured for the largest area the default 8.5 x 11 in profile can
print in (its live area, 7.25 x 9.75 in), with the drawing fitted inside it whole.
That is the lowest resolution the artwork can have in a book: a smaller art box
in a later page layout only raises it.

SVG is refused: a vector file can carry scripts and remote references, and this
version has no safe SVG renderer. Thresholds marked "convention" are PuzzlePress
choices to review, not KDP values.
"""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from ..cover.assets import MAX_ASSET_BYTES, MAX_PIXELS
from ..interior.geometry import page_frame
from ..interior.spec import KDP, PAPERBACK_LETTER, to_inches
from .issues import ArtworkError, ArtworkFinding, Severity

FORMATS = {"PNG": "png", "JPEG": "jpg"}
MODES = {"1", "L", "LA", "P", "PA", "RGB", "RGBA", "CMYK"}
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_OTHER_FORMATS = (
    (b"GIF8", "GIF"),
    (b"RIFF", "WebP"),
    (b"II*\x00", "TIFF"),
    (b"MM\x00*", "TIFF"),
    (b"BM", "BMP"),
    (b"%PDF", "PDF"),
)
ORIENTATION_TAG = 0x0112
_TRANSPOSED = {5, 6, 7, 8}

_FRAME = page_frame(PAPERBACK_LETTER, 1).content
ART_BOX_INCHES = (round(to_inches(_FRAME.width), 4), round(to_inches(_FRAME.height), 4))
MIN_DPI = KDP.min_image_dpi  # 300, KDP's print minimum.
POOR_DPI = 150.0  # Convention: below this a drawing is unsuitable, not merely soft.
ANALYSIS_SIDE = 1024
INK_LEVEL = 128  # Gray at or below this counts as line work.
EMPTY_INK = 0.001  # Convention: less ink than this reads as a blank image.
EDGE_INK = 0.02  # Convention: share of an edge strip in ink that suggests cropped art.
COLOR_DELTA = 24  # Channel spread that counts a pixel as colored.
COLOR_SHARE = 0.01  # Convention: share of colored pixels that makes the art "in color".
GRAY_BACKGROUND = 230  # Convention: a median below this means the paper is not white.
SMALL_ON_PAGE = 0.6  # Convention: a fitted drawing filling less of the art box than this.


def _sniff_svg(data: bytes, name: str) -> bool:
    if name.lower().endswith((".svg", ".svgz")):
        return True
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<svg", b"<!doctype svg")) or (
        head.startswith(b"<?xml") and b"<svg" in head
    )


def _refuse_format(data: bytes, name: str) -> ArtworkError:
    if _sniff_svg(data, name):
        return ArtworkError(
            "svg_not_supported",
            "SVG artwork is not supported in this version: vector files can carry scripts "
            "and remote references, and PuzzlePress has no safe SVG renderer yet. Export the "
            f"drawing as a PNG of at least {_minimum_pixels()} pixels instead.",
        )
    for signature, label in _OTHER_FORMATS:
        if data.startswith(signature):
            return ArtworkError(
                "unsupported_format",
                f"This is a {label} file. Import line art as PNG (preferred) or JPEG.",
            )
    return ArtworkError(
        "unsupported_format", "This is not a PNG or JPEG image. Import line art as PNG or JPEG."
    )


def _minimum_pixels() -> str:
    width, height = ART_BOX_INCHES
    return f"{round(width * MIN_DPI)} x {round(height * MIN_DPI)}"


def open_artwork(data: bytes, name: str = "") -> Image.Image:
    """Open and fully decode a PNG or JPEG, or raise ArtworkError. Never writes."""
    if not data:
        raise ArtworkError("empty_file", "The file is empty.")
    if len(data) > MAX_ASSET_BYTES:
        raise ArtworkError(
            "file_too_large",
            f"The file is {len(data):,} bytes; artwork may be at most {MAX_ASSET_BYTES:,} bytes.",
        )
    if not data.startswith((_PNG, _JPEG)):
        raise _refuse_format(data, name)
    try:
        image = Image.open(io.BytesIO(data), formats=tuple(FORMATS))
        width, height = image.size
        if width < 1 or height < 1 or width * height > MAX_PIXELS:
            raise ArtworkError(
                "too_many_pixels",
                f"{width} x {height} px is more than {MAX_PIXELS:,} pixels to process safely.",
            )
        image.load()
    except ArtworkError:
        raise
    except Image.DecompressionBombError as error:
        raise ArtworkError(
            "too_many_pixels", f"The image has too many pixels to process safely: {error}"
        ) from error
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError) as error:
        raise ArtworkError(
            "corrupt_image",
            "The image is damaged or incomplete and cannot be decoded. Export it again.",
        ) from error
    if image.format not in FORMATS:
        raise _refuse_format(data, name)
    if image.mode not in MODES:
        raise ArtworkError(
            "unsupported_color_mode",
            f"Color mode {image.mode} is not supported. Export 8-bit grayscale or RGB.",
        )
    return image


def _orientation(image: Image.Image) -> int:
    try:
        value = image.getexif().get(ORIENTATION_TAG, 1)
    except (OSError, ValueError, SyntaxError):
        return 1
    return value if isinstance(value, int) and 1 <= value <= 8 else 1


@dataclass(frozen=True)
class ArtworkInfo:
    sha256: str
    format: str  # png or jpeg
    bytes: int
    mode: str  # Pillow color mode as stored, e.g. L, RGB, RGBA, P, 1, CMYK.
    stored_pixels: tuple[int, int]
    pixels: tuple[int, int]  # Upright, after EXIF orientation.
    orientation: int
    aspect_ratio: float  # Upright width / height.
    alpha_channel: bool
    transparent_pixels: bool  # Some pixel is not fully opaque.
    dpi_metadata: tuple[float, float] | None  # What the file claims; never used for print.
    effective_dpi: float  # Fitted whole inside the art box (see module docstring).
    printed_inches: tuple[float, float]
    art_box_coverage: float  # Share of the art box the fitted drawing fills.
    ink_coverage: float  # Share of pixels at or below INK_LEVEL.
    background_level: int  # Median gray, 0 black .. 255 white.
    in_color: bool
    dhash: str  # 64-bit difference hash, 16 hex digits.

    def to_dict(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "format": self.format,
            "bytes": self.bytes,
            "mode": self.mode,
            "stored_pixels": list(self.stored_pixels),
            "pixels": list(self.pixels),
            "orientation": self.orientation,
            "aspect_ratio": self.aspect_ratio,
            "alpha_channel": self.alpha_channel,
            "transparent_pixels": self.transparent_pixels,
            "dpi_metadata": list(self.dpi_metadata) if self.dpi_metadata else None,
            "effective_dpi": self.effective_dpi,
            "art_box_inches": list(ART_BOX_INCHES),
            "printed_inches": list(self.printed_inches),
            "art_box_coverage": self.art_box_coverage,
            "ink_coverage": self.ink_coverage,
            "background_level": self.background_level,
            "in_color": self.in_color,
            "dhash": self.dhash,
        }


@dataclass(frozen=True, eq=False)
class Inspection:
    info: ArtworkInfo
    findings: tuple[ArtworkFinding, ...]
    ink_map: bytes  # 16 x 16 reduced gray levels, for the similarity check only.

    @property
    def blocking(self) -> bool:
        return any(finding.severity is Severity.BLOCKING for finding in self.findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "info": self.info.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "blocking": self.blocking,
        }


def flattened(image: Image.Image) -> tuple[Image.Image, bool, bool]:
    """Upright RGB pixels on white, plus (alpha channel present, any transparent pixel)."""
    upright = ImageOps.exif_transpose(image)
    alpha = upright.mode in ("LA", "PA", "RGBA") or (
        upright.mode == "P" and "transparency" in upright.info
    )
    transparent = False
    if alpha:
        rgba = upright.convert("RGBA")
        transparent = rgba.getchannel("A").histogram()[255] < rgba.width * rgba.height
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        rgb = Image.alpha_composite(white, rgba).convert("RGB")
    else:
        rgb = upright.convert("RGB")
    return rgb, alpha, transparent


def _reduced(image: Image.Image) -> Image.Image:
    width, height = image.size
    scale = max(width, height) / ANALYSIS_SIDE
    if scale <= 1:
        return image.copy()
    size = (max(1, round(width / scale)), max(1, round(height / scale)))
    return image.resize(size, Image.Resampling.BOX)


def _ink_share(gray: Image.Image) -> float:
    """Share of pixels at or below INK_LEVEL in an L image."""
    histogram = gray.histogram()
    return sum(histogram[: INK_LEVEL + 1]) / max(1, sum(histogram))


def _median(gray: Image.Image) -> int:
    histogram = gray.histogram()
    half, running = sum(histogram) // 2, 0
    for level, count in enumerate(histogram):
        running += count
        if running > half:
            return level
    return 255


def _color_share(rgb: Image.Image) -> float:
    """Share of pixels whose channels spread by more than COLOR_DELTA."""
    red, green, blue = rgb.split()
    high = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    low = ImageChops.darker(ImageChops.darker(red, green), blue)
    histogram = ImageChops.subtract(high, low).histogram()
    return sum(histogram[COLOR_DELTA + 1 :]) / max(1, sum(histogram))


def _edges(gray: Image.Image) -> list[str]:
    width, height = gray.size
    strip_w = max(1, round(width * 0.01))
    strip_h = max(1, round(height * 0.01))
    boxes = {
        "top": (0, 0, width, strip_h),
        "bottom": (0, height - strip_h, width, height),
        "left": (0, 0, strip_w, height),
        "right": (width - strip_w, 0, width, height),
    }
    touched = []
    for side, box in boxes.items():
        if _ink_share(gray.crop(box)) > EDGE_INK:
            touched.append(side)
    return touched


def dhash(gray: Image.Image) -> str:
    small = gray.resize((9, 8), Image.Resampling.BOX)
    values = small.tobytes()
    bits = 0
    for row in range(8):
        for column in range(8):
            left, right = values[row * 9 + column], values[row * 9 + column + 1]
            bits = (bits << 1) | (1 if left < right else 0)
    return f"{bits:016x}"


def inspect_artwork(data: bytes, name: str = "") -> Inspection:
    """Facts and findings for one file. Raises ArtworkError when it cannot be read."""
    image = open_artwork(data, name)
    orientation = _orientation(image)
    stored = image.size
    upright = (stored[1], stored[0]) if orientation in _TRANSPOSED else stored
    rgb, alpha, transparent = flattened(image)
    small = _reduced(rgb)
    gray = small.convert("L")
    ink = round(_ink_share(gray), 4)
    background = _median(gray)
    in_color = _color_share(small) > COLOR_SHARE
    box_w, box_h = ART_BOX_INCHES
    dpi = max(upright[0] / box_w, upright[1] / box_h)
    printed = (round(upright[0] / dpi, 2), round(upright[1] / dpi, 2))
    coverage = round((upright[0] / dpi) * (upright[1] / dpi) / (box_w * box_h), 3)
    raw_dpi = image.info.get("dpi")
    metadata = None
    if isinstance(raw_dpi, tuple) and len(raw_dpi) == 2:
        try:
            metadata = (round(float(raw_dpi[0]), 1), round(float(raw_dpi[1]), 1))
        except (TypeError, ValueError):
            metadata = None
    info = ArtworkInfo(
        sha256=hashlib.sha256(data).hexdigest(),
        format="jpeg" if image.format == "JPEG" else "png",
        bytes=len(data),
        mode=image.mode,
        stored_pixels=stored,
        pixels=upright,
        orientation=orientation,
        aspect_ratio=round(upright[0] / upright[1], 4),
        alpha_channel=alpha,
        transparent_pixels=transparent,
        dpi_metadata=metadata,
        effective_dpi=round(dpi, 1),
        printed_inches=printed,
        art_box_coverage=coverage,
        ink_coverage=ink,
        background_level=background,
        in_color=in_color,
        dhash=dhash(gray),
    )
    ink_map = gray.resize((16, 16), Image.Resampling.BOX).tobytes()
    return Inspection(info, _findings(info, _edges(gray), image.mode), ink_map)


def _findings(info: ArtworkInfo, edges: list[str], mode: str) -> tuple[ArtworkFinding, ...]:
    found: list[ArtworkFinding] = []
    width, height = ART_BOX_INCHES
    area = f"the {width:g} x {height:g} in art area"
    dpi = info.effective_dpi
    if dpi < POOR_DPI:
        found.append(
            ArtworkFinding(
                "artwork_resolution_too_low",
                Severity.BLOCKING,
                f"About {dpi:.0f} DPI when fitted to {area}; line art needs {MIN_DPI:.0f}. "
                f"Use a file of at least {_minimum_pixels()} pixels.",
                f"{dpi:.0f} DPI",
                f"at least {MIN_DPI:.0f} DPI",
            )
        )
    elif dpi < MIN_DPI:
        found.append(
            ArtworkFinding(
                "artwork_low_resolution",
                Severity.WARNING,
                f"About {dpi:.0f} DPI when fitted to {area}; KDP asks for {MIN_DPI:.0f}. "
                "Lines may print soft or jagged.",
                f"{dpi:.0f} DPI",
                f"at least {MIN_DPI:.0f} DPI",
            )
        )
    if info.ink_coverage < EMPTY_INK:
        found.append(
            ArtworkFinding(
                "artwork_empty",
                Severity.BLOCKING,
                # A faint drawing on tinted paper is not blank: say what was measured.
                # (Seen on a chalk drawing on gray-190 paper, docs/artwork-validation.)
                "No line work darker than mid-gray: the drawing is too faint to print as "
                "ink on this tinted paper."
                if info.background_level < GRAY_BACKGROUND
                else "No line work found: the image is blank or almost white.",
                f"{info.ink_coverage:.2%} ink",
                f"at least {EMPTY_INK:.1%} ink",
            )
        )
    if info.background_level < GRAY_BACKGROUND:
        found.append(
            ArtworkFinding(
                "artwork_gray_background",
                Severity.WARNING,
                "The background is not white; it would print as a gray tint. Clean it up "
                "before printing.",
                f"median level {info.background_level}",
                f"at least {GRAY_BACKGROUND} (white is 255)",
            )
        )
    if info.transparent_pixels:
        found.append(
            ArtworkFinding(
                "artwork_transparency",
                Severity.WARNING,
                "The image has transparent areas; they will print as white paper.",
            )
        )
    if info.in_color:
        found.append(
            ArtworkFinding(
                "artwork_in_color",
                Severity.WARNING,
                "The artwork has color. The interior prints black ink only, so colors become "
                "shades of gray; coloring pages should be black lines on white.",
            )
        )
    if mode == "CMYK":
        found.append(
            ArtworkFinding(
                "artwork_cmyk",
                Severity.WARNING,
                "CMYK files are read with a simple conversion. Export grayscale or RGB for "
                "predictable tones.",
            )
        )
    if info.art_box_coverage < SMALL_ON_PAGE:
        found.append(
            ArtworkFinding(
                "artwork_shape_mismatch",
                Severity.WARNING,
                f"Its shape fills only {info.art_box_coverage:.0%} of {area}; expect wide blank "
                "margins on the page.",
                f"{info.art_box_coverage:.0%}",
                f"at least {SMALL_ON_PAGE:.0%}",
            )
        )
    if edges:
        found.append(
            ArtworkFinding(
                "artwork_touches_edge",
                Severity.WARNING,
                f"Line work reaches the {', '.join(edges)} edge of the image; the drawing may "
                "have been cut off in the source file.",
                ", ".join(edges),
            )
        )
    return tuple(found)


def header_facts(data: bytes) -> dict[str, object]:
    """Format, pixels and mode from the file header only (no pixel decoding)."""
    if not data.startswith((_PNG, _JPEG)):
        raise _refuse_format(data, "")
    try:
        image = Image.open(io.BytesIO(data), formats=tuple(FORMATS))
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as error:
        raise ArtworkError("corrupt_image", "The image header cannot be read.") from error
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "jpeg" if image.format == "JPEG" else "png",
        "bytes": len(data),
        "stored_pixels": list(image.size),
        "mode": image.mode,
    }


def thumbnail_png(data: bytes, side: int = 360) -> bytes:
    """A small upright grayscale PNG on white, for Studio listings only."""
    rgb, _, _ = flattened(open_artwork(data))
    rgb.thumbnail((side, side), Image.Resampling.BOX)
    buffer = io.BytesIO()
    rgb.convert("L").save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()
