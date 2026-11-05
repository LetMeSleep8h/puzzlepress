"""Contact sheet of an artwork review: original | prepared | difference per drawing.

    python tests/artwork_contact_sheet.py REVIEW_DIR OUTPUT.png

Reads the images and measures.json that `artwork_review.py` wrote for each drawing
and lays out one row per drawing, captioned with its measured fine-line and
light-stroke retention and its preparation findings. For a person to look at; it
decides nothing. Real artwork stays outside the repository, so OUTPUT belongs
beside the review, not in docs/.
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None
TILE = 260


def _thumb(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image.thumbnail((TILE, TILE), Image.Resampling.BOX)
    canvas = Image.new("RGB", (TILE, TILE), "#ffffff")
    canvas.paste(image, ((TILE - image.width) // 2, (TILE - image.height) // 2))
    return canvas


def sheet(review: Path, output: Path) -> Path:
    rows: list[tuple[str, list[Image.Image], str]] = []
    for folder in sorted(p for p in review.iterdir() if (p / "measures.json").is_file()):
        record = json.loads((folder / "measures.json").read_text(encoding="utf-8"))
        if "refused" in record:
            rows.append((folder.name, [], f"refused: {record['refused']['code']}"))
            continue
        measures = record["preparation"]["measures"]
        codes = [f["code"] for f in record["preparation"]["findings"]]
        caption = (
            f"fine lines {measures['thin_line_retention']}  light strokes "
            f"{measures['faint_line_retention']}  | {', '.join(codes) or 'no findings'}"
        )
        tiles = [
            _thumb(folder / name) for name in ("original.png", "prepared.png", "difference.png")
        ]
        rows.append((folder.name, tiles, caption))
    width = 3 * TILE + 40
    height = sum((TILE if tiles else 0) + 40 for _, tiles, _ in rows) + 10
    out = Image.new("RGB", (width, height), "#ecebe6")
    draw = ImageDraw.Draw(out)
    y = 10
    for name, tiles, caption in rows:
        draw.text((10, y), f"{name}: {caption}", fill="#1d1d1d")
        y += 18
        for index, tile in enumerate(tiles):
            out.paste(tile, (10 + index * (TILE + 10), y))
        y += (TILE if tiles else 0) + 22
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(output, optimize=True)
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("review", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    sys.stdout.write(f"{sheet(args.review, args.output)}\n")


if __name__ == "__main__":
    main()
