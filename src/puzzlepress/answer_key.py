"""Independent answer-key check of a built interior PDF, from its text alone.

The engine already verifies solutions against authoritative placements before it
draws them. This check reads the finished PDF instead, so it observes what will
print: every puzzle page (grid plus word list, see `inventory`) must have exactly
one solution grid with the same letters, and that solution's marked (bold)
letters must spell every listed word along a straight line and mark nothing
else. Solution grids with no puzzle are reported too. It never modifies the PDF.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .inventory import _LETTER, InventoryPuzzle, _Item, normalize_word, read_pdf_pages


@dataclass(frozen=True)
class SolutionGrid:
    page: int
    rows: tuple[str, ...]
    marked: frozenset[tuple[int, int]]  # (column, row) of bold letters.
    order: tuple[float, float] = (0.0, 0.0)  # Reading order on the page.


@dataclass(frozen=True)
class AnswerKeyResult:
    puzzles: int
    solutions: int
    matched: int
    issues: tuple[str, ...] = field(default=())
    unreadable_pages: tuple[int, ...] = ()

    @property
    def complete(self) -> bool:
        return (
            not self.issues
            and not self.unreadable_pages
            and self.puzzles > 0
            and self.matched == self.puzzles == self.solutions
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "puzzles": self.puzzles,
            "solutions": self.solutions,
            "matched": self.matched,
            "issues": list(self.issues),
            "unreadable_pages": list(self.unreadable_pages),
        }


def _segments(row: list[_Item]) -> list[list[_Item]]:
    if len(row) < 2:
        return [row]
    gaps = [b.x - a.x for a, b in zip(row, row[1:], strict=False)]
    pitch = statistics.median(gaps)
    out: list[list[_Item]] = [[row[0]]]
    for gap, item in zip(gaps, row[1:], strict=True):
        if gap > pitch * 1.8:
            out.append([item])
        else:
            out[-1].append(item)
    return out


def solution_grids(page: int, items: list[_Item]) -> list[SolutionGrid]:
    """Split a page's letters into separate grids (stacked or side by side)."""
    letters = [i for i in items if _LETTER.match(i.text)]
    sizes = sorted({i.size for i in letters})
    # Grids of different dimensions share a page at different letter sizes.
    grids = [g for size in sizes for g in _grids(page, [i for i in letters if i.size == size])]
    return sorted(grids, key=lambda g: g.order)


def _grids(page: int, letters: list[_Item]) -> list[SolutionGrid]:
    size = letters[0].size
    rows: list[list[_Item]] = []
    for item in sorted(letters, key=lambda i: (-i.y, i.x)):
        if rows and abs(rows[-1][0].y - item.y) <= size * 0.3:
            rows[-1].append(item)
        else:
            rows.append([item])
    open_grids: list[dict[str, object]] = []
    done: list[list[list[_Item]]] = []
    for row in rows:
        row.sort(key=lambda i: i.x)
        y = row[0].y
        for segment in _segments(row):
            x = segment[0].x
            target = None
            for grid in open_grids:
                last: list[_Item] = grid["rows"][-1]  # type: ignore[index]
                pitch = grid["pitch"]
                dy = last[0].y - y
                limit = size * 3 if pitch is None else float(pitch) * 1.3  # type: ignore[arg-type]
                if len(last) == len(segment) and abs(last[0].x - x) <= size and 0 < dy <= limit:
                    target = grid
                    break
            if target is None:
                open_grids.append({"rows": [segment], "pitch": None})
            else:
                grid_rows: list[list[_Item]] = target["rows"]  # type: ignore[assignment]
                if target["pitch"] is None:
                    target["pitch"] = grid_rows[-1][0].y - y
                grid_rows.append(segment)
    for grid in open_grids:
        done.append(grid["rows"])  # type: ignore[arg-type]
    out = []
    for grid_rows in done:
        if len(grid_rows) < 2:
            continue
        marked = frozenset(
            (c, r) for r, row in enumerate(grid_rows) for c, item in enumerate(row) if item.bold
        )
        first = grid_rows[0][0]
        out.append(
            SolutionGrid(
                page,
                tuple("".join(i.text for i in row) for row in grid_rows),
                marked,
                (-round(first.y), round(first.x)),
            )
        )
    return out


def _marks_issue(puzzle: InventoryPuzzle, solution: SolutionGrid) -> str | None:
    from .quality import screen_words
    from .wordsearch import Grid

    forms = sorted({normalize_word(w) for w in puzzle.display_words or puzzle.words})
    found = screen_words(Grid(solution.rows), forms).occurrences
    covered: set[tuple[int, int]] = set()
    missing = []
    for word in forms:
        paths = [
            {(c.x, c.y) for c in o.coordinates}
            for o in found
            if o.word == word and {(c.x, c.y) for c in o.coordinates} <= solution.marked
        ]
        if not paths:
            missing.append(word)
        for path in paths:
            covered |= path
    if missing:
        return f"{puzzle.label}: solution does not mark {', '.join(missing)}"
    extra = solution.marked - covered
    if extra:
        return f"{puzzle.label}: solution marks {len(extra)} letter(s) outside the listed words"
    return None


def check_answer_key(path: str | Path) -> AnswerKeyResult:
    from .inventory import inventory_from_pdf

    source = Path(path)
    data = source.read_bytes()
    pages, skipped, _count = read_pdf_pages(data, source.name)
    inventory = inventory_from_pdf(source)
    solutions: list[SolutionGrid] = []
    for page in pages:
        # Solution pages: letters, no word list, and marked (bold) letters. A spread's
        # grid page has no word list either, but nothing on it is marked.
        if not page.words and any(i.bold and _LETTER.match(i.text) for i in page.items):
            solutions.extend(solution_grids(page.number, page.items))
    issues: list[str] = []
    for puzzle in inventory.unverified:
        issues.append(f"{puzzle.label}: {'; '.join(puzzle.issues)}")
    used: set[int] = set()
    matched = 0
    for puzzle in inventory.verified:
        candidates = [i for i, s in enumerate(solutions) if s.rows == puzzle.grid and i not in used]
        if not candidates:
            issues.append(f"{puzzle.label}: no solution grid with the same letters")
            continue
        index = candidates[0]
        used.add(index)
        problem = _marks_issue(puzzle, solutions[index])
        if problem:
            issues.append(problem)
        else:
            matched += 1
    for index, solution in enumerate(solutions):
        if index not in used:
            issues.append(f"page {solution.page}: a solution grid matches no puzzle")
    unreadable = tuple(s.page for s in skipped if s.reason in ("no_text", "unreadable"))
    return AnswerKeyResult(
        len(inventory.puzzles), len(solutions), matched, tuple(issues), unreadable
    )
