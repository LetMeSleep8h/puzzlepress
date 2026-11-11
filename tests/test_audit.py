"""`book audit`: read-only, prioritized, evidence-backed recommendations.

Every book here is SYNTHETIC (composition-demo variants and disposable copies).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from puzzlepress import load_project
from puzzlepress.audit import OtherBook, Priority, audit_book, audit_bytes, audit_markdown
from puzzlepress.audit.content import content_recommendations, is_backward, is_diagonal, level_facts
from puzzlepress.audit.evidence import evidence_recommendations, manual_checks
from puzzlepress.audit.listing import BookFacts, claims_progression, listing_recommendations
from puzzlepress.audit.pages import page_recommendations
from puzzlepress.audit.report import puzzle_pages, theme_base
from puzzlepress.audit.series import series_recommendations
from puzzlepress.engines.registry import word_search_publication
from puzzlepress.interior.spec import Paper
from puzzlepress.inventory import inventory_from_project, inventory_from_report
from puzzlepress.wordsearch import Direction
from tests.helpers import demo_variant
from tests.publishing_helpers import complete_section, publishing_project

FACTS = BookFacts(puzzles=6, themes=(2, 2), levels=2, parts=None, drawings=None)


def run_cli(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "puzzlepress", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def published(**overrides: object):
    def mutate(data: dict) -> None:
        data["publishing"] = complete_section(attestations={}, **overrides)
        data["book"]["author"] = "Synthetic Test Author"

    return demo_variant(mutate)


def codes(recommendations) -> list[str]:
    return [r.code for r in recommendations]


# ------------------------------------------------------------------- listing


def test_keyword_whose_words_are_all_in_the_title_is_medium_with_kdp_source():
    # Title "Seaside Word Searches"; the category holds "Puzzles".
    project = published(keywords=["seaside word puzzles", "harbour walks", "tide pool terms"])
    found = [
        r
        for r in listing_recommendations(project, FACTS, None)
        if r.code == "keyword_repeats_metadata"
    ]
    assert [(r.field, r.priority) for r in found] == [("publishing.keywords.0", Priority.MEDIUM)]
    assert found[0].source == "https://kdp.amazon.com/en_US/help/topic/G201298500"
    assert "puzzle, seaside, word" in found[0].evidence


def test_keyword_half_repeating_the_title_is_low():
    project = published(keywords=["seaside harbour walks lighthouse", "seaside sailing"])
    found = {
        r.field: r.priority
        for r in listing_recommendations(project, FACTS, None)
        if r.code == "keyword_repeats_metadata"
    }
    assert found == {"publishing.keywords.1": Priority.LOW}  # 1 of 2 words; 1 of 4 is fine.


def test_keyword_repeating_category_words_is_found_and_singulars_match():
    project = published(
        keywords=["word search puzzles", "coastal walks"],
        categories=["Humor & Entertainment > Puzzles & Games > Word Search"],
    )
    found = [
        r
        for r in listing_recommendations(project, FACTS, None)
        if r.code == "keyword_repeats_metadata"
    ]
    assert [r.field for r in found] == ["publishing.keywords.0"]
    assert found[0].priority is Priority.MEDIUM  # word, search, puzzle(s): all repeated


def test_unused_keyword_and_category_slots_are_counted():
    project = published(keywords=["coastal walks"])
    found = {r.code: r for r in listing_recommendations(project, FACTS, None)}
    assert found["keyword_slots_unused"].title.startswith("6 of 7")
    assert found["category_slots_unused"].priority is Priority.LOW
    full = published(keywords=[f"phrase {n} coast" for n in "abcdefg"])
    assert "keyword_slots_unused" not in codes(listing_recommendations(full, FACTS, None))


def test_claims_that_contradict_levels_or_puzzle_count_are_high():
    def mutate(data: dict) -> None:
        data["book"]["description"] = "Twelve puzzles in three difficulty levels."

    project = demo_variant(mutate)
    found = [r for r in listing_recommendations(project, FACTS, None) if r.code == "claim_mismatch"]
    assert len(found) == 1 and found[0].priority is Priority.HIGH
    assert "'three difficulty levels' but the book has 2 levels" in found[0].evidence
    assert "'Twelve puzzles' but the book has 6 puzzles" in found[0].evidence
    assert found[0].field == "book.description"


@pytest.mark.parametrize(
    "description",
    [
        "Travel through history one word search at a time, in two levels.",
        "In the last three levels words run backwards; two levels in all.",
        "Each of four levels is easy. Six puzzles.",
    ],
)
def test_partial_and_singular_counts_are_not_claims(description: str):
    def mutate(data: dict) -> None:
        data["book"]["description"] = description

    project = demo_variant(mutate)
    assert "claim_mismatch" not in codes(listing_recommendations(project, FACTS, None))


def test_theme_counts_accept_level_suffixed_labels_and_only_question_otherwise():
    assert theme_base("Engines & Powertrains · Warm-up") == "engines & powertrains"
    assert theme_base("Pioneers — Challenge") == "pioneers"
    assert theme_base("Rock-n-roll") == "rock-n-roll"

    def mutate(data: dict) -> None:
        data["book"]["description"] = "Puzzles in seven themes."

    project = demo_variant(mutate)
    accepted = BookFacts(6, (21, 7), 2, None, None)
    assert "theme_count_differs" not in codes(listing_recommendations(project, accepted, None))
    found = [
        r
        for r in listing_recommendations(project, BookFacts(6, (3, 3), 2, None, None), None)
        if r.code == "theme_count_differs"
    ]
    assert found and found[0].priority is Priority.MEDIUM


def test_cover_text_counts_are_checked_too():
    from dataclasses import replace

    from puzzlepress.cover_config import CoverConfig

    project = replace(demo_variant(), cover=CoverConfig(None, back_text="Forty puzzles inside."))
    found = [r for r in listing_recommendations(project, FACTS, None) if r.code == "claim_mismatch"]
    assert found and found[0].evidence.startswith("the cover text:") and found[0].field is None
    assert found[0].area == "cover"


def test_positioning_names_the_planned_audience_or_asks_for_one():
    from tests.planning_helpers import document, variant

    project = published(description="Coastal word searches.", keywords=["harbour walks"])
    missing = listing_recommendations(project, FACTS, None)
    assert "audience_unrecorded" in codes(missing)
    plan = document(variant(positioning__primary_audience="Retired sailors"))
    named = listing_recommendations(project, FACTS, plan)
    assert "audience_not_named" in codes(named)
    project = published(description="For retired sailors.", keywords=["harbour walks"])
    assert not {"audience_not_named", "audience_unrecorded"} & set(
        codes(listing_recommendations(project, FACTS, plan))
    )


def test_progression_promise_is_read_from_the_books_own_text():
    def mutate(data: dict) -> None:
        data["book"]["description"] = "The puzzles get harder as you go."

    assert claims_progression(demo_variant(mutate))
    assert not claims_progression(demo_variant())


# ------------------------------------------------------------------- content


def test_direction_classes():
    assert {d for d in Direction if is_diagonal(d)} == {
        Direction.DOWN_RIGHT,
        Direction.DOWN_LEFT,
        Direction.UP_RIGHT,
        Direction.UP_LEFT,
    }
    assert {d for d in Direction if is_backward(d)} == {
        Direction.LEFT,
        Direction.UP,
        Direction.UP_LEFT,
        Direction.DOWN_LEFT,
    }


def test_level_facts_agree_with_the_generated_grids():
    project = demo_variant(puzzles=6)
    report, plan = word_search_publication(project)
    levels = {level.profile: level for level in level_facts(report)}
    assert set(levels) == {"gentle", "varied"}
    gentle = levels["gentle"]
    assert gentle.grids == ("10 x 8",) and gentle.allowed_directions == 2
    assert not gentle.allows_diagonal and not gentle.allows_backward
    assert gentle.placed_diagonal == (0, 0) and gentle.placed_backward == (0, 0)
    assert levels["varied"].allowed_directions == 8
    assert sum(len(level.puzzles) for level in levels.values()) == 6


def test_easier_puzzle_after_a_harder_one_is_reported_with_its_page():
    project = demo_variant(puzzles=6)  # Alternates gentle (10 x 8, 2) and varied (10 x 10, 8).
    report, plan = word_search_publication(project)
    pages = puzzle_pages(plan)
    found = [
        r for r in content_recommendations(report, pages, False) if r.code == "difficulty_order"
    ]
    assert found and found[0].priority is Priority.LOW
    assert found[0].puzzles == ("p3", "p5")
    assert found[0].pages == (pages["p3"], pages["p5"])
    promised = content_recommendations(report, pages, True)
    assert next(r for r in promised if r.code == "difficulty_order").priority is Priority.MEDIUM


def test_unplaced_directions_name_only_puzzles_that_allow_and_lack_them():
    project = demo_variant(puzzles=12)
    report, plan = word_search_publication(project)
    by_id = {r.id: r.puzzle for r in report.puzzles}
    for r in content_recommendations(report, puzzle_pages(plan), False):
        if r.code not in ("no_diagonal_words", "no_backward_words"):
            continue
        test = is_diagonal if r.code == "no_diagonal_words" else is_backward
        for puzzle_id in r.puzzles:
            puzzle = by_id[puzzle_id]
            assert puzzle is not None
            assert any(test(d) for d in puzzle.config.directions)
            assert not any(test(p.direction) for p in puzzle.solution.placements)


def test_word_from_the_puzzle_title_is_a_low_judgment_item():
    def mutate(data: dict) -> None:
        puzzle = data["word_search"]["puzzles"][0]
        bank = next(b for b in data["word_search"]["banks"] if b["id"] == puzzle["bank"])
        display = next(e["display"] for e in bank["entries"] if e["id"] == puzzle["target_ids"][0])
        puzzle["title"] = f"All About {display.title()}"

    project = demo_variant(mutate)
    report, plan = word_search_publication(project)
    found = [r for r in content_recommendations(report, puzzle_pages(plan), False)]
    echo = next(r for r in found if r.code == "title_in_word_list")
    assert echo.priority is Priority.LOW and project.word_search is not None
    assert echo.puzzles[0] == project.word_search.puzzles[0].id


# --------------------------------------------------------------------- print


class _Page:
    def __init__(self, index: int, kind):
        self.index, self.kind = index, kind


def _plan(count: int, blanks: int = 0):
    from puzzlepress.publication import PageKind

    class Plan:
        pages = [
            _Page(i, PageKind.BLANK if i <= blanks else PageKind.PUZZLE)
            for i in range(1, count + 1)
        ]

    return Plan()


def test_odd_page_count_states_kdps_rounding_and_the_spine_difference():
    project = demo_variant()
    found = page_recommendations(project, _plan(29), Paper.WHITE)  # type: ignore[arg-type]
    odd = next(r for r in found if r.code == "odd_page_count")
    assert odd.title == "29 pages: KDP will count 30"
    assert odd.priority is Priority.MEDIUM  # No cover configured.
    assert "0.0023 in" in odd.evidence  # 0.002252 in per white page.
    assert odd.source == "https://kdp.amazon.com/en_US/help/topic/G201857950"
    assert not page_recommendations(project, _plan(30), Paper.WHITE)  # type: ignore[arg-type]
    cream = page_recommendations(project, _plan(29), Paper.CREAM)  # type: ignore[arg-type]
    assert "0.0025 in" in cream[0].evidence


def test_many_blank_pages_list_them_without_suggesting_filler():
    found = page_recommendations(demo_variant(), _plan(30, blanks=4), Paper.WHITE)  # type: ignore[arg-type]
    blank = next(r for r in found if r.code == "many_blank_pages")
    assert blank.pages == (1, 2, 3, 4) and "never fill" in blank.action


# -------------------------------------------------------------------- series


def test_repeated_puzzles_and_series_differences(tmp_path: Path):
    project = demo_variant()
    report, plan = word_search_publication(project)
    mine = inventory_from_report(project, report, "book.yaml")
    other = demo_variant(lambda d: d["book"].update(author="Someone Else", imprint="Other"))
    earlier = inventory_from_report(other, word_search_publication(other)[0], "b", "earlier")
    found, unassessed = series_recommendations(
        project, mine, [OtherBook("earlier", other, earlier)], puzzle_pages(plan)
    )
    by_code = {r.code: r for r in found}
    assert by_code["exact_duplicate_previous"].priority is Priority.HIGH
    assert by_code["series_author"].priority is Priority.MEDIUM
    assert by_code["series_imprint"].priority is Priority.LOW
    assert not unassessed


def test_inventory_from_report_equals_regenerating_the_project(tmp_path: Path):
    from puzzlepress import dump_project

    source = tmp_path / "book"
    source.mkdir()
    project = demo_variant()
    (source / "book.yaml").write_text(dump_project(project), encoding="utf-8")
    regenerated = inventory_from_project(source)
    reused = inventory_from_report(project, word_search_publication(project)[0], "book.yaml")
    assert regenerated == reused


# ------------------------------------------------------------------ evidence


def test_overview_items_become_prioritized_evidence_and_external_steps_stay_manual():
    overview = {
        "items": [
            {"code": "source_valid", "title": "Source", "status": "completed", "basis": "internal",
             "blocks_export": False, "area": "book", "detail": "ok", "action": None, "what": "w"},
            {"code": "metadata", "title": "KDP metadata", "status": "blocking",
             "basis": "kdp_modeled", "blocks_export": True, "area": "publishing",
             "detail": "invalid", "action": "Fix it", "what": "w"},
            {"code": "interior_preflight", "title": "Interior preflight",
             "status": "needs_attention", "basis": "kdp_modeled", "blocks_export": False,
             "area": "print", "detail": "warnings", "action": None, "what": "Open Print"},
            {"code": "human_review", "title": "Review", "status": "awaiting_review",
             "basis": "author_judgment", "blocks_export": False, "area": "puzzles",
             "detail": "0 of 6", "action": "Review", "what": "w"},
            {"code": "physical_proof", "title": "Proof", "status": "external_pending",
             "basis": "external", "blocks_export": False, "area": "publishing",
             "detail": "none", "action": None, "what": "w"},
        ],
        "proofs": {"print_previewer": None, "physical_proof": {"current": False}},
    }  # fmt: skip
    found = {r.code: r.priority for r in evidence_recommendations(overview)}
    assert found == {
        "evidence_metadata": Priority.HIGH,
        "evidence_interior_preflight": Priority.LOW,
        "evidence_human_review": Priority.MEDIUM,
    }
    checks = {c.code: c.status for c in manual_checks(demo_variant(), overview)}
    assert checks["print_previewer"] == "not_recorded"
    assert checks["physical_proof"] == "stale"  # A proof of earlier files is not a proof.
    assert "grid_legibility" in checks and "photo_content" not in checks


# ------------------------------------------------------- whole audit and CLI


@pytest.fixture(scope="module")
def built_book(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """16 puzzles, 29 pages, interior and cover built: KDP will count 30."""
    return publishing_project(tmp_path_factory.mktemp("audit"))


def test_audit_of_a_built_book_orders_by_priority_and_writes_nothing(built_book):
    source, output = built_book
    before = {p: p.read_bytes() for p in [*source.rglob("*"), *output.rglob("*")] if p.is_file()}
    loaded = load_project(source)
    report = audit_book(loaded.project, source, output)
    after = {p: p.read_bytes() for p in [*source.rglob("*"), *output.rglob("*")] if p.is_file()}
    assert before == after
    assert report.page_count == 29
    odd = next(r for r in report.recommendations if r.code == "odd_page_count")
    assert odd.priority is Priority.HIGH  # The cover's spine is sized for 29 pages.
    order = [r.sort_key() for r in report.recommendations]
    assert order == sorted(order)
    assert report.levels and report.manual_checks
    assert any("Amazon" in item for item in report.not_assessed)
    assert any("Series" in item for item in report.not_assessed)
    assert "photo_content" in {c.code for c in report.manual_checks}
    text = audit_markdown(report)
    assert text.startswith("# Book audit: ") and "## Not assessed" in text


def test_cli_json_matches_the_written_report_and_is_deterministic(built_book, tmp_path):
    source, output = built_book
    first = run_cli("book", "audit", source, "--json", "--report", tmp_path / "r")
    assert first.returncode == 1, first.stderr  # High priority: the odd page count.
    written = (tmp_path / "r" / "audit.json").read_bytes()
    assert first.stdout.encode() == written.replace(b"\r\n", b"\n")
    data = json.loads(written)
    assert data["kind"] == "puzzlepress-book-audit" and data["audit_version"] == 1
    assert data["counts"]["high"] >= 1
    again = run_cli("book", "audit", source, "--report", tmp_path / "r")
    assert again.returncode == 1 and "# Book audit:" in again.stdout
    assert (tmp_path / "r" / "audit.json").read_bytes() == written
    assert (tmp_path / "r" / "audit.md").read_text(encoding="utf-8").startswith("# Book audit:")
    assert not list((tmp_path / "r").glob(".*staged"))


def test_cli_refuses_report_inside_a_book_or_over_foreign_files(built_book, tmp_path):
    source, _ = built_book
    inside = run_cli("book", "audit", source, "--report", source / "reports")
    assert inside.returncode == 1 and "source_overlap" in inside.stderr
    assert not (source / "reports").exists()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "audit.json").write_text('{"kind": "something else"}', encoding="utf-8")
    refused = run_cli("book", "audit", source, "--report", foreign)
    assert refused.returncode == 1 and "output_collision" in refused.stderr
    assert (foreign / "audit.json").read_text(encoding="utf-8") == '{"kind": "something else"}'
    itself = run_cli("book", "audit", source, "--previous", source)
    assert itself.returncode == 1 and "same_book" in itself.stderr


def test_cli_compares_with_a_previous_book(built_book, tmp_path):
    source, _ = built_book
    result = run_cli("book", "audit", source, "--previous", source.parent / "book", "--json")
    assert result.returncode == 1  # The same path: refused as the book itself.
    copy = tmp_path / "earlier"
    copy.mkdir()
    (copy / "book.yaml").write_bytes((source / "book.yaml").read_bytes())
    data = json.loads(run_cli("book", "audit", source, "--previous", copy, "--json").stdout or "{}")
    found = {r["code"] for r in data["recommendations"]}
    assert "exact_duplicate_previous" in found
    assert data["compared_books"] == [load_project(copy).project.book.id]


def test_audit_bytes_are_identical_across_runs(built_book):
    source, output = built_book
    project = load_project(source).project
    assert audit_bytes(audit_book(project, source, output)) == audit_bytes(
        audit_book(project, source, output)
    )


def test_coloring_book_audit_states_what_it_does_not_assess(tmp_path: Path):
    from tests.coloring_helpers import composed_coloring_book

    source = composed_coloring_book(tmp_path / "coloring", 3)
    loaded = load_project(source)
    report = audit_book(loaded.project, loaded.source_path.parent, tmp_path / "out")
    assert report.engine == "coloring" and not report.levels
    assert any("coloring preflight" in item for item in report.not_assessed)
    assert "line_art" in {c.code for c in report.manual_checks}
