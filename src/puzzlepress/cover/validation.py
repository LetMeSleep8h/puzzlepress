"""Cover layout contract, restated independently of the layout engine.

Checks wrap arithmetic, bleed coverage, uniform photo placement, safe areas,
spine eligibility and clearance, the barcode area, type sizes and overlaps.
Each issue code is also a cover preflight finding code.
"""

from ..interior.issues import LayoutIssue
from ..interior.model import Box
from ..interior.spec import KDP_COVER, to_inches
from .design import design_issues
from .geometry import CoverGeometry
from .model import CoverLayout, CoverPhoto, CoverText, CoverTextBox
from .watermark import watermark_issues

TOLERANCE = 0.01  # Points, as for interior layout validation.
FRONT_ROLES = ("title", "subtitle", "author")
SPINE_ROLES = ("spine_title", "spine_author")
BACK_ROLES = ("back_text", "imprint")
PANEL_ROLES = {"front": FRONT_ROLES, "spine": SPINE_ROLES, "back": BACK_ROLES}


def _in(points: float) -> str:
    return f"{to_inches(points):.4f} in"


def panel_of(text: CoverText) -> str:
    for panel, roles in PANEL_ROLES.items():
        if text.role in roles:
            return panel
    for panel in ("front", "back"):
        # The author's extra layers (<panel>_extra:<id>) and text boxes (<panel>_element:<id>).
        if text.role.startswith((f"{panel}_extra:", f"{panel}_element:")):
            return panel
    return "unknown"


def wrap_issues(
    geometry: CoverGeometry, trim_width: float, trim_height: float
) -> list[LayoutIssue]:
    """The KDP wrap formula: bleed + back + spine + front + bleed by bleed + trim + bleed."""
    issues: list[LayoutIssue] = []
    bleed = KDP_COVER.bleed
    spine = KDP_COVER.spine_width(geometry.page_count, geometry.paper)
    width = 2 * bleed + 2 * trim_width + spine
    height = 2 * bleed + trim_height
    media = geometry.media
    for name, actual, required in (
        ("width", media.width, width),
        ("height", media.height, height),
        ("spine", geometry.spine_width, spine),
    ):
        if abs(actual - required) > TOLERANCE:
            issues.append(
                LayoutIssue(
                    "invalid_wrap_dimensions",
                    f"The cover {name} does not follow the KDP wrap formula.",
                    region=f"cover.{name}",
                    actual=_in(actual),
                    required=_in(required),
                )
            )
    tiles = (
        (geometry.back.x - media.x, bleed, "left bleed"),
        (geometry.spine.x - geometry.back.right, 0.0, "back/spine fold"),
        (geometry.front.x - geometry.spine.right, 0.0, "spine/front fold"),
        (media.right - geometry.front.right, bleed, "right bleed"),
        (geometry.back.y - media.y, bleed, "bottom bleed"),
        (media.top - geometry.back.top, bleed, "top bleed"),
    )
    for actual, required, name in tiles:
        if abs(actual - required) > TOLERANCE:
            issues.append(
                LayoutIssue(
                    "insufficient_bleed" if "bleed" in name else "invalid_wrap_dimensions",
                    f"The {name} is not where the wrap places it.",
                    region=f"cover.{name.replace(' ', '_')}",
                    actual=_in(actual),
                    required=_in(required),
                )
            )
    return issues


def text_issues(layout: CoverLayout) -> list[LayoutIssue]:
    """Safe areas, spine rules, barcode area and minimum size for every text line."""
    g = layout.geometry
    issues: list[LayoutIssue] = []

    def fail(
        code: str,
        text: CoverText,
        message: str,
        actual: str | None = None,
        required: str | None = None,
    ) -> None:
        issues.append(
            LayoutIssue(
                code, message, region=f"cover.{text.role}", actual=actual, required=required
            )
        )

    for text in layout.texts:
        panel = panel_of(text)
        if text.size < KDP_COVER.min_font_size - 1e-9:
            fail(
                "font_too_small",
                text,
                "Cover text is below the minimum size.",
                actual=f"{text.size:g} pt",
                required=f"{KDP_COVER.min_font_size:g} pt",
            )
        if panel == "spine":
            if not g.spine_text_allowed:
                fail(
                    "spine_text_not_allowed",
                    text,
                    f"KDP prints spine text only on books with at least "
                    f"{KDP_COVER.spine_text_min_pages} pages.",
                    actual=f"{g.page_count} pages",
                    required=f"{KDP_COVER.spine_text_min_pages} pages",
                )
            if not g.spine_safe.contains(text.bounds, TOLERANCE) or not text.rotated:
                fail(
                    "unsafe_spine_text",
                    text,
                    "Spine text must stay 0.0625 in inside each fold and 0.125 in from the trim.",
                )
        elif panel in ("front", "back"):
            safe = g.front_safe if panel == "front" else g.back_safe
            if not safe.contains(text.bounds, TOLERANCE) or text.rotated:
                fail(
                    f"unsafe_{panel}_text",
                    text,
                    f"{panel.capitalize()} cover text must stay 0.125 in inside the trim "
                    "and fold lines.",
                )
            if panel == "back" and text.bounds.overlaps(g.barcode_keep_clear, TOLERANCE):
                fail(
                    "barcode_region_conflict",
                    text,
                    "Text is inside the area reserved for KDP's barcode.",
                )
        else:
            fail("unsafe_front_text", text, "Text has no cover panel.")
    return issues


def validate_cover_layout(
    layout: CoverLayout, trim_width: float, trim_height: float
) -> tuple[LayoutIssue, ...]:
    g = layout.geometry
    issues = wrap_issues(g, trim_width, trim_height) + text_issues(layout)
    if not layout.background.box.contains(g.media, TOLERANCE):
        issues.append(
            LayoutIssue(
                "insufficient_bleed",
                "The background does not reach every bleed edge.",
                region="cover.background",
            )
        )
    for photo in layout.photos:
        issues += _photo_issues(layout, photo)
    if not layout.config.designed:
        photo = layout.photo
        if (
            photo.region.right < g.media.right - TOLERANCE
            or photo.region.top < g.media.top - TOLERANCE
        ):
            issues.append(
                LayoutIssue(
                    "insufficient_bleed",
                    "The photograph stops short of the bleed edge.",
                    region="cover.photo",
                )
            )
    issues += design_issues(layout.stack, g)
    for item in layout.stack:
        if isinstance(item, CoverTextBox):
            lines = [t for t in layout.texts if t.role == item.role]
            if any(not item.box.contains(t.bounds, TOLERANCE) for t in lines):
                issues.append(
                    LayoutIssue(
                        "text_box_overflow",
                        "The text does not fit its box. Enlarge the box, shorten the text or "
                        "set a smaller size; nothing is cut off.",
                        region=f"cover.{item.role}",
                        actual=f"{len(lines)} lines",
                    )
                )
    for panel in layout.panels:
        if not g.media.contains(panel.box, TOLERANCE):
            issues.append(
                LayoutIssue(
                    "photo_placement", "A panel extends past the media box.", region="cover.panel"
                )
            )
    texts = layout.texts
    for index, first in enumerate(texts):
        for second in texts[index + 1 :]:
            if first.bounds.overlaps(second.bounds, TOLERANCE):
                issues.append(
                    LayoutIssue(
                        "text_overlap",
                        f"Cover text {first.role} overlaps {second.role}.",
                        region=f"cover.{first.role}",
                    )
                )
    if layout.watermark is not None:
        issues += watermark_issues(
            layout.watermark,
            g.front_safe,
            tuple(p.region for p in layout.photos),
            tuple((t.role, t.bounds) for t in texts),
        )
    if layout.spine.rendered != any(panel_of(t) == "spine" for t in texts):
        issues.append(
            LayoutIssue(
                "unsafe_spine_text", "Spine status disagrees with spine text.", region="cover.spine"
            )
        )
    return tuple(issues)


def _photo_issues(layout: CoverLayout, photo: CoverPhoto) -> list[LayoutIssue]:
    """A photograph covers its region inside the media box, scaled uniformly."""
    g = layout.geometry
    issues: list[LayoutIssue] = []
    region = f"cover.{photo.role}"
    if not g.media.contains(photo.region, TOLERANCE) or not photo.placement.contains(
        photo.region, TOLERANCE
    ):
        issues.append(
            LayoutIssue(
                "photo_placement",
                "The photograph does not cover its region inside the media box.",
                region=region,
            )
        )
    x0, y0, x1, y1 = photo.pixels
    scale = photo.window.scale
    expected = Box(0, 0, (x1 - x0) * scale, (y1 - y0) * scale)
    if (
        abs(expected.width - photo.placement.width) > TOLERANCE
        or abs(expected.height - photo.placement.height) > TOLERANCE
    ):
        issues.append(
            LayoutIssue("photo_placement", "The photograph is not scaled uniformly.", region=region)
        )
    return issues
