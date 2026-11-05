"""Independent PDF inspection with pypdf: observed facts, then contract checks.

The renderer returning is not evidence of a correct file. `read_pdf_facts`
reopens the bytes and records what the file contains (boxes, fonts, images,
annotations, transparency, text). It judges nothing. `inspect_pdf` checks those
facts against the layout after a build; preflight rules judge the same facts.
"""

import io
import re
from dataclasses import dataclass

from pypdf import PageObject, PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import ArrayObject, DictionaryObject

from ..cancellation import checkpoint
from .issues import LayoutIssue
from .model import Box, ImageBlock, InteriorLayout

BOX_TOLERANCE = 0.01
IDENTITY_TRANSFORM = b"1 0 0 1 0 0 cm"
# Catalog entries that add interactive or navigational behavior to a print file.
INTERACTIVE_CATALOG_KEYS = ("/AcroForm", "/OpenAction", "/Names")
DESCRIPTIVE_METADATA = ("/Title", "/Author", "/Subject", "/Keywords")
_SUBSET_PREFIX = re.compile(r"^/?[A-Z]{6}\+")

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 in points.


@dataclass(frozen=True)
class PdfFont:
    name: str
    embedded: bool
    subset: bool


@dataclass(frozen=True)
class PdfPageFacts:
    number: int  # 1-based.
    media: Rect | None
    trim: Rect | None
    bleed: Rect | None
    rotation: int
    annotations: int
    fonts: tuple[PdfFont, ...]
    images: int
    transparency: bool
    painted: bool  # Any content beyond ReportLab's identity transform.
    text: str


@dataclass(frozen=True)
class PdfFacts:
    page_count: int
    encrypted: bool
    outline: bool
    interactive: tuple[str, ...]  # Present INTERACTIVE_CATALOG_KEYS.
    optional_content: bool  # Layers (/OCProperties).
    descriptive_metadata: tuple[str, ...]  # Non-empty DESCRIPTIVE_METADATA fields.
    pages: tuple[PdfPageFacts, ...]


def read_pdf_facts(data: bytes) -> PdfFacts | LayoutIssue:
    """Observe a PDF; an empty or unparsable file yields a single issue instead."""
    if not data:
        return LayoutIssue("pdf_empty", "The PDF has no bytes.")
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            # Observe an owner-locked file that opens without a password; record it.
            reader.decrypt("")
        catalog = reader.root_object
        info: dict[str, object] = dict(reader.metadata or {})
        count = len(reader.pages)
        facts: list[PdfPageFacts] = []
        for number, page in enumerate(reader.pages, 1):
            checkpoint("inspect_pdf", number - 1, count)
            facts.append(_page_facts(number, page))
        pages = tuple(facts)
        return PdfFacts(
            page_count=len(pages),
            encrypted=reader.is_encrypted,
            outline=bool(reader.outline),
            interactive=tuple(key for key in INTERACTIVE_CATALOG_KEYS if key in catalog),
            optional_content="/OCProperties" in catalog,
            descriptive_metadata=tuple(
                key for key in DESCRIPTIVE_METADATA if str(info.get(key) or "").strip()
            ),
            pages=pages,
        )
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, OSError) as error:
        return LayoutIssue("pdf_unreadable", f"The PDF does not parse: {error}")


def _rect(value: object) -> Rect | None:
    if not isinstance(value, ArrayObject) or len(value) != 4:
        return None
    x0, y0, x1, y1 = (float(v) for v in value)
    return (x0, y0, x1, y1)


def _page_facts(number: int, page: PageObject) -> PdfPageFacts:
    resources = page.get("/Resources")
    resources = resources.get_object() if resources is not None else DictionaryObject()
    fonts = resources.get("/Font")
    contents = page.get_contents()
    stream = contents.get_data() if contents is not None else b""
    return PdfPageFacts(
        number=number,
        media=_rect(page.get("/MediaBox")),
        trim=_rect(page.get("/TrimBox")),
        bleed=_rect(page.get("/BleedBox")),
        rotation=int(page.get("/Rotate", 0)),
        annotations=len(page.get("/Annots", ArrayObject()).get_object()),
        fonts=tuple(
            _font(font.get_object()) for font in (fonts.get_object().values() if fonts else [])
        ),
        images=_image_count(page, resources, stream),
        transparency=_transparent(page, resources),
        painted=bool(stream.replace(IDENTITY_TRANSFORM, b"").strip()),
        text=page.extract_text() or "",
    )


def _image_count(page: PageObject, resources: DictionaryObject, stream: bytes) -> int:
    """pypdf's image count, without its second content-stream parse when none can exist.

    pypdf finds images only in /XObject resources and inline `BI` operators. A page
    with neither an /XObject resource nor the bytes `BI` anywhere in its decoded
    content has no image, so the answer (0) is exact; otherwise pypdf counts.
    """
    if "/XObject" not in resources and b"BI" not in stream:
        return 0
    return len(page.images)


def _font(font: DictionaryObject) -> PdfFont:
    name = str(font.get("/BaseFont", ""))
    if font.get("/Subtype") == "/Type0":
        descendants = font.get("/DescendantFonts")
        font = descendants.get_object()[0].get_object() if descendants else DictionaryObject()
    descriptor = font.get("/FontDescriptor")
    descriptor = descriptor.get_object() if descriptor is not None else DictionaryObject()
    return PdfFont(
        name=name,
        embedded=any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")),
        subset=bool(_SUBSET_PREFIX.match(name)),
    )


def _transparent(page: PageObject, resources: DictionaryObject) -> bool:
    group = page.get("/Group")
    if group is not None and group.get_object().get("/S") == "/Transparency":
        return True
    states = resources.get("/ExtGState")
    for state in states.get_object().values() if states is not None else []:
        state = state.get_object()
        if any(float(state.get(key, 1)) < 1 for key in ("/CA", "/ca")):
            return True
        if state.get("/SMask", "/None") != "/None" or state.get("/BM", "/Normal") not in (
            "/Normal",
            "/Compatible",
        ):
            return True
    return False


def same_box(actual: Rect | None, expected: Box) -> bool:
    if actual is None:
        return False
    target = (expected.x, expected.y, expected.right, expected.top)
    return all(abs(a - b) <= BOX_TOLERANCE for a, b in zip(actual, target, strict=True))


def inspect_pdf(data: bytes, layout: InteriorLayout) -> tuple[LayoutIssue, ...]:
    """Post-build contract: the PDF faithfully carries the layout it was drawn from."""
    facts = read_pdf_facts(data)
    if isinstance(facts, LayoutIssue):
        return (facts,)
    return contract_issues(facts, layout)


def contract_issues(facts: PdfFacts, layout: InteriorLayout) -> tuple[LayoutIssue, ...]:
    issues: list[LayoutIssue] = []

    def fail(code: str, message: str, page: int | None = None) -> None:
        issues.append(LayoutIssue(code, message, physical_page=page))

    if facts.encrypted:
        fail("pdf_encrypted", "The interior must not be encrypted.")
    if facts.page_count != len(layout.pages):
        fail(
            "pdf_page_count",
            f"PDF has {facts.page_count} pages; the layout has {len(layout.pages)}.",
        )
        return tuple(issues)
    if facts.outline:
        fail("pdf_outline", "The PDF contains bookmarks.")
    for key in facts.interactive:
        fail("pdf_catalog", f"Unexpected catalog entry {key}.")
    for page, planned in zip(facts.pages, layout.pages, strict=True):
        number = page.number
        if page.annotations:
            fail("pdf_annotations", "The page contains annotations.", number)
        if page.rotation != 0:
            fail("pdf_rotation", "The page is rotated.", number)
        for name, actual, expected in (
            ("/MediaBox", page.media, planned.frame.media),
            ("/TrimBox", page.trim, planned.frame.trim),
        ):
            if not same_box(actual, expected):
                fail("pdf_page_size", f"{name} differs from the layout.", number)
        if any(not font.embedded for font in page.fonts):
            fail("font_not_embedded", "A font on the page is not embedded.", number)
        placed = sum(isinstance(e, ImageBlock) for e in planned.elements)
        if page.images != placed:
            fail(
                "pdf_images",
                f"The page has {page.images} images; its layout places {placed}.",
                number,
            )
        if not planned.elements:
            # Font resources are shared document-wide; a blank page may carry only
            # ReportLab's identity transform and no painting operators.
            if page.text.strip() or page.painted:
                fail("pdf_blank_page", "An intentional blank page has content.", number)
        elif planned.folio is not None and planned.folio not in page.text.split():
            fail("pdf_folio", "The printed page number is missing.", number)
    return tuple(issues)
