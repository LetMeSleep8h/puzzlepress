# PuzzlePress Studio

Studio is a local visual editor for word-search projects, their book composition,
a print proof of the built interior, a photography-first cover studio and a
publishing workspace that exports a package for manual KDP upload. Python remains the
single authority for schema validation, normalization, generation, identity and
quality. The browser keeps drafts and displays authoritative results.

## Start locally

Python 3.11+ and Node.js 22+ are required. From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,studio,web-test]"
cd studio
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\puzzlepress-studio.exe
```

Open <http://127.0.0.1:8000/books>. After building, only the last command is needed.
Linux/macOS use `.venv/bin/python`, `.venv/bin/puzzlepress-studio` and `npm`.
The launcher is loopback-only; flags are `--books books`, `--frontend studio/dist`
and `--port 8000`. Paths are relative to the launch directory. A checkout is
required: the Python wheel does not bundle the frontend. For frontend development,
run `npm run dev` in `studio/` alongside the Python server; Vite proxies API calls.

## Navigation and drafts

A compact app bar (logo, **Books**) sits above every page. A project's sections
are grouped in workflow order; every earlier URL is unchanged:

| Group | Section | Route |
| --- | --- | --- |
|  | Overview (also the book title) | `/books/{key}` |
| Create | Plan | `/books/{key}/planning` |
| Create | Puzzles (the authoring editor, formerly Edit) | `/books/{key}/edit` |
| Create | Book | `/books/{key}/book` |
| Create | Interior | `/books/{key}/interior` |
| Create | Cover | `/books/{key}/cover` |
| Review | Print proof | `/books/{key}/print` |
| Review | Solutions (saved puzzles, grids and solutions) | `/books/{key}/puzzles`, `/books/{key}/puzzles/{id}` |
| Review | Quality | `/books/{key}/quality` |
| Publish | Publishing | `/books/{key}/publishing` |

A coloring book has its own navigation: Overview, Artwork, Pages, Cover, Print
proof and Publishing (routes `/artwork`, `/pages`, `/cover`, `/print`,
`/publishing`); no puzzle, solution or word wording appears in it. Pages, Cover
and Publishing share one draft, as below; Artwork saves imports and preparation
settings directly, and a clean draft reloads the saved source when you return to
it (see [coloring-publishing.md](coloring-publishing.md)).

Puzzles, Book, Interior, Cover and Publishing share one draft of `book.yaml`; Plan has its
own draft of `planning.yaml`. Switching sections keeps both drafts, the project
header shows **Unsaved draft** while either has edits, and leaving the project asks
first. Each draft section has the same compact bar, sticky below the app bar:
saved state, the latest status message, a jump link, **Validate draft**, the
section's preview action, **Revert draft** and **Save changes**, with the reminder
that saving writes normalized YAML (comments and formatting are not kept). There
is no autosave. Conflicts and failures keep the draft (see below).

## Authoring workflow

1. Open a valid project and choose **Puzzles**. The initial draft is a copy of the
   normalized persisted source. Overview, Solutions and Quality show saved source;
   Puzzles retains its draft when you visit those sections. **Book title** is
   the first field: the canonical `book.title` that prints on the title page and
   cover and goes to KDP. Changing it stales the interior, cover, the metadata
   and ISBN confirmations and any exported package until they are rebuilt,
   reconfirmed and exported again. **Language** beside it edits `book.language`,
   a tag such as `en` or `en-US`. Python checks the tag, reporting problems
   beside the field, and Publishing reports whether KDP lists the language for
   paperbacks; changing it stales the metadata confirmation. The shared project
   seed is under **Shared seed** at the end of the form.
2. Find a puzzle in the navigator: search titles, IDs and themes, filter by theme
   or difficulty, or step with **Previous** and **Next**. Only the selected
   puzzle's fields are rendered, so a 60- or 100-puzzle book stays fast. Puzzles
   with validation issues or preview findings carry a marker, and the selected
   puzzle's findings from the last preview appear above its fields.
   Edit a puzzle title, ID or theme. Select its bank and difficulty profile. Add
   or remove target references and reorder them with the Up/Down controls.
3. In **Word banks**, choose any existing bank and edit entry IDs/display text,
   add entries or deliberately remove them. Bank changes affect all referencing
   puzzles. Renaming/removing entry IDs does not silently repair references;
   validation identifies references that need attention.
4. Add, remove or reorder puzzle definitions (**Move up**, **Move down** and
   **Remove puzzle** act on the selected puzzle). New IDs are the first unused
   `puzzle-N`; entries use `word-N`. No randomness or clock data is introduced.
   The project seed is shared. Changing a puzzle ID changes its derived seed;
   reordering puzzles preserves their individual seeds and grids.
5. Expand **Profile settings** to edit the selected shared profile's dimensions,
   directions and work limits. Names are authored settings, not calibrated scores.
   Quality policy exposes maximum reuse and the prohibited-word list. Similarity
   thresholds and other unexposed schema values are retained in the draft.
6. **Validate draft** explicitly asks Python to validate the entire project.
   Issues retain original paths/codes; safely mapped input errors also appear
   beside their fields. Editing clears outdated issues and preview results.
7. **Preview draft** validates and generates the whole unsaved batch. Inspect the
   selected grid, targets, decimal-string seed, profile, independent verification,
   authoritative solutions and whole-book quality. Findings never rewrite content.
   Generation failures, review findings, disabled screening and incomplete scans
   remain distinct. Neither validation nor preview writes any source or output.
8. **Save changes** validates again, checks the revision, persists and reloads.
   The editor adopts the server's reloaded state, including normalization. Saving
   requires schema/filesystem validity, not a clean quality report or successful
   generation. Publishers may save valid content that still needs review.

**Editorial review.** Above the selected puzzle's fields, **Mark reviewed**,
**Needs changes** and **Reset** record your judgment of its saved content in
`reviews.yaml` (never `book.yaml`); notes, reviewer and date sit behind a
disclosure and are only what you type. A puzzle with unsaved edits cannot be
marked reviewed. The navigator shows each puzzle's review state, filters by it
and offers **Next unreviewed**; editing reviewed content shows the review as
stale. Identities and states: [production design](production-design-polish.md#editorial-review).

**Revert draft** returns to the snapshot originally opened or last saved, after
confirmation. It does not fetch external edits. Leaving the project with edits
requires confirmation; browser close/refresh uses the native warning where
supported. Drafts stay in memory only. No autosave, undo history or recovery after
closing the browser is provided. Requests disable draft controls while pending;
responses from abandoned components are ignored.

A legacy project can explicitly add initial word-search content, with visible
10×10/right/down custom settings. The first word and theme need author input.
Invalid saved YAML remains visible as an invalid project; repair it on disk before
opening the visual editor. The editor does not create project folders, rename
banks/profiles or add additional banks/profiles to existing content.

## Book composer

Choose **Book** in a project. The composer edits the same in-memory draft as
**Puzzles**: one revision, one unsaved state, one validation and one save. Changes
made in either tab are visible in the other. Composition rules are in
[book composition](book-composition.md).

1. A project without `composition` shows an explicit **Start book composition**
   action: a title page, editable instructions and solutions at the end. Nothing is
   saved until **Save changes**. No copyright text is supplied.
2. **Front matter** and **Back matter** list one logical page per item. Add, remove
   and reorder items with buttons. The title page edits the book's subtitle, author
   and imprint; the book title is at the top of Puzzles.
3. **Puzzles** sets whether the section starts on a recto page and reorders the
   project's single puzzle order with Up/Down. Focus follows the moved puzzle.
   Reordering also reorders Edit and reports, never a grid.
4. **Solutions** chooses end or omit, the section heading, solutions per logical
   page and the section start. **Page numbers** chooses the scheme and which
   sections print numbers.
5. On opening, the saved plan is requested once. After edits, **Preview plan**
   validates, generates and plans the unsaved draft. The plan lists every logical
   page grouped by section, with side, number (parenthesized when counted but not
   printed), content, cross-references and explicit blanks with their reason, plus
   statistics, verification, completeness and a separate quality-finding count.
   It is not a print preview. After a save or reload the plan refreshes.
   Above the statistics, a strip draws every logical page in spreads (page 1 alone
   on the right), coloured by section with blanks hatched, and a line compares the
   plan's page count with the saved book's built interior (current, stale or not
   built). Jump links lead to each outline section.

Validation errors attach to their composer fields. Failed and stale saves keep the
draft, exactly as in Edit. Drag-and-drop is not used: buttons work for pointer and
keyboard and avoid accidental moves.

## Interior design

Choose **Interior** to design the printed interior ([interior
design](interior-design.md)). Tabs **Page layout**, **Answer layout**, **Theme**
and **Title & dividers** edit the shared draft: `composition.puzzles.layout`,
`composition.solutions.per_page` (moved here from Book, which now links to it),
the theme dividers and the optional `interior` section. **Add an interior
design** starts version 2 at the Classic theme and layout; version 1 styles keep
their preset controls and offer an explicit **Convert to version 2**. Answer
layout lists each per-page choice with Python's letter size and Fits, Cramped or
Too small for the book's grids. Theme lists Python's themes with swatches and
what each accent prints as, treatments, **Reset to the theme**, and design file
export and import. The preview shows PDFium rasters of the pages Python rendered
from the draft (`POST /draft/interior`) by role: puzzle spread, puzzle page,
answer page, last answer page, divider, instructions, title page. A note says
what saving changes (interior stale, page count and spine, package). **Reset the
whole design to defaults** removes the section from the draft.

## Print proof

Choose **Print** to build the saved source's interior, run preflight and proof the
real PDF page by page: thumbnails, single pages, facing spreads, zoom, geometry
overlays and findings linked to their pages. Builds use the saved revision only;
unsaved drafts disable **Build interior**. Stale and mismatched interiors are
labeled. A stale interior shows Python's reasons and the **Rebuild outdated
artifacts** panel: each artifact's state, the planned steps (conditional ones say
"only if needed"), and **Rebuild N steps** for the saved revision; results appear
only as the server reports them. Details, caching and endpoints:
[preflight](preflight.md#studio-print-proof).

## Cover Studio

Choose **Cover** to design the paperback cover around your own photograph
([cover](cover.md)). It edits the project's `cover` section in the same draft as
Puzzles and Book: one revision, one validation, one save.

The workspace has three regions on wide screens (1200 px and up): **tools** on
the left, the **canvas** in the centre and the **inspector** on the right, each
scrolling on its own so the preview stays in view. From 800 to 1199 px the canvas
sits beside one tabbed panel (Tools, Properties, Checks); below 800 px the canvas
fits the screen width above that panel.

1. Build the interior in **Print proof** first: the wrap is sized from its real page
   count, trim and paper. Without one, the canvas explains that it is missing.
2. **Photo** tab: a thumbnail library of `cover-assets` with file name, pixels and
   the effective DPI each photo reaches at the current zoom and layout, with a
   warning below 300. **Compare** previews another photo without applying it
   (**Use this photo** or **Keep current**). **Import…** copies the original bytes;
   identical bytes are reused, nothing is overwritten or upscaled.
3. **Text** tab: title, subtitle, author, back-cover text, imprint and your extra
   front or back text layers, each with a show/hide toggle. Hiding or restyling a
   layer changes only the cover; the book details stay as they are.
4. **Fonts** tab: import a `.ttf` or `.otf` (`font/ttf` or `font/otf` upload).
   Python validates it before anything is written: refused fonts say why
   (PostScript outlines, variable, restricted embedding, damaged). Each font shows a
   specimen drawn by the cover renderer, its embedding permission and any
   characters this cover uses that it lacks. **Add to cover** makes it selectable
   and asks for its license and source (unknown values warn).
5. **Design** tab: layout (full wrap or front photo), type preset, title position,
   default alignment, tone, legibility treatment, fill color and spine text.
6. **Canvas**: the PDFium raster of the draft's real cover PDF, rendered by Python
   after each change (debounced). Views: full wrap, front, spine, back; zoom fit to
   400% (the canvas scrolls when larger); **Overlays** from Python geometry (trim
   and folds, bleed, KDP safe areas, type area, barcode corner, text bounds), never
   in the PDF; **Undo** (Ctrl+Z) steps back through this session's cover edits;
   **Draft** or **Built PDF**. Click a text layer to select it; drag it (centre
   guides snap within 6 px; the outline turns red outside the safe area); arrow
   keys move it 1 pt (Shift 10 pt) when the canvas has focus; Escape cancels a drag
   or clears the selection. The photograph moves only after you select it (click
   the cover, or the DPI note below the canvas): then drag it, use the arrow keys,
   `+`/`-` to zoom and `0` to reset. Every move becomes an authored value (an
   offset in points, or the normalized focal point) and Python lays the cover out
   again; the browser never positions cover type.
7. **Inspector → Properties**: for a text layer, visibility, text on the cover
   (with line breaks; **Use the book's title** resets it), font (bundled faces and
   fonts added to the cover), size (blank: the preset decides), line and letter
   spacing, letter case, color (blank: the text tone), alignment, the offset in
   points with **Reset position**, and **Reset to layout defaults**. For the
   photograph, the crop sliders and **Print quality**: effective DPI against the
   300 DPI minimum, used source pixels, printed size and the best DPI at zoom 1,
   with why zooming lowers it.
8. **Inspector → Checks**: Python's draft checks (text outside its safe area,
   display text that differs from the book details, hidden title or author, font
   license, resolution, page count, spine text), each linking to its layer; the
   interior, spine width and wrap size; then the built cover's separate structural
   and KDP verdicts, findings and **Build cover** (saved revision only; disabled
   while the draft is dirty or not buildable).

A draft whose text was moved out of its safe area still previews, so you can see
and fix it; the response says it is not buildable, and builds refuse it. A draft
previews against the last built interior even when that interior is out of date
for the draft, and says so; an interior whose files do not agree is refused.
Decoded photos (two), draft PDFs (160 MB), thumbnails and specimens are cached in
memory.

**Regions and design elements** (cover version 3, [production
design](production-design-polish.md#cover-regions-cover-version-3)). A version 1 or
2 cover offers **Convert to regions**: a dialog shows Python's preview of the
converted cover and its identity check, and nothing changes until you confirm.
Then the region picker (Full wrap, Back, Spine, Front) chooses where new elements
go and opens the region's background (color and gradient). **Shapes** adds
rectangles, ellipses, lines and text boxes centred in the region; **Layers** lists
the stack top first with visibility, lock and forward/backward buttons; the
inspector edits position and size in points, fill, stroke, opacity, rotation,
text, and duplicates or deletes. Locked elements neither drag nor nudge.
**Design** offers named presets. Python reports overflow, spine, fold and barcode
issues beside the element they concern.

**Assets** gives each photograph and font a status: In use, Draft only, Unused
or In trash. **Details** shows the file's size, digest and every use in the saved
source and the draft. **Remove…** opens a confirmation for an unused asset and
moves it to the project trash. Used assets show where they are used instead. The
trash lists removed files with **Restore**, and permanent deletion needs a second
confirmation. In the **Photos** library, each photograph lists the layers that
use it (**Used by**, each a link that selects the layer). An unused photograph
has its own **Remove…**, which asks for confirmation and then moves it to the
trash.

**Templates** ([cover templates and rich text](cover-templates-rich-text.md)) is
the first tools tab. Each card shows a thumbnail of this book rendered by
Python with the template, its name, description and category, whether it needs a
photograph, and the fonts it uses. Browsing saves nothing and leaves the draft
alone. **Preview…** opens a larger Python preview listing the book details that
stay, what the template replaces and what it keeps, any photo placeholder, and
the blocking and advisory check counts. **Apply template** puts the design into
the unsaved draft, where **Undo** or **Revert draft** restores the previous
cover. The tab also offers **Save as template**, **Duplicate**, and for project
templates **Rename**, **Export** and **Delete** (with confirmation), plus
**Import a template file…**. A version 1 or 2 cover shows a banner above the
tools that leads to **Convert to region design…**.

**Rich text**: back-cover text and text boxes use a formatting editor. Bold,
italic and underline (Ctrl/⌘+B, I, U), font, size and colour apply only to the
selection; alignment, lists, heading and paragraph spacing apply to the selected
paragraphs. Paste is plain text. Variants the face lacks are disabled with a
reason. The text inspector is grouped into Content, Typography, Paragraph,
Layout, Position, Effects and Validation.

**Canvas**: the **Preview** group (Full wrap, Back, Spine, Front) is labelled, and
the tools panel heads with the current **Editing region**. Dragging snaps to the
region's centre lines and to the KDP safe-area edges (6 px). **Fit selection**
zooms to the selected layer. **Overlays** stays within the window at every width.
Checks list **Blocking** findings, which stop a build, separately from
**Advisory** ones, which do not; preflight is unchanged.

## Publishing

Choose **Publishing** to turn the built book into a package for manual KDP upload
([publishing](publishing.md)). It edits the project's `publishing` section in the
same draft as Edit, Book and Cover.

1. A book without metadata shows **Start publishing metadata**: every decision
   starts undecided and nothing is confirmed for you.
2. The summary shows the front panel cropped from the built `cover.pdf` raster,
   title, subtitle, author, format, paper, pages, spine width and separate
   metadata, interior, cover and package verdicts.
3. Edit series, edition, contributors, the plain-text description (with a
   character count), keywords, category preferences, the explicit-content and
   reading-age answers, low-content classification, the ISBN option, AI content
   per kind and your confirmations. Title, subtitle, author, imprint and language
   are shown read-only, linking to Puzzles (title and language) and Book
   (subtitle, author, imprint).
4. As you type, Python checks the draft (`POST /draft/publishing`); blocking and
   review findings appear beside their fields as text.
5. Confirmations come from that check. Each shows **Confirmed**, **Review
   again** (with what it covers and that it changed) or **Not confirmed**; a box
   is checked only when Python reports the current draft confirmed, and shows
   nothing while a newer draft is being checked. Ticking one records the review
   identity Python reported; editing covered content unticks it, and nothing is
   reconfirmed for you. A version 1 section shows **Upgrade publishing section**
   and its old answers never count. Native checkboxes; Space toggles.
6. The readiness column (saved source) lists what is done and what is left by
   stage, the readiness statement, and a **Checklist** of Python's rules grouped
   where you act: Book content, Interior, Cover, Metadata, Rights and AI
   disclosure, ISBN and classification, Final confirmations. Each group says
   whether it is complete, has items to review or is blocking (unchecked rules
   block), opens when something blocks, shows the findings with their KDP sources
   and links to the right section or field. Findings by severity and every check
   follow. The column stays in view beside the form and moves above it below
   1000px. Nothing is checked or confirmed for you.
7. **Final steps** (above the form) is Python's production overview: the stage
   ladder from draft source to Published (never tracked), the rebuild panel when
   anything is outdated, and every check with its kind (PuzzlePress rule, modeled
   KDP requirement, your judgment, outside PuzzlePress), status and whether it
   blocks export; each item opens to what it checks, why, what to do and a link.
   Then the ten human-proofing steps and **Proof records**: record a Print
   Previewer or physical proof you reviewed, with your dates, observed issues and
   decision (undecided by default). A record names the interior and cover now in
   the build directory and goes stale when either changes. Nothing is approved for
   you.
8. **Save changes**, then **Export package** (saved revision only; disabled while
   the draft is dirty or anything blocks). Optionally write `publishing.zip`. The
   summary lists the files, digests, location relative to the project and the
   package identity, and the checklist is shown in full. Nothing is uploaded.

## Planning

Choose **Planning** to plan a book before producing it ([book planning](book-planning.md)).
The plan lives in `planning.yaml` beside `book.yaml`, with its own draft and byte
revision: saving a plan never changes `book.yaml` or disturbs a book draft, and
leaving the project is guarded while either draft has unsaved edits.

1. A project without a plan shows **Start a plan**: every decision starts
   undecided, nothing is approved, and nothing is saved until **Save plan**.
2. The section list (overview, audience, research, comparable books, themes,
   puzzle allocation, vocabulary, difficulty, coverage) shows how many findings
   each section has to fix or review; sections deep-link as `#planning-<section>`
   and their heading takes focus. Below 850px the list wraps above the editor.
3. As you type, Python checks the draft (`POST /draft/planning`). Findings appear
   beside their fields as text with their action; schema problems mark the field
   and keep the draft. Empty optional fields become null (unknown); typed text is
   sent exactly. Words are entered one a line; invalid words are reported, never
   rewritten. Puzzle words are chosen from the theme's vocabulary.
4. Charts are tables of Python's numbers: puzzles by theme (allocated and
   specified), usable versus needed words per theme, and level progression in book
   order with each cell's level number printed (and a table view).
5. The readiness column lists each gate as Passed or Blocked with its blocking
   codes, the approval state and every production-feasibility item with how it is
   known. It moves below the editor under 1280px.
6. **Approve this plan** is available only for the saved, unedited plan when
   nothing blocks it; it sends the planning identity Python reported for that
   revision. Unsaved edits to an approved plan are announced as making the
   approval stale; after saving, the approval shows as stale until you approve
   again (restoring the exact content restores it). **Withdraw approval** removes it.

## Conflict and failure recovery

A save includes the revision loaded with the authoritative source. A competing
save or external byte change, including comments or output settings, returns
`409 source_changed`. The draft remains available. Review/copy the edits you want
to keep, then choose **Reload saved source** and confirm discarding the draft.
Reload is read-only and the draft is replaced only after the response succeeds.
There is no automatic merge or force-overwrite button.

Invalid drafts return structured issues without writing. Failed saves retain the
draft and never show a success state. `save_unconfirmed` means replacement occurred
but reload could not confirm the result; reload to review before retrying. A lost
network response can likewise leave the client uncertain whether a save completed.
Missing projects, unavailable server, malformed response and unexpected failures
have recovery messages. Python tracebacks stay in server logs.

## Persistence and YAML behavior

Only `book.yaml` in an immediate project folder under the configured books root
can be replaced. Route keys are 1..128 ASCII letters/digits/hyphens/underscores,
starting alphanumeric. Keys are independent of book IDs. Resolved directory/file
boundaries and symlinks are checked; output must remain disjoint from source.
No caller-supplied destination or arbitrary filesystem write is accepted.

`studio/editing.py` validates the complete proposed object through `validate_project`
and `resolve_output_directory`. It stages `dump_project` UTF-8 bytes in a unique
sibling temporary file, flushes and fsyncs it, then reloads and verifies that staged
model. It rechecks route/output boundaries and the exact original revision before
`os.replace`. Same-directory replacement is atomic on supported local Windows and
POSIX filesystems: readers see the old or new complete file. Successful saves reload
and validate the authoritative file and return that state. Saves within a process
serialize through a lock. Failures before replacement preserve the old source and
attempt to remove the staged file; cleanup failures are logged.

Use one Studio process per books root. Portable file APIs do not provide an atomic
compare-and-swap against an uncooperative external editor: a very small interval
remains between the last revision check and replacement. This is trusted local
authoring software, not protection against hostile concurrent filesystem swaps.
Network filesystem semantics and sudden-power-loss durability are not guaranteed.
A forcibly killed process may leave a `.puzzlepress-*.tmp` sibling; it is never
loaded as project source, and Studio does not recursively clean directories.

The existing PyYAML serializer is deliberately canonical, not a formatting
round-tripper. It sorts mapping keys, emits normalized defaults and null optional
book fields, preserves authored sequence order, and uses its own scalar quoting,
whitespace and formatting. Comments, original quotes and blank lines are lost.
Seeds become decimal YAML integers; HTTP seeds remain decimal strings. Directions
and prohibited search forms follow existing core normalization. Equivalent models
produce identical YAML bytes. No YAML dependency or schema change was added.

## Architecture and HTTP surface

- `studio/service.py`: scoped snapshots, byte revisions, core report presentation.
- `studio/editing.py`: explicit adapter-level persistence, keeping core APIs pure.
- `studio/printing.py`, `studio/preview.py`: interior build/preflight adapter and the
  PDFium page rasterizer with its digest-keyed cache (one process-wide PDFium lock).
- `studio/covering.py`: cover status, draft render, photo import, build and rasters.
- `studio/publishing.py`: publishing readiness, draft metadata checks and export.
- `studio/planning.py`: planning status, draft checks, revision-aware plan saves and approval.
- `studio/assets.py`: the asset library, trash, restore and purge under the save lock.
- `studio/reviewing.py`: editorial reviews and proof records (revision-checked sidecars).
- `studio/production.py`: production overview (cached by the bytes it reads) and rebuilds.
- `studio/server.py`: thin HTTP handlers, expected errors, static assets and launcher.
- `studio/src/draft.tsx`: shared draft lifecycle and toolbar; `Editor.tsx`,
  `ContentEditor.tsx`, `Composer.tsx`, `editor-fields.tsx`: visual inputs and
  transport presentation. No second domain implementation or planner.

| Method and path | Request / result |
| --- | --- |
| `GET /api/projects` | Sorted library, including invalid projects |
| `GET /api/projects/{key}` | Normalized source, validation, identity, engine version, derived `engine` {kind, label}, byte revision |
| `GET /api/projects/{key}/coloring` | Coloring books: saved revision and artwork library report (see [coloring books](coloring.md), which also lists the artwork import, removal, thumbnail and line-art preparation endpoints, and the coloring Print proof) |
| `POST /api/projects/{key}/generation` | `{identity}`; saved-source batch report |
| `POST /api/projects/{key}/draft/validate` | `{source}`; normalized valid project and semantic identity |
| `POST /api/projects/{key}/draft/preview` | `{source}`; core batch, verification and authoritative solution cells |
| `POST /api/projects/{key}/draft/plan` | `{source}`; verified publication plan, verification and generation summary |
| `POST /api/projects/{key}/draft/save` | `{source, revision}`; reloaded authoritative state and new revision |
| `GET /api/projects/{key}/interior` | Saved interior state (`missing`, `current`, `stale`, `invalid`), preflight report, preview pages and overlay geometry |
| `POST /api/projects/{key}/interior/build` | `{revision}`; builds saved source, writes interior and `preflight.json`, returns state or `{build: {success: false, stage, diagnostics}}` |
| `GET /api/projects/{key}/interior/pages/{n}` | `?size=thumb\|page\|detail&pdf=<sha256>`; PNG raster of page `n` of that exact PDF |
| `GET /api/projects/{key}/interior/pdf` | `?pdf=<sha256>`; the built `interior.pdf` as an attachment while it is that exact file (409 `preview_stale`); Studio links it for coloring books |
| `GET /api/projects/{key}/cover` | Saved cover state (`no_config`, `missing`, `current`, `stale`, `invalid`), cover preflight report, layout geometry |
| `POST /api/projects/{key}/draft/cover` | `{source}`; renders the draft's cover in memory; layout geometry with each text line's layer and face, interior facts, checks (with their layer), `buildable`, `display` text, the photo and font `library` (per-photo DPI, per-font missing characters) and the preview digest |
| `GET /api/projects/{key}/cover/preview` | `?size=preview\|detail&pdf=<sha256>`; PNG of a draft PDF or `cover.pdf` (409 when gone) |
| `GET /api/projects/{key}/cover/assets` | Photos in `cover-assets` with pixels, orientation and problems |
| `POST /api/projects/{key}/cover/assets` | `?name=`; raw `image/jpeg` or `image/png` body (one of two non-JSON POSTs, with font uploads); imports and returns the asset |
| `GET /api/projects/{key}/cover/assets/thumbnail` | `?path=cover-assets/<name>`; upright sRGB JPEG preview (360 px) of a listed photo |
| `GET /api/projects/{key}/cover/fonts` | Fonts in `cover-assets/fonts` with names, glyph count and embedding permission, or why each is unusable |
| `POST /api/projects/{key}/cover/fonts` | `?name=`; raw `font/ttf` or `font/otf` body; validates, imports and returns the font |
| `GET /api/projects/{key}/cover/fonts/specimen` | `?font=cover-assets/fonts/<name>` or `bundled:<face>`; PNG of a specimen drawn by ReportLab and rasterized by PDFium |
| `POST /api/projects/{key}/cover/build` | `{revision}`; builds saved source, writes `cover.pdf`, `cover.json`, `cover-preflight.json` |
| `POST /api/projects/{key}/draft/cover/convert` | `{source}`; the version 3 form of a version 1/2 cover with its preview and identity check; writes nothing |
| `POST /api/projects/{key}/draft/cover/presets` | `{source}`; named design presets for this cover; writes nothing |
| `POST /api/projects/{key}/draft/interior` | `{source}`; representative pages of the draft's interior with their `roles`, page count, resolved design, warnings and `answers` (per page, answer pages, last page count, every choice's fit); on a layout failure the diagnostics and `answers`; writes nothing |
| `GET /api/interior/designs` | Built-in themes and page layouts with what each sets (Python's catalogue) |
| `POST /api/projects/{key}/draft/interior/export` | `{source, name}`; the draft's design as a `puzzlepress-interior-design` JSON attachment, without photographs |
| `POST /api/projects/{key}/draft/interior/import` | `{source, text}`; validates a design file and returns `{success, name, interior}` for the draft (keeping its photographs) or `{success: false, issues}`; writes nothing |
| `GET /api/projects/{key}/draft/interior/pages/{n}` | `?size=&pdf=<sha256>`; PNG of a draft sample page |
| `POST /api/projects/{key}/assets/list` | `{source?}`; photos and fonts with their uses in the saved source and draft, and the trash |
| `POST /api/projects/{key}/assets/trash` | `{path, sha256, revision, source?}`; moves an unused asset to the trash (409 `asset_in_use` with `uses`, `asset_changed`, `source_changed`) |
| `POST /api/projects/{key}/assets/restore` | `{trashed}`; restores under the original name (409 `asset_collision`) |
| `POST /api/projects/{key}/assets/purge` | `{trashed, sha256}`; deletes a trashed file permanently |
| `GET /api/projects/{key}/reviews` | Review states for every puzzle with current identities, the sidecar revision and the saved source revision |
| `POST /api/projects/{key}/reviews/record` | `{source_revision, revision, puzzle, status, identity, note, reviewer, reviewed_on}`; records a judgment of the saved content (409 when either revision is stale) |
| `POST /api/projects/{key}/reviews/policy` | `{revision, require_all}` |
| `GET /api/projects/{key}/proofs` | Proof records with currency, and the artifacts now in the build directory |
| `POST /api/projects/{key}/proofs/record` | `{revision, record}`; 409 `artifacts_changed` when the named artifacts are not the current ones |
| `POST /api/projects/{key}/proofs/remove` | `{revision, id}` |
| `GET /api/projects/{key}/production` | Overview items, stages, proofing steps, artifact assessment, review summary, proofs |
| `POST /api/projects/{key}/rebuild` | `{revision}`; runs the planned steps for the saved revision and returns the recomputed overview with per-step results (`source_changed` if an edit lands mid-run) |
| `GET /api/projects/{key}/publishing` | Readiness report, KDP metadata record, checklist, package identity, export state (`none`, `current`, `stale`, `damaged`), location, built cover digest |
| `POST /api/projects/{key}/draft/publishing` | `{source}`; `{metadata, upgrade}`: findings and confirmation states with current review identities for the draft, and the version 2 form of a version 1 section; writes nothing |
| `POST /api/projects/{key}/publishing/export` | `{revision, archive}`; exports the saved revision's package (409 `source_changed`), or returns why not and writes nothing |
| `GET /api/projects/{key}/planning` | `{book, revision, source, report, options}`; `revision`, `source` and `report` are null without `planning.yaml` |
| `POST /api/projects/{key}/draft/planning` | `{source}`; `{report}` for an unsaved plan, or 422 `invalid_planning` with field issues; writes nothing |
| `POST /api/projects/{key}/planning/save` | `{source, revision}`; replaces `planning.yaml` at that revision (`null`: create; 409 `source_changed` otherwise) |
| `POST /api/projects/{key}/planning/approval` | `{revision, identity}`; approves the saved revision's reviewed identity, or withdraws with `null` (409 `identity_mismatch`, `not_ready`, `source_changed`) |

Revision is `sha256-<digest of exact source bytes>`. It detects cosmetic changes
and output edits that semantic identity intentionally excludes. Identical bytes
have the same revision, including repeated canonical saves. Draft validation has
no persisted revision (`null`). Build identity/version and per-puzzle seed
contracts are unchanged. Reports retain the CLI structure and string seeds.

Errors use `{"error":{"code":"...","message":"...","issues":[]}}`.
Invalid project/draft: 422; missing project: 404; stale source: 409; save I/O failure:
503; unexpected programming failure: generic 500 with logged diagnostics.
One generation or plan runs per service at a time; competing requests receive
`409 generation_busy`. Planning a draft without composition returns `422 no_composition`. Expected per-puzzle generation failures are in the
HTTP 200 batch report. Closing a page does not interrupt already-running Python.
JSON POSTs require same-origin Origin when supplied, local Host and JSON content
type. CSP and no-store response headers remain enabled; no CORS, auth or telemetry.

Routes: `/books`, `/books/{key}`, `/books/{key}/edit`, `/books/{key}/book`, `/books/{key}/interior`, `/books/{key}/print`, `/books/{key}/cover`, `/books/{key}/publishing`, `/books/{key}/planning`, `/books/{key}/puzzles`,
`/books/{key}/puzzles/{id}`, `/books/{key}/quality`. Deep links serve the shell.

## Design, accessibility and screenshots

The established paper/green design, supplied logo, locally bundled Newsreader and
Public Sans remain ([design](../DESIGN.md)). Controls are 34-36 px on desktop and
44 px on touch screens. Desktop editing sits alongside preview; narrower views
stack and include a preview jump. Tab lists use arrow keys; the cover canvas
announces the selected layer and its keys, and moves are announced politely. Labels, fieldsets, explicit buttons, focus outlines,
keyboard reorder controls, native discard/delete confirmations and polite status
messages support keyboard operation. Solutions also use underlines and a textual
one-based coordinate register; the API remains zero-based. Large grids scroll
inside their region. Reduced-motion behavior remains.

Actual captures from disposable projects:
[editor](images/studio/editor.png), [word editing](images/studio/word-editing.png),
[draft solution](images/studio/draft-preview.png), [quality](images/studio/editor-quality.png),
[validation](images/studio/editor-validation.png), [conflict](images/studio/editor-conflict.png),
and [1440](images/studio/editor-1440.png), [1024](images/studio/editor-1024.png),
[768](images/studio/editor-768.png), [390](images/studio/editor-390.png) widths.
Composer: [overview](images/studio/composer.png), [front matter](images/studio/composer-front-matter.png),
[ordering](images/studio/composer-order.png), [plan](images/studio/composer-plan.png),
[validation](images/studio/composer-validation.png), and [1440](images/studio/composer-1440.png),
[1024](images/studio/composer-1024.png), [768](images/studio/composer-768.png),
[390](images/studio/composer-390.png) widths. Above 1200px the plan stays in view while
editing; narrower layouts stack it below the outline with a **Jump to plan** link.

## Checks

From the repository root, with the environment activated:

```text
python -m pytest --basetemp=.pytest_cache/tmp
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pip check
```

From `studio/`:

```text
npm ci
npm run check
npm test
npm run build
npm ls --depth=0
npx playwright install chromium
npm run test:browser
```

`check` runs strict TypeScript, ESLint and Prettier. Browser tests start
`e2e/server.py` on port 8015 with disposable temporary copies, never reuse a running
server, and verify the repository fixtures' bytes remain unchanged. API writes
also use pytest temporary projects. Browser checks cover real edit/preview/save/
reload, deterministic preview, conflict, simulated HTTP save failure, field errors,
keyboard operation, responsive layouts and axe, for Edit, the Book composer and the
Print proof (real build, preflight, rasterized pages, overlays, spreads), and in
`e2e/polish.spec.ts` for region design, the asset trash, interior styles, rebuilds,
editorial review and proof records. For installed Chrome on Windows,
set `$env:STUDIO_BROWSER_CHANNEL='chrome'` before running browser tests.
The Python Windows/Linux 3.11/3.13/3.14 CI matrix and separate Linux browser job
remain unchanged; local results do not establish remote CI status.

## Limits

Existing ASCII/size/search limits apply. No extra schema fields, calibrated
scores, automatic content repair, persisted previews, collaboration or cloud.
Only Chrome/Chromium is exercised; axe is not screen-reader certification.
Starlette warns about its deprecated httpx test client. Page previews need
`pypdfium2` (in the `studio` extra). Publishing exports a local package only; it never
logs in to, uploads to or submits anything in KDP.
Publishing captures: [overview](images/studio/publishing.png),
[metadata](images/studio/publishing-metadata.png),
[AI disclosure](images/studio/publishing-disclosure.png),
[readiness](images/studio/publishing-readiness.png),
[blocking findings](images/studio/publishing-blocking.png),
[ready package](images/studio/publishing-ready.png),
[export](images/studio/publishing-export.png), [390](images/studio/publishing-390.png).
Planning captures: [overview](images/studio/planning.png),
[themes](images/studio/planning-themes.png), [vocabulary](images/studio/planning-vocabulary.png),
[progression](images/studio/planning-progression.png), [coverage](images/studio/planning-coverage.png),
[approved](images/studio/planning-approved.png), [stale approval](images/studio/planning-stale.png),
[390](images/studio/planning-390.png).
Cover captures: [overview](images/studio/cover.png), [start](images/studio/cover-start.png),
[text layers](images/studio/cover-layers.png), [fonts](images/studio/cover-fonts.png),
[print quality](images/studio/cover-print-quality.png),
[1024](images/studio/cover-1024.png), [768](images/studio/cover-768.png),
[front crop](images/studio/cover-crop.png), [full wrap](images/studio/cover-wrap.png),
[overlays](images/studio/cover-overlays.png), [spine](images/studio/cover-spine.png),
[readiness](images/studio/cover-readiness.png), [1440](images/studio/cover-1440.png),
[390](images/studio/cover-390.png).
Production design captures: [convert to regions](images/studio/cover-convert.png),
[layers](images/studio/cover-layers-stack.png), [regions 1440](images/studio/cover-regions-1440.png),
[1024](images/studio/cover-regions-1024.png), [768](images/studio/cover-regions-768.png),
[390](images/studio/cover-regions-390.png), [asset library](images/studio/assets-library.png),
[asset removal](images/studio/assets-remove.png), [interior design](images/studio/interior-design-1440.png),
[interior 390](images/studio/interior-design-390.png), [rebuild plan](images/studio/rebuild-plan.png),
[rebuild results](images/studio/rebuild-results.png), [editorial review](images/studio/puzzles-review.png),
[final steps](images/studio/publishing-final-steps.png).
Print captures: [overview](images/studio/print.png), [puzzle](images/studio/print-puzzle.png),
[spread](images/studio/print-spread.png), [overlays](images/studio/print-overlays.png),
[findings](images/studio/print-findings.png), [status](images/studio/print-kdp-not-ready.png),
[390](images/studio/print-390.png).
