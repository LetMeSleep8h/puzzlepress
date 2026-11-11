"""Puzzle inventories: the word sets and grids of a book, from source or from its PDF.

An inventory records what is known about a book's puzzles so a new book can be
compared with it (see `duplicates`). It comes from one of three sources:

- a project (`book.yaml`): the engine regenerates every puzzle, so words and
  grids are authoritative and coverage is complete when every definition generates;
- an interior PDF: text is extracted page by page. A page yields a puzzle only when
  it has a rectangular letter grid and a word list and every listed word is found
  in that grid; anything else is recorded as unverified or unextracted, never
  silently dropped. Coverage is `complete` only when an expected puzzle count is
  supplied and matched with nothing unverified, otherwise `incomplete` or
  `unconfirmed`;
- a saved inventory JSON file (this module's own format), validated strictly.

Inventories never store absolute paths or times, so the same input gives the same
bytes. Nothing here writes files; the CLI writes explicit outputs only.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .cancellation import checkpoint
from .errors import ProjectError, ValidationIssue

INVENTORY_KIND = "puzzlepress-puzzle-inventory"
INVENTORY_VERSION = 1
MAX_PDF_BYTES = 512 * 1024 * 1024
MAX_PUZZLES = 2000

if TYPE_CHECKING:
    from .batch import BatchReport
    from .models import Project

_WORD = re.compile(r"^[A-Z]+(?: [A-Z]+)*$")
_LETTER = re.compile(r"^[A-Z]$")
_FOLIO = re.compile(r"^(?:\d{1,4}|[ivxlcdm]{1,8})$")


class InventoryError(ProjectError):
    """An inventory source that cannot be read or is malformed."""


def _fail(path: str, code: str, message: str) -> InventoryError:
    return InventoryError((ValidationIssue(path, code, message),))


@dataclass(frozen=True)
class InventoryPuzzle:
    """One puzzle: normalized words (sorted search forms) and its grid, if known."""

    id: str
    words: tuple[str, ...]
    grid: tuple[str, ...] | None
    status: str  # verified | unverified
    title: str | None = None
    theme: str | None = None
    page: int | None = None  # 1-based PDF page, for PDF sources.
    folio: str | None = None
    display_words: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    @property
    def label(self) -> str:
        where = f"page {self.page}" if self.page is not None else self.id
        return f"{where} ({self.title})" if self.title else where

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "theme": self.theme,
            "page": self.page,
            "folio": self.folio,
            "status": self.status,
            "words": list(self.words),
            "display_words": list(self.display_words),
            "grid": list(self.grid) if self.grid is not None else None,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class SkippedPage:
    page: int
    # blank | no_text (images only, e.g. scanned) | no_puzzle_content |
    # grid_without_words | unreadable
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {"page": self.page, "reason": self.reason}


@dataclass(frozen=True)
class Coverage:
    status: str  # complete | incomplete | unconfirmed
    pages_examined: int | None
    expected_puzzles: int | None
    notes: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.status == "complete"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "complete": self.complete,
            "pages_examined": self.pages_examined,
            "expected_puzzles": self.expected_puzzles,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Inventory:
    label: str
    source_kind: str  # project | pdf | inventory
    source_name: str
    source_sha256: str
    puzzles: tuple[InventoryPuzzle, ...]
    coverage: Coverage
    skipped_pages: tuple[SkippedPage, ...] = ()
    book_id: str | None = None

    @property
    def verified(self) -> tuple[InventoryPuzzle, ...]:
        return tuple(p for p in self.puzzles if p.verified)

    @property
    def unverified(self) -> tuple[InventoryPuzzle, ...]:
        return tuple(p for p in self.puzzles if not p.verified)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": INVENTORY_KIND,
            "inventory_version": INVENTORY_VERSION,
            "label": self.label,
            "book_id": self.book_id,
            "source": {
                "kind": self.source_kind,
                "name": self.source_name,
                "sha256": self.source_sha256,
            },
            "coverage": self.coverage.to_dict(),
            "counts": {
                "puzzles": len(self.puzzles),
                "verified": len(self.verified),
                "unverified": len(self.unverified),
                "skipped_pages": len(self.skipped_pages),
            },
            "puzzles": [p.to_dict() for p in self.puzzles],
            "skipped_pages": [s.to_dict() for s in self.skipped_pages],
        }


def inventory_json(inventory: Inventory) -> str:
    return json.dumps(inventory.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def normalize_word(display: str) -> str:
    return display.replace(" ", "").upper()


# --- Project sources ---------------------------------------------------------------


def inventory_from_project(path: str | Path, label: str | None = None) -> Inventory:
    """Regenerate every puzzle of a project with the engine (authoritative)."""
    from .batch import generate_batch
    from .project import load_project

    loaded = load_project(path)
    project = loaded.project
    if project.word_search is None:
        raise _fail("word_search", "no_puzzles", "The project defines no word-search puzzles.")
    return inventory_from_report(project, generate_batch(project), loaded.source_path.name, label)


def inventory_from_report(
    project: Project, report: BatchReport, source_name: str, label: str | None = None
) -> Inventory:
    """The inventory of an already generated batch: equal to regenerating the project."""
    from .identity import build_identity

    puzzles: list[InventoryPuzzle] = []
    for result in report.puzzles:
        if result.puzzle is None:
            puzzles.append(
                InventoryPuzzle(
                    result.id,
                    (),
                    None,
                    "unverified",
                    result.title,
                    result.theme,
                    issues=tuple(f"{e.code}: {e.message}" for e in result.errors)
                    or ("generation failed",),
                )
            )
            continue
        targets = result.puzzle.targets
        puzzles.append(
            InventoryPuzzle(
                result.id,
                tuple(sorted(t.search for t in targets)),
                result.puzzle.grid.rows,
                "verified",
                result.title,
                result.theme,
                display_words=tuple(t.display for t in targets),
            )
        )
    failed = sum(not p.verified for p in puzzles)
    coverage = Coverage(
        "complete" if not failed else "incomplete",
        None,
        len(puzzles),
        (f"{failed} puzzle(s) failed to generate.",) if failed else (),
    )
    return Inventory(
        label or project.book.id,
        "project",
        source_name,
        build_identity(project),
        tuple(puzzles),
        coverage,
        book_id=project.book.id,
    )


# --- PDF sources -------------------------------------------------------------------


@dataclass(frozen=True)
class _Item:
    x: float
    y: float
    size: float
    text: str
    bold: bool = False


@dataclass
class _Page:
    number: int
    items: list[_Item] = field(default_factory=list)
    grid: tuple[str, ...] | None = None
    grid_issue: str | None = None
    words: tuple[str, ...] = ()
    title: str | None = None
    theme: str | None = None
    folio: str | None = None


def _page_items(page: object) -> list[_Item]:
    items: list[_Item] = []

    def visit(
        text: str, cm: Sequence[float], tm: Sequence[float], font: object, size: float
    ) -> None:
        for part in text.split("\n"):
            stripped = part.strip()
            if stripped:
                scale = abs(float(cm[0])) if cm and float(cm[0]) else 1.0
                x = float(tm[4]) * scale + float(cm[4])
                y = float(tm[5]) * scale + float(cm[5])
                name = str(font.get("/BaseFont", "")) if isinstance(font, dict) else ""
                items.append(_Item(x, y, round(float(size) * scale, 1), stripped, "Bold" in name))

    page.extract_text(visitor_text=visit)  # type: ignore[attr-defined]
    return items


def _has_images(page: object) -> bool:
    try:
        resources: Any = page.get("/Resources")  # type: ignore[attr-defined]
        if resources is None:
            return False
        xobjects = resources.get_object().get("/XObject") or {}
        return any(xobjects[name].get_object().get("/Subtype") == "/Image" for name in xobjects)
    except Exception:  # noqa: BLE001 - unknown structure counts as possible content.
        return True


def _rows(letters: list[_Item]) -> list[list[_Item]]:
    rows: list[list[_Item]] = []
    for item in sorted(letters, key=lambda i: (-i.y, i.x)):
        if rows and abs(rows[-1][0].y - item.y) <= item.size * 0.3:
            rows[-1].append(item)
        else:
            rows.append([item])
    return [sorted(row, key=lambda i: i.x) for row in rows]


def _analyze(page: _Page) -> None:
    letters = [i for i in page.items if _LETTER.match(i.text)]
    multi = [i for i in page.items if not _LETTER.match(i.text)]
    if letters:
        sizes: dict[float, int] = {}
        for item in letters:
            sizes[item.size] = sizes.get(item.size, 0) + 1
        size = max(sorted(sizes), key=lambda s: sizes[s])
        grid_letters = [i for i in letters if i.size == size]
        rows = _rows(grid_letters)
        widths = {len(r) for r in rows}
        if len(rows) >= 2 and len(widths) == 1 and min(widths) >= 2:
            page.grid = tuple("".join(i.text for i in row) for row in rows)
        elif len(grid_letters) >= 4:
            page.grid_issue = f"irregular letter grid (row lengths {sorted(widths)})"
    candidates = [i for i in multi if _WORD.match(i.text) and len(i.text) > 1]
    if candidates:
        counts: dict[float, int] = {}
        for item in candidates:
            counts[item.size] = counts.get(item.size, 0) + 1
        word_size = max(sorted(counts), key=lambda s: counts[s])
        page.words = tuple(i.text for i in candidates if i.size == word_size)
    others = [i for i in multi if i.text not in page.words]
    folios = [i for i in others if _FOLIO.match(i.text)]
    if folios:
        page.folio = min(folios, key=lambda i: i.y).text
    headings = sorted(
        (i for i in others if not _FOLIO.match(i.text)), key=lambda i: (-i.size, -i.y)
    )
    if headings:
        page.title = headings[0].text
        below = [i for i in headings[1:] if i.y < headings[0].y]
        if below:
            page.theme = max(below, key=lambda i: i.y).text


def _verify(words: tuple[str, ...], grid: tuple[str, ...]) -> tuple[str, ...]:
    """Issues: listed words that cannot be found in straight lines in the grid."""
    from .quality import screen_words
    from .wordsearch import Grid, WordSearchError

    forms = sorted({normalize_word(w) for w in words})
    if len(forms) != len(words):
        return ("the word list repeats a word",)
    if len(forms) > 100:
        return ("more than 100 words; not verified",)
    try:
        found = {o.word for o in screen_words(Grid(grid), forms).occurrences}
    except WordSearchError as error:
        return tuple(f"grid: {issue.message}" for issue in error.issues)
    missing = [w for w in forms if w not in found]
    return tuple(f"word not found in the grid: {w}" for w in missing)


def _puzzle(page: _Page, grid: tuple[str, ...] | None, extra: str = "") -> InventoryPuzzle:
    issues: list[str] = []
    if grid is None:
        issues.append(page.grid_issue or "no letter grid found")
    else:
        issues.extend(_verify(page.words, grid))
    return InventoryPuzzle(
        f"page-{page.number:04d}",
        tuple(sorted({normalize_word(w) for w in page.words})),
        grid,
        "unverified" if issues else "verified",
        page.title,
        page.theme,
        page.number,
        page.folio,
        page.words,
        tuple(issues) + ((extra,) if extra and issues else ()),
    )


def inventory_from_pdf(
    path: str | Path, expected_puzzles: int | None = None, label: str | None = None
) -> Inventory:
    """Extract puzzles from an interior PDF's text; never claims unchecked coverage."""
    source = Path(path)
    try:
        if source.stat().st_size > MAX_PDF_BYTES:
            raise _fail("previous", "too_large", f"{source.name} is larger than 512 MB.")
        data = source.read_bytes()
    except OSError as error:
        raise _fail("previous", "io", f"Cannot read {source}: {error}") from error
    pages, skipped, count = read_pdf_pages(data, source.name)
    return _inventory_from_pages(source, data, pages, skipped, count, expected_puzzles, label)


def read_pdf_pages(data: bytes, name: str) -> tuple[list[_Page], list[SkippedPage], int]:
    """Analyzed pages with text, the pages without, and the page count."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise _fail("previous", "encrypted", f"{name} is encrypted.")
        count = len(reader.pages)
    except (PdfReadError, ValueError, KeyError, TypeError) as error:
        raise _fail("previous", "pdf", f"{name} is not a readable PDF: {error}") from error
    pages: list[_Page] = []
    skipped: list[SkippedPage] = []
    for index in range(count):
        checkpoint("read_pdf_text", index, count)
        page = _Page(index + 1)
        try:
            page.items = _page_items(reader.pages[index])
        except Exception:  # noqa: BLE001 - a damaged page is reported, never fatal.
            skipped.append(SkippedPage(index + 1, "unreadable"))
            continue
        if not page.items:
            reason = "no_text" if _has_images(reader.pages[index]) else "blank"
            skipped.append(SkippedPage(index + 1, reason))
            continue
        _analyze(page)
        pages.append(page)
    return pages, skipped, count


def _inventory_from_pages(
    source: Path,
    data: bytes,
    pages: list[_Page],
    skipped: list[SkippedPage],
    count: int,
    expected_puzzles: int | None,
    label: str | None,
) -> Inventory:
    puzzles: list[InventoryPuzzle] = []
    i = 0
    while i < len(pages):
        page = pages[i]
        following = pages[i + 1] if i + 1 < len(pages) else None
        if page.words and (page.grid is not None or page.grid_issue):
            puzzles.append(_puzzle(page, page.grid))
        elif (
            page.words
            and following is not None
            and following.number == page.number + 1
            and following.grid is not None
            and not following.words
        ):
            # A spread: the word list faces the grid on the next page.
            puzzles.append(_puzzle(page, following.grid, "spread pairing"))
            i += 1
        elif page.words:
            puzzles.append(_puzzle(page, None))
        elif page.grid is not None or page.grid_issue:
            skipped.append(SkippedPage(page.number, "grid_without_words"))
        else:
            skipped.append(SkippedPage(page.number, "no_puzzle_content"))
        i += 1
        if len(puzzles) > MAX_PUZZLES:
            raise _fail("previous", "too_many", "More than 2,000 puzzle pages; not supported.")
    skipped.sort(key=lambda s: s.page)
    verified = sum(p.verified for p in puzzles)
    notes: list[str] = []
    unverified = len(puzzles) - verified
    if unverified:
        notes.append(f"{unverified} puzzle page(s) could not be verified.")
    unreadable = [s.page for s in skipped if s.reason in ("no_text", "unreadable")]
    if unreadable:
        notes.append(
            f"{len(unreadable)} page(s) had images but no extractable text, or could not "
            "be read (scanned or damaged): "
            + ", ".join(map(str, unreadable[:20]))
            + ("..." if len(unreadable) > 20 else "")
        )
    grid_only = sum(s.reason == "grid_without_words" for s in skipped)
    if grid_only:
        notes.append(
            f"{grid_only} page(s) hold grids without a word list (usually solution pages); "
            "they are not compared."
        )
    if expected_puzzles is not None and verified != expected_puzzles:
        notes.append(f"Verified {verified} puzzle(s); expected {expected_puzzles}.")
    if unverified or unreadable or (expected_puzzles is not None and verified != expected_puzzles):
        status = "incomplete"
    elif expected_puzzles is None:
        status = "unconfirmed"
        notes.append(
            "The total puzzle count was not supplied (--expected-puzzles), so complete "
            "coverage is not claimed."
        )
    else:
        status = "complete"
    return Inventory(
        label or source.stem,
        "pdf",
        source.name,
        hashlib.sha256(data).hexdigest(),
        tuple(puzzles),
        Coverage(status, count, expected_puzzles, tuple(notes)),
        tuple(skipped),
    )


# --- Saved inventories -------------------------------------------------------------


def _expect(data: Mapping[str, object], key: str, kind: type | tuple[type, ...], path: str) -> Any:
    value = data.get(key)
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise _fail(f"{path}.{key}", "type", f"Expected {key} to be a valid value.")
    return value


def _optional_str(data: Mapping[str, object], key: str, path: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise _fail(f"{path}.{key}", "type", f"Expected {key} to be text or null.")
    return value


def _string_list(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _fail(path, "type", "Expected a list of strings.")
    return tuple(value)


def parse_inventory(text: str, name: str = "inventory.json") -> Inventory:
    """Read this module's JSON format; malformed or unknown versions are errors."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise _fail("inventory", "json", f"{name} is not valid JSON: {error.msg}") from error
    if not isinstance(data, dict) or data.get("kind") != INVENTORY_KIND:
        raise _fail("inventory", "kind", f"{name} is not a PuzzlePress puzzle inventory.")
    if data.get("inventory_version") != INVENTORY_VERSION:
        raise _fail("inventory.inventory_version", "version", "Unsupported inventory version.")
    _expect(data, "source", dict, "inventory")
    coverage_data = _expect(data, "coverage", dict, "inventory")
    status = coverage_data.get("status")
    if status not in ("complete", "incomplete", "unconfirmed"):
        raise _fail("inventory.coverage.status", "value", "Unknown coverage status.")
    raw_puzzles = _expect(data, "puzzles", list, "inventory")
    if len(raw_puzzles) > MAX_PUZZLES:
        raise _fail("inventory.puzzles", "count", "More than 2,000 puzzles.")
    puzzles: list[InventoryPuzzle] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_puzzles):
        path = f"inventory.puzzles[{index}]"
        if not isinstance(raw, dict):
            raise _fail(path, "type", "Expected a puzzle object.")
        puzzle_id = _expect(raw, "id", str, path)
        if puzzle_id in seen:
            raise _fail(f"{path}.id", "duplicate", f"Duplicate puzzle id {puzzle_id}.")
        seen.add(puzzle_id)
        state = raw.get("status")
        if state not in ("verified", "unverified"):
            raise _fail(f"{path}.status", "value", "Expected verified or unverified.")
        words = _string_list(raw.get("words"), f"{path}.words")
        if any(not re.fullmatch(r"[A-Z]{1,50}", w) for w in words):
            raise _fail(f"{path}.words", "value", "Words must be normalized A-Z search forms.")
        grid_raw = raw.get("grid")
        grid = None if grid_raw is None else _string_list(grid_raw, f"{path}.grid")
        if grid is not None and (
            not grid
            or len({len(r) for r in grid}) != 1
            or any(not re.fullmatch(r"[A-Z]+", r) for r in grid)
        ):
            raise _fail(f"{path}.grid", "value", "Expected a rectangular A-Z grid.")
        if state == "verified" and not words:
            raise _fail(f"{path}.words", "value", "A verified puzzle needs its words.")
        page = raw.get("page")
        if page is not None and (not isinstance(page, int) or isinstance(page, bool)):
            raise _fail(f"{path}.page", "type", "Expected a page number or null.")
        puzzles.append(
            InventoryPuzzle(
                puzzle_id,
                tuple(sorted(set(words))),
                grid,
                state,
                _optional_str(raw, "title", path),
                _optional_str(raw, "theme", path),
                page,
                _optional_str(raw, "folio", path),
                _string_list(raw.get("display_words", []), f"{path}.display_words"),
                _string_list(raw.get("issues", []), f"{path}.issues"),
            )
        )
    skipped = []
    for index, raw in enumerate(data.get("skipped_pages", [])):
        if not isinstance(raw, dict) or not isinstance(raw.get("page"), int):
            raise _fail(f"inventory.skipped_pages[{index}]", "type", "Expected a page entry.")
        skipped.append(SkippedPage(raw["page"], str(raw.get("reason", "unknown"))))
    pages = coverage_data.get("pages_examined")
    expected = coverage_data.get("expected_puzzles")
    for key, value in (("pages_examined", pages), ("expected_puzzles", expected)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise _fail(f"inventory.coverage.{key}", "type", "Expected a count or null.")
    notes = _string_list(coverage_data.get("notes", []), "inventory.coverage.notes")
    # A saved file cannot claim more than its own content shows.
    if status == "complete" and any(not p.verified for p in puzzles):
        raise _fail("inventory.coverage.status", "value", "Complete coverage lists unverified.")
    return Inventory(
        str(_expect(data, "label", str, "inventory")),
        "inventory",
        name,
        hashlib.sha256(text.encode("utf-8")).hexdigest(),
        tuple(puzzles),
        Coverage(str(status), pages, expected, notes),
        tuple(skipped),
        _optional_str(data, "book_id", "inventory"),
    )


def load_inventory(
    path: str | Path, expected_puzzles: int | None = None, label: str | None = None
) -> Inventory:
    """Auto-detect: a project (book.yaml or its folder), a PDF, a release folder
    holding `interior.pdf`, or a saved inventory `.json`. Reads only; never writes."""
    source = Path(path).expanduser()
    if not source.exists():
        raise _fail("previous", "not_found", f"Not found: {source}")
    if source.is_dir():
        if (source / "book.yaml").is_file():
            return inventory_from_project(source, label)
        if (source / "interior.pdf").is_file():
            return inventory_from_pdf(
                source / "interior.pdf", expected_puzzles, label or source.name
            )
        raise _fail(
            "previous",
            "unrecognized",
            f"{source} holds neither book.yaml nor interior.pdf; name the file directly.",
        )
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        return inventory_from_pdf(source, expected_puzzles, label)
    if suffix in (".yaml", ".yml"):
        return inventory_from_project(source, label)
    if suffix == ".json":
        try:
            text = source.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as error:
            raise _fail("previous", "io", f"Cannot read {source}: {error}") from error
        loaded = parse_inventory(text, source.name)
        return loaded if label is None else _relabel(loaded, label)
    raise _fail("previous", "unsupported", f"Unsupported source type: {source.name}")


def _relabel(inventory: Inventory, label: str) -> Inventory:
    from dataclasses import replace

    return replace(inventory, label=label)
