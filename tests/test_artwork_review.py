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
