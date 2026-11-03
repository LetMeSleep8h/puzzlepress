"""Compare a new book's puzzles with previous books and with each other.

Exact duplicates: equal normalized word sets (order and spacing ignored), or equal
grids, including grids that are rotations or mirror images of each other.
Near duplicates (configurable `Thresholds`):

- word Jaccard (shared / union) at or above `word_jaccard`, or
- word overlap (shared / smaller set) at or above `word_overlap`, with at least
  `min_shared_words` shared words, or
- grid agreement (same letter at the same cell, best of the eight rotations and
  mirror images of equal-sized grids) at or above `grid_agreement`.

Unverified previous puzzles are still compared using what was extracted, and every
match against one says so. The report is `clean` only when nothing matched and
every source's coverage is complete; anything else is never reported as clean.
These measures flag candidates for review; they are not an originality guarantee.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .errors import ValidationIssue
from .inventory import Inventory, InventoryError, InventoryPuzzle

REPORT_KIND = "puzzlepress-duplicate-report"
REPORT_VERSION = 1


@dataclass(frozen=True)
class Thresholds:
    word_jaccard: float = 0.6
    word_overlap: float = 0.8
    min_shared_words: int = 3
    grid_agreement: float = 0.5

    def __post_init__(self) -> None:
        issues = [
            ValidationIssue(f"thresholds.{name}", "range", f"{name} must be in (0, 1].")
            for name in ("word_jaccard", "word_overlap", "grid_agreement")
            if not 0 < getattr(self, name) <= 1
        ]
        if not 1 <= self.min_shared_words <= 100:
            issues.append(
                ValidationIssue("thresholds.min_shared_words", "range", "Use 1..100 words.")
            )
        if issues:
            raise InventoryError(tuple(issues))

    def to_dict(self) -> dict[str, object]:
        return {
            "word_jaccard": self.word_jaccard,
            "word_overlap": self.word_overlap,
            "min_shared_words": self.min_shared_words,
            "grid_agreement": self.grid_agreement,
        }


@dataclass(frozen=True)
class Match:
    severity: str  # exact | near
    reasons: tuple[str, ...]  # identical_words, identical_grid, word_jaccard, ...
    new_id: str
    new_label: str
    other_source: str  # previous book label, or "new book"
    other_id: str
    other_label: str
    other_verified: bool
    shared_words: tuple[str, ...]
    word_jaccard: float
    word_overlap: float
    grid_agreement: float | None
    grid_transform: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "reasons": list(self.reasons),
            "new": {"id": self.new_id, "label": self.new_label},
            "other": {
                "source": self.other_source,
                "id": self.other_id,
                "label": self.other_label,
                "verified": self.other_verified,
            },
            "shared_words": list(self.shared_words),
            "word_jaccard": round(self.word_jaccard, 4),
            "word_overlap": round(self.word_overlap, 4),
            "grid_agreement": None
            if self.grid_agreement is None
            else round(self.grid_agreement, 4),
            "grid_transform": self.grid_transform,
        }


@dataclass(frozen=True)
class Recommendation:
    puzzle_id: str
    action: str
    replace_at_least: int
    words_to_replace: tuple[str, ...]
    candidates: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "puzzle_id": self.puzzle_id,
            "action": self.action,
            "replace_at_least": self.replace_at_least,
            "words_to_replace": list(self.words_to_replace),
            "candidates": list(self.candidates),
        }


@dataclass(frozen=True)
class DuplicateReport:
    new: Inventory
    previous: tuple[Inventory, ...]
    thresholds: Thresholds
    matches: tuple[Match, ...]
    recommendations: tuple[Recommendation, ...] = field(default=())

    @property
    def exact(self) -> tuple[Match, ...]:
        return tuple(m for m in self.matches if m.severity == "exact")

    @property
    def near(self) -> tuple[Match, ...]:
        return tuple(m for m in self.matches if m.severity == "near")

    @property
    def coverage_complete(self) -> bool:
        return self.new.coverage.complete and all(p.coverage.complete for p in self.previous)

    @property
    def verdict(self) -> str:
        if self.exact:
            return "exact_duplicates"
        if self.near:
            return "near_duplicates"
        if not self.coverage_complete:
            return "incomplete_coverage"
        return "clean"

    @property
    def clean(self) -> bool:
        return self.verdict == "clean"

    def to_dict(self) -> dict[str, object]:
        def source(inv: Inventory) -> dict[str, object]:
            return {
                "label": inv.label,
                "book_id": inv.book_id,
                "kind": inv.source_kind,
                "name": inv.source_name,
                "sha256": inv.source_sha256,
                "coverage": inv.coverage.to_dict(),
                "puzzles_examined": len(inv.puzzles),
                "verified": len(inv.verified),
                "unverified": [
                    {"id": p.id, "label": p.label, "issues": list(p.issues)} for p in inv.unverified
                ],
            }

        return {
            "kind": REPORT_KIND,
            "report_version": REPORT_VERSION,
            "verdict": self.verdict,
            "clean": self.clean,
            "coverage_complete": self.coverage_complete,
            "thresholds": self.thresholds.to_dict(),
            "new_book": source(self.new),
            "previous_books": [source(p) for p in self.previous],
            "counts": {
                "new_puzzles": len(self.new.puzzles),
                "previous_puzzles": sum(len(p.puzzles) for p in self.previous),
                "exact": len(self.exact),
                "near": len(self.near),
                "within_new_book": sum(m.other_source == WITHIN for m in self.matches),
            },
            "exact_duplicates": [m.to_dict() for m in self.exact],
            "near_duplicates": [m.to_dict() for m in self.near],
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


WITHIN = "new book"


def _transforms(grid: tuple[str, ...]) -> list[tuple[str, tuple[str, ...]]]:
    rows = list(grid)
    cols = ["".join(r[i] for r in rows) for i in range(len(rows[0]))]
    out = [
        ("identity", tuple(rows)),
        ("mirror_horizontal", tuple(r[::-1] for r in rows)),
        ("mirror_vertical", tuple(rows[::-1])),
        ("rotate_180", tuple(r[::-1] for r in rows[::-1])),
        ("transpose", tuple(cols)),
        ("rotate_90", tuple(c[::-1] for c in cols)),
        ("rotate_270", tuple(cols[::-1])),
        ("anti_transpose", tuple(c[::-1] for c in cols[::-1])),
    ]
    return out


def grid_agreement(
    left: tuple[str, ...] | None, right: tuple[str, ...] | None
) -> tuple[float | None, str | None]:
    """Best same-cell letter agreement over the eight symmetries of `right`."""
    if not left or not right:
        return None, None
    a = "".join(left)
    best: tuple[float | None, str | None] = (None, None)
    for name, candidate in _transforms(right):
        if len(candidate) != len(left) or len(candidate[0]) != len(left[0]):
            continue
        b = "".join(candidate)
        score = sum(x == y for x, y in zip(a, b, strict=True)) / len(a)
        if best[0] is None or score > best[0]:
            best = (score, name)
    return best


def compare_pair(
    new: InventoryPuzzle,
    other: InventoryPuzzle,
    other_source: str,
    thresholds: Thresholds,
) -> Match | None:
    left, right = set(new.words), set(other.words)
    shared = left & right
    union = left | right
    jaccard = len(shared) / len(union) if union else 0.0
    overlap = len(shared) / min(len(left), len(right)) if left and right else 0.0
    agreement, transform = grid_agreement(new.grid, other.grid)
    exact: list[str] = []
    near: list[str] = []
    if left and left == right:
        exact.append("identical_words")
    if agreement == 1.0:
        exact.append("identical_grid")
    if not exact:
        if jaccard >= thresholds.word_jaccard and len(shared) >= 1:
            near.append("word_jaccard")
        if overlap >= thresholds.word_overlap and len(shared) >= thresholds.min_shared_words:
            near.append("word_overlap")
        if agreement is not None and agreement >= thresholds.grid_agreement:
            near.append("grid_agreement")
    if not exact and not near:
        return None
    return Match(
        "exact" if exact else "near",
        tuple(exact or near),
        new.id,
        new.label,
        other_source,
        other.id,
        other.label,
        other.verified,
        tuple(sorted(shared)),
        jaccard,
        overlap,
        agreement,
        transform if agreement is not None else None,
    )


def _replacements_needed(match: Match, new_size: int, other_size: int, t: Thresholds) -> int:
    """Fewest shared words to swap for unused words so the pair stops matching."""
    shared = len(match.shared_words)
    for k in range(1, shared + 1):
        s = shared - k
        union = new_size + other_size - s
        jaccard = s / union if union else 0.0
        overlap = s / min(new_size, other_size) if new_size and other_size else 0.0
        if jaccard < t.word_jaccard and (overlap < t.word_overlap or s < t.min_shared_words):
            return k
    return shared


def compare_inventories(
    new: Inventory,
    previous: Sequence[Inventory],
    thresholds: Thresholds | None = None,
    candidates: Mapping[str, tuple[str, ...]] | None = None,
) -> DuplicateReport:
    """Every new puzzle against every previous puzzle, and new puzzles pairwise.

    `candidates` optionally maps a new puzzle ID to unused replacement words
    (normalized, in preference order), used only for recommendations.
    """
    t = thresholds or Thresholds()
    matches: list[Match] = []
    for inv in previous:
        for puzzle in new.puzzles:
            for other in inv.puzzles:
                match = compare_pair(puzzle, other, inv.label, t)
                if match is not None:
                    matches.append(match)
    puzzles = new.puzzles
    for i, puzzle in enumerate(puzzles):
        for other in puzzles[i + 1 :]:
            match = compare_pair(puzzle, other, WITHIN, t)
            if match is not None:
                matches.append(match)
    sizes = {p.id: len(p.words) for p in puzzles}
    other_sizes = {(inv.label, p.id): len(p.words) for inv in previous for p in inv.puzzles}
    other_sizes.update({(WITHIN, p.id): len(p.words) for p in puzzles})
    recommendations: list[Recommendation] = []
    by_puzzle: dict[str, list[Match]] = {}
    for match in matches:
        by_puzzle.setdefault(match.new_id, []).append(match)
    for puzzle_id in sorted(by_puzzle):
        group = by_puzzle[puzzle_id]
        need = 0
        words: set[str] = set()
        grid_only = True
        for m in group:
            if m.shared_words and any(r != "grid_agreement" for r in m.reasons):
                grid_only = False
                need = max(
                    need,
                    _replacements_needed(
                        m, sizes[puzzle_id], other_sizes[(m.other_source, m.other_id)], t
                    ),
                )
                words.update(m.shared_words)
        if grid_only:
            action = (
                "The grid repeats another puzzle's letters; change its words or its puzzle "
                "ID (which derives the seed) and rebuild."
            )
        else:
            action = (
                f"Replace at least {need} of the shared words with words not used in the "
                "previous book, then rebuild and compare again."
            )
        recommendations.append(
            Recommendation(
                puzzle_id,
                action,
                need,
                tuple(sorted(words)),
                tuple((candidates or {}).get(puzzle_id, ()))[:10],
            )
        )
    return DuplicateReport(new, tuple(previous), t, tuple(matches), tuple(recommendations))


def report_json(report: DuplicateReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def report_markdown(report: DuplicateReport) -> str:
    """A short human summary of the same report."""
    lines = [
        "# Duplicate-puzzle report",
        "",
        f"Verdict: **{report.verdict}**",
        "",
        "| Source | Kind | Puzzles examined | Verified | Unverified | Coverage |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for label, inv in [("new: " + report.new.label, report.new)] + [
        ("previous: " + p.label, p) for p in report.previous
    ]:
        lines.append(
            f"| {label} | {inv.source_kind} ({inv.source_name}) | {len(inv.puzzles)} | "
            f"{len(inv.verified)} | {len(inv.unverified)} | {inv.coverage.status} |"
        )
    for inv in (report.new, *report.previous):
        for note in inv.coverage.notes:
            lines.append(f"- {inv.label}: {note}")
    t = report.thresholds
    lines += [
        "",
        f"Thresholds: word Jaccard >= {t.word_jaccard}, word overlap >= {t.word_overlap} "
        f"with >= {t.min_shared_words} shared words, grid agreement >= {t.grid_agreement}.",
        "",
    ]
    for title, group in (("Exact duplicates", report.exact), ("Near duplicates", report.near)):
        lines.append(f"## {title} ({len(group)})")
        lines.append("")
        if not group:
            lines.append("None.")
        for m in group:
            grid = "" if m.grid_agreement is None else f", grid {m.grid_agreement:.2f}"
            flag = "" if m.other_verified else " [other puzzle unverified]"
            lines.append(
                f"- {m.new_label} vs {m.other_source}: {m.other_label}{flag}: "
                f"{', '.join(m.reasons)} (Jaccard {m.word_jaccard:.2f}, overlap "
                f"{m.word_overlap:.2f}{grid}); shared: {', '.join(m.shared_words) or '-'}"
            )
        lines.append("")
    unverified = [(inv.label, p) for inv in (report.new, *report.previous) for p in inv.unverified]
    lines.append(f"## Unverified puzzles ({len(unverified)})")
    lines.append("")
    if not unverified:
        lines.append("None.")
    for label, p in unverified:
        lines.append(f"- {label}: {p.label}: {'; '.join(p.issues)}")
    lines += ["", f"## Recommended replacements ({len(report.recommendations)})", ""]
    if not report.recommendations:
        lines.append("None.")
    for r in report.recommendations:
        extra = f" Candidates: {', '.join(r.candidates)}." if r.candidates else ""
        words = f" Shared: {', '.join(r.words_to_replace)}." if r.words_to_replace else ""
        lines.append(f"- {r.puzzle_id}: {r.action}{words}{extra}")
    lines.append("")
    return "\n".join(lines)
