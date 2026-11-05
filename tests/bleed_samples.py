"""Contact sheet of full-bleed pages for a person to inspect (Interval 10).

    python tests/bleed_samples.py OUTPUT.png [--profiles all|PROFILE ...]

For each bleed profile, a SYNTHETIC two-drawing book with one zoomed, shifted fill
and one plain fill is built; both filled pages (a recto and a verso) are rendered by
PDFium from the PDF bytes and outlined with Python's boxes: trim (red), fill area
(blue), KDP safe area (orange). Nothing is drawn from the browser.
"""

import argparse
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from test_bleed_raster import bleed_book  # noqa: E402

SCALE = 0.4


def sheet(profiles: list[str], output: Path) -> Path:
    import pypdfium2 as pdfium

    from puzzlepress import load_project
    from puzzlepress.engines.registry import engine_for
    from puzzlepress.interior import build_interior
    from puzzlepress.interior.spec import PROFILES
    from puzzlepress.preflight.rules import kdp_safe_area
    from puzzlepress.studio.service import coloring_placements

    tiles: list[tuple[str, Image.Image]] = []
    for profile in profiles:
        with tempfile.TemporaryDirectory() as temporary:
            directory = bleed_book(Path(temporary), profile)
            project = load_project(directory).project
            spec = PROFILES[profile]
            content, plan = engine_for(project).build_publication(project, directory)
            preview = coloring_placements(project, content, plan)
            build = build_interior(project, spec, directory)
            document = pdfium.PdfDocument(build.pdf)
            count = len(PdfReader(io.BytesIO(build.pdf)).pages)
            for number in sorted(int(n) for n, p in preview.items() if p["fit"] == "fill"):
                frame = build.layout.pages[number - 1].frame
                image = document[number - 1].render(scale=SCALE).to_pil().convert("RGB")
                draw = ImageDraw.Draw(image)
                height = frame.media.height

                def box(
                    b: object,
                    color: str,
                    width: int = 2,
                    d: ImageDraw.ImageDraw = draw,
                    height: float = height,
                ) -> None:
                    x, y, w, h = (getattr(b, k) for k in ("x", "y", "width", "height"))
                    d.rectangle(
                        (
                            x * SCALE,
                            (height - y - h) * SCALE,
                            (x + w) * SCALE,
                            (height - y) * SCALE,
                        ),
                        outline=color,
                        width=width,
                    )

                box(frame.trim, "#c0392b")
                placed = preview[str(number)]["box"]
                box(type("B", (), placed)(), "#2c6fbb")
                safe = kdp_safe_area(spec, count, frame.recto, frame.trim)
                if safe:
                    box(safe, "#d68910", 1)
                side = "recto" if frame.recto else "verso"
                tiles.append((f"{profile} p{number} {side}", image))
    rows = [tiles[i : i + 4] for i in range(0, len(tiles), 4)]
    width = max(sum(t.width for _, t in row) + 10 * (len(row) + 1) for row in rows)
    height = sum(max(t.height for _, t in row) + 30 for row in rows) + 10
    out = Image.new("RGB", (width, height), "#e8e6df")
    draw = ImageDraw.Draw(out)
    y = 10
    for row in rows:
        x = 10
        for label, tile in row:
            draw.text((x, y), label, fill="#222222")
            out.paste(tile, (x, y + 16))
            x += tile.width + 10
        y += max(t.height for _, t in row) + 30
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(output, optimize=True)
    return output


def main(argv: list[str] | None = None) -> None:
    from puzzlepress.interior.spec import PROFILES

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--profiles", nargs="*", default=["all"])
    args = parser.parse_args(argv)
    profiles = (
        sorted(p for p in PROFILES if p.endswith("-bleed"))
        if args.profiles == ["all"]
        else args.profiles
    )
    print(sheet(profiles, args.output))


if __name__ == "__main__":
    main()
