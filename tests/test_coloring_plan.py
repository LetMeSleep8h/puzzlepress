"""Coloring composition, publication plans and their independent parity verification.

Every book here is SYNTHETIC (tests/coloring_helpers.py).
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from coloring_helpers import composed_coloring_book, encode, line_art

from puzzlepress import validate_project
from puzzlepress.cli import main
from puzzlepress.coloring.content import ColoringContent, prepare_content
from puzzlepress.coloring.plan import plan_coloring, verify_coloring_plan
from puzzlepress.composition import PageNumberPolicy
from puzzlepress.engines.kind import EngineKind
from puzzlepress.engines.registry import ENGINES, engine_for
from puzzlepress.errors import ProjectError
from puzzlepress.identity import build_identity
from puzzlepress.project import load_project
from puzzlepress.publication import (
    ARTWORK_BLANK_REASON,
    BLANK_REASON,
    DIVIDER_BLANK_REASON,
    REVERSE_BLANK_REASON,
    PageKind,
    PublicationPlan,
)


def plan_of(directory: Path) -> tuple[PublicationPlan, ColoringContent]:
    project = load_project(directory).project
    content, plan = engine_for(project).build_publication(project, directory)
    assert isinstance(content, ColoringContent)
    return plan, content


def shape(plan: PublicationPlan) -> list[str]:
    """Each page as kind, with the blank reason for blanks."""
    return [
        f"blank:{p.blank_reason}" if p.kind is PageKind.BLANK else p.kind.value for p in plan.pages
    ]


def verified(plan: PublicationPlan, directory: Path, content: ColoringContent) -> list[str]:
    project = load_project(directory).project
    return [issue.code for issue in verify_coloring_plan(plan, project, content).issues]


# ------------------------------------------------------------------- composition


def coloring_data(tmp_path: Path) -> dict[str, object]:
    return load_project(composed_coloring_book(tmp_path / "book", 1)).project.to_dict()


def codes(data: dict[str, object]) -> list[tuple[str, str]]:
    return [(i.path, i.code) for i in validate_project(data).issues]


def test_coloring_composition_serializes_without_puzzle_terms(tmp_path):
    data = coloring_data(tmp_path)
    assert data["composition"] == {
        "front_matter": [
            {"kind": "title_page"},
            {
                "kind": "copyright_page",
                "text": "Copyright 2026 Synthetic Author. All rights reserved.",
            },
        ],
        "artwork": {"start": "recto"},
        "back_matter": [],
        "page_numbers": {
            "scheme": "continuous",
            "show_front_matter": False,
            "show_artwork": True,
            "show_back_matter": True,
        },
    }


def test_word_search_page_numbers_keep_their_fields():
    assert PageNumberPolicy().to_dict() == {
        "scheme": "continuous",
        "show_front_matter": False,
        "show_solutions": True,
        "show_back_matter": True,
    }


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"puzzles": {"start": "any"}}, ("composition.puzzles", "not_applicable_for_engine")),
        (
            {"solutions": {"placement": "omit"}},
            ("composition.solutions", "not_applicable_for_engine"),
        ),
        (
            {"page_numbers": {"show_solutions": True}},
            ("composition.page_numbers.show_solutions", "not_applicable_for_engine"),
        ),
        ({"artwork": {"start": "left"}}, ("composition.artwork.start", "choice")),
        ({"artwork": {"reverse": True}}, ("composition.artwork.reverse", "unknown_field")),
        (
            {"page_numbers": {"show_artwork": "yes"}},
            ("composition.page_numbers.show_artwork", "type"),
        ),
        ({"extra": 1}, ("composition.extra", "unknown_field")),
        (
            {"page_numbers": {"scheme": "roman_front_matter"}, "front_matter": []},
            ("composition.page_numbers.scheme", "requires_front_matter"),
        ),
    ],
)
def test_invalid_coloring_compositions_are_reported(tmp_path, change, expected):
    data = coloring_data(tmp_path)
    composition = data["composition"]
    assert isinstance(composition, dict)
    composition.update(change)
    assert expected in codes(data)


def test_word_search_composition_rejects_coloring_settings():
    composed = load_project(Path("books/composition-demo")).project
    data = composed.to_dict()
    data["composition"]["page_numbers"]["show_artwork"] = True
    assert ("composition.page_numbers.show_artwork", "unknown_field") in codes(data)
    data = composed.to_dict()
    data["composition"]["artwork"] = {"start": "recto"}
    assert ("composition.artwork", "unknown_field") in codes(data)


def test_coloring_books_take_cover_and_publishing_but_no_interior_style(tmp_path):
    # Interval 5: covers and publishing metadata are the shared sections; interior
    # styles (grids, word lists, solution pages) stay word search.
    data = coloring_data(tmp_path)
    data["interior"] = {"version": 1}
    assert codes(data) == [("interior", "not_available_for_engine")]
    for section in ("cover", "publishing"):
        data = coloring_data(tmp_path)
        data[section] = {"version": 1}
        assert not [code for _, code in codes(data) if code == "not_available_for_engine"]


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        ({"divider": {}}, ("coloring.pages.1.divider.title", "required")),
        ({"divider": {"title": " "}}, ("coloring.pages.1.divider.title", "text")),
        ({"divider": {"title": "A", "text": "x" * 601}}, ("coloring.pages.1.divider.text", "text")),
        ({"divider": {"title": "A", "art": 1}}, ("coloring.pages.1.divider.art", "unknown_field")),
        (
            {"divider": {"title": "A"}, "artwork": "drawing-1"},
            ("coloring.pages.1.artwork", "unknown_field"),
        ),
        ({}, ("coloring.pages.1.artwork", "required")),
    ],
)
def test_invalid_divider_entries_are_reported(tmp_path, page, expected):
    data = coloring_data(tmp_path)
    coloring = data["coloring"]
    assert isinstance(coloring, dict)
    coloring["pages"].append(page)
    assert expected in codes(data)


def test_divider_entries_round_trip(tmp_path):
    data = coloring_data(tmp_path)
    coloring = data["coloring"]
    assert isinstance(coloring, dict)
    coloring["pages"].insert(0, {"divider": {"title": "Woodland", "text": "Two\nlines"}})
    project = validate_project(data).require_project()
    assert project.to_dict()["coloring"]["pages"][0] == {
        "divider": {"title": "Woodland", "text": "Two\nlines"}
    }


# --------------------------------------------------------------------- page parity


@pytest.mark.parametrize("count", [0, 1, 2, 3, 9])
@pytest.mark.parametrize("front", [0, 1, 2, 3])
@pytest.mark.parametrize("reverse", [True, False])
def test_parity_for_every_count_and_front_matter_length(tmp_path, count, front, reverse):
    directory = composed_coloring_book(tmp_path / "book", count, front=front, reverse=reverse)
    plan, content = plan_of(directory)
    assert verified(plan, directory, content) == []
    art = [p for p in plan.pages if p.kind is PageKind.COLORING]
    assert [p.artwork.id for p in art if p.artwork] == [f"drawing-{i + 1}" for i in range(count)]
    # The artwork section starts recto; with reverses every drawing is recto and backed.
    if art:
        assert art[0].index % 2 == 1
    for page in art:
        if reverse:
            assert page.index % 2 == 1
            assert plan.pages[page.index].blank_reason == REVERSE_BLANK_REASON
    # Every blank is explained, and the only blank runs are single pages.
    blanks = [p for p in plan.pages if p.kind is PageKind.BLANK]
    assert all(p.blank_reason for p in blanks)
    assert not any(
        a.kind is PageKind.BLANK and b.kind is PageKind.BLANK
        for a, b in zip(plan.pages, plan.pages[1:], strict=False)
    )
    # Odd front matter needs exactly one blank before a (nonempty) artwork section.
    starts = [p for p in blanks if p.blank_reason == BLANK_REASON]
    assert len(starts) == (front % 2 if count else 0)
    stats = plan.statistics
    assert stats.artwork_pages == count
    assert stats.logical_pages == len(plan.pages)
    assert stats.reverse_blank_pages == (count if reverse else 0)
    if count == 0:
        assert [d.code for d in plan.diagnostics] == ["no_coloring_pages"]
        assert not plan.complete
    else:
        assert plan.complete


@pytest.mark.parametrize(
    ("front", "reverse", "expected"),
    [
        (
            3,
            True,
            [
                "title_page",
                "copyright_page",
                "instructions",
                f"blank:{BLANK_REASON}",
                "coloring",
                f"blank:{REVERSE_BLANK_REASON}",
                "divider",
                f"blank:{REVERSE_BLANK_REASON}",
                "coloring",
                f"blank:{REVERSE_BLANK_REASON}",
                "coloring",
                f"blank:{REVERSE_BLANK_REASON}",
            ],
        ),
        (
            2,
            False,
            [
                "title_page",
                "copyright_page",
                "coloring",
                f"blank:{DIVIDER_BLANK_REASON}",
                "divider",
                "coloring",
                "coloring",
            ],
        ),
    ],
)
def test_dividers_keep_their_alignment(tmp_path, front, reverse, expected):
    directory = composed_coloring_book(
        tmp_path / "book", 3, front=front, reverse=reverse, dividers={1: "Woodland"}
    )
    plan, content = plan_of(directory)
    assert shape(plan) == expected
    assert verified(plan, directory, content) == []
    divider = next(p for p in plan.pages if p.kind is PageKind.DIVIDER)
    assert divider.index % 2 == 1
    assert divider.divider is not None and divider.divider.title == "Woodland"
    assert not divider.number.displayed


def test_section_start_any_lets_double_sided_art_begin_on_a_left_page(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 2, front=1, reverse=False, start="any")
    plan, content = plan_of(directory)
    assert shape(plan) == ["title_page", "coloring", "coloring"]
    assert verified(plan, directory, content) == []


def test_reverse_pages_force_recto_even_when_the_section_may_start_anywhere(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1, front=1, start="any")
    plan, _ = plan_of(directory)
    assert shape(plan) == [
        "title_page",
        f"blank:{ARTWORK_BLANK_REASON}",
        "coloring",
        f"blank:{REVERSE_BLANK_REASON}",
    ]


def test_consecutive_dividers_each_start_recto(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1, front=0, dividers={0: "Part one"})
    project = load_project(directory).project
    data = project.to_dict()
    data["coloring"]["pages"].insert(0, {"divider": {"title": "Book one"}})
    (directory / "book.yaml").write_text(
        __import__("puzzlepress").dump_project(validate_project(data).require_project()),
        encoding="utf-8",
    )
    plan, content = plan_of(directory)
    assert [p.index for p in plan.pages if p.kind is PageKind.DIVIDER] == [1, 3]
    assert verified(plan, directory, content) == []


def test_page_numbers_follow_policy_and_count_every_page(tmp_path):
    directory = composed_coloring_book(
        tmp_path / "book",
        2,
        front=3,
        numbers={"scheme": "roman_front_matter", "show_front_matter": True, "show_artwork": False},
        back=[{"kind": "notes", "title": "Notes"}],
    )
    plan, content = plan_of(directory)
    assert verified(plan, directory, content) == []
    labels = [(p.kind.value, p.number.label, p.number.displayed) for p in plan.pages]
    assert labels == [
        ("title_page", "i", True),
        ("copyright_page", "ii", True),
        ("instructions", "iii", True),
        ("blank", "iv", False),
        ("coloring", "1", False),
        ("blank", "2", False),
        ("coloring", "3", False),
        ("blank", "4", False),
        ("notes", "5", True),
    ]


def test_plan_json_has_no_puzzle_terms(tmp_path, capsys):
    directory = composed_coloring_book(tmp_path / "book", 2, dividers={1: "Woodland"})
    assert main(["book", "plan", str(directory), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    text = json.dumps(payload)
    for term in ("puzzle", "solution", "word"):
        assert term not in text
    assert payload["plan"]["engine"] == "coloring"
    assert payload["verification"] == {"valid": True, "issues": []}
    assert payload["plan"]["statistics"]["artwork_pages"] == 2
    page = payload["plan"]["pages"][2]
    assert page["artwork"]["id"] == "drawing-1"
    assert page["artwork"]["prepared"].startswith("sha256-")


def test_book_plan_reports_an_empty_book(tmp_path, capsys):
    directory = composed_coloring_book(tmp_path / "book", 0)
    assert main(["book", "plan", str(directory)]) == 1
    captured = capsys.readouterr()
    assert "no_coloring_pages" in captured.err
    assert "coloring pages: 0" in captured.out


def test_a_coloring_book_without_composition_fails_with_guidance(tmp_path, capsys):
    directory = composed_coloring_book(tmp_path / "book", 1)
    data = load_project(directory).project.to_dict()
    del data["composition"]
    (directory / "book.yaml").write_text(
        __import__("puzzlepress").dump_project(validate_project(data).require_project()),
        encoding="utf-8",
    )
    assert main(["book", "plan", str(directory)]) == 1
    err = capsys.readouterr().err
    assert "composition [required]" in err
    assert "artwork: {start:" in err


# ------------------------------------------------------------ content and identity


def test_missing_and_altered_artwork_make_the_plan_incomplete(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 2)
    project = load_project(directory).project
    assert project.coloring is not None
    first, second = project.coloring.artwork
    (directory / first.path).unlink()
    (directory / second.path).write_bytes(encode(line_art(99, (300, 400))))
    plan, content = plan_of(directory)
    assert {d.code for d in plan.diagnostics} == {"artwork_unavailable"}
    messages = " ".join(d.message for d in plan.diagnostics)
    assert "missing" in messages and "no longer matches" in messages
    assert set(content.failures) == {first.id, second.id}
    assert [p.artwork.prepared for p in plan.pages if p.artwork] == ["", ""]
    assert verified(plan, directory, content) == []


def test_preparation_settings_change_identity_and_prepared_digest(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1)
    project = load_project(directory).project
    before, content = plan_of(directory)
    data = project.to_dict()
    data["coloring"]["artwork"][0]["adjustments"]["line_weight"] = 1
    changed = validate_project(data).require_project()
    after_content, after = ENGINES[EngineKind.COLORING].build_publication(changed, directory)
    assert build_identity(changed) != build_identity(project)
    assert after.identity != before.identity
    first = next(p.artwork for p in before.pages if p.artwork)
    second = next(p.artwork for p in after.pages if p.artwork)
    assert first and second and first.source == second.source
    assert first.prepared != second.prepared


def test_packed_samples_round_trip_exactly(tmp_path):
    gray = line_art(4, (301, 203))
    gray.putpixel((5, 5), 128)  # A gray level forces 8-bit samples.
    for image, bits in ((line_art(3, (301, 203)), 1), (gray, 8)):
        directory = composed_coloring_book(tmp_path / f"book{bits}", 1, images=[image])
        _, content = plan_of(directory)
        (art,) = content.art.values()
        assert art.bits == bits
        assert art.image().tobytes() == image.tobytes()


def test_prepared_content_requires_the_project_folder(tmp_path):
    project = load_project(composed_coloring_book(tmp_path / "book", 1)).project
    with pytest.raises(ProjectError) as raised:
        prepare_content(project, None)
    assert raised.value.issues[0].code == "project_folder_required"


def test_engines_refuse_each_others_content(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1)
    project = load_project(directory).project
    plan, content = plan_of(directory)
    with pytest.raises(TypeError):
        ENGINES[EngineKind.WORD_SEARCH].verify_publication(plan, project, content)
    composed = load_project(Path("books/composition-demo")).project
    report, word_plan = engine_for(composed).build_publication(composed)
    with pytest.raises(TypeError):
        ENGINES[EngineKind.COLORING].verify_publication(word_plan, composed, report)


def test_plan_requires_content_from_the_same_source(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 1)
    project = load_project(directory).project
    _, content = plan_of(directory)
    with pytest.raises(ValueError, match="not made from this project"):
        plan_coloring(replace(project, build=replace(project.build, seed=2)), content)


# -------------------------------------------------------------- corrupted plans


def corrupt(plan: PublicationPlan, pages: list) -> PublicationPlan:
    return replace(plan, pages=tuple(pages))


def test_verifier_catches_corrupted_plans(tmp_path):
    directory = composed_coloring_book(tmp_path / "book", 3, front=2, dividers={1: "Woodland"})
    plan, content = plan_of(directory)
    pages = list(plan.pages)
    art = [i for i, p in enumerate(pages) if p.kind is PageKind.COLORING]

    def check(changed: list, code: str) -> None:
        assert code in verified(corrupt(plan, changed), directory, content)

    # Two drawings swapped: their content no longer follows the authored order.
    swapped = pages.copy()
    swapped[art[0]] = replace(pages[art[0]], artwork=pages[art[1]].artwork)
    check(swapped, "artwork_ref")
    # A drawing moved onto a left-hand page by deleting the blank before it.
    shifted = [replace(p, index=i + 1) for i, p in enumerate(pages[:3] + pages[4:])]
    check(shifted, "parity")
    # A reverse blank dropped.
    dropped = pages[: art[0] + 1] + pages[art[0] + 2 :]
    dropped = [replace(p, index=i + 1) for i, p in enumerate(dropped)]
    check(dropped, "reverse_blank")
    # The prepared digest is not the content's.
    wrong = pages.copy()
    ref = pages[art[0]].artwork
    assert ref is not None
    wrong[art[0]] = replace(pages[art[0]], artwork=replace(ref, prepared="sha256-" + "0" * 64))
    check(wrong, "prepared_digest")
    # A folio printed on a blank page.
    blank = next(i for i, p in enumerate(pages) if p.kind is PageKind.BLANK)
    numbered = pages.copy()
    numbered[blank] = replace(pages[blank], number=replace(pages[blank].number, displayed=True))
    check(numbered, "folio")
    # An unexplained blank.
    unknown = pages.copy()
    unknown[blank] = replace(pages[blank], blank_reason="padding")
    check(unknown, "blank_reason")
    # Dividers keep their authored words.
    divider = next(i for i, p in enumerate(pages) if p.kind is PageKind.DIVIDER)
    retitled = pages.copy()
    assert pages[divider].divider is not None
    retitled[divider] = replace(
        pages[divider], divider=replace(pages[divider].divider, title="Changed")
    )
    check(retitled, "artwork_order")
    # A page from another book.
    assert "identity" in verified(replace(plan, identity="pp1-sha256-0"), directory, content)
