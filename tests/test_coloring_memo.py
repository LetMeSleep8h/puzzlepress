"""The in-process memo of packed prepared drawings: every input in the key, no bypass."""

import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from puzzlepress.coloring import content
from puzzlepress.coloring.content import DEFLATE_LEVEL, prepare_content
from puzzlepress.coloring_config import Adjustments
from puzzlepress.project import load_project
from tests.coloring_helpers import composed_coloring_book


@pytest.fixture
def book(tmp_path: Path) -> Path:
    return composed_coloring_book(tmp_path / "book", 2)


def with_adjustments(project, adjustments: Adjustments):  # type: ignore[no-untyped-def]
    coloring = project.coloring
    artwork = tuple(replace(a, adjustments=adjustments) for a in coloring.artwork)
    return replace(project, coloring=replace(coloring, artwork=artwork))


def test_second_preparation_reuses_and_changed_settings_miss(book: Path) -> None:
    content.PACKED.clear()
    project = load_project(book).project
    first = prepare_content(project, book)
    assert content.PACKED.misses == 2 and content.PACKED.hits == 0
    again = prepare_content(project, book)
    assert content.PACKED.hits == 2
    assert {k: v.samples for k, v in again.art.items()} == {
        k: v.samples for k, v in first.art.items()
    }
    thicker = prepare_content(with_adjustments(project, Adjustments(line_weight=1)), book)
    assert content.PACKED.hits == 2 and content.PACKED.misses == 4
    assert all(thicker.art[k].digest != first.art[k].digest for k in first.art)


def test_changed_artwork_bytes_are_never_answered_from_memory(book: Path) -> None:
    content.PACKED.clear()
    project = load_project(book).project
    assert not prepare_content(project, book).failures
    artwork = project.coloring.artwork[0]
    path = book / artwork.path
    original = path.read_bytes()
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))  # One flipped bit.
    tampered = prepare_content(project, book)
    assert artwork.id in tampered.failures and artwork.id not in tampered.art
    path.unlink()
    assert artwork.id in prepare_content(project, book).failures
    path.write_bytes(original)
    assert not prepare_content(project, book).failures


def test_keys_name_the_deflate_level_and_zlib_build(
    book: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content.PACKED.clear()
    project = load_project(book).project
    prepare_content(project, book)
    keys = list(content.PACKED._values)
    assert all(k.endswith(f":deflate-{DEFLATE_LEVEL}:{zlib.ZLIB_RUNTIME_VERSION}") for k in keys)
    monkeypatch.setattr(content.zlib, "ZLIB_RUNTIME_VERSION", "other-zlib")
    prepare_content(project, book)
    assert content.PACKED.hits == 0  # Another zlib build packs other bytes: no reuse.


def test_titles_follow_the_current_source(book: Path) -> None:
    content.PACKED.clear()
    project = load_project(book).project
    prepare_content(project, book)
    coloring = project.coloring
    renamed = replace(
        project,
        coloring=replace(
            coloring, artwork=(replace(coloring.artwork[0], title="Renamed"), *coloring.artwork[1:])
        ),
    )
    art = prepare_content(renamed, book).art[coloring.artwork[0].id]
    assert content.PACKED.hits == 2 and art.artwork.title == "Renamed"
