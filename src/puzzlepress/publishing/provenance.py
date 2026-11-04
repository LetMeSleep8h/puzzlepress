"""A small, auditable provenance record for a publishing package.

Machine facts are what PuzzlePress computed or recomputed and anyone can check
again (identities, digests, versions, counts). Author declarations are what the
author stated in book.yaml; they are recorded, never verified. A digest
identifies bytes; it proves nothing about authorship, rights or ownership. No
paths, timestamps, camera metadata or location data are recorded.
"""

import json

from .. import __version__
from ..content import PIPELINE_VERSION
from .metadata import kdp_ai_answers
from .readiness import PublishingReadinessReport

# 2: each confirmation records the review identity it was given for.
PROVENANCE_VERSION = 2
LIMITS = (
    "SHA-256 digests identify exact bytes. They do not prove authorship, copyright or "
    "ownership of the text, word lists or photograph.",
    "Author declarations and confirmations are the author's statements. PuzzlePress records "
    "them as written and cannot verify them.",
    "A valid ISBN check digit does not show that the ISBN is registered to this book.",
    "Readiness covers the checks PuzzlePress models. Amazon KDP reviews the book and decides.",
)


def _manifest(data: bytes | None) -> dict[str, object]:
    if data is None:
        return {}
    value = json.loads(data.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def provenance_record(report: PublishingReadinessReport) -> dict[str, object]:
    project = report.project
    config = project.publishing
    interior_pair = report.interior_bytes()
    cover_pair = report.cover_bytes()
    interior = _manifest(interior_pair[1] if interior_pair else None)
    cover = _manifest(cover_pair[1] if cover_pair else None)
    identities = report.identities()
    puzzles = project.word_search.puzzles if project.word_search else ()
    photo = cover.get("photo")
    photo_facts = (
        {
            "sha256": photo.get("sha256"),
            "format": photo.get("format"),
            "pixels": photo.get("pixels"),
            "in_cover_pdf": "re-encoded from bare pixels; EXIF, GPS, XMP, ICC and comments "
            "are not carried into cover.pdf",
        }
        if isinstance(photo, dict)
        else None
    )
    interior_pdf = interior.get("pdf")
    cover_pdf = cover.get("pdf")
    cover_toolchain = cover.get("toolchain")
    declarations: dict[str, object] | None = None
    if config is not None:
        declarations = {
            "ai_disclosure": kdp_ai_answers(config.ai_disclosure),
            "confirmations": [
                {
                    "name": c.name,
                    "statement": c.statement,
                    "covers": c.covers,
                    "confirmed": c.state == "confirmed",
                    "state": c.state,
                    "review_identity": c.confirmed if c.state == "confirmed" else None,
                }
                for c in report.metadata.confirmations
                if c.required
            ],
            "low_content": config.low_content,
            "isbn_mode": config.isbn.mode.value,
        }
        if project.coloring is not None:
            declarations["artwork_origin"] = {
                "interior_artwork": _value(config.ai_disclosure.interior_artwork),
                "cover_artwork": _value(config.ai_disclosure.cover_artwork),
            }
            declarations["content_rights"] = (
                config.content_rights.to_dict() if config.content_rights else None
            )
    content: dict[str, object] = (
        {"artwork": _artwork_facts(project, interior)}
        if project.coloring is not None
        else {
            "puzzles": {
                "count": len(puzzles),
                "generator": "PuzzlePress word-search generator: seeded, deterministic "
                "procedural placement, independently verified; no machine-learning model",
                "pipeline_version": PIPELINE_VERSION,
                "seeds": "derived per puzzle from build.seed and the puzzle ID",
            }
        }
    )
    return {
        "provenance_version": PROVENANCE_VERSION,
        "book_id": project.book.id,
        "machine_facts": {
            "engine_version": __version__,
            "source_identity": identities["source"],
            "publishing_identity": identities["publishing"],
            **content,
            "interior": None
            if not interior
            else {
                "interior_identity": interior.get("interior_identity"),
                "pdf_sha256": interior_pdf.get("sha256")
                if isinstance(interior_pdf, dict)
                else None,
                "page_count": interior.get("page_count"),
                "renderer_version": interior.get("renderer_version"),
                "raster_images": _raster_images(interior),
            },
            "cover": None
            if not cover
            else {
                "cover_identity": cover.get("cover_identity"),
                "pdf_sha256": cover_pdf.get("sha256") if isinstance(cover_pdf, dict) else None,
                "renderer_version": cover_toolchain.get("renderer_version")
                if isinstance(cover_toolchain, dict)
                else None,
                "photograph": photo_facts,
            },
        },
        "author_declarations": declarations,
        "limits": list(COLORING_LIMITS if project.coloring is not None else LIMITS),
    }


def _value(origin: object) -> object:
    return getattr(origin, "value", None)


def _raster_images(interior: dict[str, object]) -> int:
    """Embedded drawings: one per coloring page, each embedded once; none for word search."""
    artwork = interior.get("artwork")
    if not isinstance(artwork, list):
        return 0
    return len({str(item.get("prepared")) for item in artwork if isinstance(item, dict)})


def _artwork_facts(project: object, interior: dict[str, object]) -> dict[str, object]:
    """What PuzzlePress knows about the drawings: digests and processing, never authorship."""
    book = getattr(project, "coloring", None)
    assert book is not None
    pages = book.artwork_pages
    coloring = interior.get("coloring")
    return {
        "pages": len(pages),
        "drawings": len({artwork_id for _, artwork_id in pages}),
        "processing": "PuzzlePress line-art preparation of the author's imported files: "
        "deterministic image adjustments with recorded settings; no machine-learning model, "
        "nothing generated or traced",
        "preparation_version": coloring.get("preparation_version")
        if isinstance(coloring, dict)
        else None,
        "sources": sorted(
            {art.sha256 for art in book.artwork if any(a == art.id for _, a in pages)}
        ),
    }


COLORING_LIMITS = (
    "SHA-256 digests identify exact bytes. They do not prove authorship, copyright, a licence "
    "or ownership of the artwork, cover images or text; having a file is not a right to "
    "publish it.",
    *LIMITS[1:],
    "Automated line-art checks measure ink, lines and resolution. Whether each drawing is "
    "good to color, and how it prints, needs a person and a printed proof.",
)
