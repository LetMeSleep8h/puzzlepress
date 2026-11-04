# Multi-engine architecture and coloring book engine: assessment and plan

Status: branch `feat/multi-engine-coloring`, cut from main `693aa00`. The author
approved D1-D6 as recommended. Interval 1 (foundation) is implemented; the
coloring engine (Intervals 2-7) is not.

## 1. What the repository is today

PuzzlePress is one content engine (word search) with a mature shared publishing
stack around it. That stack's contracts are strict: byte-identical PDFs,
versioned identities, observational preflight, a single writer per artifact.

| Layer | Modules | Engine coupling |
| --- | --- | --- |
| Project schema | `validation.py`, `models.Project`, `yaml_io`, `project.py` | Optional sections. `composition` requires `word_search` (`composition_validation.py:44`); `cover`, `publishing` and `interior` require `composition`. |
| Build identity | `identity.py` | Conditional envelope keys (`word_search_pipeline_version`, `composition_version`). Adding a section is safe if it is omitted when absent. |
| Composition and plan | `composition.py`, `publication.py`, `publication_verification.py` | Matter, recto starts, blanks and numbering are generic. Puzzles, solutions, theme dividers, spreads and `PuzzleRef` digests are word search. `build_publication` always calls `generate_batch`. |
| Print interior | `interior/` (`spec`, `engine`, `model`, `render`, `validation`, `inspection`, `build`) | Per-`PageKind` dispatch. `ImageBlock` exists for grayscale JPEG photos with cover-fill crop. Digest binding, solution templates and grid validation are word search. Bleed is rejected in spec, geometry, validation and preflight. |
| Interior preflight | `preflight/` (41 rules, ruleset 4) | About 33 rules are generic. It rebuilds the expected interior through `build_interior`, so a new engine must plug in there. |
| Cover | `cover/`, `cover_config.py` | Reads only `interior.json`/`interior.pdf` (page count, paper). Indirect coupling: requires `composition`, and templates bind `{puzzle_count}`/`{theme_count}`. |
| Publishing | `publishing/` | Generic metadata. Word-search wording and checks: low-content hint, rights statement over "word lists", description puzzle-count claims, category example. The rights review identity hashes puzzles, not interior images. |
| Production | `production/produce.py`, `answer_key.py`, `duplicates.py`, `inventory.py` | Always runs the answer-key read-back. A book with no puzzles would block on `answer_key_mismatch`. Duplicates compare word sets and grids. |
| Planning | `planning/` (`planning.yaml`) | Entirely word search (vocabulary pools, grids, directions). |
| Studio API | `studio/server.py`, `service.py`, `editing.py`, `covering.py` | No project-creation endpoint exists. `generate_project` assumes word search. Uploads are raw-body (64 MiB images, 10 MiB fonts). SPA routes are listed by hand. |
| Studio UI | `App.tsx` `NAV`, `Library.tsx`, `Overview.tsx`, `draft.tsx`, `style.css` | The navigation (Puzzles, Solutions, Quality), Library facts and Overview are word search. Only the Cover has undo, with no redo. Lists reorder with Up/Down buttons; there is no drag-and-drop. |

Reusable as-is or nearly as-is: print specifications and `KdpConstraints`,
matter/numbering/recto logic, the layout element model, deterministic rendering
and pypdf inspection, generic preflight rules, the entire cover pipeline, the
publishing metadata, readiness and package, the asset library with its trash,
proofs, the content-addressed photo import pattern, PDFium previews, the draft
and atomic save model, and the Studio Book, Cover, Print and Publishing pages.

## 2. Compatibility risks (all must hold after every interval)

1. **Identity leakage.** A new field on `Project`/`Book` that `to_dict()` emits as
   `null`, or an unconditional envelope key, changes every build identity. A bump
   to `__version__` also changes every PDF (it is in the Creator string).
2. **Plan JSON drift.** Any always-present key in `PlanPage.to_dict` or the
   statistics changes `plan_digest`, which changes interior identity and breaks
   preflight on existing builds. New fields must be emitted only when set, like
   `divider`.
3. **Ruleset bytes.** Interior, cover and publishing ruleset versions and rule
   descriptions are in report bytes and the package identity. Changing a shared
   rule's wording or version stales every exported package.
4. **Renderer paths.** Unknown elements fall through to `_grid`
   (`render.py:70`). Line art must not reuse `encode_gray` (JPEG) or
   `crop_window` (cover-fill crops artwork). New code paths only; existing ones
   stay byte-identical.
5. **Shared gates.** `composition`-required checks in plan, cover, readiness and
   production, and message text, are matched by tests and Studio. Branch on the
   engine at the seams. Do not loosen the word-search paths.

A golden regression test, written **before** any change, pins these values for
every demo book and the synthetic production book:

- build identity
- plan digest
- interior identity and PDF SHA-256
- cover identity and PDF SHA-256
- the interior, cover and publishing report bytes

## 3. Proposed architecture

### 3.1 Engine kind and dispatch (no plugin framework)

- The engine kind is **derived**, never authored twice:
  - `coloring` when a `coloring` section is present;
  - otherwise `word_search`, including legacy sources with neither section (the
    author's Interval 1 requirement: existing projects default to word search).

  The two sections are mutually exclusive (`engine_conflict`). This needs no schema version bump, because the change is additive like every earlier section.
- `puzzlepress/engines/` holds:
  - a small `ContentEngine` `Protocol`;
  - a two-entry registry keyed by kind.

  The protocol has only the operations where the engines diverge today:
  - `validate_section`
  - `content_pages(project) -> engine pages + refs`
  - `verify_plan`
  - `layout_page(kind)`
  - `bind_digests`
  - `review_content` (for the rights identity)
  - `production_checks`

  Word search is wrapped by delegating to the existing functions unchanged. Its code does not move.
- The shared stack calls the registry at those seams only:
  - `build_publication`
  - `verify_publication_plan`
  - `interior.build`
  - preflight's expected rebuild
  - readiness `_interior`
  - `produce`
  - the Studio `generate_project`

### 3.2 Shared composition

- `composition` stays the shared section: `front_matter`, `back_matter`, `page_numbers`.
- Engine-specific blocks are validated per engine:
  - word search keeps `puzzles` and the required `solutions` (unchanged);
  - coloring takes `artwork`: `start`, `reverse`, `dividers`.
- For a coloring book, `puzzles` and `solutions` are rejected rather than ignored.
- `composition_version` stays 1 for word search. Coloring composition adds its own conditional envelope key.

### 3.3 Coloring source (`coloring`, version 1)

```yaml
coloring:
  version: 1
  artwork:                 # library; original bytes in coloring-assets/<sha256>.<ext>
    - id: fox
      path: coloring-assets/3fa1….png
      sha256: 3fa1…
      title: Fox in the Ferns          # optional caption
      prepare: {grayscale: true, threshold: 0.55, contrast: 1.2, brightness: 0,
                background: 0.92, despeckle: 1, line_weight: 0,
                crop: auto, fit: contain, scale: 1.0, offset: [0, 0]}
  pages:                   # publication order; an id may appear once
    - {artwork: fox}
    - {divider: {title: Woodland}}
    - {artwork: owl}
  style: {border: none|thin|double, caption: none|below}
```

- **Import.** Import copies the original bytes, content-addressed, never
  overwrites and reuses identical bytes. This is the cover import pattern in a
  separate `coloring-assets/` folder, managed by the existing asset library and
  trash.
- **Preparation is configuration.** Each artwork's `prepare` settings are authored
  configuration. The prepared pixels are derived and never written over the
  original.
- **Identity.** The artwork digest and its `prepare` settings enter the build
  identity, satisfying the documented rule that external assets enter by digest.
- **Audience and edition.** Target audience, edition and series already live in
  `publishing` (`audience.reading_age`, `edition`, `series`) and are reused, not
  duplicated.
- **Subject.** Subject or collection is a new optional field outside build
  identity (see Decision D5).

### 3.4 Plan and parity

- New `Section.ARTWORK` and `PageKind.COLORING`. Existing `blank` is reused with
  the new reason `reverse_blank`, and existing `divider` is reused.
- `ArtworkRef` holds `id`, `ordinal`, `title`, the `sha256-` of the prepared
  pixels and the source digest.
- With `reverse: blank`, every coloring page is a recto followed by an explicit
  blank verso. A divider is placed recto with its own blank verso. The section
  starts recto.
- The verifier proves parity independently: every artwork page is odd, and every
  `reverse_blank` sits directly after one. Inserting or removing pages can
  therefore never shift art onto a verso unnoticed.
- KDP's blank-run limits are already modeled. One blank between pages is within
  them.

### 3.5 Line-art preparation (Pillow only, deterministic)

- **Pipeline.** The steps run in this order:
  1. decode (EXIF orientation, alpha flattened onto white)
  2. grayscale
  3. brightness and contrast
  4. background lift: near-white pixels mapped to pure white
  5. despeckle: median filter, plus removal of connected specks below N px
  6. optional threshold to 1-bit
  7. line weight: Min/Max filters of 3 or 5 px, ±1 step only
  8. auto-crop to the ink bounding box
  9. contain-fit and position in the art box, in points
- **Measures.** Each step records ink coverage and a thin-line survival measure:
  the share of the original ink skeleton still present after preparation.
  - `thin_lines_lost` (warning) at survival below 0.9.
  - `artwork_detail_destroyed` (blocking) below 0.6. The thresholds are conventions to review.
  - Settings are never changed automatically.
- **PDF encoding.**
  - Line art is embedded **losslessly**: FlateDecode, DeviceGray at 8 bpc, or 1 bpc when thresholded.
  - This is a new renderer branch and `ImageBlock` encoding kind. The existing JPEG path stays byte-identical.
  - Effective DPI is measured from the placed pixel size.
- **Previews.** Studio previews are PNGs that Python renders from the same
  pipeline: original, processed, and a difference overlay. The browser never
  processes pixels.

### 3.6 Coloring preflight additions

These run only when the engine is coloring and are listed as not applicable
otherwise. Their placement against the existing ruleset is Decision D3.

| Rule | Severity |
| --- | --- |
| Artwork effective DPI under 300 | KDP rule (existing `kdp_image_resolution` measure) |
| Art box outside the live area (clipping) | Blocking |
| Page parity (art on a verso) | Blocking |
| Unintended empty page: a coloring page whose prepared art has under 0.5 % ink | Blocking |
| Intentional `reverse_blank` | Passes (not counted as an unintended empty page) |
| Excessive gray: mean ink under 50 % for most inked pixels, or background not white | Warning |
| Duplicate artwork: exact digest, and near duplicates by a 64-bit difference hash at Hamming distance 6 or less | Warning |
| Missing or altered asset bytes | Blocking |

Generic rules already cover page size, trim, margins, fonts, page count,
annotations and folios. Production `produce` dispatches by engine:

- the answer key, word duplicates and inventory apply to word search only;
- coloring gets the artwork duplicate report instead.

### 3.7 Cover and publishing

- **Cover.** The cover needs no change to its geometry: it reads the coloring
  interior's page count and paper. Template bindings gain an engine-neutral
  `{page_count}`/`{artwork_count}`. For a coloring book, the `{puzzle_count}`
  binding reports `binding_not_applicable`.
- **Rights review.** For coloring books the rights statement and its review
  identity cover the artwork digests and captions. The rights identity for word
  search is unchanged.
- **Low-content and AI images.** The publishing wording on low-content books and
  AI images needs official KDP provenance before it is written (AGENTS rule). The
  first step of Interval 5 is to read KDP's help pages and record the URLs.

### 3.8 Catalog

- The catalog is **derived**, not stored: the Library lists each book's identity,
  engine kind, subject or collection, edition and format, the last built
  production identity and the production overview status. These values come from
  existing sources and `publishing`.
- No separate catalog database is introduced in this phase.

### 3.9 Studio

- **Creation.** `POST /api/projects {kind, key, title, language}` writes a new
  folder with a starter `book.yaml`, atomically under the save lock. It refuses
  existing keys, symlinks and paths outside the library. The Library gets a
  type picker:
  - Word Search and Coloring Book are enabled;
  - Maze, Crossword, Sudoku and the other future types are shown disabled and
    labelled "Not available".
- **Per-engine navigation.** `NAV`, the section regex and the server's SPA route
  list all derive from one table.
  - Word search keeps its navigation exactly.
  - Coloring: Overview, Artwork, Pages, Book, Interior, Cover, Print proof, Publishing.
- **Artwork page.** Batch upload uses repeated raw-body uploads. It includes:
  - the library grid with Python thumbnails;
  - a metadata panel (format, pixels, DPI at the art box, digest);
  - duplicate badges;
  - replace, which imports a new file and repoints the page, leaving the old file
    unreferenced;
  - remove, which moves the file to the trash only when nothing references it;
  - preparation controls with original/processed/difference views.
- **Pages page.** It provides:
  - thumbnails from the real PDF raster;
  - ordering with drag-and-drop (pointer events, as the cover canvas does) plus the existing Up/Down buttons for keyboard use;
  - duplicate and remove;
  - placement controls;
  - zoom and pan on the PDFium raster;
  - safe-area and bleed guides drawn from Python geometry;
  - a generic undo/redo hook extracted from the Cover's stack.
- **Terminology.** No puzzle, solution or word wording appears in coloring
  projects; shared pages take engine-specific labels.

### 3.10 Future engines and mixed books (documented, not built)

- Maze, crossword and sudoku follow the word-search shape: a generated puzzle with
  a solution, a seed and digest refs, and solution pages.
- Photography and illustrated books follow the coloring shape: imported raster
  art with captions.
- A mixed activity book would reference an ordered list of engine sections in
  `composition`. Each engine contributes `content_pages` independently, and the
  shared plan assigns parity and numbering. This interval writes that design
  down and builds none of it.

## 4. Decisions needed

- **D1 SVG import.** No SVG library is installed.
  - Options:
    - (a) reject SVG with a clear `svg_not_supported` finding in this phase;
    - (b) add `svglib` (pure Python plus `lxml`), parsed with entity resolution and network disabled, and an allowlist that drops scripts, `foreignObject`, external `href` and CSS `url()`.
  - Recommendation: (a), because the rules say to avoid new dependencies.
- **D2 Bleed.** Full-bleed art needs a new bleed profile and bleed-aware
  page-box, margin and printer-mark rules.
  - Options:
    - (a) art within the live area, no bleed, in this phase, with bleed guides shown as "not used by this profile";
    - (b) add an 8.625 x 11.25 in bleed profile now.
  - Recommendation: (a). Most coloring interiors keep art inside the margins, and (b) widens the preflight change considerably.
- **D3 Preflight versioning.** Adding coloring rules to the shared interior
  ruleset changes its version and stales every exported word-search package, as
  the 3 → 4 change did.
  - Options:
    - (a) accept that;
    - (b) a separate `puzzlepress-kdp-coloring` ruleset, so word-search reports keep their bytes.
  - Recommendation: (b).
- **D4 Trim sizes.** Only 8.5 x 11 in exists.
  - Options:
    - (a) keep 8.5 x 11 (white and cream) in this phase;
    - (b) also add 8 x 10 and 8.5 x 8.5.
  - Recommendation: (a). (b) means new profiles and cover-template scaling checks.
- **D5 Subject/collection.**
  - Options:
    - (a) an optional `catalog: {subject, collection}` section outside build identity;
    - (b) reuse `publishing.series`.
  - Recommendation: (a).
- **D6 Starter content.** A new word-search project must be valid, so it needs a
  small visible starter (one bank, one puzzle, a minimal composition) clearly
  labelled as placeholder text. A new coloring project starts with no artwork and
  reports `no_artwork` as blocking. The question is whether that is acceptable.

## 5. Intervals, dependencies and acceptance criteria

Each interval ends with tests, Ruff, mypy, `pip check` and the demo commands; a
report; and a commit on this branch. Studio suites run from Interval 6 on.

| # | Interval | Depends on | Acceptance |
| --- | --- | --- | --- |
| 1 | **Foundation**: golden compatibility test captured on main values; derived engine kind; `engines/` protocol and registry wrapping word search; dispatch at the seams; `engine` in project detail and Library | none | Golden test byte-equal; all 1,8xx existing tests pass unchanged; every existing book reported as `word_search`; no output or identity changes |
| 2 | **Artwork library**: `coloring` schema v1 (artwork, pages), `coloring-assets/` import, inspection (format, pixels, mode, DPI at the art box), exact/near duplicates, asset-library and trash integration, CLI `coloring import / inspect` | 1, D1, D5 | Import never overwrites; corrupt, oversized, unsupported and SVG files rejected with codes; duplicates found; identity includes digests; tests for each |
| 3 | **Line-art preparation**: deterministic pipeline, measures, thin-line findings, comparison renders | 2 | Same input and settings give the same pixels across processes; thin-line regressions detected on synthetic art; originals untouched |
| 4 | **Coloring interior**: composition `artwork` block, plan kinds, parity verifier, lossless image renderer branch, layout and validation, `book build`, coloring preflight ruleset, `books/coloring-demo` from a synthetic art generator | 3, D2, D3, D4 | PDF reopened and inspected (sizes, boxes, Flate images, DPI); parity proven with and without blanks; byte-identical rebuilds; word-search golden unchanged |
| 5 | **Cover, publishing, production**: cover from a coloring interior (spine matches page count), engine-neutral template bindings, rights identity over artwork, KDP wording with recorded provenance, `produce` dispatch, package | 4 | A coloring demo packages after synthetic decisions on a temporary copy; spine equals page count times the paper factor; word-search readiness and package identities unchanged |
| 6 | **Studio**: create-project API and type picker, per-engine navigation, Artwork, Pages and preparation editors, undo/redo hook, guides, print preview | 2–5, D6 | Vitest and Playwright: create, import, prepare, reorder (drag and keyboard), save, reload, build, preview, cover, publishing; axe at 1440/1024/768/390; no word-search terms in coloring screens; existing specs pass |
| 7 | **Docs and verification**: architecture and engine interfaces, coloring guide, artwork requirements, print guidance, migration notes, roadmap, CONTEXT.md; representative previews rendered and inspected | 1–6 | Docs match behavior; full suites run; the report lists what still needs human visual review |

Rich-text and publishing-readiness regressions (PRs #9 and #13) stay covered by
their existing tests, which are run in every interval and never edited to pass.
