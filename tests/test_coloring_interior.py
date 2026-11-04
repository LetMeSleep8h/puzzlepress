"""Coloring interiors: layout, lossless rendering, identity, writes and determinism.

Every drawing is SYNTHETIC (tests/coloring_helpers.py). Losslessness is proven by
decoding the embedded image streams independently (pypdf + zlib) and comparing
pixels with an independent preparation of the original file, not by appearance.
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import zlib
from dataclasses import replace
from pathlib import Path

import pytest
from coloring_helpers import FULL_SIZE, composed_coloring_book, fine_detail, line_art
from PIL import Image
from pypdf import PdfReader

from puzzlepress import validate_project
from puzzlepress.cli import main
from puzzlepress.coloring.content import ColoringContent
from puzzlepress.coloring.prepare import prepared_pixels
from puzzlepress.coloring_config import Border
from puzzlepress.interior import DEFAULT_PROFILE, InteriorError, build_interior, print_profile
from puzzlepress.interior.build import (
    IDENTITY_INPUTS,
    interior_identity,
    sample_interior,
    write_interior,
)
from puzzlepress.interior.coloring import (
    ART_ROLE,
    art_box,
    embedded_images,
    image_integrity,
    layout_coloring,
    validate_coloring_layout,
    zlib_implementation,
)
from puzzlepress.interior.engine import FOLIO_BAND
from puzzlepress.interior.model import Box, ImageBlock, ImageEncoding, Panel, TextLine
from puzzlepress.interior.render import LosslessImage, render_pdf
from puzzlepress.interior.spec import PrintSpecification
from puzzlepress.project import load_project
from puzzlepress.publication import PageKind

SPEC = print_profile(DEFAULT_PROFILE)
assert isinstance(SPEC, PrintSpecification)
MEDIUM = (1088, 1463)  # Half of a full page: quick, still a real raster.
ROOT = Path(__file__).resolve().parents[1]


def build(directory: Path):
    return build_interior(load_project(directory).project, SPEC, directory)


@pytest.fixture(scope="module")
def simple(tmp_path_factory):
    """Three drawings, title and copyright pages, one divider, reverses on."""
    directory = composed_coloring_book(
        tmp_path_factory.mktemp("simple") / "book",
        3,
        size=MEDIUM,
        dividers={1: "Woodland"},
        border="thin",
    )
    return directory, build(directory)


def art_blocks(layout):
    return [
        (page.number, element)
        for page in layout.pages
        for element in page.elements
        if isinstance(element, ImageBlock)
    ]


# --------------------------------------------------------------------- the book


def test_pages_follow_the_plan_and_art_is_recto(simple):
    _, built = simple
    kinds = [page.kind for page in built.layout.pages]
    assert kinds == [
        "title_page",
        "copyright_page",
        "coloring",
        "blank",
        "divider",
        "blank",
        "coloring",
        "blank",
        "coloring",
        "blank",
    ]
    assert [n for n, _ in art_blocks(built.layout)] == [3, 7, 9]
    for page in built.layout.pages:
        if page.kind == "blank":
            assert page.elements == ()
    reader = PdfReader(io.BytesIO(built.pdf))
    assert len(reader.pages) == len(built.plan.pages) == built.manifest["page_count"]
    for page in reader.pages:
        assert [round(float(v), 3) for v in page.mediabox] == [0, 0, 612, 792]
        assert [round(float(v), 3) for v in page.trimbox] == [0, 0, 612, 792]


def test_page_numbers_print_only_where_the_plan_shows_them(simple):
    _, built = simple
    for page, entry in zip(built.layout.pages, built.plan.pages, strict=True):
        folios = [e.text for e in page.elements if isinstance(e, TextLine) and e.role == "folio"]
        assert folios == ([entry.number.label] if entry.number.displayed else [])
    assert [p.folio for p in built.layout.pages] == [
        None, None, "3", None, None, None, "7", None, "9", None
    ]  # fmt: skip


def test_art_is_whole_centred_and_uniformly_scaled_inside_its_box(simple):
    _, built = simple
    for number, block in art_blocks(built.layout):
        page = built.layout.pages[number - 1]
        content = page.frame.content
        body = Box(content.x, content.y + FOLIO_BAND, content.width, content.height - FOLIO_BAND)
        region = art_box(body, Border.THIN)
        assert block.box == block.placement  # Never clipped.
        assert region.contains(block.placement, 0.01)
        assert block.pixels == (0, 0, *MEDIUM)
        assert block.encoding is ImageEncoding.LOSSLESS
        ratio = block.placement.width / block.placement.height
        assert ratio == pytest.approx(MEDIUM[0] / MEDIUM[1], rel=1e-9)
        # Fills the box on its limiting side and is centred on the other.
        assert block.placement.height == pytest.approx(region.height)
        left = block.placement.x - region.x
        assert left == pytest.approx(region.right - block.placement.right)
        assert block.effective_dpi == pytest.approx(MEDIUM[1] / (region.height / 72))


def test_borders_frame_the_art_without_touching_it(tmp_path):
    for border, strokes in ((Border.THIN, [1.0]), (Border.DOUBLE, [1.5, 0.75])):
        directory = composed_coloring_book(tmp_path / border.value, 1, border=border.value)
        built = build(directory)
        page = built.layout.pages[2]
        frames = [e for e in page.elements if isinstance(e, Panel)]
        assert [f.stroke_width for f in frames] == strokes
        assert all(f.fill_gray is None and f.stroke_gray == 0.0 for f in frames)
        (block,) = [e for e in page.elements if isinstance(e, ImageBlock)]
        innermost = frames[-1]
        # Inside the innermost stroke's inner edge, with padding to spare.
        inner = innermost.box.expanded(-innermost.stroke_width / 2 - 12)
        assert inner.contains(block.placement, 1e-6)
        # Every stroke's painted extent stays inside the live area.
        assert all(page.frame.content.contains(f.bounds, 0.01) for f in frames)


def test_full_page_art_measures_its_effective_dpi(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1, images=[line_art(1, FULL_SIZE)])
    built = build(directory)
    ((_, block),) = art_blocks(built.layout)
    # 2175 x 2925 px fitted to 7.25 x 9.4167 in (the live area above the number band).
    assert block.effective_dpi == pytest.approx(2925 / ((702 - FOLIO_BAND) / 72))
    assert round(block.effective_dpi) == 311


# ------------------------------------------------------------------- losslessness


def decoded_pages(pdf: bytes) -> dict[int, Image.Image]:
    """Independent decode: pypdf stream bytes, zlib, and the stated pixel format."""
    reader = PdfReader(io.BytesIO(pdf), strict=True)
    found: dict[int, Image.Image] = {}
    for number, page in enumerate(reader.pages, start=1):
        xobjects = page["/Resources"].get("/XObject")
        if xobjects is None:
            continue
        ((_, ref),) = xobjects.get_object().items()
        stream = ref.get_object()
        assert stream["/Filter"] == ["/FlateDecode"]
        assert stream["/ColorSpace"] == "/DeviceGray"
        assert "/DecodeParms" not in stream and "/SMask" not in stream
        assert not stream.get("/Interpolate", False)
        size = (int(stream["/Width"]), int(stream["/Height"]))
        raw = zlib.decompress(stream._data)
        mode = "1" if stream["/BitsPerComponent"] == 1 else "L"
        assert stream["/BitsPerComponent"] in (1, 8)
        found[number] = Image.frombytes(mode, size, raw).convert("L")
    return found


@pytest.mark.parametrize(
    ("adjust", "bits"),
    [({}, 8), ({"threshold": 0.5}, 1), ({"line_weight": 1, "contrast": 1.4}, 8)],
)
def test_embedded_pixels_equal_an_independent_preparation(tmp_path, adjust, bits):
    original = line_art(7, MEDIUM)
    original.putpixel((10, 10), 140)  # A gray level: thresholding must remove it.
    directory = composed_coloring_book(tmp_path / "book", 1, images=[original])
    project = load_project(directory).project
    data = project.to_dict()
    data["coloring"]["artwork"][0]["adjustments"].update(adjust)
    project = validate_project(data).require_project()
    built = build_interior(project, SPEC, directory)
    assert project.coloring is not None
    (artwork,) = project.coloring.artwork
    expected = prepared_pixels((directory / artwork.path).read_bytes(), artwork.adjustments)
    pages = decoded_pages(built.pdf)
    assert list(pages) == [3]
    assert pages[3].size == expected.size
    assert pages[3].tobytes() == expected.tobytes()
    assert built.manifest["artwork"][0]["bits"] == bits
    assert b"/DCTDecode" not in built.pdf


def test_thin_lines_survive_rendering_pixel_for_pixel(tmp_path):
    drawing = fine_detail()
    directory = composed_coloring_book(tmp_path / "book", 1, images=[drawing])
    built = build(directory)
    (embedded,) = decoded_pages(built.pdf).values()
    assert embedded.tobytes() == drawing.convert("L").tobytes()
    # And the rasterized page still shows the one-pixel lines (no smoothing away).
    pdfium = pytest.importorskip("pypdfium2")
    document = pdfium.PdfDocument(built.pdf)
    ((_, block),) = art_blocks(built.layout)
    scale = block.effective_dpi / 72
    raster = document[2].render(scale=scale, grayscale=True).to_pil().convert("L")
    x0 = round(block.placement.x * scale)
    y0 = round((792 - block.placement.top) * scale)
    art = raster.crop((x0, y0, x0 + drawing.width, y0 + drawing.height))
    original_ink = sum(
        drawing.convert("L").point(lambda v: 255 if v <= 128 else 0).histogram()[255:]
    )
    rendered_ink = sum(art.point(lambda v: 255 if v <= 160 else 0).histogram()[255:])
    assert rendered_ink >= 0.9 * original_ink


def test_two_level_art_is_packed_at_one_bit(tmp_path):
    bilevel = line_art(2, MEDIUM)  # line_art draws pure black on pure white.
    directory = composed_coloring_book(tmp_path / "book", 1, images=[bilevel])
    built = build(directory)
    (record,) = built.manifest["artwork"]
    assert record["bits"] == 1
    assert decoded_pages(built.pdf)[3].tobytes() == bilevel.tobytes()


def test_original_artwork_is_never_modified(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 2)
    before = {p.name: p.read_bytes() for p in (directory / "coloring-assets").iterdir()}
    build(directory)
    after = {p.name: p.read_bytes() for p in (directory / "coloring-assets").iterdir()}
    assert before == after


def test_image_integrity_detects_wrong_pixels_and_lossy_images(simple):
    _, built = simple
    content = built.report
    assert isinstance(content, ColoringContent)
    images = embedded_images(built.pdf)
    assert isinstance(images, tuple) and len(images) == 3
    assert image_integrity(images, built.layout, content) == ()
    first = images[0]
    codes = [
        i.code
        for i in image_integrity(
            (replace(first, digest="sha256-0"), *images[1:]), built.layout, content
        )
    ]
    assert codes == ["pdf_image_pixels"]
    lossy = replace(first, filters=("/DCTDecode",))
    assert [i.code for i in image_integrity((lossy, *images[1:]), built.layout, content)] == [
        "pdf_image_lossy"
    ]
    resampled = replace(first, width=first.width // 2)
    assert [i.code for i in image_integrity((resampled, *images[1:]), built.layout, content)] == [
        "pdf_image_resampled"
    ]
    assert [i.code for i in image_integrity(images[1:], built.layout, content)] == ["pdf_images"]


# --------------------------------------------------------- validation and rejects


def test_layout_validation_catches_clipping_distortion_and_strays(simple):
    _, built = simple
    content = built.report
    layout, plan = built.layout, built.plan
    assert isinstance(content, ColoringContent)
    assert validate_coloring_layout(layout, plan, content, Border.THIN) == ()
    number, block = art_blocks(layout)[0]
    page = layout.pages[number - 1]

    def with_block(changed: ImageBlock):
        elements = tuple(changed if e is block else e for e in page.elements)
        pages = tuple(replace(page, elements=elements) if p is page else p for p in layout.pages)
        return [
            i.code
            for i in validate_coloring_layout(
                replace(layout, pages=pages), plan, content, Border.THIN
            )
        ]

    shrunk = Box(block.box.x, block.box.y, block.box.width / 2, block.box.height)
    assert "artwork_clipped" in with_block(replace(block, box=shrunk))
    wide = replace(block.placement, width=block.placement.width * 1.2)
    assert "artwork_distorted" in with_block(replace(block, placement=wide, box=wide))
    moved = replace(block.placement, x=block.placement.x + 200)
    assert "artwork_outside_box" in with_block(replace(block, placement=moved, box=moved))
    assert "artwork_content" in with_block(replace(block, encoding=ImageEncoding.JPEG))
    assert "artwork_content" in with_block(replace(block, sha256="sha256-0"))
    assert "border_mismatch" in [
        i.code for i in validate_coloring_layout(layout, plan, content, Border.DOUBLE)
    ]


def test_unsupported_page_kinds_fail_explicitly(simple):
    _, built = simple
    content = built.report
    assert isinstance(content, ColoringContent)
    pages = list(built.plan.pages)
    pages[0] = replace(pages[0], kind=PageKind.PUZZLE)
    with pytest.raises(InteriorError) as raised:
        layout_coloring(replace(built.plan, pages=tuple(pages)), content, SPEC, Border.NONE)
    assert [i.code for i in raised.value.issues] == ["unsupported_page_type"]


def test_unknown_elements_and_wrong_encodings_never_render(simple):
    _, built = simple
    layout = built.layout
    page = layout.pages[0]

    class Stray:
        role = "stray"

    odd = replace(layout, pages=(replace(page, elements=(Stray(),)),))
    with pytest.raises(ValueError, match="Unsupported layout element"):
        render_pdf(odd)
    number, block = art_blocks(layout)[0]
    art_page = layout.pages[number - 1]
    one = replace(layout, pages=(replace(art_page, number=1),))
    with pytest.raises(ValueError, match="lossless"):
        render_pdf(one, {(1, ART_ROLE): (b"jpeg", (1, 1))})
    jpeg_block = replace(block, encoding=ImageEncoding.JPEG)
    jpeg = replace(layout, pages=(replace(art_page, number=1, elements=(jpeg_block,)),))
    with pytest.raises(ValueError, match="JPEG"):
        render_pdf(jpeg, {(1, ART_ROLE): LosslessImage(b"", (1, 1), 8)})


def test_unbound_or_missing_art_fails_before_rendering(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 2)
    project = load_project(directory).project
    assert project.coloring is not None
    (directory / project.coloring.artwork[1].path).unlink()
    with pytest.raises(InteriorError) as raised:
        build_interior(project, SPEC, directory)
    assert raised.value.stage == "integrity"
    assert [i.code for i in raised.value.issues] == ["incomplete_plan", "missing_artwork"]


def test_empty_and_uncomposed_books_fail_with_actionable_errors(tmp_path, capsys):
    empty = composed_coloring_book(tmp_path / "empty", 0)
    assert main(["book", "build", str(empty), "--output", str(tmp_path / "out")]) == 1
    err = capsys.readouterr().err
    assert "no interior was written" in err and "no_coloring_pages" in err
    assert not (tmp_path / "out").exists()
    uncomposed = composed_coloring_book(tmp_path / "uncomposed", 1)
    data = load_project(uncomposed).project.to_dict()
    del data["composition"]
    (uncomposed / "book.yaml").write_text(
        __import__("puzzlepress").dump_project(validate_project(data).require_project()),
        encoding="utf-8",
    )
    assert main(["book", "build", str(uncomposed), "--output", str(tmp_path / "out")]) == 1
    assert "composition [required]" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_bleed_profiles_are_rejected(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1)
    project = load_project(directory).project
    with pytest.raises(InteriorError) as raised:
        build_interior(project, replace(SPEC, bleed=True), directory)
    assert raised.value.stage == "print_spec"


# ------------------------------------------------------------ identity and output


def test_manifest_records_identity_inputs_and_environment(simple):
    _, built = simple
    manifest = built.manifest
    assert manifest["engine"] == "coloring"
    coloring = manifest["coloring"]
    assert coloring == {
        "renderer_version": 1,
        "preparation_version": 1,
        "image_library": f"pillow {Image.__version__}",
        "zlib": zlib_implementation(),
    }
    environment = manifest["environment"]
    assert set(environment) == {"python", "pillow", "reportlab", "pypdf", "zlib_runtime"}
    assert manifest["interior_identity"] == interior_identity(manifest)
    without = {k: v for k, v in manifest.items() if k != "coloring"}
    assert interior_identity(without) != manifest["interior_identity"]
    pages = [record["page"] for record in manifest["artwork"]]
    assert pages == [3, 7, 9]
    for record in manifest["artwork"]:
        assert record["prepared"].startswith("sha256-")
        assert record["source_sha256"] and record["pixels"] == list(MEDIUM)
    assert manifest["composition"]["artwork_pages"] == 3
    assert manifest["pdf"]["sha256"] == hashlib.sha256(built.pdf).hexdigest()


def test_word_search_manifests_gain_no_coloring_fields():
    project = load_project(ROOT / "books" / "composition-demo").project
    manifest = build_interior(project, SPEC).manifest
    assert not {"engine", "coloring", "environment", "artwork", "composition"} & set(manifest)
    assert set(IDENTITY_INPUTS) <= set(manifest)


def test_rebuilds_are_byte_identical_in_process_and_across_processes(simple, tmp_path):
    directory, built = simple
    again = build(directory)
    assert again.pdf == built.pdf and again.manifest == built.manifest
    script = (
        "import sys, hashlib; from pathlib import Path; "
        "from puzzlepress.interior import build_interior, print_profile; "
        "from puzzlepress.project import load_project; "
        "d = Path(sys.argv[1]); "
        "b = build_interior(load_project(d).project, print_profile('paperback-8.5x11'), d); "
        "print(hashlib.sha256(b.pdf).hexdigest())"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(directory)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "7"},
    )
    assert result.stdout.strip() == hashlib.sha256(built.pdf).hexdigest()


def test_setting_and_source_changes_change_identity_and_bytes(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1, size=MEDIUM)
    first = build(directory)
    project = load_project(directory).project
    data = project.to_dict()
    data["coloring"]["artwork"][0]["adjustments"]["line_weight"] = 1
    changed = build_interior(validate_project(data).require_project(), SPEC, directory)
    assert changed.manifest["interior_identity"] != first.manifest["interior_identity"]
    assert changed.manifest["identity"] != first.manifest["identity"]
    assert changed.pdf != first.pdf
    # Turning page numbers off changes the folio, never the art's placement.
    data = project.to_dict()
    data["composition"]["page_numbers"]["show_artwork"] = False
    quiet = build_interior(validate_project(data).require_project(), SPEC, directory)
    assert art_blocks(quiet.layout) == art_blocks(first.layout)
    assert quiet.layout.pages[2].folio is None and first.layout.pages[2].folio == "3"


def test_write_is_atomic_and_cleans_up_after_failures(simple, tmp_path, monkeypatch):
    directory, built = simple
    output = tmp_path / "out"
    written = write_interior(built, output, directory)
    assert written.pdf.read_bytes() == built.pdf
    assert (
        json.loads(written.manifest.read_text())["interior_identity"]
        == (built.manifest["interior_identity"])
    )

    def fail(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    changed = replace(built, pdf=b"%PDF-new", manifest={**built.manifest, "page_count": 0})
    with pytest.raises(InteriorError) as raised:
        write_interior(changed, output, directory)
    assert raised.value.issues[0].code == "write_failed"
    assert written.pdf.read_bytes() == built.pdf
    assert sorted(p.name for p in output.iterdir()) == ["interior.json", "interior.pdf"]


def test_concurrent_builds_write_one_consistent_interior(simple, tmp_path):
    directory, built = simple
    output = tmp_path / "out"
    errors: list[BaseException] = []

    def run() -> None:
        try:
            write_interior(build(directory), output, directory)
        except BaseException as error:  # Reported below; a failure must be clean.
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(isinstance(e, InteriorError) for e in errors)
    pdf = (output / "interior.pdf").read_bytes()
    manifest = json.loads((output / "interior.json").read_text())
    assert pdf == built.pdf
    assert manifest["pdf"]["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert sorted(p.name for p in output.iterdir()) == ["interior.json", "interior.pdf"]


def test_book_build_cli_writes_a_verified_coloring_interior(simple, tmp_path, capsys):
    directory, built = simple
    output = tmp_path / "cli"
    assert main(["book", "build", str(directory), "--output", str(output), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert (output / "interior.pdf").read_bytes() == built.pdf
    assert payload["manifest"]["engine"] == "coloring"


def test_sample_draws_representative_coloring_pages(simple):
    directory, built = simple
    sample = sample_interior(load_project(directory).project, SPEC, directory)
    assert sample.page_count == len(built.layout.pages)
    roles = {page.physical_page: page.roles for page in sample.pages}
    assert roles == {1: ("title",), 3: ("coloring",), 4: ("reverse_blank",), 5: ("divider",)}
    assert len(PdfReader(io.BytesIO(sample.pdf)).pages) == 4
