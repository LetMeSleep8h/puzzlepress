"""Cover watermarks: configuration, deterministic placement, baking and output."""

import hashlib

import pytest
from PIL import Image

from puzzlepress import load_project
from puzzlepress.cover.build import build_cover
from puzzlepress.cover.issues import CoverError
from puzzlepress.cover.watermark import (
    CLEARANCE,
    MAX_SIZE,
    MIN_SIZE,
    SHADOW_OFFSET,
    bake_watermark,
    place_watermark,
)
from puzzlepress.cover_config import Watermark, WatermarkPosition
from puzzlepress.cover_validation import validate_cover
from puzzlepress.interior.fonts import ASCENT, DESCENT, text_width
from puzzlepress.interior.model import Box, Face
from tests.cover_helpers import cover_project, photo_bytes

FRONT = Box(400.0, 0.0, 612.0, 792.0)


def test_disabled_or_empty_watermark_places_nothing() -> None:
    assert place_watermark(Watermark(enabled=False, text="Q"), FRONT) is None
    assert place_watermark(Watermark(text=""), FRONT) is None


def test_scale_sets_width_from_the_front_panel() -> None:
    placed = place_watermark(Watermark(text="Quang", scale=0.25, shadow=False), FRONT)
    assert placed is not None
    assert placed.size * text_width("Quang", Face.BOLD, 1.0) == pytest.approx(0.25 * 612)
    assert placed.box.width == pytest.approx(0.25 * 612)
    assert placed.box.height == pytest.approx((ASCENT + DESCENT) * placed.size)
    tiny = place_watermark(Watermark(text="Q", scale=0.05), Box(0, 0, 10, 10))
    huge = place_watermark(Watermark(text="Q", scale=0.8), FRONT)
    assert tiny is not None and tiny.size == MIN_SIZE
    assert huge is not None and huge.size == MAX_SIZE


@pytest.mark.parametrize("position", list(WatermarkPosition))
def test_every_position_keeps_the_margin(position) -> None:
    margin = 30.0
    placed = place_watermark(Watermark(text="Photo", position=position, margin=margin), FRONT)
    assert placed is not None
    box = placed.box
    horizontal = (
        position.value.split("-")[-1] if position is not WatermarkPosition.CENTER else "center"
    )
    vertical = (
        position.value.split("-")[0] if position is not WatermarkPosition.CENTER else "middle"
    )
    expected_x = {
        "left": FRONT.x + margin,
        "center": FRONT.x + (FRONT.width - box.width) / 2,
        "right": FRONT.right - margin - box.width,
    }[horizontal]
    expected_y = {
        "bottom": FRONT.y + margin,
        "middle": FRONT.y + (FRONT.height - box.height) / 2,
        "top": FRONT.top - margin - box.height,
    }[vertical]
    assert box.x == pytest.approx(expected_x)
    assert box.y == pytest.approx(expected_y)
    assert placed == place_watermark(
        Watermark(text="Photo", position=position, margin=margin), FRONT
    )


def test_shadow_stays_inside_the_margin() -> None:
    plain = place_watermark(Watermark(text="Photo"), FRONT)
    shadowed = place_watermark(Watermark(text="Photo", shadow=True), FRONT)
    assert plain is not None and shadowed is not None
    assert shadowed.box.right == pytest.approx(FRONT.right - 27.0)
    assert shadowed.box.y == pytest.approx(FRONT.y + 27.0)
    assert shadowed.box.width == pytest.approx(plain.box.width + shadowed.size * SHADOW_OFFSET)


def _baked(opacity: float, shadow: bool = False) -> Image.Image:
    image = (
        Image.new("RGB", (400, 200), (0, 0, 0))
        if not shadow
        else Image.new("RGB", (400, 200), (128, 128, 128))
    )
    placed = place_watermark(
        Watermark(
            text="WWWW", opacity=opacity, scale=0.8, margin=10, shadow=shadow, color="#ffffff"
        ),
        Box(0, 0, 400, 200),
    )
    assert placed is not None
    return bake_watermark(image, Box(0, 0, 400, 200), 1.0, placed)


def test_opacity_scales_the_baked_pixels() -> None:
    full = _baked(1.0).getextrema()
    half = _baked(0.5).getextrema()
    assert full == ((0, 255),) * 3
    assert all(abs(high - 128) <= 1 for _, high in half)
    shadowed = _baked(1.0, shadow=True).getextrema()
    assert shadowed[0][0] < 128 and shadowed[0][1] == 255  # The shadow darkens beneath.


def _cover_data(**watermark):
    return {"version": 2, "watermark": {"text": "Photo: Q. Huynh", **watermark}}


def test_watermark_needs_version_2_and_valid_values() -> None:
    image = {"path": "cover-assets/x-000000000000.jpg", "sha256": "0" * 64}
    _, issues = validate_cover({"version": 1, "image": image, "watermark": {"text": "x"}}, True)
    assert [i.code for i in issues] == ["requires_version_2"]
    config, issues = validate_cover(
        {"version": 2, "image": image, "watermark": {"text": " Q "}}, True
    )
    assert not issues and config is not None and config.watermark == Watermark(text="Q")
    assert config.to_dict()["watermark"]["position"] == "bottom-right"
    bad = {
        "opacity": 0.0,
        "scale": 2,
        "margin": 1,
        "position": "corner",
        "text": "",
        "color": "white",
        "shadow": "yes",
        "angle": 45,
    }
    for key, value in bad.items():
        _, issues = validate_cover(
            {"version": 2, "image": image, "watermark": {"text": "Q", key: value}}, True
        )
        assert issues, key


def _build(tmp_path, name, cover=None, data=None):
    source, output = cover_project(
        tmp_path / name, data=data or photo_bytes(5400, 3600), cover=cover
    )
    project = load_project(source).project
    return source, build_cover(project, source, output)


def test_disabled_watermark_renders_the_same_pdf(tmp_path) -> None:
    _, plain = _build(tmp_path, "plain", {"version": 2})
    _, off = _build(tmp_path, "off", _cover_data(enabled=False))
    _, on = _build(tmp_path, "on", _cover_data(opacity=0.4, shadow=True))
    assert off.pdf == plain.pdf
    assert on.pdf != plain.pdf
    _, again = _build(tmp_path, "again", _cover_data(opacity=0.4, shadow=True))
    assert again.pdf == on.pdf  # Deterministic.
    assert on.layout.watermark is not None
    assert on.layout.photo.watermark == on.layout.watermark


def test_source_photo_is_untouched(tmp_path) -> None:
    data = photo_bytes(5400, 3600)
    source, _ = _build(tmp_path, "src", _cover_data(), data)
    (asset,) = (source / "cover-assets").iterdir()
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == hashlib.sha256(data).hexdigest()


def test_watermark_over_cover_text_is_reported(tmp_path) -> None:
    with pytest.raises(CoverError) as caught:
        _build(tmp_path, "over", _cover_data(position="top-center", scale=0.6, margin=40))
    codes = {issue.code for issue in caught.value.issues}
    assert "watermark_overlaps_text" in codes
    assert CLEARANCE > 0
