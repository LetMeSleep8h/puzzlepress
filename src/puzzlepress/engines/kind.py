"""Which content engine a book uses: derived from its sections, never authored twice.

A schema-v1 book selects its engine by the content section it carries. Every
existing project, including a legacy one with neither section, is a word-search
project, so no source file changes and no identity moves. This module imports
only the shared error type, so models and validation can depend on it.
"""

from enum import StrEnum

from ..errors import ValidationIssue


class EngineKind(StrEnum):
    WORD_SEARCH = "word_search"
    COLORING = "coloring"


# The book.yaml section that selects each engine.
SECTIONS: dict[EngineKind, str] = {
    EngineKind.WORD_SEARCH: "word_search",
    EngineKind.COLORING: "coloring",
}

# Engines this version can validate, plan and build. A recognised but unavailable
# engine is reported, never read with another engine's rules.
AVAILABLE: frozenset[EngineKind] = frozenset({EngineKind.WORD_SEARCH})


def detect_engine(source: object) -> tuple[EngineKind | None, tuple[ValidationIssue, ...]]:
    """Derive the engine from a decoded source mapping.

    Returns None with issues when the source names more than one engine or one this
    version cannot build. A non-mapping is left to schema validation.
    """
    if not isinstance(source, dict):
        return None, ()
    present = [kind for kind, section in SECTIONS.items() if section in source]
    if len(present) > 1:
        names = " and ".join(SECTIONS[kind] for kind in present)
        later = SECTIONS[present[-1]]
        return None, (
            ValidationIssue(
                later,
                "engine_conflict",
                f"A book uses one content engine, but this source has {names}. "
                "Keep one section and move the other content to its own project.",
            ),
        )
    kind = present[0] if present else EngineKind.WORD_SEARCH
    if kind not in AVAILABLE:
        from .. import __version__

        return None, (
            ValidationIssue(
                SECTIONS[kind],
                "engine_unavailable",
                f"The {kind.value} engine is not available in PuzzlePress {__version__}. "
                f"Remove the {SECTIONS[kind]} section or open this book with a version "
                "that supports it.",
            ),
        )
    return kind, ()
