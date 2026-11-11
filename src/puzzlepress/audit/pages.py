"""Print facts KDP applies after upload that preflight does not model.

KDP "will calculate your page count based on your manuscript file, rounding up to
an even number if necessary" (Paperback Submission Guidelines, read 2026-11-11). A
cover whose spine was sized for an odd page count is then sized for one page fewer
than KDP counts. PuzzlePress keeps deriving the spine from the pages it built; the
audit reports the difference so the author decides.
"""

from ..interior.spec import KDP_COVER, Paper, to_inches
from ..models import Project
from ..publication import PageKind, PublicationPlan
from .model import Basis, Category, Priority, Recommendation

SUBMISSION_GUIDELINES = "https://kdp.amazon.com/en_US/help/topic/G201857950"


def page_recommendations(
    project: Project, plan: PublicationPlan, paper: Paper
) -> list[Recommendation]:
    found: list[Recommendation] = []
    count = len(plan.pages)
    if count % 2:
        built = to_inches(KDP_COVER.spine_width(count, paper))
        counted = to_inches(KDP_COVER.spine_width(count + 1, paper))
        cover = project.cover is not None
        found.append(
            Recommendation(
                "odd_page_count",
                Priority.HIGH if cover else Priority.MEDIUM,
                Category.PRINT,
                Basis.KDP_HELP,
                f"{count} pages: KDP will count {count + 1}",
                "KDP rounds the page count up to an even number. "
                + (
                    f"The cover's spine is sized for {count} pages ({built:.4f} in); for "
                    f"{count + 1} pages it is {counted:.4f} in ({counted - built:.4f} in wider)."
                    if cover
                    else f"A cover made for {count} pages would be {counted - built:.4f} in "
                    "narrower at the spine than KDP expects."
                ),
                "Make the page count even with real content (remove or merge one page of "
                "matter, or add one genuine page), then rebuild the interior and cover. "
                "Otherwise confirm in KDP's cover check that the current spine is accepted.",
                "book",
                source=SUBMISSION_GUIDELINES,
                pages=(count,),
            )
        )
    blanks = [page.index for page in plan.pages if page.kind is PageKind.BLANK]
    if count and len(blanks) * 10 > count:
        found.append(
            Recommendation(
                "many_blank_pages",
                Priority.LOW,
                Category.PRINT,
                Basis.KDP_HELP,
                f"{len(blanks)} of {count} pages are blank",
                "KDP lists excessive blank pages as a common reason files are returned. "
                "These are layout blanks (recto starts, blank backs).",
                "Check whether recto starts or blank backs could be relaxed in Book; never "
                "fill them with filler content.",
                "book",
                source=SUBMISSION_GUIDELINES,
                pages=tuple(blanks),
            )
        )
    return found
