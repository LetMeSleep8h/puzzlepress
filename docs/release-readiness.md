# Coloring book engine: release readiness (Interval 10)

Status 2026-11-05: **the engine is a release candidate for producing a coloring book;
no book is ready for KDP.** The representative package built here is a technical
demonstration on artwork approved for testing only, and it is blocked, correctly, on
decisions only the author can make and on artwork limits.

## Completed features

- Artwork: import (PNG/JPEG, content-addressed, originals never written), inspection,
  non-destructive deterministic preparation (gray, invert, tone, cleanup, despeckle,
  threshold, line weight), paper-relative line measures (version 3), dark-edge and
  speck reporting, duplicates.
- Composition: sections, dividers, blank backs, page numbering, front and back matter;
  placement contain/fill; Studio Pages designer with Python's geometry and crop data.
- Interior: lossless PDF, eight trims and papers, standard and full-bleed profiles,
  page boxes by parity, preflight (coloring ruleset 5, interior ruleset 5).
- Cover: wrap, spine from the built page count and paper, templates, cover preflight.
- Publishing: metadata, AI disclosure, content rights, attestations, KDP checklist,
  package only when ready; nothing is submitted.
- Production: worker process per job, cancellation, recovery, verified releases, cheap
  polling, cached project loading.

## Tested configurations

| Configuration | How | Result |
| --- | --- | --- |
| 17 real historical drawings | `artwork_review.py --manifest` (3 settings), contact sheets, crops | see artwork-validation/findings.md (Interval 10) |
| Full bleed, all 8 profiles | `tests/test_bleed_raster.py`: PDF raster vs Studio's crop preview | within 1 px; boxes by parity; gutter blank |
| Demonstration book, `paperback-8.5x11` | `tests/release_candidate.py` through Studio's API and worker | 41 pages, structurally valid, release verified, blocked |
| Demonstration book, `paperback-8.5x11-bleed`, 3 filled pages | same | 41 pages (8.625 x 11.25 in), structurally valid, blocked |
| Word-search books | golden baseline, full suite | outputs unchanged |
| 1-300 drawings, standard and full bleed | `tests/production_benchmark.py` | CONTEXT.md, Interval 10 |

## The release-candidate package

`python tests/release_candidate.py docs/artwork-validation/approved.json ORIGINALS OUT`
(ORIGINALS from `tests/artwork_fetch.py`) builds, outside the repository:

- `proof-source/`: the NOT FOR SALE project and `sources.json` (every page traced to its
  file, SHA-256, source URL and rights basis);
- `standard-build/demo-release/` and `bleed-build/demo-release/`: interior.pdf,
  interior.json, preflight.json, cover.pdf, cover.json, cover-preflight.json,
  artwork-integrity.json (the artwork manifest: pinned originals, prepared digests,
  placement, DPI, findings), artwork-duplicates.json/.md, publishing-readiness.json
  (the rights review), kdp-metadata.json, publishing-validation.json/.md, production.json;
- `summary.json` / `summary.md`.

No `publishing/` upload package is written: readiness blocks it until the author
decides. The human-review checklist is publishing-validation.md's manual-review list
plus artwork-validation/proof-checklist.md and bleed-proof-checklist.md.

## Rights and AI disclosure

| Item | State | Who decides |
| --- | --- | --- |
| Interior artwork | historical drawings; `approved.json` records each rights basis (US pre-1931 publication and similar) and approval **for testing only, not for publication or sale** | the author; a book for sale needs artwork approved for that |
| Cover artwork | one approved drawing (Libbey automobile), same approval | the author |
| Text (titles, dividers, sources page, description) | written by PuzzlePress's scripts for the demonstration | the author |
| AI disclosure (text, images, translations) | `unknown` | the author answers KDP's question |
| Content rights declarations | `undecided` | the author |
| Attestations (rights, AI, metadata, ISBN) | not confirmed | the author |
| ISBN, low-content, explicit-content answer, categories | undecided | the author |

Nothing here was invented: no author name, license, disclosure or confirmation was
written on the author's behalf. No AI-generated artwork was made or used.

## Open blockers (demonstration book)

1. Artwork approved for testing only; an automotive coloring book for sale needs
   artwork whose publication rights the author holds (own, commissioned, licensed or
   verified public domain approved for sale).
2. Author decisions: rights basis, AI disclosure, ISBN, low-content, explicit content,
   attestations, categories.
3. Resolution: five drawings print below 300 DPI full page (Pollard Willows 270, Meyer
   268 and 208, Vitis 210, Tenniel 296; 240 for Libbey filled to the bleed).
4. Unsuitable art: Doré (excessive ink), Cypresses (blank after preparation), the
   Otis scan frame (crop before import).
5. No physical proof (proof-status.md: not started).

## Physical proof requirements

Before any release: a printed proof of the interior and cover (and of a bleed
interior if the book uses bleed), inspected with proof-checklist.md and
bleed-proof-checklist.md, recorded in proof-status.md as "inspected with findings" or
"approved". PuzzlePress never orders one.

## KDP metadata

Recorded in kdp-metadata.json from the publishing section: title, subtitle, author
(undecided in the demonstration), description (factual), keywords and categories
(empty), trim, paper, ink, bleed setting, page count. KDP decides acceptance; nothing is
uploaded or submitted by PuzzlePress.

## Recommended follow-up

- Artwork with publication rights for the automotive subject (the author's decision).
- An artwork crop step (non-destructive, recorded as configuration) for scan frames.
- A physical proof of the demonstration (standard and bleed) to settle pale hatch,
  grain, tint and trim behavior.
- The inherited rich-text browser failure (templates.spec.ts) as its own task.
