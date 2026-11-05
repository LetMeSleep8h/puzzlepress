"""Optional `catalog` and `print` sections: schema, identity and the print profile."""

import json
from pathlib import Path

import pytest

from puzzlepress.cli import main
from puzzlepress.identity import build_identity
from puzzlepress.project import load_project
from puzzlepress.validation import validate_project
from puzzlepress.yaml_io import dump_project
from tests.helpers import DEMO


def source_data() -> dict:
    return load_project(DEMO).project.to_dict()


def issues(data: dict) -> set[tuple[str, str]]:
    return {(i.path, i.code) for i in validate_project(data).issues}


def test_absent_sections_change_nothing() -> None:
    data = source_data()
    project = validate_project(data).require_project()
    assert "catalog" not in project.to_dict() and "print" not in project.to_dict()
    assert project.catalog is None and project.printing is None


def test_catalog_is_validated_normalized_and_outside_identity() -> None:
    data = source_data()
    plain = validate_project(data).require_project()
    filed = validate_project(
        {**data, "catalog": {"subject": "  Cars ", "collection": "Garage"}}
    ).require_project()
    assert filed.catalog is not None and filed.catalog.subject == "Cars"
    assert filed.to_dict()["catalog"] == {"subject": "Cars", "collection": "Garage"}
    assert build_identity(filed) == build_identity(plain)
    assert validate_project({**data, "catalog": {}}).require_project().to_dict()["catalog"] == {}
    assert issues({**data, "catalog": {"genre": "x"}}) == {("catalog.genre", "unknown_field")}
    assert issues({**data, "catalog": {"subject": "two\nlines"}}) == {("catalog.subject", "text")}
    assert issues({**data, "catalog": {"collection": ""}}) == {("catalog.collection", "text")}
    assert issues({**data, "catalog": []}) == {("catalog", "type")}


def test_print_profile_is_validated_and_part_of_identity() -> None:
    data = source_data()
    plain = validate_project(data).require_project()
    white = validate_project({**data, "print": {"profile": "paperback-8.5x11"}}).require_project()
    cream = validate_project(
        {**data, "print": {"profile": "paperback-8.5x11-cream"}}
    ).require_project()
    assert len({build_identity(plain), build_identity(white), build_identity(cream)}) == 3
    assert issues({**data, "print": {}}) == {("print.profile", "required")}
    assert issues({**data, "print": {"profile": "a4"}}) == {
        ("print.profile", "unsupported_profile")
    }
    assert issues({**data, "print": {"profile": "paperback-8.5x11", "trim": "x"}}) == {
        ("print.trim", "unknown_field")
    }
    round_trip = validate_project(json.loads(json.dumps(cream.to_dict()))).require_project()
    assert round_trip == cream and "print:" in dump_project(cream)


def write(tmp_path: Path, data: dict) -> Path:
    book = tmp_path / "book"
    book.mkdir()
    (book / "book.yaml").write_text(
        dump_project(validate_project(data).require_project()), encoding="utf-8"
    )
    return book


def test_builds_use_the_authored_profile_and_refuse_another(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = source_data()
    book = write(tmp_path, {**data, "print": {"profile": "paperback-8.5x11-cream"}})
    out = tmp_path / "out"
    assert main(["book", "build", str(book), "--output", str(out)]) == 0
    manifest = json.loads((out / "interior.json").read_text(encoding="utf-8"))
    assert manifest["print_profile"]["profile_id"] == "paperback-8.5x11-cream"
    capsys.readouterr()
    assert (
        main(["book", "build", str(book), "--output", str(out), "--profile", "paperback-8.5x11"])
        == 1
    )
    assert "profile_conflict" in capsys.readouterr().err
    # The same profile, named explicitly, is no conflict.
    profile = ["--profile", "paperback-8.5x11-cream"]
    assert main(["book", "build", str(book), "--output", str(out), *profile]) == 0
