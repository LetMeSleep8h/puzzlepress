"""Coloring interiors: layout, lossless line-art embedding and image integrity.

A verified coloring plan becomes one physical page per plan entry, in plan order,
exactly as word-search interiors do. Title, copyright, instructions, about and notes
pages and section dividers use the classic word-search templates unchanged; a
coloring page holds one prepared drawing and, when the book asks for one, a ruled
border. The layout never reorders, inserts, omits or resizes pages.

Placement: a drawing is fitted whole ("contain") and centred in the art box: the
live area above the page-number band, inset inside a border when there is one.
The box is the same whether or not numbers print, so turning numbers off never
moves art. Scale is uniform, so the aspect ratio is exact, and nothing is cropped
or clipped. Effective DPI is the prepared pixels per printed inch; it is measured,
and the 300 DPI KDP minimum is a preflight finding, not a build failure.

Encoding: the prepared pixels are embedded exactly as `coloring.content` packed
them, deflated (FlateDecode) DeviceGray at 1 bit per pixel when they are only black
and white and 8 bits otherwise. Nothing is resampled, recompressed as JPEG,
smoothed or interpolated by PuzzlePress; the PDF draws the image at its placement
and the printer's RIP scales it. After rendering, every embedded image is decoded
again and compared with the prepared pixels digest by digest.

Deflate output is byte-reproducible only with the same zlib implementation, so the
coloring identity records it (see `coloring_toolchain`).
"""

import hashlib
import io
import platform
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import PIL
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import ArrayObject, NameObject

from ..coloring.content import ColoringContent, PreparedArt
from ..coloring.prepare import PREPARATION_VERSION, pixel_digest
from ..coloring_config import Border
from ..publication import PageKind, PublicationPlan
from .design import CLASSIC
from .engine import (
    _copyright_page,
    _divider_page,
    _folio,
    _notes_page,
    _Page,
    _text_page,
    _title_page,
    page_count_checks,
    plan_digest,
)
from .geometry import page_frame
from .issues import InteriorError, LayoutIssue
from .model import Box, ImageBlock, ImageEncoding, InteriorLayout, Panel, PhysicalPage
from .render import LosslessImage
from .spec import PrintSpecification, validate_print_spec
from .validation import EPSILON, validate_layout

# 1: contain-fit, centred art in the body above the folio band; thin (1 pt) and
# double (1.5 + 0.75 pt) borders; deflate level coloring.content.DEFLATE_LEVEL.
COLORING_RENDERER_VERSION = 1
ART_ROLE = "coloring_art"
BORDER_ROLE = "coloring_border"
BORDER_PAD = 12.0  # Art keeps this far inside a border's innermost stroke.
DOUBLE_GAP = 4.0  # Between a double border's two strokes.
# (stroke widths, outermost first) per border style.
BORDER_STROKES: dict[Border, tuple[float, ...]] = {
    Border.NONE: (),
    Border.THIN: (1.0,),
    Border.DOUBLE: (1.5, 0.75),
}


def zlib_implementation() -> str:
    """The deflate implementation's identity: classic zlib output is stable across
    releases; zlib-ng (Python 3.14 on Windows links it) is recorded with its version.
    """
    runtime = zlib.ZLIB_RUNTIME_VERSION
    return f"zlib-ng {runtime}" if "zlib-ng" in runtime.lower() else "zlib"


def coloring_toolchain() -> dict[str, object]:
    """Output-affecting inputs of a coloring interior beyond the shared toolchain."""
    return {
        "renderer_version": COLORING_RENDERER_VERSION,
        "preparation_version": PREPARATION_VERSION,
        "image_library": f"pillow {PIL.__version__}",
        "zlib": zlib_implementation(),
    }


def environment() -> dict[str, object]:
    """Recorded for traceability only: what this interior was rendered with."""
    from importlib.metadata import version

    return {
        "python": platform.python_version(),
        "pillow": PIL.__version__,
        "reportlab": version("reportlab"),
        "pypdf": version("pypdf"),
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
    }


# ------------------------------------------------------------------------- layout


def art_box(body: Box, border: Border) -> Box:
    """Where a drawing may print on a coloring page: inside every border stroke."""
    strokes = BORDER_STROKES[border]
    if not strokes:
        return body
    inset = sum(strokes) + DOUBLE_GAP * (len(strokes) - 1) + BORDER_PAD
    return Box(body.x + inset, body.y + inset, body.width - 2 * inset, body.height - 2 * inset)


def _border(page: _Page, border: Border) -> None:
    """Ruled frames whose painted strokes stay inside the page body."""
    offset = 0.0
    for index, width in enumerate(BORDER_STROKES[border]):
        body = page.body
        box = Box(
            body.x + offset + width / 2,
            body.y + offset + width / 2,
            body.width - 2 * offset - width,
            body.height - 2 * offset - width,
        )
        page.elements.append(Panel(f"{BORDER_ROLE}_{index + 1}", box, None, 0.0, width))
        offset += width + DOUBLE_GAP


def place_art(box: Box, width: int, height: int) -> tuple[Box, float]:
    """(placement, effective DPI): the whole drawing, uniformly scaled and centred."""
    scale = min(box.width / width, box.height / height)  # Points per pixel.
    placed_w, placed_h = width * scale, height * scale
    placement = Box(
        box.x + (box.width - placed_w) / 2, box.y + (box.height - placed_h) / 2, placed_w, placed_h
    )
    return placement, 72.0 / scale


def _coloring_page(page: _Page, art: Mapping[str, PreparedArt], border: Border) -> None:
    ref = page.plan_page.artwork
    assert ref is not None
    prepared = art[ref.id]
    if border is not Border.NONE:
        _border(page, border)
    region = art_box(page.body, border)
    placement, dpi = place_art(region, prepared.width, prepared.height)
    page.elements.append(
        ImageBlock(
            ART_ROLE,
            placement,
            prepared.digest,
            placement,
            (0, 0, prepared.width, prepared.height),
            dpi,
            dpi,
            ImageEncoding.LOSSLESS,
        )
    )


def _bindings(plan: PublicationPlan, content: ColoringContent) -> tuple[LayoutIssue, ...]:
    """Every coloring page names prepared pixels the content holds, by digest."""
    issues: list[LayoutIssue] = []
    if not plan.complete:
        issues.extend(
            LayoutIssue("incomplete_plan", d.message, subject=d.code, region=d.path)
            for d in plan.diagnostics
        )
    if content.identity != plan.identity:
        issues.append(
            LayoutIssue(
                "identity_mismatch",
                "Prepared artwork and plan come from different sources.",
                actual=content.identity,
                required=plan.identity,
            )
        )
    for page in plan.pages:
        ref = page.artwork
        if page.kind is not PageKind.COLORING or ref is None:
            continue
        prepared = content.art.get(ref.id)
        if prepared is None or prepared.digest != ref.prepared:
            issues.append(
                LayoutIssue(
                    "digest_mismatch" if prepared else "missing_artwork",
                    "Prepared artwork differs from the plan's digest."
                    if prepared
                    else "No prepared artwork for this page.",
                    page=page.index,
                    kind=page.kind.value,
                    subject=ref.id,
                    actual=prepared.digest if prepared else None,
                    required=ref.prepared,
                )
            )
    return tuple(issues)


def layout_coloring(
    plan: PublicationPlan, content: ColoringContent, spec: PrintSpecification, border: Border
) -> InteriorLayout:
    """Lay out a verified coloring plan. Raises InteriorError with every diagnostic."""
    spec_issues = validate_print_spec(spec)
    if spec_issues:
        raise InteriorError("print_spec", spec_issues)
    binding = _bindings(plan, content)
    if binding:
        raise InteriorError("integrity", binding)
    count_errors, warnings = page_count_checks(spec, len(plan.pages))
    if count_errors:
        raise InteriorError("layout", count_errors)
    renderers: dict[PageKind, Callable[[_Page], None]] = {
        PageKind.TITLE_PAGE: _title_page,
        PageKind.COPYRIGHT_PAGE: _copyright_page,
        PageKind.INSTRUCTIONS: _text_page,
        PageKind.ABOUT: _text_page,
        PageKind.NOTES: _notes_page,
        PageKind.DIVIDER: _divider_page,
        PageKind.BLANK: lambda page: None,
        PageKind.COLORING: lambda page: _coloring_page(page, content.art, border),
    }
    pages: list[PhysicalPage] = []
    issues: list[LayoutIssue] = []
    for position, plan_page in enumerate(plan.pages):
        number = position + 1
        page = _Page(spec, plan_page, number, page_frame(spec, number), CLASSIC)
        if plan_page.index != number:
            page.issue("plan_order", "Plan indexes must equal physical page order.")
        renderer = renderers.get(plan_page.kind)
        if renderer is None:
            page.issue("unsupported_page_type", "Coloring interiors cannot draw this entry kind.")
        else:
            renderer(page)
            if plan_page.number.displayed:
                _folio(page)
        issues.extend(page.issues)
        pages.append(page.freeze())
    if issues:
        raise InteriorError("layout", tuple(issues))
    return InteriorLayout(
        spec=spec,
        book_id=plan.book_id,
        identity=plan.identity,
        plan_digest=plan_digest(plan),
        pages=tuple(pages),
        warnings=warnings,
        design=CLASSIC,
    )


def validate_coloring_layout(
    layout: InteriorLayout, plan: PublicationPlan, content: ColoringContent, border: Border
) -> tuple[LayoutIssue, ...]:
    """The shared structural checks, plus each coloring page's drawing and border."""
    issues = list(validate_layout(layout, plan, None))
    if issues and issues[0].code == "page_count_mismatch":
        return tuple(issues)
    strokes = BORDER_STROKES[border]
    for page, entry in zip(layout.pages, plan.pages, strict=True):

        def fail(code: str, message: str, page: PhysicalPage = page) -> None:
            issues.append(
                LayoutIssue(
                    code, message, page=page.plan_index, physical_page=page.number, kind=page.kind
                )
            )

        images = [e for e in page.elements if isinstance(e, ImageBlock)]
        if entry.kind is not PageKind.COLORING:
            if images:
                fail("unexpected_image", "Only coloring pages carry a drawing.")
            continue
        ref = entry.artwork
        prepared = content.art.get(ref.id) if ref else None
        if ref is None or prepared is None or len(images) != 1:
            fail("artwork_content", "A coloring page carries exactly its one drawing.")
            continue
        (image,) = images
        frames = [e for e in page.elements if isinstance(e, Panel)]
        region = art_box(_body(page), border)
        width, height = prepared.width, prepared.height
        placement = image.placement
        if (
            image.role != ART_ROLE
            or image.encoding is not ImageEncoding.LOSSLESS
            or image.sha256 != ref.prepared
            or image.pixels != (0, 0, width, height)
        ):
            fail("artwork_content", "The drawing is not the prepared pixels, whole and lossless.")
        if image.box != placement:
            fail("artwork_clipped", "The drawing is clipped to a smaller box.")
        if not region.contains(placement, EPSILON):
            fail("artwork_outside_box", "The drawing extends beyond its art box.")
        if abs(placement.width * height - placement.height * width) > EPSILON * max(width, height):
            fail("artwork_distorted", "The drawing is not uniformly scaled.")
        if abs(image.effective_dpi - width * 72.0 / placement.width) > 1e-6:
            fail("artwork_dpi", "The recorded effective DPI does not match the placement.")
        if [f.stroke_width for f in frames] != list(strokes) or any(
            f.fill_gray is not None or f.stroke_gray != 0.0 for f in frames
        ):
            fail("border_mismatch", "The page border differs from the book's border setting.")
    return tuple(issues)


def _body(page: PhysicalPage) -> Box:
    """The page body: the live area above the folio band (as `_Page.body`)."""
    from .engine import FOLIO_BAND

    content = page.frame.content
    return Box(content.x, content.y + FOLIO_BAND, content.width, content.height - FOLIO_BAND)


def encode_art(
    layout: InteriorLayout, content: ColoringContent
) -> dict[tuple[int, str], LosslessImage]:
    """Each drawing's packed samples, keyed as the renderer expects."""
    by_digest = {art.digest: art for art in content.art.values()}
    encoded: dict[tuple[int, str], LosslessImage] = {}
    for page in layout.pages:
        for element in page.elements:
            if isinstance(element, ImageBlock):
                art = by_digest[element.sha256]
                encoded[(page.number, element.role)] = LosslessImage(
                    art.samples, (art.width, art.height), art.bits
                )
    return encoded


# ---------------------------------------------------------------- image integrity


@dataclass(frozen=True)
class EmbeddedImage:
    """What one embedded image XObject on a page actually holds."""

    page: int  # 1-based physical page.
    name: str
    width: int
    height: int
    bits: int
    color_space: str
    filters: tuple[str, ...]
    digest: str | None  # `pixel_digest` of the decoded samples; None if undecodable.

    def to_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "name": self.name,
            "pixels": [self.width, self.height],
            "bits": self.bits,
            "color_space": self.color_space,
            "filters": list(self.filters),
            "digest": self.digest,
        }


def embedded_images(pdf: bytes) -> tuple[EmbeddedImage, ...] | LayoutIssue:
    """Decode every image XObject the pages reference, independently of the renderer."""
    try:
        reader = PdfReader(io.BytesIO(pdf), strict=True)
        found: list[EmbeddedImage] = []
        for number, page in enumerate(reader.pages, start=1):
            resources = page.get("/Resources")
            resources = resources.get_object() if resources is not None else {}
            xobjects = resources.get("/XObject")
            if xobjects is None:
                continue
            for name, reference in sorted(xobjects.get_object().items()):
                stream = reference.get_object()
                if stream.get("/Subtype") != "/Image":
                    continue
                raw_filters = stream.get("/Filter")
                if raw_filters is None:
                    filters: tuple[str, ...] = ()
                elif isinstance(raw_filters, ArrayObject):
                    filters = tuple(str(f) for f in raw_filters)
                else:
                    filters = (str(raw_filters),)
                width, height = int(stream["/Width"]), int(stream["/Height"])
                bits = int(stream.get("/BitsPerComponent", 0))
                space = stream.get("/ColorSpace")
                digest = None
                if filters == ("/FlateDecode",) and space == NameObject("/DeviceGray"):
                    digest = _decoded_digest(zlib.decompress(stream._data), width, height, bits)
                found.append(
                    EmbeddedImage(
                        number, str(name), width, height, bits, str(space), filters, digest
                    )
                )
        return tuple(found)
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, zlib.error) as error:
        return LayoutIssue("pdf_images_unreadable", f"Embedded images do not decode: {error}")


def _decoded_digest(raw: bytes, width: int, height: int, bits: int) -> str | None:
    from PIL import Image

    try:
        if bits == 1:
            image = Image.frombytes("1", (width, height), raw).convert("L")
        elif bits == 8:
            image = Image.frombytes("L", (width, height), raw)
        else:
            return None
    except ValueError:
        return None
    return pixel_digest(image)


def image_integrity(
    images: tuple[EmbeddedImage, ...], layout: InteriorLayout, content: ColoringContent
) -> tuple[LayoutIssue, ...]:
    """Each coloring page embeds exactly its prepared pixels, losslessly; nothing else."""
    issues: list[LayoutIssue] = []
    by_digest = {art.digest: art for art in content.art.values()}
    pages: dict[int, list[EmbeddedImage]] = {}
    for image in images:
        pages.setdefault(image.page, []).append(image)
    for page in layout.pages:
        expected = [e for e in page.elements if isinstance(e, ImageBlock)]
        found = pages.get(page.number, [])

        def fail(code: str, message: str, page: PhysicalPage = page) -> None:
            issues.append(
                LayoutIssue(
                    code, message, physical_page=page.number, kind=page.kind, region="image"
                )
            )

        if len(found) != len(expected):
            fail(
                "pdf_images",
                f"The page embeds {len(found)} images; its layout places {len(expected)}.",
            )
            continue
        for block, image in zip(expected, found, strict=True):
            art = by_digest.get(block.sha256)
            if art is None:
                fail("pdf_image_unknown", "An embedded image is not prepared artwork.")
                continue
            if image.filters != ("/FlateDecode",) or image.color_space != "/DeviceGray":
                fail(
                    "pdf_image_lossy",
                    f"Line art must be lossless DeviceGray Flate; found {image.color_space} "
                    f"{', '.join(image.filters) or 'unfiltered'}.",
                )
            elif (image.width, image.height, image.bits) != (art.width, art.height, art.bits):
                fail(
                    "pdf_image_resampled",
                    f"The embedded image is {image.width} x {image.height} at {image.bits} bit; "
                    f"the prepared drawing is {art.width} x {art.height} at {art.bits} bit.",
                )
            elif image.digest != art.digest:
                fail("pdf_image_pixels", "The embedded pixels differ from the prepared drawing.")
    return tuple(issues)


def art_digest(art: PreparedArt) -> str:
    """The SHA-256 of the packed samples (the embedded stream's bytes)."""
    return hashlib.sha256(art.samples).hexdigest()
