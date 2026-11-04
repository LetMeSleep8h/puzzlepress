"""Cover templates: reusable, versioned cover designs that are not any one book.

A template holds a design (type preset, legibility, spine text setting, region
backgrounds, the element stack and per-layer text styling) plus display facts
(name, description, category, palette, photo need) and, for custom templates,
the imported fonts it uses. It never holds a book's identity: no title, author
or imprint words, no back-cover copy, no photograph and no attestation.

Book-bound words are semantic bindings resolved when a template is applied:
`{title}` (the book title), `{subtitle}`, `{author}`, `{imprint}`,
`{puzzle_count}`, `{theme_count}` and `{solutions}` (word search) and
`{artwork_count}` (coloring pages). Text whose binding has no value in the book
is left out rather than invented, so a word-search binding never prints on a
coloring cover. `{page_count}` and `{trim_size}` are live variables
(puzzlepress.cover.variables): applying a template keeps them as written, and
the cover layout fills them in from the built interior. Photographs are numbered slots filled with
the cover's own photographs in stack order; an unfilled required slot becomes
a visible placeholder, never an unrelated picture. Spine boxes may say
`"width": "spine"` so they follow the built interior's spine.

Templates use the cover's own region and element system: applying one produces
an ordinary version 3 cover configuration that Python validates, lays out and
renders like any other. There is no second rendering engine and nothing in a
template is executed.
"""

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .content_validation import _Reader
from .cover.variables import LIVE_VARIABLES
from .cover_config import (
    METADATA_ROLES,
    CoverConfig,
    CoverFont,
    CoverImage,
    Crop,
)
from .cover_design import PhotoElement, Region, TextBoxElement
from .cover_richtext import is_rich
from .cover_validation import HEX_COLOR, LAYER_ID, _fonts, validate_cover
from .errors import ValidationIssue
from .models import Project

TEMPLATE_VERSION = 1
SUPPORTED_TEMPLATE_VERSIONS = (1,)
MAX_TEMPLATE_BYTES = 256 * 1024
MAX_NAME = 60
MAX_DESCRIPTION = 300
MAX_PALETTE = 8
MAX_SLOTS = 4
IDENTITY_PREFIX = "pp1-cover-template-sha256-"
# The reference trim template coordinates are authored against (8.5 x 11 in).
REFERENCE_TRIM = (612.0, 792.0)
BINDINGS = (
    "title",
    "subtitle",
    "author",
    "imprint",
    "puzzle_count",
    "theme_count",
    "solutions",
    "artwork_count",
    "page_count",
    "trim_size",
)
BINDING = re.compile(r"\{([a-z_]+)\}")
TEMPLATE_FIELDS = {
    "template_version",
    "id",
    "name",
    "description",
    "category",
    "photo",
    "palette",
    "fonts",
    "design",
    "provenance",
}
DESIGN_FIELDS = {"type", "legibility", "spine_text", "regions", "elements", "text"}
# Template-only element fields, removed when the template is instantiated.
TEMPLATE_ELEMENT_FIELDS = {"slot", "requires_slot"}
PLACEHOLDER_FILL = "#8f948d"
# Sample values for validating a template's design as a cover.
_SAMPLE_IMAGE = {"path": "cover-assets/template-sample.jpg", "sha256": "0" * 64}
_SAMPLE_SPINE = 18.0


class TemplateCategory(StrEnum):
    PHOTOGRAPHIC = "photographic"
    BOLD = "bold"
    DYNAMIC = "dynamic"
    CLASSIC = "classic"
    MINIMAL = "minimal"
    TECHNICAL = "technical"
    PUZZLE = "puzzle"
    EDITORIAL = "editorial"
    CUSTOM = "custom"


class PhotoNeed(StrEnum):
    REQUIRED = "required"  # Unfilled slots become visible placeholders.
    OPTIONAL = "optional"  # Unfilled slots (and elements that frame them) are left out.
    NONE = "none"


class TemplateError(Exception):
    """A template that cannot be read, saved or applied, with structured issues."""

    def __init__(self, code: str, message: str, issues: tuple[ValidationIssue, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.issues = issues


@dataclass(frozen=True)
class CoverTemplate:
    id: str
    name: str
    description: str
    category: TemplateCategory
    photo: PhotoNeed
    design: Mapping[str, object]  # Validated, JSON-compatible design (see module docstring).
    palette: tuple[str, ...] = ()
    fonts: tuple[CoverFont, ...] = ()
    provenance: str | None = None
    builtin: bool = False  # Shipped with PuzzlePress; never modified or deleted.

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "template_version": TEMPLATE_VERSION,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "photo": self.photo.value,
        }
        if self.palette:
            data["palette"] = list(self.palette)
        if self.fonts:
            data["fonts"] = [font.to_dict() for font in self.fonts]
        data["design"] = copy.deepcopy(dict(self.design))
        if self.provenance is not None:
            data["provenance"] = self.provenance
        return data

    def identity(self) -> str:
        return IDENTITY_PREFIX + hashlib.sha256(canonical(self.to_dict())).hexdigest()

    def slots(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                {
                    int(e["slot"])  # type: ignore[call-overload]
                    for e in _elements(self.design)
                    if e.get("type") == "photo"
                }
            )
        )

    def faces(self) -> tuple[str, ...]:
        """Every font key the design names (bundled faces and families, imported ids)."""
        names: set[str] = set()
        design = self.design
        text = design.get("text")
        for layer in text.values() if isinstance(text, dict) else ():
            if isinstance(layer, dict) and isinstance(layer.get("font"), str):
                names.add(layer["font"])
        for element in _elements(design):
            if isinstance(element.get("font"), str):
                names.add(str(element["font"]))
            rich = element.get("rich")
            for block in rich.get("blocks", []) if isinstance(rich, dict) else []:
                for run in block.get("runs", []) if isinstance(block, dict) else []:
                    if isinstance(run, dict) and isinstance(run.get("font"), str):
                        names.add(run["font"])
        return tuple(sorted(names))


def canonical(data: object) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def template_bytes(template: CoverTemplate) -> bytes:
    """The stored and exported form: canonical keys, indented, UTF-8, final newline."""
    text = json.dumps(template.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def _elements(design: Mapping[str, object]) -> list[dict[str, object]]:
    elements = design.get("elements")
    return [e for e in elements if isinstance(e, dict)] if isinstance(elements, list) else []


# ------------------------------------------------------------------ bindings


def template_values(project: Project) -> dict[str, str]:
    """Binding values from the book itself; a binding without a value is absent."""
    book = project.book
    values: dict[str, str] = {"title": book.title}
    for key in ("subtitle", "author", "imprint"):
        value = getattr(book, key)
        if value:
            values[key] = value
    puzzles = project.word_search.puzzles if project.word_search else ()
    if puzzles:
        values["puzzle_count"] = str(len(puzzles))
        themes = {p.theme for p in puzzles if p.theme}
        if len(themes) >= 2:
            values["theme_count"] = str(len(themes))
    if project.coloring is not None and project.coloring.artwork_pages:
        values["artwork_count"] = str(len(project.coloring.artwork_pages))
    composition = project.composition
    if (
        project.coloring is None
        and composition is not None
        and composition.solutions.placement.value == "end"
    ):
        values["solutions"] = "Solutions at the back"
    # Live variables stay in the text; the cover layout fills them in.
    values.update({name: "{" + name + "}" for name in LIVE_VARIABLES})
    return values


def _bind(text: str, values: Mapping[str, str]) -> str | None:
    """Text with bindings resolved; None when any binding has no value."""
    missing = False

    def resolve(match: re.Match[str]) -> str:
        nonlocal missing
        value = values.get(match[1])
        if value is None:
            missing = True
            return ""
        return value

    result = BINDING.sub(resolve, text)
    return None if missing else result


def _bind_rich(document: dict[str, object], values: Mapping[str, str]) -> dict[str, object] | None:
    """Blocks whose bindings all resolve; None when nothing is left."""
    blocks: list[object] = []
    for block in document.get("blocks", []):  # type: ignore[attr-defined]
        runs: list[object] = []
        dropped = False
        for run in block.get("runs", []):
            text = _bind(run["text"], values)
            if text is None:
                dropped = True
                break
            if text:
                runs.append({**run, "text": text})
        if not dropped and (runs or not block.get("runs")):
            blocks.append({**block, "runs": runs})
    if not any(block.get("runs") for block in blocks):  # type: ignore[attr-defined]
        return None
    return {**document, "blocks": blocks}


# ------------------------------------------------------------------ instantiation


@dataclass(frozen=True)
class SlotPhoto:
    image: CoverImage
    crop: Crop


def _scale(element: dict[str, object], sx: float, sy: float, spine: float) -> None:
    box = element.get("box")
    if isinstance(box, dict):
        if box.get("width") == "spine":
            box["x"], box["width"] = 0.0, round(spine, 2)
        elif sx != 1.0:
            box["x"], box["width"] = round(box["x"] * sx, 2), round(box["width"] * sx, 2)
        if sy != 1.0:
            box["y"], box["height"] = round(box["y"] * sy, 2), round(box["height"] * sy, 2)
    for end in ("from", "to"):
        point = element.get(end)
        if isinstance(point, dict) and (sx != 1.0 or sy != 1.0):
            point["x"], point["y"] = round(point["x"] * sx, 2), round(point["y"] * sy, 2)


def instantiate(
    template: CoverTemplate,
    values: Mapping[str, str],
    photos: tuple[SlotPhoto, ...],
    spine_width: float,
    trim: tuple[float, float] = REFERENCE_TRIM,
) -> tuple[dict[str, object], tuple[int, ...]]:
    """The template as a version 3 cover section, and the required slots left unfilled."""
    design = copy.deepcopy(dict(template.design))
    sx, sy = trim[0] / REFERENCE_TRIM[0], trim[1] / REFERENCE_TRIM[1]
    filled = {index + 1: photo for index, photo in enumerate(photos)}
    missing: list[int] = []
    elements: list[dict[str, object]] = []
    for element in _elements(design):
        needs = element.pop("requires_slot", None)
        if isinstance(needs, int) and needs not in filled:
            continue
        _scale(element, sx, sy, spine_width)
        kind = element.get("type")
        if kind == "photo":
            slot = int(element.pop("slot"))  # type: ignore[call-overload]
            photo = filled.get(slot)
            if photo is not None:
                crop = element.get("crop", {})
                zoom = crop.get("zoom", 1.0) if isinstance(crop, dict) else 1.0
                element["image"] = photo.image.to_dict()
                element["crop"] = {"x": photo.crop.x, "y": photo.crop.y, "zoom": zoom}
            elif template.photo is PhotoNeed.REQUIRED:
                missing.append(slot)
                element = {
                    "id": f"photo-slot-{slot}",
                    "type": "rect",
                    "region": element["region"],
                    **({"box": element["box"]} if "box" in element else {}),
                    "fill": PLACEHOLDER_FILL,
                    "stroke": None,
                    "name": f"Photo placeholder {slot}",
                }
            else:
                continue
        elif kind == "text":
            if "rich" in element:
                rich = _bind_rich(element["rich"], values)  # type: ignore[arg-type]
                if rich is None:
                    continue
                element["rich"] = rich
            else:
                text = _bind(str(element.get("text", "")), values)
                if text is None or not text.strip():
                    continue
                element["text"] = text
        elements.append(element)
    cover: dict[str, object] = {
        "version": 3,
        "type": design.get("type", {}),
        "legibility": design.get("legibility", "none"),
        "spine_text": design.get("spine_text", "auto"),
        "regions": design.get("regions"),
        "elements": elements,
    }
    if design.get("text"):
        cover["text"] = design["text"]
    if template.fonts:
        cover["fonts"] = [font.to_dict() for font in template.fonts]
    return cover, tuple(missing)


# ------------------------------------------------------------------ validation


def _issue(reader: _Reader, path: str, code: str, message: str) -> None:
    reader.issue(path, code, message)


def _bounded_text(reader: _Reader, raw: object, path: str, limit: int, empty: bool = False) -> str:
    if (
        not isinstance(raw, str)
        or (not raw.strip() and not empty)
        or len(raw) > limit
        or any(ord(c) < 32 or ord(c) == 127 for c in raw)
    ):
        reader.issue(path, "text", f"Expected up to {limit} characters on one line.")
        return ""
    return raw.strip()


def _check_bindings(reader: _Reader, text: object, path: str) -> None:
    if not isinstance(text, str):
        return
    for name in BINDING.findall(text):
        if name not in BINDINGS:
            reader.issue(
                path,
                "unknown_binding",
                f"Unknown binding {{{name}}}. Use one of: "
                + ", ".join(f"{{{b}}}" for b in BINDINGS)
                + ".",
            )


def read_template(raw: object, builtin: bool = False) -> CoverTemplate:
    """Validate a template document. Raises TemplateError with every issue found."""
    reader = _Reader()
    data = reader.mapping(raw, "template", TEMPLATE_FIELDS)
    if not isinstance(raw, dict):
        raise TemplateError(
            "template_invalid", "A template is a JSON object.", tuple(reader.issues)
        )
    version = data.get("template_version")
    if type(version) is not int or version not in SUPPORTED_TEMPLATE_VERSIONS:
        raise TemplateError(
            "template_version",
            f"Template version {version!r} is not supported. Supported versions: "
            + ", ".join(str(v) for v in SUPPORTED_TEMPLATE_VERSIONS)
            + ".",
        )
    template_id = data.get("id")
    if (
        not isinstance(template_id, str)
        or len(template_id) > 40
        or not LAYER_ID.fullmatch(template_id)
    ):
        reader.issue("template.id", "id", "Use 1..40 lowercase letters, digits and hyphens.")
        template_id = ""
    name = _bounded_text(reader, data.get("name"), "template.name", MAX_NAME)
    description = _bounded_text(
        reader, data.get("description", ""), "template.description", MAX_DESCRIPTION, empty=True
    )
    category = data.get("category")
    if category not in {c.value for c in TemplateCategory}:
        reader.issue(
            "template.category",
            "choice",
            f"Use one of: {', '.join(c.value for c in TemplateCategory)}.",
        )
        category = TemplateCategory.CUSTOM.value
    photo = data.get("photo")
    if photo not in {p.value for p in PhotoNeed}:
        reader.issue("template.photo", "choice", "Use one of: required, optional, none.")
        photo = PhotoNeed.NONE.value
    palette: list[str] = []
    for index, color in enumerate(
        reader.sequence(data.get("palette", []), "template.palette", MAX_PALETTE, 0)
    ):
        if not isinstance(color, str) or not HEX_COLOR.fullmatch(color):
            reader.issue(f"template.palette.{index}", "color", "Use a #RRGGBB sRGB color.")
        else:
            palette.append(color.lower())
    fonts = _fonts(reader, data.get("fonts", []), "template.fonts")
    if builtin and fonts:
        reader.issue(
            "template.fonts", "builtin_fonts", "Built-in templates use bundled faces only."
        )
    provenance = (
        _bounded_text(reader, data["provenance"], "template.provenance", MAX_DESCRIPTION)
        if "provenance" in data
        else None
    )
    design = reader.mapping(data.get("design"), "template.design", DESIGN_FIELDS)
    if "regions" not in design:
        reader.issue("template.design.regions", "required", "State the three region backgrounds.")
    slots: set[int] = set()
    for index, element in enumerate(_elements(design)):
        path = f"template.design.elements.{index}"
        kind = element.get("type")
        if "requires_slot" in element and element["requires_slot"] not in range(1, MAX_SLOTS + 1):
            reader.issue(f"{path}.requires_slot", "slot", f"Use a slot from 1 to {MAX_SLOTS}.")
        if kind == "photo":
            if "image" in element:
                reader.issue(
                    f"{path}.image",
                    "template_photo",
                    "A template names photo slots, never a project's photograph.",
                )
            slot = element.get("slot")
            if type(slot) is not int or not 1 <= slot <= MAX_SLOTS:
                reader.issue(f"{path}.slot", "slot", f"Use a slot from 1 to {MAX_SLOTS}.")
            else:
                slots.add(slot)
        elif "slot" in element:
            reader.issue(f"{path}.slot", "unknown_field", "Only photo elements have a slot.")
        if kind == "text":
            _check_bindings(reader, element.get("text"), f"{path}.text")
            rich = element.get("rich")
            for b, block in enumerate(rich.get("blocks", []) if isinstance(rich, dict) else []):
                for r, run in enumerate(block.get("runs", []) if isinstance(block, dict) else []):
                    if isinstance(run, dict):
                        _check_bindings(
                            reader, run.get("text"), f"{path}.rich.blocks.{b}.runs.{r}.text"
                        )
        box = element.get("box")
        if (
            isinstance(box, dict)
            and box.get("width") == "spine"
            and element.get("region") != (Region.SPINE.value)
        ):
            reader.issue(f"{path}.box.width", "spine_width", "Only spine boxes follow the spine.")
    if slots and slots != set(range(1, len(slots) + 1)):
        reader.issue("template.design.elements", "slot", "Number photo slots 1, 2, 3 without gaps.")
    if photo == PhotoNeed.NONE.value and slots:
        reader.issue("template.photo", "photo_need", "A template with photo slots needs photos.")
    if photo != PhotoNeed.NONE.value and not slots:
        reader.issue("template.photo", "photo_need", "A template without photo slots needs none.")
    text = design.get("text", {})
    if isinstance(text, dict):
        for role, layer in text.items():
            if isinstance(layer, dict):
                for key in ("text", "visible"):
                    if key in layer:
                        reader.issue(
                            f"template.design.text.{role}.{key}",
                            "book_specific",
                            "A template styles book text; the words and their visibility stay "
                            "with the book.",
                        )
    if reader.issues:
        raise TemplateError("template_invalid", "The template is not valid.", tuple(reader.issues))
    template = CoverTemplate(
        str(template_id),
        name,
        description,
        TemplateCategory(str(category)),
        PhotoNeed(str(photo)),
        copy.deepcopy(dict(design)),
        tuple(palette),
        fonts,
        provenance,
        builtin,
    )
    # The design itself is checked by the cover validator, with every slot and binding filled.
    sample_values = {name: f"Sample {name}" for name in BINDINGS}
    sample_photos = tuple(
        SlotPhoto(CoverImage(_SAMPLE_IMAGE["path"], _SAMPLE_IMAGE["sha256"]), Crop())
        for _ in template.slots()
    )
    cover, _ = instantiate(template, sample_values, sample_photos, _SAMPLE_SPINE)
    _, issues = validate_cover(cover, True)
    if issues:
        mapped = tuple(
            replace(issue, path=issue.path.replace("cover.", "template.design.", 1))
            for issue in issues
        )
        raise TemplateError("template_invalid", "The template design is not valid.", mapped)
    return template


def parse_template(data: bytes, builtin: bool = False) -> CoverTemplate:
    """A template file's bytes: bounded, UTF-8 JSON, then validated. Never executed."""
    if len(data) > MAX_TEMPLATE_BYTES:
        raise TemplateError(
            "template_too_large", f"A template file is at most {MAX_TEMPLATE_BYTES // 1024} KB."
        )
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TemplateError("template_unreadable", f"The template is not JSON: {error}") from error
    return read_template(raw, builtin)


# ------------------------------------------------------------------ application


@dataclass(frozen=True)
class Application:
    cover: CoverConfig
    missing_slots: tuple[int, ...]
    replaced: tuple[str, ...]
    kept: tuple[str, ...]
    font_ids: dict[str, str] = field(default_factory=dict)  # Template font id -> cover id.


def slot_photos(cover: CoverConfig | None) -> tuple[SlotPhoto, ...]:
    """The cover's own photographs in stack order, each once, with its current focal point."""
    if cover is None:
        return ()
    if cover.image is not None:
        return (SlotPhoto(cover.image, cover.crop),)
    seen: dict[str, SlotPhoto] = {}
    for element in cover.elements:
        if isinstance(element, PhotoElement):
            seen.setdefault(element.image.sha256, SlotPhoto(element.image, element.crop))
    return tuple(seen.values())


def _merge_fonts(
    current: tuple[CoverFont, ...], wanted: tuple[CoverFont, ...]
) -> tuple[list[dict[str, object]], dict[str, str]]:
    fonts = [font.to_dict() for font in current]
    by_digest = {font.sha256: font.id for font in current}
    used = {font.id for font in current}
    mapping: dict[str, str] = {}
    for font in wanted:
        if font.sha256 in by_digest:
            mapping[font.id] = by_digest[font.sha256]
            continue
        new_id, n = font.id, 2
        while new_id in used:
            new_id, n = f"{font.id[:36]}-{n}", n + 1
        used.add(new_id)
        mapping[font.id] = new_id
        fonts.append({**font.to_dict(), "id": new_id})
    return fonts, mapping


def _rename_fonts(cover: dict[str, object], mapping: Mapping[str, str]) -> None:
    if not mapping:
        return

    def rename(item: object) -> None:
        if isinstance(item, dict):
            font = item.get("font")
            if isinstance(font, str) and font in mapping:
                item["font"] = mapping[font]
            for value in item.values():
                rename(value)
        elif isinstance(item, list):
            for value in item:
                rename(value)

    rename(cover.get("elements"))
    rename(cover.get("text"))


def apply_template(
    template: CoverTemplate,
    project: Project,
    spine_width: float,
    trim: tuple[float, float] = REFERENCE_TRIM,
) -> Application:
    """The project's cover redesigned with `template`; nothing is saved.

    Book details, display-text overrides and layer visibility, the back-cover
    text, extra text layers, imported fonts and the cover's photographs are kept.
    The design (regions, elements, type preset, legibility, spine setting and text
    styling) comes from the template. Raises TemplateError if the result is invalid.
    """
    current = project.cover
    cover, missing = instantiate(
        template, template_values(project), slot_photos(current), spine_width, trim
    )
    fonts, mapping = _merge_fonts(current.fonts if current else (), template.fonts)
    _rename_fonts(cover, mapping)
    if fonts:
        cover["fonts"] = fonts
    else:
        cover.pop("fonts", None)
    styles = cover.get("text")
    text: dict[str, dict[str, object]] = (
        {str(role): dict(layer) for role, layer in styles.items() if isinstance(layer, dict)}
        if isinstance(styles, dict)
        else {}
    )
    if current is not None:
        for role, layer in current.text:
            kept = {
                key: value
                for key, value in layer.to_dict().items()
                if key == "visible" or (key == "text" and role in METADATA_ROLES)
            }
            if kept:
                text[role.value] = {**text.get(role.value, {}), **kept}
        if current.back_rich is not None or current.back_text is not None:
            cover["back_text"] = (
                current.back_rich.to_dict() if current.back_rich else current.back_text
            )
        if current.extra:
            cover["extra"] = [layer.to_dict() for layer in current.extra]
    if text:
        cover["text"] = text
    else:
        cover.pop("text", None)
    config, issues = validate_cover(cover, project.composition is not None)
    if config is None:
        raise TemplateError(
            "template_not_applicable",
            "The template cannot be applied to this cover.",
            issues,
        )
    replaced = [
        "Region backgrounds for the back, spine and front",
        "Every design layer: photo frames, shapes, lines and text boxes",
        "The type preset, title position, alignment and text tone",
        "Text styling of the title, subtitle, author, back text and imprint",
        "The legibility treatment and the spine text setting",
    ]
    if current is not None and not current.designed:
        replaced.append("The single-photo layout (the cover becomes a region design)")
    kept_items = [
        "The book's title, subtitle, author and imprint (Book details are never changed)",
        "Display-text overrides and hidden layers",
    ]
    if current is not None and current.back_text:
        kept_items.append("Your back-cover text")
    if current is not None and current.extra:
        kept_items.append("Your extra text layers")
    photos = slot_photos(current)
    if photos:
        kept_items.append(
            f"Your photograph{'s' if len(photos) > 1 else ''}, re-placed in the template's frames"
        )
    return Application(config, missing, tuple(replaced), tuple(kept_items), mapping)


# ------------------------------------------------------------------ saving a cover as a template


def _bound_text(text: str, values: Mapping[str, str]) -> str:
    """Book words in a text box become bindings, longest value first."""
    for key, value in sorted(values.items(), key=lambda item: -len(item[1])):
        if key in ("title", "subtitle", "author", "imprint") and len(value) >= 3:
            text = text.replace(value, "{" + key + "}")
    return text


def template_from_cover(
    project: Project,
    template_id: str,
    name: str,
    description: str,
    spine_width: float,
) -> CoverTemplate:
    """The project's cover design as a custom template, without the book's identity.

    Photographs become numbered slots; book words in text boxes become bindings;
    display-text overrides, visibility, back-cover copy and extra layers stay with
    the book. Imported fonts the design uses are listed so applying the template
    can check them (they are project assets: the template is scoped to projects
    that have the same font files).
    """
    from .cover.convert import convert_to_regions

    cover = project.cover
    if cover is None:
        raise TemplateError("no_cover", "This project has no cover to save as a template.")
    designed = cover if cover.designed else convert_to_regions(cover)
    data = designed.to_dict()
    values = template_values(project)
    slots: dict[str, int] = {}
    elements: list[dict[str, object]] = []
    for element, raw in zip(designed.elements, data["elements"], strict=True):  # type: ignore[call-overload]
        item = {k: v for k, v in raw.items() if k not in ("locked",)}
        if isinstance(element, PhotoElement):
            slot = slots.setdefault(element.image.sha256, len(slots) + 1)
            item.pop("image")
            item["slot"] = slot
            item["crop"] = {"zoom": element.crop.zoom}
        elif isinstance(element, TextBoxElement):
            if "rich" in item and is_rich(item["rich"]):
                for block in item["rich"]["blocks"]:
                    for run in block["runs"]:
                        run["text"] = _bound_text(run["text"], values)
            else:
                item["text"] = _bound_text(str(item["text"]), values)
        box = item.get("box")
        if (
            element.region is Region.SPINE
            and isinstance(box, dict)
            and abs(float(box["x"])) < 0.01
            and abs(float(box["width"]) - spine_width) < 0.01
        ):
            box["width"] = "spine"
        elements.append(item)
    styles: dict[str, dict[str, object]] = {}
    for role, layer in designed.text:
        style = {k: v for k, v in layer.to_dict().items() if k not in ("text", "visible")}
        if style:
            styles[role.value] = style
    design: dict[str, object] = {
        "type": data["type"],
        "legibility": data["legibility"],
        "spine_text": data["spine_text"],
        "regions": data["regions"],
        "elements": elements,
    }
    if styles:
        design["text"] = styles
    named = {str(e.get("font")) for e in elements if e.get("font")}
    named |= {str(s["font"]) for s in styles.values() if s.get("font")}
    for element in designed.elements:
        if isinstance(element, TextBoxElement) and element.rich is not None:
            named |= element.rich.fonts()
    fonts = tuple(font for font in designed.fonts if font.id in named)
    palette: list[str] = []
    for color in [designed.regions.back.color, designed.regions.spine.color]:  # type: ignore[union-attr]
        if color not in palette:
            palette.append(color)
    for element in elements:
        for key in ("fill", "color", "stroke"):
            color = element.get(key)
            if isinstance(color, str) and color not in palette and len(palette) < 6:
                palette.append(color)
    raw_template = {
        "template_version": TEMPLATE_VERSION,
        "id": template_id,
        "name": name,
        "description": description,
        "category": TemplateCategory.CUSTOM.value,
        "photo": PhotoNeed.REQUIRED.value if slots else PhotoNeed.NONE.value,
        "palette": palette,
        "design": design,
        "provenance": "Saved from a PuzzlePress cover; photographs and book words removed.",
    }
    if fonts:
        raw_template["fonts"] = [font.to_dict() for font in fonts]
    return read_template(raw_template)
