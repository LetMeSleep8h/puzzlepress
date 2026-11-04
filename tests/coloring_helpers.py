"""SYNTHETIC line art and coloring books for engine tests and browser acceptance.

Every drawing is generated here from a seed: black outlines of ellipses, boxes and
polylines on white. Nothing here is authored artwork.
"""

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw

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
