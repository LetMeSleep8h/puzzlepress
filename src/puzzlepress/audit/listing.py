"""Listing checks: what the title, subtitle, descriptions, cover text and keywords say.

These complement the publishing ruleset (which decides KDP metadata validity) with
consistency and discoverability observations. Nothing here changes a ruleset,
a report or an identity.
"""

import re
from dataclasses import dataclass

from ..cover_design import TextBoxElement
from ..models import Project
from ..planning.model import PlanningDocument
from ..publishing import text
from ..publishing.rules import KDP_METADATA, KEYWORDS
from .model import Basis, Category, Priority, Recommendation

PROGRESSION = re.compile(
    r"\b(?:harder|progressively|increas\w*\s+(?:in\s+)?difficult\w*|growing\s+difficult\w*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BookFacts:
    """Counts a listing may state, measured from the source and plan."""

    puzzles: int | None  # Word search only.
    themes: tuple[int, ...] | None  # Distinct themes, and distinct bases ("Engines - Warm-up").
    levels: int | None
    parts: int | None  # Divider pages; None when the book has no dividers.
    drawings: int | None  # Coloring only.


def _words(value: str) -> set[str]:
    found = re.findall(r"[^\W\d_]+", value.casefold())
    return {text.singular(w) for w in found if len(w) >= 3 and w not in text.STOPWORDS}


def cover_texts(project: Project) -> tuple[str, ...]:
    """The plain words printed on the cover beyond the book details."""
    cover = project.cover
    if cover is None:
        return ()
    found: list[str] = []
    if cover.back_text:
        found.append(cover.back_text)
    for element in cover.elements:
        if isinstance(element, TextBoxElement):
            plain = element.rich.plain() if element.rich is not None else element.text
            if plain:
                found.append(plain)
    found += [layer.text for layer in cover.extra if layer.text]
    return tuple(found)


# A count after one of these words is part of the book, not the whole ("the last two
# parts", "each of three levels"); "one ... at a time" is not a count at all.
PARTIAL = re.compile(
    r"\b(?:last|first|next|final|other|these|those|of|every|each|per|top|bottom|middle)\s*$",
    re.IGNORECASE,
)


def _whole(value: str, claims: list[tuple[str, int]]) -> list[tuple[str, int]]:
    kept: list[tuple[str, int]] = []
    start = 0
    for phrase, number in claims:
        at = value.find(phrase, start)
        start = at + len(phrase) if at >= 0 else start
        if number <= 1 or (at >= 0 and PARTIAL.search(value[max(0, at - 12) : at])):
            continue
        kept.append((phrase, number))
    return kept


def _claims(project: Project, facts: BookFacts) -> list[Recommendation]:
    fields: list[tuple[str, str, str]] = [
        ("book.title", project.book.title, "settings"),
    ]
    if project.book.subtitle:
        fields.append(("book.subtitle", project.book.subtitle, "settings"))
    if project.book.description:
        fields.append(("book.description", project.book.description, "settings"))
    if project.publishing is not None and project.publishing.description:
        fields.append(("publishing.description", project.publishing.description, "publishing"))
    fields += [("cover", value, "cover") for value in cover_texts(project)]
    # Levels (difficulty profiles) and parts (dividers) are exact; a theme is an
    # authored label that may carry a level ("Engines - Warm-up"), so either count is
    # accepted and a mismatch is a question rather than an error.
    checks: list[tuple[str, str, tuple[int, ...] | None, bool]] = [
        ("themes", r"themes?", facts.themes, False),
        ("levels", r"(?:difficulty\s+)?levels?", (facts.levels,) if facts.levels else None, True),
        ("parts", r"parts?|sections?", (facts.parts,) if facts.parts else None, True),
    ]
    found: list[Recommendation] = []
    for path, value, area in fields:
        mismatches: list[str] = []
        questions: list[str] = []
        for label, nouns, actual, exact in checks:
            if not actual:
                continue
            for phrase, number in _whole(value, text.count_claims(value, nouns)):
                if number not in actual:
                    shown = " or ".join(str(n) for n in sorted(set(actual)))
                    (mismatches if exact else questions).append(
                        f"'{phrase}' but the book has {shown} {label}"
                    )
        # The publishing ruleset already checks counts in the KDP description.
        if path != "publishing.description":
            if facts.puzzles is not None:
                for phrase, number in _whole(value, text.puzzle_claims(value)):
                    if number != facts.puzzles:
                        mismatches.append(f"'{phrase}' but the book has {facts.puzzles} puzzles")
            if facts.drawings is not None:
                for phrase, number in _whole(value, text.drawing_claims(value)):
                    if number != facts.drawings:
                        mismatches.append(
                            f"'{phrase}' but the book has {facts.drawings} coloring pages"
                        )
        where = "the cover text" if path == "cover" else path
        if questions:
            found.append(
                Recommendation(
                    "theme_count_differs",
                    Priority.MEDIUM,
                    Category.LISTING,
                    Basis.MEASURED,
                    "Text states a theme count the puzzle themes do not show",
                    f"{where}: " + "; ".join(questions) + " (distinct puzzle theme labels).",
                    "Check the number; if themes are grouped differently than the labels, "
                    "no change is needed.",
                    area,
                    field=None if path == "cover" else path,
                )
            )
        if mismatches:
            found.append(
                Recommendation(
                    "claim_mismatch",
                    Priority.HIGH,
                    Category.LISTING,
                    Basis.MEASURED,
                    "Text states a count the book does not have",
                    f"{where}: " + "; ".join(mismatches),
                    "Correct the number in the text (or the book) so what readers are told "
                    "matches what is printed.",
                    area,
                    field=None if path == "cover" else path,
                )
            )
    return found


def _keywords(project: Project) -> list[Recommendation]:
    config = project.publishing
    if config is None:
        return []
    found: list[Recommendation] = []
    keywords = config.keywords
    if len(keywords) < KDP_METADATA.max_keywords:
        unused = KDP_METADATA.max_keywords - len(keywords)
        found.append(
            Recommendation(
                "keyword_slots_unused",
                Priority.MEDIUM,
                Category.LISTING,
                Basis.KDP_HELP,
                f"{unused} of {KDP_METADATA.max_keywords} keyword slots unused",
                f"{len(keywords)} keyword(s) saved; KDP accepts up to "
                f"{KDP_METADATA.max_keywords} keywords or short phrases.",
                "Add phrases readers would search for that the title, subtitle and categories "
                "do not already contain.",
                "publishing",
                field="publishing.keywords",
                source=KEYWORDS.url,
            )
        )
    book = project.book
    metadata = set()
    for value in (book.title, book.subtitle or "", book.author or ""):
        metadata |= _words(value)
    for contributor in config.contributors:
        metadata |= _words(contributor.name)
    for category in config.categories:
        metadata |= _words(category)
    for i, keyword in enumerate(keywords):
        significant = _words(keyword)
        repeated = significant & metadata
        if not significant or not repeated:
            continue
        whole = repeated == significant
        if not whole and len(repeated) * 2 < len(significant):
            continue
        found.append(
            Recommendation(
                "keyword_repeats_metadata",
                Priority.MEDIUM if whole else Priority.LOW,
                Category.LISTING,
                Basis.KDP_HELP,
                "Keyword repeats the title, subtitle or categories"
                if whole
                else "Keyword mostly repeats the title, subtitle or categories",
                f"'{keyword}': {', '.join(sorted(repeated))} already in the title, subtitle, "
                "contributors or categories. KDP asks keywords to avoid information covered "
                "elsewhere in the metadata.",
                "Replace it with words the listing does not already contain (a subject, an "
                "occasion, a reader) — keep only what is true of the book.",
                "publishing",
                field=f"publishing.keywords.{i}",
                source=KEYWORDS.url,
            )
        )
    if config.categories and len(config.categories) < KDP_METADATA.max_categories:
        found.append(
            Recommendation(
                "category_slots_unused",
                Priority.LOW,
                Category.LISTING,
                Basis.KDP_HELP,
                f"{len(config.categories)} of {KDP_METADATA.max_categories} categories chosen",
                f"KDP lets you select {KDP_METADATA.max_categories} categories; "
                f"{len(config.categories)} saved.",
                "Consider a further category that truly fits the book; confirm it in KDP's "
                "selector.",
                "publishing",
                field="publishing.categories",
            )
        )
    return found


def _positioning(project: Project, plan: PlanningDocument | None) -> list[Recommendation]:
    audience = plan.positioning.primary_audience if plan is not None else None
    if not audience:
        return [
            Recommendation(
                "audience_unrecorded",
                Priority.LOW,
                Category.LISTING,
                Basis.JUDGMENT,
                "No primary audience recorded",
                "planning.yaml records no primary audience, so the audit cannot check that "
                "the title, subtitle, description and keywords speak to one reader.",
                "Record the reader you are writing for in the Plan (positioning).",
                "planning",
                field="positioning.primary_audience",
            )
        ]
    listing = " ".join(
        [
            project.book.title,
            project.book.subtitle or "",
            project.publishing.description or "" if project.publishing else "",
            " ".join(project.publishing.keywords) if project.publishing else "",
        ]
    )
    if _words(audience) & _words(listing):
        return []
    return [
        Recommendation(
            "audience_not_named",
            Priority.LOW,
            Category.LISTING,
            Basis.JUDGMENT,
            "The listing does not name the planned audience",
            f"The plan's primary audience is '{audience}', but none of its words appear in "
            "the title, subtitle, description or keywords.",
            "Decide whether the listing should say who the book is for.",
            "publishing",
        )
    ]


def listing_recommendations(
    project: Project, facts: BookFacts, plan: PlanningDocument | None
) -> list[Recommendation]:
    return [*_claims(project, facts), *_keywords(project), *_positioning(project, plan)]


def claims_progression(project: Project) -> bool:
    """Whether the book's own text promises puzzles that grow harder."""
    values = [project.book.description or "", *cover_texts(project)]
    if project.publishing is not None:
        values.append(project.publishing.description or "")
    if project.composition is not None:
        values += [item.text or "" for item in project.composition.front_matter]
    return any(PROGRESSION.search(value) for value in values)
