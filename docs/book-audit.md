# Book audit

`puzzlepress book audit` and Studio's **Audit** page review an existing or already
published book and return prioritized, evidence-backed recommendations. The audit
is read-only: it never edits `book.yaml`, rebuilds a file, regenerates a puzzle or
contacts Amazon. It writes only when asked (`--report DIR`, outside every book
folder).

```text
puzzlepress book audit books/my-book
puzzlepress book audit books/my-book --previous ../books/volume-1 --previous ../books/volume-2
puzzlepress book audit books/my-book --json --report build/audit
```

Exit codes: **0** no high-priority recommendation, **1** at least one (or an
expected error), **2** usage. `--json` prints exactly the bytes of `audit.json`
(`puzzlepress-book-audit`, `audit_version` 1, sorted keys, no times). `--output`
names the built directory when it is not the project's `output.directory`.
`--report` refuses a directory inside the audited or a compared book, a symlinked
file, and an `audit.json` that is not an audit.

## What it checks

Each recommendation has a priority, a category, a basis (`kdp_help` with the
official page, `measured`, or `judgment`), the evidence, an action, and where to
look: a `book.yaml` field, physical interior pages (Studio links to
`print?page=N`) and puzzle IDs.

| Category | Code | Priority | What |
| --- | --- | --- | --- |
| Listing | `claim_mismatch` | high | The title, subtitle, `book.description`, KDP description or cover text states a number of levels, parts (dividers) or puzzles the book does not have. Partial counts ("the last two parts") and "one" are not counts. |
| Listing | `theme_count_differs` | medium | A stated number of themes matches neither the distinct puzzle theme labels nor their bases ("Engines · Warm-up" counts as "Engines"). |
| Listing | `keyword_slots_unused` | medium | Fewer than KDP's seven keywords. |
| Listing | `keyword_repeats_metadata` | medium / low | Every (medium) or at least half (low) of a keyword's words already appear in the title, subtitle, contributors or categories; KDP asks keywords to avoid them. |
| Listing | `category_slots_unused` | low | Fewer than three categories. |
| Listing | `audience_unrecorded`, `audience_not_named` | low | No primary audience in `planning.yaml`, or its words appear nowhere in the listing. |
| Print | `odd_page_count` | high with a cover, else medium | KDP rounds the page count up to an even number; the evidence gives the spine for both counts. |
| Print | `many_blank_pages` | low | More than 10 % of pages are layout blanks. |
| Content | `difficulty_order` | medium if the book promises rising difficulty, else low | A puzzle has a smaller grid and no more directions (or fewer directions and no larger grid) than an earlier one. |
| Content | `no_diagonal_words`, `no_backward_words` | low | A level allows those directions but some puzzles placed no word that way. |
| Content | `uneven_backward_words` | low | A puzzle has fewer than half its level's median backward words. |
| Content | `title_in_word_list` | low | A listed word appears in the puzzle's own title. |
| Content | `generation_failed` | high | A puzzle produced no verified grid. |
| Series | `exact_duplicate_previous` / `near_duplicate_previous` | high / medium | Repeats against compared books (`puzzle compare`'s thresholds). Within the book: medium. |
| Series | `series_author`, `series_imprint`, `series_language`, `series_print_profile`, `series_solutions_per_page`, `series_puzzle_layout`, `series_interior_style` | medium (author) / low | Settings that differ from the compared books. |
| Evidence | `evidence_<item>` | high when it blocks export, else medium (low for preflight warnings and the export) | Every open item of the production overview (preflight, readiness, decisions, editorial review, plan approval). |

Backward words read right to left or bottom to top (left, up, up-left,
down-left). Difficulty profiles are generation settings, not measured
difficulty; the "Difficulty by level" table reports the generated grids' facts.

Manual checks are listed separately: Print Previewer and physical proof (status
from `proofs.yaml`: recorded, recorded for earlier files, not recorded), and
by-hand checks for the binding, grid legibility or line art, the cover thumbnail,
the spine and folds, and the content of cover photographs.

**Not assessed**, always stated: sales, royalties, advertising, search ranking,
customer reviews and competitor listings (PuzzlePress has no Amazon data); series
when no book is compared; coloring artwork, which coloring preflight assesses.

## Studio

**Audit** (Review group; coloring books after Produce) shows the audit of the saved
revision, filters by category, links each item to the page that edits it and each
page number to Print proof, and offers the Markdown report as a download. It
compares the book with the library's other books in the same **collection**
(Settings > Collection). `GET /api/projects/{key}/audit` returns `{key, revision,
audit, markdown, collection, compared}`, cached by the same bytes as the production
overview plus the compared books' revisions.

## Sources

KDP pages read 2026-11-11: [Paperback Submission
Guidelines](https://kdp.amazon.com/en_US/help/topic/G201857950) ("rounding up to an
even number if necessary"; excessive blank pages as a common failure) and [Make
Your Book More Discoverable with
Keywords](https://kdp.amazon.com/en_US/help/topic/G201298500) (avoid information
covered elsewhere in the metadata and words in the categories; up to seven).
Priorities, the 10 % blank share and the half-of-median and half-of-words limits
are PuzzlePress conventions.
