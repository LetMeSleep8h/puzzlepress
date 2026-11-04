# Paperback cover

PuzzlePress builds a deterministic full-wrap paperback cover (back, spine and
front in one PDF) from your own photograph, a small semantic configuration and
the physical facts of the built interior. Version 2 adds per-layer text
controls, extra text layers and imported fonts. Version 3 designs the back, spine
and front as separate regions with a stack of photographs, rectangles, ellipses,
lines and text boxes ([production design](production-design-polish.md)). It is not
an image editor and has no AI generation, stock search, effects, transparency or
free-form paths.

Word-search and coloring books share this cover unchanged: the cover reads only
the built interior's page count, trim and paper, so a coloring cover's spine is
sized from the coloring interior exactly like a word-search one. A cover may use
a drawing as its photograph (imported into `cover-assets` like any photo). Text
boxes may print `{page_count}` and `{trim_size}`, filled in from the verified
interior whenever the cover is laid out
([template variables](cover-templates-rich-text.md)).

```text
interior.pdf + interior.json ──> verified interior facts (page count, trim, paper)
                                         │
photograph (cover-assets, SHA-256) ──> decode ──┐
cover section of book.yaml ─────────────────────┼──> CoverLayout ──> validation
                                                │        │
                                         cover geometry  └──> cover.pdf ──> inspection
                                                                 │
                                                  cover.json + cover-preflight.json
```

```text
puzzlepress book build books/cover-demo
puzzlepress cover inspect books/cover-demo
puzzlepress cover build books/cover-demo
puzzlepress cover preflight books/cover-demo
puzzlepress cover import books/my-book ~/Pictures/harbour.jpg
```

Code lives in `puzzlepress.cover`: `assets` (import, reads, decoding), `crop`,
`geometry`, `fonts`, `layout`, `model`, `validation`, `render`, `inspection`,
`build` (pipeline, identity, manifest, the only writer) and `preflight`. The
schema is `cover_config.py` / `cover_validation.py`; the CLI is `cover_cli.py`.

## Configuration

The cover is an optional, versioned `cover` section of `book.yaml`. It lives in
the project file so Studio edits it through the same draft, revision check and
atomic save as everything else; there is no second store. It requires a
`composition`, because the spine is sized from the built interior.

```yaml
cover:
  version: 1                 # required: 1, 2 or 3; other versions are rejected
  layout: full_wrap          # full_wrap | front_photo
  image:
    path: cover-assets/harbour-dusk-34b4d3b99667.jpg
    sha256: 34b4d3b99667a8361dbed0eb299622ba9c3231a6cde69a55888faca7347ac786
  crop: {x: 0.5, y: 0.45, zoom: 1.0}   # focal point 0..1, zoom 1..4
  type: {style: editorial, position: top, align: center, tone: light}
  legibility: shade          # shade | panel | none
  background: '#1f2a33'      # sRGB fill wherever the photo does not print
  spine_text: auto           # auto | none
  back_text: |-              # optional, 1..1,200 characters of plain text
    Twenty word searches from harbour walls and lighthouse paths.
```

| Field | Values |
| --- | --- |
| `layout` | `full_wrap`: one photo bleed to bleed across back, spine and front. `front_photo`: photo on the front panel and its three bleed edges; spine and back are the fill color. |
| `type.style` | `editorial` (Newsreader serif), `bold` (uppercase Vera Sans Bold), `minimal` (Vera Sans) |
| `type.position` | `top`, `middle` or `bottom` title block (author at the foot, or above for `bottom`) |
| `type.align` / `tone` | `center` or `left`; `light` or `dark` text |
| `legibility` | `shade` pulls photo pixels behind text toward black (light text) or white (dark text) with a soft ramp, baked into the image; `panel` draws an opaque band of the fill color; `none` |

Cover text comes from the book: the front uses `book.title`, `subtitle` and
`author`; the back uses `book.imprint` and the optional `back_text`. Nothing is
invented: no reviews, prices, ISBN, URLs or marketing text. Validation reports
structured paths (`cover.crop.x [crop_out_of_bounds]`, `cover.image.path
[asset_path]`) and never repairs. Crop values are normalized to four decimals and
colors to lowercase.

### Version 2: text layers and imported fonts

`version: 2` accepts three optional fields; `version: 1` keeps its exact meaning,
rejects them (`requires_version_2`) and lays out, renders and identifies exactly as
before. Studio sets version 2 only when a version 2 control is first used.

```yaml
cover:
  version: 2
  fonts:                      # at most 8; imported with `cover import` or Studio
  - id: harbour-display
    path: cover-assets/fonts/harbour-display-292646cbb948.ttf
    sha256: 292646cbb948153511e308fa80def59959746d70114bd0936ba0a7f67a33181d
    license: SIL Open Font License 1.1   # what you record; null = unknown
    source: https://example.org/where-you-got-it
  text:                       # overrides by role; omit a field to keep the layout's
    title: {visible: false}   # hidden on the cover; book.title is unchanged
    subtitle:
      font: harbour-display   # a bundled face or a fonts[].id
      size: 24                # points (4-160); without it titles step down to fit
      color: '#f5d27a'
      align: right            # left | center | right
      line_spacing: 1.2       # x the size, baseline to baseline (0.8-3)
      letter_spacing: 1.5     # points between characters (-2 to 20)
      case: upper             # upper | as_written
      offset: {x: 0, y: -36}  # points from the layout's position; x right, y up
    author: {text: "A. N. Author"}   # display text; must match the book details
  extra:                      # at most 8 additional lines of your own text
  - {id: tagline, panel: front, text: "Sixty puzzles from the coast", size: 18}
```

| Field | Meaning |
| --- | --- |
| `text.<role>` | `title`, `subtitle`, `author`, `back_text`, `imprint`. `back_text` takes no `text` (edit `cover.back_text`). |
| `visible` | `false` hides the layer on the cover only. The book details are never changed. |
| `text` | Display text for a book-detail role, for example with a line break. KDP requires cover information to match the book details, so publishing blocks (`cover_text_matches`) unless it equals them apart from spacing, line breaks and capitals. |
| `font` | Bundled faces: `serif-display`, `serif`, `serif-italic`, `sans`, `sans-bold`, `sans-italic`; or an imported font's `id`. |
| `offset` | Moves the layer from where the layout places it. Text moved outside its safe area, onto the barcode corner or over other text fails layout validation (the build refuses; Studio previews it and says why). |
| `extra[]` | `id`, `panel` (`front`/`back`), `text` (up to 300 characters) and the same overrides; laid out centred in the panel's type area, then moved by `offset`. |

Defaults keep the preset: with no overrides every position is computed exactly as
in version 1. Hiding the title or author is allowed; publishing reports it as the
`cover_text_omitted` warning, because KDP's formatting help requires cover
information to match the book details but does not state that the title must
appear (read 2026-10-10, "Fix Paperback and Hardcover Formatting Issues").

### Version 3: regions and elements

`version: 3` replaces `layout`, `image`, `crop` and `background` with `regions`
(a color and optional gradient for back, spine and front) and `elements` (up to
24, at most 4 photographs), positioned in points from each region's bottom-left
trim corner. `type`, `legibility`, `spine_text`, `back_text`, `fonts`, `text` and
`extra` keep their version 2 meaning (version 1 and 2 reject `regions` and
`elements` with `requires_version_3`), and book text is drawn above every element.
Translucent shapes are flattened by Python against one solid color or one
photograph, or reported (`opacity_not_flattenable`). Nothing converts a cover
implicitly; Studio's **Convert to regions** produces a version 3 cover that
renders the same bytes. The full schema, coordinate system, spine and barcode
rules are in [production design](production-design-polish.md#cover-regions-cover-version-3).

### Templates and rich text

A template applies a complete version 3 design without touching the book
details. `back_text` (version 2 and up) and text boxes (version 3) may hold a
rich text document instead of a string. Unformatted text stays a plain string,
and every cover that does not use formatting renders the same bytes as before.
Both are described in [cover templates and rich text](cover-templates-rich-text.md).

### Imported fonts

A deliberately bounded first implementation: one static font with TrueType (glyf)
outlines per `.ttf` or `.otf` file, at most 10 MB. Import validates the whole file
from memory before writing (`cover import PROJECT FONT.ttf` or Studio), copies the
original bytes to `cover-assets/fonts/<name>-<sha256 prefix>.ttf|otf`, reuses
identical bytes and never overwrites. Refused with a code:

| Code | Font |
| --- | --- |
| `font_unsupported_outlines` | OpenType with PostScript (CFF) outlines (`OTTO`): ReportLab cannot embed them |
| `font_variable_unsupported` | Variable fonts (`fvar`, `gvar`, ...): deferred; import a static instance |
| `font_collection_unsupported` | `.ttc` collections |
| `font_unsupported` | WOFF/WOFF2, other extensions, over 10 MB |
| `font_embedding_restricted` | OS/2 `fsType` forbids embedding (restricted license), allows bitmap embedding only, or forbids subsetting (PuzzlePress embeds subsets) |
| `font_corrupt` | Damaged files, bad table checksums, missing required tables (including OS/2), no character map |
| `font_missing`, `asset_digest_mismatch` | The configured file is gone or changed since it was chosen |

Installable, editable and preview-and-print fonts may be embedded in a print PDF.
`license` and `source` are what you record; PuzzlePress never infers them, and an
unknown value is the `cover_font_license` warning. Reading the embedding flags is
not a license review: confirm that your license allows commercial print use.
Fonts are parsed by ReportLab in pure Python from memory under a digest-derived
name, so no system font or search path is consulted and nothing in the font is
executed by PuzzlePress (PDFium/FreeType interpret TrueType hinting when Studio
rasterizes previews). Characters the font cannot draw fail with
`unsupported_character` naming each code point; Studio lists them per font before
you choose it. The same Python layout and renderer produce Studio's preview and
`cover.pdf`; the browser never draws cover type.

**Identity boundary.** The cover is excluded from the project build identity, so
editing a crop never makes the interior stale. It is identified by the cover
identity instead (below).

## Photographs

- **Import.** `cover import` and Studio copy the original bytes, unchanged, into
  the project's `cover-assets/` folder as `<name>-<sha256 prefix>.jpg|png`.
  Imports never overwrite; identical bytes reuse the existing file; a different
  file under the same name is refused. Paths are validated
  (`cover-assets/<lowercase-name>.jpg`), so absolute or machine paths never enter
  the project. Unreferenced imports are never deleted automatically.
- **Formats.** JPEG and PNG, at most 64 MB and 80 megapixels. HEIC is not
  supported. Errors: `image_missing`, `image_corrupt`, `image_unsupported`,
  `unsupported_color_mode` (CMYK, 16-bit, bilevel, unreadable ICC profile),
  `transparency_not_supported` (any alpha below fully opaque),
  `asset_digest_mismatch` (the file no longer matches its pinned SHA-256).
- **Normalization.** One decode serves layout, preview and PDF: EXIF orientation
  is applied (all eight values are tested), an embedded ICC profile is converted
  to sRGB with Pillow's LittleCMS (perceptual intent), otherwise sRGB is assumed,
  and the result is 8-bit RGB without alpha.
- **Privacy.** Only the orientation tag is read. The original in `cover-assets`
  keeps whatever metadata the camera wrote, because it is your source file. The
  PDF never does: the printed pixels are re-encoded from bare pixel data as a
  baseline JPEG with only a JFIF header, and inspection rejects any APP1-APP15
  (EXIF, GPS, XMP, ICC, IPTC) or COM segment. Tests embed camera, artist, GPS and
  comment markers and assert none reach `cover.pdf`.

## Watermark

Version 2 and 3 covers accept an optional `watermark`, baked by Python into the
derived pixels of the photograph under it; the photo in `cover-assets/` is never
changed and the PDF carries no transparency.

```yaml
watermark:
  enabled: true          # false keeps the settings and renders exactly as without
  text: "Photo: Your Name"   # 1..60 characters, one line (Vera Sans Bold)
  opacity: 0.35          # 0.05..1
  position: bottom-right # top|middle|bottom-left|center|right, or center
  scale: 0.25            # text width as a fraction of the front trim width (0.05..0.8)
  margin: 27             # points from the front trim edges (9..216)
  shadow: false          # a soft dark copy offset down-right
  color: '#ffffff'
```

Build fails, never moves it, when the watermark leaves the front safe area
(`watermark_outside_safe_area`), comes within 4 pt of cover text
(`watermark_overlaps_text`), or is not wholly over one photograph
(`watermark_outside_photo`).

## Crop and resolution

A focal point `(x, y)` in the upright photo and a `zoom`. The photo scales
uniformly until it covers its region (cover-fit), then by `zoom`; the window of
source pixels is centered on the focal point and clamped inside the photo. The
applied center is reported. Nothing is stretched. `crop.py` is the single
implementation; Studio maps drags and keys onto `(x, y, zoom)` and never
computes crops itself.

The renderer draws exactly the whole source pixels covering that window, scaled
so the window lands on the region and clipped to it. No resampling occurs.

**Effective DPI** = source pixels inside the window ÷ printed inches of the region
(the same on both axes). The original file's DPI tag is ignored. Results are
`ok`, `image_low_effective_dpi` (zoom out to reach 300) or `image_too_small`
(even zoom 1 is below 300). Low resolution never fails a build; it blocks KDP
readiness.

## Full-wrap geometry

PDF points (1 in = 72 pt), origin at the bottom-left corner of the bleed. Left to
right: bleed | back | spine | front | bleed.

```text
width  = 0.125 + trim width + spine + trim width + 0.125 in
height = 0.125 + trim height + 0.125 in
spine  = interior page count x paper thickness
```

| Paper (black ink) | Inches per page |
| --- | --- |
| White | 0.002252 |
| Cream | 0.0025 |

Example: 300 cream pages give a 0.75 in spine and an 18.0 x 11.25 in wrap; the
35-page cover demo on white paper is 17.3288 x 11.25 in with a 0.0788 in spine.

Regions: media, trim, back, spine, front; KDP safe areas (front and back inset
0.125 in from trim and folds; spine inset 0.0625 in from each fold and 0.125 in
from top and bottom); PuzzlePress type areas (0.5 in from every panel edge, which
layout uses); the barcode box and its keep-clear corner.

**Interior facts.** Geometry comes only from a current interior: `interior.json`
must match `interior.pdf` (SHA-256 and size), recompute its interior identity,
name the current source, profile and toolchain, and the page count is counted in
the PDF itself. Authors never type a page count or spine width.

**Paper** is a property of the print profile, never inferred:
`paperback-8.5x11` v2 states white paper and `paperback-8.5x11-cream` v1 cream
(`book build --profile`, or the Paper choice in Studio's Print tab). The page
layout is identical; the interior identity differs. Groundwood is not offered
because KDP publishes no spine multiplier for it; color interiors are not supported.

## Spine text

KDP's page states both "more than 79 pages" and "at least 79 pages"; PuzzlePress
applies the stricter reading, 80 pages or more. When eligible, the title (top)
and author (bottom) read top to bottom, centered across the spine, in the preset
face at up to 14, 13 or 12 pt (editorial, bold, minimal), as large as the 0.0625 in clearances allow and never below 7 pt.
Spine text is omitted with a stated reason when the book is too short
(`page_count`), the spine cannot hold 7 pt type (`spine_too_narrow`: below about 99 white or
89 cream pages for the editorial preset, 106 or 96 for the sans presets) or the author chose `none`. Text that
fits across but not along the spine fails with `spine_text_overflow`. Real
interiors exercise both outcomes: a 95-page book on white paper reaches 80 pages
but its 0.214 in spine omits text as `spine_too_narrow` (tested with the synthetic
production book); a synthetic 152-page book's 0.342 in spine printed it at 14 pt
(measured, [production scale](production-scale.md)).

## Barcode area

KDP prints a 2 x 1.2 in barcode in the lower-right corner of the back cover when
you do not supply one. That size and corner are KDP's; the paperback offsets are
not stated. PuzzlePress assumes 0.25 in from the bottom trim and from the spine
fold (KDP's hardcover guidance) and reserves the whole corner from the trim and
fold to 0.125 in beyond that box. No text may enter it; the photograph may, since
KDP's white box covers it. No barcode or ISBN is generated.

## Typography

| Role | Editorial | Bold | Minimal |
| --- | --- | --- | --- |
| Title | Newsreader 72pt cut, 62 down to 36 pt | Vera Sans Bold caps, 60-34 | Vera Sans, 42-28 |
| Subtitle | Newsreader italic 20 | Vera Sans 17 | Vera Sans 14 |
| Author | Newsreader 17 | Vera Sans Bold caps 14 | Vera Sans 12.5 |
| Back text / imprint | 12.5 / 10.5 italic | 11.5 / 9.5 | 11 / 9 |

Titles step down 2 pt at a time to fit at most three lines, within the preset
range; otherwise the build fails with `text_overflow`. Subtitles fit three lines,
authors two, back text the area above the barcode corner. Characters a face cannot
draw (beyond Latin-1 for Vera) fail with `unsupported_character`.

Version 2 overrides replace a preset's face, size, pitch, case, color or
alignment per layer; an explicit size sets every line at that size (up to six lines)
instead of stepping down. Letter spacing is drawn with the PDF character spacing
operator and included in every measurement.

Fonts are bundled and pinned by SHA-256: the interior's Bitstream Vera Sans and
three static Newsreader cuts (`Newsreader72pt-Regular`, `Newsreader16pt-Regular`,
`Newsreader16pt-Italic`) from github.com/productiontype/Newsreader at commit
`cfcb4f7`, licensed under the SIL Open Font License 1.1 (no reserved font name;
`src/puzzlepress/cover/fonts/OFL.txt`). They are embedded as TrueType subsets.

## PDF

One page; MediaBox = BleedBox = full wrap; TrimBox = trim. Drawing order:
background fill, the clipped photograph (one DCTDecode DeviceRGB image,
quality 95, 4:4:4, no metadata, embedded unchanged), legibility panels, text.
No transparency, strokes, crop or trim marks, annotations, forms, bookmarks,
guides or overlays. ReportLab invariant mode fixes dates and the document ID;
descriptive metadata is empty.

**Color.** The PDF is DeviceRGB with sRGB-normalized photo pixels and sRGB fills.
PuzzlePress does no CMYK conversion and writes no output intent. KDP says images
"should be in CMYK"; preflight reports this as a warning and you should judge
color from a printed proof. Exact printed color is not claimed.

**Determinism.** Identical source, photograph, interior facts, toolchain (ReportLab,
Pillow, fonts) and renderer version give byte-identical `cover.pdf` and
`cover.json`. Tests compare bytes in-process and in another process with a
different working directory and `PYTHONHASHSEED`; CI rebuilds and compares.

**Inspection.** After rendering, pypdf reopens the bytes and checks page count,
the three boxes, rotation, annotations, catalog entries, layers, transparency,
that every font is an embedded bundled subset, exactly one image of the layout's
pixel size with no metadata segments, no stroke operators, no descriptive or XMP
metadata, and that every line of cover text is present.

## Identity, manifest and staleness

`pp1-cover-sha256-...` over canonical JSON of: book ID, the semantic cover config
(photo and imported fonts by SHA-256, not file name; a font's recorded license and
source are provenance and excluded), the cover text, interior physical facts (page
count, profile ID and version, trim, paper, ink), the cover profile (KDP cover
constants and PuzzlePress insets, version 1) and the toolchain (cover renderer
version 1, engine version, ReportLab, Pillow, font digests). No paths or times.

`cover.json` (manifest version 1) records those inputs, the identity, provenance
(interior identity, source identity, interior PDF SHA-256, the photo's project
path), geometry, photo facts, resolution, embedded pixel size and encoding,
spine-text status, what each book detail prints (`display`: the title, subtitle,
author and imprint as shown, or null when hidden; publishing compares it with the
book details), the color model and the PDF's SHA-256 and size. Existing covers keep
their identity and PDF bytes; only `cover.json` gains `display` when rebuilt.

A rebuilt interior with the same physical facts keeps the cover identity: the
cover still fits, and preflight warns that its provenance names the earlier
interior. A change to page count, paper, profile, trim, photo, crop, design,
cover text, cover rules or toolchain makes the cover stale, and preflight names
which. Modification times are never used.

## Cover preflight

`cover preflight` observes: it reads `cover.pdf`, `cover.json`, the interior beside
them and the pinned photo, renders the expected cover in memory and compares. It
never writes anything except `cover-preflight.json` (`--no-write` opts out). Rule
scopes, severities, outcomes and the rule that unevaluated error rules block are
those of [interior preflight](preflight.md). Ruleset `puzzlepress-kdp-cover` v3
(v2 added `cover_fonts` and `cover_font_license`; v3 adds the design warnings
`kdp_spine_design` and `kdp_barcode_design`, not applicable before version 3);
report version 1; KDP rules checked 2026-10-07 (font wording read 2026-10-10).

| Code | Scope | Checks |
| --- | --- | --- |
| `cover_configured` | structural | The project has a cover section |
| `cover_artifacts` | structural | `cover.pdf` and `cover.json` are regular files |
| `cover_manifest` | structural | Manifest names this book, identity recomputes, PDF digest and size match |
| `interior_current` | structural | Interior present, intact and built from current source, profile and toolchain |
| `cover_photo` | structural | Photo present, matches its pin and decodes |
| `cover_fonts` | structural | Imported fonts present, pinned, static TrueType and embeddable (n/a without imported fonts) |
| `cover_buildable` | structural | Current inputs lay out, validate and render |
| `cover_current` | structural | Recorded identity equals the current one (`cover_stale`, with reasons) |
| `cover_interior_provenance` | structural warning | Interior rebuilt after the cover with the same facts |
| `cover_matches_render` | structural | PDF bytes equal a fresh render |
| `cover_pdf_structure` | structural | The inspection contract above |
| `kdp_cover_page_count` | KDP | Interior has at least 24 pages |
| `kdp_cover_dimensions` | KDP | Page size equals the wrap formula for the current interior |
| `kdp_cover_bleed` | KDP | Background and photo reach every bleed edge |
| `kdp_cover_image_resolution` | KDP | Effective DPI at least 300 |
| `kdp_cover_text_safe_area` | KDP | Front and back text 0.125 in inside trim and folds |
| `kdp_spine_text` | KDP (ambiguous) | Spine text only from 80 pages; 0.0625 in fold clearance |
| `kdp_barcode_area` | KDP (ambiguous) | No text in the barcode corner |
| `kdp_cover_font_size` | KDP | All text at least 7 pt |
| `kdp_cover_fonts_embedded` | KDP | Every font embedded |
| `kdp_cover_flattened` | KDP | No transparency or layers |
| `kdp_cover_no_marks` | KDP | No stroked marks or guides, annotations, forms or bookmarks |
| `kdp_cover_not_encrypted` | KDP | Not encrypted |
| `kdp_cover_file_size` | KDP | At most 650 MB |
| `kdp_cover_file_size_recommended` | KDP warning | KDP recommends 40 MB or less |
| `kdp_cover_color_space` | KDP warning (ambiguous) | RGB images while KDP recommends CMYK |
| `cover_font_license` | KDP warning (ambiguous) | An imported font without a recorded license or source |
| `kdp_spine_design` | KDP warning | Spine background differs from a neighbor at the fold, or a spine element is within the fold variance |
| `kdp_barcode_design` | KDP warning | A design element lies in the barcode keep-clear area |

**Classification.** Expected build failures (stages `config`, `interior`, `asset`,
`geometry`, `layout`, `layout_validation`, `pdf_verification`, `output`) write
nothing: missing or stale interior, missing, corrupt or changed photo, invalid
crop, impossible text. KDP readiness concerns build and are reported: page count,
resolution, color. Safe areas, spine eligibility and the barcode corner are
guaranteed by layout and re-checked by preflight.

States: `no_config`, `missing`, `current`, `stale` (cover or interior inputs
changed), `invalid` (other structural failures). The 11-page `composition-demo`
gives a structurally valid cover that is not KDP ready; the 35-page `cover-demo`
is valid and ready with one color warning.

## KDP provenance

Read on 2026-10-07 from official KDP help pages. Search snippets were used only
to locate pages.

| Value | Source | Status |
| --- | --- | --- |
| Wrap formula, 0.125 in bleed | Create a Paperback Cover | requirement |
| White 0.002252, cream 0.0025 in/page; premium color 0.002347 (not modeled) | Create a Paperback Cover | requirement |
| Spine text page threshold | Create a Paperback Cover | ambiguous ("more than 79" and "at least 79"); 80 applied |
| 0.0625 in spine clearance; 0.125 in text safe area | Create a Paperback Cover | requirement |
| 300 DPI, 7 pt, embedded fonts, flattened, no marks | Create a Paperback Cover | requirement |
| "Images should be in CMYK" | Create a Paperback Cover | recommendation, warning |
| 650 MB limit; 40 MB recommended | Create a Paperback Cover | requirement; recommendation |
| Barcode 2 x 1.2 in, lower-right of back cover | Low-Content Book Barcode Details | requirement; offsets assumed |
| 24-page minimum | Paperback Submission Guidelines | requirement |
| Groundwood paper exists, no spine multiplier published | Print Options | not supported |

The same page says spine shifts "up to 0.0125 in" with "(3.2 mm)", which is
0.125 in; the 0.0625 in clearance is what is enforced. Values live only in
`interior.spec.KdpCoverConstraints`. To update: re-read these pages, change the
constants, bump `RULESET_VERSION` in `cover/preflight.py` when a verdict can
change and `COVER_PROFILE_VERSION` in `cover/build.py` when geometry changes, and
add boundary tests.

## CLI

All commands read the project's output directory (or `--output DIR`), which must
hold the built interior.

- `cover inspect PROJECT [--json]`: interior facts, wrap size, spine width and
  eligibility, photo resolution. Read-only.
- `cover import PROJECT PHOTO [--json]`: copy a photo into `cover-assets` and
  print the `path` and `sha256` to reference. It never edits `book.yaml`.
- `cover build PROJECT [--json]`: build, verify and write `cover.pdf` and
  `cover.json`. Exit 0 written, 1 expected failure (JSON
  `{success: false, stage, diagnostics}`; nothing written), 2 usage.
- `cover preflight PROJECT [--json] [--no-write]`: exit 0 structurally valid and
  KDP ready, 1 otherwise; `--json` prints exactly `cover-preflight.json`.

Writes stage, fsync, read back and `os.replace` beside an interior whose
manifest names the same book, and replace only this book's cover files. The PDF
and manifest replacements are not one transaction; the manifest's PDF SHA-256
exposes a mismatched pair.

## Studio

The **Cover** tab ([studio](studio.md#cover-studio)) edits the cover section in the
shared draft and previews a real PDF rendered by Python from the unsaved draft: a
tools panel (layers, photos, text, shapes, fonts, the asset library and
design), a region picker (full wrap, back, spine, front), the canvas with
selectable, draggable text and elements, and an inspector for the selected layer,
region or the photograph's print quality. Draft previews also render layouts that fail
validation (text moved out of its safe area) so they can be corrected; the
response marks them not buildable and builds still refuse them. The **Templates**
tab applies a template to the draft only, and the text editor formats back-cover
text and text boxes ([cover templates and rich text](cover-templates-rich-text.md)).

## Limitations

One trim (8.5 x 11 in), black-ink white or cream paper, two layouts or three
regions with up to 24 elements (no grouping, two-stop gradients, rotation for
rectangles and ellipses only), three type presets plus per-layer overrides, Latin-1 text with the bundled faces, RGB output
without color management, no CMYK, no barcode or ISBN, no hardcover, ebook or
Kindle covers. Imported fonts: static TrueType outlines only (no CFF/OpenType-PS,
variable fonts, collections or WOFF); no kerning or ligatures (ReportLab draws
glyph advances); spine text keeps its preset face. Offsets are relative to the
layout's own position, so changing the preset or text length moves the starting
point. Unused photos and fonts are removed only through the asset library's
trash, never automatically. Rich text has no kerning, hyphenation or justified
alignment; bold or italic needs a bundled or imported face that has it. Templates
are authored for 8.5 x 11 in and scaled; project templates that use imported
fonts work only in projects holding the same font files. Spine text needs 80+ pages
and a spine wide enough for 7 pt type.
The cover demo's photograph is a synthetic stand-in. KDP metadata and the publishing package are described in
[publishing](publishing.md).
