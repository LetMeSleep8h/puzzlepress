"""Schema-v1 optional composition section. Collects independent issues; never repairs."""

from typing import TypeVar

from .composition import (
    BACK_MATTER_KINDS,
    DEFAULT_SOLUTIONS_PER_PAGE,
    FRONT_MATTER_KINDS,
    MATTER_FIELDS,
    MAX_DIVIDER_QUOTE,
    MAX_DIVIDER_TEXT,
    NO_SOLUTIONS,
    SOLUTIONS_PER_PAGE,
    ArtworkPolicy,
    Composition,
    DividerPolicy,
    MatterItem,
    MatterKind,
    NumberingScheme,
    PageNumberPolicy,
    PuzzleLayout,
    SectionStart,
    SolutionPlacement,
    SolutionPolicy,
    ThemeDivider,
)
from .content import PuzzleDefinition
from .content_validation import _Reader
from .errors import ValidationIssue

MAX_BODY_TEXT = 2000
Choice = TypeVar("Choice", SectionStart, SolutionPlacement, NumberingScheme, PuzzleLayout)


def validate_composition(
    value: object, has_puzzles: bool, coloring: bool = False
) -> tuple[Composition | None, tuple[ValidationIssue, ...]]:
    """Validate composition; `has_puzzles` states whether word_search is declared.

    `coloring` selects a coloring book's composition: front matter, the artwork
    section's start, back matter and page numbers. Puzzle and solution settings
    do not apply to it and are reported, never ignored.
    """
    if coloring:
        return _coloring_composition(value)
    reader = _Reader()
    path = "composition"
    root = reader.mapping(
        value, path, {"front_matter", "puzzles", "solutions", "back_matter", "page_numbers"}
    )
    if not isinstance(value, dict):
        return None, tuple(reader.issues)
    if not has_puzzles:
        reader.issue(
            path, "requires_puzzles", "Composition requires word_search puzzle definitions."
        )
    front = _matter(
        reader, root.get("front_matter", []), f"{path}.front_matter", FRONT_MATTER_KINDS
    )
    back = _matter(reader, root.get("back_matter", []), f"{path}.back_matter", BACK_MATTER_KINDS)
    puzzles = reader.mapping(
        root.get("puzzles", {}), f"{path}.puzzles", {"start", "layout", "dividers"}
    )
    puzzles_start = _choice(
        reader, puzzles.get("start", "any"), f"{path}.puzzles.start", SectionStart
    )
    layout = _choice(
        reader, puzzles.get("layout", "single"), f"{path}.puzzles.layout", PuzzleLayout
    )
    dividers = (
        _dividers(reader, puzzles["dividers"], f"{path}.puzzles.dividers")
        if "dividers" in puzzles
        else None
    )
    solutions = _solutions(reader, root.get("solutions"), f"{path}.solutions", "solutions" in root)
    numbers = _page_numbers(reader, root.get("page_numbers", {}), f"{path}.page_numbers")
    if numbers.scheme is NumberingScheme.ROMAN_FRONT_MATTER and not front:
        reader.issue(
            f"{path}.page_numbers.scheme",
            "requires_front_matter",
            "Roman front-matter numbering requires at least one front-matter page.",
        )
    if layout is PuzzleLayout.SPREAD and puzzles_start is SectionStart.RECTO and dividers is None:
        reader.issue(
            f"{path}.puzzles.start",
            "spread_starts_verso",
            "A spread opens on a left-hand page, so puzzles cannot start on a right-hand "
            "page. Start puzzles on any page, or add theme dividers that start recto.",
        )
    if reader.issues or solutions is None:
        return None, tuple(reader.issues)
    return (
        Composition(solutions, tuple(front), puzzles_start, tuple(back), numbers, dividers, layout),
        (),
    )


def _limited(reader: _Reader, value: object, path: str, limit: int) -> str:
    text = _body(reader, value, path)
    if len(text) > limit:
        reader.issue(path, "text", f"Expected at most {limit} characters.")
    return text


def _dividers(reader: _Reader, raw: object, path: str) -> DividerPolicy:
    data = reader.mapping(raw, path, {"start", "themes"})
    start = _choice(reader, data.get("start", "any"), f"{path}.start", SectionStart)
    themes: list[ThemeDivider] = []
    seen: set[str] = set()
    for index, entry in enumerate(
        reader.sequence(data.get("themes", []), f"{path}.themes", 100, 0)
    ):
        item = f"{path}.themes.{index}"
        values = reader.mapping(entry, item, {"theme", "title", "text", "quote", "attribution"})
        theme = reader.text(values.get("theme"), f"{item}.theme")
        if theme in seen:
            reader.issue(f"{item}.theme", "duplicate", f"Theme {theme!r} is listed twice.")
        seen.add(theme)
        title = _title(reader, values["title"], f"{item}.title") if "title" in values else None
        text = (
            _limited(reader, values["text"], f"{item}.text", MAX_DIVIDER_TEXT)
            if "text" in values
            else None
        )
        quote = (
            _limited(reader, values["quote"], f"{item}.quote", MAX_DIVIDER_QUOTE)
            if "quote" in values
            else None
        )
        attribution = (
            _title(reader, values["attribution"], f"{item}.attribution")
            if "attribution" in values
            else None
        )
        if attribution is not None and quote is None:
            reader.issue(
                f"{item}.attribution", "requires_quote", "An attribution belongs to a quote."
            )
        themes.append(ThemeDivider(theme, title, text, quote, attribution))
    return DividerPolicy(start, tuple(themes))


def _choice(reader: _Reader, value: object, path: str, enum: type[Choice]) -> Choice:
    names = [member.value for member in enum]
    if not isinstance(value, str) or value not in names:
        reader.issue(path, "choice", f"Use one of: {', '.join(names)}.")
        return next(iter(enum))
    return enum(value)


def _flag(reader: _Reader, value: object, path: str) -> bool:
    if type(value) is not bool:
        reader.issue(path, "type", "Expected true or false.")
        return False
    return value


def _title(reader: _Reader, value: object, path: str) -> str:
    text = reader.text(value, path)
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        reader.issue(path, "text", "Titles are a single line without control characters.")
    return text


def _body(reader: _Reader, value: object, path: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_BODY_TEXT
        or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
        or any((ord(c) < 32 and c != "\n") or ord(c) == 127 for c in value)
    ):
        reader.issue(
            path,
            "text",
            f"Expected 1..{MAX_BODY_TEXT} characters of plain text; line breaks are allowed.",
        )
        return ""
    return value.strip()


def _matter(
    reader: _Reader, raw: object, path: str, kinds: tuple[MatterKind, ...]
) -> list[MatterItem]:
    items: list[MatterItem] = []
    seen: set[MatterKind] = set()
    for i, entry in enumerate(reader.sequence(raw, path, len(kinds), 0)):
        item_path = f"{path}.{i}"
        if not isinstance(entry, dict):
            reader.mapping(entry, item_path, set())
            continue
        raw_kind = entry.get("kind")
        if not isinstance(raw_kind, str) or raw_kind not in {kind.value for kind in kinds}:
            reader.mapping(entry, item_path, {"kind", "title", "text"})
            reader.issue(
                f"{item_path}.kind",
                "kind",
                f"Supported kinds here: {', '.join(kind.value for kind in kinds)}.",
            )
            continue
        kind = MatterKind(raw_kind)
        fields = MATTER_FIELDS[kind]
        data = reader.mapping(entry, item_path, {"kind", *fields})
        if kind in seen:
            reader.issue(f"{item_path}.kind", "duplicate_kind", f"Only one {kind.value} page.")
        seen.add(kind)
        if kind is MatterKind.TITLE_PAGE and i:
            reader.issue(item_path, "order", "The title page must be the first page.")
        title = (
            _title(reader, data.get("title"), f"{item_path}.title") if "title" in fields else None
        )
        text = _body(reader, data.get("text"), f"{item_path}.text") if "text" in fields else None
        items.append(MatterItem(kind, title, text))
    return items


def _solutions(reader: _Reader, raw: object, path: str, present: bool) -> SolutionPolicy | None:
    if not present:
        reader.issue(path, "required", "Choose a solution placement: end or omit.")
        return None
    data = reader.mapping(raw, path, {"placement", "title", "per_page", "start"})
    placement = _choice(reader, data.get("placement"), f"{path}.placement", SolutionPlacement)
    if placement is SolutionPlacement.OMIT:
        for key in sorted({"title", "per_page", "start"} & set(data)):
            reader.issue(
                f"{path}.{key}", "not_applicable", "Only applies when solutions are placed."
            )
        return SolutionPolicy(placement)
    title = _title(reader, data.get("title"), f"{path}.title")
    per_page = data.get("per_page", DEFAULT_SOLUTIONS_PER_PAGE)
    if type(per_page) is not int or per_page not in SOLUTIONS_PER_PAGE:
        reader.issue(
            f"{path}.per_page",
            "choice",
            f"Use one of: {', '.join(map(str, SOLUTIONS_PER_PAGE))} solutions a printed page.",
        )
        per_page = DEFAULT_SOLUTIONS_PER_PAGE
    start = _choice(reader, data.get("start", "any"), f"{path}.start", SectionStart)
    return SolutionPolicy(placement, title, per_page, start)


def _page_numbers(reader: _Reader, raw: object, path: str) -> PageNumberPolicy:
    data = reader.mapping(
        raw, path, {"scheme", "show_front_matter", "show_solutions", "show_back_matter"}
    )
    defaults = PageNumberPolicy()
    scheme = data.get("scheme", defaults.scheme.value)
    return PageNumberPolicy(
        _choice(reader, scheme, f"{path}.scheme", NumberingScheme),
        _flag(reader, data.get("show_front_matter", False), f"{path}.show_front_matter"),
        _flag(reader, data.get("show_solutions", True), f"{path}.show_solutions"),
        _flag(reader, data.get("show_back_matter", True), f"{path}.show_back_matter"),
    )


def divider_issues(
    composition: Composition, puzzles: tuple[PuzzleDefinition, ...]
) -> list[ValidationIssue]:
    """Dividers need each theme's puzzles to be consecutive and name only real themes."""
    issues: list[ValidationIssue] = []
    assert composition.dividers is not None
    finished: set[str] = set()
    previous: str | None = None
    for index, puzzle in enumerate(puzzles):
        if puzzle.theme != previous:
            if puzzle.theme in finished:
                issues.append(
                    ValidationIssue(
                        f"word_search.puzzles.{index}.theme",
                        "themes_not_contiguous",
                        f"Theme {puzzle.theme!r} returns after another theme; divider pages "
                        "need each theme's puzzles together in publication order.",
                    )
                )
            if previous is not None:
                finished.add(previous)
            previous = puzzle.theme
    known = {puzzle.theme for puzzle in puzzles}
    for index, entry in enumerate(composition.dividers.themes):
        if entry.theme not in known:
            issues.append(
                ValidationIssue(
                    f"composition.puzzles.dividers.themes.{index}.theme",
                    "unknown_theme",
                    f"No puzzle has the theme {entry.theme!r}.",
                )
            )
    return issues


# Settings that belong to word-search books only, with the reason given to authors.
_WORD_SEARCH_ONLY = {
    "puzzles": "Coloring books have no puzzles; place the artwork section with artwork.start.",
    "solutions": "Coloring books have no solutions to place.",
}


def _coloring_composition(value: object) -> tuple[Composition | None, tuple[ValidationIssue, ...]]:
    """A coloring book's composition. Never repairs; collects independent issues."""
    reader = _Reader()
    path = "composition"
    if not isinstance(value, dict):
        reader.mapping(value, path, set())
        return None, tuple(reader.issues)
    for key, reason in _WORD_SEARCH_ONLY.items():
        if key in value:
            reader.issue(f"{path}.{key}", "not_applicable_for_engine", reason)
    known = {"front_matter", "artwork", "back_matter", "page_numbers"}
    reader.mapping({k: v for k, v in value.items() if k not in _WORD_SEARCH_ONLY}, path, known)
    front = _matter(
        reader, value.get("front_matter", []), f"{path}.front_matter", FRONT_MATTER_KINDS
    )
    back = _matter(reader, value.get("back_matter", []), f"{path}.back_matter", BACK_MATTER_KINDS)
    artwork = reader.mapping(value.get("artwork", {}), f"{path}.artwork", {"start"})
    start = _choice(reader, artwork.get("start", "recto"), f"{path}.artwork.start", SectionStart)
    raw_numbers = value.get("page_numbers", {})
    numbers_path = f"{path}.page_numbers"
    if isinstance(raw_numbers, dict) and "show_solutions" in raw_numbers:
        reader.issue(
            f"{numbers_path}.show_solutions",
            "not_applicable_for_engine",
            "Coloring books have no solutions; use show_artwork for coloring pages.",
        )
        raw_numbers = {k: v for k, v in raw_numbers.items() if k != "show_solutions"}
    data = reader.mapping(
        raw_numbers,
        numbers_path,
        {"scheme", "show_front_matter", "show_artwork", "show_back_matter"},
    )
    numbers = PageNumberPolicy(
        _choice(
            reader, data.get("scheme", "continuous"), f"{numbers_path}.scheme", NumberingScheme
        ),
        _flag(reader, data.get("show_front_matter", False), f"{numbers_path}.show_front_matter"),
        True,
        _flag(reader, data.get("show_back_matter", True), f"{numbers_path}.show_back_matter"),
        _flag(reader, data.get("show_artwork", True), f"{numbers_path}.show_artwork"),
    )
    if numbers.scheme is NumberingScheme.ROMAN_FRONT_MATTER and not front:
        reader.issue(
            f"{numbers_path}.scheme",
            "requires_front_matter",
            "Roman front-matter numbering requires at least one front-matter page.",
        )
    if reader.issues:
        return None, tuple(reader.issues)
    return (
        Composition(
            NO_SOLUTIONS,
            tuple(front),
            back_matter=tuple(back),
            page_numbers=numbers,
            artwork=ArtworkPolicy(start),
        ),
        (),
    )
