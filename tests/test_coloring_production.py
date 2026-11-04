"""`book produce` for coloring books: complete, verified, atomic and deterministic."""

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coloring_production import write_book  # noqa: E402

from puzzlepress import dump_project, validate_project  # noqa: E402
from puzzlepress.errors import ProjectError  # noqa: E402
from puzzlepress.production import coloring as production  # noqa: E402
from puzzlepress.production.produce import produce  # noqa: E402
from puzzlepress.project import load_project  # noqa: E402

TOP_LEVEL = {
    "artwork-duplicates.json",
    "artwork-duplicates.md",
    "artwork-integrity.json",
    "cover-preflight.json",
    "cover.json",
    "cover.pdf",
    "interior.json",
    "interior.pdf",
    "kdp-metadata.json",
    "preflight.json",
    "production.json",
    "publishing-readiness.json",
    "publishing-validation.json",
    "publishing-validation.md",
}
PACKAGE = {
    "cover-preflight.json",
    "cover.pdf",
    "interior-preflight.json",
    "interior.pdf",
    "kdp-checklist.md",
    "metadata.json",
    "package.json",
    "provenance.json",
    "readiness.json",
}


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_book(tmp_path_factory.mktemp("coloring-produce"))


@pytest.fixture(scope="module")
def released(made: Path, tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("released") / "release"
    return produce(made, output)


def _digests(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_a_complete_package_is_produced_and_ready(released) -> None:
    directory = released.directory
    assert released.ready, [i.message for i in released.validation.blocking]
    names = {p.name for p in directory.iterdir() if p.is_file()}
    assert names == TOP_LEVEL
    assert {p.name for p in (directory / "publishing").iterdir()} == PACKAGE
    manifest = json.loads((directory / "production.json").read_text(encoding="utf-8"))
    assert manifest["engine"] == "coloring" and manifest["version"] == 2
    assert manifest["result"]["status"] == "ready_for_manual_kdp_submission"
    assert manifest["result"]["package"] == "publishing/"
    assert "cannot guarantee" in manifest["result"]["guarantee"]
    assert set(manifest["environment"]) == {"python", "image_library", "zlib"}
    # Manual review is always listed: automated checks never judge the artwork.
    assert any(i.code == "artwork_review" for i in released.validation.manual)
    # The package holds exactly the bytes the run inspected.
    for name in ("interior.pdf", "cover.pdf"):
        assert (directory / name).read_bytes() == (directory / "publishing" / name).read_bytes()
    package = json.loads((directory / "publishing" / "package.json").read_text())
    assert package["rulesets"]["publishing"]["id"] == "puzzlepress-kdp-publishing-coloring"
    assert package["rulesets"]["interior"]["id"] == "puzzlepress-kdp-coloring"


def test_manifest_lists_every_file_with_its_digest(released) -> None:
    directory = released.directory
    manifest = json.loads((directory / "production.json").read_text(encoding="utf-8"))
    listed = {entry["name"]: entry for entry in manifest["files"]}
    digests = _digests(directory)
    digests.pop("production.json")
    assert set(listed) == set(digests)
    for name, digest in digests.items():
        assert listed[name]["sha256"] == digest
        assert listed[name]["bytes"] == (directory / name).stat().st_size


def test_interior_and_cover_agree(released) -> None:
    directory = released.directory
    interior = json.loads((directory / "interior.json").read_text(encoding="utf-8"))
    cover = json.loads((directory / "cover.json").read_text(encoding="utf-8"))
    # A cover pins the physical facts of the interior it was sized from.
    assert cover["interior"]["page_count"] == interior["page_count"] == 28
    assert cover["interior"]["paper"] == interior["print_profile"]["paper"]
    assert cover["interior"]["profile_id"] == interior["print_profile"]["profile_id"]
    readiness = json.loads((directory / "publishing-readiness.json").read_text(encoding="utf-8"))
    assert readiness["verdicts"]["interior"]["state"] == "current"
    assert readiness["verdicts"]["cover"]["state"] == "current"
    integrity = json.loads((directory / "artwork-integrity.json").read_text(encoding="utf-8"))
    assert integrity["verified"] is True
    assert integrity["interior_identity"] == interior["interior_identity"]
    assert len(integrity["artwork"]) == 12
    assert all(
        len(item["pages"]) == 1 and item["effective_dpi"] >= 300 for item in integrity["artwork"]
    )
    duplicates = json.loads((directory / "artwork-duplicates.json").read_text(encoding="utf-8"))
    assert duplicates["complete"] is True


def test_production_is_deterministic(made: Path, released, tmp_path: Path) -> None:
    again = produce(made, tmp_path / "again")
    assert _digests(again.directory) == _digests(released.directory)


def test_rerun_replaces_the_output_and_leaves_no_staging(made: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    produce(made, output)
    stray = output / "stray.txt"
    stray.write_text("left from an earlier tool", encoding="utf-8")
    produce(made, output)
    assert not stray.exists()  # the output is the verified run, nothing else
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_failure_keeps_the_previous_output_and_cleans_up(
    made: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "out"
    produce(made, output)
    before = _digests(output)

    def broken(*args: object, **kwargs: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(production, "_verify", broken)
    with pytest.raises(OSError, match="disk full"):
        produce(made, output)
    assert _digests(output) == before
    assert [p.name for p in tmp_path.iterdir()] == ["out"]  # no staging, no lock


def test_a_concurrent_run_is_refused(made: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    lock = tmp_path / ".out.produce.lock"
    lock.write_text("", encoding="utf-8")
    with pytest.raises(ProjectError) as raised:
        produce(made, output)
    assert raised.value.issues[0].code == "production_in_progress"
    assert not output.exists()
    assert lock.exists()  # never removed by the refused run


def test_unresolved_rights_block_and_no_package_is_written(made: Path, tmp_path: Path) -> None:
    book = tmp_path / "book"
    shutil.copytree(made, book)
    data = load_project(book).project.to_dict()
    del data["publishing"]["content_rights"]
    (book / "book.yaml").write_text(
        dump_project(validate_project(data).require_project()), encoding="utf-8"
    )
    result = produce(book, tmp_path / "out")
    assert not result.ready
    assert any(i.code == "content_rights_declared" for i in result.validation.blocking)
    assert not (result.directory / "publishing").exists()
    manifest = json.loads((result.directory / "production.json").read_text(encoding="utf-8"))
    assert manifest["result"]["status"] == "blocked" and manifest["result"]["package"] is None


def test_output_inside_the_project_or_foreign_is_refused(made: Path, tmp_path: Path) -> None:
    with pytest.raises(ProjectError) as raised:
        produce(made, made / "release")
    assert raised.value.issues[0].code == "protected_overlap"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "production.json").write_text('{"kind": "other"}', encoding="utf-8")
    with pytest.raises(ProjectError) as raised:
        produce(made, foreign)
    assert raised.value.issues[0].code == "output_collision"


def test_word_search_options_are_refused_for_coloring(made: Path, tmp_path: Path) -> None:
    with pytest.raises(ProjectError) as raised:
        produce(made, tmp_path / "out", previous=[made], photo_manifest=made / "x.yaml")
    issue = raised.value.issues[0]
    assert issue.code == "not_applicable_for_engine"
    assert "--previous" in issue.message and "--photos" in issue.message


def test_originals_are_never_written(made: Path, released) -> None:
    assets = made / "coloring-assets"
    for path in assets.iterdir():
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert path.name.split("-")[-1].split(".")[0] == digest[:12]
