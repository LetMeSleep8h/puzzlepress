# Print preflight and preview

Preflight inspects a built interior and answers two separate questions. It
observes; it never repairs. It does not change the publication plan, the layout,
`interior.pdf`, `interior.json` or project source, and it never pads, regroups,
shrinks, re-renders or regenerates anything to make a check pass.

```text
puzzlepress book build books/composition-demo
puzzlepress book preflight books/composition-demo
puzzlepress book preflight books/composition-demo --json --no-write
```

## Two validity levels

**Structural validity**: did PuzzlePress produce a coherent artifact that matches
its authoritative inputs? The files exist and parse, the manifest describes this
PDF, the PDF was built from the current source, plan, profile and toolchain, and
the PDF keeps the renderer contract (page count, boxes, fonts, blanks, folios).

**KDP readiness**: does the artifact satisfy the Amazon KDP paperback constraints
PuzzlePress models? Readiness is only claimed for a structurally valid artifact.

A PDF can be structurally valid but not KDP ready. `composition-demo` (11 pages)
is the canonical example: it builds, verifies and previews correctly, and its
readiness fails with `kdp_minimum_page_count`. `book build` still writes it with
a warning; the plan owns page count and the renderer never pads.

Preflight verifies modeled constraints only. Amazon remains the final authority;
passing preflight is not a guarantee of acceptance.

Coloring books are preflighted with their own ruleset, `puzzlepress-kdp-coloring`,
which reuses the rules below under the same codes and adds artwork, image-integrity,
parity, rendering-environment and line-quality rules
([coloring.md](coloring.md#preflight)). This catalogue and its reports are unchanged.

## How it works

```text
interior.pdf + interior.json        current project source
        |                                     |
  read bytes (fixed names)        build_interior() in memory
        |                          (plan, verify, bind digests,
  pypdf facts (inspection.py)       layout, validate, render)
        \_____________________________________/
                          |
                  rules (preflight/rules.py)
                          |
                    PreflightReport
```

- `preflight.context` reads only `interior.pdf` and `interior.json` in a directory
  already checked to be disjoint from source; symlinks and non-files are reported.
- The expected interior is rebuilt with the same pure pipeline as `book build`.
  Preflight never re-derives geometry.
- `interior.inspection.read_pdf_facts` is the single pypdf layer: boxes, rotation,
  annotations, fonts (embedded, subset), images, transparency, layers, metadata,
  text and painting. The post-build check and preflight judge the same facts.
  Facts are a function of the bytes alone, so when `interior.pdf` is byte-identical
  to the fresh build, preflight reuses the facts read during that build instead of
  parsing the file again; any other bytes are read afresh. Pages with no
  `/XObject` resource and no `BI` bytes in their content have no image, so the
  image count skips pypdf's second content-stream parse there (exact; tested).
- Layout-based rules (margins, type sizes, line weights, blanks, folios, numbering)
  apply only when the PDF bytes equal a fresh render of the current verified layout
  (`pdf_matches_layout`). Otherwise they are `not_evaluated`, never passed.

## Rule model

Each rule has a stable `code`, a `scope` (`structural` or `kdp`), a `category`
(`artifact`, `integrity`, `page`, `geometry`, `typography`, `font`, `content`),
the `severity` of its findings (`error`, `warning`, `info`), a `basis`
(`kdp_requirement`, `kdp_ambiguous`, `puzzlepress_contract`) and its `source`.
Each evaluation has an outcome: `passed`, `failed`, `not_applicable` or
`not_evaluated` (a prerequisite failed).

- Structural is **valid** when no structural error rule failed or went unevaluated.
- KDP is **ready** when the artifact is structurally valid and no KDP error rule
  failed or went unevaluated. Warnings never block.

Findings carry the rule, severity, scope, category, message, physical and logical
page, page kind, side, displayed folio, puzzle ID (`subject`), region, bounds in
PDF points (origin at the trim's bottom-left) and a `measure` (`actual`,
`required`, `unit`, `comparison`). Book-level findings have no page and no region.
Findings sort by severity, scope, page, rule and region.

## Rule catalogue

Values live in `interior.spec.KdpConstraints` (the one home of KDP numbers).
Official sources were read on 2026-10-07: KDP help "Set Trim Size, Bleed, and
Margins", "Paperback Submission Guidelines", "Fix Paperback and Hardcover
Formatting Issues" and "Print Options".

### Structural

| Code | Checks |
| --- | --- |
| `interior_artifacts` | Both files exist as regular files (no symlinks). |
| `manifest_format` | Manifest version 1 with every required field. |
| `manifest_book` | Manifest book ID equals the project's. |
| `manifest_pdf_digest` | PDF SHA-256 and size equal the manifest. |
| `interior_identity` | Recorded identity recomputes from the recorded inputs. |
| `source_current` | Built from the current source (build identity). |
| `print_profile_current` | Profile is built in and its definition is unchanged. |
| `toolchain_current` | Renderer, engine, ReportLab and font digests are current. |
| `source_buildable` | Current source plans, binds digests and lays out. |
| `plan_current` | Plan digest equals the current verified plan. |
| `pdf_matches_layout` | PDF bytes equal a fresh deterministic render. |
| `pdf_readable` | pypdf parses the PDF strictly; not encrypted. |
| `page_count` | PDF pages equal manifest and plan pages. |
| `page_boxes` | MediaBox and TrimBox equal the trim; no larger BleedBox. |
| `page_rotation` | No rotated pages. |
| `pdf_interactive_features` | No annotations, forms, actions, name trees or bookmarks. |
| `fonts_bundled` | Only embedded subsets of the bundled Vera Sans faces. |
| `raster_images` | Raster images appear only where the verified layout places a styled photograph (photo-feature title page or theme divider); any other image is foreign. |
| `blank_pages` | Plan blanks have no text or painting. |
| `folios_printed` | Every displayed page number is in the page text. |
| `content_in_live_area` | Every element's painted extent lies inside the profile's live area. |
| `design_legibility` | Warning only: solution letters below 7.5 pt (`dense_solution_page`), accent labels lighter than 50% black (`light_text`), banner or panel type with too little contrast (`low_contrast_text`), and dark tints over large areas (`heavy_ink_coverage`), as the verified layout reports them. PuzzlePress conventions; never blocks. |

### KDP

| Code | Requirement | Source | Basis |
| --- | --- | --- | --- |
| `kdp_minimum_page_count` | At least 24 pages | Submission Guidelines | requirement |
| `kdp_maximum_page_count` | At most 550 pages (8.5 x 11 in) | Print Options | ambiguous |
| `kdp_trim_size` | Trim within 4-8.5 x 6-11.69 in | Print Options | requirement |
| `kdp_page_size` | Single trim-size pages, no spreads | Submission Guidelines | requirement |
| `kdp_no_bleed` | No-bleed: no BleedBox beyond trim | Set Trim Size, Bleed, and Margins | requirement |
| `kdp_gutter` | Inside clearance by page count (below) | Set Trim Size, Bleed, and Margins | requirement |
| `kdp_outside_margins` | Outside, top, bottom at least 0.25 in | Set Trim Size, Bleed, and Margins | requirement |
| `kdp_minimum_font_size` | Text and grid letters at least 7 pt | Submission Guidelines | requirement |
| `kdp_minimum_line_weight` | Rules, frames, marks at least 0.75 pt | Submission Guidelines | requirement |
| `kdp_fonts_embedded` | Every font program embedded | Submission Guidelines | requirement |
| `kdp_full_font_embedding` | Warning when fonts are subsets | Formatting Issues | ambiguous |
| `kdp_no_annotations` | No annotations, comments, forms, bookmarks | Submission Guidelines | requirement |
| `kdp_not_encrypted` | Not locked or encrypted | Submission Guidelines | requirement |
| `kdp_flattened` | No transparency or layers | Submission Guidelines | requirement |
| `kdp_no_printer_marks` | No slug area beyond the trim for crop or registration marks | Submission Guidelines | requirement |
| `kdp_image_resolution` | Raster images at least 300 DPI | Submission Guidelines | requirement |
| `kdp_blank_page_runs` | At most 4 consecutive blanks (10 at end) | Formatting Issues | requirement |
| `kdp_page_number_parity` | Even numbers on left (verso) pages | Submission Guidelines | requirement |
| `kdp_no_metadata` | Warning for title/author/subject/keywords | Submission Guidelines | ambiguous |

Gutter (inside margin) by page count: 24-150 0.375 in, 151-300 0.5, 301-500 0.625,
501-700 0.75, 701-828 0.875. Above 828 the gutter is undefined and the rule is
`not_evaluated` (the build already fails there). Margins are measured from each
element's painted extent (text advance width with font ascent/descent; stroked
frames include half their line width), with 0.01 pt tolerance.

Ambiguities, recorded rather than resolved:

- **Maximum pages.** The rendered official Print Options table (2026-10-07) lists
  only 5 x 8 in under amazon.com paperbacks; KDP says the maximum "depends on ink,
  paper, and trim size". A search-indexed copy of the page lists 24-590 (white)
  and 24-550 (cream) for 8.5 x 11 in. Paper is not modeled, so 550 applies.
- **Full embedding.** Formatting Issues says fonts "should be fully embedded";
  Submission Guidelines says "embedded". PuzzlePress embeds TrueType subsets that
  contain every glyph used, so this is a warning to review, not a block.
- **Metadata.** Submission Guidelines asks for no "metadata". Descriptive fields
  are checked; the producer/creator tool names every PDF carries are not.
- **Line weight.** KDP states "0.75 point or 0.01 in"; 0.01 in is 0.72 pt. The
  stricter 0.75 pt applies.

Not modeled here: invisible objects, placeholder text, bleed profiles, color interiors, paper type and
per-marketplace trim tables. Image resolution is measured from the layout: each
styled photograph's used source pixels over its printed size, against 300 DPI.

### Updating KDP rules

1. Re-read the four official KDP help pages above; never use third-party sources
   as normative.
2. Change values only in `interior.spec.KdpConstraints` and rule wording in
   `preflight/rules.py`; record ambiguity in this file.
3. Bump `RULESET_VERSION` in `preflight/model.py` whenever a verdict can change,
   and update `KDP_RULES_CHECKED`. Project and interior identities do not change:
   the ruleset belongs to inspection, not authored semantics.
4. Add boundary tests for the new value (`tests/test_preflight.py`).

Ruleset history. **v4**: adds the warning `design_legibility` for interior design
readability notes; no other verdict changes. **v3**: interior styles may print grayscale photographs, so
`raster_images` attributes each image to the layout instead of refusing all images,
and `kdp_image_resolution` measures effective DPI from the layout (previously any
image failed both as unverified). Books without styled photographs get the same
verdicts as v2. **v2**: version 1's `kdp_no_printer_marks` also failed any element
outside the profile's live area. That area is PuzzlePress's own margin choice
(0.75/0.5/0.625 in), not a KDP rule, and an element past it is not a printer's mark.
Containment is now the structural `content_in_live_area` rule; `kdp_no_printer_marks`
keeps its code and judges only the area beyond the trim; KDP margins remain
`kdp_gutter` and `kdp_outside_margins`. Saved v1 reports are outdated and are
recomputed, never trusted.

## Report

`PreflightReport.to_dict()` (and `preflight.json`) contains `report_version` (1),
`ruleset {id, version, kdp_rules_checked}`, `book_id`, `source_identity`,
`profile`, `artifacts` (PDF and manifest SHA-256 and size, recorded and expected
interior identity, `matches_layout`), `page_count`, `structural.status`,
`kdp.status`, `counts` (by severity, scope, category, outcome), sorted `findings`,
every rule with its outcome, note and worst measured case, and `pages` (physical
and logical page, kind, side, folio, finding counts). No timestamps or paths.
Identical artifacts, source and ruleset produce byte-identical JSON.

## CLI

`puzzlepress book preflight PROJECT [--output DIR] [--json] [--no-write]` reads the
interior in the project's output directory (or `--output`). It prints structural
status, KDP readiness, profile, page count, PDF SHA-256, blocking findings and
warnings; `--json` prints the report exactly as written. It writes `preflight.json`
beside the interior (staged, fsynced, `os.replace`) only when `interior.json`
names the same book; `--no-write` writes nothing. Exit **0** structurally valid and
KDP ready, **1** otherwise (including a missing or stale interior), **2** usage.

## Studio print proof

The **Print** tab shows the saved project's built interior. **Build interior**
builds the saved source at the revision Studio loaded (`409 source_changed`
otherwise), writes `interior.pdf`, `interior.json` and `preflight.json`, and shows
the result. Unsaved drafts disable the build: the proof always reflects persisted
source. Nothing builds automatically.

- **Preview.** Pages are rasterized server-side from the exact `interior.pdf` bytes
  with PDFium (`pypdfium2`), never recreated in HTML. Sizes: thumbnail 0.5x
  (306 x 396 px), page 2x (1224 x 1584), detail 4x (2448 x 3168). The viewer picks
  page or detail by displayed size and device pixel ratio. Images are lossless PNG.
- **Cache.** An in-memory LRU (96 MB) keyed by PDF SHA-256, page and size; at most
  one open PDF; PDFium calls are serialized. Image URLs carry the digest and are
  served `private, immutable`; a request whose digest no longer matches the file
  gets `409 preview_stale`. Preflight results are cached by source revision, PDF
  and manifest digests and ruleset version. Nothing is written to disk.
- **Viewer.** Single page and facing spreads (page 1 alone on the right; verso
  left, recto right), First/Previous/Next/Last, direct page entry, lazy-loaded
  thumbnails, zoom (fit, 50-300% of physical size at 96 px/in) and keyboard
  (arrows, Page Up/Down, Home, End) on the page canvas.
- **Overlays.** Live area, KDP minimum margins for this page count, element bounds
  and finding regions, drawn as SVG over the raster from Python-supplied boxes.
  The binding edge is marked. Overlays are never in the PDF and are disabled when
  the PDF is not the current layout's render.
- **Findings.** Verdicts as text, grouped blocking/warnings/information with
  measured and required values; selecting a page finding navigates to its page and
  highlights its region. Passed, not applicable and not evaluated checks are
  secondary disclosures.
- **States.** `missing`, `current`, `stale` (source, plan, profile or toolchain
  changed: old pages shown, labeled out of date) and `invalid` (other structural
  failures, such as a PDF that does not match its manifest).

API: `GET /api/projects/{key}/interior`, `POST /api/projects/{key}/interior/build`
`{revision}` and `GET /api/projects/{key}/interior/pages/{n}?size=thumb|page|detail&pdf=<sha256>`.
Keys are validated route keys; files are fixed names in the project's resolved
output directory; page numbers are bounds-checked integers; sizes are an allow-list;
the digest must be 64 hex characters. No caller-supplied path is ever read.

The page images are visual. They carry no text for assistive technology; page
descriptions, statuses and findings are available as text.

## Limitations

One built-in profile, no bleed, black ink. Studio builds the default profile only.
The 8.5 x 11 in maximum page count is unverified on the current official table.
Preflight cannot judge visual quality or content correctness, and KDP's own
reviewers may apply checks PuzzlePress does not model. Covers have their own
preflight ([cover](cover.md#cover-preflight)). Publishing readiness consumes both
reports afresh ([publishing](publishing.md)); nothing is submitted to KDP.
