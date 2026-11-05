"""SYNTHETIC line art and coloring books for engine tests and browser acceptance.

Every drawing is generated here from a seed: black outlines of ellipses, boxes and
polylines on white. Nothing here is authored artwork.
"""

import io
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from puzzlepress import dump_project, validate_project

# 7.25 x 9.75 in at 300 DPI: the default profile's live area.
FULL_SIZE = (2175, 2925)


def line_art(
    seed: int,
    size: tuple[int, int] = FULL_SIZE,
    mode: str = "L",
    line: int = 0,
    background: int | tuple[int, ...] = 255,
) -> Image.Image:
    """A deterministic outline drawing: a few closed shapes and two polylines."""
    rng = random.Random(seed)
    width, height = size
    image = Image.new(mode, size, background)
    draw = ImageDraw.Draw(image)
    stroke = line or max(2, round(min(size) / 240))
    ink = (0, 0, 0, 255)[: len(image.getbands())] if mode != "L" and mode != "1" else 0
    margin = round(min(size) * 0.08)
    for _ in range(5):
        x0 = rng.randrange(margin, width // 2)
        y0 = rng.randrange(margin, height // 2)
        x1 = rng.randrange(x0 + width // 8, width - margin)
        y1 = rng.randrange(y0 + height // 8, height - margin)
        if rng.random() < 0.5:
            draw.ellipse((x0, y0, x1, y1), outline=ink, width=stroke)
        else:
            draw.rectangle((x0, y0, x1, y1), outline=ink, width=stroke)
    for _ in range(2):
        points = [
            (rng.randrange(margin, width - margin), rng.randrange(margin, height - margin))
            for _ in range(6)
        ]
        draw.line(points, fill=ink, width=stroke)
    return image


def encode(image: Image.Image, kind: str = "PNG", **options: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=kind, **options)
    return buffer.getvalue()


def png(seed: int, **options: object) -> bytes:
    return encode(line_art(seed, **options))  # type: ignore[arg-type]


def coloring_source(book_id: str = "synthetic-coloring-book") -> dict[str, object]:
    return {
        "schema_version": 1,
        "book": {"id": book_id, "title": "Synthetic Coloring Book", "language": "en"},
        "build": {"seed": 1},
        "coloring": {"version": 1},
    }


def write_coloring_book(directory: Path, source: dict[str, object] | None = None) -> Path:
    """An empty coloring book (no artwork yet) in `directory`; returns its folder."""
    directory.mkdir(parents=True, exist_ok=True)
    project = validate_project(source or coloring_source()).require_project()
    (directory / "book.yaml").write_text(dump_project(project), encoding="utf-8")
    return directory


def write_artwork_files(directory: Path, seeds: list[int]) -> list[Path]:
    """PNG files of the given drawings, named art-<seed>.png, outside any project."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for seed in seeds:
        path = directory / f"art-{seed}.png"
        path.write_bytes(png(seed))
        paths.append(path)
    return paths


# ---------------------------------------------------------------- calibration fixtures
# Each is SYNTHETIC and drawn at full page size (2175 x 2925, 300 DPI over the live
# area) so measured widths are the widths a printed page would have.


def fine_detail(size: tuple[int, int] = FULL_SIZE) -> Image.Image:
    """Known widths: horizontal rules of 1, 2, 3 and 6 px, one- and two-pixel circles,
    glyph-like zigzags with 2 px strokes and a 1 px crosshatch."""
    width, height = size
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    y = 120
    for stroke in (1, 2, 3, 6):
        for _ in range(6):
            draw.line([(150, y), (width - 150, y)], fill=0, width=stroke)
            y += 28
        y += 40
    for index, radius in enumerate(range(80, 400, 40)):
        draw.ellipse(
            (width // 2 - radius, 1500 - radius, width // 2 + radius, 1500 + radius),
            outline=0,
            width=1 + index % 2,
        )
    for row in range(4):
        for column in range(24):
            x0, y0 = 150 + column * 78, 2050 + row * 70
            draw.line([(x0, y0 + 40), (x0 + 12, y0), (x0 + 24, y0 + 40), (x0 + 36, y0)], 0, 2)
    for offset in range(0, 600, 6):
        draw.line([(150 + offset, 2400), (150 + offset, 2800)], fill=0, width=1)
        draw.line([(150, 2400 + offset * 400 // 600), (750, 2400 + offset * 400 // 600)], 0, 1)
    return image


def dense_pattern(size: tuple[int, int] = FULL_SIZE) -> Image.Image:
    """A mandala-like page with a lot of ink: rings every 18 px and 72 spokes."""
    import math

    width, height = size
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    cx, cy = width // 2, height // 2
    for radius in range(30, min(width, height) // 2 - 40, 18):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=0, width=6)
    for spoke in range(72):
        angle = spoke * math.pi / 36
        end = (cx + math.cos(angle) * 1050, cy + math.sin(angle) * 1050)
        draw.line([(cx, cy), end], fill=0, width=5)
    return image


def noisy_scan(seed: int, size: tuple[int, int] = FULL_SIZE) -> Image.Image:
    """Line art on gray, grainy paper (level 214-234) with scattered specks."""
    rng = random.Random(seed)
    width, height = size
    noise = Image.frombytes("L", size, rng.randbytes(width * height)).point(lambda v: v * 20 // 255)
    paper = ImageChops.add(Image.new("L", size, 214), noise)
    image = ImageChops.darker(line_art(seed, size), paper)
    draw = ImageDraw.Draw(image)
    for _ in range(400):
        x, y, r = rng.randrange(width), rng.randrange(height), rng.choice((0, 1, 1, 2))
        draw.ellipse((x - r, y - r, x + r, y + r), fill=40)
    return image


def aged_scan(
    paper: int = 226,
    *,
    ink: int = 70,
    blur: float = 0.8,
    grain: int = 14,
    gradient: int = 0,
    art: Image.Image | None = None,
    seed: int = 3,
) -> Image.Image:
    """A scan-like page in the manner of the Interval 7 patent-drawing scans: the line
    art (default `fine_detail`) inked at `ink` rather than black, blurred over its rim
    as a scanner does, multiplied onto grainy paper of level `paper`, optionally
    darkening by `gradient` levels from top to bottom (uneven aging)."""
    from PIL import ImageFilter

    lines = (art if art is not None else fine_detail()).convert("L")
    size = lines.size
    lines = lines.point(lambda v: ink + (255 - ink) * v // 255)
    lines = lines.filter(ImageFilter.GaussianBlur(blur)) if blur else lines
    rng = random.Random(seed)
    width, height = size
    noise = Image.frombytes("L", size, rng.randbytes(width * height))
    noise = noise.point(lambda v: v * grain // 255)
    base = Image.new("L", size, paper - grain // 2)
    if gradient:
        ramp = Image.linear_gradient("L").resize(size).point(lambda v: v * gradient // 255)
        base = ImageChops.subtract(base, ramp)
    return ImageChops.multiply(lines, ImageChops.add(base, noise))


def white_on_black(seed: int, size: tuple[int, int] = FULL_SIZE) -> Image.Image:
    return ImageChops.invert(line_art(seed, size))


def transparent_art(seed: int, size: tuple[int, int] = FULL_SIZE) -> Image.Image:
    """Black outlines on a fully transparent background (RGBA)."""
    lines = line_art(seed, size)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.putalpha(ImageChops.invert(lines))
    return image


def light_colored_lines(seed: int, size: tuple[int, int] = FULL_SIZE) -> Image.Image:
    """Yellow outlines on white: nearly invisible in luma."""
    lines = line_art(seed, size)
    image = Image.new("RGB", size, (255, 255, 255))
    image.paste((240, 220, 0), mask=ImageChops.invert(lines))
    return image


def pencil_sketch(seed: int, size: tuple[int, int] = FULL_SIZE) -> Image.Image:
    """Soft, light line work: the fine-detail page drawn in gray (level 96) at twice the
    size and reduced, so strokes have anti-aliased edges, on slightly warm paper (246)."""
    width, height = size
    big = fine_detail((width * 2, height * 2)).point(lambda v: 96 if v < 128 else 246)
    del seed  # One layout; the parameter keeps the fixture signature uniform.
    return big.resize(size, Image.Resampling.BOX)


# ------------------------------------------------------------- composed coloring books

SMALL_SIZE = (300, 400)  # Small SYNTHETIC drawings keep plan and layout tests quick.
FRONT_MATTER = (
    {"kind": "title_page"},
    {"kind": "copyright_page", "text": "Copyright 2026 Synthetic Author. All rights reserved."},
    {"kind": "instructions", "title": "How to use this book", "text": "Color one page a day."},
)


def composed_coloring_book(
    directory: Path,
    count: int,
    *,
    front: int = 2,
    reverse: bool = True,
    start: str = "recto",
    dividers: dict[int, str] | None = None,
    size: tuple[int, int] = SMALL_SIZE,
    images: list[Image.Image] | None = None,
    border: str = "none",
    numbers: dict[str, object] | None = None,
    back: list[dict[str, object]] | None = None,
) -> Path:
    """A SYNTHETIC coloring book with `count` drawings and a coloring composition.

    `dividers` maps a 0-based drawing position to a divider title placed before it.
    Drawings are imported through the library, so files are real, content-addressed
    project assets.
    """
    from puzzlepress.coloring.library import import_files
    from puzzlepress.project import load_project

    write_coloring_book(directory)
    drawings = images or [line_art(seed, size) for seed in range(count)]
    if drawings:
        import_files(
            directory, [(f"drawing {i + 1}.png", encode(d)) for i, d in enumerate(drawings)]
        )
    data = load_project(directory).project.to_dict()
    pages: list[object] = []
    for position, page in enumerate(data["coloring"]["pages"]):  # type: ignore[index]
        if dividers and position in dividers:
            pages.append({"divider": {"title": dividers[position]}})
        pages.append(page)
    coloring = data["coloring"]
    assert isinstance(coloring, dict)
    coloring["pages"] = pages
    coloring["layout"] = {"blank_reverse": reverse, "border": border}
    data["composition"] = {
        "front_matter": list(FRONT_MATTER[:front]),
        "artwork": {"start": start},
        "back_matter": back or [],
        "page_numbers": numbers or {},
    }
    project = validate_project(data).require_project()
    (directory / "book.yaml").write_text(dump_project(project), encoding="utf-8")
    return directory
