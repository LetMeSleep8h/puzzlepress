"""Studio adapter for Cover Studio: status, draft previews, photo import and builds.

Every decision is made by the core cover APIs used by `puzzlepress cover`; this
module locates the saved project's folders, caches decoded photos and rendered
draft PDFs in memory, and presents results. Previews are PDFium rasters of real
cover PDFs (a draft's PDF or cover.pdf), never recreated in the browser. Only
fixed artifact names and validated project asset references are ever read.

Text layers carry their measured boxes so Studio can select and move them; a move
becomes an authored offset in points that Python lays out and renders again.
Font specimens are small PDFs drawn with ReportLab and rasterized by PDFium, the
same path as the cover itself; photo thumbnails are previews only.
"""

import hashlib
import io
import re
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from threading import Lock

from PIL import Image
from reportlab.pdfgen.canvas import Canvas

from puzzlepress.cover.assets import (
    MAX_ASSET_BYTES,
    AssetEntry,
    Photo,
    decode_photo,
    import_photo,
    list_assets,
    read_asset,
    read_asset_file,
)
from puzzlepress.cover.build import (
    PDF_NAME,
    CoverBuild,
    build_cover,
    read_interior_facts,
    render_cover,
    write_cover,
    write_cover_preflight,
)
from puzzlepress.cover.convert import convert_to_regions, design_presets
from puzzlepress.cover.crop import crop_window
from puzzlepress.cover.design import region_area, region_origin
from puzzlepress.cover.font_assets import (
    MAX_FONT_BYTES,
    FontEntry,
    import_font,
    inspect_font,
    list_fonts,
    load_cover_fonts,
    load_font,
    read_font_file,
)
from puzzlepress.cover.fonts import CoverFace, font_name, missing_characters
from puzzlepress.cover.issues import CoverError
from puzzlepress.cover.layout import CoverCopy, cover_display, same_words
from puzzlepress.cover.model import (
    CoverLayout,
    CoverPhoto,
    CoverShape,
    CoverText,
    CoverTextBox,
    ImageResolution,
    StackItem,
)
from puzzlepress.cover.preflight import RULESET_VERSION, preflight_cover, report_bytes
from puzzlepress.cover.validation import panel_of
from puzzlepress.cover.variables import LIVE_VARIABLES
from puzzlepress.cover_config import CoverConfig, CoverImage, Crop
from puzzlepress.cover_design import PhotoElement, Region, TextBoxElement
from puzzlepress.cover_template import BINDING, BINDINGS
from puzzlepress.interior import InteriorError
from puzzlepress.interior.build import check_output_directory
from puzzlepress.interior.issues import LayoutIssue
from puzzlepress.interior.model import Box
from puzzlepress.interior.spec import KDP, KDP_COVER
from puzzlepress.models import Project
from puzzlepress.project import resolve_output_directory

from .editing import DraftStore
from .preview import PageOutOfRange, PageRasterizer, PreviewUnavailable
from .service import StudioError, StudioService

DIGEST = re.compile(r"[0-9a-f]{64}")
# A full 8.5 x 11 in wrap is about 1260 x 810 pt: ~1 px/pt to view, 2.5 to inspect,
# 0.3 for template gallery cards.
COVER_SCALES = {"thumb": 0.3, "preview": 1.0, "detail": 2.5}
LOCK_WAIT = 60.0
DRAFT_BUDGET = 160 * 1024 * 1024
PHOTO_CACHE = 4
THUMBNAIL_PIXELS = 360
SPECIMEN_TEXT = "Aa Bb Cc Gg Qq 0123456789"
# Bundled faces as Studio's font picker lists them: family, style, key.
BUNDLED_FONTS = (
    ("Newsreader Display", "Regular", CoverFace.SERIF_DISPLAY),
    ("Newsreader", "Regular", CoverFace.SERIF),
    ("Newsreader", "Italic", CoverFace.SERIF_ITALIC),
    ("Vera Sans", "Regular", CoverFace.SANS),
    ("Vera Sans", "Bold", CoverFace.SANS_BOLD),
    ("Vera Sans", "Oblique", CoverFace.SANS_ITALIC),
)


def _layer_of(role: str) -> str:
    """The editable layer a measured line belongs to."""
    if role.startswith(("front_extra:", "back_extra:")):
        return "extra:" + role.split(":", 1)[1]
    if "_element:" in role:
        return "element:" + role.split(":", 1)[1]
    if role in ("spine_title", "spine_author"):
        return "spine"
    return role


def _box(box: Box) -> dict[str, float]:
    return {k: round(getattr(box, k), 3) for k in ("x", "y", "width", "height")}


def _present_photo(photo: CoverPhoto, resolution: ImageResolution) -> dict[str, object]:
    left, top, right, bottom = photo.window.normalized()
    return {
        "role": photo.role,
        "layer": _layer_of(photo.role) if photo.role != "photo" else "photo",
        "region": _box(photo.region),
        "window": {"left": left, "top": top, "right": right, "bottom": bottom},
        "center": list(photo.window.center),
        "pixels": list(photo.pixels),
        "resolution": resolution.to_dict(),
    }


def _present_item(item: StackItem) -> dict[str, object]:
    if isinstance(item, CoverPhoto):
        kind, box, bounds = "photo", item.region, item.region
    elif isinstance(item, CoverShape):
        kind, box, bounds = item.kind, item.box, item.bounds
    else:
        kind, box, bounds = "text", item.box, item.box
    return {
        "role": item.role,
        "layer": _layer_of(item.role),
        "kind": kind,
        "box": _box(box),
        "bounds": _box(bounds),
        "rotation": round(item.rotation, 3) if isinstance(item, CoverShape) else 0.0,
    }


def present_layout(layout: CoverLayout) -> dict[str, object]:
    """Authoritative geometry for overlays and crop interaction, in PDF points."""
    g = layout.geometry
    photos = [
        _present_photo(photo, res)
        for photo, res in zip(layout.photos, layout.resolutions, strict=True)
    ]
    items: list[dict[str, object]] = []
    for item in layout.stack:
        if layout.config.designed:
            items.append(_present_item(item))
            if isinstance(item, CoverPhoto):
                items += [_present_item(shape) | {"baked": True} for shape in item.baked]
    resolution = layout.resolution
    return {
        "geometry": g.to_dict(),
        "texts": [
            {
                "role": text.role,
                "layer": _layer_of(text.role),
                "text": text.text,
                "panel": panel_of(text),
                "size": text.size,
                "face": text.face,
                "rotated": text.rotated,
                "box": _box(text.bounds),
            }
            for text in layout.texts
        ],
        "panels": [{"role": p.role, "box": _box(p.box)} for p in layout.panels],
        # The first photograph (versions 1 and 2 have exactly one); None without photos.
        "photo": photos[0] if photos else None,
        "photos": photos,
        "elements": items,
        "regions": {
            region.value: {
                "origin": _box(region_origin(g, region)),
                "area": _box(region_area(g, region)),
            }
            for region in Region
        },
        "warnings": [issue.to_dict() for issue in layout.warnings],
        "resolution": None if resolution is None else resolution.to_dict(),
        "spine_text": layout.spine.to_dict(),
    }


def display_checks(project: Project) -> list[dict[str, str]]:
    """How the cover's displayed text relates to the book details (never changed here)."""
    assert project.cover is not None
    copy = CoverCopy.from_project(project)
    details = copy.to_dict()
    checks: list[dict[str, str]] = []
    for key, shown in cover_display(project.cover, copy).items():
        detail = details[key]
        if shown is None and detail and key in ("title", "author"):
            checks.append(
                {
                    "code": "cover_text_omitted",
                    "severity": "warning",
                    "layer": key,
                    "message": f"The cover does not print the {key}; the book details keep "
                    f"{detail!r}. Publishing will ask you to confirm this is intended.",
                }
            )
        elif shown is not None and not same_words(shown, str(detail or "")):
            checks.append(
                {
                    "code": "cover_text_differs",
                    "severity": "error",
                    "layer": key,
                    "message": f"The cover prints the {key} as {shown!r}; the book details say "
                    f"{detail!r}. KDP requires the cover to match the book details, so "
                    "publishing blocks until they match. Line breaks and capitals may differ.",
                }
            )
    for element in project.cover.elements:
        if not isinstance(element, TextBoxElement):
            continue
        text = element.rich.plain() if element.rich is not None else element.text
        unresolved = sorted(
            {name for name in BINDING.findall(text) if name in BINDINGS} - set(LIVE_VARIABLES)
        )
        if unresolved:
            names = ", ".join("{" + name + "}" for name in unresolved)
            checks.append(
                {
                    "code": "template_binding_in_text",
                    "severity": "warning",
                    "layer": element.id,
                    "message": f"{names} is a template binding: it is filled in only when a "
                    "template is applied, so this text box prints it literally. Type the words "
                    "instead. Only {page_count} and {trim_size} are filled in from the built "
                    "interior.",
                }
            )
    for font in project.cover.fonts:
        if font.license is None or font.source is None:
            checks.append(
                {
                    "code": "cover_font_license",
                    "severity": "warning",
                    "layer": f"font:{font.id}",
                    "message": f"Record the license and source of font {font.id!r}. PuzzlePress "
                    "reads its embedding flags but cannot confirm your license.",
                }
            )
    return checks


def issue_checks(issues: tuple[LayoutIssue, ...]) -> list[dict[str, str]]:
    """Layout validation failures of a draft: shown, but the cover will not build."""
    layers = {
        "cover.title": "title",
        "cover.subtitle": "subtitle",
        "cover.author": "author",
        "cover.back_text": "back_text",
        "cover.imprint": "imprint",
    }
    checks: list[dict[str, str]] = []
    for issue in issues:
        region = issue.region or ""
        layer = layers.get(region, "")
        if "_extra:" in region:
            layer = "extra:" + region.split(":", 1)[1]
        elif "_element:" in region:
            layer = "element:" + region.split(":", 1)[1]
        checks.append(
            {
                "code": issue.code,
                "severity": "error",
                "layer": layer,
                "message": f"{issue.message} This draft previews, but the cover will not "
                "build until it is fixed.",
            }
        )
    return checks


def layout_checks(layout: CoverLayout, page_count: int) -> list[dict[str, str]]:
    """Readiness facts a draft can know before a cover is built (no artifacts yet)."""
    checks: list[dict[str, str]] = []
    for photo, res in zip(layout.photos, layout.resolutions, strict=True):
        layer = "photo" if photo.role == "photo" else _layer_of(photo.role)
        if res.status == "image_too_small":
            checks.append(
                {
                    "code": "image_too_small",
                    "severity": "error",
                    "layer": layer,
                    "message": f"The photo reaches at most {res.max_dpi:.0f} DPI here; KDP "
                    f"needs {res.minimum_dpi:g}. Use a larger photograph.",
                }
            )
        elif res.status == "image_low_effective_dpi":
            checks.append(
                {
                    "code": "image_low_effective_dpi",
                    "severity": "error",
                    "layer": layer,
                    "message": f"This crop prints at {res.effective_dpi:.0f} DPI; KDP needs "
                    f"{res.minimum_dpi:g}. Zoom out (up to {res.max_dpi:.0f} DPI available).",
                }
            )
    for warning in layout.warnings:
        region = warning.region or ""
        checks.append(
            {
                "code": warning.code,
                "severity": "warning",
                "layer": _layer_of(region.removeprefix("cover.")) if "_element:" in region else "",
                "message": warning.message,
            }
        )
    if page_count < KDP.min_pages:
        checks.append(
            {
                "code": "kdp_minimum_page_count",
                "severity": "error",
                "message": f"The interior has {page_count} pages; KDP paperbacks need "
                f"{KDP.min_pages}. The cover still previews and builds.",
            }
        )
    reasons = {
        "page_count": "Spine text is omitted: KDP prints it only from 80 pages.",
        "spine_too_narrow": "Spine text is omitted: the spine cannot hold 7 pt type.",
        "authored": "Spine text is off for this cover.",
    }
    if layout.spine.reason:
        checks.append(
            {
                "code": "spine_text_omitted",
                "severity": "info",
                "message": reasons[layout.spine.reason],
            }
        )
    return checks


MIN_CONTRAST = 3.0  # WCAG large-text contrast; cover type is mostly large.


def _luminance(color: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    a, b = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def _inside(box: Box, x: float, y: float) -> bool:
    return box.x <= x <= box.right and box.y <= y <= box.top


def _behind(layout: CoverLayout, text: CoverText) -> tuple[float, float, float] | None:
    """The solid color under the middle of a line, or None over a photograph or gradient."""
    x, y = text.bounds.x + text.bounds.width / 2, text.bounds.y + text.bounds.height / 2
    color: tuple[float, float, float] | None = layout.background.color
    for fill in layout.region_fills:
        if _inside(fill.box, x, y):
            color = None if fill.gradient else fill.color
    stack = layout.stack
    book_text = "_element:" not in text.role
    limit = next(
        (
            i
            for i, item in enumerate(stack)
            if isinstance(item, CoverTextBox) and item.role == text.role
        ),
        len(stack),
    )
    for item in stack[:limit]:
        if isinstance(item, CoverPhoto) and _inside(item.region, x, y):
            color = None
        elif (
            isinstance(item, CoverShape)
            and item.fill is not None
            and item.opacity >= 1.0
            and not item.rotation
            and item.kind != "line"
            and _inside(item.box, x, y)
        ):
            if item.kind == "ellipse":
                rx, ry = item.box.width / 2, item.box.height / 2
                dx, dy = x - (item.box.x + rx), y - (item.box.y + ry)
                if (dx / rx) ** 2 + (dy / ry) ** 2 > 1:
                    continue
            color = item.fill
    if book_text:
        for panel in layout.panels:
            if _inside(panel.box, x, y):
                color = panel.color
    return color


def design_checks(layout: CoverLayout) -> list[dict[str, str]]:
    """Advisory design findings: low contrast and template photo placeholders. Never blocking."""
    if not layout.config.designed:
        return []
    checks: list[dict[str, str]] = []
    flagged: set[str] = set()
    for text in layout.texts:
        layer = _layer_of(text.role)
        if layer in flagged:
            continue
        background = _behind(layout, text)
        if background is None:
            continue
        ratio = contrast_ratio(text.color, background)
        if ratio < MIN_CONTRAST:
            flagged.add(layer)
            checks.append(
                {
                    "code": "low_contrast",
                    "severity": "warning",
                    "layer": layer,
                    "message": f"This text has a contrast of {ratio:.1f}:1 against its "
                    f"background; aim for at least {MIN_CONTRAST:g}:1 so it reads in print "
                    "and in thumbnails.",
                }
            )
    for element in layout.config.elements:
        if element.id.startswith("photo-slot-") and element.name and "placeholder" in element.name:
            checks.append(
                {
                    "code": "template_photo_placeholder",
                    "severity": "warning",
                    "layer": f"element:{element.id}",
                    "message": "This template frame is waiting for a photograph. Import one in "
                    "Photos and place it, or delete the placeholder.",
                }
            )
    return checks


class CoverService:
    def __init__(self, service: StudioService, drafts: DraftStore) -> None:
        self.service = service
        self.store = service.store
        self.drafts = drafts
        self.rasterizer = PageRasterizer(scales=COVER_SCALES)
        self._lock = Lock()
        self._photos: OrderedDict[str, Photo] = OrderedDict()
        self._pdfs: OrderedDict[str, bytes] = OrderedDict()
        self._pdf_bytes = 0
        self._reports: OrderedDict[tuple[str, ...], dict[str, object]] = OrderedDict()
        # Header facts by (path, size, mtime): listing photos and fonts stays cheap.
        self._headers: dict[tuple[str, int, int], object] = {}
        self._thumbnails: OrderedDict[str, bytes] = OrderedDict()
        self.specimens = PageRasterizer(budget=16 * 1024 * 1024, scales={"specimen": 2.0})

    # ------------------------------------------------------------ locating

    def _folders(self, key: str, project: Project) -> tuple[Path, Path]:
        source = self.store.source(key).parent
        try:
            directory = check_output_directory(resolve_output_directory(project, source), source)
        except InteriorError as error:
            raise StudioError(
                503, "output_unavailable", "The project's output directory is unavailable."
            ) from error
        return source, directory

    def _photo(self, source: Path, image: CoverImage) -> Photo:
        digest = image.sha256
        with self._lock:
            cached = self._photos.get(digest)
            if cached is not None:
                self._photos.move_to_end(digest)
        data = read_asset(source, image)  # Always re-verify the file.
        if cached is not None:
            return cached
        photo = decode_photo(data)
        with self._lock:
            self._photos[digest] = photo
            while len(self._photos) > PHOTO_CACHE:
                self._photos.popitem(last=False)
        return photo

    def _photo_set(self, source: Path, project: Project) -> dict[str, Photo]:
        assert project.cover is not None
        return {image.sha256: self._photo(source, image) for image in project.cover.images()}

    def _remember(self, pdf: bytes) -> str:
        digest = hashlib.sha256(pdf).hexdigest()
        with self._lock:
            if digest not in self._pdfs:
                self._pdfs[digest] = pdf
                self._pdf_bytes += len(pdf)
            self._pdfs.move_to_end(digest)
            while self._pdf_bytes > DRAFT_BUDGET and len(self._pdfs) > 1:
                _, evicted = self._pdfs.popitem(last=False)
                self._pdf_bytes -= len(evicted)
        return digest

    # ------------------------------------------------------------ assets

    def _photo_entries(self, source: Path) -> tuple[AssetEntry, ...]:
        try:
            return list_assets(source)
        except CoverError as error:
            raise StudioError(422, error.issues[0].code, error.issues[0].message) from error

    def assets(self, key: str) -> dict[str, object]:
        source = self.store.source(key).parent
        return {
            "assets": [
                {
                    "path": entry.path,
                    "problem": entry.problem,
                    **(entry.info.to_dict() if entry.info else {}),
                }
                for entry in self._photo_entries(source)
            ]
        }

    def thumbnail(self, key: str, reference: str) -> bytes:
        """A small upright sRGB JPEG of a project photograph, for the photo library only."""
        source = self.store.source(key).parent
        try:
            data = read_asset_file(source, reference)
        except CoverError as error:
            raise StudioError(404, error.issues[0].code, error.issues[0].message) from error
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            cached = self._thumbnails.get(digest)
        if cached is not None:
            return cached
        try:
            image = decode_photo(data).image.copy()
        except CoverError as error:
            raise StudioError(422, error.issues[0].code, error.issues[0].message) from error
        image.thumbnail((THUMBNAIL_PIXELS, THUMBNAIL_PIXELS), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=85)
        jpeg = buffer.getvalue()
        with self._lock:
            self._thumbnails[digest] = jpeg
            while len(self._thumbnails) > 64:
                self._thumbnails.popitem(last=False)
        return jpeg

    def _font_entries(self, source: Path) -> tuple[FontEntry, ...]:
        try:
            return list_fonts(source)
        except CoverError as error:
            raise StudioError(422, error.issues[0].code, error.issues[0].message) from error

    def fonts(self, key: str) -> dict[str, object]:
        source = self.store.source(key).parent
        return {"fonts": [_font_entry(entry) for entry in self._font_entries(source)]}

    def import_font(self, key: str, data: bytes, name: str) -> dict[str, object]:
        if len(data) > MAX_FONT_BYTES:
            raise StudioError(413, "font_unsupported", "The font file is too large.")
        source = self.store.source(key).parent
        try:
            imported = import_font(source, data, name)
        except CoverError as error:
            issue = error.issues[0]
            status = 503 if issue.code == "write_failed" else 422
            raise StudioError(status, issue.code, issue.message) from error
        return {
            "font": {"path": imported.path, "reused": imported.reused, **imported.info.to_dict()},
            **self.fonts(key),
        }

    def specimen(self, key: str, reference: str) -> bytes:
        """PNG of a font specimen rendered as a PDF by ReportLab, then by PDFium."""
        source = self.store.source(key).parent
        if reference.startswith("bundled:"):
            face = reference.removeprefix("bundled:")
            if face not in {f.value for f in CoverFace}:
                raise StudioError(404, "not_found", "Unknown bundled face.")
            name = font_name(face)
        else:
            try:
                name = load_font(read_font_file(source, reference)).key
            except CoverError as error:
                raise StudioError(422, error.issues[0].code, error.issues[0].message) from error
        pdf = _specimen_pdf(name)
        digest = hashlib.sha256(pdf).hexdigest()
        try:
            return self.specimens.png(pdf, digest, 1, "specimen")
        except PreviewUnavailable as error:
            raise StudioError(
                503, "preview_unavailable", "Install the studio extra (pypdfium2) for previews."
            ) from error

    def _library(
        self, source: Path, project: Project, region: Box, crop: Crop
    ) -> dict[str, object]:
        """Photos with the resolution each reaches here; fonts with the characters they lack."""
        assert project.cover is not None
        zoom = crop.zoom
        photos = []
        for entry in self._photo_entries(source):
            item: dict[str, object] = {"path": entry.path, "problem": entry.problem}
            if entry.info is not None:
                item |= entry.info.to_dict()
                window = crop_window(entry.info.width, entry.info.height, region, crop)
                item["dpi"] = {
                    "effective": round(window.effective_dpi, 2),
                    "max": round(window.max_dpi, 2),
                    "zoom": zoom,
                    "minimum": KDP_COVER.min_image_dpi,
                    "sufficient": window.effective_dpi + 1e-9 >= KDP_COVER.min_image_dpi,
                }
            photos.append(item)
        text = _cover_characters(project)
        fonts = []
        for font in self._font_entries(source):
            listed = _font_entry(font)
            if font.info is not None:
                charset = self._charset(source, font)
                listed["missing"] = sorted({c for c in text if ord(c) not in charset})
            fonts.append(listed)
        bundled = [
            {
                "key": face.value,
                "family": family,
                "style": style,
                "missing": list(missing_characters("".join(sorted(text)), face)),
            }
            for family, style, face in BUNDLED_FONTS
        ]
        return {"photos": photos, "fonts": fonts, "bundled_fonts": bundled}

    def _charset(self, source: Path, entry: FontEntry) -> frozenset[int]:
        assert entry.info is not None
        cache_key = (entry.info.sha256, 0, 0)
        cached = self._headers.get(cache_key)
        if isinstance(cached, frozenset):
            return cached
        _, ttf = inspect_font(read_font_file(source, entry.path), entry.info.container)
        charset = frozenset(ttf.face.charToGlyph)
        self._headers[cache_key] = charset
        return charset

    def import_photo(self, key: str, data: bytes, name: str) -> dict[str, object]:
        if len(data) > MAX_ASSET_BYTES:
            raise StudioError(413, "image_unsupported", "The photograph file is too large.")
        source = self.store.source(key).parent
        try:
            imported = import_photo(source, data, name)
        except CoverError as error:
            issue = error.issues[0]
            status = 503 if issue.code == "write_failed" else 422
            raise StudioError(status, issue.code, issue.message) from error
        return {
            "asset": {"path": imported.path, "reused": imported.reused, **imported.info.to_dict()},
            **self.assets(key),
        }

    # ------------------------------------------------------------ status and build

    def status(self, key: str) -> dict[str, object]:
        with self.service.exclusive(wait=LOCK_WAIT):
            return self._status(key)

    def _status(self, key: str, built: CoverBuild | None = None) -> dict[str, object]:
        project, revision = self.store.snapshot(key)
        base: dict[str, object] = {"key": key, "revision": revision, "ruleset": RULESET_VERSION}
        if project.cover is None:
            return {**base, "state": "no_config", "report": None, "preview": None}
        source, directory = self._folders(key, project)
        files = [
            directory / name
            for name in ("cover.pdf", "cover.json", "interior.pdf", "interior.json")
        ]
        photos = [source / image.path for image in project.cover.images()]
        cache_key = (key, revision, *(_digest(path) for path in [*files, *photos]))
        cached = self._reports.get(cache_key)
        if cached is None:
            report = preflight_cover(project, source, directory, built)
            data = report.to_dict()
            pdf = report.context.artifacts.pdf
            expected = report.context.expected
            cached = {
                "state": report.state,
                "report": data,
                "layout": present_layout(expected.layout) if expected else None,
                "preview": None
                if pdf is None
                else {"pdf_sha256": hashlib.sha256(pdf).hexdigest(), "scales": COVER_SCALES},
            }
            self._reports[cache_key] = cached
            while len(self._reports) > 8:
                self._reports.popitem(last=False)
        return {**base, **cached}

    def build(self, key: str, revision: str) -> dict[str, object]:
        """Build the saved source exactly at `revision`, then preflight what was written."""
        with self.service.exclusive(wait=LOCK_WAIT):
            project, current = self.store.snapshot(key)
            if current != revision:
                raise StudioError(
                    409, "source_changed", "Saved source changed. Reload before building."
                )
            if project.cover is None:
                raise StudioError(422, "no_cover", "This project has no cover section.")
            source, directory = self._folders(key, project)
            try:
                build = build_cover(project, source, directory)
                write_cover(build, directory, source)
            except CoverError as error:
                return {
                    "build": {
                        "success": False,
                        "stage": error.stage,
                        "diagnostics": [issue.to_dict() for issue in error.issues],
                    },
                    **self._status(key),
                }
            report = preflight_cover(project, source, directory, build)
            try:
                write_cover_preflight(report_bytes(report), project.book.id, directory, source)
            except CoverError:
                pass  # The report is still returned; cover-preflight.json is optional.
            return {"build": {"success": True}, **self._status(key, build)}

    # ------------------------------------------------------------ draft preview

    def draft(self, key: str, source_data: object) -> dict[str, object]:
        """Render the unsaved draft's cover in memory against the built interior."""
        project = self.drafts.validate(key, source_data)
        if project.cover is None:
            raise StudioError(422, "no_cover", "This draft has no cover section.")
        with self.service.exclusive(wait=LOCK_WAIT):
            source, directory = self._folders(key, project)
            try:
                interior = read_interior_facts(directory, project, require_current=False)
                photos = self._photo_set(source, project)
                fonts = load_cover_fonts(source, project.cover)
                build = render_cover(
                    project, interior, photos, fonts=fonts, allow_layout_issues=True
                )
            except CoverError as error:
                return {
                    "success": False,
                    "stage": error.stage,
                    "diagnostics": [issue.to_dict() for issue in error.issues],
                }
            digest = self._remember(build.pdf)
            return {
                "success": True,
                "interior": {
                    **interior.physical(),
                    "stale": interior.stale,
                    "interior_identity": interior.interior_identity,
                },
                "cover_identity": build.manifest["cover_identity"],
                "layout": present_layout(build.layout),
                "checks": issue_checks(build.layout_issues)
                + display_checks(project)
                + layout_checks(build.layout, interior.page_count)
                + design_checks(build.layout),
                "buildable": not build.layout_issues,
                "display": cover_display(project.cover, CoverCopy.from_project(project)),
                "library": self._library(source, project, *_library_frame(build.layout)),
                "preview": {"pdf_sha256": digest, "scales": COVER_SCALES},
            }

    def convert(self, key: str, source_data: object) -> dict[str, object]:
        """The version 3 equivalent of a draft's v1/v2 cover, verified by rendering both.

        Nothing is saved: the browser offers the converted cover as a draft edit.
        """
        project = self.drafts.validate(key, source_data)
        cover = project.cover
        if cover is None:
            raise StudioError(422, "no_cover", "This draft has no cover section.")
        if cover.designed:
            raise StudioError(422, "already_designed", "This cover is already a region design.")
        converted = convert_to_regions(cover)
        designed = replace(project, cover=converted)
        with self.service.exclusive(wait=LOCK_WAIT):
            source, directory = self._folders(key, project)
            try:
                interior = read_interior_facts(directory, project, require_current=False)
                photos = self._photo_set(source, project)
                fonts = load_cover_fonts(source, cover)
                before = render_cover(
                    project, interior, photos, fonts=fonts, allow_layout_issues=True
                )
                after = render_cover(
                    designed, interior, photos, fonts=fonts, allow_layout_issues=True
                )
            except CoverError as error:
                return {
                    "success": False,
                    "stage": error.stage,
                    "diagnostics": [issue.to_dict() for issue in error.issues],
                }
        digest = self._remember(after.pdf)
        return {
            "success": True,
            "cover": converted.to_dict(),
            "identical": before.pdf == after.pdf,
            "layout": present_layout(after.layout),
            "preview": {"pdf_sha256": digest, "scales": COVER_SCALES},
        }

    def presets(self, key: str, source_data: object) -> dict[str, object]:
        """Named version 3 starting points from the draft's photograph and colors."""
        project = self.drafts.validate(key, source_data)
        if project.cover is None:
            raise StudioError(422, "no_cover", "This draft has no cover section.")
        return {
            "presets": [
                {
                    "id": preset.id,
                    "name": preset.name,
                    "description": preset.description,
                    "cover": preset.config.to_dict(),
                }
                for preset in design_presets(project.cover)
            ]
        }

    # ------------------------------------------------------------ rasters

    def image(self, key: str, pdf_digest: str, size: str) -> bytes:
        if size not in COVER_SCALES:
            raise StudioError(404, "not_found", "Unknown preview size.")
        if not DIGEST.fullmatch(pdf_digest):
            raise StudioError(422, "invalid_request", "Supply the cover PDF digest.")
        project = self.store.load(key)
        with self._lock:
            pdf = self._pdfs.get(pdf_digest)
        if pdf is None:
            _, directory = self._folders(key, project)
            path = directory / PDF_NAME
            data = path.read_bytes() if path.is_file() and not path.is_symlink() else None
            if data is None or hashlib.sha256(data).hexdigest() != pdf_digest:
                raise StudioError(
                    409, "preview_stale", "This cover preview is no longer available."
                )
            pdf = data
        try:
            return self.rasterizer.png(pdf, pdf_digest, 1, size)
        except PageOutOfRange as error:
            raise StudioError(404, "page_not_found", "The cover has no such page.") from error
        except PreviewUnavailable as error:
            raise StudioError(
                503, "preview_unavailable", "Install the studio extra (pypdfium2) for previews."
            ) from error


def _library_frame(layout: CoverLayout) -> tuple[Box, Crop]:
    """Where library DPI is measured: the first photograph, else the front region."""
    config = layout.config
    if layout.photos:
        photo = layout.photos[0]
        if config.image is not None:
            return photo.region, config.crop
        element = next(
            e
            for e in config.elements
            if isinstance(e, PhotoElement) and photo.role.endswith(f":{e.id}")
        )
        return photo.region, element.crop
    return region_area(layout.geometry, Region.FRONT), Crop()


def _digest(path: Path) -> str:
    try:
        if path.is_file() and not path.is_symlink():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "?"
    return "-"


def _font_entry(entry: FontEntry) -> dict[str, object]:
    return {
        "path": entry.path,
        "problem": entry.problem,
        "message": entry.message,
        **(entry.info.to_dict() if entry.info else {}),
    }


def _cover_characters(project: Project) -> set[str]:
    """Every character the cover could print, as written and in capitals."""
    config: CoverConfig | None = project.cover
    assert config is not None
    copy = CoverCopy.from_project(project)
    values = [v for v in copy.to_dict().values() if isinstance(v, str)]
    values += [layer.text for _, layer in config.text if layer.text]
    values += [extra.text for extra in config.extra]
    text = "".join(values)
    return {c for c in text + text.upper() if not c.isspace()}


def _specimen_pdf(name: str) -> bytes:
    """A one-line specimen page drawn exactly as cover text is (ReportLab, invariant)."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=(300, 44), invariant=True)
    canvas.setFillColorRGB(1, 1, 1)
    canvas.rect(0, 0, 300, 44, stroke=0, fill=1)
    canvas.setFillColorRGB(0.145, 0.176, 0.157)
    canvas.setFont(name, 20)
    canvas.drawString(8, 14, SPECIMEN_TEXT)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()
