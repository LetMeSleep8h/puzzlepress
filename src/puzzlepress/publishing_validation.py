"""Schema-v1 optional publishing section. Collects independent issues; never repairs.

Schema validation decides only whether values are interpretable. KDP limits
(seven keywords, 4,000-character descriptions, three categories, ISBN check
digits) are publishing findings with official provenance, so a draft that
exceeds them still saves and is reported precisely (puzzlepress.publishing).
"""

from typing import TypeVar

from .content_validation import _Reader
from .errors import ValidationIssue
from .publishing_config import (
    CONFIRMATIONS,
    LEGACY_PUBLISHING_VERSION,
    MAX_CATEGORIES,
    MAX_CATEGORY,
    MAX_CONTRIBUTORS,
    MAX_DESCRIPTION,
    MAX_EDITION,
    MAX_KEYWORD,
    MAX_KEYWORDS,
    MAX_NAME,
    MAX_NOTES,
    MAX_READING_AGE,
    MAX_SERIES_NUMBER,
    PUBLISHING_VERSION,
    REVIEW_IDENTITY,
    AiDisclosure,
    Attestations,
    Audience,
    ContentOrigin,
    ContentRights,
    Contributor,
    ContributorRole,
    Isbn,
    IsbnMode,
    PublishingConfig,
    ReadingAge,
    RightsBasis,
    Series,
)

FIELDS = {
    "version",
    "description",
    "keywords",
    "categories",
    "contributors",
    "audience",
    "low_content",
    "isbn",
    "edition",
    "series",
    "ai_disclosure",
    "attestations",
    "notes",
    "content_rights",
}
Choice = TypeVar("Choice", IsbnMode, ContentOrigin, ContributorRole, RightsBasis)


def validate_publishing(
    value: object, has_composition: bool, coloring: bool = False
) -> tuple[PublishingConfig | None, tuple[ValidationIssue, ...]]:
    """Validate the publishing section; `has_composition` states whether one is declared.

    `coloring` admits the coloring-only declarations (`content_rights` and the
    artwork origins in `ai_disclosure`); other books report them as not applicable.
    """
    reader = _Reader()
    path = "publishing"
    data = reader.mapping(value, path, FIELDS)
    if not isinstance(value, dict):
        return None, tuple(reader.issues)
    if not has_composition:
        reader.issue(
            path,
            "requires_composition",
            "Publishing metadata requires a book composition: a package needs a built interior.",
        )
    version = data.get("version")
    if type(version) is not int or version not in (LEGACY_PUBLISHING_VERSION, PUBLISHING_VERSION):
        reader.issue(
            f"{path}.version",
            "unsupported_version",
            f"Publishing version {version!r} is not supported. Supported versions: "
            f"{PUBLISHING_VERSION}, and {LEGACY_PUBLISHING_VERSION} (yes/no confirmations, "
            "read as unconfirmed).",
        )
        return None, tuple(reader.issues)
    description = _optional_text(
        reader, data.get("description"), f"{path}.description", MAX_DESCRIPTION, multiline=True
    )
    keywords = _texts(
        reader, data.get("keywords", []), f"{path}.keywords", MAX_KEYWORDS, MAX_KEYWORD
    )
    categories = _texts(
        reader, data.get("categories", []), f"{path}.categories", MAX_CATEGORIES, MAX_CATEGORY
    )
    contributors = _contributors(reader, data.get("contributors", []), f"{path}.contributors")
    audience = _audience(reader, data.get("audience", {}), f"{path}.audience")
    low_content = _flag(reader, data.get("low_content"), f"{path}.low_content")
    isbn = _isbn(reader, data.get("isbn", {}), f"{path}.isbn")
    edition = _optional_int(reader, data.get("edition"), f"{path}.edition", 1, MAX_EDITION)
    series = _series(reader, data.get("series"), f"{path}.series")
    disclosure = _disclosure(
        reader, data.get("ai_disclosure", {}), f"{path}.ai_disclosure", coloring
    )
    content_rights = None
    if "content_rights" in data:
        if coloring:
            content_rights = _content_rights(
                reader, data["content_rights"], f"{path}.content_rights"
            )
        else:
            reader.issue(
                f"{path}.content_rights",
                "not_applicable_for_engine",
                "Artwork rights declarations apply to coloring books. Word-search books "
                "declare their rights with the rights confirmation.",
            )
    attestations = _attestations(
        reader, data.get("attestations", {}), f"{path}.attestations", version
    )
    notes = _optional_text(reader, data.get("notes"), f"{path}.notes", MAX_NOTES, multiline=True)
    if reader.issues:
        return None, tuple(reader.issues)
    return (
        PublishingConfig(
            description=description,
            keywords=keywords,
            categories=categories,
            contributors=contributors,
            audience=audience,
            low_content=low_content,
            isbn=isbn,
            edition=edition,
            series=series,
            ai_disclosure=disclosure,
            attestations=attestations,
            notes=notes,
            version=version,
            content_rights=content_rights,
        ),
        (),
    )


def _clean(value: str, multiline: bool) -> bool:
    """Valid Unicode scalars; no control characters except line breaks in long text."""
    return not any(
        0xD800 <= ord(c) <= 0xDFFF
        or ((ord(c) < 32 and not (multiline and c == "\n")) or 0x7F <= ord(c) <= 0x9F)
        for c in value
    )


def _text(
    reader: _Reader, value: object, path: str, limit: int, multiline: bool = False
) -> str | None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or not _clean(value, multiline)
    ):
        breaks = "; line breaks are allowed" if multiline else " on one line"
        reader.issue(
            path, "text", f"Expected 1..{limit:,} characters of nonempty plain text{breaks}."
        )
        return None
    return value.strip()


def _optional_text(
    reader: _Reader, value: object, path: str, limit: int, multiline: bool = False
) -> str | None:
    return None if value is None else _text(reader, value, path, limit, multiline)


def _texts(reader: _Reader, value: object, path: str, count: int, limit: int) -> tuple[str, ...]:
    items = reader.sequence(value, path, count, 0)
    return tuple(
        text
        for i, item in enumerate(items)
        if (text := _text(reader, item, f"{path}.{i}", limit)) is not None
    )


def _choice(
    reader: _Reader, value: object, path: str, enum: type[Choice], default: Choice
) -> Choice:
    names = [member.value for member in enum]
    if not isinstance(value, str) or value not in names:
        reader.issue(path, "choice", f"Use one of: {', '.join(names)}.")
        return default
    return enum(value)


def _flag(reader: _Reader, value: object, path: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        reader.issue(path, "type", "Expected true, false or null (not yet decided).")
        return None
    return value


def _optional_int(reader: _Reader, value: object, path: str, low: int, high: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not low <= value <= high:
        reader.issue(path, "number", f"Expected a whole number from {low} to {high}, or null.")
        return None
    return value


def _contributors(reader: _Reader, value: object, path: str) -> tuple[Contributor, ...]:
    contributors: list[Contributor] = []
    for i, entry in enumerate(reader.sequence(value, path, MAX_CONTRIBUTORS, 0)):
        item = reader.mapping(entry, f"{path}.{i}", {"role", "name"})
        if not isinstance(entry, dict):
            continue
        role = _choice(
            reader, item.get("role"), f"{path}.{i}.role", ContributorRole, ContributorRole.AUTHOR
        )
        name = _text(reader, item.get("name"), f"{path}.{i}.name", MAX_NAME)
        if name is not None:
            contributors.append(Contributor(role, name))
    return tuple(contributors)


def _audience(reader: _Reader, value: object, path: str) -> Audience:
    data = reader.mapping(value, path, {"sexually_explicit", "reading_age"})
    age = reader.mapping(data.get("reading_age", {}), f"{path}.reading_age", {"minimum", "maximum"})
    minimum = _optional_int(
        reader, age.get("minimum"), f"{path}.reading_age.minimum", 0, MAX_READING_AGE
    )
    maximum = _optional_int(
        reader, age.get("maximum"), f"{path}.reading_age.maximum", 0, MAX_READING_AGE
    )
    if minimum is not None and maximum is not None and minimum > maximum:
        reader.issue(f"{path}.reading_age", "range", "The minimum reading age exceeds the maximum.")
    return Audience(
        _flag(reader, data.get("sexually_explicit"), f"{path}.sexually_explicit"),
        ReadingAge(minimum, maximum),
    )


def _isbn(reader: _Reader, value: object, path: str) -> Isbn:
    data = reader.mapping(value, path, {"mode", "value"})
    mode = _choice(
        reader, data.get("mode", "undecided"), f"{path}.mode", IsbnMode, IsbnMode.UNDECIDED
    )
    raw = data.get("value")
    entered = None if raw is None else _text(reader, raw, f"{path}.value", 32)
    if entered is not None and mode is not IsbnMode.OWN:
        reader.issue(
            f"{path}.value",
            "isbn_value_unexpected",
            "Enter an ISBN only for your own ISBN. KDP assigns free ISBNs itself.",
        )
    return Isbn(mode, entered)


def _series(reader: _Reader, value: object, path: str) -> Series | None:
    if value is None:
        return None
    data = reader.mapping(value, path, {"title", "number"})
    if not isinstance(value, dict):
        return None
    title = _text(reader, data.get("title"), f"{path}.title", MAX_NAME)
    number = _optional_int(reader, data.get("number"), f"{path}.number", 1, MAX_SERIES_NUMBER)
    return Series(title, number) if title is not None else None


ARTWORK_ORIGINS = ("interior_artwork", "cover_artwork")


def _disclosure(reader: _Reader, value: object, path: str, coloring: bool) -> AiDisclosure:
    data = reader.mapping(value, path, {"text", "images", "translations", *ARTWORK_ORIGINS})
    unknown = ContentOrigin.UNKNOWN
    text = _choice(reader, data.get("text", "unknown"), f"{path}.text", ContentOrigin, unknown)
    images = _choice(
        reader, data.get("images", "unknown"), f"{path}.images", ContentOrigin, unknown
    )
    translations = _choice(
        reader, data.get("translations", "unknown"), f"{path}.translations", ContentOrigin, unknown
    )
    for kind, origin in (("text", text), ("images", images)):
        if origin is ContentOrigin.NONE:
            reader.issue(
                f"{path}.{kind}",
                "choice",
                "'none' applies to translations only; declare who created this content.",
            )
    artwork: dict[str, ContentOrigin | None] = {}
    for kind in ARTWORK_ORIGINS:
        if kind not in data:
            artwork[kind] = None
        elif not coloring:
            reader.issue(
                f"{path}.{kind}",
                "not_applicable_for_engine",
                "Artwork origins apply to coloring books; declare images with 'images'.",
            )
            artwork[kind] = None
        else:
            origin = _choice(reader, data[kind], f"{path}.{kind}", ContentOrigin, unknown)
            if origin is ContentOrigin.NONE and kind == "interior_artwork":
                reader.issue(
                    f"{path}.{kind}",
                    "choice",
                    "'none' applies to cover artwork only; declare who created the drawings.",
                )
            artwork[kind] = origin
    return AiDisclosure(
        text, images, translations, artwork["interior_artwork"], artwork["cover_artwork"]
    )


def _content_rights(reader: _Reader, value: object, path: str) -> ContentRights:
    fields = ("interior_artwork", "cover_artwork", "text")
    data = reader.mapping(value, path, {*fields, "notes"})
    undecided = RightsBasis.UNDECIDED
    values: dict[str, RightsBasis] = {}
    for kind in fields:
        basis = _choice(
            reader, data.get(kind, "undecided"), f"{path}.{kind}", RightsBasis, undecided
        )
        if basis is RightsBasis.NONE and kind != "cover_artwork":
            reader.issue(
                f"{path}.{kind}",
                "choice",
                "'none' applies to cover artwork only (a cover without images).",
            )
        values[kind] = basis
    notes = _optional_text(reader, data.get("notes"), f"{path}.notes", MAX_NOTES, multiline=True)
    return ContentRights(values["interior_artwork"], values["cover_artwork"], values["text"], notes)


def _attestations(reader: _Reader, value: object, path: str, version: int) -> Attestations:
    data = reader.mapping(value, path, set(CONFIRMATIONS))
    if version == LEGACY_PUBLISHING_VERSION:
        # Version 1 answers are kept for round-trips; they never count as confirmed.
        legacy: set[str] = set()
        for name in CONFIRMATIONS:
            raw = data.get(name, False)
            if not isinstance(raw, bool):
                reader.issue(f"{path}.{name}", "type", "Expected true or false (version 1).")
            elif raw:
                legacy.add(name)
        return Attestations(legacy=frozenset(legacy))
    values: dict[str, str | None] = {}
    for name in CONFIRMATIONS:
        raw = data.get(name)
        if isinstance(raw, bool):
            reader.issue(
                f"{path}.{name}",
                "confirmation_identity",
                "A confirmation records what you reviewed, not yes or no: confirm in "
                "Studio, or set the review identity `puzzlepress publish validate` prints, "
                "or null.",
            )
        elif raw is not None and (not isinstance(raw, str) or not REVIEW_IDENTITY.fullmatch(raw)):
            reader.issue(
                f"{path}.{name}",
                "confirmation_identity",
                "Expected null or a review identity (pp1-review-sha256-...).",
            )
        else:
            values[name] = raw
    return Attestations(
        rights=values.get("rights"),
        ai_disclosure=values.get("ai_disclosure"),
        metadata=values.get("metadata"),
        isbn=values.get("isbn"),
    )
