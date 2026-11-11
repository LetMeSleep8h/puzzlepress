"""Quality evidence from the production overview, and what only a proof can settle.

The overview (production/guidance.py) already reruns preflight and readiness and
reads reviews and proof records; the audit turns its open items into
recommendations and does not recompute them.
"""

from collections.abc import Mapping

from ..models import Project
from .model import Basis, Category, ManualCheck, Priority, Recommendation

DONE = {"completed", "not_applicable"}
BASIS = {
    "internal": Basis.MEASURED,
    "kdp_modeled": Basis.MEASURED,
    "author_judgment": Basis.JUDGMENT,
}
# Open but advisory: warnings that never block, or an export that is optional once
# the files are uploaded.
ADVISORY = {"interior_preflight", "cover_preflight", "export"}


def evidence_recommendations(overview: Mapping[str, object]) -> list[Recommendation]:
    items = overview.get("items")
    assert isinstance(items, list)
    found: list[Recommendation] = []
    for item in items:
        assert isinstance(item, dict)
        status = str(item["status"])
        if status in DONE or item["basis"] == "external":
            continue
        if item["blocks_export"] or status == "blocking":
            priority = Priority.HIGH
        elif item["code"] in ADVISORY and status == "needs_attention":
            priority = Priority.LOW
        else:
            priority = Priority.MEDIUM
        action = item.get("action") or item.get("what")
        found.append(
            Recommendation(
                f"evidence_{item['code']}",
                priority,
                Category.EVIDENCE,
                BASIS.get(str(item["basis"]), Basis.MEASURED),
                str(item["title"]),
                str(item["detail"]),
                str(action),
                str(item["area"]),
            )
        )
    return found


def _recorded(proofs: object, kind: str) -> str:
    if not isinstance(proofs, dict):
        return "not_recorded"
    latest = proofs.get(kind)
    if isinstance(latest, dict) and latest.get("current"):
        return "recorded"
    return "stale" if isinstance(latest, dict) else "not_recorded"


def manual_checks(project: Project, overview: Mapping[str, object]) -> tuple[ManualCheck, ...]:
    proofs = overview.get("proofs")
    checks = [
        ManualCheck(
            "print_previewer",
            "Review the uploaded files in KDP's Print Previewer",
            "KDP's own check of trim, margins and the cover template; PuzzlePress only models it.",
            _recorded(proofs, "print_previewer"),
        ),
        ManualCheck(
            "physical_proof",
            "Order and inspect a printed proof copy",
            "Paper, ink density, binding and colour are only visible in print; no physical "
            "proof is assumed.",
            _recorded(proofs, "physical_proof"),
        ),
        ManualCheck(
            "gutter",
            "Open the proof flat: nothing important disappears into the binding",
            "Gutter widths follow KDP's table; how a reader holds the book is not modelled.",
            "manual",
        ),
    ]
    if project.word_search is not None:
        checks.append(
            ManualCheck(
                "grid_legibility",
                "Grid letters, word lists and solution marks print dark and readable",
                "Type sizes are measured; how dark they print on this paper is not.",
                "manual",
            )
        )
    if project.coloring is not None:
        checks.append(
            ManualCheck(
                "line_art",
                "Line art prints clean: no gray haze, broken fine lines or show-through",
                "Line measures are computed from pixels; paper and toner are not.",
                "manual",
            )
        )
    if project.cover is not None:
        checks += [
            ManualCheck(
                "cover_thumbnail",
                "Read the front cover at thumbnail size (about 160 px wide)",
                "Amazon shows covers small in search results; legibility there is a judgment.",
                "manual",
            ),
            ManualCheck(
                "spine_and_folds",
                "Check the spine text and both folds on the printed cover",
                "KDP allows the fold to vary; a sliver of the next panel may show.",
                "manual",
            ),
            ManualCheck(
                "photo_content",
                "Check the cover photographs for people, licence plates, logos and trademarks",
                "Rights and releases are yours to decide; PuzzlePress cannot see what a "
                "photograph shows.",
                "manual",
            ),
        ]
    return tuple(checks)
