"""Replacement suggestions for puzzles flagged as duplicates."""

from collections.abc import Mapping, Sequence

from ..inventory import Inventory, normalize_word
from ..models import Project


def replacement_candidates(
    project: Project, previous: Sequence[Inventory], limit: int = 10
) -> Mapping[str, tuple[str, ...]]:
    """Per puzzle: entries of its own bank that it does not use, that no previous
    puzzle uses, ordered by how rarely this book already uses them, then bank order."""
    content = project.word_search
    if content is None:
        return {}
    banks = {bank.id: bank for bank in content.banks}
    old = {word for inventory in previous for puzzle in inventory.puzzles for word in puzzle.words}
    usage: dict[str, int] = {}
    for definition in content.puzzles:
        entries = {e.id: e for e in banks[definition.bank].entries}
        for target in definition.target_ids:
            word = normalize_word(entries[target].display)
            usage[word] = usage.get(word, 0) + 1
    result: dict[str, tuple[str, ...]] = {}
    for definition in content.puzzles:
        used = set(definition.target_ids)
        pool = [
            (usage.get(normalize_word(e.display), 0), index, e.display)
            for index, e in enumerate(banks[definition.bank].entries)
            if e.id not in used and normalize_word(e.display) not in old
        ]
        result[definition.id] = tuple(display for _, _, display in sorted(pool)[:limit])
    return result
