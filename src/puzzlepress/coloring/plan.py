"""A coloring book's publication plan, and its independent verification.

Pages follow the authored order exactly: front matter, then `coloring.pages`
(drawings and section dividers), then back matter. Blank pages are inserted only
to satisfy the stated parity, and every one is an explicit plan page with a reason:

- `section_recto_start`: the artwork section starts on a right-hand page;
- `artwork_recto_start` / `divider_recto_start`: a single-sided coloring page, or
  any divider, starts on a right-hand page;
- `reverse_blank`: the blank back of a single-sided coloring page or divider.

With blank reverse pages on (the default), every coloring page is a right-hand
(odd) page backed by a blank. Dividers always start on a right-hand page, and with
blank reverses take one too. Physical page numbers count every page; whether a
number is printed is the composition's page-number policy, and blanks and
dividers never print one.

The verifier restates these rules against the source and the prepared content
rather than re-running the planner, so a planner defect cannot certify itself.
"""

from collections.abc import Callable
from dataclasses import dataclass

from ..composition import Composition, MatterItem, MatterKind, NumberingScheme, SectionStart
from ..engines.kind import EngineKind
from ..errors import ProjectError, ValidationIssue
from ..identity import build_identity
from ..models import Project
from ..publication import (
    ARTWORK_BLANK_REASON,
    BLANK_REASON,
    DIVIDER_BLANK_REASON,
    PLAN_VERSION,
    REVERSE_BLANK_REASON,
    ArtworkRef,
    DividerContent,
    MatterContent,
    NumberStyle,
    PageKind,
    PageNumber,
    PlanPage,
    PublicationPlan,
    Section,
    plan_statistics,
)
from ..publication_verification import PlanVerification
from .content import ColoringContent

_ORDER = (Section.FRONT_MATTER, Section.ARTWORK, Section.BACK_MATTER)
_RECTO_REASONS = (BLANK_REASON, ARTWORK_BLANK_REASON, DIVIDER_BLANK_REASON)


def require_coloring_composition(project: Project) -> Composition:
    """The coloring composition, or an expected, actionable error."""
    composition = project.composition
    if project.coloring is None or composition is None or composition.artwork is None:
        raise ProjectError(
            (
                ValidationIssue(
                    "composition",
                    "required",
                    "This coloring book has no composition. Add one, for example "
                    "composition: {front_matter: [{kind: title_page}], artwork: {start: "
                    "recto}}, to choose its front matter, page numbers and back matter.",
                ),
            )
        )
    return composition


def _matter(item: MatterItem, project: Project) -> MatterContent:
    if item.kind is MatterKind.TITLE_PAGE:
        book = project.book
        return MatterContent(book.title, book.subtitle, book.author, book.imprint)
    return MatterContent(title=item.title, text=item.text)


@dataclass(frozen=True)
class _Slot:
    section: Section
    kind: PageKind
    matter: MatterContent | None = None
    divider: DividerContent | None = None
    artwork: ArtworkRef | None = None
    blank_reason: str | None = None
    blank_before: Section | None = None


def plan_coloring(project: Project, content: ColoringContent) -> PublicationPlan:
    """Plan validated source with the content prepared from that same source."""
    composition = require_coloring_composition(project)
    book = project.coloring
    assert book is not None and composition.artwork is not None
    identity = build_identity(project)
    if content.identity != identity:
        raise ValueError("Prepared content was not made from this project source")
    reverse = book.layout.blank_reverse
    slots: list[_Slot] = []

    def recto(reason: str, before: Section) -> None:
        if len(slots) % 2 == 1:  # The next page would be a left-hand page.
            section = slots[-1].section if slots else before
            slots.append(_Slot(section, PageKind.BLANK, blank_reason=reason, blank_before=before))

    def backed() -> None:
        if reverse:
            slots.append(_Slot(Section.ARTWORK, PageKind.BLANK, blank_reason=REVERSE_BLANK_REASON))

    for item in composition.front_matter:
        slots.append(
            _Slot(Section.FRONT_MATTER, PageKind(item.kind.value), matter=_matter(item, project))
        )
    if composition.artwork.start is SectionStart.RECTO and book.pages:
        recto(BLANK_REASON, Section.ARTWORK)
    diagnostics: list[ValidationIssue] = []
    ordinal = 0
    for entry, page in enumerate(book.pages, start=1):
        if page.divider is not None:
            recto(DIVIDER_BLANK_REASON, Section.ARTWORK)
            title = page.divider.title
            slots.append(
                _Slot(
                    Section.ARTWORK,
                    PageKind.DIVIDER,
                    divider=DividerContent(title, title, page.divider.text),
                )
            )
            backed()
            continue
        assert page.artwork is not None
        artwork = book.artwork_by_id(page.artwork)
        assert artwork is not None  # Validation guarantees known artwork.
        ordinal += 1
        prepared = content.art.get(artwork.id)
        if prepared is None:
            failure = content.failures.get(artwork.id)
            diagnostics.append(
                ValidationIssue(
                    f"coloring.pages.{entry - 1}",
                    "artwork_unavailable",
                    f"Artwork {artwork.id} cannot be printed: "
                    f"{failure.message if failure else 'it was not prepared.'}",
                )
            )
        ref = ArtworkRef(
            artwork.id,
            ordinal,
            entry,
            artwork.title,
            artwork.sha256,
            prepared.digest if prepared else "",
        )
        if reverse:
            recto(ARTWORK_BLANK_REASON, Section.ARTWORK)
        slots.append(_Slot(Section.ARTWORK, PageKind.COLORING, artwork=ref))
        backed()
    if not ordinal:
        diagnostics.append(
            ValidationIssue(
                "coloring.pages",
                "no_coloring_pages",
                "The book has no coloring pages. Import artwork and add it to the pages.",
            )
        )
    for item in composition.back_matter:
        slots.append(
            _Slot(Section.BACK_MATTER, PageKind(item.kind.value), matter=_matter(item, project))
        )

    numbers = composition.page_numbers
    roman_front = numbers.scheme is NumberingScheme.ROMAN_FRONT_MATTER
    front_count = sum(slot.section is Section.FRONT_MATTER for slot in slots)
    shown = {
        Section.FRONT_MATTER: numbers.show_front_matter,
        Section.ARTWORK: bool(numbers.show_artwork),
        Section.BACK_MATTER: numbers.show_back_matter,
    }
    pages: list[PlanPage] = []
    for index, slot in enumerate(slots, start=1):
        in_front = slot.section is Section.FRONT_MATTER
        pages.append(
            PlanPage(
                index=index,
                section=slot.section,
                kind=slot.kind,
                number=PageNumber(
                    index - front_count if roman_front and not in_front else index,
                    NumberStyle.ROMAN if roman_front and in_front else NumberStyle.ARABIC,
                    slot.kind not in (PageKind.BLANK, PageKind.DIVIDER) and shown[slot.section],
                ),
                matter=slot.matter,
                blank_reason=slot.blank_reason,
                blank_before=slot.blank_before,
                divider=slot.divider,
                artwork=slot.artwork,
            )
        )
    frozen = tuple(pages)
    return PublicationPlan(
        identity,
        project.book.id,
        project.book.language,
        frozen,
        plan_statistics(frozen),
        tuple(diagnostics),
        engine=EngineKind.COLORING,
    )


_Fail = Callable[[str, str, str], None]


def verify_coloring_plan(
    plan: PublicationPlan, project: Project, content: ColoringContent
) -> PlanVerification:
    """Check a coloring plan's invariants against the source and prepared content."""
    issues: list[ValidationIssue] = []

    def fail(path: str, code: str, message: str) -> None:
        issues.append(ValidationIssue(path, code, message))

    composition, book = project.composition, project.coloring
    if book is None or composition is None or composition.artwork is None:
        fail("plan", "source", "Source has no coloring composition.")
        return PlanVerification(tuple(issues))
    identity = build_identity(project)
    if plan.plan_version != PLAN_VERSION or plan.engine is not EngineKind.COLORING:
        fail("plan_version", "version", "Not a supported coloring plan.")
    if plan.identity != identity or content.identity != identity:
        fail("identity", "identity", "Plan, prepared content and source identities differ.")
    if (plan.book_id, plan.language) != (project.book.id, project.book.language):
        fail("book_id", "book", "Plan book does not match source.")
    pages = plan.pages
    if not pages:
        if book.pages or composition.front_matter or composition.back_matter:
            fail("pages", "empty", "The source has pages the plan lacks.")
        return PlanVerification(tuple(issues))
    reverse = book.layout.blank_reverse
    for position, page in enumerate(pages):
        path = f"pages.{position}"
        if page.index != position + 1:
            fail(f"{path}.index", "order", "Logical indexes must be contiguous from 1.")
        if page.section not in _ORDER:
            fail(f"{path}.section", "section", "Coloring plans have no puzzle sections.")
        elif position and pages[position - 1].section in _ORDER:
            if _ORDER.index(page.section) < _ORDER.index(pages[position - 1].section):
                fail(f"{path}.section", "order", "Sections are out of reading order.")
        if page.puzzle is not None or page.solutions or page.solution_page is not None:
            fail(path, "content", "Coloring plans reference no puzzles or solutions.")
        _check_page(page, path, fail, reverse, pages)
    _check_sequence(plan, project, content, fail)
    _check_numbers(plan, composition, fail)
    return PlanVerification(tuple(issues))


def _check_page(
    page: PlanPage, path: str, fail: _Fail, reverse: bool, pages: tuple[PlanPage, ...]
) -> None:
    recto = page.index % 2 == 1
    following = pages[page.index] if page.index < len(pages) else None
    previous = pages[page.index - 2] if page.index > 1 else None
    if page.kind is PageKind.BLANK:
        if page.matter or page.divider or page.artwork:
            fail(path, "blank_content", "Blank pages carry no content.")
        if page.number.displayed:
            fail(f"{path}.number", "folio", "Blank pages print no page number.")
        if page.blank_reason == REVERSE_BLANK_REASON:
            if not reverse:
                fail(path, "reverse_blank", "Blank reverse pages are turned off for this book.")
            if previous is None or previous.kind not in (PageKind.COLORING, PageKind.DIVIDER):
                fail(path, "reverse_blank", "A reverse blank must follow its coloring page.")
            if recto:
                fail(path, "parity", "A reverse blank is the back of a right-hand page.")
        elif page.blank_reason in _RECTO_REASONS:
            if recto or following is None or following.kind is PageKind.BLANK:
                fail(path, "parity", "A recto-start blank must precede a right-hand page.")
        else:
            fail(f"{path}.blank_reason", "blank_reason", "Unknown blank page reason.")
    elif page.kind is PageKind.COLORING:
        if page.artwork is None or page.section is not Section.ARTWORK:
            fail(path, "artwork", "Coloring pages reference one drawing in the artwork section.")
        if reverse:
            if not recto:
                fail(path, "parity", "Single-sided coloring pages are right-hand pages.")
            if following is None or following.blank_reason != REVERSE_BLANK_REASON:
                fail(path, "reverse_blank", "A single-sided coloring page needs its blank back.")
    elif page.kind is PageKind.DIVIDER:
        if page.divider is None or page.section is not Section.ARTWORK:
            fail(path, "divider", "Divider pages carry their authored title.")
        if not recto:
            fail(path, "parity", "Section dividers start on a right-hand page.")
        if reverse and (following is None or following.blank_reason != REVERSE_BLANK_REASON):
            fail(path, "reverse_blank", "A divider takes a blank back when reverses are on.")
    elif page.artwork is not None or page.divider is not None:
        fail(path, "content", "Matter pages carry no artwork or divider.")


def _check_sequence(
    plan: PublicationPlan, project: Project, content: ColoringContent, fail: _Fail
) -> None:
    composition, book = project.composition, project.coloring
    assert composition is not None and book is not None and composition.artwork is not None
    front = [
        p for p in plan.pages if p.section is Section.FRONT_MATTER and p.kind is not PageKind.BLANK
    ]
    back = [
        p for p in plan.pages if p.section is Section.BACK_MATTER and p.kind is not PageKind.BLANK
    ]
    for name, planned, authored in (
        ("front_matter", front, composition.front_matter),
        ("back_matter", back, composition.back_matter),
    ):
        if [p.kind.value for p in planned] != [item.kind.value for item in authored]:
            fail(name, "matter", f"Planned {name.replace('_', ' ')} differs from the source.")
        for page, item in zip(planned, authored, strict=False):
            matter = page.matter
            expected = _matter(item, project)
            if matter != expected:
                fail(f"pages.{page.index - 1}.matter", "matter", "Matter text differs from source.")
    body = [p for p in plan.pages if p.section is Section.ARTWORK and p.kind is not PageKind.BLANK]
    if len(body) != len(book.pages):
        fail("pages", "artwork_order", "Planned coloring pages differ from coloring.pages.")
        return
    ordinal = 0
    for page, entry in zip(body, book.pages, strict=True):
        path = f"pages.{page.index - 1}"
        if entry.divider is not None:
            divider = page.divider
            if (
                page.kind is not PageKind.DIVIDER
                or divider is None
                or (divider.title, divider.text) != (entry.divider.title, entry.divider.text)
            ):
                fail(path, "artwork_order", "A divider differs from its authored entry.")
            continue
        ordinal += 1
        ref = page.artwork
        artwork = book.artwork_by_id(entry.artwork or "")
        if page.kind is not PageKind.COLORING or ref is None or artwork is None:
            fail(path, "artwork_order", "A coloring page differs from its authored entry.")
            continue
        prepared = content.art.get(artwork.id)
        if (ref.id, ref.ordinal, ref.title, ref.source) != (
            artwork.id,
            ordinal,
            artwork.title,
            artwork.sha256,
        ):
            fail(path, "artwork_ref", "Coloring page reference differs from its artwork.")
        if ref.prepared != (prepared.digest if prepared else ""):
            fail(path, "prepared_digest", "Coloring page does not name the prepared pixels.")
    if composition.artwork.start is SectionStart.RECTO and body and body[0].index % 2 == 0:
        fail(f"pages.{body[0].index - 1}", "parity", "The artwork section starts on the right.")


def _check_numbers(plan: PublicationPlan, composition: Composition, fail: _Fail) -> None:
    numbers = composition.page_numbers
    roman = numbers.scheme is NumberingScheme.ROMAN_FRONT_MATTER
    front_count = sum(p.section is Section.FRONT_MATTER for p in plan.pages)
    shown = {
        Section.FRONT_MATTER: numbers.show_front_matter,
        Section.ARTWORK: bool(numbers.show_artwork),
        Section.BACK_MATTER: numbers.show_back_matter,
    }
    for page in plan.pages:
        in_front = page.section is Section.FRONT_MATTER
        value = page.index - front_count if roman and not in_front else page.index
        style = NumberStyle.ROMAN if roman and in_front else NumberStyle.ARABIC
        displayed = page.kind not in (PageKind.BLANK, PageKind.DIVIDER) and shown.get(
            page.section, False
        )
        if (page.number.value, page.number.style, page.number.displayed) != (
            value,
            style,
            displayed,
        ):
            fail(f"pages.{page.index - 1}.number", "folio", "Page number differs from policy.")
