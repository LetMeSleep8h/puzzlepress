"""A coloring book's printable content: each used drawing's prepared pixels.

The coloring engine's counterpart of word search's generated batch. Originals are
read and verified against their pinned SHA-256, prepared in memory with their
saved settings (`coloring.prepare`, the same pipeline as Studio's previews), and
kept as exact, losslessly packed samples: 1 bit per pixel when the prepared pixels
are only black and white, else 8-bit gray, deflated. Holding packed samples
instead of decoded images bounds memory for long books; the packed samples are
also exactly what the PDF embeds, so what was prepared is what prints.

Nothing here writes files. A drawing that cannot be read or prepared is reported
as a failure for the plan, never replaced, skipped silently or prepared with other
settings.
"""

import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..coloring_config import Artwork
from ..errors import ProjectError, ValidationIssue
from ..identity import build_identity
from ..models import Project
from .assets import read_artwork
from .issues import ArtworkError
from .prepare import PREPARATION_VERSION, pixel_digest, prepared_pixels

# Deflate level for packed samples. Changing it changes PDF bytes: it is part of
# the coloring renderer version (interior.coloring.COLORING_RENDERER_VERSION).
DEFLATE_LEVEL = 9


@dataclass(frozen=True)
class PreparedArt:
    """One drawing's prepared pixels as packed samples, with their digest."""

    artwork: Artwork
    width: int
    height: int
    bits: int  # 1 (only black and white) or 8 (gray levels).
    samples: bytes  # Deflated rows; 1-bit rows are padded to whole bytes, 0 is black.
    digest: str  # `pixel_digest` of the prepared mode-L pixels.

    def image(self) -> Image.Image:
        """Decode the packed samples back to the prepared mode-L pixels."""
        raw = zlib.decompress(self.samples)
        if self.bits == 1:
            return Image.frombytes("1", (self.width, self.height), raw).convert("L")
        return Image.frombytes("L", (self.width, self.height), raw)


def pack(artwork: Artwork, image: Image.Image) -> PreparedArt:
    """Pack prepared mode-L pixels losslessly. Two-level art uses 1 bit per pixel."""
    if image.mode != "L":
        raise ValueError("Prepared artwork is mode L")
    levels = {value for value, count in enumerate(image.histogram()) if count}
    digest = pixel_digest(image)
    if levels <= {0, 255}:
        # Exactly representable in one bit: 0 stays black, 255 white.
        raw, bits = image.convert("1", dither=Image.Dither.NONE).tobytes(), 1
    else:
        raw, bits = image.tobytes(), 8
    return PreparedArt(
        artwork, image.width, image.height, bits, zlib.compress(raw, DEFLATE_LEVEL), digest
    )


@dataclass(frozen=True)
class ColoringContent:
    """Prepared drawings by artwork ID, for exactly one source (its build identity)."""

    identity: str
    art: dict[str, PreparedArt]
    failures: dict[str, ArtworkError]
    preparation_version: int = PREPARATION_VERSION


def prepare_content(project: Project, source_directory: Path | None) -> ColoringContent:
    """Read, verify and prepare every drawing a page uses, in page order.

    Raises ProjectError when the book has no coloring section or no project folder
    to read from; per-drawing failures are returned for the plan to report.
    """
    book = project.coloring
    if book is None:
        raise ProjectError(
            (ValidationIssue("coloring", "required", "This project is not a coloring book."),)
        )
    if source_directory is None:
        raise ProjectError(
            (
                ValidationIssue(
                    "coloring",
                    "project_folder_required",
                    "Coloring books are built from their project folder, where the artwork is.",
                ),
            )
        )
    art: dict[str, PreparedArt] = {}
    failures: dict[str, ArtworkError] = {}
    for _, artwork_id in book.artwork_pages:
        if artwork_id in art or artwork_id in failures:
            continue
        artwork = book.artwork_by_id(artwork_id)
        if artwork is None:  # Validation guarantees every page names known artwork.
            raise RuntimeError(f"Page names unknown artwork {artwork_id!r}")
        try:
            data = read_artwork(source_directory, artwork)
            image = prepared_pixels(data, artwork.adjustments, artwork.path)
        except ArtworkError as error:
            failures[artwork_id] = error.about(artwork.path)
            continue
        art[artwork_id] = pack(artwork, image)
    return ColoringContent(build_identity(project), art, failures)
