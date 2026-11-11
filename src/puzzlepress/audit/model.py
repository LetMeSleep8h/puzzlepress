"""Value models of a book audit: prioritized, evidence-backed recommendations.

An audit observes saved source and built files; it never edits, rebuilds or
submits anything. Priorities are PuzzlePress conventions for ordering work, not
predictions of sales: no sales, advertising, ranking or competitor data is read.
"""

from dataclasses import dataclass, field
from enum import StrEnum

AUDIT_KIND = "puzzlepress-book-audit"
AUDIT_VERSION = 1


class Priority(StrEnum):
    HIGH = "high"  # Blocks KDP readiness, contradicts the book, or repeats an earlier book.
    MEDIUM = "medium"  # Likely to weaken the listing or the printed book; worth fixing.
    LOW = "low"  # Polish or a judgment call; recorded so it is not forgotten.


class Category(StrEnum):
    LISTING = "listing"  # Title, subtitle, description, keywords, categories.
    PRINT = "print"  # Page count, spine, built interior and cover.
    CONTENT = "content"  # Puzzles: difficulty facts, word lists.
    SERIES = "series"  # Earlier or sibling books: repeats and consistency.
    EVIDENCE = "evidence"  # Reviews, preflight, decisions, proofs recorded or not.


class Basis(StrEnum):
    KDP_HELP = "kdp_help"  # Stated on an official KDP help page (source URL given).
    MEASURED = "measured"  # Measured by PuzzlePress from the source or built files.
    JUDGMENT = "judgment"  # Needs the author's judgment; PuzzlePress only points at it.


PRIORITY_ORDER = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
CATEGORY_ORDER = {c: i for i, c in enumerate(Category)}


@dataclass(frozen=True)
class Recommendation:
    code: str
    priority: Priority
    category: Category
    basis: Basis
    title: str
    evidence: str
    action: str
    area: str  # Studio section that edits or shows the subject.
    field: str | None = None  # book.yaml path, when one field is the subject.
    source: str | None = None  # Official page for KDP_HELP.
    pages: tuple[int, ...] = ()  # Physical interior pages (1-based) to look at.
    puzzles: tuple[str, ...] = ()  # Puzzle IDs concerned.

    def sort_key(self) -> tuple[int, int, str, str]:
        return (
            PRIORITY_ORDER[self.priority],
            CATEGORY_ORDER[self.category],
            self.code,
            self.field or ",".join(self.puzzles),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "priority": self.priority.value,
            "category": self.category.value,
            "basis": self.basis.value,
            "title": self.title,
            "evidence": self.evidence,
            "action": self.action,
            "area": self.area,
            "field": self.field,
            "source": self.source,
            "pages": list(self.pages),
            "puzzles": list(self.puzzles),
        }


@dataclass(frozen=True)
class ManualCheck:
    """Something only a printed proof or a person can settle."""

    code: str
    title: str
    why: str
    status: str  # recorded | not_recorded

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "title": self.title, "why": self.why, "status": self.status}


@dataclass(frozen=True)
class LevelFacts:
    """Measured facts of one difficulty profile as the book uses it."""

    profile: str
    puzzles: tuple[str, ...]
    grids: tuple[str, ...]  # Distinct "W x H", in first-use order.
    words: tuple[int, int]  # Fewest and most words per puzzle.
    allowed_directions: int
    allows_diagonal: bool
    allows_backward: bool
    placed_diagonal: tuple[int, int]  # Fewest and most diagonal words per puzzle.
    placed_backward: tuple[int, int]
    longest_word: int

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "puzzles": len(self.puzzles),
            "first_puzzle": self.puzzles[0],
            "last_puzzle": self.puzzles[-1],
            "grids": list(self.grids),
            "words": {"min": self.words[0], "max": self.words[1]},
            "allowed_directions": self.allowed_directions,
            "allows_diagonal": self.allows_diagonal,
            "allows_backward": self.allows_backward,
            "placed_diagonal": {"min": self.placed_diagonal[0], "max": self.placed_diagonal[1]},
            "placed_backward": {"min": self.placed_backward[0], "max": self.placed_backward[1]},
            "longest_word": self.longest_word,
        }


@dataclass(frozen=True)
class AuditReport:
    book_id: str
    engine: str
    title: str
    page_count: int | None
    recommendations: tuple[Recommendation, ...]
    manual_checks: tuple[ManualCheck, ...]
    levels: tuple[LevelFacts, ...] = ()
    compared_books: tuple[str, ...] = ()
    # What this audit did not assess, and why; never silently skipped.
    not_assessed: tuple[str, ...] = ()
    statement: str = field(
        default=(
            "PuzzlePress audits the saved source and built files it can read. It has no "
            "access to Amazon sales, advertising, search rankings, reviews or competitor "
            "data, and Amazon KDP decides acceptance."
        )
    )

    def counts(self) -> dict[str, int]:
        return {p.value: sum(r.priority is p for r in self.recommendations) for p in Priority}

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": AUDIT_KIND,
            "audit_version": AUDIT_VERSION,
            "book_id": self.book_id,
            "engine": self.engine,
            "title": self.title,
            "page_count": self.page_count,
            "counts": self.counts(),
            "recommendations": [r.to_dict() for r in self.recommendations],
            "manual_checks": [m.to_dict() for m in self.manual_checks],
            "levels": [level.to_dict() for level in self.levels],
            "compared_books": list(self.compared_books),
            "not_assessed": list(self.not_assessed),
            "statement": self.statement,
        }
