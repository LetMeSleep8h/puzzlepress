"""Renderer-independent book composition: matter, section and numbering policy.

Publication order of puzzles is the authored `word_search.puzzles` sequence.
Composition never selects, repeats or reorders puzzles on its own.
"""

from dataclasses import dataclass
from enum import StrEnum

COMPOSITION_VERSION = 1


class MatterKind(StrEnum):
    TITLE_PAGE = "title_page"
    COPYRIGHT_PAGE = "copyright_page"
    INSTRUCTIONS = "instructions"
    ABOUT = "about"
    NOTES = "notes"


FRONT_MATTER_KINDS = (MatterKind.TITLE_PAGE, MatterKind.COPYRIGHT_PAGE, MatterKind.INSTRUCTIONS)
BACK_MATTER_KINDS = (MatterKind.ABOUT, MatterKind.NOTES)
# Fields each kind accepts, in addition to `kind`; all listed fields are required.
MATTER_FIELDS: dict[MatterKind, tuple[str, ...]] = {
    MatterKind.TITLE_PAGE: (),
    MatterKind.COPYRIGHT_PAGE: ("text",),
    MatterKind.INSTRUCTIONS: ("title", "text"),
    MatterKind.ABOUT: ("title", "text"),
    MatterKind.NOTES: ("title",),
}


class SectionStart(StrEnum):
    ANY = "any"
    RECTO = "recto"


class SolutionPlacement(StrEnum):
    END = "end"
    OMIT = "omit"


class NumberingScheme(StrEnum):
    CONTINUOUS = "continuous"
    ROMAN_FRONT_MATTER = "roman_front_matter"


class PuzzleLayout(StrEnum):
    """How many pages one puzzle occupies. Pagination, so composition, never style."""

    SINGLE = "single"  # Title, grid and word list on one page.
    SPREAD = "spread"  # Word list on a left-hand page facing the grid on the right.


# Solutions grouped on one printed page. Four (a 2 x 2 arrangement) is the default
# when a composition places solutions without stating a count.
SOLUTIONS_PER_PAGE = (1, 2, 4, 6, 8)
DEFAULT_SOLUTIONS_PER_PAGE = 4
MAX_DIVIDER_TEXT = 600
MAX_DIVIDER_QUOTE = 300


@dataclass(frozen=True)
class MatterItem:
    """One logical page of authored matter. Title pages use book metadata."""

    kind: MatterKind
    title: str | None = None
    text: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"kind": self.kind.value}
        for field in MATTER_FIELDS[self.kind]:
            data[field] = getattr(self, field)
        return data


@dataclass(frozen=True)
class SolutionPolicy:
    """Where solutions appear and how many are grouped on one logical page.

    Grouping is semantic (which solutions share a page); arrangement within a
    page is a renderer decision. A renderer must reject, not regroup, a density
    it cannot fit.
    """

    placement: SolutionPlacement = SolutionPlacement.END
    title: str | None = None
    per_page: int = DEFAULT_SOLUTIONS_PER_PAGE
    start: SectionStart = SectionStart.ANY

    def to_dict(self) -> dict[str, object]:
        if self.placement is SolutionPlacement.OMIT:
            return {"placement": self.placement.value}
        return {
            "placement": self.placement.value,
            "title": self.title,
            "per_page": self.per_page,
            "start": self.start.value,
        }


@dataclass(frozen=True)
class PageNumberPolicy:
    scheme: NumberingScheme = NumberingScheme.CONTINUOUS
    show_front_matter: bool = False
    show_solutions: bool = True
    show_back_matter: bool = True
    # Coloring books only (None for word search, so its identities never change):
    # whether coloring pages print their number. Coloring books have no solutions.
    show_artwork: bool | None = None

    def to_dict(self) -> dict[str, object]:
        if self.show_artwork is not None:
            return {
                "scheme": self.scheme.value,
                "show_front_matter": self.show_front_matter,
                "show_artwork": self.show_artwork,
                "show_back_matter": self.show_back_matter,
            }
        return {
            "scheme": self.scheme.value,
            "show_front_matter": self.show_front_matter,
            "show_solutions": self.show_solutions,
            "show_back_matter": self.show_back_matter,
        }


@dataclass(frozen=True)
class ThemeDivider:
    """Authored text for one theme's divider page. Nothing here is generated.

    `quote` and `attribution` are the author's own, optional words; PuzzlePress
    never supplies a quotation or a source.
    """

    theme: str
    title: str | None = None  # None: the theme name.
    text: str | None = None
    quote: str | None = None
    attribution: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"theme": self.theme}
        for key in ("title", "text", "quote", "attribution"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data


@dataclass(frozen=True)
class DividerPolicy:
    """A divider page before each theme group of puzzles (explicit plan pages).

    Each theme's puzzles must be consecutive in publication order. `start: recto`
    puts every divider on a right-hand page with an explicit blank before it when
    needed.
    """

    start: SectionStart = SectionStart.ANY
    themes: tuple[ThemeDivider, ...] = ()

    def entry(self, theme: str) -> ThemeDivider:
        return next((t for t in self.themes if t.theme == theme), ThemeDivider(theme))

    def to_dict(self) -> dict[str, object]:
        return {"start": self.start.value, "themes": [t.to_dict() for t in self.themes]}


@dataclass(frozen=True)
class ArtworkPolicy:
    """Where a coloring book's artwork section starts (right-hand page by default).

    Page order, section dividers and blank reverse pages are the `coloring`
    section's: composition only places the section among the book's matter.
    """

    start: SectionStart = SectionStart.RECTO

    def to_dict(self) -> dict[str, object]:
        return {"start": self.start.value}


# A coloring composition has no solutions; this neutral policy is never serialized.
NO_SOLUTIONS = SolutionPolicy(SolutionPlacement.OMIT)


@dataclass(frozen=True)
class Composition:
    """Solution policy is required: a book must state its solution decision.

    A coloring book's composition sets `artwork` instead and states no solution
    decision (`solutions` is NO_SOLUTIONS); it serializes front matter, the artwork
    section, back matter and page numbers only.
    """

    solutions: SolutionPolicy
    front_matter: tuple[MatterItem, ...] = ()
    puzzles_start: SectionStart = SectionStart.ANY
    back_matter: tuple[MatterItem, ...] = ()
    page_numbers: PageNumberPolicy = PageNumberPolicy()
    # Present only when the author enables dividers, so earlier identities never change.
    dividers: DividerPolicy | None = None
    # Recorded only for spreads, so single-page books keep their identities.
    puzzle_layout: PuzzleLayout = PuzzleLayout.SINGLE
    # Coloring books only: the artwork section's placement.
    artwork: ArtworkPolicy | None = None

    def to_dict(self) -> dict[str, object]:
        if self.artwork is not None:
            return {
                "front_matter": [item.to_dict() for item in self.front_matter],
                "artwork": self.artwork.to_dict(),
                "back_matter": [item.to_dict() for item in self.back_matter],
                "page_numbers": self.page_numbers.to_dict(),
            }
        puzzles: dict[str, object] = {"start": self.puzzles_start.value}
        if self.puzzle_layout is not PuzzleLayout.SINGLE:
            puzzles["layout"] = self.puzzle_layout.value
        if self.dividers is not None:
            puzzles["dividers"] = self.dividers.to_dict()
        return {
            "front_matter": [item.to_dict() for item in self.front_matter],
            "puzzles": puzzles,
            "solutions": self.solutions.to_dict(),
            "back_matter": [item.to_dict() for item in self.back_matter],
            "page_numbers": self.page_numbers.to_dict(),
        }
