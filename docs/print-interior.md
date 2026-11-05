# Print interior engine

`puzzlepress book build` turns a composed project into a print interior PDF. It
consumes the verified [publication plan](book-composition.md) and never changes
it: one physical page per plan entry, in plan order.

```text
project -> generation -> plan -> plan verification -> digest binding
        -> print specification -> layout -> layout validation
        -> PDF -> PDF inspection -> interior.pdf + interior.json
```

```text
puzzlepress book build books/composition-demo
puzzlepress book build books/composition-demo --output /tmp/demo --json
```

## Renderer contract

The plan decides what is on each page; the renderer decides where. Layout may
choose coordinates, grid scale and the arrangement of an already-planned
solution group. It never reorders, omits, inserts, merges or splits entries,
regroups solutions, changes numbering, regenerates puzzles or shrinks content
below profile minimums. Content that does not fit fails with a diagnostic.

Code lives in `puzzlepress.interior`: `spec` (profiles, units, KDP constraints),
`fonts`, `text` (wrapping), `geometry`, `engine` (layout), `validation`,
`render` (ReportLab), `inspection` (pypdf) and `build` (pipeline and writer).
`build_interior(project, spec, source_directory=None)` is pure (the directory
is read only for styled photographs); `write_interior` is the only writer.
`sample_interior` lays out every page but renders only representative pages
(`sample_roles`: a facing puzzle pair, a puzzle page, a full and the final
answer page, a divider, instructions, the title page), for Studio previews;
`answer_layouts` reports how every solutions-per-page choice prints the book's
grids, using the solution renderer's own geometry.

Coloring books take the same pipeline with prepared artwork in place of generated
puzzles (`interior.coloring`): the same plan rules, matter templates, folio band,
validation, writer and inspection, plus a lossless line-art branch (`ImageBlock`
with `encoding: lossless`, embedded as FlateDecode DeviceGray) and an independent
decode of every embedded drawing. The renderer refuses an element type it does not
know, and an image whose payload does not match its encoding, instead of drawing it
as something else. See [coloring.md](coloring.md#interior).

## Interior styles

An optional `interior` section restyles the same plan
([production design](production-design-polish.md#interior-styles)): presets
classic, editorial, modern and high_contrast, title-page layouts (minimal,
editorial, color block, framed, photo feature), puzzle-page header, grid frame
and word-list settings, solution captions, mark weight and muted letters, and
divider layouts. `interior/design.py` resolves a style into one `InteriorDesign`
(version 1); the engine reads only that object. Tints are DeviceGray percentages
of black, panels stay inside the live area and photographs are converted to
grayscale by Python (`interior/images.py`). Without a style the engine uses the
classic constants and renders byte-identical PDFs; with one, the manifest records
the resolved design as its `style` input, so the interior identity changes while
the build identity, plan and grids do not.

Version 2 styles add a theme, a page layout and look overrides, resolved into a
`Look` inside the same design (`look_version` 1; absent for version 1 and no
style, so those identities hold). Themed puzzle, word-list, solution and divider
pages may carry a page frame (stroked `Panel`), a motif band of filled `Polygon`
elements on the outer side, banners (filled or stroked `Panel`s with optional
rounded corners) and rounded grid frames. Validation also refuses
`decoration_overlap`, `frame_crosses_content` and stroked or filled panels over
grids. Solution templates: 1 (1 x 1), 2 (1 x 2), 4 (2 x 2), 6 (2 x 3) and 8 (2 x
4, letters 68% of the cell; the others 56%), one per book from the plan's
largest group. A density whose letters fall below the profile minimum fails once
as `solution_layout_unreadable`, naming the densest choice that fits. See
[interior design](interior-design.md).

## Print specification

A `PrintSpecification` is renderer-facing and separate from composition; nothing
physical enters the plan or `book.yaml`. Profiles are built in and selected by
`--profile`. Adding a trim means adding a profile and its supported trim, not
changing page templates. Specs are validated before layout.

| Profile | `paperback-8.5x11` v2 (default) and `paperback-8.5x11-cream` v1 |
| --- | --- |
| Ink and paper | black ink; white paper (default) or cream paper |
| Trim | 8.5 x 11 in (612 x 792 pt); media box = trim box |
| Bleed | none (bleed specs are rejected) |
| Margins | inside 0.75 in, outside 0.5 in, top 0.625 in, bottom 0.625 in |
| Live area | 7.25 x 9.75 in, mirrored between recto and verso |
| Ink | DeviceGray only, no transparency |
| Folios | centered at the foot of the live area (`outside` also supported) |

### Print profiles (Interval 7)

Three more trims from KDP's standard paperback table ("Set Trim Size, Bleed, and
Margins", read 2026-11-05), each on white or cream paper, black ink, no bleed. A
book chooses one in Settings (`print.profile`); the CLI's `--profile` must match it.

| Profile (white / cream) | Trim | Margins (inside / outside / top / bottom) | KDP pages (white / cream) | Modeled maximum | Word search | Coloring | Cover |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `paperback-8.5x11` (v2), `-cream` (v1) | 8.5 x 11 in | 0.75 / 0.5 / 0.625 / 0.625 in | 24-590 / 24-550 | 590 / 550 | yes | yes | yes |
| `paperback-6x9`, `-cream` | 6 x 9 in | 0.75 / 0.5 / 0.5 / 0.5 in | 24-828 / 24-776 | 828 / 776 | yes (letters may fall below 9 pt and fail) | yes | yes |
| `paperback-8x10`, `-cream` | 8 x 10 in | 0.75 / 0.5 / 0.625 / 0.625 in | 24-828 / 24-776 | 828 / 776 | yes | yes | yes |
| `paperback-8.5x8.5`, `-cream` | 8.5 x 8.5 in | 0.75 / 0.5 / 0.625 / 0.625 in | 24-590 / 24-550 | 590 / 550 | yes | yes | yes |

"Yes" means the demos (composition-demo, cover-demo with its cover, the coloring
"sections" sample) build, pass structural preflight and, where they are long
enough, KDP preflight on that trim (`tests/test_print_profiles.py`). A larger grid
than the demos' can be too small on 6 x 9: the build then fails with the measured
letter size; nothing is shrunk. The modeled maximum follows the trim and the
profile's paper (interior preflight ruleset 5; rulesets 3-4 used each trim's cream value
for both papers while the official 8.5 x 11 row was missing). Cover templates
are authored on 8.5 x 11 and scaled to the trim; a cover element pushed outside the
media is reported, not moved. Not offered: other KDP trims, groundwood and color
papers, hardcover.

### Full bleed (not available)

Full-bleed interiors are refused (`unsupported_bleed_configuration`); every profile
is no-bleed and Studio offers none. Interval 8 verified KDP's rules and assessed the
work, and kept bleed unavailable rather than ship a partial publishing option.

KDP rules, read 2026-11-05 ("Set Trim Size, Bleed, and Margins"; "Paperback
Submission Guidelines"):

- Bleed is 0.125 in beyond the trim at the top, bottom and outside edge; the inside
  (gutter) edge has none. The PDF page is 0.125 in wider and 0.25 in taller than the
  trim (8.625 x 11.25 in for 8.5 x 11). Bleed needs a PDF upload, and one bleed page
  makes the whole file a bleed file.
- With bleed, outside, top and bottom margins are at least 0.375 in (0.25 in
  without); the gutter table is the same. No crop or trim marks.

What a bleed slice needs (recommended for Interval 9, coloring first):

1. Bleed profiles (`paperback-<trim>-bleed`, white and cream) with 0.375 in or larger
   outside/top/bottom margins, in `spec.py` beside the no-bleed ones.
2. `geometry.page_frame`: media = trim + bleed; the trim box sits at the media's
   inside edge (left on rectos, right on versos) and 0.125 in up; content boxes follow
   the trim. Renderer: MediaBox, BleedBox = media, TrimBox per page.
3. Coloring placement: an explicit per-page `fit: bleed` that cover-fits the drawing to
   the bleed box, records the crop as configuration (the original is untouched) and
   reports the ink share that falls outside the trim and outside the safe area.
4. Preflight: bleed variants of `kdp_no_bleed`, `kdp_page_size`, `kdp_outside_margins`,
   `content_in_live_area` and `kdp_no_printer_marks` (art past the trim is bleed, not a
   slug), plus a parity check of alternating trim boxes; unevaluated rules block.
5. Publishing: the upload checklist and metadata state "Bleed (PDF only)"; package
   identity already includes the print configuration. Cover geometry is unchanged
   (trim and page count).
6. Studio: bleed profiles in Settings, trim/bleed/safe overlays in Pages and Print, a
   "will be trimmed" view, and the profile shown in Cover, Publishing and Produce.

Paper is stated by the profile, never inferred: it does not change interior page
geometry or PDF bytes, but it is part of the interior identity and sets the cover's
spine width ([cover](cover.md)). Version 1 of `paperback-8.5x11` did not model
paper; v2 states white paper explicitly, so v1 interiors report as stale and must
be rebuilt. Groundwood and color papers are not offered: KDP publishes no
groundwood spine multiplier, and interiors are black ink only.

Units: PDF points (1 in = 72 pt), converted once in `spec.inches`. Every
profile dimension is exact in binary floating point. Geometry comparisons use
1e-6 pt; layout validation and PDF box checks use 0.01 pt.

Recto pages are odd physical pages with the inside (binding) margin on the left;
verso pages are even with it on the right. Tests use asymmetric margins to catch
mirroring mistakes.

### KDP constraints

Centralized in `spec.KdpConstraints`, checked against KDP help pages ("Set Trim
Size, Bleed, and Margins"; "Paperback Manuscript File Requirements"):

- Gutter by page count: 24-150 0.375 in; 151-300 0.5; 301-500 0.625; 501-700
  0.75; 701-828 0.875. Above 828 pages the build fails.
- Outside/top/bottom at least 0.25 in without bleed (0.375 in with bleed).
- Text at least 7 pt; lines at least 0.75 pt; fonts embedded; no annotations,
  bookmarks or printer's marks.
- At least 24 pages. A shorter book still builds with warning
  `kdp_minimum_page_count`: the plan owns page count and the renderer never pads.
  [Preflight](preflight.md) reports it as a KDP readiness failure.

The full KDP rule set, its provenance and documented ambiguities (maximum page
count, full embedding) are in [preflight](preflight.md).

Physical page count equals the plan's logical page count. The gutter is fixed by
the profile and validated against that count; it is never enlarged automatically.

Bleed is not supported: puzzle pages have no element that prints to the trim
edge, so a bleed page box would add risk without content. KDP's bleed sizes
(0.125 in outside, top and bottom) are documented here for a future profile.

## Typography

Bitstream Vera Sans Regular, Bold and Italic are bundled in
`src/puzzlepress/interior/fonts/` with their license (copied from ReportLab's
distribution; redistributable, embeddable, may not be sold alone). Each file's
SHA-256 is pinned and checked before registration; system fonts are never
consulted. Vera has clear, distinct capitals for grids and covers Latin-1 plus
common punctuation. Text containing a character the font cannot draw fails
with `unsupported_character` and its code point.

| Role | Size (pt) |
| --- | --- |
| Title / subtitle / author / imprint | 30 bold / 16 / 14 / 11 |
| Heading, puzzle title | 22 bold |
| Body, copyright | 11.5, 9.5 |
| Theme | 12 italic |
| Word list | 13 |
| Puzzle grid letters | 9 to 20, scaled with cells |
| Solution grid letters | 7 to 14, scaled with cells |
| Captions, folios | 9.5, 10 |

## Layout model

`layout_interior(plan, report, spec)` returns an immutable `InteriorLayout`:
the spec, plan digest and identity, warnings, and `PhysicalPage`s, each with
its plan index and kind, media/trim/live boxes, displayed folio and elements.
Elements are `TextLine` (measured, with bounds), `Rule` and `LetterGrid`
(authoritative rows, square cells, frame, emphasized cells and `SolutionMark`
capsules). Origin is the bottom-left of the trim box. The renderer draws exactly
these elements, so layout is tested without parsing PDFs.

Every element's `bounds` is its painted extent: a text line's advance width with
the font's ascent and descent, a rule including its stroke width, and a grid frame
plus half its stroke on every side (strokes are centered on their path). Grids are
fitted so this whole extent fits their region: the cell is the largest that leaves
room for the frame stroke, and the painted frame is centered and top-aligned.
Validation, collision checks and preflight measure the same painted extents.

A 24 pt folio band is reserved at the foot of every live area.

- **Title page:** title, a short rule, subtitle and author from book metadata;
  imprint at the foot if authored. Nothing is invented.
- **Copyright:** authored text at the foot, in a 5.5 in measure, line breaks kept.
- **Instructions / about:** heading, then text wrapped in a 5.5 in measure.
- **Notes:** heading, then ruled writing lines (0.75 pt, gray).
- **Puzzle:** title, theme, framed grid and word list centered together below
  the header. Cells are square, largest whose painted frame fits, capped at 20 pt
  letters; the word list starts 22 pt below the painted frame.
  Words keep their display text and authored order, column-major in up to five
  equal columns.
- **Solutions:** the first page carries the plan's heading. Template by the
  plan's largest group: 1 (1x1), 2 (stacked), 4 (2x2), 6 (2 columns x 3 rows),
  filled in reading order. Each slot has the puzzle title and the puzzle page's
  plan label above its grid. Target letters are bold black inside 1 pt capsule
  outlines from first to last cell; other letters are 55% gray. Shape carries
  the meaning, so it reads in grayscale and crossings remain legible.
- **Blank:** a real, empty PDF page with no folio.

Wrapping is greedy, keeps authored line breaks and collapses runs of spaces. It
never hyphenates, truncates or shrinks; an unbreakable word fails.

## Diagnostics

`InteriorError(stage, issues)`; stages `print_spec`, `integrity`, `layout`,
`layout_validation`, `pdf_verification`, `output`. Each `LayoutIssue` has a
`code`, `message`, logical `page`, `physical_page`, plan `kind`, `subject`
(puzzle ID), `region`, and measured `actual`/`required` values where relevant.

Codes include `unsupported_profile`, `unsupported_trim_size`,
`unsupported_bleed_configuration`, `margin_too_small`, `gutter_too_small`,
`invalid_page_geometry`, `font_too_small`, `line_weight_too_small`,
`incomplete_plan`, `missing_puzzle`, `identity_mismatch`, `digest_mismatch`,
`solution_invalid`, `plan_order`, `unsupported_page_type`,
`unsupported_solution_density`, `solution_layout_unreadable`, `text_overflow`,
`word_list_overflow`, `decoration_overlap`, `frame_crosses_content`,
`grid_too_small`, `unsupported_character`, `page_count_unsupported`, `font_invalid`,
PDF inspection codes (`pdf_*`, `font_not_embedded`) and output codes.

## Integrity and verification

1. The plan is verified by `verify_publication_plan`.
2. Every puzzle and solution entry is bound to the batch report by recomputing
   `puzzle_digest`; IDs alone are not trusted. Incomplete plans, foreign reports
   and mismatches fail; nothing regenerates. Solutions are independently verified.
3. `validate_layout` restates the contract: page order and kind, mirrored margins,
   folios equal to plan labels, empty blanks, grids equal to generated rows, word
   lists, exact solution groups and marks, minimum sizes and strokes, containment
   in the live area and no overlapping elements.
4. After rendering, pypdf reopens the bytes (`inspection.read_pdf_facts`, the
   same observation layer preflight uses) and checks page count, media and trim
   boxes, rotation, annotations, outline, forms, embedded font programs
   (`FontFile2`), empty blank pages and printed folios.

## PDF and determinism

ReportLab draws the layout with invariant mode (fixed 2000-01-01 dates, fixed
document ID), page compression and empty title/author/subject/keywords. Fonts
are embedded as TrueType subsets with deterministic subset names. No
annotations, outlines, links, crop or trim marks.

Renderer version 2 is current. Renderer 1 fitted grid frames without their stroke,
so a width-limited grid (14 x 14 in `cover-demo`) painted 0.5 pt (0.007 in) past
the live area. Version 2 reserves the stroke: grid geometry and PDF bytes change,
pagination, plan and puzzle content do not, and renderer 1 interiors report stale
(`toolchain_current`) until rebuilt. The supported grid sizes are unchanged.

Guarantee: identical project source, profile, engine/renderer version, bundled
fonts and ReportLab version produce byte-identical `interior.pdf` and
`interior.json`. Tests compare bytes within a process and across processes with
different working directories and `PYTHONHASHSEED`. A different ReportLab
release may change bytes; its version is part of the interior identity.

## Output

Files go to the project's `output.directory` (for example
`build/composition-demo/`) or `--output DIR`:

- `interior.pdf`
- `interior.json`: manifest version, book ID, `interior_identity`
  (`pp1-interior-sha256-...` over project identity, plan digest, profile,
  renderer and engine versions, PDF library and font digests), page count, trim,
  PDF SHA-256 and byte size, and warnings. No timestamps or paths.

The writer resolves the directory again at write time and rejects any overlap
with the source directory. It only replaces an interior whose manifest names
the same book; an unowned `interior.pdf` or a foreign manifest is never touched.
Both files are staged beside their targets, fsynced, read back, then moved with
`os.replace`. A failed build writes nothing; a failed write leaves the previous
interior in place and removes staged files. The two replacements are not one
atomic transaction: an interruption between them can pair a new PDF with the
previous manifest, which the manifest's PDF SHA-256 reveals.

## CLI

`puzzlepress book build PROJECT [--output DIR] [--profile ID] [--json]`. Text
output gives paths, page count, trim, profile, interior identity and PDF
SHA-256; warnings go to stderr. JSON: `{success, output{pdf, manifest},
manifest}` or `{success: false, stage, diagnostics}`. Exit 0 success, 1 expected
failure (nothing written), 2 usage. Studio's **Print** tab runs the same build
for saved source; `book preflight` inspects the result ([preflight](preflight.md)).

## Limitations

One trim (8.5 x 11 in, no bleed, black ink; white or cream paper). Fonts are subset-embedded (KDP
recommends, but does not require, full embedding). One sans family with Latin-1
coverage. No PDF/X conformance, color management, color images, hyphenation,
running heads or table of contents; typography is limited to the style's bounded
settings. The KDP page minimum
is a build warning and a preflight readiness failure. Layout never repaginates, so
overflow must be fixed in source or composition. Covers are built from the
interior's facts ([cover](cover.md)); KDP packaging is not implemented.
