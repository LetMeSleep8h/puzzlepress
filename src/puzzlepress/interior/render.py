"""PDF renderer: draws an InteriorLayout exactly, deciding no positions itself.

ReportLab's invariant mode fixes timestamps and the document ID, so identical
layouts produce identical bytes. Ink is DeviceGray only; nothing is transparent.
No annotations, outlines, marks or links are written.
"""

import hashlib
import io
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from reportlab.pdfbase import pdfdoc
from reportlab.pdfgen.canvas import Canvas

from .. import __version__
from ..cancellation import checkpoint
from .fonts import font_name
from .model import (
    Anchor,
    Face,
    ImageBlock,
    ImageEncoding,
    InteriorLayout,
    LetterGrid,
    Panel,
    Polygon,
    Rule,
    TextLine,
)


@dataclass(frozen=True)
class LosslessImage:
    """Exact DeviceGray samples, deflated: 1 or 8 bits per pixel, rows byte-padded."""

    samples: bytes
    size: tuple[int, int]
    bits: int


# Encoded images by (physical page, element role): a photograph's DeviceGray JPEG
# and its size, or line art's lossless samples.
EncodedImages = Mapping[tuple[int, str], tuple[bytes, tuple[int, int]] | LosslessImage]


def render_pdf(layout: InteriorLayout, images: EncodedImages | None = None) -> bytes:
    """Draw `layout`; `images` holds each ImageBlock's encoded pixels.

    An element type the renderer does not know is an error, never drawn as
    something else.
    """
    buffer = io.BytesIO()
    size = (layout.spec.trim.width, layout.spec.trim.height)
    # A TrueType initial font keeps ReportLab from adding an unembedded Helvetica.
    canvas = Canvas(
        buffer,
        pagesize=size,
        invariant=True,
        pageCompression=True,
        initialFontName=font_name(Face.REGULAR),  # type: ignore[arg-type]  # stub says float
    )
    # KDP asks for no metadata: write empty descriptive fields, not library defaults.
    canvas.setTitle("")
    canvas.setAuthor("")
    canvas.setSubject("")
    canvas.setKeywords("")
    canvas.setCreator(f"PuzzlePress {__version__}")
    for number, page in enumerate(layout.pages):
        checkpoint("render_pages", number, len(layout.pages))
        media, trim = page.frame.media, page.frame.trim
        canvas.setPageSize((media.width, media.height))
        canvas.setTrimBox((trim.x, trim.y, trim.right, trim.top))
        for element in page.elements:
            if isinstance(element, TextLine):
                _text(canvas, element)
            elif isinstance(element, Rule):
                _rule(canvas, element)
            elif isinstance(element, Panel):
                _panel(canvas, element)
            elif isinstance(element, Polygon):
                _polygon(canvas, element)
            elif isinstance(element, ImageBlock):
                if images is None or (page.number, element.role) not in images:
                    raise ValueError(f"No encoded image for {element.role} on page {page.number}")
                payload = images[(page.number, element.role)]
                if element.encoding is ImageEncoding.LOSSLESS:
                    if not isinstance(payload, LosslessImage):
                        raise ValueError(f"{element.role} is line art and needs lossless samples")
                    _lossless(canvas, element, payload)
                else:
                    if isinstance(payload, LosslessImage):
                        raise ValueError(f"{element.role} is a JPEG photograph, not line art")
                    _image(canvas, element, *payload)
            elif isinstance(element, LetterGrid):
                _grid(canvas, element)
            else:
                raise ValueError(
                    f"Unsupported layout element {type(element).__name__} on page {page.number}"
                )
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _text(canvas: Canvas, line: TextLine) -> None:
    canvas.setFont(font_name(line.face), line.size)
    canvas.setFillGray(line.gray)
    draw = {
        Anchor.START: canvas.drawString,
        Anchor.MIDDLE: canvas.drawCentredString,
        Anchor.END: canvas.drawRightString,
    }[line.anchor]
    draw(line.x, line.baseline, line.text)


def _rule(canvas: Canvas, rule: Rule) -> None:
    canvas.setStrokeGray(rule.gray)
    canvas.setLineWidth(rule.width)
    canvas.line(rule.x1, rule.y1, rule.x2, rule.y2)


def _panel(canvas: Canvas, panel: Panel) -> None:
    box = panel.box
    if panel.fill_gray is not None:
        canvas.setFillGray(panel.fill_gray)
    if panel.stroke_gray is not None:
        canvas.setStrokeGray(panel.stroke_gray)
        canvas.setLineWidth(panel.stroke_width)
    stroke, fill = int(panel.stroke_gray is not None), int(panel.fill_gray is not None)
    if panel.radius > 0:
        canvas.roundRect(box.x, box.y, box.width, box.height, panel.radius, stroke, fill)
    else:
        canvas.rect(box.x, box.y, box.width, box.height, stroke=stroke, fill=fill)


def _polygon(canvas: Canvas, shape: Polygon) -> None:
    canvas.setFillGray(shape.fill_gray)
    path = canvas.beginPath()
    (x, y), *rest = shape.points
    path.moveTo(x, y)
    for x, y in rest:
        path.lineTo(x, y)
    path.close()
    canvas.drawPath(path, stroke=0, fill=1)


def _image(canvas: Canvas, block: ImageBlock, jpeg: bytes, size: tuple[int, int]) -> None:
    """Embed the grayscale JPEG unchanged as one DCTDecode DeviceGray XObject, clipped."""
    name = "PPInteriorPhoto" + hashlib.sha256(jpeg).hexdigest()[:16]
    raw: Any = canvas  # ReportLab's private registration API (pinned 5.0.x).
    # Registered once per document: `_formsinuse` is reset on every page, so checking
    # it re-registered a photograph shown on a second page and ReportLab refused it.
    if raw._doc.idToObject.get(raw._doc.getXObjectName(name)) is None:
        image: Any = pdfdoc.PDFImageXObject(name)
        image.width, image.height = size
        image.bitsPerComponent = 8
        image.colorSpace = "DeviceGray"
        image.streamContent = jpeg
        image._filters = ("DCTDecode",)
        image.mask = None
        registered = raw._doc.getXObjectName(name)
        raw._setXObjects(image)
        raw._doc.Reference(image, registered)
        raw._doc.addForm(name, image)
    registered = raw._doc.getXObjectName(name)
    box, placement = block.box, block.placement
    canvas.saveState()
    path = canvas.beginPath()
    path.rect(box.x, box.y, box.width, box.height)
    canvas.clipPath(path, stroke=0, fill=0)
    canvas.translate(placement.x, placement.y)
    canvas.scale(placement.width, placement.height)
    raw._code.append(f"/{registered} Do")
    canvas.restoreState()
    raw._formsinuse.append(name)


def _lossless(canvas: Canvas, block: ImageBlock, art: LosslessImage) -> None:
    """Embed exact samples as one FlateDecode DeviceGray XObject at its placement.

    No clip, smoothing or interpolation: the placement is the printed box itself.
    """
    if art.bits not in (1, 8):
        raise ValueError("Line art is embedded at 1 or 8 bits per pixel")
    name = "PPLineArt" + hashlib.sha256(art.samples).hexdigest()[:16]
    raw: Any = canvas  # ReportLab's private registration API (pinned 5.0.x).
    # Registered once per document (as ReportLab's drawImage does), so a drawing
    # printed on several pages is embedded once and referenced from each.
    if raw._doc.idToObject.get(raw._doc.getXObjectName(name)) is None:
        image: Any = pdfdoc.PDFImageXObject(name)
        image.width, image.height = art.size
        image.bitsPerComponent = art.bits
        image.colorSpace = "DeviceGray"
        image.streamContent = art.samples
        image._filters = ("FlateDecode",)
        image.mask = None
        registered = raw._doc.getXObjectName(name)
        raw._setXObjects(image)
        raw._doc.Reference(image, registered)
        raw._doc.addForm(name, image)
    registered = raw._doc.getXObjectName(name)
    placement = block.placement
    canvas.saveState()
    canvas.translate(placement.x, placement.y)
    canvas.scale(placement.width, placement.height)
    raw._code.append(f"/{registered} Do")
    canvas.restoreState()
    raw._formsinuse.append(name)


def _grid(canvas: Canvas, grid: LetterGrid) -> None:
    canvas.setStrokeGray(0)
    canvas.setLineWidth(grid.frame_width)
    frame = grid.frame
    if grid.frame_radius > 0:
        canvas.roundRect(frame.x, frame.y, frame.width, frame.height, grid.frame_radius, 1, 0)
    else:
        canvas.rect(frame.x, frame.y, frame.width, frame.height, stroke=1, fill=0)
    for row, letters in enumerate(grid.rows):
        for column, letter in enumerate(letters):
            emphasized = (column, row) in grid.emphasized
            face = grid.emphasized_face if emphasized else grid.face
            canvas.setFont(font_name(face), grid.letter_size)
            canvas.setFillGray(0 if emphasized or not grid.marks else grid.muted_gray)
            x, y = grid.center(column, row)
            canvas.drawCentredString(x, y - grid.baseline_offset, letter)
    for mark in grid.marks:
        (x1, y1), (x2, y2) = mark.start, mark.end
        length = math.hypot(x2 - x1, y2 - y1)
        radius = mark.radius
        canvas.saveState()
        canvas.setLineWidth(mark.line_width)
        canvas.translate(x1, y1)
        canvas.rotate(math.degrees(math.atan2(y2 - y1, x2 - x1)))
        canvas.roundRect(
            -radius, -radius, length + 2 * radius, 2 * radius, radius, stroke=1, fill=0
        )
        canvas.restoreState()
