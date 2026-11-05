"""Read-only, root-scoped project access and presentation of core reports."""

import hashlib
import re
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from puzzlepress import __version__
from puzzlepress.batch import generate_batch
from puzzlepress.engines.kind import LABELS
from puzzlepress.engines.registry import engine_for
from puzzlepress.errors import ProjectError, ValidationIssue
from puzzlepress.identity import build_identity
from puzzlepress.models import Project
from puzzlepress.project import resolve_output_directory
from puzzlepress.wordsearch import verify_word_search
from puzzlepress.yaml_io import parse_project


class StudioError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        super().__init__(message)


def issue_dicts(error: ProjectError) -> list[dict[str, object]]:
    # Filesystem failures may contain absolute paths; keep those in server diagnostics.
    return [
        asdict(ValidationIssue(issue.path, issue.code, "Cannot read project source."))
        if issue.code in {"io", "not_found", "not_directory"}
        else asdict(issue)
        for issue in error.issues
    ]


@dataclass(frozen=True)
class ProjectStore:
    root: Path

    def source(self, key: str) -> Path:
        # Keys identify immediate folders, independently of authored book IDs.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", key):
            raise StudioError(404, "project_not_found", "Project not found in the book library.")
        try:
            root = self.root.resolve()
            folder = root / key
            source = folder / "book.yaml"
            resolved_folder = folder.resolve()
            resolved_source = source.resolve()
            if (
                resolved_folder.parent != root
                or resolved_source.parent != resolved_folder
                or folder.is_symlink()
                or source.is_symlink()
            ):
                raise StudioError(404, "project_not_found", "Project is outside the book library.")
            if not resolved_source.is_file():
                raise StudioError(
                    404, "project_not_found", "Project not found in the book library."
                )
            return resolved_source
        except (OSError, RuntimeError, ValueError) as error:
            raise StudioError(503, "source_unavailable", "Cannot access project source.") from error

    def load(self, key: str) -> Project:
        return self.snapshot(key)[0]

    def snapshot(self, key: str) -> tuple[Project, str]:
        path = self.source(key)
        try:
            raw = path.read_bytes()
            project = parse_project(raw.decode("utf-8-sig"))
        except (OSError, UnicodeError) as error:
            raise ProjectError(
                (ValidationIssue("source", "io", "Cannot read project source."),)
            ) from error
        resolve_output_directory(project, path.parent)
        return project, "sha256-" + hashlib.sha256(raw).hexdigest()

    def detail(self, key: str) -> dict[str, object]:
        project, revision = self.snapshot(key)
        return project_detail(key, project, revision)

    def discover(self) -> list[dict[str, object]]:
        if not self.root.exists():
            raise StudioError(
                503, "library_unavailable", "The configured books directory is missing."
            )
        try:
            keys = sorted(p.name for p in self.root.iterdir() if p.is_dir())
        except OSError as error:
            raise StudioError(
                503, "library_unavailable", "Cannot read the books directory."
            ) from error
        projects: list[dict[str, object]] = []
        for key in keys:
            try:
                projects.append(self.detail(key))
            except StudioError as error:
                if error.status != 404:
                    raise
            except ProjectError as error:
                projects.append(
                    {"key": key, "validation": {"valid": False, "issues": issue_dicts(error)}}
                )
        return projects


def engine_summary(project: Project) -> dict[str, str]:
    """The derived book type, named by the engine that builds it."""
    return {"kind": project.engine.value, "label": LABELS[project.engine]}


def project_detail(key: str, project: Project, revision: str | None = None) -> dict[str, object]:
    source = project.to_dict()
    source["build"] = {"seed": str(project.build.seed)}
    return {
        "key": key,
        "revision": revision,
        "source": source,
        "identity": build_identity(project),
        "engine_version": __version__,
        "engine": engine_summary(project),
        "validation": {"valid": True, "issues": []},
    }


class StudioService:
    """Serialize expensive requests; never cache stale authored source or write it."""

    def __init__(self, store: ProjectStore) -> None:
        self.store = store
        self._generation_lock = Lock()

    def generate(self, key: str, identity: str) -> dict[str, object]:
        project = self.store.load(key)
        if build_identity(project) != identity:
            raise StudioError(
                409, "source_changed", "Source changed. Reload the project before generating."
            )
        return self.generate_project(project)

    @contextmanager
    def exclusive(self, wait: float = 0) -> Iterator[None]:
        """Run alone. Drafts fail fast when busy; print reads may `wait` seconds."""
        acquired = (
            self._generation_lock.acquire(timeout=wait)
            if wait > 0
            else self._generation_lock.acquire(blocking=False)
        )
        if not acquired:
            raise StudioError(409, "generation_busy", "Generation is running. Try again shortly.")
        try:
            yield
        finally:
            self._generation_lock.release()

    def plan_project(self, project: Project, source: Path | None = None) -> dict[str, object]:
        """Generate (or prepare) and plan the given source; the verified plan is the result.

        `source` is the project folder, where a coloring book's artwork lives.
        """
        with self.exclusive():
            if project.composition is None:
                raise StudioError(422, "no_composition", "This project has no book composition.")
            engine = engine_for(project)
            content, plan = engine.build_publication(project, source)
            verification = engine.verify_publication(plan, project, content)
            if project.coloring is not None:
                # An incomplete coloring plan (no pages yet, a drawing that cannot be
                # read) is reported with its issues, so the composer can show them.
                payload = engine.payload(content, plan, verification)
                pages = getattr(plan, "pages", ())
                count = len(pages) if isinstance(pages, tuple | list) else 0
                return {
                    **payload,
                    "geometry": coloring_page_geometry(project, count),
                    "placements": coloring_placements(project, content, plan),
                }
            if not verification.valid:
                raise RuntimeError(f"Publication plan failed verification: {verification.issues!r}")
            return engine.payload(content, plan, verification)

    def generate_project(self, project: Project) -> dict[str, object]:
        with self.exclusive():
            if project.word_search is None:
                raise StudioError(422, "no_puzzles", "This project has no word-search definitions.")
            report = generate_batch(project)
            verification: dict[str, object] = {}
            for result in report.puzzles:
                if result.puzzle is None:
                    verification[result.id] = None
                else:
                    checked = verify_word_search(result.puzzle)
                    verification[result.id] = {"valid": checked.valid, **asdict(checked)}
            # Keep the CLI report intact; add independently verified web presentation data.
            return {
                "report": report.to_dict(),
                "verification": verification,
                "solution_cells": {
                    result.id: {
                        placement.target_id: [asdict(cell) for cell in placement.coordinates]
                        for placement in result.puzzle.solution.placements
                    }
                    for result in report.puzzles
                    if result.puzzle
                },
            }


def coloring_page_geometry(project: Project, page_count: int = 0) -> dict[str, object]:
    """Media, trim, live area, art box, fill area and KDP safe area (PDF points, origin
    at the media box's bottom-left) of a recto and a verso coloring page under the
    book's print profile (the default when it has none): what the composer outlines on
    its page previews. Without bleed the media box is the trim. Python's layout
    geometry; the browser only draws it."""
    from puzzlepress.coloring_config import Border
    from puzzlepress.interior import DEFAULT_PROFILE, print_profile
    from puzzlepress.interior.coloring import art_box, fill_box
    from puzzlepress.interior.engine import FOLIO_BAND
    from puzzlepress.interior.geometry import page_frame
    from puzzlepress.interior.model import Box
    from puzzlepress.interior.spec import KDP, PrintSpecification
    from puzzlepress.preflight.rules import kdp_safe_area

    spec = print_profile(project.printing.profile if project.printing else DEFAULT_PROFILE)
    assert isinstance(spec, PrintSpecification)
    border = project.coloring.layout.border if project.coloring else Border.NONE

    def box(value: Box) -> dict[str, float]:
        return {k: round(getattr(value, k), 3) for k in ("x", "y", "width", "height")}

    sides: dict[str, object] = {}
    for side, number in (("recto", 1), ("verso", 2)):
        frame = page_frame(spec, number)
        content = frame.content
        body = Box(content.x, content.y + FOLIO_BAND, content.width, content.height - FOLIO_BAND)
        safe = kdp_safe_area(spec, max(page_count, KDP.min_pages), frame.recto, frame.trim)
        sides[side] = {
            "media": box(frame.media),
            "trim_box": box(frame.trim),
            "live": box(content),
            "art": box(art_box(body, border)),
            "fill": box(fill_box(frame, spec)) if spec.bleed else None,
            "safe": box(safe) if safe else None,
        }
    return {
        "profile": spec.profile_id,
        "bleed": spec.bleed,
        "trim": {"width": spec.trim.width, "height": spec.trim.height},
        "media": {
            "width": spec.trim.width + (KDP.interior_bleed if spec.bleed else 0.0),
            "height": spec.trim.height + (2 * KDP.interior_bleed if spec.bleed else 0.0),
        },
        "border": border.value,
        "sides": sides,
    }


# Crop measures by prepared-pixel digest and exact page boxes: a draft plan re-measures
# only pages whose drawing or placement changed (bounded; identical inputs, identical
# result).
_CROPS: OrderedDict[tuple[object, ...], dict[str, object]] = OrderedDict()
_CROP_ENTRIES = 1024


def _crop(prepared: Any, block: Any, trim: Any, safe: Any) -> dict[str, object]:
    from puzzlepress.interior.coloring import bleed_crop

    def key_of(box: Any) -> tuple[float, ...]:
        return (box.x, box.y, box.width, box.height)

    key = (prepared.digest, key_of(block.box), key_of(block.placement), key_of(trim), key_of(safe))
    known = _CROPS.get(key)
    if known is None:
        known = bleed_crop(prepared.image(), block, trim, safe).to_dict()
        _CROPS[key] = known
        while len(_CROPS) > _CROP_ENTRIES:
            _CROPS.popitem(last=False)
    else:
        _CROPS.move_to_end(key)
    return dict(known)


def _points(box: object) -> dict[str, float]:
    return {k: round(getattr(box, k), 3) for k in ("x", "y", "width", "height")}


def coloring_placements(project: Project, content: object, plan: object) -> dict[str, object]:
    """Where each coloring page of a draft plan prints its drawing (PDF points, origin
    bottom-left) and at what effective DPI, by physical page: computed by the same
    `place_art` / `place_fill` the interior layout uses, from the prepared pixel size.

    A drawing that fills a full-bleed page reports its printed area (`box`, the fill
    area it is clipped to), its whole extent (`drawing`) and `crop`: the shares of its
    line work cut off the page, printed only in the bleed, and outside the safe area,
    measured by the preflight rule's own `bleed_crop`. Fill on a profile without bleed
    reports `error` and no box: the build refuses it, so nothing is drawn as if it
    printed."""
    from puzzlepress.coloring.content import ColoringContent
    from puzzlepress.coloring_config import CENTRED, Border, Fit
    from puzzlepress.interior import DEFAULT_PROFILE, print_profile
    from puzzlepress.interior.coloring import (
        art_box,
        fill_box,
        place_art,
        place_fill,
    )
    from puzzlepress.interior.engine import FOLIO_BAND
    from puzzlepress.interior.geometry import page_frame
    from puzzlepress.interior.model import Box, ImageBlock, ImageEncoding
    from puzzlepress.interior.spec import PrintSpecification
    from puzzlepress.preflight.rules import kdp_safe_area
    from puzzlepress.publication import PageKind, PublicationPlan

    if not isinstance(content, ColoringContent) or not isinstance(plan, PublicationPlan):
        return {}
    profile = project.printing.profile if project.printing else DEFAULT_PROFILE
    spec = print_profile(profile)
    assert isinstance(spec, PrintSpecification)
    book = project.coloring
    border = book.layout.border if book else Border.NONE
    placements = book.placements if book else {}
    result: dict[str, object] = {}
    for page in plan.pages:
        ref = page.artwork
        prepared = content.art.get(ref.id) if ref else None
        if page.kind is not PageKind.COLORING or ref is None or prepared is None:
            continue
        page_box = page_frame(spec, page.index)
        frame = page_box.content
        body = Box(frame.x, frame.y + FOLIO_BAND, frame.width, frame.height - FOLIO_BAND)
        authored = placements.get(ref.entry, CENTRED)
        record: dict[str, object] = {
            "entry": ref.entry,
            "fit": authored.fit.value,
            "pixels": {"width": prepared.width, "height": prepared.height},
            "placement": authored.to_dict(),
        }
        if authored.fit is Fit.FILL and not spec.bleed:
            record["error"] = "fill_needs_bleed"
        elif authored.fit is Fit.FILL:
            clip = fill_box(page_box, spec)
            drawing, dpi = place_fill(clip, prepared.width, prepared.height, authored)
            safe = kdp_safe_area(spec, len(plan.pages), page_box.recto, page_box.trim)
            block = ImageBlock(
                "coloring_art",
                clip,
                prepared.digest,
                drawing,
                (0, 0, prepared.width, prepared.height),
                dpi,
                dpi,
                ImageEncoding.LOSSLESS,
                bleed=True,
            )
            record.update(
                box=_points(clip),
                drawing=_points(drawing),
                effective_dpi=round(dpi, 1),
                crop=_crop(prepared, block, page_box.trim, safe) if safe else None,
            )
        else:
            box, dpi = place_art(art_box(body, border), prepared.width, prepared.height, authored)
            record.update(box=_points(box), effective_dpi=round(dpi, 1))
        result[str(page.index)] = record
    return result
