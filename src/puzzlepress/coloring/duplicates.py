"""Duplicate artwork and pages in one coloring book: exact facts, then a heuristic.

Confirmed (exact) duplicates are facts: two artwork entries pinning the same
SHA-256, or one artwork placed on more than one page. Possible duplicates are a
heuristic: two different files whose reduced images are close by a 64-bit
difference hash and by a 16 x 16 gray map. A heuristic match is a prompt to look,
never proof, and nothing here removes or replaces artwork.

Ordering is stable: groups by first artwork ID, pairs by (first, second) ID, pages
ascending.
"""

from dataclasses import dataclass

from ..coloring_config import ColoringBook
from .inspection import Inspection

REPORT_VERSION = 1
# Conventions, measured on synthetic line art (tests/coloring_helpers.py): JPEG
# re-encodes, a half-size copy and doubled line weight of one drawing measured at
# most 4 bits and 4.97 levels; 1,770 pairs of 60 different drawings at least 12
# bits and 7.56 levels. Real scans may differ; a match is a prompt to look.
MAX_HASH_DISTANCE = 10  # Of 64 bits.
MAX_MAP_DIFFERENCE = 6.5  # Mean absolute difference of 0..255 gray levels.


def hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def map_difference(left: bytes, right: bytes) -> float:
    return sum(abs(a - b) for a, b in zip(left, right, strict=True)) / len(left)


@dataclass(frozen=True)
class SameFile:
    sha256: str
    artwork: tuple[str, ...]
    pages: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {"sha256": self.sha256, "artwork": list(self.artwork), "pages": list(self.pages)}


@dataclass(frozen=True)
class RepeatedPage:
    artwork: str
    pages: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {"artwork": self.artwork, "pages": list(self.pages)}


@dataclass(frozen=True)
class SimilarPair:
    artwork: tuple[str, str]
    hash_distance: int
    map_difference: float
    pages: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "artwork": list(self.artwork),
            "hash_distance": self.hash_distance,
            "map_difference": self.map_difference,
            "pages": list(self.pages),
        }


@dataclass(frozen=True)
class DuplicateReport:
    same_file: tuple[SameFile, ...]
    repeated_pages: tuple[RepeatedPage, ...]
    similar: tuple[SimilarPair, ...]
    not_compared: tuple[str, ...]  # Artwork that could not be read, so was not compared.

    @property
    def confirmed(self) -> int:
        return len(self.same_file) + len(self.repeated_pages)

    def to_dict(self) -> dict[str, object]:
        return {
            "report_version": REPORT_VERSION,
            "confirmed": {
                "same_file": [item.to_dict() for item in self.same_file],
                "repeated_pages": [item.to_dict() for item in self.repeated_pages],
            },
            "possible": {
                "method": (
                    f"difference hash within {MAX_HASH_DISTANCE} of 64 bits and 16 x 16 gray "
                    f"map within {MAX_MAP_DIFFERENCE:g} levels; a heuristic, not proof"
                ),
                "similar": [item.to_dict() for item in self.similar],
            },
            "not_compared": list(self.not_compared),
            "complete": not self.not_compared,
        }


def _pages_of(book: ColoringBook) -> dict[str, tuple[int, ...]]:
    found: dict[str, list[int]] = {}
    for number, artwork in book.artwork_pages:
        found.setdefault(artwork, []).append(number)
    return {key: tuple(value) for key, value in found.items()}


def find_duplicates(
    book: ColoringBook, inspections: dict[str, Inspection | None]
) -> DuplicateReport:
    """`inspections` maps every artwork ID to its inspection, or None if unreadable."""
    pages = _pages_of(book)
    by_digest: dict[str, list[str]] = {}
    for item in book.artwork:
        by_digest.setdefault(item.sha256, []).append(item.id)
    same = tuple(
        sorted(
            (
                SameFile(
                    digest,
                    tuple(sorted(ids)),
                    tuple(sorted(n for i in ids for n in pages.get(i, ()))),
                )
                for digest, ids in by_digest.items()
                if len(ids) > 1
            ),
            key=lambda group: group.artwork,
        )
    )
    repeated = tuple(
        RepeatedPage(artwork, numbers)
        for artwork, numbers in sorted(pages.items())
        if len(numbers) > 1
    )
    readable = sorted(
        (item.id, item.sha256, inspection)
        for item in book.artwork
        if (inspection := inspections.get(item.id)) is not None
    )
    similar: list[SimilarPair] = []
    for index, (left_id, left_sha, left) in enumerate(readable):
        for right_id, right_sha, right in readable[index + 1 :]:
            if left_sha == right_sha:
                continue  # Already a confirmed duplicate.
            distance = hamming(left.info.dhash, right.info.dhash)
            if distance > MAX_HASH_DISTANCE:
                continue
            difference = round(map_difference(left.ink_map, right.ink_map), 2)
            if difference > MAX_MAP_DIFFERENCE:
                continue
            numbers = tuple(sorted(pages.get(left_id, ()) + pages.get(right_id, ())))
            similar.append(SimilarPair((left_id, right_id), distance, difference, numbers))
    missing = tuple(sorted(item.id for item in book.artwork if inspections.get(item.id) is None))
    return DuplicateReport(same, repeated, tuple(similar), missing)
