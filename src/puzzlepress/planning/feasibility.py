"""Can the current PuzzlePress produce this plan? Each answer says how it is known.

- verified: decided by the engine's own rules or a current cap (a word fits a
  grid or it does not; 120 puzzles exceed a 100-puzzle cap).
- estimate: computed from the plan, not from a built book (page counts before a
  publication plan exists; a grid that fits the page before its title and word
  list are laid out).
- unknown: cannot be known until production (whether placement succeeds for
  every puzzle, the exact page count, cover geometry).
- unsupported: the current engine cannot produce it.

Print checks reuse the interior's geometry functions with a region larger than
any real one, so a failure there is certain and a pass is only an estimate.
Exact page counts, layout and KDP verdicts belong to the publication plan,
interior build and preflight; nothing here duplicates them.
"""

import math
from dataclasses import dataclass

from ..content import MAX_BANK_ENTRIES, MAX_BANKS, MAX_PROFILES, MAX_PUZZLE_TARGETS, MAX_PUZZLES
from ..interior.engine import SOLUTION_GAP_X, SOLUTION_GAP_Y
from ..interior.geometry import fit_grid, max_cell_for_letter, page_frame, solution_slots
from ..interior.spec import DEFAULT_PROFILE, KDP, KDP_COVER, PROFILES, PrintSpecification
from ..wordsearch import Target, WordSearchError
from ..wordsearch.validation import validate_fit
from .analysis import PlanAnalysis
from .model import SolutionsPlan

SUPPORTED_PUZZLE_TYPES = ("word_search",)


@dataclass(frozen=True)
class Item:
    code: str
    label: str
    status: str  # verified | estimate | unknown | unsupported
    detail: str
    actual: int | str | None = None
    limit: int | str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "actual": self.actual,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class PageEstimate:
    minimum: int | None
    maximum: int | None  # None when a part of the book is not planned yet.
    parts: dict[str, int | None]

    def to_dict(self) -> dict[str, object]:
        return {"minimum": self.minimum, "maximum": self.maximum, "parts": dict(self.parts)}


def page_estimate(analysis: PlanAnalysis) -> PageEstimate:
    """Logical pages: one per puzzle, grouped solution pages, matter, recto blanks.

    The publication plan is authoritative; this mirrors its page rules only to
    bound the count before one exists. At most one blank precedes the puzzles
    and one the solutions when those sections start on a recto.
    """
    s = analysis.doc.structure
    target = s.target_puzzles
    if s.solutions is SolutionsPlan.OMIT:
        solutions: int | None = 0
    elif s.solutions is SolutionsPlan.END and s.solutions_per_page and target is not None:
        solutions = math.ceil(target / s.solutions_per_page)
    else:
        solutions = None
    parts: dict[str, int | None] = {
        "puzzles": target,
        "solutions": solutions,
        "front_matter": s.front_matter_pages,
        "back_matter": s.back_matter_pages,
    }
    if target is None:
        return PageEstimate(None, None, parts)
    known = sum(v for v in parts.values() if v is not None)
    blanks = 1 + (1 if s.solutions is SolutionsPlan.END else 0)
    maximum = known + blanks if all(v is not None for v in parts.values()) else None
    return PageEstimate(known, maximum, parts)


class Feasibility:
    def __init__(self, analysis: PlanAnalysis) -> None:
        self.analysis = analysis
        self.items: list[Item] = []
        self.estimate = page_estimate(analysis)
        self._run()

    def item(
        self,
        code: str,
        label: str,
        status: str,
        detail: str,
        actual: int | str | None = None,
        limit: int | str | None = None,
    ) -> None:
        self.items.append(Item(code, label, status, detail, actual, limit))

    def _spec(self) -> tuple[PrintSpecification, bool]:
        """The chosen profile, or the default geometry (both profiles share it) as assumed."""
        chosen = self.analysis.doc.structure.print_profile
        if chosen in PROFILES:
            return PROFILES[chosen], True
        return PROFILES[DEFAULT_PROFILE], False

    def _run(self) -> None:
        a = self.analysis
        add = a.findings.add
        doc = a.doc
        s = doc.structure
        # Puzzle type.
        if s.puzzle_type is None:
            self.item("puzzle_type", "Puzzle type", "unknown", "Not stated yet.")
        elif s.puzzle_type in SUPPORTED_PUZZLE_TYPES:
            self.item("puzzle_type", "Puzzle type", "verified", "Word searches are supported.",
                      s.puzzle_type)  # fmt: skip
        else:
            self.item("puzzle_type", "Puzzle type", "unsupported",
                      "PuzzlePress generates word searches only.", s.puzzle_type)  # fmt: skip
            add(
                "puzzle_type_unsupported",
                f"Puzzle type {s.puzzle_type!r} is not supported; only word_search is.",
                path="structure.puzzle_type",
                actual=s.puzzle_type,
                expected="word_search",
            )
        # Puzzle count against the project cap.
        target = s.target_puzzles
        if target is None:
            self.item("puzzle_count", "Puzzle count", "unknown", "No target yet.",
                      limit=MAX_PUZZLES)  # fmt: skip
        elif target <= MAX_PUZZLES:
            self.item("puzzle_count", "Puzzle count", "verified",
                      f"Within the project cap of {MAX_PUZZLES} puzzles.", target,
                      MAX_PUZZLES)  # fmt: skip
        else:
            self.item(
                "puzzle_count",
                "Puzzle count",
                "unsupported",
                f"A project holds at most {MAX_PUZZLES} puzzle definitions today. The plan "
                "may describe a larger book; producing it needs the cap reviewed first "
                "(docs/book-planning.md#generator-limits).",
                target,
                MAX_PUZZLES,
            )
            add(
                "puzzle_count_unsupported",
                f"{target} planned puzzles exceed the current cap of {MAX_PUZZLES} a project.",
                path="structure.target_puzzles",
                actual=target,
                expected=f"at most {MAX_PUZZLES}",
                action="Keep the target as a plan, but production needs the cap reviewed "
                "(Interval 12) or a smaller book.",
            )
        # Banks and profiles.
        used = [
            info for info in a.pools
            if info.pool.theme in a.themes
            and (a.allocation(a.themes[info.pool.theme]) or a.specified(info.pool.theme))
        ]  # fmt: skip
        if len(used) > MAX_BANKS:
            self.item("word_banks", "Word banks", "unsupported",
                      f"Each theme pool becomes one word bank; a project holds {MAX_BANKS}.",
                      len(used), MAX_BANKS)  # fmt: skip
            add("bank_count_unsupported",
                f"{len(used)} theme pools would need {len(used)} word banks; the cap is "
                f"{MAX_BANKS}.", path="vocabulary", actual=len(used),
                expected=f"at most {MAX_BANKS}")  # fmt: skip
        else:
            self.item("word_banks", "Word banks", "verified",
                      "Each theme pool can become one word bank.", len(used),
                      MAX_BANKS)  # fmt: skip
        for info in used:
            if len(info.forms) > MAX_BANK_ENTRIES:
                add(
                    "bank_size_exceeds",
                    f"Pool {info.pool.theme} has {len(info.forms)} usable words; one word bank "
                    f"holds {MAX_BANK_ENTRIES}. Select or split before production.",
                    path=info.path,
                    actual=len(info.forms),
                    expected=f"at most {MAX_BANK_ENTRIES}",
                    subjects=(info.pool.theme,),
                )
        levels = a.levels
        if len(levels) > MAX_PROFILES:
            self.item("profiles", "Difficulty profiles", "unsupported",
                      f"Each level becomes one profile; a project holds {MAX_PROFILES}.",
                      len(levels), MAX_PROFILES)  # fmt: skip
            add("profile_count_unsupported",
                f"{len(levels)} levels exceed the cap of {MAX_PROFILES} difficulty profiles.",
                path="difficulty.levels", actual=len(levels),
                expected=f"at most {MAX_PROFILES}")  # fmt: skip
        elif levels:
            self.item("profiles", "Difficulty profiles", "verified",
                      "Each level can become one difficulty profile.", len(levels),
                      MAX_PROFILES)  # fmt: skip
        # Generator limits per level.
        engine_ok = True
        for settings in levels:
            level = settings.level
            if settings.origin == "plan" and settings.problem not in (None, "missing"):
                engine_ok = False
                add(
                    "grid_unsupported",
                    f"Level {level.label!r}: {settings.problem}",
                    path=settings.path,
                    actual=f"{settings.width} x {settings.height}",
                    expected="1..50 x 1..50",
                    subjects=(level.id,),
                )
            if level.words.max > MAX_PUZZLE_TARGETS:
                engine_ok = False
                add(
                    "words_per_puzzle_unsupported",
                    f"Level {level.label!r} expects up to {level.words.max} words; the "
                    f"generator places at most {MAX_PUZZLE_TARGETS}.",
                    path=f"{settings.path}.words.max",
                    actual=level.words.max,
                    expected=f"at most {MAX_PUZZLE_TARGETS}",
                    subjects=(level.id,),
                )
        if levels:
            self.item(
                "generator_settings",
                "Generator settings",
                "verified" if engine_ok else "unsupported",
                "Level grids, directions and word counts are within the generator's limits."
                if engine_ok
                else "Some levels exceed the generator's limits.",
            )
        self._print()
        self._fit()
        self._pages()
        self.item(
            "generation",
            "Puzzle generation",
            "unknown",
            "Whether every grid places all its words is known only when production generates "
            "and verifies each puzzle. Placement is bounded and may fail for dense grids.",
        )
        self.item(
            "cover",
            "Cover",
            "unknown",
            "Cover size and spine derive from the built interior's real page count and paper; "
            "they cannot be planned exactly.",
        )

    def _print(self) -> None:
        a = self.analysis
        add = a.findings.add
        s = a.doc.structure
        chosen = s.print_profile
        if chosen is None:
            self.item("print_profile", "Print profile", "unknown",
                      "Not chosen. Supported: " + ", ".join(sorted(PROFILES)) + ".")  # fmt: skip
        elif chosen in PROFILES:
            self.item("print_profile", "Print profile", "verified", PROFILES[chosen].description,
                      chosen)  # fmt: skip
        else:
            self.item("print_profile", "Print profile", "unsupported",
                      "Supported: " + ", ".join(sorted(PROFILES)) + ".", chosen)  # fmt: skip
            add(
                "print_profile_unsupported",
                f"Print profile {chosen!r} is not supported.",
                path="structure.print_profile",
                actual=chosen,
                expected=", ".join(sorted(PROFILES)),
            )
        spec, known = self._spec()
        assumed = "" if known else f" (assuming the {spec.profile_id} page geometry)"
        content = page_frame(spec, 1).content
        t, stroke = spec.typography, spec.strokes.grid_frame
        sized = [x for x in a.levels if x.config is not None]
        if not sized:
            return
        failures = []
        for settings in sized:
            assert settings.config is not None
            size = settings.config.size
            grid = fit_grid(size.width, size.height, content, t.grid_letter_max, stroke,
                            max_cell_for_letter(t.grid_letter_max))  # fmt: skip
            if grid.letter_size < t.grid_letter_min - 1e-6:
                failures.append(settings.level.id)
                add(
                    "grid_print_unsupported",
                    f"Level {settings.level.label!r}: a {size.width} x {size.height} grid "
                    f"cannot keep {t.grid_letter_min:g} pt letters even using the whole live "
                    f"area{assumed}.",
                    path=settings.path,
                    actual=f"{grid.letter_size:.2f} pt",
                    expected=f"at least {t.grid_letter_min:g} pt",
                    subjects=(settings.level.id,),
                )
        self.item(
            "puzzle_grids_print",
            "Puzzle grids on the page",
            "unsupported" if failures else "estimate",
            "Some grids cannot print at the minimum letter size." if failures
            else f"Each level's grid fits the live area at {t.grid_letter_min:g} pt or more "
            f"before the title and word list are laid out{assumed}. The interior layout "
            "decides with the real word list.",
        )  # fmt: skip
        per_page = s.solutions_per_page
        if s.solutions is not SolutionsPlan.END or per_page is None:
            return
        slot = solution_slots(per_page, content, SOLUTION_GAP_X, SOLUTION_GAP_Y)[0]
        failures = []
        for settings in sized:
            assert settings.config is not None
            size = settings.config.size
            grid = fit_grid(size.width, size.height, slot, t.solution_letter_max, stroke,
                            max_cell_for_letter(t.solution_letter_max))  # fmt: skip
            if grid.letter_size < t.solution_letter_min - 1e-6:
                failures.append(settings.level.id)
                add(
                    "solution_print_unsupported",
                    f"Level {settings.level.label!r}: {per_page} solutions a page leave a "
                    f"{size.width} x {size.height} grid below {t.solution_letter_min:g} pt.",
                    path="structure.solutions_per_page",
                    actual=f"{grid.letter_size:.2f} pt",
                    expected=f"at least {t.solution_letter_min:g} pt",
                    subjects=(settings.level.id,),
                )
        self.item(
            "solution_grids_print",
            "Solution grids",
            "unsupported" if failures else "estimate",
            f"Some grids are too large for {per_page} solutions a page." if failures
            else f"Each level's solution fits {per_page} a page at {t.solution_letter_min:g} pt "
            f"or more before captions{assumed}.",
        )  # fmt: skip

    def _fit(self) -> None:
        a = self.analysis
        add = a.findings.add
        checked = 0
        failed = 0
        for i, words in sorted(a.assigned.items()):
            puzzle = a.doc.puzzles[i]
            settings = a.level_by_id.get(puzzle.level) if puzzle.level else None
            if settings is None or settings.config is None or not words:
                continue
            for word in words:
                assert word.search is not None
                checked += 1
                try:
                    validate_fit((Target("word", word.word, word.search),), settings.config)
                except WordSearchError:
                    failed += 1
                    size = settings.config.size
                    add(
                        "word_cannot_fit",
                        f"{word.word!r} ({len(word.search)} letters) cannot fit level "
                        f"{settings.level.label!r} ({size.width} x {size.height}) in any "
                        "enabled direction.",
                        path=f"puzzles.{i}.words",
                        actual=len(word.search),
                        subjects=(puzzle.id, word.word),
                    )
        if checked:
            self.item(
                "word_fit",
                "Words fit their grids",
                "unsupported" if failed else "verified",
                f"{failed} of {checked} assigned words cannot fit their level's grid."
                if failed
                else f"All {checked} assigned words fit their level's grid in an enabled "
                "direction.",
            )
        else:
            self.item("word_fit", "Words fit their grids", "unknown",
                      "No words are assigned to puzzles with complete levels yet.")  # fmt: skip

    def _pages(self) -> None:
        a = self.analysis
        add = a.findings.add
        estimate = self.estimate
        spec, _ = self._spec()
        low, high = estimate.minimum, estimate.maximum
        if low is None:
            self.item("page_count", "Page count", "unknown", "No target puzzle count yet.")
            return
        span = (
            f"{low}" if high == low else f"{low}-{high}" if high is not None else f"at least {low}"
        )
        self.item(
            "page_count",
            "Page count",
            "estimate",
            f"About {span} logical pages from the plan. The exact count comes from the "
            "publication plan; the renderer never pads.",
            span,
        )
        minimum = KDP.min_pages
        if high is not None and high < minimum:
            add(
                "page_estimate_below_minimum",
                f"The plan describes at most {high} pages; KDP's paperback minimum is {minimum}.",
                path="structure.target_puzzles",
                actual=high,
                expected=f"at least {minimum}",
                action="Plan more puzzles or pages; PuzzlePress never pads a book.",
            )
        elif low < minimum:
            add(
                "page_estimate_uncertain",
                f"The estimate ({span}) may fall below KDP's {minimum}-page minimum.",
                path="structure",
                actual=span,
                expected=f"at least {minimum}",
            )
        maximum = KDP.max_pages_for(spec.trim.name, spec.paper)
        if maximum is not None:
            if low > maximum:
                add(
                    "page_estimate_above_maximum",
                    f"The plan describes at least {low} pages; the {spec.trim.name} maximum "
                    f"PuzzlePress models is {maximum}.",
                    path="structure.target_puzzles",
                    actual=low,
                    expected=f"at most {maximum}",
                )
            elif high is None or high > maximum:
                if high is not None:
                    add(
                        "page_estimate_uncertain",
                        f"The estimate ({span}) may exceed the {maximum}-page maximum.",
                        path="structure",
                        actual=span,
                        expected=f"at most {maximum}",
                    )
        spine = KDP_COVER.spine_text_min_pages
        if low >= spine:
            status, detail = (
                "estimate",
                f"Likely: the estimate reaches the {spine} pages spine text needs.",
            )
        elif high is not None and high < spine:
            status, detail = "estimate", f"Unlikely: spine text needs {spine} pages."
        else:
            status, detail = "unknown", f"Spine text needs {spine} pages; the estimate spans that."
        self.item("spine_text", "Spine text", status, detail, span, spine)
