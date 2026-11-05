"""What to enter in KDP: the metadata record and a human submission checklist.

Both are derived from the readiness report and the authored project only. The
checklist lists steps for a person to take in KDP; it never says a step was
done, and nothing here contacts Amazon. Output is deterministic text with no
paths or timestamps.
"""

import hashlib

from .. import __version__
from ..publishing_config import ContentOrigin, IsbnMode
from .metadata import kdp_ai_answers
from .readiness import PublishingReadinessReport
from .rules import KDP_METADATA, PAPERBACK_LANGUAGES

METADATA_VERSION = 1
ISBN_STATUS = {
    IsbnMode.UNDECIDED: "undecided",
    IsbnMode.KDP_FREE: "assigned_by_kdp_during_setup",
    IsbnMode.OWN: "author_supplied_registration_not_verified",
    IsbnMode.NONE: "no_isbn_low_content",
}
ORIGIN = {
    ContentOrigin.HUMAN: "created by people",
    ContentOrigin.AI_ASSISTED: "created by people, edited with AI tools (AI-assisted)",
    ContentOrigin.AI_GENERATED: "AI-generated",
    ContentOrigin.NONE: "not a translation",
    ContentOrigin.UNKNOWN: "not yet declared",
}


def kdp_metadata(report: PublishingReadinessReport) -> dict[str, object]:
    """The KDP field values, exactly as authored (never rewritten)."""
    project = report.project
    book = project.book
    config = project.publishing
    primary = book.language.split("-")[0].casefold()
    data: dict[str, object] = {
        "metadata_version": METADATA_VERSION,
        "format": "paperback",
        "book_id": book.id,
        "publishing_identity": report.metadata.publishing_identity,
        "language": {"tag": book.language, "kdp_name": PAPERBACK_LANGUAGES.get(primary)},
        "title": book.title,
        "subtitle": book.subtitle,
        "author": book.author,
        "print": report.print_configuration(),
        "files": {"interior": "interior.pdf", "cover": "cover.pdf"},
    }
    if config is None:
        return data
    data |= {
        "series": config.series.to_dict() if config.series else None,
        "edition": config.edition,
        "contributors": [c.to_dict() for c in config.contributors],
        "description": config.description,
        "description_format": "plain text",
        "audience": config.audience.to_dict(),
        "categories": [
            {"path": path, "status": "saved_preference_not_verified_in_kdp"}
            for path in config.categories
        ],
        "keywords": list(config.keywords),
        "low_content": config.low_content,
        "isbn": {
            "mode": config.isbn.mode.value,
            "value": config.isbn.value,
            "status": ISBN_STATUS[config.isbn.mode],
        },
        "imprint": {
            "authored": book.imprint,
            "kdp_listing": "Independently published"
            if config.isbn.mode is IsbnMode.KDP_FREE
            else book.imprint,
        },
        "ai_content": kdp_ai_answers(config.ai_disclosure),
        "notes": config.notes,
    }
    if project.coloring is not None:
        disclosure = config.ai_disclosure
        data["artwork_origin"] = {
            "interior_artwork": getattr(disclosure.interior_artwork, "value", None),
            "cover_artwork": getattr(disclosure.cover_artwork, "value", None),
            "kdp_images_answer_covers": "cover and interior images and artwork together",
        }
        data["content_rights"] = config.content_rights.to_dict() if config.content_rights else None
    return data


def _box(text: str) -> str:
    return f"- [ ] {text}"


def _quote(text: str) -> list[str]:
    return [f"    > {line}" if line else "    >" for line in text.splitlines()]


def checklist_markdown(report: PublishingReadinessReport) -> str:
    project = report.project
    book = project.book
    config = project.publishing
    printing = report.print_configuration() or {}
    interior = report.interior_bytes()
    cover = report.cover_bytes()
    lines: list[str] = [
        f"# KDP paperback checklist: {book.title}",
        "",
        f"Prepared by PuzzlePress {__version__} for manual submission in Amazon KDP. Nothing "
        "on this list has been done in KDP. PuzzlePress does not contact Amazon; KDP reviews "
        "the book and decides whether to publish it.",
        "",
        f"Readiness: {report.statement()}",
        "",
        f"Publishing identity: `{report.metadata.publishing_identity}`",
        "",
        "Work through KDP's three pages in order: Paperback Details, Paperback Content, and "
        "Paperback Rights & Pricing. Values come from `metadata.json`.",
        "",
        "## 1. Paperback details",
        "",
        _box("On your KDP Bookshelf, create a paperback (or open this title's paperback draft)."),
    ]
    primary = book.language.split("-")[0].casefold()
    lines += [
        _box(f"Language: {PAPERBACK_LANGUAGES.get(primary, book.language)}"),
        _box(f"Book title: {book.title}"),
        _box(f"Subtitle: {book.subtitle}" if book.subtitle else "Subtitle: leave empty"),
    ]
    if config is None:
        lines += ["", "Publishing metadata has not been authored yet.", ""]
    else:
        series = config.series
        lines += [
            _box(
                f"Series: {series.title}" + (f", number {series.number}" if series.number else "")
                if series
                else "Series: none"
            ),
            _box(
                f"Edition number: {config.edition}"
                if config.edition
                else "Edition number: leave empty"
            ),
            _box(f"Primary author: {book.author}" if book.author else "Primary author: MISSING"),
        ]
        if config.contributors:
            lines.append(_box("Contributors:"))
            lines += [f"    - {c.role.value.capitalize()}: {c.name}" for c in config.contributors]
        else:
            lines.append(_box("Contributors: none"))
        description = config.description or ""
        lines.append(
            _box(
                f"Description ({len(description):,} of {KDP_METADATA.max_description:,} "
                "characters, plain text): paste it, then check the paragraphs in KDP's editor."
            )
        )
        lines += _quote(description)
        lines += [
            _box(
                "Publishing rights: choose the option that applies to this book. PuzzlePress "
                "does not model public-domain content."
            ),
            _box(
                "Sexually explicit images or title: "
                + {True: "Yes", False: "No", None: "NOT ANSWERED"}[
                    config.audience.sexually_explicit
                ]
            ),
        ]
        age = config.audience.reading_age
        lines.append(
            _box(
                f"Reading age: {age.minimum} to "
                + ("18+" if age.maximum == 18 else str(age.maximum))
                if age.minimum is not None and age.maximum is not None
                else "Reading age: leave unset"
            )
        )
        lines.append(_box("Primary marketplace: choose in KDP (not modeled by PuzzlePress)."))
        if config.categories:
            lines.append(
                _box(
                    "Categories: select up to three in KDP's category selector. Your saved "
                    "preferences (not verified as currently available):"
                )
            )
            lines += [f"    - {path}" for path in config.categories]
        else:
            lines.append(_box("Categories: select up to three in KDP's category selector."))
        lines.append(
            _box(
                "Low-content book: "
                + {True: "check the Low-content box", False: "leave unchecked", None: "UNDECIDED"}[
                    config.low_content
                ]
            )
        )
        if config.keywords:
            lines.append(
                _box(
                    f"Keywords ({len(config.keywords)} of {KDP_METADATA.max_keywords}), "
                    "one per box:"
                )
            )
            lines += [f"    {i}. {k}" for i, k in enumerate(config.keywords, 1)]
        else:
            lines.append(_box("Keywords: none saved (optional)."))
        answers = kdp_ai_answers(config.ai_disclosure)
        lines.append(_box("AI-generated content: answer KDP's question from your declaration:"))
        for kind, origin in (
            ("Text", config.ai_disclosure.text),
            ("Images", config.ai_disclosure.images),
            ("Translations", config.ai_disclosure.translations),
        ):
            verdict = answers[kind.lower()]["kdp"]
            told = {
                "disclose": "disclose as AI-generated",
                "not_required": "no disclosure required",
                "not_applicable": "not applicable",
                "undecided": "DECIDE BEFORE SUBMITTING",
            }[verdict]
            lines.append(f"    - {kind}: {ORIGIN[origin]} ({told})")
        if project.coloring is not None:
            disclosure = config.ai_disclosure
            lines.append(
                "    - KDP's images answer covers both the interior drawings ("
                + _origin(disclosure.interior_artwork)
                + ") and the cover artwork ("
                + _origin(disclosure.cover_artwork)
                + ")."
            )
    lines += ["", "## 2. Paperback content", ""]
    if config is not None:
        mode = config.isbn.mode
        lines.append(
            _box(
                {
                    IsbnMode.KDP_FREE: "ISBN: get a free KDP ISBN. KDP assigns the number; it "
                    "can be used only on KDP and lists the imprint as Independently published.",
                    IsbnMode.OWN: f"ISBN: use my own ISBN {config.isbn.value} with imprint "
                    f"{book.imprint or 'MISSING'} exactly as registered with your ISBN agency.",
                    IsbnMode.NONE: "ISBN: publish without an ISBN (low-content books only).",
                    IsbnMode.UNDECIDED: "ISBN: UNDECIDED. Choose before submitting.",
                }[mode]
            )
        )
    if printing:
        trim = printing["trim_in"]
        assert isinstance(trim, list)
        lines += [
            _box(f"Ink and paper: {printing['ink']} ink on {printing['paper']} paper"),
            _box(f"Trim size: {trim[0]:g} x {trim[1]:g} in"),
            _box(
                "Bleed settings: Bleed (PDF only). The interior is 0.125 in wider and 0.25 in "
                "taller than the trim; KDP trims the top, bottom and outside edges"
                if printing.get("interior_bleed")
                else "Bleed settings: No bleed (the interior has none; the cover has its own)"
            ),
            _box("Paperback cover finish: choose matte or glossy (not modeled by PuzzlePress)"),
        ]
    if interior:
        lines.append(
            _box(
                f"Manuscript: upload `interior.pdf` ({printing.get('page_count')} pages, SHA-256 "
                f"{hashlib.sha256(interior[0]).hexdigest()})."
            )
        )
    if cover:
        size = printing.get("cover")
        shown = (
            f", {size['width_in']} x {size['height_in']} in with a "
            f"{size['spine_width_in']} in spine"
            if isinstance(size, dict)
            else ""
        )
        lines.append(
            _box(
                "Book cover: choose to upload a print-ready PDF cover and upload `cover.pdf`"
                f"{shown} (SHA-256 {hashlib.sha256(cover[0]).hexdigest()})."
            )
        )
    lines += [
        _box(
            "Launch KDP's Print Previewer. Check every page, the spine, margins and the "
            "barcode area."
        ),
        _box("Review every issue the Previewer reports. PuzzlePress checks do not replace KDP's."),
        _box("Approve the preview only after reviewing it yourself."),
        "",
        "## 3. Rights and pricing",
        "",
        _box("Territories, pricing and royalty: decide in KDP (not modeled by PuzzlePress)."),
        _box(
            "Order a printed proof (optional in KDP) to check color, trim and binding before "
            "publishing; the cover is RGB and KDP prints CMYK."
        ),
        _box("Submit for publishing yourself when satisfied. KDP then reviews the book."),
        "",
        "## Warnings to review",
        "",
    ]
    reviews = [f for f in report.findings if f.severity.value in ("warning", "info")]
    blocking = [f for f in report.findings if f.severity.value == "error"]
    if blocking:
        lines += [f"- BLOCKING [{f.rule.code}] {f.message}" for f in blocking]
    lines += [f"- [{f.rule.code}] {f.message}" for f in reviews] or ["- None."]
    if config is not None:
        labels = {"confirmed": "Confirmed", "unconfirmed": "NOT CONFIRMED"}
        lines += ["", "## Your confirmations recorded in book.yaml", ""]
        lines += [
            f"- {labels.get(c.state, 'NEEDS REVIEW AGAIN')}: {c.statement}"
            for c in report.metadata.confirmations
            if c.required
        ]
        lines += [
            "",
            "These are your statements. PuzzlePress cannot verify rights, authorship, ISBN "
            "registration or the accuracy of an AI declaration.",
        ]
        if config.notes:
            lines += ["", "## Notes", "", *config.notes.splitlines()]
    return "\n".join(lines) + "\n"


def _origin(origin: ContentOrigin | None) -> str:
    if origin is None:
        return "NOT DECLARED"
    if origin is ContentOrigin.NONE:
        return "no artwork"
    return ORIGIN[origin]
