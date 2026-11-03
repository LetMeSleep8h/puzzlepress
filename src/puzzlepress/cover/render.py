"""Cover renderer: draws a CoverLayout exactly, deciding no positions itself.

The photograph is cropped to the layout's whole-pixel window, any shade bands
are baked into those pixels, and the result is encoded once as a baseline JPEG
(quality 95, no chroma subsampling) built from bare pixels, so no EXIF, GPS,
XMP, ICC or comment data can reach the PDF. It is embedded as DCTDecode
DeviceRGB, clipped to its region. Fills and text are DeviceRGB. Nothing is
transparent or stroked. ReportLab's invariant mode fixes dates and the ID.

Version 3 adds region fills (solid or a two-color linear shading), several
photographs, and shapes and lines drawn only with fills: a stroke is a filled
outline, so the no-stroke contract still holds. Translucent shapes arrive here
already flattened: blended into an opaque color, or baked into a photograph's
pixels before it is encoded.
"""

import hashlib
import io
import math
from collections.abc import Sequence
from typing import Any

from PIL import Image, ImageDraw
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfdoc
from reportlab.pdfgen.canvas import Canvas

from .. import __version__
from ..interior.model import Anchor, Box
from .assets import Photo
from .fonts import CoverFace, font_name
from .model import CoverLayout, CoverPhoto, CoverShape, CoverText, CoverTextBox, Fill, ShadeBand
from .watermark import bake_watermark

JPEG_QUALITY = 95
FILL_EVEN_ODD = 0  # reportlab.pdfgen.canvas.FILL_EVEN_ODD (absent from the stubs).


def _apply_shade(image: Image.Image, photo: CoverPhoto, band: ShadeBand) -> Image.Image:
    """Blend pixels toward the band's color by a per-row weight, inside its columns."""
    placement, scale = photo.placement, photo.window.scale
    width, height = image.size
    first = max(0, math.ceil((band.x0 - placement.x) / scale - 0.5))
    last = min(width - 1, math.floor((band.x1 - placement.x) / scale - 0.5))
    if last < first:
        return image
    rows = bytes(
        round(255 * band.weight(placement.top - (row + 0.5) * scale)) for row in range(height)
    )
    if not any(rows):
        return image
    strip = Image.frombytes("L", (1, height), rows).resize(
        (last - first + 1, height), Image.Resampling.NEAREST
    )
    mask = Image.new("L", (width, height), 0)
    mask.paste(strip, (first, 0))
    return Image.composite(Image.new("RGB", (width, height), band.toward), image, mask)


def _bake(image: Image.Image, photo: CoverPhoto, shape: CoverShape) -> Image.Image:
    """Composite a translucent shape into the cropped pixels (no PDF transparency)."""
    assert shape.fill is not None
    placement, scale = photo.placement, photo.window.scale
    points = [((x - placement.x) / scale, (placement.top - y) / scale) for x, y in shape.outline()]
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=round(255 * shape.opacity))
    color = tuple(round(255 * channel) for channel in shape.fill)
    return Image.composite(Image.new("RGB", image.size, color), image, mask)


EncodedPhoto = tuple[bytes, tuple[int, int]]


def prepare_photo(photo: Photo, layout: CoverPhoto) -> EncodedPhoto:
    """JPEG bytes of exactly the pixels the layout prints, and their pixel size."""
    if photo.info.sha256 != layout.sha256:
        raise ValueError("The decoded photo is not the one the layout was made for")
    image = photo.image.crop(layout.pixels)
    for shape in layout.baked:
        image = _bake(image, layout, shape)
    for band in layout.shade:
        image = _apply_shade(image, layout, band)
    if layout.watermark is not None:
        image = bake_watermark(image, layout.placement, layout.window.scale, layout.watermark)
    bare = Image.frombytes("RGB", image.size, image.tobytes())  # No info dictionary at all.
    buffer = io.BytesIO()
    bare.save(
        buffer, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=False, progressive=False
    )
    return buffer.getvalue(), bare.size


def _draw_jpeg(
    canvas: Canvas, jpeg: bytes, size: tuple[int, int], box: Box, used: set[str] | None = None
) -> None:
    """Embed JPEG bytes unchanged as one DCTDecode image XObject (no ASCII85 wrapper).

    Mirrors Canvas.drawImage's registration without decoding the image to name it.
    Each photograph is its own XObject; a repeat of identical bytes gets a suffix.
    """
    name = "PPCoverPhoto" + hashlib.sha256(jpeg).hexdigest()[:16]
    if used is not None:
        base, n = name, 2
        while name in used:
            name, n = f"{base}x{n}", n + 1
        used.add(name)
    # ReportLab's private registration API (pinned 5.0.x; untyped in the stubs).
    raw: Any = canvas
    image: Any = pdfdoc.PDFImageXObject(name)
    image.width, image.height = size
    image.bitsPerComponent = 8
    image.colorSpace = "DeviceRGB"
    image.streamContent = jpeg
    image._filters = ("DCTDecode",)
    image.mask = None
    registered = raw._doc.getXObjectName(name)
    raw._setXObjects(image)
    raw._doc.Reference(image, registered)
    raw._doc.addForm(name, image)
    canvas.saveState()
    canvas.translate(box.x, box.y)
    canvas.scale(box.width, box.height)
    raw._code.append(f"/{registered} Do")
    canvas.restoreState()
    raw._formsinuse.append(name)


def _rect(canvas: Canvas, box: Box, color: tuple[float, float, float]) -> None:
    canvas.setFillColorRGB(*color)
    canvas.rect(box.x, box.y, box.width, box.height, stroke=0, fill=1)


def _region(canvas: Canvas, fill: Fill) -> None:
    """A region background: a solid rectangle, or a linear shading clipped to it."""
    if fill.gradient is None:
        _rect(canvas, fill.box, fill.color)
        return
    end, direction = fill.gradient
    box = fill.box
    canvas.saveState()
    path = canvas.beginPath()
    path.rect(box.x, box.y, box.width, box.height)
    canvas.clipPath(path, stroke=0, fill=0)
    x0, y0, x1, y1 = (
        (box.x, box.top, box.x, box.y)
        if direction == "vertical"
        else (box.x, box.y, box.right, box.y)
    )
    canvas.linearGradient(x0, y0, x1, y1, (Color(*fill.color), Color(*end)), extend=True)
    canvas.restoreState()


def _outline(path: Any, shape: CoverShape, inset: float) -> None:
    """Add the shape, inset by `inset` points, to `path` in its centred, unrotated frame."""
    box = shape.box
    width, height = max(0.0, box.width - 2 * inset), max(0.0, box.height - 2 * inset)
    if shape.kind == "ellipse":
        path.ellipse(-width / 2, -height / 2, width, height)
    else:
        path.rect(-width / 2, -height / 2, width, height)


def _shape(canvas: Canvas, shape: CoverShape) -> None:
    """Fill the shape, then its stroke as a filled ring inside the box (never `S`)."""
    box = shape.box
    canvas.saveState()
    canvas.translate(box.x + box.width / 2, box.y + box.height / 2)
    if shape.rotation:
        canvas.rotate(shape.rotation)
    if shape.fill is not None:
        canvas.setFillColorRGB(*shape.fill)
        path = canvas.beginPath()
        _outline(path, shape, 0)
        canvas.drawPath(path, stroke=0, fill=1)
    if shape.stroke is not None:
        canvas.setFillColorRGB(*shape.stroke)
        ring = canvas.beginPath()  # One path: the outline and its inset, filled even-odd.
        _outline(ring, shape, 0)
        if 2 * shape.stroke_width < min(box.width, box.height):
            _outline(ring, shape, shape.stroke_width)
        canvas.drawPath(ring, stroke=0, fill=1, fillMode=FILL_EVEN_ODD)
    canvas.restoreState()


def _text(canvas: Canvas, line: CoverText) -> None:
    canvas.setFont(font_name(line.face), line.size)
    canvas.setFillColorRGB(*line.color)
    if line.underline is not None:  # A filled rectangle in the text color.
        box = line.underline
        canvas.rect(box.x, box.y, box.width, box.height, stroke=0, fill=1)
    draw = {
        Anchor.START: canvas.drawString,
        Anchor.MIDDLE: canvas.drawCentredString,
        Anchor.END: canvas.drawRightString,
    }[line.anchor]
    if line.tracking:  # Only horizontal lines are letter-spaced.
        # They start at their measured left edge; Tc adds the spacing.
        canvas.drawString(line.bounds.x, line.origin[1], line.text, charSpace=line.tracking)
        return
    if line.rotated:
        canvas.saveState()
        canvas.translate(*line.origin)
        canvas.rotate(-90)  # Spine text reads top to bottom.
        draw(0, 0, line.text)
        canvas.restoreState()
    else:
        draw(line.origin[0], line.origin[1], line.text)


def render_cover_pdf(layout: CoverLayout, photos: Sequence[EncodedPhoto]) -> bytes:
    """Draw `layout`; `photos` are the encoded photographs, in stack order."""
    if len(photos) != len(layout.photos):
        raise ValueError("One encoded photograph is needed for each placed photograph")
    g = layout.geometry
    buffer = io.BytesIO()
    canvas = Canvas(
        buffer,
        pagesize=(g.media.width, g.media.height),
        invariant=True,
        pageCompression=True,
        initialFontName=font_name(CoverFace.SANS),  # type: ignore[arg-type]  # stub says float
    )
    # KDP asks for no metadata: write empty descriptive fields, not library defaults.
    canvas.setTitle("")
    canvas.setAuthor("")
    canvas.setSubject("")
    canvas.setKeywords("")
    canvas.setCreator(f"PuzzlePress {__version__}")
    trim = g.trim
    canvas.setTrimBox((trim.x, trim.y, trim.right, trim.top))
    canvas.setBleedBox((g.media.x, g.media.y, g.media.right, g.media.top))
    _rect(canvas, layout.background.box, layout.background.color)
    for fill in layout.region_fills:
        _region(canvas, fill)
    encoded = iter(photos)
    remaining = len(layout.photos)
    used: set[str] = set()
    if not remaining:
        for panel in layout.panels:
            _rect(canvas, panel.box, panel.color)
    for item in layout.stack:
        if isinstance(item, CoverPhoto):
            jpeg, size = next(encoded)
            region = item.region
            canvas.saveState()
            path = canvas.beginPath()
            path.rect(region.x, region.y, region.width, region.height)
            canvas.clipPath(path, stroke=0, fill=0)
            _draw_jpeg(canvas, jpeg, size, item.placement, used)
            canvas.restoreState()
            remaining -= 1
            if not remaining:  # Legibility panels sit directly above the topmost photo.
                for panel in layout.panels:
                    _rect(canvas, panel.box, panel.color)
        elif isinstance(item, CoverShape):
            _shape(canvas, item)
        elif isinstance(item, CoverTextBox):
            for line in layout.texts:
                if line.role == item.role:
                    _text(canvas, line)
    for line in layout.texts:
        if not layout.is_stack_text(line):
            _text(canvas, line)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()
