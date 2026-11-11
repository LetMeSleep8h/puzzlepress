"""Word-search content facts: difficulty by level, book order and word lists.

Difficulty profiles are named generation settings, not measured difficulty. The
audit reports facts of the generated grids (grid size, allowed directions, how
words were actually placed) so the author can see whether the book matches what
its text promises. It never regenerates or changes a puzzle.
"""

import re
from collections.abc import Mapping
from statistics import median

from ..batch import BatchReport, PuzzleResult
from ..wordsearch import Direction
from .model import Basis, Category, LevelFacts, Priority, Recommendation


def is_diagonal(direction: Direction) -> bool:
    return direction.dx != 0 and direction.dy != 0


def is_backward(direction: Direction) -> bool:
    """Read against left-to-right or top-to-bottom: left, up and the leftward diagonals.

    Up-right counts as diagonal but not backward (it still reads left to right).
    """
    return direction.dx < 0 or (direction.dx == 0 and direction.dy < 0)


def _generated(report: BatchReport) -> list[PuzzleResult]:
    return [r for r in report.puzzles if r.puzzle is not None]


def level_facts(report: BatchReport) -> tuple[LevelFacts, ...]:
    """One entry per difficulty profile, in order of first use in the book."""
    by_level: dict[str, list[PuzzleResult]] = {}
    for result in _generated(report):
        by_level.setdefault(result.difficulty, []).append(result)
    levels: list[LevelFacts] = []
    for profile, results in by_level.items():
        grids: list[str] = []
        diagonal: list[int] = []
        backward: list[int] = []
        words: list[int] = []
        longest = 0
        directions: set[Direction] = set()
        for result in results:
            puzzle = result.puzzle
            assert puzzle is not None
            size = f"{puzzle.config.size.width} x {puzzle.config.size.height}"
            if size not in grids:
                grids.append(size)
            directions |= set(puzzle.config.directions)
            placements = puzzle.solution.placements
            words.append(len(puzzle.targets))
            diagonal.append(sum(is_diagonal(p.direction) for p in placements))
            backward.append(sum(is_backward(p.direction) for p in placements))
            longest = max([longest, *(len(p.search) for p in placements)])
        levels.append(
            LevelFacts(
                profile,
                tuple(r.id for r in results),
                tuple(grids),
                (min(words), max(words)),
                len(directions),
                any(is_diagonal(d) for d in directions),
                any(is_backward(d) for d in directions),
                (min(diagonal), max(diagonal)),
                (min(backward), max(backward)),
                longest,
            )
        )
    return tuple(levels)


def _pages(ids: list[str], pages: Mapping[str, int]) -> tuple[int, ...]:
    return tuple(pages[i] for i in ids if i in pages)


def _unused_directions(report: BatchReport, pages: Mapping[str, int]) -> list[Recommendation]:
    found: list[Recommendation] = []
    by_level: dict[str, list[PuzzleResult]] = {}
    for result in _generated(report):
        by_level.setdefault(result.difficulty, []).append(result)
    for level, results in by_level.items():
        for label, test in (("diagonal", is_diagonal), ("backward", is_backward)):
            allowing = [
                r for r in results if r.puzzle and any(test(d) for d in r.puzzle.config.directions)
            ]
            none = [
                r.id
                for r in allowing
                if r.puzzle and not any(test(p.direction) for p in r.puzzle.solution.placements)
            ]
            if not none:
                continue
            found.append(
                Recommendation(
                    f"no_{label}_words",
                    Priority.LOW,
                    Category.CONTENT,
                    Basis.MEASURED,
                    f"Level '{level}': {len(none)} of {len(allowing)} puzzles place no "
                    f"{label} word",
                    f"The level allows {label} words, but the generator placed none in "
                    f"{', '.join(none)}. The grids are valid; this is how words happened to fit.",
                    "Nothing needs fixing unless the instructions or description promise "
                    f"{label} words in every puzzle; say words may run that way. Changing it "
                    "means regenerating those grids.",
                    "quality",
                    pages=_pages(none, pages),
                    puzzles=tuple(none),
                )
            )
        backward = {
            r.id: sum(is_backward(p.direction) for p in r.puzzle.solution.placements)
            for r in results
            if r.puzzle and any(is_backward(d) for d in r.puzzle.config.directions)
        }
        if len(backward) >= 4:
            middle = median(backward.values())
            sparse = [i for i, n in backward.items() if 0 < n and n * 2 < middle]
            if middle >= 4 and sparse:
                found.append(
                    Recommendation(
                        "uneven_backward_words",
                        Priority.LOW,
                        Category.CONTENT,
                        Basis.MEASURED,
                        f"Level '{level}': {len(sparse)} puzzle(s) far easier in backward words",
                        f"The level's median is {middle:g} backward words per puzzle; "
                        + ", ".join(f"{i} has {backward[i]}" for i in sparse)
                        + ".",
                        "Review whether these puzzles feel easier than their neighbours; "
                        "regenerating with a new seed would change their grids.",
                        "quality",
                        pages=_pages(sparse, pages),
                        puzzles=tuple(sparse),
                    )
                )
    return found


def _order(report: BatchReport, pages: Mapping[str, int], promised: bool) -> list[Recommendation]:
    """Later puzzles whose settings are easier than an earlier puzzle's."""
    seen: list[tuple[str, int, int]] = []
    easier: list[str] = []
    detail: list[str] = []
    for result in _generated(report):
        puzzle = result.puzzle
        assert puzzle is not None
        area = puzzle.config.size.width * puzzle.config.size.height
        directions = len(puzzle.config.directions)
        for earlier, e_area, e_dirs in seen:
            if area <= e_area and directions <= e_dirs and (area, directions) != (e_area, e_dirs):
                easier.append(result.id)
                detail.append(f"{result.id} after {earlier}")
                break
        seen.append((result.id, area, directions))
    if not easier:
        return []
    return [
        Recommendation(
            "difficulty_order",
            Priority.MEDIUM if promised else Priority.LOW,
            Category.CONTENT,
            Basis.MEASURED,
            f"{len(easier)} puzzle(s) use easier settings than an earlier puzzle",
            "Smaller grid or fewer directions than an earlier puzzle: "
            + "; ".join(detail[:8])
            + ("; ..." if len(detail) > 8 else "")
            + (". The book's text says the puzzles grow harder." if promised else "."),
            "Reorder the puzzles or change their difficulty profiles if the order should "
            "rise; otherwise remove any promise that difficulty increases.",
            "edit",
            pages=_pages(easier, pages),
            puzzles=tuple(easier),
        )
    ]


def _tokens(title: str) -> list[str]:
    return [t for t in re.findall(r"[A-Z0-9]+", title.upper()) if t]


def _title_echo(report: BatchReport, pages: Mapping[str, int]) -> list[Recommendation]:
    echoes: list[str] = []
    ids: list[str] = []
    for result in _generated(report):
        assert result.puzzle is not None
        tokens = _tokens(result.title)
        runs = {
            "".join(tokens[i:j]) for i in range(len(tokens)) for j in range(i + 1, len(tokens) + 1)
        }
        repeated = [t.display for t in result.puzzle.targets if t.search in runs]
        if repeated:
            ids.append(result.id)
            echoes.append(f"{result.id} '{result.title}': {', '.join(repeated)}")
    if not ids:
        return []
    return [
        Recommendation(
            "title_in_word_list",
            Priority.LOW,
            Category.CONTENT,
            Basis.JUDGMENT,
            f"{len(ids)} puzzle(s) list a word from their own title",
            "; ".join(echoes[:8]) + ("; ..." if len(echoes) > 8 else ""),
            "A style choice: some solvers find a word printed in the heading too easy. Keep "
            "or replace it.",
            "edit",
            pages=_pages(ids, pages),
            puzzles=tuple(ids),
        )
    ]


def content_recommendations(
    report: BatchReport, pages: Mapping[str, int], promised: bool
) -> list[Recommendation]:
    failed = [r.id for r in report.puzzles if r.puzzle is None]
    found: list[Recommendation] = []
    if failed:
        found.append(
            Recommendation(
                "generation_failed",
                Priority.HIGH,
                Category.CONTENT,
                Basis.MEASURED,
                f"{len(failed)} puzzle(s) did not generate",
                f"No verified grid for {', '.join(failed)}; the audit measured the others.",
                "Open Quality to see why, then fix the word list or profile.",
                "quality",
                puzzles=tuple(failed),
            )
        )
    return [
        *found,
        *_order(report, pages, promised),
        *_unused_directions(report, pages),
        *_title_echo(report, pages),
    ]
