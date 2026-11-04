"""Authored KDP paperback publishing metadata: an optional, versioned section.

Title, subtitle, author, imprint and language stay authoritative in `book`; this
section holds only what KDP asks for beyond them, plus the author's own
disclosure and review decisions. It is excluded from the project build identity
(editing keywords never stales an interior) and identified by the publishing
identity instead. Undecided values are explicit (`None`, `undecided`, `unknown`)
and never default to a claim on the author's behalf.
"""

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum

# Version 2 binds each confirmation to the content reviewed. Version 1 recorded
# yes/no answers; it is still read, but those answers never count as confirmed.
PUBLISHING_VERSION = 2
LEGACY_PUBLISHING_VERSION = 1
CONFIRMATIONS = ("rights", "ai_disclosure", "metadata", "isbn")
# A stored confirmation: the review identity of what the author confirmed.
REVIEW_IDENTITY = re.compile(r"pp1-review-sha256-[0-9a-f]{64}")

# Generous schema bounds keep a draft savable; KDP limits are reported by
# publishing validation with their official source (docs/publishing.md).
MAX_DESCRIPTION = 10_000
MAX_KEYWORDS = 20
MAX_KEYWORD = 200
MAX_CATEGORIES = 10
MAX_CATEGORY = 300
MAX_CONTRIBUTORS = 20
MAX_NAME = 200
MAX_NOTES = 2_000
MAX_EDITION = 999
MAX_SERIES_NUMBER = 9_999
MAX_READING_AGE = 18  # 18 stands for "18 and over".


class IsbnMode(StrEnum):
    UNDECIDED = "undecided"
    KDP_FREE = "kdp_free"  # KDP assigns a free ISBN during setup; usable only on KDP.
    OWN = "own"  # An ISBN the author registered with an ISBN agency.
    NONE = "none"  # Only low-content books may publish without an ISBN.


class ContentOrigin(StrEnum):
    """Who or what created a kind of content, as the author declares it."""

    UNKNOWN = "unknown"  # Not yet reviewed; blocks a package.
    HUMAN = "human"
    AI_ASSISTED = "ai_assisted"  # Author-created, AI used to edit or refine.
    AI_GENERATED = "ai_generated"  # Created by an AI-based tool, even if edited later.
    NONE = "none"  # Translations only: the book is not a translation.


class RightsBasis(StrEnum):
    """On what basis the author may publish a kind of content, as the author declares it.

    Coloring books only (`publishing.content_rights`). Possessing a file is never a
    basis: PuzzlePress records the declaration and cannot verify it.
    """

    UNDECIDED = "undecided"  # Not yet reviewed; blocks a package.
    OWN_WORK = "own_work"  # Created by the author or the book's listed contributors.
    COMMISSIONED = "commissioned"  # Made for the author under an agreement granting the rights.
    LICENSED = "licensed"  # Used under a license that permits this commercial print use.
    PUBLIC_DOMAIN = "public_domain"  # No longer under copyright; KDP may ask for proof.
    AI_TOOL_TERMS = "ai_tool_terms"  # Generated with an AI tool, used under the tool's terms.
    NONE = "none"  # Cover only: the cover has no artwork or photograph.


class ContributorRole(StrEnum):
    AUTHOR = "author"
    EDITOR = "editor"
    ILLUSTRATOR = "illustrator"
    PHOTOGRAPHER = "photographer"
    TRANSLATOR = "translator"
    FOREWORD = "foreword"
    INTRODUCTION = "introduction"
    PREFACE = "preface"


@dataclass(frozen=True)
class Contributor:
    role: ContributorRole
    name: str

    def to_dict(self) -> dict[str, object]:
        return {"role": self.role.value, "name": self.name}


@dataclass(frozen=True)
class Series:
    title: str
    number: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {"title": self.title, "number": self.number}


@dataclass(frozen=True)
class ReadingAge:
    minimum: int | None = None
    maximum: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {"minimum": self.minimum, "maximum": self.maximum}


@dataclass(frozen=True)
class Audience:
    # KDP requires a yes/no answer; None means the author has not answered.
    sexually_explicit: bool | None = None
    reading_age: ReadingAge = field(default_factory=ReadingAge)

    def to_dict(self) -> dict[str, object]:
        return {
            "sexually_explicit": self.sexually_explicit,
            "reading_age": self.reading_age.to_dict(),
        }


@dataclass(frozen=True)
class Isbn:
    mode: IsbnMode = IsbnMode.UNDECIDED
    value: str | None = None  # Exactly as entered; only with mode `own`.

    def to_dict(self) -> dict[str, object]:
        return {"mode": self.mode.value, "value": self.value}


@dataclass(frozen=True)
class AiDisclosure:
    text: ContentOrigin = ContentOrigin.UNKNOWN
    images: ContentOrigin = ContentOrigin.UNKNOWN
    translations: ContentOrigin = ContentOrigin.UNKNOWN
    # Coloring books: the artwork behind KDP's single images answer, which covers
    # interior and cover images alike. Written only when present (None elsewhere).
    interior_artwork: ContentOrigin | None = None
    cover_artwork: ContentOrigin | None = None  # `none`: the cover has no artwork.

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "text": self.text.value,
            "images": self.images.value,
            "translations": self.translations.value,
        }
        if self.interior_artwork is not None:
            data["interior_artwork"] = self.interior_artwork.value
        if self.cover_artwork is not None:
            data["cover_artwork"] = self.cover_artwork.value
        return data


@dataclass(frozen=True)
class ContentRights:
    """Coloring books: the author's declared basis for publishing each kind of content."""

    interior_artwork: RightsBasis = RightsBasis.UNDECIDED
    cover_artwork: RightsBasis = RightsBasis.UNDECIDED
    text: RightsBasis = RightsBasis.UNDECIDED  # Captions, dividers, matter, description.
    notes: str | None = None  # Licence names, sources, agreements: the author's record.

    def to_dict(self) -> dict[str, object]:
        return {
            "interior_artwork": self.interior_artwork.value,
            "cover_artwork": self.cover_artwork.value,
            "text": self.text.value,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Attestations:
    """The author's own confirmations. Never set by PuzzlePress; no timestamps.

    Each holds the review identity of the content the author confirmed, or None
    (puzzlepress.publishing.review decides whether it still applies). A version 1
    section stored booleans: `legacy` keeps the names saved as true so the file
    round-trips unchanged, and none of them counts as a confirmation.
    """

    rights: str | None = None  # Holds the rights to the content (wording per engine).
    ai_disclosure: str | None = None  # Reviewed the AI disclosure as declared.
    metadata: str | None = None  # The book details and KDP metadata represent the book.
    isbn: str | None = None  # Own ISBN registered with this title, author and imprint.
    legacy: frozenset[str] | None = None  # Version 1 only: names saved as true.

    def stored(self, name: str) -> str | None:
        value = getattr(self, name)
        assert value is None or isinstance(value, str)
        return value

    def to_dict(self) -> dict[str, object]:
        if self.legacy is not None:
            return {name: name in self.legacy for name in CONFIRMATIONS}
        return {name: self.stored(name) for name in CONFIRMATIONS}


@dataclass(frozen=True)
class PublishingConfig:
    description: str | None = None
    keywords: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    contributors: tuple[Contributor, ...] = ()
    audience: Audience = field(default_factory=Audience)
    low_content: bool | None = None
    isbn: Isbn = field(default_factory=Isbn)
    edition: int | None = None
    series: Series | None = None
    ai_disclosure: AiDisclosure = field(default_factory=AiDisclosure)
    attestations: Attestations = field(default_factory=Attestations)
    notes: str | None = None
    version: int = PUBLISHING_VERSION
    content_rights: ContentRights | None = None  # Coloring books only; written when present.

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "description": self.description,
            "keywords": list(self.keywords),
            "categories": list(self.categories),
            "contributors": [c.to_dict() for c in self.contributors],
            "audience": self.audience.to_dict(),
            "low_content": self.low_content,
            "isbn": self.isbn.to_dict(),
            "edition": self.edition,
            "series": self.series.to_dict() if self.series else None,
            "ai_disclosure": self.ai_disclosure.to_dict(),
            "attestations": self.attestations.to_dict(),
            "notes": self.notes,
            **(
                {"content_rights": self.content_rights.to_dict()}
                if self.content_rights is not None
                else {}
            ),
        }

    def upgraded(self) -> "PublishingConfig":
        """This section in the current version. Version 1 confirmations recorded no
        reviewed content, so every confirmation starts unconfirmed; nothing else changes."""
        if self.version == PUBLISHING_VERSION:
            return self
        return replace(self, version=PUBLISHING_VERSION, attestations=Attestations())
