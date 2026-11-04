"""Line-art preparation: pipeline, measures and findings, cache keys, settings, CLI."""

import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from puzzlepress import dump_project, load_project, validate_project
from puzzlepress.coloring import components, prepare
from puzzlepress.coloring.issues import ArtworkError
from puzzlepress.coloring.library import (
    adjust_artwork,
    import_files,
    prepare_entry,
    with_adjustments,
)
from puzzlepress.coloring.prepare import (
    PREPARATION_VERSION,
    cache_key,
    difference_image,
    prepare_artwork,
    preview_png,
)
from puzzlepress.coloring_config import Adjustments
from puzzlepress.coloring_validation import validate_adjustments
from puzzlepress.errors import ProjectError
from tests.coloring_helpers import (
    dense_pattern,
    encode,
    fine_detail,
    light_colored_lines,
    line_art,
    noisy_scan,
    pencil_sketch,
    png,
    transparent_art,
    white_on_black,
    write_coloring_book,
)

ROOT = Path(__file__).resolve().parents[1]


def codes(prepared) -> list[str]:
    return [finding.code for finding in prepared.findings]


def severity(prepared, code: str) -> str:
    return next(f.severity.value for f in prepared.findings if f.code == code)


@pytest.fixture(scope="module")
def fine() -> bytes:
    return encode(fine_detail())


# ---------------------------------------------------------------- pipeline


def test_defaults_return_the_original_gray_levels_exactly():
    image = line_art(1)
    prepared = prepare_artwork(encode(image), Adjustments())
    assert prepared.image.tobytes() == image.tobytes()
    assert prepared.findings == () and prepared.measures.mean_change == 0


def test_identical_inputs_give_identical_pixels_and_keys(fine):
    first = prepare_artwork(fine, Adjustments(line_weight=1, background_cleanup=0.5))
    second = prepare_artwork(fine, Adjustments(line_weight=1, background_cleanup=0.5))
    assert first.key == second.key
    assert first.image.tobytes() == second.image.tobytes()
    assert first.to_dict() == second.to_dict()


def test_preparation_is_deterministic_across_processes(tmp_path):
    source = tmp_path / "art.png"
    source.write_bytes(encode(noisy_scan(2, size=(800, 1000))))
    script = (
        "import sys, hashlib; from pathlib import Path; "
        "from puzzlepress.coloring.prepare import prepare_artwork; "
        "from puzzlepress.coloring_config import Adjustments as A; "
        "p = prepare_artwork(Path(sys.argv[1]).read_bytes(), "
        "A(despeckle=3, background_cleanup=0.6, threshold=0.5, line_weight=1)); "
        "print(p.key, hashlib.sha256(p.image.tobytes()).hexdigest(), p.to_dict())"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script, str(source)],
            capture_output=True,
            text=True,
            check=True,
            env={**__import__("os").environ, "PYTHONHASHSEED": seed},
            cwd=cwd,
        ).stdout
        for seed, cwd in (("1", tmp_path), ("999", ROOT))
    }
    assert len(outputs) == 1


def test_the_original_bytes_are_never_changed(fine):
    copy = bytes(fine)
    prepare_artwork(fine, Adjustments(threshold=0.5, line_weight=-1, despeckle=5))
    prepare_artwork(fine, Adjustments(invert=True, contrast=2))
    assert fine == copy


def test_corrupt_and_oversized_originals_fail_without_fallback(monkeypatch):
    with pytest.raises(ArtworkError) as raised:
        prepare_artwork(png(1)[:500], Adjustments())
    assert raised.value.code == "corrupt_image"
    monkeypatch.setattr(prepare, "MAX_PREPARE_PIXELS", 1000)
    with pytest.raises(ArtworkError) as raised:
        prepare_artwork(png(1), Adjustments())
    assert raised.value.code == "too_large_to_prepare"


def test_scan_bounds_are_reported_never_guessed(monkeypatch):
    monkeypatch.setattr(prepare, "MAX_ANALYZED_INK", 1000)
    prepared = prepare_artwork(png(1), Adjustments())
    assert prepared.measures.strokes_before is None
    assert set(prepared.measures.not_measured) >= {"strokes", "specks"}
    with pytest.raises(ArtworkError) as raised:
        prepare_artwork(png(1), Adjustments(despeckle=1))
    assert raised.value.code == "too_much_ink_to_despeckle"


# ---------------------------------------------------------------- measures and findings


def test_fine_lines_are_kept_by_default_and_thickening(fine):
    for adjustments in (Adjustments(), Adjustments(line_weight=2), Adjustments(threshold=0.5)):
        prepared = prepare_artwork(fine, adjustments)
        assert prepared.measures.thin_line_retention == 1.0
        assert "thin_lines_destroyed" not in codes(prepared)


def test_thinning_fine_lines_is_blocking(fine):
    prepared = prepare_artwork(fine, Adjustments(line_weight=-1))
    assert prepared.measures.thin_line_retention == 0.0
    assert severity(prepared, "thin_lines_destroyed") == "blocking"
    assert "detail_lost" in codes(prepared)


def test_thinning_thick_lines_slightly_is_not_a_finding():
    prepared = prepare_artwork(png(1), Adjustments(line_weight=-1))
    assert prepared.measures.thin_line_retention is None  # No fine lines to lose.
    assert 0.6 < prepared.measures.detail_retention < 0.8
    assert codes(prepared) == []


def test_a_threshold_that_erases_faint_lines_is_blocking():
    pencil = encode(pencil_sketch(0))
    assert codes(prepare_artwork(pencil, Adjustments(threshold=0.5))) == []
    erased = prepare_artwork(pencil, Adjustments(threshold=0.35))
    assert severity(erased, "prepared_blank") == "blocking"
    assert severity(erased, "thin_lines_destroyed") == "blocking"


def test_gray_paper_is_normalized_to_white():
    noisy = encode(noisy_scan(2))
    raw = prepare_artwork(noisy, Adjustments())
    assert raw.measures.paper_level_after == 224 and "background_tint" in codes(raw)
    cleaned = prepare_artwork(noisy, Adjustments(background_cleanup=0.6))
    assert cleaned.measures.paper_level_after == 255
    assert "background_tint" not in codes(cleaned)
    assert cleaned.measures.thin_line_retention in (None, 1.0)


def test_despeckle_removes_isolated_specks_only():
    image = Image.new("L", (400, 400), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(50, 200), (350, 200)], fill=0, width=3)
    draw.rectangle((100, 205, 101, 206), fill=0)  # A 2 x 2 mark 2 px below the line.
    draw.rectangle((300, 60, 301, 61), fill=0)  # A 2 x 2 speck far from everything.
    for x in range(60, 340, 6):  # A dashed faint line: 2 px dashes 4 px apart.
        draw.rectangle((x, 320, x + 1, 321), fill=0)
    prepared = prepare_artwork(encode(image), Adjustments(despeckle=1))
    out = prepared.image
    assert prepared.measures.specks_removed == 1
    assert out.getpixel((300, 60)) == 255  # The isolated speck is gone.
    assert out.getpixel((100, 205)) == 0  # The mark beside the line stays.
    assert out.getpixel((60, 320)) == 0  # Dashes of the faint line stay.


def test_despeckle_keeps_faint_line_fragments_and_cleans_scans():
    pencil = prepare_artwork(encode(pencil_sketch(0)), Adjustments(despeckle=5))
    assert pencil.measures.detail_retention == 1.0
    noisy = encode(noisy_scan(2))
    assert "specks_remaining" in codes(prepare_artwork(noisy, Adjustments()))
    # Despeckle 3 (marks up to 16 px) leaves the scan's 13-21 px dots: still flagged.
    partly = prepare_artwork(noisy, Adjustments(background_cleanup=0.6, despeckle=3, threshold=0.5))
    assert partly.measures.specks_per_megapixel_after > 5
    assert codes(partly) == ["specks_remaining"]
    fixed = prepare_artwork(noisy, Adjustments(background_cleanup=0.6, despeckle=4, threshold=0.5))
    assert codes(fixed) == [] and fixed.measures.specks_per_megapixel_after == 0
    assert fixed.measures.specks_removed > 200


def test_transparency_is_composited_onto_white():
    prepared = prepare_artwork(encode(transparent_art(4)), Adjustments())
    lines = prepare_artwork(encode(line_art(4)), Adjustments())
    assert prepared.measures.paper_level_after == 255
    assert prepared.measures.ink_after == lines.measures.ink_after
    assert codes(prepared) == []


def test_white_on_black_needs_invert():
    data = encode(white_on_black(3))
    plain = prepare_artwork(data, Adjustments())
    assert severity(plain, "excessive_ink") == "blocking"
    assert "turn on Invert" in plain.findings[0].message
    inverted = prepare_artwork(data, Adjustments(invert=True))
    assert codes(inverted) == [] and inverted.measures.ink_after < 0.05


def test_light_colored_lines_need_the_darkest_channel():
    data = encode(light_colored_lines(5))
    luma = prepare_artwork(data, Adjustments())
    assert severity(luma, "prepared_blank") == "blocking"
    assert "Grayscale" in luma.findings[0].message
    darkest = prepare_artwork(data, Adjustments(grayscale=False))
    assert codes(darkest) == [] and darkest.measures.ink_after > 0.03


def test_brightening_everything_away_is_blocking():
    prepared = prepare_artwork(png(1), Adjustments(brightness=1.0))
    assert severity(prepared, "prepared_blank") == "blocking"


def test_dense_patterns_report_heavy_ink_and_broken_strokes():
    dense = encode(dense_pattern())
    assert codes(prepare_artwork(dense, Adjustments())) == []
    heavy = prepare_artwork(dense, Adjustments(line_weight=2))
    assert severity(heavy, "heavy_ink") == "warning"
    broken = prepare_artwork(dense, Adjustments(line_weight=-2))
    assert broken.measures.strokes_after > broken.measures.strokes_before * 100
    assert "strokes_broken" in codes(broken)


def test_thickening_never_reports_broken_strokes():
    noisy = encode(noisy_scan(2))
    thick = prepare_artwork(noisy, Adjustments(line_weight=2))
    assert thick.measures.strokes_after == thick.measures.strokes_before
    assert "strokes_broken" not in codes(thick)


def test_new_edge_contact_is_flagged():
    clear = prepare_artwork(png(1), Adjustments(line_weight=2))
    assert clear.measures.new_edges == ()
    # Darkening the paper into ink makes every edge ink, which the original was not.
    dark = prepare_artwork(png(1), Adjustments(brightness=-0.6))
    assert set(dark.measures.new_edges) == {"top", "bottom", "left", "right"}
    assert "prepared_touches_edge" in codes(dark)


def test_difference_preview_colors_removed_and_added_ink():
    image = Image.new("L", (40, 40), 255)
    ImageDraw.Draw(image).line([(5, 20), (35, 20)], fill=0, width=1)
    thick = Image.new("L", (40, 40), 255)
    ImageDraw.Draw(thick).line([(5, 20), (35, 20)], fill=0, width=3)
    difference = difference_image(image, thick)
    assert difference.getpixel((20, 20)) == prepare.KEPT_COLOR
    assert difference.getpixel((20, 19)) == prepare.ADDED_COLOR
    assert difference_image(thick, image).getpixel((20, 19)) == prepare.REMOVED_COLOR
    assert difference.getpixel((2, 2)) == (255, 255, 255)
    prepared = prepare_artwork(png(1), Adjustments())
    for kind in ("original", "prepared", "difference"):
        data = preview_png(prepared, kind)
        assert (
            data.startswith(b"\x89PNG")
            and max(Image.open(__import__("io").BytesIO(data)).size) <= 1200
        )


# ---------------------------------------------------------------- run-length labeling


def _reference_areas(image: Image.Image, level: int) -> list[int]:
    width, height = image.size
    data = image.tobytes()
    seen = [False] * len(data)
    areas = []
    for start in range(len(data)):
        if seen[start] or data[start] > level:
            continue
        seen[start], stack, area = True, [start], 0
        while stack:
            index = stack.pop()
            area += 1
            y, x = divmod(index, width)
            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    if 0 <= ny < height and 0 <= nx < width:
                        n = ny * width + nx
                        if not seen[n] and data[n] <= level:
                            seen[n] = True
                            stack.append(n)
        areas.append(area)
    return sorted(areas)


@pytest.mark.parametrize("seed", range(12))
def test_run_length_labeling_matches_a_pixel_flood_fill(seed):
    rng = random.Random(seed)
    size = (rng.randrange(5, 60), rng.randrange(5, 60))
    image = Image.frombytes(
        "L", size, bytes(rng.choice((0, 255, 255)) for _ in range(size[0] * size[1]))
    )
    assert sorted(components.region_areas(image, 128, 10**6)) == _reference_areas(image, 128)


# ---------------------------------------------------------------- cache keys


def test_cache_keys_name_source_settings_and_versions(monkeypatch):
    sha = "a" * 64
    base = cache_key(sha, Adjustments())
    assert base.startswith("pp1-prepared-sha256-")
    assert cache_key("b" * 64, Adjustments()) != base
    keys = {
        cache_key(sha, Adjustments(**{name: value}))
        for name, value in (
            ("grayscale", False),
            ("threshold", 0.5),
            ("brightness", 0.1),
            ("contrast", 1.5),
            ("background_cleanup", 0.2),
            ("despeckle", 1),
            ("line_weight", 1),
            ("invert", True),
        )
    }
    assert len(keys) == 8 and base not in keys
    monkeypatch.setattr(prepare, "PREPARATION_VERSION", PREPARATION_VERSION + 1)
    assert cache_key(sha, Adjustments()) != base
    monkeypatch.setattr(prepare, "PREPARATION_VERSION", PREPARATION_VERSION)
    monkeypatch.setattr(prepare, "PILLOW_VERSION", "0.0.0")
    assert cache_key(sha, Adjustments()) != base


# ---------------------------------------------------------------- settings in book.yaml


def test_invert_is_serialized_only_when_set():
    assert "invert" not in Adjustments().to_dict()
    assert Adjustments(invert=True).to_dict()["invert"] is True
    parsed, issues = validate_adjustments({"invert": True, "threshold": 0.4})
    assert issues == () and parsed == Adjustments(invert=True, threshold=0.4)
    parsed, issues = validate_adjustments({"invert": "yes"})
    assert parsed is None and issues[0].code == "type"
    parsed, issues = validate_adjustments({"sharpen": 1})
    assert parsed is None and issues[0].code == "unknown_field"


def test_interval_two_books_keep_their_bytes(tmp_path):
    book = write_coloring_book(tmp_path / "book")
    import_files(book, [("a.png", png(1))])
    text = (book / "book.yaml").read_text(encoding="utf-8")
    assert "invert" not in text
    assert dump_project(load_project(book).project) == text


def test_adjust_saves_settings_and_keeps_the_original(tmp_path):
    book = write_coloring_book(tmp_path / "book")
    (result,) = import_files(book, [("a.png", png(1))])
    original = (book / result.path).read_bytes()
    saved = adjust_artwork(book, "a", Adjustments(line_weight=1, invert=False))
    assert saved.adjustments == Adjustments(line_weight=1)
    assert load_project(book).project.coloring.artwork[0].adjustments.line_weight == 1
    prepared = prepare_entry(book, load_project(book).project, "a")
    assert prepared.adjustments.line_weight == 1
    adjust_artwork(book, "a", Adjustments())  # Reset.
    assert load_project(book).project.coloring.artwork[0].adjustments == Adjustments()
    assert (book / result.path).read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == result.sha256


def test_adjust_refuses_a_changed_source_and_unknown_artwork(tmp_path):
    book = write_coloring_book(tmp_path / "book")
    import_files(book, [("a.png", png(1))])
    with pytest.raises(ProjectError) as raised:
        adjust_artwork(book, "a", Adjustments(line_weight=1), revision="sha256-" + "0" * 64)
    assert raised.value.issues[0].code == "source_changed"
    with pytest.raises(ArtworkError) as raised:
        adjust_artwork(book, "missing", Adjustments())
    assert raised.value.code == "unknown_artwork"


def test_a_failed_save_leaves_book_yaml_as_it_was(tmp_path, monkeypatch):
    from puzzlepress.coloring import library

    book = write_coloring_book(tmp_path / "book")
    import_files(book, [("a.png", png(1))])
    before = (book / "book.yaml").read_bytes()

    def fail(*_args, **_kwargs):
        raise ProjectError(())

    monkeypatch.setattr(library, "replace_source", fail)
    with pytest.raises(ProjectError):
        adjust_artwork(book, "a", Adjustments(line_weight=2))
    assert (book / "book.yaml").read_bytes() == before


def test_with_adjustments_changes_only_that_artwork():
    data = {
        "schema_version": 1,
        "book": {"id": "b", "title": "B", "language": "en"},
        "build": {"seed": 1},
        "coloring": {
            "version": 1,
            "artwork": [
                {"id": "a", "path": "coloring-assets/a-" + "1" * 12 + ".png", "sha256": "1" * 64},
                {"id": "b", "path": "coloring-assets/b-" + "2" * 12 + ".png", "sha256": "2" * 64},
            ],
        },
    }
    project = validate_project(data).require_project()
    updated, item = with_adjustments(project, "b", Adjustments(threshold=0.5))
    assert item.adjustments.threshold == 0.5
    assert updated.coloring.artwork[0] == project.coloring.artwork[0]


# ---------------------------------------------------------------- CLI


def run(capsys, *args: str) -> tuple[int, str, str]:
    from puzzlepress.cli import main

    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_prepare_previews_without_saving(tmp_path, capsys):
    book = write_coloring_book(tmp_path / "book")
    import_files(book, [("a.png", encode(fine_detail()))])
    before = (book / "book.yaml").read_bytes()
    code, out, _ = run(
        capsys, "coloring", "prepare", str(book), "a", "--set", "line_weight=-1", "--json"
    )
    data = json.loads(out)
    assert code == 1 and data["blocking"]
    assert "thin_lines_destroyed" in [f["code"] for f in data["findings"]]
    assert (book / "book.yaml").read_bytes() == before
    code, _, err = run(
        capsys, "coloring", "prepare", str(book), "a", "--output", str(book / "previews")
    )
    assert code == 1 and "output_inside_source" in err
    target = tmp_path / "previews"
    code, out, _ = run(capsys, "coloring", "prepare", str(book), "a", "--output", str(target))
    assert code == 0 and sorted(p.name for p in target.iterdir()) == [
        "a-difference.png",
        "a-original.png",
        "a-prepared.png",
    ]
    assert Image.open(target / "a-prepared.png").size == (2175, 2925)


def test_cli_adjust_sets_and_resets(tmp_path, capsys):
    book = write_coloring_book(tmp_path / "book")
    import_files(book, [("a.png", png(1))])
    code, out, _ = run(
        capsys,
        "coloring",
        "adjust",
        str(book),
        "a",
        "--set",
        "threshold=0.5",
        "--set",
        "invert=false",
    )
    assert code == 0 and "threshold=0.5" in out
    assert load_project(book).project.coloring.artwork[0].adjustments.threshold == 0.5
    code, _, err = run(capsys, "coloring", "adjust", str(book), "a", "--set", "contrast=9")
    assert code == 1 and "[range]" in err
    code, _, err = run(capsys, "coloring", "adjust", str(book), "a", "--set", "nonsense")
    assert code == 1 and "invalid_setting" in err
    code, _, _ = run(capsys, "coloring", "adjust", str(book), "a", "--reset")
    assert code == 0 and load_project(book).project.coloring.artwork[0].adjustments == Adjustments()
