"""Full-bleed PDFs agree with Studio's crop preview, pixel for pixel (Interval 10).

For every bleed profile, a SYNTHETIC two-drawing book fills one recto and one verso.
Each built page is rendered by PDFium (the rasterizer Studio's Print proof uses) and
compared with a raster made independently from Studio's preview data
(`coloring_placements`: the drawing's whole extent and the fill box it is clipped
to), never from the layout's own elements. Also checked from the PDF: page and trim
boxes by parity, white beyond the fill box on the binding side.
"""

import io
from pathlib import Path

import pytest
from coloring_helpers import composed_coloring_book
from PIL import Image, ImageChops, ImageFilter
from pypdf import PdfReader

from puzzlepress import dump_project, load_project, validate_project
from puzzlepress.engines.registry import engine_for
from puzzlepress.interior import build_interior
from puzzlepress.interior.spec import KDP, PROFILES
from puzzlepress.studio.service import coloring_placements

pdfium = pytest.importorskip("pypdfium2")

BLEED = sorted(p for p in PROFILES if p.endswith("-bleed"))
SCALE = 0.5  # 36 px per inch: enough to see every edge, quick to compare.


def bleed_book(tmp_path: Path, profile: str) -> Path:
    directory = composed_coloring_book(tmp_path / "book", 2, size=(1088, 1463), reverse=False)
    data = load_project(directory).project.to_dict()
    data["print"] = {"profile": profile}
    data["composition"]["page_numbers"]["show_artwork"] = False
    art = [p for p in data["coloring"]["pages"] if "artwork" in p]
    art[0]["placement"] = {"fit": "fill", "scale": 1.3, "x": 0.4, "y": -0.6}
    art[1]["placement"] = {"fit": "fill"}
    (directory / "book.yaml").write_text(
        dump_project(validate_project(data).require_project()), encoding="utf-8"
    )
    return directory


def rect(box: dict[str, float], media_height: float) -> tuple[int, int, int, int]:
    """A PDF box (points, origin bottom-left) as raster pixels (origin top-left)."""
    left = round(box["x"] * SCALE)
    top = round((media_height - box["y"] - box["height"]) * SCALE)
    return left, top, left + round(box["width"] * SCALE), top + round(box["height"] * SCALE)


@pytest.mark.parametrize("profile", BLEED)
def test_the_pdf_shows_exactly_the_crop_studio_previews(tmp_path: Path, profile: str) -> None:
    directory = bleed_book(tmp_path, profile)
    project = load_project(directory).project
    spec = PROFILES[profile]
    content, plan = engine_for(project).build_publication(project, directory)
    preview = coloring_placements(project, content, plan)
    build = build_interior(project, spec, directory)
    reader = PdfReader(io.BytesIO(build.pdf))
    document = pdfium.PdfDocument(build.pdf)
    filled = {int(n): p for n, p in preview.items() if p["fit"] == "fill"}
    assert len(filled) == 2 and {n % 2 for n in filled} == {0, 1}  # A recto and a verso.
    for number, placed in filled.items():
        page = reader.pages[number - 1]
        width, height = spec.trim.width, spec.trim.height
        media_w, media_h = width + KDP.interior_bleed, height + 2 * KDP.interior_bleed
        assert [float(v) for v in page.mediabox] == pytest.approx([0, 0, media_w, media_h])
        assert [float(v) for v in page.bleedbox] == pytest.approx([0, 0, media_w, media_h])
        trim_x = 0.0 if number % 2 else KDP.interior_bleed
        assert [float(v) for v in page.trimbox] == pytest.approx(
            [trim_x, 9.0, trim_x + width, 9.0 + height]
        )
        # What the PDF prints.
        raster = document[number - 1].render(scale=SCALE).to_pil().convert("L")
        # PDFium rounds a half pixel up; everything else is compared within 1 px.
        assert (
            abs(raster.width - media_w * SCALE) <= 1 and abs(raster.height - media_h * SCALE) <= 1
        )
        # What Studio previews: the drawing at its whole extent, clipped to the box.
        art = next(a for a in content.art.values() if a.artwork.id == placed_artwork(plan, number))
        drawing = rect(placed["drawing"], media_h)
        clip = rect(placed["box"], media_h)

        picture = art.image()
        # Inside the clip: the same picture in the same place. PDFium and Pillow
        # resample thin lines differently, so the pictures are compared lightly blurred,
        # and the best alignment must be the preview's own position, within 1 px
        # (1/36 in here); a misplaced crop of 2 px or more fails.
        inner = (clip[0] + 3, clip[1] + 3, clip[2] - 3, clip[3] - 3)
        shown = raster.crop(inner).filter(ImageFilter.BoxBlur(2))
        scores = sorted(
            (
                mean(
                    shown,
                    expected(raster.size, picture, drawing, clip, dx, dy)
                    .crop(inner)
                    .filter(ImageFilter.BoxBlur(2)),
                ),
                dx,
                dy,
            )
            for dx in range(-3, 4)
            for dy in range(-3, 4)
        )
        best, dx, dy = scores[0]
        assert abs(dx) <= 1 and abs(dy) <= 1, (profile, number, scores[:3])
        assert best < 4, (profile, number, best)
        # Outside the clip (the gutter strip on the binding side): nothing printed.
        gutter = (
            (0, 0, clip[0] - 1, raster.height)
            if number % 2
            else (
                clip[2] + 1,
                0,
                raster.width,
                raster.height,
            )
        )
        if gutter[2] > gutter[0]:
            assert raster.crop(gutter).getextrema()[0] >= 250, (profile, number)
        # The fill box reaches the bleed edges: top, bottom and outside.
        assert clip[1] == 0 and abs(clip[3] - raster.height) <= 1
        assert abs(clip[2] - raster.width) <= 1 if number % 2 else clip[0] == 0


def expected(
    size: tuple[int, int],
    picture: Image.Image,
    drawing: tuple[int, int, int, int],
    clip: tuple[int, int, int, int],
    dx: int = 0,
    dy: int = 0,
) -> Image.Image:
    """Studio's preview as a raster: the drawing at its whole extent, clipped."""
    canvas = Image.new("L", size, 255)
    layer = Image.new("L", size, 255)
    scaled = picture.resize(
        (drawing[2] - drawing[0], drawing[3] - drawing[1]), Image.Resampling.BOX
    )
    layer.paste(scaled, (drawing[0] + dx, drawing[1] + dy))
    mask = Image.new("L", size, 0)
    mask.paste(255, clip)
    canvas.paste(layer, (0, 0), mask)
    return canvas


def mean(a: Image.Image, b: Image.Image) -> float:
    histogram = ImageChops.difference(a, b).histogram()
    return sum(v * c for v, c in enumerate(histogram)) / max(1, sum(histogram))


def placed_artwork(plan: object, number: int) -> str:
    page = next(p for p in plan.pages if p.index == number)  # type: ignore[attr-defined]
    return str(page.artwork.id)
