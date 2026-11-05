# PuzzlePress current state

## Completed scope

Multi-engine Interval 7 (real-world print validation and production readiness) on
branch `feat/print-validation-production`, cut from main `34efd48` after PR #20;
committed locally, not pushed. Evidence: docs/artwork-validation/.

- Real artwork: 17 drawings approved by the author (pre-1931 US patent drawings
  from NARA scans, Van Gogh drawings, Meyer ornament, Britton & Brown botany, Doré,
  Tenniel), provenance and SHA-256 in `approved.json`; reviewed under defaults,
  cleanup 0.6 + despeckle 2, and + threshold 0.5 (`findings.md`). Finding:
  fine-line retention (and line work kept) is biased by background cleanup on tinted
  paper: 47-89 % measured while 99.3-100 % of the ink still prints. No threshold
  changed; the measure fix waits for the printed proof. Faint drawings on tinted
  paper are no longer called blank (`artwork_empty`, `prepared_blank` wording).
- Proof package: `tests/proof_project.py` builds a NOT FOR SALE 41-page proof and
  cover from the approved files with `sources.json` tracing every page;
  `proof-checklist.md` for the printed copy. Nothing ordered.
- Settings is the one editor for book details in word-search books too (Puzzles,
  Book and Publishing link there); no schema or identity change.
- Produce from Studio (`studio/producing.py`, `Produce.tsx`): background run of the
  unchanged `produce()` into `<output.directory>-release` for the saved revision,
  step progress (new optional `progress` callback; outputs unchanged), success only
  after every listed file is re-verified, cancellation between steps for coloring
  (`ProductionCancelled`, previous release kept), downloads and the package ZIP from
  verified bytes, stale by build identity.
- Print profiles `paperback-6x9`, `-8x10`, `-8.5x8.5` (+ `-cream`) from KDP's
  standard table, black ink, no bleed, the 8.5 x 11 gutter; covers wrap every trim;
  Studio offers trim and paper together. Bleed assessed, not built. 8.5 x 11 unchanged.
- PR #21 (separate, from main): the journey spec's CI timeout diagnostics.

Earlier: multi-engine Interval 6 (visual book authoring and Studio UX), merged as
PR #20. Walkthrough: docs/studio-coloring-walkthrough.md.

- Creation (`creation.py`, `creation_cli.py`, `studio/creating.py`): `puzzlepress
  book new FOLDER --type word_search|coloring --title ...` and Studio **New book**
  (`/create`, GET `/api/project-types`, POST `/api/projects` under the save lock).
  Keys are lowercase hyphenated names directly in the library; exclusive `mkdir`,
  creation marker, staged and read-back `book.yaml`; a failure removes only what it
  wrote; an interrupted creation (marker plus staging files only) is recognised and
  replaced (`recovered`); anything else is `project_exists`. Word search starts
  with one puzzle titled "Starter puzzle: replace before publishing"; coloring
  starts with no artwork (plan reports `no_coloring_pages`). Seed derived from the
  key and written out; output `../../build/<key>`.
- Optional `catalog` {subject, collection} (Library only, outside every identity)
  and `print` {profile} (in build identity when present; book build, produce and
  Studio print/rebuild use it; a different explicit profile is `profile_conflict`).
  Absent sections change no bytes or identities.
- Coloring placement: `coloring.pages[].placement` {scale 0.5..1, x, y -1..1};
  centred normalizes to none. `place_art` default path unchanged (renderer 1); the
  validator checks each drawing is where its page puts it (`artwork_placement`).
  Lossless: same pixels, smaller, higher effective DPI. Draft plans carry Python's
  placed boxes (`placements`).
- Studio: Settings (both engines; coloring book details only there, word-search
  title/language stay in Puzzles and title-page details in Book, linked); Pages
  designer (select, zoomable page view, replace drawing, placement sliders,
  centre/reset, duplicate, insert divider); `history.ts` scoped undo/redo with
  grouped gestures and Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y outside text fields, cleared
  on save/reload/revert; `viewport.tsx`/`zoom.ts` Fit page, Fit width, steps, Reset
  view, drag/keyboard pan (no re-render); Print proof gains Fit width, Reset view,
  drag pan, `+ - 0`, and shows a book's own paper. Coloring Overview lists the
  journey and why an empty book cannot pass. Library and app bar link New book.
- Production lock (`production/lock.py`): OS lock (flock / msvcrt.locking) on
  `.<output>.produce.lock`, released by the kernel on process death; live holder
  refused with process and host; abandoned same-host record reclaimed and reported
  (stderr `Recovered:`); empty, unreadable or other-host records refused, never
  removed. Coloring produce restores a previous output an interrupted swap moved
  aside and removes this output's own staging/backup folders (now named after the
  output). Word-search produce takes the same lock; its outputs are unchanged.
- Memo review: keys hold source digest, settings, preparation version, Pillow (plus
  deflate level and zlib build for packed pixels); originals are read and verified
  before lookup; bounded (4096 entries; 256 MB packed). Tests added.
- `tests/artwork_review.py` (review harness: images, measures, print-size PDF,
  review.md with human fields "not recorded"); `tests/coloring_benchmark.py`.
- Fixed: main's Linux CI failure (run 41849615371) in
  `test_frontend_fixtures_match_the_engine_output` (platform-dependent PNG digests
  of synthetic drawings; compared without them).

Earlier: multi-engine Interval 5 (coloring covers, publishing, production and the
Studio Pages composer), merged as PR #19. Guide: docs/coloring-publishing.md.

- Coloring books take the shared `cover` and `publishing` sections (interior style
  stays word search). The cover pipeline is unchanged: wrap and spine from the built
  coloring interior's page count and the profile's paper.
- Template variables: `{artwork_count}` is an apply-time binding; `{page_count}` and
  `{trim_size}` are live variables (`cover/variables.py`) kept in the text and
  filled in by the cover layout from the verified interior, so a page-count change
  re-renders the number with the spine and stales the cover. Existing covers and
  templates keep their bytes. Studio warns about a binding typed into a text box.
- Publishing: separate ruleset `puzzlepress-kdp-publishing-coloring` v1 (word-search
  reports, packages and identities unchanged). Adds `ai_disclosure.interior_artwork`
  / `cover_artwork` (written only when present), `content_rights` (own work,
  commissioned, licensed, public domain, AI tool terms, cover `none`), rules
  `artwork_origin_declared`, `artwork_origin_consistent`, `content_rights_declared`,
  `content_rights_review`, coloring low-content wording and drawing-count claims.
  The rights review identity covers artwork digests and captions, dividers and the
  declaration. KDP Content Guidelines and Low-Content Books pages re-read
  2026-11-04; the AI form's option wording was not found on an official page and
  is not modeled.
- `book produce` for coloring (`production/coloring.py`): interior, cover, both
  preflights, `artwork-integrity.json`, `artwork-duplicates.json/.md`, readiness,
  KDP metadata, package under `publishing/` only when ready, validation and
  `production.json` v2 (engine, environment, status, guarantee statement). Staged in
  a sibling directory, verified, swapped; lock file against concurrent runs.
  Word-search options refused for coloring books. Word-search production unchanged.
- Light strokes (gray 129-200, stroke-like, not an anti-aliased rim) are measured;
  `faint_strokes_erased` warning under `coloring_line_quality`; coloring preflight
  ruleset 2; orange in the difference view. In-process memos (`coloring/memo.py`)
  for measures and packed pixels keyed by content address (plus deflate level and
  zlib build for packed bytes).
- Studio: coloring navigation Overview, Artwork, Pages, Cover, Print proof,
  Publishing; one draft for Pages/Cover/Publishing. Pages composer
  (`ColoringPages.tsx`): reorder by drag or buttons, add, repeat, remove, dividers,
  matter, layout, numbering, undo; Python plan preview with spreads, automatic
  blanks, numbers and live area/art box from Python geometry; built-interior state.
  Draft plans of coloring books return incomplete plans with reasons and geometry.
- Fixed: the router swallowed download links (template Export; reproduced in a
  browser, now left to the browser); the JPEG interior path re-registered one
  photograph on a second page (`redefining named object`).

Earlier: multi-engine Interval 4 (coloring composition, lossless interior, coloring
preflight) on branch `feat/multi-engine-coloring`, merged as PR #18. Guide:
docs/coloring.md (Composition and page parity, Interior, Preflight).

- Composition for coloring books: front matter, `artwork.start` (recto default),
  back matter, page numbers with `show_artwork`; puzzle and solution settings are
  `not_applicable_for_engine`. `coloring.pages` takes `{divider: {title, text?}}`.
  Cover, publishing and interior style stayed refused for coloring books in that
  interval, and `book produce` refused them (Interval 5 adds all but interior style).
- `coloring/content.py`: used originals read and verified, prepared with saved
  settings (`prepared_pixels`, the preview pipeline without measures), kept as
  packed deflated samples (1 bit when two-level, else 8). `coloring/plan.py`: plan
  with explicit blanks (`section_recto_start`, `artwork_recto_start`,
  `divider_recto_start`, `reverse_blank`) and an independent verifier (order,
  parity, reverse blanks, prepared digests, numbering). Registry holds both engines;
  content is engine-specific (`EngineContent`) and callers narrow it.
- `interior/coloring.py`: layout reusing the classic matter and divider templates;
  art contain-fitted and centred in the live area above the folio band, inside an
  optional thin or double border; `ImageBlock.encoding` `lossless` embedded as
  FlateDecode DeviceGray, once per document; every embedded image decoded again and
  compared with its prepared digest. The renderer refuses unknown elements and
  mismatched encodings. Coloring manifest: `coloring` identity input (renderer and
  preparation versions, Pillow, zlib implementation), artwork records, composition
  counts, environment (traceability only). Word-search manifests, identities and
  outputs are unchanged.
- `preflight/coloring.py`: ruleset `puzzlepress-kdp-coloring` v1 (55 rules; shared
  rules reused by code). Rendering environment, image integrity, artwork sources,
  parity, placement, DPI with pixels needed, line quality from the preparation
  measures, duplicates; look-alike art and large changes are `info`, presented as
  manual review. The shared severity scale and ruleset are unchanged.
- Preparation gains `line_core_level` and `faint_lines` (warning; found in the
  sample review). Studio: coloring Print proof (thumbnails of every page, blank
  backs, overlays, findings, `GET /interior/pdf` export, stale banner). Samples:
  `tests/coloring_samples.py`; previews in `docs/images/coloring/interior-*.png`.
- Fixed in passing: `write_interior`'s read-back check now fails as `write_failed`
  under a concurrent writer instead of a raw PermissionError (Windows).

Earlier: multi-engine Interval 3 (line-art preparation), on the same branch.

- `coloring/prepare.py`: in-memory pipeline over the verified original (luma or
  darkest-channel gray, invert, brightness/contrast, background cleanup, despeckle
  of isolated marks only, threshold, line weight). Defaults return the original's
  gray levels exactly. `PREPARATION_VERSION` 1; content address
  `pp1-prepared-sha256-` over source digest, settings, version and Pillow version.
  Bounds: 40 MP, 3 M ink pixels per scan (`not_measured` or an explicit error).
- Measures against the unadjusted original: fine-line (opening-based) and line-work
  retention, strokes on shared ink, isolated specks, paper level, ink, new edge
  contact, mean change; findings with blocking and warning severities, thresholds
  calibrated on synthetic fixtures (table in the guide; speck warning lowered to
  5/MP after visual review of `docs/images/coloring/preparation-samples.png`).
- `coloring/components.py`: run-length 8-connected labeling with union-find and
  isolation within 6 px (checked against a flood fill).
- `invert` adjustment, serialized only when true (Interval 2 books keep their
  bytes). `validate_adjustments`, `prepare_entry`, `with_adjustments`,
  `adjust_artwork` (revision-checked through `replace_source`).
- CLI `coloring prepare` (preview, `--set`, `--reset`, `--output` outside the book)
  and `coloring adjust`. Studio: Prepare line art panel (debounced, numbered
  previews; original/prepared/difference; findings; Save, Reset, Revert); API
  POST `/coloring/prepare`, GET `/coloring/prepared/{key}/{kind}` (in-memory cache
  per project), POST `/coloring/adjustments`.
- Main CI repair (`883c64c` on local `fix/artwork-stem-python-314`, cherry-picked
  here as `47c54d3`): artwork stems split without `pathlib` (Python 3.14 changed
  `stem` for dot-heavy names), and the golden PDF gate also needs the same zlib
  family (Python 3.14 on Windows links zlib-ng, which compresses streams to other
  bytes). Baseline version 3 records classic zlib; pinned values unchanged.

Earlier: multi-engine Interval 2 (coloring schema, artwork import and library),
merged to main as PR #16. Guide: docs/coloring.md.

- `coloring_config`/`coloring_validation`: optional `coloring` (version 1) with
  artwork (id, `coloring-assets/<stem>-<sha12>.png|jpg`, full SHA-256, title,
  adjustments recorded but not applied), ordered pages and layout (`blank_reverse`
  true, `border` none|thin|double). Defaults normalized; part of build identity with
  envelope `coloring_version: 1`. Not with `word_search` (`engine_conflict`) or
  `composition` (`not_available_for_engine`), so no cover/interior/publishing.
  Caps 300 artwork / 300 pages are provisional (nothing built yet).
- Coloring is loadable: `engine_for` refuses it (`engine_not_buildable`), so `book
  plan|build|preflight|produce` exit 1 without a traceback; `inspect` shows artwork
  and page counts. `LABELS` names book types apart from the build registry.
- `coloring/`: `inspection` (PNG/JPEG by content; SVG refused `svg_not_supported`;
  empty, corrupt, other formats, >64 MB, >80 MP, 16-bit refused; facts and findings,
  effective DPI fitted to the 7.25 x 9.75 in live area; blocking <150 DPI and
  blank; warnings <300 DPI, gray paper, color, transparency, CMYK, shape, edge
  contact), `assets` (content-addressed, staged, fsynced, linked, never overwritten,
  digest-checked reads inside the resolved project), `duplicates` (confirmed
  same-file and repeated pages apart from a dHash + gray-map heuristic), `library`
  (all-or-nothing batch import, reimport adds nothing, removal keeps the file).
  `source_store.replace_source`: the CLI's revision-checked book.yaml writer (the
  same contract as Studio's save). The asset library lists artwork with its uses and
  trashes only unreferenced files to `coloring-assets/.trash/`.
- CLI `coloring import|list|inspect|duplicates|remove`. Studio: a coloring book has
  Overview and Artwork only (no word-search terms); API GET `/coloring`, POST
  `/coloring/artwork` (raw body; SVG and unlabeled bodies pass the upload guard so
  Python explains them), POST `/coloring/remove`, GET `/coloring/thumbnail`.
- Golden baseline v2 (fix): version 1's Windows normalization also rewrote JSON
  escapes in `book plan --json` and `puzzle batch --json`, so main's Linux CI failed
  after PR #15 (run 41772806080). Re-recorded from the pre-refactor engine with the
  corrected harness: exactly those five digests changed and equal Linux CI's values.
  PDF files are now compared when ReportLab, Pillow and PyYAML match (pypdf only
  reads PDFs), so Linux CI compares PDF bytes too.

Earlier: multi-engine Interval 1 (foundation), merged to main as PR #15.

- `engines/kind.py`: `EngineKind` (word_search, coloring), derived from the content
  section and never stored. Every existing project, legacy ones included, is
  word_search. `detect_engine` on raw source: `engine_conflict` (both sections);
  `engine_unavailable` remains for a recognised engine a version cannot load.
  Word-search validation issues and their order are unchanged.
- `Project.engine` is a property, so `to_dict`, YAML and build identity are untouched.
- `engines/registry.py`: `ContentEngine` protocol (kind, label, build_publication,
  verify_publication) and `WordSearchEngine`, which delegates to the existing
  functions. `engine_for(project)` dispatches `book plan`, `book build`,
  `sample_interior`, Studio plan previews and print samples. Produce, readiness,
  cover and preflight are unchanged (they consume the built interior).
- `inspect` prints `Engine: word_search (Word search)`. Studio project detail adds
  `engine` {kind, label}; Library rows show Type and Overview shows Book type.
  Navigation is unchanged.
- Golden baseline (`tests/golden_baseline.py`, `tests/fixtures/golden/baseline.json`,
  `tests/test_golden_baseline.py`): recorded from the unchanged engine (commit
  a9e076a) for the four demos, the legacy fixture and the synthetic production book:
  build identities, `validate`, `puzzle batch --json`, `book plan --json`, interior
  PDF/manifest, interior and cover preflight JSON, cover PDF/manifest, publishing
  validate/inspect JSON, every `book produce` file and `puzzle generate`, with exit
  codes and stderr. Two runs with different hash seeds, working directories and
  scratch roots agree. Human-readable stdout prints absolute paths, so the scratch
  root and separators are normalized there only. PDF-dependent values are compared
  only under the recorded ReportLab 5.0.1, Pillow 12.3.0, pypdf 6.19.0, PyYAML
  6.0.3 (skipped with a reason otherwise); source-only values always.

Earlier: production run and previous-book checks on branch `feat/automotive-book-production`
(guide: docs/production-run.md). Engine only; real books stay in puzzlepress-books.

- `inventory.py`: puzzle inventories from a project (regenerated, authoritative), an
  interior PDF (pypdf text positions; a page counts only when every listed word is
  found in its grid) or saved JSON (`inventory_version` 1, strict). Coverage
  complete | incomplete | unconfirmed; a PDF is complete only with a matching
  `--expected-puzzles` and no unverified, image-only or unreadable page.
- `duplicates.py`: exact (equal word sets, equal grids under the 8 symmetries) and
  near (Jaccard 0.6, overlap 0.8 with 3 shared, grid agreement 0.5; configurable)
  against previous books and within the book; replacement recommendations;
  `clean` needs complete coverage. CLI `puzzle inventory`, `puzzle compare`.
- `answer_key.py`: reads the built PDF back; each puzzle needs one solution grid
  with equal letters whose bold letters spell every word and nothing else.
- `photo_manifest.py` + `cover photos`: explicitly listed files only (no scanning),
  read-only checks (format, pixels, aspect, cover-fit DPI: <300 warns, <150 errors),
  optional import through `import_photo`. Windows drive paths on other systems are
  reported, not guessed.
- Cover `watermark` (versions 2 and 3; `cover/watermark.py`): text, opacity,
  9 positions, scale (fraction of front width), margin, shadow, color; baked into
  the photo's derived pixels in Vera Sans Bold; disabled renders identical bytes.
  Blocking: outside front safe area, within 4 pt of cover text, not over one photo.
  Studio has no watermark controls; template application/conversion may drop it.
- `production/produce.py` + `book produce`: interior, preflight, cover and cover
  preflight (when configured), duplicate report, photo check, publishing validation
  (blocking / warnings / manual review / verified) and `production.json` (no times)
  into a directory disjoint from the project and every previous source.
- Checks: 1,807 tests (1 Windows-only skipped) on Linux, Python 3.13; Windows only through CI.

## Earlier completed scope

Interior design studio on branch `feat/interior-design-studio` from main
`dafaba2`; committed, not pushed; no PR, tag, release or deployment. Guide:
docs/interior-design.md.

- Answers: `composition.solutions.per_page` 1|2|4|6|8 per printed page, **4 when
  omitted** (was 1; books that omitted it repaginate and report stale). Template 8
  is 2x4 with letters 68% of the cell (others 56%, unchanged). A density below the
  7 pt solution minimum fails once as `solution_layout_unreadable`, naming the
  densest choice that fits; the count is never changed. `answer_fits` /
  `answer_layouts` measure every choice with the renderer's own slot geometry.
  `dense_solution_page` warns below 7.5 pt.
- Spreads: `composition.puzzles.layout` single|spread (only `spread` is written).
  Spread = `puzzle_words` verso facing the `puzzle` grid recto; blank
  `spread_verso_start` aligns it; cross-references name the grid page; recto
  puzzle start needs dividers (`spread_starts_verso`). Verified by
  `publication_verification` (`_check_spreads`); statistics count both pages.
- Interior style version 2: `theme` (classic, racing_orange, classic_garage,
  editorial_minimal, high_contrast, ink_saver) and `layout` (classic, bold_header,
  clean_minimal, large_readability) instead of `preset`; `colors` {accent,
  secondary} #rrggbb printed as Rec. 601 gray; look overrides `banner`, `corners`,
  `background`, `motif`, `motif_intensity`, `density`, `folio_style`; puzzle
  pages add `word_position`, `word_align`, `word_weight`, `letter_scale`,
  `grid_width`, `puzzle_number`, `answer_reference` (authored text with one
  `{page}`); solution pages add `page_label`. Resolved into `InteriorDesign.look`
  (`look_version` 1), absent for version 1 and no style, so those identities hold.
  Version 2 classic+classic renders the same bytes as no style.
- Renderer: rounded `Panel`s and grid frames, filled `Polygon` motifs in a band on
  the outer side, page frame, header band, banners (section headings, and puzzle
  titles with bold_header), folio rule/outline. Validation adds
  `decoration_overlap`, `frame_crosses_content`; stroked panels over grids fail.
  DeviceGray only. Renderer version unchanged (existing output identical).
- Preflight ruleset 4: warning `design_legibility` (dense solutions, `light_text`,
  `low_contrast_text`, `heavy_ink_coverage`). Package identity includes the
  ruleset version, so packages exported before report stale.
- Design files (`interior_design_file`): `puzzlepress-interior-design` v1 JSON,
  <=64 KB, interior section only (no photos, book details or composition);
  import keeps the draft's photos and validates with the book schema.
- Studio Interior: tabs Page layout, Answer layout (choices with Python's letter
  size and Fits/Cramped/Too small, answer page counts), Theme (catalogue from
  `GET /api/interior/designs`, accents with printed gray, treatments, design file
  export/import), Title & dividers; preview by role (spread, puzzle, answers, last
  answers, divider, instructions, title); "What saving changes" note; resets per
  section and whole design. Book (Composer) no longer edits per_page; it links here.

Earlier: cover templates, rich text and Studio fixes (Interval 12.3), branch
`feat/cover-templates-rich-text`, merged to main as PR #9. Guide:
docs/cover-templates-rich-text.md.

- Templates (`cover_template`, `cover_template_store`, `cover/templates/*.json`):
  versioned JSON (`template_version` 1, <=256 KB) holding a version 3 design with
  photo slots (<=4), `requires_slot` and book bindings; eight original built-ins
  (Photographic Editorial leads); project templates in `cover-templates/<id>.json`
  (<=100) with atomic, identity-checked save, rename, duplicate, delete, import
  and export; built-ins protected; imported fonts checked by path and SHA-256.
  Applying replaces only the design, keeps book details, overrides, back text,
  extras, fonts and photographs, and turns a missing required photo into a
  reported placeholder.
- Rich text (`cover_richtext`, `cover/richtext`): blocks and runs (bold, italic,
  underline, size, family, colour; alignment, lists, heading, spacing, breaks),
  <=40 blocks x 80 runs, in `back_text` (v2+) and text boxes (`rich`, v3).
  Measured layout; `text_overflow`, `text_box_overflow`,
  `unsupported_character`, `font_variant_unavailable`; never clipped or faked.
  Unformatted documents are stored as strings and render identical bytes; other
  checks read the plain words.
- Studio: Templates tab (Python thumbnails, preview dialog, Apply into the
  undoable draft, save/duplicate/rename/export/delete/import), rich text editor,
  sectioned text inspector, Editing region heading, labelled Preview group,
  legacy conversion banner, Fit selection, safe-area snapping, overlay menu
  within the window, photo library Remove and Used-by links, asset status chips,
  Blocking/Advisory checks with advisory `low_contrast` and
  `template_photo_placeholder`. Interior previews retry while Studio is briefly
  busy. API: GET /cover/templates, POST /draft/cover/templates/{id}/preview,
  POST /cover/templates (save), /import, /{id}/update, /{id}/duplicate,
  /{id}/delete, GET /{id}/export.

Engine, build identity, renderer, cover renderer and profile, publishing and
planning versions unchanged; demo interiors and covers are byte-identical to
main with equal identities.

Earlier: production design and publishing polish (Interval 12.2), branch
`feat/production-design-publishing-polish`, merged to main as PR #8. Guide:
docs/production-design-polish.md.

- Cover version 3 (`cover_design`, `cover_design_validation`, `cover/design`,
  `cover/convert`): back/spine/front regions (color, optional two-stop gradient)
  and up to 24 stacked elements (photo <=4, rect, ellipse, line, text box) in points
  from each region's bottom-left trim corner. Strokes are filled even-odd rings;
  opacity is flattened by Python against one solid color or baked into one photo,
  else `opacity_not_flattenable`. Layout issues `text_overflow`,
  `spine_element_outside`, `element_outside_media`; warnings `spine_color_at_fold`,
  `spine_element_at_fold`, `element_under_barcode`. Cover preflight ruleset 3 adds
  `kdp_spine_design` and `kdp_barcode_design` (warnings). Explicit
  `convert_to_regions` renders identical bytes (identity changes); four design
  presets. Versions 1/2 unchanged.
- Asset library (`asset_library`, `studio/assets`): photos and fonts with uses in
  saved source and draft; unused assets move atomically to `cover-assets/.trash/`
  (restore, purge as a second step); `asset_in_use`, `asset_changed`,
  `asset_collision`, `asset_unsafe`; save lock held while moving.
- Interior styles (`interior_style`, `interior_style_validation`,
  `interior/design`, `interior/images`): optional `interior` v1 with presets
  classic/editorial/modern/high_contrast and bounded overrides; title layouts
  minimal/editorial/color_block/framed/photo_feature; DeviceGray tints; grayscale
  photographs (luma, DeviceGray JPEG, no metadata). Outside build identity; the
  resolved design (v1) is the manifest `style` input. `sample_interior` renders
  the first page of each kind for previews. Interior preflight ruleset 3:
  `raster_images` attributes images to the layout, `kdp_image_resolution`
  measures DPI from it.
- Theme dividers (`composition.puzzles.dividers`): `divider` plan pages before
  each theme group, start any/recto (`divider_recto_start` blank), author text
  only, `themes_not_contiguous`, `unknown_theme`, `divider_pages` statistic only
  when non-zero; verified by `publication_verification`.
- Editorial review (`editorial`, `sidecar`): `reviews.yaml` beside book.yaml,
  identity `pp1-puzzle-review-sha256-` over book ID, puzzle ID, title, theme,
  profile grid/directions and ordered words; states not_reviewed, reviewed,
  needs_changes, stale; optional `require_all` policy (internal gate).
- Proof records (`proofing`): `proofs.yaml`, print_previewer / physical_proof,
  bound to interior and cover identities and PDF digests, stale when either
  changes; decisions only as typed.
- Production (`production/artifacts`, `rebuild`, `guidance`; `studio/production`):
  dependency assessment from the readiness report, minimal rebuild plans
  (cover-only, nothing for metadata/reviews, conditional cover after interior),
  verified one-step-at-a-time rebuilds with `before_write` source checks
  (`source_changed`), and an overview with kinds internal / kdp_modeled /
  author_judgment / external, six statuses, stages and ten proofing steps.
- Studio: Interior page; Cover region picker and Layers, Shapes, Assets tabs,
  convert dialog, element inspector; review row, filters and Next unreviewed in
  Puzzles; stale banner and rebuild panel in Print; Final steps and proof records
  in Publishing. API rows in docs/studio.md.

Engine 0.1.0; build identity, pipeline, composition (dividers additive), plan,
print profile, renderer (2), cover renderer (1), cover profile (1), publishing
schema, package and planning versions unchanged. Every demo and the synthetic
production book build byte-identical interiors and covers with unchanged
identities (compared against main).

## Architecture and launch

- Python core is pure and authoritative. Runtime deps: PyYAML, ReportLab 5.0.x
  (BSD), pypdf 6.x (BSD-3), Pillow 12.x (MIT-CMU; now declared, `>=12,<13`). Dev adds
  types-reportlab. Studio extras FastAPI/uvicorn; web tests httpx. React/strict
  TypeScript/Vite, locally bundled fonts.
- Pipeline: project -> batch -> quality -> composition -> plan -> verification ->
  digest binding -> layout -> layout validation -> PDF -> pypdf inspection -> write.
- Core: `composition.py`, `composition_validation.py`, `publication.py`,
  `publication_verification.py`, `book_cli.py` (plan, build). Print engine in
  `interior/`: `spec` (profiles, points, `KdpConstraints`), `fonts` (bundled Vera
  Sans, pinned SHA-256), `text` (wrap), `geometry`, `engine` (layout),
  `validation`, `render` (ReportLab), `inspection` (pypdf), `build` (pipeline,
  manifest, only writer), `issues`, `model`. CLI imports it lazily.
- Preflight in `preflight/`: `model` (Rule, Finding, Measure, RuleResult,
  PreflightReport, versions), `context` (artifact reading, manifest parsing,
  Context), `rules` (catalogue, 41 rules), `engine` (`preflight_interior`).
  `interior.inspection.read_pdf_facts` is the single pypdf fact layer shared by
  the post-build check and preflight. `interior.build` stays the only writer
  (adds `write_preflight_report`, `interior_identity`, `toolchain`).
- Cover: `cover_config.py`/`cover_validation.py` (schema) and `cover/` (`assets`,
  `crop`, `geometry`, `fonts`, `font_assets`, `layout`, `model`, `validation`, `render`,
  `inspection`, `build` = only writer, `preflight`); `cover_cli.py`.
- Publishing: `publishing_config.py`/`publishing_validation.py` (schema) and
  `publishing/` (`model`, `rules` = catalogue and the one home of KDP metadata
  values, `isbn`, `text`, `identity`, `review` (confirmation review identities),
  `metadata`, `readiness`, `provenance`,
  `submission`, `package` = only writer); `publish_cli.py`; `studio/publishing.py`;
  `Publishing.tsx`.
- Planning: `planning/` (`model`, `schema`, `identity`, `store` = only writer of
  planning.yaml, `rules` = catalogue, `vocabulary`, `analysis`, `feasibility`,
  `readiness` (state, approval), `handoff`); `planning_cli.py`; `studio/planning.py`;
  `Planning.tsx`, `planning-draft.ts`, `planning-fields.tsx`, `planning-visuals.tsx`.
- Studio: `printing.py` (status/build/page adapter, profile choice), `preview.py`
  (PDFium raster, one process-wide lock), `covering.py` (cover adapter); `Print.tsx`,
  `Cover.tsx` (with `cover-model.ts`, `cover-canvas.tsx`, `cover-tools.tsx`,
  `cover-inspector.tsx`), `publishing-checklist.tsx` plus `service.py`,
  `editing.py`, `draft.tsx` etc.
- Build `cd studio; npm ci; npm run build`; launch from root
  `.\.venv\Scripts\puzzlepress-studio.exe` (http://127.0.0.1:8000/books).

## Print interior

- Profiles `paperback-8.5x11` v2 (white, default) and `paperback-8.5x11-cream` v1,
  both black ink, paper stated explicitly (v1 interiors now report stale; page
  geometry and PDF bytes identical, identity differs). Shared geometry: 612x792 pt, no bleed (rejected), margins
  inside 0.75 / outside 0.5 / top+bottom 0.625 in, gray ink, centered folios
  (`outside` supported). Spec is renderer-facing, not authored YAML; `--profile`.
- KDP rules centralized (verified on KDP help 2026-10): gutter table to 828 pages,
  0.25 in outer margins, 7 pt text, 0.75 pt lines, 24-page minimum (warning only;
  renderer never pads). Physical pages = plan pages. Gutter fixed, validated
  against count, never enlarged.
- Layout (renderer 2): one PhysicalPage per plan entry; elements TextLine/Rule/
  LetterGrid (with SolutionMark capsules); 24 pt folio band. Element `bounds` are
  painted extents; grids fit by frame plus half stroke. Solution template from plan's
  largest group: 1, 2 stacked, 2x2, 2x3, 2x4 (compact cells). Puzzle letters 9-20
  pt, solutions 7-14.
- Failures are `InteriorError(stage, LayoutIssue...)` with page, physical page,
  kind, subject, region, actual/required. Overflow, tiny grids, unbreakable words,
  missing glyphs, digest mismatch, incomplete plan, foreign report, unknown kind,
  bad order, density >6, bad spec: fail, never repaginate/regroup/shrink.
- Determinism: ReportLab invariant mode, empty metadata, subset fonts. Same source,
  profile, versions, fonts and ReportLab version give byte-identical PDF and
  manifest (tested across process, cwd, PYTHONHASHSEED).
- Output: `output.directory` or `--output`: `interior.pdf`, `interior.json` (interior
  identity, plan digest, profile, versions, fonts, PDF SHA-256, warnings; no time).
  Rechecks source disjointness at write; replaces only same-book manifests; staged,
  fsynced, read back, `os.replace`; failed builds write nothing.

## Preflight (docs/preflight.md)

- Observational: reads `interior.pdf`/`interior.json` (fixed names, no symlinks),
  rebuilds the expected interior in memory via `build_interior`, compares. Never
  mutates plan, layout, PDF, manifest or source. Writes only `preflight.json`.
- Structural valid = no structural error rule failed or unevaluated. KDP ready =
  structurally valid and no KDP error rule failed or unevaluated. Warnings never
  block. Layout rules run only if PDF bytes equal a fresh render
  (`pdf_matches_layout`), else `not_evaluated`. Stale = source/plan/profile/
  toolchain rule failed; mismatched PDF/manifest = invalid.
- KDP rules (values in `spec.KdpConstraints`, read on official KDP help
  2026-10-07): min 24 pages, max 550 (8.5x11; official table omits the row,
  indexed copy 590 white/550 cream: ambiguous), trim range, single trim pages,
  no bleed, gutter table, 0.25 in outside, 7 pt, 0.75 pt, embedded fonts, full
  embedding (warning, ambiguous), no annotations/bookmarks/forms, not encrypted,
  flattened, no slug area (`kdp_no_printer_marks`), 300 DPI images (n/a without
  images), blank runs
  4/10, even folios on verso, descriptive metadata (warning). Margins measured
  from element ink bounds. Structural `content_in_live_area` checks painted extents
  against the profile live area. Ruleset 4; identities unaffected by rulesets.
- composition-demo: structurally valid, NOT KDP ready (only error
  `kdp_minimum_page_count`, warning `kdp_full_font_embedding`). 16-puzzle
  variant (29 pages) is ready (tested).
- CLI `book preflight PROJECT [--output DIR] [--json] [--no-write]`: exit 0 valid
  and ready, 1 otherwise, 2 usage; `--json` bytes equal `preflight.json`.
- Studio Print tab (`/books/{key}/print`): Build interior (saved revision only;
  dirty draft disables it), verdict line, thumbnails (lazy), single/spread view
  (page 1 alone right), zoom fit/50-300%, keyboard on canvas, overlays (live area,
  KDP minimum margins, element bounds, finding regions; Python boxes, SVG only),
  findings linked to pages, passed/n.a./not-evaluated disclosures, stale/invalid
  notes. API: GET `/interior`, POST `/interior/build {revision}`, GET
  `/interior/pages/{n}?size=thumb|page|detail&pdf=<sha256>` (409 `preview_stale`).
  Print reads wait up to 60 s for the generation lock; drafts still 409.
- Preview: pypdfium2 rasters of the exact PDF bytes, scales 0.5/2/4 (306x396,
  1224x1584, 2448x3168), lossless PNG, in-memory LRU 96 MB keyed by PDF digest,
  page, size; one PDFium lock; digest URLs cached `private, immutable`.

## Cover (docs/cover.md)

- Version 2 (text layers): per-layer overrides for title, subtitle, author, back text
  and imprint (visible, display text, font, size, color, align, spacing, case,
  offset), up to 8 extra text layers and 8 imported static TrueType fonts with
  author-recorded license; hiding text never changes `book`. Version 3: see
  Completed scope.
- Config: optional `cover` (version 1, 2 or 3; see docs/cover.md) in book.yaml, requires composition,
  excluded from build identity. layout full_wrap|front_photo; image {path
  `cover-assets/<name>.jpg|png`, sha256}; crop {x, y 0..1, zoom 1..4, 4 dp};
  type {style editorial|bold|minimal, position top|middle|bottom, align
  center|left, tone light|dark}; legibility shade|panel|none; background #rrggbb;
  spine_text auto|none; back_text <=1,200. Copy = book title/subtitle/author/imprint.
- Photos: import copies original bytes, content-addressed, never overwrites, reuses
  identical bytes. JPEG/PNG <=64 MB, <=80 MP. Decode once: EXIF orientation,
  ICC->sRGB (LittleCMS), 8-bit RGB, opaque only. PDF gets a bare-pixel baseline
  JPEG q95 4:4:4 (JFIF only), DCTDecode unchanged (no ASCII85). No EXIF/GPS/XMP/ICC.
- Crop: cover-fit uniform scale x zoom, focal clamped; whole source pixels drawn,
  clipped, no resampling. Effective DPI = used pixels / printed inches;
  ok | image_low_effective_dpi | image_too_small.
- Geometry from a current interior only (manifest digest, identity, source,
  profile, toolchain; pages counted in the PDF). Wrap = 0.125 + W + spine + W +
  0.125; spine = pages x 0.002252 (white) / 0.0025 (cream). KDP safe 0.125 in;
  spine 0.0625 in; type area 0.5 in; barcode 2x1.2 in at 0.25 in from bottom/fold
  (offsets assumed) with keep-clear corner. Spine text from 80 pages (stricter of
  KDP's contradictory wording) and only if 7 pt fits; else omitted with reason.
- Fonts: Vera Sans + Newsreader 72pt Regular, 16pt Regular/Italic (OFL 1.1,
  upstream commit cfcb4f7, pinned SHA-256). Titles step 2 pt within preset, <=3 lines.
- Identity `pp1-cover-sha256-` over book ID, semantic config (photo by digest),
  copy, interior physical facts, cover profile v1, toolchain (renderer v1, engine,
  ReportLab, Pillow, fonts). Provenance (interior identity, PDF digest, photo path)
  is recorded, not identity: a rebuilt interior with equal facts only warns.
- Output beside the interior: cover.pdf (1 page, MediaBox=BleedBox=wrap,
  TrimBox=trim, DeviceRGB, no strokes/marks/annotations/metadata), cover.json,
  cover-preflight.json. Byte-identical across process, cwd, PYTHONHASHSEED.
- Cover preflight ruleset `puzzlepress-kdp-cover` v2, 27 rules (11 structural,
  16 KDP; warnings: provenance, 40 MB, RGB vs CMYK, font license). States no_config, missing,
  current, stale, invalid. Never writes except cover-preflight.json.
- CLI `cover inspect|import|build|preflight` (`--output`, `--json`, `--no-write`);
  exit 0/1/2 as book commands; preflight 0 only when valid and ready.
- Studio Cover: shared draft; debounced POST /draft/cover renders the real PDF
  in memory (stale interior labeled, damaged refused; invalid moved text previews
  but is not buildable); tools | canvas | inspector at 1200 px+, canvas + tabbed
  panel at 800-1199, stacked below; PDFium raster views (wrap/front/spine/back),
  zoom fit-400%, Python-geometry overlays, layer selection, drag with centre
  snapping and safe-area outline, arrow nudges (1/10 pt), Escape, Undo; the photo
  drags/keys only once selected; print-quality panel; build saved revision only.
  API: GET /cover, POST /draft/cover, GET /cover/preview, GET/POST
  /cover/assets, GET /cover/assets/thumbnail, GET/POST /cover/fonts (raw
  font/ttf|otf), GET /cover/fonts/specimen, POST /cover/build. Print: paper
  choice, keeps the built profile.
- Fixtures: `books/cover-demo` (20 puzzles, 35 pages, synthetic stand-in photo from
  tests/cover_demo_photo.py): cover valid and KDP ready (interior is not; see
  verification), spine text omitted. Real long interiors: a 95-page white-paper
  book (0.2139 in spine) reaches 80 pages but omits spine text as
  `spine_too_narrow` (tested on the synthetic production book); a synthetic
  152-page book printed it at 14 pt (measured).

## Publishing (docs/publishing.md)

- Optional `publishing` (version 2; 1 read as legacy) in book.yaml, requires composition, excluded
  from build identity; `pp1-publishing-sha256-` over the section, referenced book
  details (title, subtitle, author, imprint, language), schema and engine versions.
  Title/subtitle/author/imprint/language stay in `book`; `book.description` is not
  the KDP description. Undecided values are explicit (null, `undecided`, `unknown`).
  Schema bounds are generous; KDP limits are findings, so drafts over them save.
- KDP values read on official help pages 2026-10-08 (URLs in `publishing/rules.py`):
  title+subtitle <200 (two wordings; stricter), description 4,000 and prohibited
  content, 7 keywords, 3 categories, 100-char imprint, 39 paperback languages,
  explicit-content answer, low-content (puzzle books "not generally low-content";
  no free ISBN or series when low-content), free ISBN KDP-only, AI-generated vs
  AI-assisted disclosure, cover must match details. No per-keyword length is
  modeled (KDP states none). Plain-text descriptions are a PuzzlePress rule.
- 35 metadata/disclosure/attestation rules plus 12 artifact/consistency rules
  (`puzzlepress-kdp-publishing` v2); findings carry code, severity, scope, basis,
  source URL, field, actual/required, action, Studio area, related preflight rule.
  Heuristic detectors (testimonials, promotion, stuffing, keyword variants) warn;
  unambiguous patterns block. Description puzzle counts are checked against content.
- Readiness reruns interior and cover preflight (never trusts saved reports; a
  missing/outdated/forged one is a warning), keeps verdicts separate (metadata,
  disclosure, attestations, interior and cover state/structural/KDP, artifacts,
  package), carries preflight warnings unchanged, treats unevaluated error rules as
  blocking, and explains staleness ("Cover is out of date because the interior
  paper changed (white -> cream).").
- Package (only when ready, from inspected bytes): interior.pdf, cover.pdf,
  metadata.json, kdp-checklist.md, readiness.json, interior-/cover-preflight.json,
  provenance.json, package.json; `pp1-package-sha256-` over identities, print
  configuration, three ruleset versions and file digests. Staged directory,
  verified, swapped; refuses foreign/other-book directories; export state none,
  current, stale, damaged. Optional stored ZIP with fixed order, date, attributes.
- CLI `publish validate|inspect|package` (`--output`, `--json`, `--zip`): exit 0/1/2;
  inspect `--json` equals readiness bytes. Studio: GET /publishing, POST
  /draft/publishing, POST /publishing/export {revision, archive}; Publishing tab.
- Confirmations: `pp1-review-sha256-` per statement (rights: word lists, titles,
  matter, back text, photo digest; ai_disclosure: declaration, that content and the
  description; metadata: book details and KDP metadata; isbn: ISBN, title,
  subtitle, author, imprint). States confirmed/stale/unconfirmed/legacy; reverting
  to the reviewed content restores; Python computes, Studio copies the reported
  identity, `publish validate` prints it; version 1 `true` never counts and Studio
  offers the upgrade.
- `books/publishing-demo`: cover-demo puzzles with 13 x 13 varied grids, metadata
  valid, interior and cover KDP ready, AI disclosure unknown and no confirmations,
  so packaging is blocked until a person decides. Tests/CI decide on temp copies.

## Planning (docs/book-planning.md)

- `planning.yaml` (planning_version 1) beside `book.yaml`: concept, positioning
  (candidate vs chosen audience, claims with evidence), structure (type, target,
  print profile, solutions, matter pages), difficulty strategy and levels (grid,
  directions, word range, or an existing profile), themes (hierarchy, required,
  allocation), vocabulary pools with provenance (default `unknown`), planned
  puzzles, constraints, questions, research notes (evidence kind, source, date),
  comparables (unknown stays null) and `approval`. Missing file = no plan; legacy
  projects unaffected. Studio and `plan approve` save through `store.write_planning`
  (revision-checked, staged, verified, atomic; null revision creates only).
- Schema only checks interpretability; everything else is a finding with a stable
  code, gate, severity, basis, path and actual/expected (ruleset
  `puzzlepress-planning` v1, 84 rules). Words use the engine's normalization;
  reuse/similarity the quality measures (reuse 2, Jaccard 0.8); print fit
  `fit_grid` on the whole live area (necessary condition); pages, KDP minimum,
  maximum and spine text from `interior.spec`. Feasibility statuses: verified,
  estimate, unknown, unsupported.
- States by first blocking gate: draft, needs_research, needs_content (content or
  structure), structurally_valid (feasibility blocks), production_feasible
  (decisions block), ready_for_approval, approved. Editorial findings never block.
- Identity `pp1-planning-sha256-` over the document without approval, book ID and
  planning identity version (no engine/toolchain, paths or times). Approval stores
  the reviewed identity; stale on edit, restored with the content; not counted on a
  blocked plan; not publishing approval. Handoff (`plan handoff --json`, approved
  only) prints a versioned document and writes nothing.
- Automotive plan (puzzlepress-books): 60 puzzles all specified, 7 themes, 3 levels (gradual), 807
  ai_generated candidates (184 from Interval 11, 623 noted `Added in Interval 12.`,
  unused ones with reasons), white paper, positioning/cap/paper resolved from the
  author's brief, 5 research notes (+ `r-positioning-default`, a preference), no
  comparables. State needs_research; only error question_blocking_open
  (q-comparables); open non-blocking q-vocabulary-review; 6 bank_size_exceeds
  warnings (production splits pools into warm-up/standard and challenge banks).
- Production comparison: `plan production` matches the automotive book with 0 deviations,
  793 placements all ai_generated, and states the plan is not approved.
- Generator limits: cap 100 within the work budget; measured 20/60/100 (synthetic,
  plan vocabulary): generation 0.16/0.49/0.82 s, interior 1.15/3.32/5.51 s,
  preflight 1.13/3.35/5.93 s; 100 puzzles packaged with synthetic decisions.

## Composition model

- Optional top-level `composition` (requires `word_search`): `front_matter`
  (title_page, copyright_page{text}, instructions{title,text}; each once; title
  page first), `puzzles.start` any|recto, `puzzles.layout` single|spread, required
  `solutions` {placement end|omit; with end: title, per_page 1|2|4(default)|6|8,
  start any|recto}, `back_matter` (about{title,
  text}, notes{title}), `page_numbers` {scheme continuous|roman_front_matter,
  show_front_matter false, show_solutions true, show_back_matter true}.
- Titles 1..200 single-line; body 1..2,000 plain text with line breaks. No default
  legal text anywhere. Errors collected with structured paths; nothing repaired.
- Backward compatibility: absent composition is not reinterpreted; legacy identities
  byte-identical (garden-demo/automotive pinned). Planning requires explicit
  composition (`composition [required]`); Studio offers a visible starter.
- Identity: present composition is in canonical inputs plus envelope
  `composition_version: 1`; omitted/explicit defaults hash equally.
- Publication order is `word_search.puzzles` order: no second reference list,
  every definition once. Seeds follow IDs, so reordering never changes grids.

## Plan semantics

- Each plan page is one logical page; index 1 recto, odd recto/even verso. One
  page per matter item and per puzzle; solutions grouped per_page in puzzle order
  (grouping semantic, arrangement is layout). Back matter follows directly.
- recto start inserts one explicit blank (`section_recto_start`, `before_section`)
  attributed to the preceding section, only when needed.
- Numbers: value/style/label/displayed; blanks counted, never displayed; puzzle
  pages always displayed. roman_front_matter: front (incl. trailing blank) roman,
  arabic restarts at 1. Cross-refs by logical index: `solution_page`, `puzzle_page`.
- Puzzle refs: id, ordinal, title, theme, seed (JSON string), `sha256-` digest of
  generated puzzle JSON. Failed generation keeps entries with null digest plus a
  `generation_failed` diagnostic; `complete` false. Quality stays separate.
- Statistics are logical counts, not final printed/KDP page counts.
- Verifier checks invariants vs source/report (order, sections, matter text, seeds,
  digests, coverage, grouping, cross-refs, justified blanks, recto starts,
  numbering/display, statistics, diagnostics). Fresh-plan failure raises.

## CLI and API

- `puzzlepress book plan PROJECT [--json]`: read-only; exit 0 complete, 1
  invalid/missing composition/generation failure, 2 usage.
- `puzzlepress book build PROJECT [--output DIR] [--profile ID] [--json]`: exit 0
  written (warnings on stderr), 1 expected failure with diagnostics (JSON `{success:
  false, stage, diagnostics}`), 2 usage.
- POST `/api/projects/{key}/draft/plan` `{source}` (409 `generation_busy`, 422
  `no_composition`). Print endpoints: see Preflight.

## Studio composer

Outline sections (front matter, puzzles, solutions, back matter, page numbers)
beside a plan table grouped by section with side, number (parenthesized when not
printed), content, blanks and reasons, statistics, verification and quality count.
Up/Down/Remove buttons (no drag dependency); focus follows moved puzzles. Saved plan
auto-requests once per revision; edits clear it until Preview plan; save/reload
announce then refresh. Plan sticky above 1200px; stacks below with Jump to plan.
Same revision/atomic save/stale rejection/draft retention as Interval 5.

## Persistence contract (unchanged)

Only existing root-scoped `book.yaml`; key/symlink/output boundary checks; byte
revision `sha256-<bytes>`; validate, stage, fsync, reload, recheck, `os.replace`,
reload. Canonical YAML loses comments/formatting. One Studio process per library;
small external-editor race remains. Drafts memory-only; no autosave/undo/merge.

## Actual local verification

Visual authoring (Interval 6), 2026-11-04 (Windows, Python 3.13):

- Baseline (main `b42b5bd` plus the CI fixture fix): the full suite exited 0 with 9
  skips. After: **2213 passed, 10 skipped** (symlink permission, Windows drive
  paths), including the golden test 4/4 against baseline v3 with PDF bytes compared
  (word-search outputs, identities, plan JSON, manifests and reports byte-identical).
  Ruff lint and format, strict mypy (159 files), pip check, `git diff --check`.
  AGENTS CLI commands exit as on main (both `publish` commands exit 1 on main too;
  scratch output directories).
- Coloring: the four `tests/coloring_samples.py` books build byte-identical PDFs
  with equal build and interior identities on this branch and on main.
- Frontend: tsc, ESLint, Prettier (`--end-of-line auto`), build. Vitest **124/124**
  (an earlier full run timed out the existing Composer test at 5.1 s; it passes
  alone and in the final run). Playwright **38/39**: new `authoring.spec.ts`
  (New book to built, zoomable proof without YAML; axe and 1440/1024/768/390
  without overflow) and every coloring spec pass; `templates.spec.ts` rich text
  fails at line 300 as before. Rewritten `docs/images/studio` captures restored.
- Visual review of the authoring captures found the New book form unstyled
  (labels beside inputs, oversized radios) and Fit page at 18 % (the view's height
  followed its content); both fixed and re-captured.
- Locks: active, crashed and unattributable owners tested across real processes on
  Windows; Linux uses the `fcntl` path (CI).
- Benchmark (`tests/coloring_benchmark.py`, 150 drawings / 302 pages, two runs
  each): no measurable difference from main; first preflight 111-144 s on both,
  peak 174 MB on both (table in docs/coloring-publishing.md).
- Real artwork: none legitimately available (the books repository has cover
  photographs only, licence unrecorded). The review harness ran on the synthetic
  set; no threshold changed and no print quality is claimed.

Coloring covers, publishing, production and Pages, 2026-11-04 (Windows, Python 3.13):

- Baseline before changes (clean main worktree): **2101 passed, 9 skipped**. After:
  **2151 passed, 9 skipped** (symlink permission), including the golden test against
  baseline v3 (word-search outputs, PDFs, manifests and reports byte-identical).
  Ruff lint and format, strict mypy (153 files), pip check, `git diff --check`.
  AGENTS CLI commands exit as on main (both `publish` commands exit 1 on main too;
  scratch output directories, since `.pytest_cache` is unreadable here).
- Frontend: tsc, ESLint, build, Prettier on changed files. Vitest **112/114** in the
  last full run: two existing word-search tests (Composer "edits matter, policies
  and keyboard order", Cover "crop controls") hit their 5 s limit at 5.0-5.3 s and
  pass alone (Composer 8/8, Cover 13/13; the Composer one takes 4.8 s with main's
  Composer.tsx). All new tests pass. Playwright **38/39**: new `coloring-pages.spec.ts` (keyboard and
  drag reorder, divider, save, reload, axe, 1440/1024/768/390 without overflow,
  40 px targets), the template Export download regression and all coloring specs
  pass; `templates.spec.ts` rich text fails at line 329 as before. Rewritten
  `docs/images/studio` captures restored.
- Export bug reproduced in the browser pane before the fix (click prevented, API URL
  pushed as a route, no request reached the server) and verified after (GET 200).
- Synthetic production book (`tests/coloring_production.py`): `book produce` ready,
  complete package, cover prints "28 pages, 8.5 x 11 in" from the built interior.
- Measurements (same machine, idle): 150 drawings / 302 pages build 20.2 s (main)
  vs 20.3 s; first preflight 122.9 s vs 100.6 s; second preflight in the process
  118.4 s vs 14.9 s; peak 147 MB vs 141 MB; coloring produce 125.1 s (120 MB).
  12-drawing produce 24.5 s without the memo, 14.3 s with it, byte-identical.
- Real artwork: none available (the books repository has automotive cover
  photographs only). A read-only inspection of one photograph reported color, gray
  paper and edge contact. Human review procedure in docs/coloring-publishing.md.

Coloring composition, interior and preflight, 2026-11-04 (Windows):

- Python 3.13: **2101 passed, 9 skipped** (symlink permission, Windows drive paths),
  including the golden test 4/4 against baseline v3 (word-search outputs, PDFs,
  manifests and reports byte-identical). Ruff lint and format, strict mypy (150
  files), pip check, `git diff --check`. AGENTS CLI commands exit as on main (both
  `publish` commands exit 1 on main too; scratch output directories).
- Python 3.14.6 (zlib-ng) against 3.13 (classic zlib), same sample book: each
  builds deterministically with different PDF bytes; a build preflighted in the
  other environment reports `coloring_rendering_environment`, leaves
  `pdf_matches_layout` not evaluated and still passes `coloring_image_integrity`;
  a build preflighted where it was built is valid and ready.
- Frontend: tsc, ESLint, Prettier (`--end-of-line auto`), build. Vitest
  **103/103 (an earlier full run under load timed out 2-3 Composer, Cover and Editor tests that pass alone and on rerun)**. Playwright **36/37: all three coloring specs pass (artwork, preparation, print proof with axe and four widths); templates.spec.ts rich text fails as before. Rewritten docs/images/studio captures restored**.
- Samples (synthetic): simple 8 pages, detailed 18, sections 29 (ready), single-sided
  12; 0.19-0.38 MB; build 0.7-2.0 s, preflight 3.6-6.4 s. Scale: 60 drawings / 122
  pages build 8.4 s, preflight 37.7 s; 150 / 302 pages build 19.7 s (96 MB peak),
  preflight 92.8 s (132 MB peak, 1,028 MB before keeping measures only).
- Visual review of the contact sheets and Studio captures at 1440 and 390 px. It
  found the pale pencil page (`faint_lines` added); the previews are synthetic and
  real artwork still needs a person's review.

Line-art preparation and the Python 3.14 CI repair, 2026-11-04 (Windows):

- Python 3.13: **1971 passed, 9 skipped** (symlink permission, Windows drive
  paths); golden test 4/4 (source-only, PDF files, every output) against baseline
  v3, whose pinned values are those recorded from the pre-refactor engine. Ruff lint
  and format, strict mypy (146 files), pip check, `git diff --check`. AGENTS CLI
  commands exit as on main (scratch output directory).
- Python 3.14.6 (fresh venv on the repair branch): **1922 passed, 10 skipped**
  before the zlib gate; the only failure was the golden PDF comparison under
  zlib-ng, now skipped with that reason (golden on 3.14: 2 passed, 2 skipped). Main's
  CI run 41779596662 showed the golden PDF comparison passing on Linux 3.14.
- Frontend (idle machine): tsc, ESLint, Prettier (`--end-of-line auto`), build.
  Vitest **100/100** twice. Playwright **35/36**: `coloring.spec.ts` (import and
  preparation: findings, difference view, keyboard on a real slider, save, reload,
  reset, axe, 1440/1024/768/390 without overflow) passes; `templates.spec.ts` rich
  text fails at line 320 as before. Rewritten `docs/images/studio` captures restored.
- Visual review: `docs/images/coloring/preparation-samples.png` (seven cases) and
  Studio panel captures at 1440 and 390 px. They found a dusty result that passed
  the checks (speck warning recalibrated) and oversized checkboxes and radios in the
  panel (fixed). The previews are synthetic; real drawings still need a person's
  review.

Coloring schema and artwork library, 2026-11-04 (Windows, Python 3.13):

- Python: **1918 passed, 9 skipped** (symlink permission, Windows drive paths),
  scratch `--basetemp`, `-p no:cacheprovider`; then the corrected golden test 4/4
  (source-only, PDF files, every output) against baseline v2. Ruff lint and format,
  strict mypy (144 files), pip check, `git diff --check`. AGENTS CLI commands exit
  as on main (scratch output directory).
- Frontend: tsc, ESLint, Prettier (`--end-of-line auto`), build. Vitest **95/96**:
  the Composer "edits matter…" test times out at 5 s while another project's
  CPU-heavy jobs run on this machine; main's frontend code fails the same test under
  the same load, and Composer + Cover pass 21/21 alone. Playwright **34/35**: new
  `coloring.spec.ts` passes (import, SVG refusal, reimport, look-alike, reload, axe,
  removal, 1440/1024/768/390 without overflow); `templates.spec.ts` rich text fails
  at line 320 as before. Rewritten `docs/images/studio` captures were restored.
- Measured: full inspection about 0.12 s per 2175 x 2925 drawing; similarity
  thresholds from 60 synthetic drawings (1,770 pairs, none matched).
- Linux: PR #15's CI showed baseline v1's five platform-dependent digests (fixed in
  v2). The v2 PDF comparison on Linux awaits the next CI run.

Multi-engine foundation, 2026-11-03 (Windows, Python 3.13):

- Python: **1823 passed, 8 skipped** (symlink permission, Windows drive paths);
  scratch `--basetemp`, `-p no:cacheprovider`. Golden baseline: all outputs equal
  the pre-refactor values (also run on the unchanged engine before committing).
  Ruff lint and format, strict mypy (133 files), pip check, `git diff --check`.
  AGENTS CLI commands exit as on main (into a scratch directory: this machine's
  `.pytest_cache` denies writes); `publish validate`/`inspect` exit 1 on
  publishing-demo on both.
- Frontend: tsc, ESLint, build; Prettier passes with `--end-of-line auto` (CRLF
  checkout only otherwise). Vitest **91/91** twice on an idle machine; while the
  Python suite ran alongside, 1-13 timing-dependent tests timed out (same 5 s
  limits; they pass alone and idle). Playwright **33/34**: `templates.spec.ts`
  rich text fails at line 320 (`runs[0]` not bold `Twenty`) identically on main
  `693aa00` code and this branch, twice each. The browser specs rewrite
  `docs/images/studio/*.png`; those captures were restored, not committed.
- Not verified then: the golden PDF digests on Linux/macOS. Linux CI after the merge
  found baseline v1's normalization bug instead (see Interval 2).

Interior design studio, 2026-10-18 (Windows, Python 3.13):

- Python: **1742 passed, 7 skipped (symlink permission)**, scratch `--basetemp`,
  `-p no:cacheprovider`; the 319 interior, preflight, composition and Studio API
  tests rerun after the last theme-table change. Ruff lint and format, strict mypy
  (122 files), pip check, `git diff --check`. AGENTS CLI commands exit as on main
  (`publish validate`/`inspect` exit 1 on publishing-demo on both).
- Frontend: tsc, ESLint, 89 Vitest, build. Prettier passes with `--end-of-line
  auto`; without it, only the CRLF checkout is flagged. Playwright **33/34**
  (Chromium): new `interior.spec.ts` (answer layout, theme, layout, Python
  validation beside the field, save, reload, real build, design export/import,
  axe, 1440/1024/768/390 without overflow) and the updated polish and composer
  specs pass; the `templates.spec.ts` rich text test fails as recorded on main.
- Compatibility (main via `git archive` vs this branch): composition-demo,
  cover-demo, publishing-demo, a version 1 styled cover-demo with dividers, and a
  disposable copy of the automotive book as authored all give identical PDF
  digests and interior identities.
- Visual: rendered and inspected every theme, every layout, a spread, 8 a page
  with a partial last page, and the automotive copy's pages.
- External book: a disposable copy of puzzlepress-books `books/automotive`
  (author's uncommitted edits included) with `per_page: 4` and Racing Orange /
  Bold Header, puzzle numbers, answer references and caption labels: 95 -> 80
  pages (30 -> 15 answer pages, 13/15/17 grids, no readability warnings), 4.3 s
  build, interior preflight structurally valid and KDP ready (only the existing
  `kdp_full_font_embedding` warning), cover rebuilt with spine 0.1802 in for 80
  pages. Its instructions text still says solutions are "two to a page": the
  author must edit it. The books repository's book.yaml digest and status were
  unchanged.

Book language editing, 2026-10-18 (Windows, Python 3.13): Language now sits
beside Book title at the top of Puzzles. Python **1659 passed, 7 skipped
(symlink permission)**; Ruff, strict mypy (120 files), pip check; tsc, ESLint,
86 Vitest (a Composer test intermittently exceeds its 5 s timeout under full-run
load and passes alone), build. Prettier flags only the CRLF checkout.

Book title editing, 2026-10-18 (Windows, Python 3.13): the only title control
was inside a collapsed disclosure at the end of Puzzles (about 8,500 px down on
the 60-puzzle automotive book), and Publishing and Book pointed to an "Edit" tab
that is labelled Puzzles. Book title is now the first field of Puzzles; the seed
stays under Shared seed. Save, validation, staleness and packaging were already
correct and are now covered by tests.

- Python: **1659 passed, 7 skipped (symlink permission)**, scratch `--basetemp`
  and `-p no:cacheprovider`. Ruff lint and format, strict mypy (120 files), pip
  check, `git diff --check`.
- Frontend: tsc, ESLint, 84 Vitest, build. Prettier passes except the CRLF
  checkout it flags locally. Playwright **31/32**: the `templates.spec.ts` rich
  text test fails here with and without this change (Windows Ctrl+Shift+Right
  selects the trailing space).
- External book: a disposable copy of puzzlepress-books `books/automotive`
  retitled through Studio changed only `book.title`, survived reload, showed in
  Publishing with no title findings, and staled the metadata confirmation.

Cover templates, rich text and Studio fixes, 2026-10-15 (Linux container,
Python 3.13, Chromium 1194 via `STUDIO_BROWSER_PATH`):

- Python: **1661 passed** (1651 in the full run plus 9 readiness tests added
  after it started, and `test_external_library` passing in a scratch
  `--basetemp`: that test refuses a basetemp inside the repository, so it failed
  once when `.pytest_cache/tmp` was used). Ruff lint and format, strict mypy
  (120 files), pip check, `git diff --check`, and the AGENTS CLI commands with
  the same exit codes as main (`publish validate`/`inspect` exit 1 on
  publishing-demo on both).
- Frontend: tsc, ESLint, Prettier, 80 Vitest, build. Playwright **32/32** with
  axe, including `templates.spec.ts`: browsing writes nothing, preview, Apply,
  Undo to the exact previous cover, save and delete a project template,
  selection-only bold through typing and undo, bold-italic disabled, photo
  removal with Used-by links, and the gallery and overlay menu at 1440, 1024,
  768 and 390 px with no horizontal overflow. One earlier full run had a
  publishing readiness wait time out under load; that spec passed alone and in
  the full rerun. `polish.spec.ts` interior design also failed on main here:
  the interior status read held the lock when the draft preview fired. Interior
  previews now retry.
- Compatibility: cover-demo and publishing-demo interiors and covers have the
  same PDF digests and cover identities as main. All eight templates render
  without layout issues at 24/95/300/550 pages, white and cream paper, and with
  or without a photograph or author. Every template applied to a publishing-ready
  book leaves readiness with no `cover_text_*` findings and the package ready.
- External book: a disposable copy of puzzlepress-books `books/automotive`
  (`2eb9551`, no cover yet) with a synthetic 5,400 x 3,500 blue-car photograph.
  Every template previews buildable with no blocking checks; only the advisory
  `spine_text_omitted` appears at 95 pages. Photographic Editorial gives a navy
  back and spine with the car on the front, and the cover builds structurally
  valid and KDP ready. Readiness shows no `cover_text_*` finding and blocks
  only on the author's decisions. The books repository's status and file
  digests were identical before and after.
- Performance on that copy (one run, except medians of three for drafts):
  interior build 4.8 s, photo import 3.5 s, v1 draft 0.37 s, eight gallery
  previews 1.5 s cold and 0.4 s cached, template draft 0.21 s, rich back text
  draft 0.23 s, save 0.55 s, cover build 0.98 s, readiness 4.6 s.

Production design and publishing polish (Windows, Python 3.13.15, Node 24.18.0):

- Python: **1553 passed, 6 skipped (symlink permission)**, 1 Starlette httpx warning; run with a scratch
  `--basetemp` and `-p no:cacheprovider` because this machine's
  `.pytest_cache` folder denies access. Ruff lint and format, strict mypy (115
  files), pip check, `git diff --check`.
- Frontend: tsc, ESLint, 79 Vitest, build. Prettier passes except three
  unchanged e2e files whose Windows CRLF checkout it flags locally. Playwright
  **28/28** with axe, including `polish.spec.ts` (region conversion, add, nudge,
  lock, reorder, save and build; asset trash and restore with used assets
  protected; interior preset, dividers and sample pages; rebuild plan and
  confirmed results; review record, filter and stale on edit; final steps and a
  proof record). Captures regenerated and reviewed at 1440, 1024, 768 and 390; no
  horizontal overflow.
- Compatibility: every demo book and the synthetic production book give the same
  interior and cover PDF digests and identities as main; converting cover-demo to
  regions renders the same bytes.
- Performance (synthetic 60-puzzle book with the demo cover; medians, same as
  main within 1 % where both exist): cover open 0.33 s, plain/24-element preview
  0.47/0.48 s, style preview 0.25 s, interior build 3.5 s, interior preflight
  0.16 s, cover build 0.68 s, cover preflight 0.28 s, readiness 4.1 s, asset list
  0.15 s, review navigator 0.15 s, no-op rebuild 4.3 s, rebuild after a puzzle
  edit 15.2 s.
- External book: a disposable copy of puzzlepress-books `books/automotive`
  (`2eb9551` plus the author's uncommitted edits) built interior `f7dc9987…` and
  cover `5f034847…`, identical to main with equal identities; the cover is
  structurally valid and KDP ready. Converting it to regions rendered the same
  bytes and its rebuild rewrote the same `cover.pdf`; a style preview took 0.9 s;
  the review navigator lists 60 puzzles, none reviewed; the overview blocks only
  on metadata and export and waits on the author's decisions (AI disclosure,
  rights, ISBN, classification, content review, plan approval). The repository's
  status and 15 recorded file digests were identical before and after.

## Limits and decisions for review

Coloring publishing (Interval 5): no genuine coloring artwork was available; every
threshold (including light strokes) is calibrated on synthetic drawings and needs
the human review procedure in docs/coloring-publishing.md. Light-stroke detection
cannot tell construction lines from detail. The first preflight of a process still
measures every drawing; the memo helps only repeated work in one process and is
never on disk. The composer preview draws Python's plan with thumbnails, not built
pages. No project-creation API or type picker, no generic undo/redo hook, no zoom
or pan, no illustration editor. KDP's AI form wording, prices and markets are not
modeled. A stale `.produce.lock` after a crash must be deleted by hand.

Coloring interior (Interval 4): 8.5 x 11 in, no bleed, one art box for every page
(no auto-crop, captions, per-page placement or scale). Coloring PDFs are
byte-reproducible only with the recorded zlib implementation and Pillow. The
300-entry caps were not measured at their limit.

Line-art preparation (Interval 3): thresholds are conventions measured on
synthetic drawings only (fine-line retention never fell between 0.05 and 0.99
there, so the 0.60/0.90 limits are unexercised); despeckle also removes deliberate
stippling further than 6 px apart; the difference preview shows ink changes only;
no build reads prepared pixels yet; preparation takes 0.6-3 s per full page in
Studio. Interior PDF bytes depend on Python's zlib (Python 3.14 on Windows links
zlib-ng), which the interior identity does not record, so a book built under one
zlib and preflighted under the other fails `pdf_matches_layout`: a follow-up, not
fixed here.

Coloring books (Interval 2): adjustments are stored, not applied; no page layout,
interior, cover, preflight or package exists for them; DPI is measured against the
profile's live area; caps are provisional; the similarity heuristic is measured on
synthetic drawings only; Studio cannot edit titles, adjustments or page order or
trash artwork (CLI `remove --trash` and the asset library API can); the CLI's
`import`/`remove` rewrite book.yaml canonically (comments lost), through a writer
that follows Studio's save contract but is a second implementation of it.

Interior design: the omitted `per_page` default changed from 1 to 4, which
repaginates any book that omitted it (all demos and the automotive book state 2,
so none changed). Themes print in gray on the black-ink profiles; there is one
font family, no free positioning, one arrangement per count, no difficulty label,
and dividers for themes only. 8 a page fits grids up to about 11 x 11. Planning
accepts 8 but does not model spreads. The reference screenshots named in the brief
were not attached, so the themes follow its written description only.

Book details: Language sits beside Book title at the top of Puzzles, where the
`language_supported` finding points. Studio does not check language tags;
Python's project validation and the Publishing rule do.

Templates and rich text: templates are authored at 8.5 x 11 in and scaled; a
project template using imported fonts works only where the same font files
exist; a template whose body face lacks a variant used in formatted back text
previews `font_variant_unavailable` until that formatting changes. Rich text has
no kerning, hyphenation or justification. Photo-library removal confirms with
the browser's dialog (the Assets tab keeps its own). The canvas offers
centre and safe-area snapping and Fit selection, but no rulers, multi-select or
alignment tools.

Production polish: interior photographs are grayscale and placed with a centred
crop in Studio (other crops in YAML); no element grouping, alignment tools or
multi-stop gradients; rotation for rectangles and ellipses only; text boxes take
one style; reviews and proofs keep no history and have no CLI; a no-op rebuild
still costs one readiness evaluation (about 4 s at 60 puzzles). Earlier: variable,
CFF and WOFF fonts are deferred; no kerning or
ligatures; spine text keeps its preset face; offsets are relative to the
layout's position, so a preset or text change moves the start point; extra
layers are plain text only. Cover undo covers the current session only and is
cleared by save, reload or revert. Panel widths are fixed per breakpoint (no
drag-resize). Only Chromium is exercised; axe is not screen-reader
certification. The author's automotive photo reaches 67 DPI here (another photo
in its library reaches 185), so its cover is not KDP ready until a larger
photograph is supplied.

Author decisions for the automotive book (puzzlepress-books, docs/): review the
AI-drafted words, titles and matter text (its content audit) and the
23-word screening list; record comparable books actually read (q-comparables) and
approve the plan if intended; author, imprint, subtitle, copyright notice, edition;
supply a photograph (full wrap about 5,300 x 3,400 px at 300 DPI) and design the
cover; ISBN, low-content, explicit-content answer, categories; the AI disclosure
(KDP: AI-created text stays AI-generated after edits); the three confirmations;
then Print Previewer and a physical proof. Not verified: KDP's handling of an odd
page count (95) and the 8.5 x 11 page maximum; the description-claims heuristic
reads "13 by 13 grids" as a count. Generation v1's random sequence depends on word
count, not words. Planning heuristics (label similarity 0.5, pool overlap 0.3,
balance 2x/0.5x) remain conventions to review.

Paperback only; plain-text descriptions (KDP's HTML subset is a possible future
enhancement); categories are unverified preferences; contributor roles beyond
author/editor/illustrator/translator come from KDP's form, not its help pages;
confirmations bind to content, not to a person or time, and keep no history; heuristic
detectors can over- or under-report. Not modeled: pricing, territories,
marketplace, cover finish, publishing-rights options, public domain. Review
before Interval 11: whether a rebuilt interior with unchanged physical facts should
require a cover rebuild (today the cover stays current with a provenance warning,
since its bytes would not change); whether publishing-demo keeps its 13 x 13 grids
(its header comment explains them by the old overhang; content left untouched);
whether `saved_reports` should be a note; and the Interval 9 items
(80-page spine reading, barcode offsets, RGB warning, 550-page maximum, two-file
cover write). History: Interval 9 commits 9c6d290 and 446252b (on main) lack their
source modules (an unanchored `cover/` ignore rule); 7ea89b2 adds them. The
branch was already merged and deleted, so it was not rewritten.