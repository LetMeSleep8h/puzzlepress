"""Faint drawings on tinted paper are reported as faint, never as blank (Interval 7).

The real-artwork review found a chalk drawing on gray-190 paper reported as "blank or
almost white". These SYNTHETIC images reproduce that case without real artwork.
"""

from coloring_helpers import encode
from PIL import Image, ImageDraw

from puzzlepress.coloring.inspection import inspect_artwork
from puzzlepress.coloring.prepare import prepare_artwork
from puzzlepress.coloring_config import Adjustments


def faint_on_tinted(paper: int, stroke: int) -> bytes:
    image = Image.new("L", (1200, 1600), paper)
    draw = ImageDraw.Draw(image)
    for i in range(0, 1100, 60):
        draw.line((50 + i, 100, 120 + i, 1500), fill=stroke, width=4)
    return encode(image)


def test_a_faint_drawing_on_tinted_paper_is_called_faint() -> None:
    data = faint_on_tinted(190, 165)
    empty = next(f for f in inspect_artwork(data).findings if f.code == "artwork_empty")
    assert "too faint to print as ink" in empty.message and "blank" not in empty.message
    blank = next(
        f for f in prepare_artwork(data, Adjustments()).findings if f.code == "prepared_blank"
    )
    assert "pale gray" in blank.message and "colored" not in blank.message


def test_a_white_page_is_still_called_blank() -> None:
    data = faint_on_tinted(255, 255)
    empty = next(f for f in inspect_artwork(data).findings if f.code == "artwork_empty")
    assert "blank or almost white" in empty.message
