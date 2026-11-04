"""Publishing rule catalogue and the one home of KDP metadata values.

Official sources were read on 2026-10-08 (KDP_RULES_CHECKED); search snippets
were used only to locate pages. Each rule states its basis: a KDP requirement,
a KDP recommendation, an ambiguous KDP statement (the stricter reading
applies), a PuzzlePress rule, or a decision only a person can make. To update:
re-read the pages below, change values only here, bump RULESET_VERSION when a
verdict can change, and add boundary tests (docs/publishing.md).
"""

from dataclasses import dataclass

from .model import Basis, Rule, Scope, Severity, Source

RULESET_ID = "puzzlepress-kdp-publishing"
# 2: confirmations bind to the reviewed content (publishing.review); the assumed
# 50-character keyword warning (`keywords_length`, no KDP source) is removed.
# 3: the cover's displayed text (cover version 2 layers) must match the book
# details (`cover_text_matches`); a hidden title or author is a warning.
RULESET_VERSION = 3
KDP_RULES_CHECKED = "2026-10-08"


def _kdp(title: str, topic: str) -> Source:
    return Source(f"KDP help: {title}", f"https://kdp.amazon.com/en_US/help/topic/{topic}")


METADATA = _kdp("Metadata Guidelines for Books", "G201097560")
TITLES = _kdp("Books Titles & Editions", "GW7J4WEKBVU25YEC")
DESCRIPTION = _kdp("Write a Book Description", "G201189630")
KEYWORDS = _kdp("Make Your Book More Discoverable with Keywords", "G201298500")
CATEGORIES = _kdp("KDP Categories", "G200652170")
LANGUAGES = _kdp("Book Supported Languages", "G200673300")
AUDIENCE = _kdp("Primary Audience and Reading Age", "G201506310")
ISBN = _kdp("What is an ISBN and Imprint?", "G201834170")
LOW_CONTENT = _kdp("Low-Content Books", "GGE5T76TWKA85DJM")
CONTENT = _kdp("Content Guidelines", "G200672390")
FORMATTING = _kdp("Fix Paperback and Hardcover Formatting Issues", "G201834260")
CREATE = _kdp("Create a Book", "G202172740")
CONTRACT = Source("PuzzlePress publishing contract", "docs/publishing.md")
INTERIOR_PREFLIGHT = Source("PuzzlePress interior preflight", "docs/preflight.md")
COVER_PREFLIGHT = Source("PuzzlePress cover preflight", "docs/cover.md#cover-preflight")


@dataclass(frozen=True)
class KdpMetadataConstraints:
    """KDP paperback metadata values, checked 2026-10-08. Provenance: docs/publishing.md."""

    # "Your title and subtitle together must be fewer than 200 characters" (Metadata
    # Guidelines) and "200 characters or less" (Titles & Editions): stricter applies.
    max_title_and_subtitle: int = 199
    max_description: int = 4000  # Write a Book Description.
    max_keywords: int = 7  # "Use up to seven keywords or short phrases."
    # The keywords page names no per-keyword length (it only mentions the text
    # field's limit), so none is modeled; KDP's form enforces its own.
    max_categories: int = 3  # "you can select 3 categories".
    max_imprint: int = 100  # "The Imprint field has a limit of 100 characters."
    # Reading age bands named by KDP; 18 in the schema stands for "18 and over".
    reading_age_bands: tuple[tuple[int, int], ...] = ((0, 2), (3, 5), (6, 8), (9, 12), (13, 17))


KDP_METADATA = KdpMetadataConstraints()

# KDP's Book Supported Languages page (2026-10-08): languages that support
# paperbacks, keyed by the BCP 47 primary subtag PuzzlePress maps each name to.
# eBook-only languages (Arabic, Chinese (Traditional), Gujarati, Hindi,
# Malayalam, Marathi, Persian, Tamil) are deliberately absent.
PAPERBACK_LANGUAGES: dict[str, str] = {
    "af": "Afrikaans",
    "gsw": "Alsatian",
    "eu": "Basque",
    "nb": "Bokmål Norwegian",
    "br": "Breton",
    "ca": "Catalan",
    "kw": "Cornish",
    "co": "Corsican",
    "da": "Danish",
    "nl": "Dutch/Flemish",
    "stq": "Eastern Frisian",
    "en": "English",
    "fi": "Finnish",
    "fr": "French",
    "fy": "Frisian",
    "gl": "Galician",
    "de": "German",
    "he": "Hebrew",
    "is": "Icelandic",
    "ga": "Irish",
    "it": "Italian",
    "ja": "Japanese",
    "la": "Latin",
    "lb": "Luxembourgish",
    "gv": "Manx",
    "frr": "Northern Frisian",
    "no": "Norwegian",
    "nn": "Nynorsk Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "oc": "Provençal",
    "rm": "Romansh",
    "sco": "Scots",
    "gd": "Scottish Gaelic",
    "es": "Spanish",
    "sv": "Swedish",
    "uk": "Ukrainian",
    "cy": "Welsh",
    "yi": "Yiddish",
}

_RULES: tuple[Rule, ...] = (
    # ------------------------------------------------------------ metadata
    Rule(
        "publishing_configured",
        Scope.METADATA,
        Severity.ERROR,
        "Publishing metadata authored",
        Basis.PUZZLEPRESS_RULE,
        CONTRACT,
    ),
    Rule(
        "title_length",
        Scope.METADATA,
        Severity.ERROR,
        "Title and subtitle length",
        Basis.KDP_AMBIGUOUS,
        METADATA,
    ),
    Rule(
        "title_content",
        Scope.METADATA,
        Severity.ERROR,
        "Title, subtitle and series title content",
        Basis.KDP_REQUIREMENT,
        METADATA,
    ),
    Rule(
        "title_review",
        Scope.METADATA,
        Severity.WARNING,
        "Title wording to review",
        Basis.KDP_REQUIREMENT,
        METADATA,
    ),
    Rule(
        "author_present",
        Scope.METADATA,
        Severity.ERROR,
        "Primary author",
        Basis.KDP_REQUIREMENT,
        METADATA,
    ),
    Rule(
        "names_content",
        Scope.METADATA,
        Severity.ERROR,
        "Author, contributor and imprint names",
        Basis.KDP_REQUIREMENT,
        METADATA,
    ),
    Rule(
        "contributors_review",
        Scope.METADATA,
        Severity.WARNING,
        "Contributors to review",
        Basis.KDP_REQUIREMENT,
        METADATA,
    ),
    Rule(
        "imprint_length",
        Scope.METADATA,
        Severity.ERROR,
        "Imprint length",
        Basis.KDP_REQUIREMENT,
        ISBN,
    ),
    Rule(
        "language_supported",
        Scope.METADATA,
        Severity.ERROR,
        "Paperback language",
        Basis.KDP_REQUIREMENT,
        LANGUAGES,
    ),
    Rule(
        "description_present",
        Scope.METADATA,
        Severity.ERROR,
        "Description written",
        Basis.PUZZLEPRESS_RULE,
        CONTRACT,
    ),
    Rule(
        "description_length",
        Scope.METADATA,
        Severity.ERROR,
        "Description length",
        Basis.KDP_REQUIREMENT,
        DESCRIPTION,
    ),
    Rule(
        "description_markup",
        Scope.METADATA,
        Severity.ERROR,
        "Description is plain text",
        Basis.PUZZLEPRESS_RULE,
        CONTRACT,
    ),
    Rule(
        "description_prohibited",
        Scope.METADATA,
        Severity.ERROR,
        "Description excludes prohibited content",
        Basis.KDP_REQUIREMENT,
        DESCRIPTION,
    ),
    Rule(
        "description_review",
        Scope.METADATA,
        Severity.WARNING,
        "Description wording to review",
        Basis.KDP_REQUIREMENT,
        DESCRIPTION,
    ),
    Rule(
        "keywords_count",
        Scope.METADATA,
        Severity.ERROR,
        "Number of keywords",
        Basis.KDP_REQUIREMENT,
        KEYWORDS,
    ),
    Rule(
        "keywords_format",
        Scope.METADATA,
        Severity.ERROR,
        "Keyword format",
        Basis.KDP_REQUIREMENT,
        KEYWORDS,
    ),
    Rule(
        "keywords_review",
        Scope.METADATA,
        Severity.WARNING,
        "Keywords to review",
        Basis.KDP_RECOMMENDATION,
        KEYWORDS,
    ),
    Rule(
        "keywords_present",
        Scope.METADATA,
        Severity.INFO,
        "Keywords entered",
        Basis.KDP_RECOMMENDATION,
        KEYWORDS,
    ),
    Rule(
        "categories_count",
        Scope.METADATA,
        Severity.ERROR,
        "Number of categories",
        Basis.KDP_REQUIREMENT,
        CATEGORIES,
    ),
    Rule(
        "categories_format",
        Scope.METADATA,
        Severity.ERROR,
        "Category format",
        Basis.PUZZLEPRESS_RULE,
        CONTRACT,
    ),
    Rule(
        "categories_present",
        Scope.METADATA,
        Severity.WARNING,
        "Categories chosen",
        Basis.PUZZLEPRESS_RULE,
        CATEGORIES,
    ),
    Rule(
        "categories_unverified",
        Scope.METADATA,
        Severity.INFO,
        "Category availability",
        Basis.HUMAN_REVIEW,
        CATEGORIES,
    ),
    Rule(
        "audience_explicit",
        Scope.METADATA,
        Severity.ERROR,
        "Sexually explicit images or title answered",
        Basis.KDP_REQUIREMENT,
        AUDIENCE,
    ),
    Rule(
        "audience_reading_age",
        Scope.METADATA,
        Severity.ERROR,
        "Reading age consistent",
        Basis.PUZZLEPRESS_RULE,
        AUDIENCE,
    ),
    Rule(
        "low_content_decided",
        Scope.METADATA,
        Severity.ERROR,
        "Low-content classification",
        Basis.KDP_REQUIREMENT,
        LOW_CONTENT,
    ),
    Rule(
        "low_content_review",
        Scope.METADATA,
        Severity.WARNING,
        "Low-content classification to review",
        Basis.KDP_RECOMMENDATION,
        LOW_CONTENT,
    ),
    Rule(
        "isbn_decided",
        Scope.METADATA,
        Severity.ERROR,
        "ISBN choice",
        Basis.KDP_REQUIREMENT,
        ISBN,
    ),
    Rule(
        "isbn_valid",
        Scope.METADATA,
        Severity.ERROR,
        "ISBN format and check digit",
        Basis.KDP_REQUIREMENT,
        ISBN,
    ),
    Rule(
        "isbn_eligibility",
        Scope.METADATA,
        Severity.ERROR,
        "ISBN option allowed",
        Basis.KDP_REQUIREMENT,
        LOW_CONTENT,
    ),
    Rule(
        "isbn_imprint",
        Scope.METADATA,
        Severity.WARNING,
        "Imprint with this ISBN",
        Basis.KDP_REQUIREMENT,
        ISBN,
    ),
    Rule(
        "series_eligibility",
        Scope.METADATA,
        Severity.ERROR,
        "Series allowed",
        Basis.KDP_REQUIREMENT,
        LOW_CONTENT,
    ),
    # ------------------------------------------------------------ disclosure
    Rule(
        "ai_disclosure_complete",
        Scope.DISCLOSURE,
        Severity.ERROR,
        "AI content declared",
        Basis.KDP_REQUIREMENT,
        CONTENT,
    ),
    Rule(
        "ai_disclosure_required",
        Scope.DISCLOSURE,
        Severity.INFO,
        "AI-generated content to disclose",
        Basis.KDP_REQUIREMENT,
        CONTENT,
    ),
    # ------------------------------------------------------------ attestation
    Rule(
        "attestations",
        Scope.ATTESTATION,
        Severity.ERROR,
        "Author confirmations",
        Basis.HUMAN_REVIEW,
        CONTRACT,
    ),
    # ------------------------------------------------------------ consistency
    Rule(
        "cover_text_matches",
        Scope.CONSISTENCY,
        Severity.ERROR,
        "Cover text matches book details",
        Basis.KDP_REQUIREMENT,
        FORMATTING,
    ),
    Rule(
        "cover_text_omitted",
        Scope.CONSISTENCY,
        Severity.WARNING,
        "Cover shows the title and author",
        Basis.KDP_AMBIGUOUS,
        FORMATTING,
    ),
    Rule(
        "cover_matches_interior",
        Scope.CONSISTENCY,
        Severity.ERROR,
        "Cover built for this interior",
        Basis.PUZZLEPRESS_RULE,
        COVER_PREFLIGHT,
    ),
    Rule(
        "description_claims",
        Scope.CONSISTENCY,
        Severity.ERROR,
        "Description counts match the book",
        Basis.PUZZLEPRESS_RULE,
        CONTENT,
    ),
    # ------------------------------------------------------------ artifacts
    Rule(
        "output_directory",
        Scope.ARTIFACTS,
        Severity.ERROR,
        "Build directory available",
        Basis.PUZZLEPRESS_RULE,
        CONTRACT,
    ),
    Rule(
        "saved_reports",
        Scope.ARTIFACTS,
        Severity.WARNING,
        "Saved preflight reports",
        Basis.PUZZLEPRESS_RULE,
        CONTRACT,
    ),
    # ------------------------------------------------------------ interior and cover
    Rule(
        "interior_present",
        Scope.INTERIOR,
        Severity.ERROR,
        "Interior built",
        Basis.PUZZLEPRESS_RULE,
        INTERIOR_PREFLIGHT,
    ),
    Rule(
        "interior_structural",
        Scope.INTERIOR,
        Severity.ERROR,
        "Interior structurally valid",
        Basis.PUZZLEPRESS_RULE,
        INTERIOR_PREFLIGHT,
    ),
    Rule(
        "interior_kdp",
        Scope.INTERIOR,
        Severity.ERROR,
        "Interior KDP ready",
        Basis.KDP_REQUIREMENT,
        INTERIOR_PREFLIGHT,
    ),
    Rule(
        "interior_warnings",
        Scope.INTERIOR,
        Severity.WARNING,
        "Interior preflight warnings",
        Basis.KDP_AMBIGUOUS,
        INTERIOR_PREFLIGHT,
    ),
    Rule(
        "cover_present",
        Scope.COVER,
        Severity.ERROR,
        "Cover configured and built",
        Basis.PUZZLEPRESS_RULE,
        COVER_PREFLIGHT,
    ),
    Rule(
        "cover_structural",
        Scope.COVER,
        Severity.ERROR,
        "Cover structurally valid",
        Basis.PUZZLEPRESS_RULE,
        COVER_PREFLIGHT,
    ),
    Rule(
        "cover_kdp",
        Scope.COVER,
        Severity.ERROR,
        "Cover KDP ready",
        Basis.KDP_REQUIREMENT,
        COVER_PREFLIGHT,
    ),
    Rule(
        "cover_warnings",
        Scope.COVER,
        Severity.WARNING,
        "Cover preflight warnings",
        Basis.KDP_AMBIGUOUS,
        COVER_PREFLIGHT,
    ),
)

RULES: dict[str, Rule] = {rule.code: rule for rule in _RULES}
CODES: tuple[str, ...] = tuple(rule.code for rule in _RULES)
# Rules that need only the authored project (no built artifacts).
METADATA_CODES: tuple[str, ...] = tuple(
    rule.code
    for rule in _RULES
    if rule.scope in (Scope.METADATA, Scope.DISCLOSURE, Scope.ATTESTATION)
    or rule.code == "description_claims"
)


# ---------------------------------------------------------------- coloring books

# A separate ruleset, so word-search reports and packages keep their bytes. Shared
# rules keep their codes and wording; coloring adds artwork origin and rights
# declarations. KDP's Content Guidelines (G200672390) and Low-Content Books
# (GGE5T76TWKA85DJM) pages were re-read for these on 2026-11-04 (COLORING_CHECKED).
COLORING_RULESET_ID = "puzzlepress-kdp-publishing-coloring"
COLORING_RULESET_VERSION = 1
COLORING_CHECKED = "2026-11-04"

_COLORING_ADDITIONS: tuple[Rule, ...] = (
    Rule(
        "artwork_origin_declared",
        Scope.DISCLOSURE,
        Severity.ERROR,
        "Interior and cover artwork origin declared",
        Basis.KDP_REQUIREMENT,
        CONTENT,
    ),
    Rule(
        "artwork_origin_consistent",
        Scope.DISCLOSURE,
        Severity.ERROR,
        "KDP's images answer agrees with the artwork origins",
        Basis.KDP_REQUIREMENT,
        CONTENT,
    ),
    Rule(
        "content_rights_declared",
        Scope.DISCLOSURE,
        Severity.ERROR,
        "Rights basis declared for interior artwork, cover artwork and text",
        Basis.PUZZLEPRESS_RULE,
        CONTENT,
    ),
    Rule(
        "content_rights_review",
        Scope.DISCLOSURE,
        Severity.WARNING,
        "Rights declarations that need evidence or a closer look",
        Basis.HUMAN_REVIEW,
        CONTENT,
    ),
)


def _with_additions(
    rules: tuple[Rule, ...], after: str, added: tuple[Rule, ...]
) -> tuple[Rule, ...]:
    index = next(i for i, rule in enumerate(rules) if rule.code == after) + 1
    return rules[:index] + added + rules[index:]


_COLORING_RULES = _with_additions(_RULES, "ai_disclosure_required", _COLORING_ADDITIONS)


@dataclass(frozen=True)
class PublishingRuleset:
    """One engine's publishing rule catalogue, in report order."""

    id: str
    version: int
    checked: str  # When the official pages behind it were last read.
    rules: dict[str, Rule]
    codes: tuple[str, ...]
    metadata_codes: tuple[str, ...]


def _ruleset(id: str, version: int, checked: str, rules: tuple[Rule, ...]) -> PublishingRuleset:
    return PublishingRuleset(
        id,
        version,
        checked,
        {rule.code: rule for rule in rules},
        tuple(rule.code for rule in rules),
        tuple(
            rule.code
            for rule in rules
            if rule.scope in (Scope.METADATA, Scope.DISCLOSURE, Scope.ATTESTATION)
            or rule.code == "description_claims"
        ),
    )


WORD_SEARCH_RULESET = _ruleset(RULESET_ID, RULESET_VERSION, KDP_RULES_CHECKED, _RULES)
COLORING_RULESET = _ruleset(
    COLORING_RULESET_ID, COLORING_RULESET_VERSION, COLORING_CHECKED, _COLORING_RULES
)


def ruleset_for(coloring: bool) -> PublishingRuleset:
    """The publishing ruleset for a coloring book, or the word-search one."""
    return COLORING_RULESET if coloring else WORD_SEARCH_RULESET
