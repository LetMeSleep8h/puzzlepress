"""Artwork import, storage, inspection, duplicates and removal for coloring books."""

import hashlib
import json
import zlib
from pathlib import Path

import pytest
from PIL import Image

from puzzlepress import load_project
from puzzlepress.asset_library import library, list_trash, restore_asset, trash_asset
from puzzlepress.coloring import assets as artwork_assets
from puzzlepress.coloring import inspection as artwork_inspection
from puzzlepress.coloring import library as artwork_library
from puzzlepress.coloring.assets import artwork_stem, artwork_title, read_artwork
from puzzlepress.coloring.inspection import inspect_artwork
from puzzlepress.coloring.issues import ArtworkError, ImportRejected
from puzzlepress.coloring.library import (
    import_files,
    library_report,
    remove_artwork,
    without_artwork,
)
from puzzlepress.errors import ProjectError
from tests.coloring_helpers import encode, line_art, png, write_coloring_book

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def book(tmp_path) -> Path:
    return write_coloring_book(tmp_path / "book")


def files_in(folder: Path) -> list[str]:
    directory = folder / "coloring-assets"
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


def coloring(folder: Path):
    return load_project(folder).project.coloring


def codes(found) -> list[str]:
    return [finding.code for finding in found.findings]


# ---------------------------------------------------------------- import


def test_import_stores_the_original_bytes_and_adds_pages(book, tmp_path):
    source = tmp_path / "Fox in the Ferns.png"
    data = png(1)
    source.write_bytes(data)
    before = source.stat().st_mtime_ns
    (result,) = import_files(book, [(source.name, source.read_bytes())])
    assert result.added and result.stored and result.page == 1
    sha = hashlib.sha256(data).hexdigest()
    assert result.path == f"coloring-assets/fox-in-the-ferns-{sha[:12]}.png"
    assert (book / result.path).read_bytes() == data
    assert source.read_bytes() == data and source.stat().st_mtime_ns == before
    item = coloring(book).artwork[0]
    assert (item.id, item.sha256, item.title) == ("fox-in-the-ferns", sha, "Fox in the Ferns")
    assert [page.artwork for page in coloring(book).pages] == ["fox-in-the-ferns"]


def test_reimport_and_duplicate_bytes_store_once(book):
    revision = (book / "book.yaml").read_bytes()
    first = import_files(book, [("a.png", png(1)), ("b.png", png(2)), ("copy.png", png(1))])
    assert [(r.id, r.added) for r in first] == [("a", True), ("b", True), ("a", False)]
    assert len(files_in(book)) == 2
    saved = (book / "book.yaml").read_bytes()
    assert saved != revision
    again = import_files(book, [("renamed.png", png(1))])
    assert [(r.id, r.added, r.stored) for r in again] == [("a", False, False)]
    assert (book / "book.yaml").read_bytes() == saved  # Nothing new: nothing written.
    assert len(files_in(book)) == 2


def test_no_page_and_unique_ids(book):
    import_files(book, [("art.png", png(1)), ("art.png", png(2))], add_pages=False)
    book_data = coloring(book)
    assert [item.id for item in book_data.artwork] == ["art", "art-2"]
    assert book_data.pages == ()


def test_detected_format_names_the_file_not_the_extension(book):
    jpeg = encode(line_art(1).convert("RGB"), "JPEG", quality=92)
    (as_jpeg, as_png) = import_files(book, [("drawing.png", jpeg), ("other.jpg", png(2))])
    assert as_jpeg.path.endswith(".jpg") and as_png.path.endswith(".png")


@pytest.mark.parametrize(
    ("name", "stem", "title"),
    [
        ("Füchse im Farn 🦊.png", "fuchse-im-farn", "Füchse im Farn 🦊"),
        ("../../escape/evil.png", "evil", "evil"),
        ("C:\\Users\\me\\Owl_Night.PNG", "owl-night", "Owl Night"),
        ("....png", "artwork", "..."),
        # Names pathlib splits differently from Python 3.14; ours must not change.
        (".png", "png", ".png"),
        ("a..png", "a", "a."),
        ("trailing.", "trailing", "trailing"),
        ("archive.tar.png", "archive-tar", "archive.tar"),
        ("no-extension", "no-extension", "no-extension"),
        ("猫.png", "artwork", "猫"),
        ("tab\there\x00.png", "tab-here", "tab here"),
        ("CON.png", "con", "CON"),
    ],
)
def test_names_are_made_safe(name, stem, title):
    assert artwork_stem(name) == stem
    assert artwork_title(name) == title


def test_traversal_names_stay_inside_coloring_assets(book, tmp_path):
    (result,) = import_files(book, [("../../../outside.png", png(1))])
    assert result.path.startswith("coloring-assets/outside-")
    assert not (tmp_path / "outside.png").exists()
    assert (book / result.path).is_file()


def test_unicode_titles_round_trip_through_book_yaml(book):
    import_files(book, [("Füchse im Farn 🦊.png", png(1))])
    assert coloring(book).artwork[0].title == "Füchse im Farn 🦊"


def _truncated() -> bytes:
    data = png(3)
    return data[: len(data) // 2]


def _sixteen_bit() -> bytes:
    return encode(Image.new("I;16", (50, 50), 1000))


SVG = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("empty.png", b"", "empty_file"),
        ("art.svg", SVG, "svg_not_supported"),
        ("disguised.png", SVG, "svg_not_supported"),
        ("upper.SVG", b"<svg/>", "svg_not_supported"),
        ("art.svgz", zlib.compress(SVG), "svg_not_supported"),
        ("noise.png", bytes(range(7, 71)), "unsupported_format"),
        ("anim.gif", b"GIF89a" + b"\x00" * 20, "unsupported_format"),
        ("page.pdf", b"%PDF-1.7\n", "unsupported_format"),
        ("half.png", _truncated(), "corrupt_image"),
        ("deep.png", _sixteen_bit(), "unsupported_color_mode"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_invalid_files_are_refused_with_codes(name, data, code):
    with pytest.raises(ArtworkError) as raised:
        inspect_artwork(data, name)
    assert raised.value.code == code
    assert raised.value.message


def test_size_and_pixel_limits(monkeypatch):
    monkeypatch.setattr(artwork_inspection, "MAX_ASSET_BYTES", 1000)
    with pytest.raises(ArtworkError) as raised:
        inspect_artwork(png(1))
    assert raised.value.code == "file_too_large"
    monkeypatch.setattr(artwork_inspection, "MAX_ASSET_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(artwork_inspection, "MAX_PIXELS", 1000)
    with pytest.raises(ArtworkError) as raised:
        inspect_artwork(png(1))
    assert raised.value.code == "too_many_pixels"


def test_one_bad_file_refuses_the_whole_batch(book):
    before = (book / "book.yaml").read_bytes()
    with pytest.raises(ImportRejected) as raised:
        import_files(book, [("good.png", png(1)), ("bad.svg", SVG), ("worse.png", b"x")])
    assert [(e.subject, e.code) for e in raised.value.errors] == [
        ("bad.svg", "svg_not_supported"),
        ("worse.png", "unsupported_format"),
    ]
    assert (book / "book.yaml").read_bytes() == before
    assert files_in(book) == []


def test_a_failed_source_write_removes_only_files_this_batch_created(book, monkeypatch):
    (kept,) = import_files(book, [("kept.png", png(1))], add_pages=False)
    before = (book / "book.yaml").read_bytes()

    def fail(*_args, **_kwargs):
        raise ProjectError(())

    monkeypatch.setattr(artwork_library, "replace_source", fail)
    with pytest.raises(ProjectError):
        import_files(book, [("new.png", png(2)), ("again.png", png(1))])
    assert (book / "book.yaml").read_bytes() == before
    assert files_in(book) == [Path(kept.path).name]


def test_a_failed_file_write_leaves_nothing_behind(book, monkeypatch):
    def broken_link(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(artwork_assets.os, "link", broken_link)
    with pytest.raises(ImportRejected) as raised:
        import_files(book, [("a.png", png(1))])
    assert raised.value.errors[0].code == "write_failed"
    assert files_in(book) == []  # No staged temporary file is left either.


def test_an_existing_file_with_other_content_is_never_replaced(book):
    data = png(1)
    sha = hashlib.sha256(data).hexdigest()
    folder = book / "coloring-assets"
    folder.mkdir()
    squatter = folder / f"art-{sha[:12]}.png"
    squatter.write_bytes(png(2))
    with pytest.raises(ImportRejected) as raised:
        import_files(book, [("art.png", data)])
    assert raised.value.errors[0].code == "asset_collision"
    assert squatter.read_bytes() == png(2)


def test_a_concurrent_source_change_is_refused(book, monkeypatch):
    original = artwork_library.import_into

    def edit_meanwhile(*args, **kwargs):
        result = original(*args, **kwargs)
        path = book / "book.yaml"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return result

    monkeypatch.setattr(artwork_library, "import_into", edit_meanwhile)
    with pytest.raises(ProjectError) as raised:
        import_files(book, [("a.png", png(1))])
    assert raised.value.issues[0].code == "source_changed"
    assert files_in(book) == []


def test_word_search_books_take_no_artwork(tmp_path):
    folder = tmp_path / "garden"
    folder.mkdir()
    (folder / "book.yaml").write_bytes((ROOT / "books/garden-demo/book.yaml").read_bytes())
    with pytest.raises(ProjectError) as raised:
        import_files(folder, [("a.png", png(1))])
    assert raised.value.issues[0].code == "not_a_coloring_book"
    assert not (folder / "coloring-assets").exists()


def test_imports_are_deterministic_across_projects(tmp_path):
    first = write_coloring_book(tmp_path / "one")
    second = write_coloring_book(tmp_path / "two")
    batch = [("b.png", png(2)), ("a.png", png(1)), ("c.jpg", png(3))]
    import_files(first, batch)
    import_files(second, batch)
    assert (first / "book.yaml").read_bytes() == (second / "book.yaml").read_bytes()
    one = library_report(first, load_project(first).project).to_dict()
    two = library_report(second, load_project(second).project).to_dict()
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)


# ---------------------------------------------------------------- reading and isolation


def test_reads_verify_the_pinned_digest(book):
    (result,) = import_files(book, [("a.png", png(1))])
    item = coloring(book).artwork[0]
    assert read_artwork(book, item) == png(1)
    (book / result.path).write_bytes(png(2))
    with pytest.raises(ArtworkError) as raised:
        read_artwork(book, item)
    assert raised.value.code == "artwork_changed"
    (book / result.path).unlink()
    with pytest.raises(ArtworkError) as raised:
        read_artwork(book, item)
    assert raised.value.code == "artwork_missing"
    report = library_report(book, load_project(book).project)
    assert report.entries[0].error.code == "artwork_missing" and report.blocking == 1


def test_projects_never_read_each_others_artwork(tmp_path):
    first = write_coloring_book(tmp_path / "one")
    second = write_coloring_book(tmp_path / "two")
    (result,) = import_files(first, [("a.png", png(1))])
    # The second book names the first book's file by its own relative path only.
    text = (first / "book.yaml").read_text(encoding="utf-8")
    (second / "book.yaml").write_text(text, encoding="utf-8")
    report = library_report(second, load_project(second).project)
    assert report.entries[0].error.code == "artwork_missing"
    assert not (second / result.path).exists()
    assert library_report(first, load_project(first).project).entries[0].error is None


def _can_symlink(tmp_path: Path) -> bool:
    try:
        (tmp_path / "probe-link").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        return False
    return True


def test_a_symlinked_artwork_folder_is_refused(tmp_path):
    if not _can_symlink(tmp_path):
        pytest.skip("Creating symlinks requires OS permission on this host")
    other = write_coloring_book(tmp_path / "other")
    import_files(other, [("a.png", png(1))])
    book = write_coloring_book(tmp_path / "book")
    (book / "coloring-assets").symlink_to(other / "coloring-assets", target_is_directory=True)
    with pytest.raises(ImportRejected) as raised:
        import_files(book, [("b.png", png(2))])
    assert raised.value.errors[0].code == "asset_unsafe"


# ---------------------------------------------------------------- inspection


def test_full_size_line_art_has_no_findings():
    found = inspect_artwork(png(1))
    info = found.info
    assert info.pixels == (2175, 2925) and info.effective_dpi == 300.0
    assert info.printed_inches == (7.25, 9.75) and info.art_box_coverage == 1.0
    assert (info.format, info.mode, info.transparent_pixels, info.in_color) == (
        "png",
        "L",
        False,
        False,
    )
    assert found.findings == () and not found.blocking


@pytest.mark.parametrize(
    ("data", "expected", "blocking"),
    [
        (encode(line_art(1, size=(1450, 1950))), ["artwork_low_resolution"], False),
        (encode(line_art(1, size=(600, 800))), ["artwork_resolution_too_low"], True),
        (encode(Image.new("L", (2175, 2925), 255)), ["artwork_empty"], True),
        (encode(line_art(1, background=200)), ["artwork_gray_background"], False),
        (encode(line_art(1, mode="RGB", background=(255, 255, 255))), [], False),
        (encode(line_art(1, size=(4000, 1500))), ["artwork_shape_mismatch"], False),
    ],
    ids=["soft", "too-low", "empty", "gray-paper", "gray-rgb", "wide"],
)
def test_findings_separate_blocking_from_warnings(data, expected, blocking):
    found = inspect_artwork(data)
    assert codes(found) == expected
    assert found.blocking is blocking


def test_color_transparency_and_cmyk_are_warnings():
    colored = line_art(1, mode="RGB", background=(255, 255, 255))
    colored.paste((220, 30, 30), (300, 300, 900, 900))
    assert "artwork_in_color" in codes(inspect_artwork(encode(colored)))
    clear = line_art(1, mode="RGBA", background=(255, 255, 255, 0))
    found = inspect_artwork(encode(clear))
    assert "artwork_transparency" in codes(found) and found.info.transparent_pixels
    assert found.info.alpha_channel and not found.blocking
    cmyk = encode(line_art(1).convert("CMYK"), "JPEG", quality=95)
    assert "artwork_cmyk" in codes(inspect_artwork(cmyk))


def test_art_touching_the_image_edge_is_flagged():
    image = line_art(1)
    image.paste(0, (0, 0, 2175, 40))  # A band of ink along the top edge.
    found = inspect_artwork(encode(image))
    finding = next(f for f in found.findings if f.code == "artwork_touches_edge")
    assert finding.actual == "top"


def test_exif_orientation_is_reported_upright():
    image = line_art(1, size=(2925, 2175)).convert("RGB")
    exif = Image.Exif()
    exif[0x0112] = 6  # Rotate 90 degrees when displayed.
    found = inspect_artwork(encode(image, "JPEG", quality=92, exif=exif))
    assert found.info.stored_pixels == (2925, 2175)
    assert found.info.pixels == (2175, 2925) and found.info.orientation == 6


def test_dpi_metadata_is_recorded_but_never_trusted():
    found = inspect_artwork(encode(line_art(1, size=(600, 800)), dpi=(1200, 1200)))
    assert found.info.dpi_metadata == (1200.0, 1200.0)
    assert found.info.effective_dpi < 150 and found.blocking


def test_inspection_never_changes_the_bytes():
    data = png(5)
    copy = bytes(data)
    inspect_artwork(data)
    assert data == copy


# ---------------------------------------------------------------- duplicates


def _yaml_with(book: Path, extra_artwork: list[dict], pages: list[str]) -> None:
    project = load_project(book).project
    data = project.to_dict()
    data["coloring"]["artwork"] += extra_artwork
    data["coloring"]["pages"] = [{"artwork": page} for page in pages]
    from puzzlepress import dump_project, validate_project

    (book / "book.yaml").write_text(
        dump_project(validate_project(data).require_project()), encoding="utf-8"
    )


def test_confirmed_and_possible_duplicates_are_reported_apart(book):
    jpeg = encode(line_art(1).convert("RGB"), "JPEG", quality=90)
    results = import_files(book, [("one.png", png(1)), ("two.png", png(2)), ("look.jpg", jpeg)])
    one = results[0]
    _yaml_with(
        book,
        [{"id": "one-again", "path": one.path, "sha256": one.sha256}],
        ["one", "two", "look", "one", "one-again"],
    )
    report = library_report(book, load_project(book).project).duplicates
    data = report.to_dict()
    assert data["confirmed"]["same_file"] == [
        {"sha256": one.sha256, "artwork": ["one", "one-again"], "pages": [1, 4, 5]}
    ]
    assert data["confirmed"]["repeated_pages"] == [{"artwork": "one", "pages": [1, 4]}]
    similar = data["possible"]["similar"]
    assert [pair["artwork"] for pair in similar] == [["look", "one"], ["look", "one-again"]]
    assert all(pair["hash_distance"] <= 10 for pair in similar)
    assert "heuristic" in data["possible"]["method"] and data["complete"]


def test_different_drawings_are_not_called_similar(book):
    import_files(book, [(f"art-{seed}.png", png(seed)) for seed in range(1, 9)])
    report = library_report(book, load_project(book).project).duplicates
    assert report.similar == () and report.confirmed == 0


def test_duplicate_report_order_ignores_library_order(tmp_path):
    jpeg = encode(line_art(1).convert("RGB"), "JPEG", quality=90)
    batch = [("one.png", png(1)), ("look.jpg", jpeg), ("two.png", png(2))]
    reports = []
    for name, order in (("a", batch), ("b", list(reversed(batch)))):
        folder = write_coloring_book(tmp_path / name)
        import_files(folder, order)
        reports.append(library_report(folder, load_project(folder).project).duplicates.to_dict())
    assert reports[0]["possible"]["similar"][0]["artwork"] == ["look", "one"]
    assert reports[0]["possible"]["similar"] == [
        {**pair, "pages": reports[0]["possible"]["similar"][0]["pages"]}
        for pair in reports[1]["possible"]["similar"]
    ]


def test_unreadable_artwork_is_listed_as_not_compared(book):
    (result,) = import_files(book, [("a.png", png(1))])
    (book / result.path).unlink()
    data = library_report(book, load_project(book).project).duplicates.to_dict()
    assert data["not_compared"] == ["a"] and not data["complete"]


# ---------------------------------------------------------------- removal and trash


def test_removal_needs_its_pages_and_keeps_the_original(book):
    (result,) = import_files(book, [("a.png", png(1))])
    with pytest.raises(ArtworkError) as raised:
        remove_artwork(book, "a")
    assert raised.value.code == "artwork_in_use"
    removed = remove_artwork(book, "a", with_pages=True)
    assert removed.pages == (1,) and not removed.file_still_referenced
    assert coloring(book).artwork == () and coloring(book).pages == ()
    assert (book / result.path).read_bytes() == png(1)


def test_removing_one_of_two_entries_keeps_the_shared_file_referenced(book):
    (result,) = import_files(book, [("a.png", png(1))], add_pages=False)
    _yaml_with(book, [{"id": "b", "path": result.path, "sha256": result.sha256}], [])
    project, removed = without_artwork(load_project(book).project, "a")
    assert removed.file_still_referenced
    with pytest.raises(ArtworkError) as raised:
        without_artwork(project, "missing")
    assert raised.value.code == "unknown_artwork"


def test_the_asset_library_lists_protects_trashes_and_restores_artwork(book):
    (result,) = import_files(book, [("a.png", png(1))])
    project = load_project(book).project
    (entry,) = [e for e in library(book, project) if e.kind == "artwork"]
    assert entry.path == result.path and entry.sha256 == result.sha256 and entry.uses
    assert entry.uses[0].path == "coloring.artwork.0" and entry.uses[0].area == "artwork"
    from puzzlepress.asset_library import AssetError

    with pytest.raises(AssetError) as raised:
        trash_asset(book, result.path, result.sha256, project)
    assert raised.value.code == "asset_in_use"
    remove_artwork(book, "a", with_pages=True)
    trashed = trash_asset(book, result.path, result.sha256, load_project(book).project)
    assert trashed.trashed.startswith("coloring-assets/.trash/")
    assert files_in(book) == [".trash"]
    assert [t.restores_to for t in list_trash(book)] == [result.path]
    assert restore_asset(book, trashed.trashed) == result.path
    assert (book / result.path).read_bytes() == png(1)


def test_word_search_asset_listings_are_unchanged(tmp_path):
    folder = tmp_path / "cover-demo"
    import shutil

    shutil.copytree(ROOT / "books" / "cover-demo", folder)
    project = load_project(folder).project
    assert all(entry.kind != "artwork" for entry in library(folder, project))
    assert all(entry.kind != "artwork" for entry in list_trash(folder))


# ---------------------------------------------------------------- CLI


def run(capsys, *args: str) -> tuple[int, str, str]:
    from puzzlepress.cli import main

    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_import_list_inspect_duplicates_remove(book, tmp_path, capsys):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    for seed in (1, 2):
        (incoming / f"art-{seed}.png").write_bytes(png(seed))
    (incoming / "small.png").write_bytes(encode(line_art(9, size=(600, 800))))
    (incoming / "vector.svg").write_bytes(SVG)
    files = [str(p) for p in sorted(incoming.iterdir())]

    code, _, err = run(capsys, "coloring", "import", str(book), *files)
    assert code == 1 and "vector.svg [svg_not_supported]" in err and "Nothing was imported" in err
    code, out, _ = run(capsys, "coloring", "import", str(book), *files[:3], "--json")
    assert code == 0 and [a["id"] for a in json.loads(out)["artwork"]] == [
        "art-1",
        "art-2",
        "small",
    ]
    code, out, _ = run(capsys, "coloring", "list", str(book))
    assert code == 0 and "3 artwork, 3 pages" in out and "Puzzle" not in out
    code, out, _ = run(capsys, "coloring", "inspect", str(book), "small")
    assert code == 1 and "artwork_resolution_too_low" in out
    code, out, _ = run(capsys, "coloring", "inspect", str(book), "--file", files[3], "--json")
    assert code == 1 and json.loads(out)["files"][0]["error"]["code"] == "svg_not_supported"
    code, out, _ = run(capsys, "coloring", "duplicates", str(book))
    assert code == 0 and "No duplicate" in out
    code, out, err = run(capsys, "coloring", "remove", str(book), "art-2")
    assert code == 1 and "artwork_in_use" in err
    code, out, _ = run(capsys, "coloring", "remove", str(book), "art-2", "--with-pages", "--trash")
    assert code == 0 and "restorable" in out
    assert [t.restores_to.split("/")[1][:5] for t in list_trash(book)] == ["art-2"]


def test_cli_refuses_directories_and_word_search_books(book, tmp_path, capsys):
    code, _, err = run(capsys, "coloring", "import", str(book), str(tmp_path))
    assert code == 1 and "[not_a_file]" in err
    code, _, err = run(capsys, "coloring", "list", str(ROOT / "books" / "garden-demo"))
    assert code == 1 and "not_a_coloring_book" in err and "Traceback" not in err


def test_publishing_and_production_refuse_coloring_books(book, capsys, tmp_path):
    import_files(book, [("a.png", png(1))])
    code, _, err = run(capsys, "publish", "inspect", str(book))
    assert code == 1 and "Traceback" not in err
    code, _, err = run(capsys, "book", "produce", str(book), "--output", str(tmp_path / "out"))
    assert code == 1 and "not_available_for_engine" in err and "Traceback" not in err
    code, _, err = run(capsys, "puzzle", "batch", str(book))
    assert code == 1 and "Traceback" not in err
