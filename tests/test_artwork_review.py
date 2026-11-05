"""The real-artwork review harness: reads inputs only and records no human judgement."""

import hashlib
import json
from pathlib import Path

import pytest
from artwork_review import NOT_RECORDED, review
from coloring_helpers import encode, line_art


def test_review_writes_evidence_and_never_touches_inputs(tmp_path: Path) -> None:
    inputs = tmp_path / "art"
    inputs.mkdir()
    (inputs / "one.png").write_bytes(encode(line_art(1, (1088, 1463))))
    (inputs / "two.jpg").write_bytes(encode(line_art(2, (1088, 1463)).convert("RGB"), "JPEG"))
    (inputs / "notes.txt").write_text("not art", encoding="utf-8")
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
    sheet = review(inputs, tmp_path / "out", {"contrast": 1.2})
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()} == before
    out = tmp_path / "out"
    for stem in ("one", "two"):
        assert {p.name for p in (out / stem).iterdir()} == {
            "original.png",
            "prepared.png",
            "difference.png",
            "measures.json",
        }
        record = json.loads((out / stem / "measures.json").read_text(encoding="utf-8"))
        assert record["adjustments"]["contrast"] == 1.2
        assert "no human review" in record["evidence"]
    assert (out / "print" / "interior.pdf").is_file()
    text = sheet.read_text(encoding="utf-8")
    assert text.count(f"{NOT_RECORDED} |") == 8  # Two drawings x four human fields.
    assert "notes.txt" not in text


def test_review_refuses_an_output_inside_its_inputs(tmp_path: Path) -> None:
    (tmp_path / "a.png").write_bytes(encode(line_art(1, (300, 400))))
    with pytest.raises(SystemExit):
        review(tmp_path, tmp_path / "out", {})
    with pytest.raises(SystemExit):
        review(tmp_path, tmp_path.parent, {})  # An output containing the inputs.


# ---------------------------------------------------------------- verified originals (Interval 9)


def _manifest(tmp_path: Path, files: dict[str, bytes]) -> Path:
    manifest = tmp_path / "approved.json"
    entries = [
        {"file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in files.items()
    ]
    manifest.write_text(json.dumps({"artworks": entries}), encoding="utf-8")
    return manifest


def test_a_manifest_review_refuses_missing_extra_or_changed_originals(tmp_path: Path) -> None:
    good, other = encode(line_art(1, (300, 400))), encode(line_art(2, (300, 400)))
    manifest = _manifest(tmp_path, {"a.png": good, "b.png": good})
    inputs = tmp_path / "art"
    inputs.mkdir()
    (inputs / "a.png").write_bytes(other)  # Changed: same name, other bytes.
    (inputs / "c.png").write_bytes(good)  # Not in the manifest.
    with pytest.raises(SystemExit) as raised:
        review(inputs, tmp_path / "out", {}, manifest)
    message = str(raised.value)
    assert "missing: b.png" in message and "not in the manifest: c.png" in message
    assert "changed: a.png" in message
    assert not (tmp_path / "out").exists()  # Nothing was measured.


def test_a_verified_review_compares_with_the_recorded_measures(tmp_path: Path) -> None:
    from artwork_compare import compare

    data = encode(line_art(1, (1088, 1463)))
    manifest = _manifest(tmp_path, {"a.png": data})
    inputs = tmp_path / "art"
    inputs.mkdir()
    (inputs / "a.png").write_bytes(data)
    settings = {"background_cleanup": 0.6, "despeckle": 2}
    review(inputs, tmp_path / "out", settings, manifest)
    record = tmp_path / "record.json"
    record.write_text(
        json.dumps(
            {
                "settings": settings,
                "drawings": {
                    "a.png": {"thin_kept": 0.5, "light_kept": None},
                    "z.png": {"thin_kept": 0.9, "light_kept": None},
                },
            }
        ),
        encoding="utf-8",
    )
    table = compare(tmp_path / "out", record)
    assert "| a.png | 50% -> " in table and "| z.png | 90% -> not reviewed |" in table
    # A review made with other settings is refused, not compared.
    review(inputs, tmp_path / "other", {"contrast": 1.2}, manifest)
    with pytest.raises(SystemExit):
        compare(tmp_path / "other", record)


def test_fetching_keeps_only_verified_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No network: the download is replaced by what each URL "serves"."""
    import artwork_fetch

    good = encode(line_art(1, (300, 400)))
    entries = [
        {"file": n, "bytes": len(good), "sha256": hashlib.sha256(good).hexdigest(), "source_url": n}
        for n in ("ok.png", "kept.png", "bad-local.png", "bad-remote.png")
    ]
    manifest = tmp_path / "approved.json"
    manifest.write_text(json.dumps({"artworks": entries}), encoding="utf-8")
    folder = tmp_path / "originals"
    folder.mkdir()
    (folder / "kept.png").write_bytes(good)
    (folder / "bad-local.png").write_bytes(b"something else")
    served = {"ok.png": good, "bad-remote.png": b"a different image"}
    monkeypatch.setattr(artwork_fetch, "_download", lambda url: served[url])
    monkeypatch.setattr(artwork_fetch, "PAUSE", 0.0)
    assert artwork_fetch.fetch(manifest, folder) == 2
    assert (folder / "ok.png").read_bytes() == good == (folder / "kept.png").read_bytes()
    assert (folder / "bad-local.png").read_bytes() == b"something else"  # Never overwritten.
    assert not (folder / "bad-remote.png").exists()
    with pytest.raises(SystemExit):
        artwork_fetch.fetch(manifest, artwork_fetch.ROOT / "originals")


def test_the_contact_sheet_shows_every_reviewed_drawing(tmp_path: Path) -> None:
    from artwork_contact_sheet import TILE, sheet
    from PIL import Image

    inputs = tmp_path / "art"
    inputs.mkdir()
    for seed in (1, 2):
        (inputs / f"d{seed}.png").write_bytes(encode(line_art(seed, (300, 400))))
    review(inputs, tmp_path / "out", {"background_cleanup": 0.6})
    image = Image.open(sheet(tmp_path / "out", tmp_path / "sheet.png"))
    assert image.width == 3 * TILE + 40 and image.height >= 2 * TILE
