"""Previous-book duplicate detection: inventories, PDF extraction, comparison, reports.

All data is synthetic: small hand-written inventories and books built from the
composition demo into temporary directories.
"""

import json

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from puzzlepress.answer_key import check_answer_key
from puzzlepress.duplicates import (
    Thresholds,
    compare_inventories,
    compare_pair,
    grid_agreement,
    report_json,
    report_markdown,
)
from puzzlepress.inventory import (
    Coverage,
    Inventory,
    InventoryError,
    InventoryPuzzle,
    inventory_from_pdf,
    inventory_from_project,
    inventory_json,
    load_inventory,
    parse_inventory,
)
from puzzlepress.yaml_io import dump_project
from tests.helpers import demo_variant

GRID = ("ABCD", "EFGH", "IJKL", "MNOP")


def puzzle(pid, words, grid=None, status="verified"):
    return InventoryPuzzle(pid, tuple(sorted(words)), grid, status, title=pid.title())


def inventory(label, *puzzles, status="complete"):
    return Inventory(
        label, "inventory", f"{label}.json", "0" * 64, puzzles, Coverage(status, None, None)
    )


T = Thresholds()


# ------------------------------------------------------------------ pair rules


def test_equivalent_word_sets_in_another_order_are_exact() -> None:
    match = compare_pair(
        puzzle("a", ["PISTON", "VALVE", "CAM"]), puzzle("b", ["CAM", "VALVE", "PISTON"]), "old", T
    )
    assert match is not None and match.severity == "exact"
    assert match.reasons == ("identical_words",)


def test_identical_and_rotated_grids_are_exact() -> None:
    rotated = tuple("".join(row[i] for row in GRID)[::-1] for i in range(4))
    for other, transform in ((GRID, {"identity"}), (rotated, {"rotate_90", "rotate_270"})):
        match = compare_pair(puzzle("a", ["X"], GRID), puzzle("b", ["Y"], other), "old", T)
        assert match is not None and match.severity == "exact"
        assert "identical_grid" in match.reasons
        assert match.grid_transform in transform


def test_grid_agreement_needs_equal_shapes() -> None:
    assert grid_agreement(GRID, ("ABC", "DEF")) == (None, None)
    assert grid_agreement(GRID, None) == (None, None)
    assert grid_agreement(("AB", "CD"), ("AB", "CX"))[0] == 0.75


def test_near_duplicates_by_jaccard_overlap_and_grid() -> None:
    base = ["A" * 3, "B" * 3, "C" * 3, "D" * 3, "E" * 3]
    jaccard = compare_pair(puzzle("a", base), puzzle("b", base[:4] + ["ZZZ"]), "old", T)
    assert jaccard is not None and jaccard.severity == "near"
    assert "word_jaccard" in jaccard.reasons
    contained = compare_pair(
        puzzle("a", base[:3]), puzzle("b", base + ["F" * 3, "G" * 3]), "old", T
    )
    assert contained is not None and contained.reasons == ("word_overlap",)
    similar = ("ABCD", "EFGH", "IJKL", "MNOQ")
    grid = compare_pair(puzzle("a", ["X"], GRID), puzzle("b", ["Y"], similar), "old", T)
    assert grid is not None and grid.reasons == ("grid_agreement",)
    assert grid.grid_agreement == pytest.approx(15 / 16)


def test_unrelated_puzzles_do_not_match_and_thresholds_are_configurable() -> None:
    left, right = puzzle("a", ["AAA", "BBB", "CCC"]), puzzle("b", ["AAA", "XXX", "YYY", "ZZZ"])
    assert compare_pair(left, right, "old", T) is None
    loose = Thresholds(word_jaccard=0.15)
    assert compare_pair(left, right, "old", loose) is not None


@pytest.mark.parametrize(
    "kwargs",
    [{"word_jaccard": 0}, {"word_overlap": 1.5}, {"grid_agreement": -1}, {"min_shared_words": 0}],
)
def test_malformed_thresholds_are_rejected(kwargs) -> None:
    with pytest.raises(InventoryError):
        Thresholds(**kwargs)


# --------------------------------------------------------------- whole reports


def test_report_separates_exact_near_within_book_and_unverified() -> None:
    old = inventory(
        "book-1",
        puzzle("p1", ["AAA", "BBB", "CCC"]),
        puzzle("p2", ["DDD", "EEE", "FFF", "GGG", "HHH"]),
        puzzle("p3", ["QQQ"], status="unverified"),
    )
    new = inventory(
        "book-2",
        puzzle("n1", ["CCC", "BBB", "AAA"]),
        puzzle("n2", ["DDD", "EEE", "FFF", "GGG", "III"]),
        puzzle("n3", ["JJJ", "KKK", "LLL"]),
        puzzle("n4", ["LLL", "KKK", "JJJ"]),
    )
    report = compare_inventories(new, [old], candidates={"n2": ("WWW", "VVV")})
    assert [(m.new_id, m.other_id) for m in report.exact] == [("n1", "p1"), ("n3", "n4")]
    assert [(m.new_id, m.other_id) for m in report.near] == [("n2", "p2")]
    assert report.exact[1].other_source == "new book"
    assert report.verdict == "exact_duplicates" and not report.clean
    data = report.to_dict()
    assert data["counts"] == {
        "new_puzzles": 4,
        "previous_puzzles": 3,
        "exact": 2,
        "near": 1,
        "within_new_book": 1,
    }
    assert data["previous_books"][0]["unverified"][0]["id"] == "p3"
    rec = {r.puzzle_id: r for r in report.recommendations}
    assert rec["n2"].replace_at_least == 1 and rec["n2"].candidates == ("WWW", "VVV")
    assert rec["n1"].replace_at_least == 1
    text = report_markdown(report)
    for heading in ("Exact duplicates (2)", "Near duplicates (1)", "Unverified puzzles (1)"):
        assert heading in text
    assert report_json(report) == report_json(
        compare_inventories(new, [old], candidates={"n2": ("WWW", "VVV")})
    )


def test_clean_needs_complete_coverage_everywhere() -> None:
    new = inventory("new", puzzle("n1", ["AAA", "BBB"]))
    old = inventory("old", puzzle("p1", ["CCC", "DDD"]), status="unconfirmed")
    report = compare_inventories(new, [old])
    assert not report.matches and report.verdict == "incomplete_coverage" and not report.clean
    assert compare_inventories(new, [inventory("old", puzzle("p1", ["CCC"]))]).clean


def test_matches_against_unverified_puzzles_say_so() -> None:
    old = inventory("old", puzzle("p1", ["AAA", "BBB"], status="unverified"), status="incomplete")
    report = compare_inventories(inventory("new", puzzle("n1", ["BBB", "AAA"])), [old])
    assert report.exact[0].other_verified is False
    assert "[other puzzle unverified]" in report_markdown(report)


# ------------------------------------------------------ project and PDF sources


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from puzzlepress.interior import build_interior, write_interior
    from puzzlepress.interior.spec import PAPERBACK_LETTER

    root = tmp_path_factory.mktemp("dup")
    source = root / "My Book ü"
    source.mkdir()
    project = demo_variant()
    (source / "book.yaml").write_text(dump_project(project), encoding="utf-8")
    out = root / "release dir"
    write_interior(build_interior(project, PAPERBACK_LETTER), out, source)
    return source, out / "interior.pdf", len(project.word_search.puzzles)


def test_project_inventory_is_complete_and_reproducible(built) -> None:
    source, _, count = built
    first = inventory_from_project(source)
    assert first.coverage.status == "complete" and len(first.verified) == count
    assert inventory_json(first) == inventory_json(inventory_from_project(source / "book.yaml"))
    assert "/" not in first.source_name and str(source) not in inventory_json(first)


def test_pdf_extraction_matches_the_source(built) -> None:
    source, pdf, count = built
    from_pdf = inventory_from_pdf(pdf, expected_puzzles=count)
    from_source = inventory_from_project(source)
    assert from_pdf.coverage.status == "complete"
    assert [(p.words, p.grid) for p in from_pdf.puzzles] == [
        (p.words, p.grid) for p in from_source.puzzles
    ]
    assert inventory_from_pdf(pdf).coverage.status == "unconfirmed"
    assert inventory_from_pdf(pdf, expected_puzzles=count + 1).coverage.status == "incomplete"
    report = compare_inventories(from_source, [from_pdf])
    assert len(report.exact) == count


def _rewrite(pdf, target, replace_page):
    reader = PdfReader(pdf)
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        replacement = replace_page(index, page)
        writer.add_page(replacement if replacement is not None else page)
    with open(target, "wb") as stream:
        writer.write(stream)


def _image_page(path):
    canvas = Canvas(str(path), pagesize=(612, 792))
    from PIL import Image

    image = path.with_suffix(".png")
    Image.new("RGB", (8, 8), (90, 90, 90)).save(image)
    canvas.drawImage(str(image), 72, 72, 200, 200)
    canvas.showPage()
    canvas.save()
    return PdfReader(path).pages[0]


def test_unextractable_pages_make_coverage_incomplete(built, tmp_path) -> None:
    _, pdf, count = built
    first_puzzle = inventory_from_pdf(pdf).puzzles[0].page - 1
    scanned = _image_page(tmp_path / "scan.pdf")
    damaged = tmp_path / "damaged.pdf"
    _rewrite(pdf, damaged, lambda i, _: scanned if i == first_puzzle else None)
    result = inventory_from_pdf(damaged, expected_puzzles=count)
    assert result.coverage.status == "incomplete"
    assert len(result.verified) == count - 1
    assert any(s.reason == "no_text" for s in result.skipped_pages)
    # Without a count the image-only page still prevents a complete claim.
    assert inventory_from_pdf(damaged).coverage.status == "incomplete"


def test_inventory_json_round_trips_and_rejects_malformed_files(built, tmp_path) -> None:
    _, pdf, count = built
    text = inventory_json(inventory_from_pdf(pdf, expected_puzzles=count))
    loaded = parse_inventory(text)
    assert [p.to_dict() for p in loaded.puzzles] == json.loads(text)["puzzles"]
    data = json.loads(text)
    bad = [
        "not json",
        json.dumps({"kind": "other"}),
        json.dumps({**data, "inventory_version": 9}),
        json.dumps({**data, "puzzles": [{**data["puzzles"][0], "words": ["fuel pump"]}]}),
        json.dumps({**data, "puzzles": [{**data["puzzles"][0], "grid": ["AB", "C"]}]}),
        json.dumps({**data, "puzzles": data["puzzles"][:1] * 2}),
        json.dumps(
            {**data, "puzzles": [{**data["puzzles"][0], "status": "unverified"}]}
        ),  # complete coverage cannot list unverified puzzles
    ]
    for case in bad:
        with pytest.raises(InventoryError):
            parse_inventory(case)


def test_load_inventory_detects_each_source_kind(built, tmp_path) -> None:
    source, pdf, count = built
    saved = tmp_path / "saved inventory.json"
    saved.write_text(inventory_json(inventory_from_project(source)), encoding="utf-8")
    assert load_inventory(source).source_kind == "project"
    assert load_inventory(pdf.parent, count).source_kind == "pdf"
    assert load_inventory(pdf.parent, count).label == "release dir"
    assert load_inventory(saved).source_kind == "inventory"
    for missing in (tmp_path / "nope.pdf", tmp_path):
        with pytest.raises(InventoryError):
            load_inventory(missing)
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(InventoryError):
        load_inventory(tmp_path / "notes.txt")


def test_answer_key_read_back(built, tmp_path) -> None:
    _, pdf, count = built
    result = check_answer_key(pdf)
    assert result.complete and result.matched == result.solutions == count
    pages = PdfReader(pdf).pages
    last = len(pages) - 1
    while "Solutions" not in (pages[last].extract_text() or "") and last > 0:
        last -= 1
    truncated = tmp_path / "missing-solution.pdf"
    blank = PdfWriter().add_blank_page(612, 792)
    _rewrite(pdf, truncated, lambda i, _: blank if i == last else None)
    broken = check_answer_key(truncated)
    assert not broken.complete
    assert any("no solution grid" in issue for issue in broken.issues)
