"""`book produce`: one reproducible run, protected sources, sorted validation."""

import json

import pytest

from puzzlepress.cli import main
from puzzlepress.production.produce import ProductionError, classify, produce
from puzzlepress.yaml_io import dump_project
from tests.cover_helpers import cover_project
from tests.helpers import demo_variant


@pytest.fixture(scope="module")
def books(tmp_path_factory):
    """A previous book (source plus its built release folder) and a new cover book."""
    from puzzlepress.interior import build_interior, write_interior
    from puzzlepress.interior.spec import PAPERBACK_LETTER

    root = tmp_path_factory.mktemp("produce")
    previous = root / "previous book"
    previous.mkdir()
    old = demo_variant()
    (previous / "book.yaml").write_text(dump_project(old), encoding="utf-8")
    release = root / "releases" / "review 1"
    write_interior(build_interior(old, PAPERBACK_LETTER), release, previous)
    source, _ = cover_project(root / "new", puzzles=16, build_interior=False)
    return root, previous, release, source, len(old.word_search.puzzles)


def _files(directory):
    return {p.name: p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file()}


def test_run_writes_every_artifact_and_is_reproducible(books) -> None:
    root, _, release, source, count = books
    first = produce(source, root / "run a", [release], expected_puzzles=count)
    second = produce(source, root / "run b", [release], expected_puzzles=count)
    names = set(_files(first.directory))
    assert {
        "interior.pdf",
        "interior.json",
        "preflight.json",
        "cover.pdf",
        "cover.json",
        "cover-preflight.json",
        "duplicate-report.json",
        "duplicate-report.md",
        "publishing-validation.json",
        "publishing-validation.md",
        "production.json",
    } <= names
    assert _files(first.directory) == _files(second.directory)
    manifest = json.loads((first.directory / "production.json").read_text(encoding="utf-8"))
    assert manifest["book_id"] == "composition-demo"
    assert {f["name"] for f in manifest["files"]} == names - {"production.json"}
    assert str(root) not in (first.directory / "production.json").read_text(encoding="utf-8")


def test_validation_is_sorted_and_never_claims_more_than_checked(books) -> None:
    root, _, release, source, count = books
    result = produce(source, root / "run c", [release], expected_puzzles=count)
    validation = json.loads((root / "run c" / "publishing-validation.json").read_text())
    assert set(validation) >= {"blocking", "warnings", "manual_review", "verified"}
    assert any(i["code"] == "physical_proof" for i in validation["manual_review"])
    assert "Nothing here is a KDP approval" in validation["note"]
    # The 16-puzzle book repeats the demo's word lists, so duplicates block it.
    assert any(i["source"] == "duplicates" for i in validation["blocking"])
    assert not result.ready
    assert any(v.startswith("Answer key: all 16") for v in validation["verified"])


def test_unconfirmed_previous_coverage_blocks(books) -> None:
    root, _, release, source, _ = books
    result = produce(source, root / "run d", [release])
    codes = [i.code for i in result.validation.blocking]
    assert "incomplete_coverage" in codes


@pytest.mark.parametrize("where", ["source", "previous", "release", "parent"])
def test_output_may_not_overlap_protected_folders(books, where) -> None:
    root, previous, release, source, _ = books
    target = {
        "source": source / "out",
        "previous": previous / "out",
        "release": release,
        "parent": release.parent.parent,
    }[where]
    with pytest.raises(ProductionError):
        produce(source, target, [previous, release])
    assert not (release / "production.json").exists()


def test_output_owned_by_another_book_is_refused(books) -> None:
    root, _, release, source, _ = books
    other = root / "other"
    other.mkdir()
    (other / "production.json").write_text('{"kind": "x"}', encoding="utf-8")
    with pytest.raises(ProductionError):
        produce(source, other, [release])


def test_missing_cover_and_no_previous_book_are_reported() -> None:
    validation = classify(None, None, False, None, None, None)
    assert [i.code for i in validation.blocking] == ["cover_not_configured"]
    assert [i.code for i in validation.warnings] == ["no_previous_book"]
    assert validation.verified == ()


def test_cli_produce_and_compare(books, capsys) -> None:
    root, previous, release, source, count = books
    out = root / "cli run"
    assert main(["book", "produce", str(source), "--output", str(out), "--previous", str(release),
                 "--expected-puzzles", str(count)]) == 1  # fmt: skip
    assert "Blocking failures" in capsys.readouterr().out
    assert main(["puzzle", "compare", str(previous), "--previous", str(release),
                 "--expected-puzzles", str(count), "--json"]) == 1  # fmt: skip
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["exact"] == count and report["coverage_complete"]
    assert main(["puzzle", "inventory", str(release), "--expected-puzzles", str(count)]) == 0
    assert json.loads(capsys.readouterr().out)["coverage"]["status"] == "complete"
    assert main(["puzzle", "inventory", str(release), "--output", str(release / "x.json")]) == 1


def test_photo_manifest_is_checked_and_its_archive_protected(books) -> None:
    from tests.cover_helpers import photo_bytes

    root, _, release, source, count = books
    archive = root / "cameras ü"
    archive.mkdir()
    (archive / "shot.jpg").write_bytes(photo_bytes(600, 400))
    manifest = root / "photos.yaml"
    manifest.write_text(
        f"photo_manifest_version: 1\nbase_directory: '{archive}'\nphotos: [shot.jpg]\n",
        encoding="utf-8",
    )
    with pytest.raises(ProductionError):
        produce(source, archive / "out", [release], count, photo_manifest=manifest)
    result = produce(source, root / "run p", [release], count, photo_manifest=manifest)
    assert (result.directory / "photo-check.json").is_file()
    assert any(i.code == "image_too_small" for i in result.validation.blocking)
    assert sorted(p.name for p in archive.iterdir()) == ["shot.jpg"]
