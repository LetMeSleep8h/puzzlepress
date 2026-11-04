"""The optional `coloring` section: validation, defaults, identity and engine rules."""

import copy

import pytest

from puzzlepress import build_identity, canonical_build_inputs, dump_project, validate_project
from puzzlepress.coloring_config import Adjustments, Border, ColoringLayout
from puzzlepress.engines import EngineKind
from puzzlepress.engines.registry import engine_for
from puzzlepress.errors import ProjectError
from puzzlepress.yaml_io import load_yaml, parse_project
from tests.coloring_helpers import coloring_source

SHA = "3fa1c2d4e5f6" + "0" * 52


def source(**coloring: object) -> dict:
    data = coloring_source()
    data["coloring"] = {"version": 1, **coloring}
    return data


def artwork(identifier: str = "fox", sha: str = SHA, **extra: object) -> dict:
    return {
        "id": identifier,
        "path": f"coloring-assets/{identifier}-{sha[:12]}.png",
        "sha256": sha,
        **extra,
    }


def codes(data: dict) -> list[tuple[str, str]]:
    return [(issue.path, issue.code) for issue in validate_project(data).issues]


def test_minimal_coloring_book_loads_with_defaults():
    project = validate_project(source()).require_project()
    assert project.engine is EngineKind.COLORING
    book = project.coloring
    assert book.artwork == () and book.pages == ()
    assert book.layout == ColoringLayout(blank_reverse=True, border=Border.NONE)
    assert project.to_dict()["coloring"] == {
        "version": 1,
        "artwork": [],
        "pages": [],
        "layout": {"blank_reverse": True, "border": "none"},
    }


def test_artwork_pages_and_adjustments_normalize():
    data = source(
        artwork=[artwork(title="  Fox in the Ferns ", adjustments={"contrast": 1.25})],
        pages=[{"artwork": "fox"}, {"artwork": "fox"}],
        layout={"blank_reverse": False, "border": "thin"},
    )
    project = validate_project(data).require_project()
    item = project.coloring.artwork[0]
    assert item.title == "Fox in the Ferns"
    assert item.adjustments == Adjustments(contrast=1.25)
    assert [page.artwork for page in project.coloring.pages] == ["fox", "fox"]
    assert project.coloring.layout == ColoringLayout(False, Border.THIN)


def test_omitted_and_explicit_defaults_hash_equally_and_round_trip():
    omitted = validate_project(source(artwork=[artwork()])).require_project()
    explicit = validate_project(
        source(
            artwork=[artwork(title=None, adjustments=Adjustments().to_dict())],
            pages=[],
            layout={"blank_reverse": True, "border": "none"},
        )
    ).require_project()
    assert build_identity(omitted) == build_identity(explicit)
    text = dump_project(omitted)
    assert parse_project(text) == omitted
    assert dump_project(parse_project(text)) == text  # Serialization is stable.


def test_identity_includes_the_section_and_its_version():
    project = validate_project(source(artwork=[artwork()])).require_project()
    encoded = canonical_build_inputs(project)
    assert b'"coloring_version":1' in encoded and SHA.encode() in encoded
    changed = copy.deepcopy(source(artwork=[artwork(adjustments={"line_weight": 1})]))
    assert build_identity(validate_project(changed).require_project()) != build_identity(project)


@pytest.mark.parametrize(
    ("coloring", "expected"),
    [
        ({"version": 2}, [("coloring.version", "unsupported_version")]),
        ({"version": 1, "extra": 1}, [("coloring.extra", "unknown_field")]),
        ({"version": 1, "artwork": [artwork("Bad ID")]}, None),
        (
            {"version": 1, "artwork": [artwork(), artwork()]},
            [("coloring.artwork.1", "duplicate_id")],
        ),
        (
            {"version": 1, "pages": [{"artwork": "missing"}]},
            [("coloring.pages.0.artwork", "unknown_artwork")],
        ),
        (
            {"version": 1, "artwork": [{**artwork(), "sha256": "f" * 64}]},
            [("coloring.artwork.0.sha256", "sha256_mismatch")],
        ),
        (
            {"version": 1, "artwork": [{**artwork(), "path": "../other/coloring-assets/x.png"}]},
            [("coloring.artwork.0.path", "path")],
        ),
        (
            {"version": 1, "artwork": [{**artwork(), "path": "coloring-assets/../../x.png"}]},
            [("coloring.artwork.0.path", "path")],
        ),
        (
            {"version": 1, "artwork": [{**artwork(), "path": "cover-assets/fox-3fa1c2d4e5f6.png"}]},
            [("coloring.artwork.0.path", "path")],
        ),
        (
            {"version": 1, "artwork": [artwork(adjustments={"contrast": 9})]},
            [("coloring.artwork.0.adjustments.contrast", "range")],
        ),
        (
            {"version": 1, "artwork": [artwork(adjustments={"despeckle": True})]},
            [("coloring.artwork.0.adjustments.despeckle", "range")],
        ),
        (
            {"version": 1, "layout": {"border": "dotted"}},
            [("coloring.layout.border", "choice")],
        ),
        (
            {"version": 1, "artwork": [artwork(title="Line\nbreak")]},
            [("coloring.artwork.0.title", "text")],
        ),
        ({"version": 1, "pages": [{}] * 301}, [("coloring.pages", "count")]),
    ],
)
def test_invalid_sections_fail_with_paths(coloring, expected):
    data = coloring_source()
    data["coloring"] = coloring
    found = codes(data)
    if expected is None:
        assert ("coloring.artwork.0.id", "id") in found
    else:
        assert found == expected


def test_word_search_and_coloring_conflict(garden):
    data = garden.to_dict()
    data["coloring"] = {"version": 1}
    found = codes(data)
    assert ("coloring", "engine_conflict") in found
    assert not any(path.startswith("coloring.") for path, _ in found)


def test_coloring_books_take_no_composition_cover_or_publishing_yet():
    data = source()
    data["composition"] = {"solutions": {"placement": "omit"}}
    assert codes(data) == [("composition", "not_available_for_engine")]
    data = source()
    data["publishing"] = {"version": 2}
    assert ("publishing", "requires_composition") in codes(data)


def test_valid_coloring_book_is_not_buildable():
    project = validate_project(source()).require_project()
    with pytest.raises(ProjectError) as raised:
        engine_for(project)
    (issue,) = raised.value.issues
    assert (issue.path, issue.code) == ("coloring", "engine_not_buildable")
    assert "cannot plan, build or package" in issue.message


def test_word_search_projects_have_no_coloring_key(garden):
    assert "coloring" not in garden.to_dict()
    assert b"coloring" not in canonical_build_inputs(garden)


def test_yaml_source_with_unicode_title_round_trips(tmp_path):
    data = source(artwork=[artwork(title="Füchse im Farn 🦊")], pages=[{"artwork": "fox"}])
    project = validate_project(data).require_project()
    text = dump_project(project)
    assert validate_project(load_yaml(text)).require_project() == project
