# Coloring books: schema, artwork, library and line-art preparation

This version can represent a coloring book, validate it, import, inspect and
de-duplicate its artwork, and prepare line art for black-ink printing (preview,
measure and save settings), from the CLI or Studio. It cannot yet lay out pages,
build an interior, make a cover or package a coloring book: those commands refuse
coloring books (`engine_not_buildable`). Plan:
[multi-engine-plan.md](multi-engine-plan.md).

## Source

A coloring book is a schema-v1 `book.yaml` with a `coloring` section instead of
`word_search`. The two together fail `engine_conflict`. The engine kind is derived,
never written: `inspect` shows `Engine: coloring (Coloring book)`.

```yaml
schema_version: 1
book: {id: woodland-coloring, title: Woodland Coloring, language: en}
build: {seed: 1}
coloring:
  version: 1
  artwork:
    - id: fox-in-the-ferns
      path: coloring-assets/fox-in-the-ferns-0dfcb86a26ec.png
      sha256: 0dfcb86a26ece8601d11ec6894c84b3f3edcacdd74ad04011dafa092eacbe51e
      title: Fox in the Ferns            # optional, one line, <=200
      adjustments:                       # optional; see Line-art preparation
        grayscale: true                  # luma; false: darkest channel
        threshold: null                  # null or 0.05..0.95
        brightness: 0.0                  # -1..1
        contrast: 1.0                    # 0.25..4
        background_cleanup: 0.0          # 0..1
        despeckle: 0                     # 0..5
        line_weight: 0                   # -2..2
        invert: true                     # optional; written only when true
  pages:                                 # publication order
    - {artwork: fox-in-the-ferns}
  layout:
    blank_reverse: true                  # default: single-sided, blank backs
    border: none                         # none | thin | double
```

| Rule | Code |
| --- | --- |
| `version` must be 1 | `unsupported_version` |
| Artwork IDs: lowercase letters/digits and hyphens, <=64, unique | `id`, `duplicate_id` |
| `path` is `coloring-assets/<stem>-<12 hex>.png\|jpg`: no other folder, no `..`, no backslash | `path` |
| `sha256` is 64 lowercase hex digits and starts with the name's 12 hex | `sha256`, `sha256_mismatch` |
| Pages name existing artwork; an artwork may be on several pages (reported as a duplicate) | `unknown_artwork` |
| At most 300 artwork and 300 pages (provisional: no coloring interior is measured yet) | `count` |
| No `composition` yet, so no `cover`, `interior` or `publishing` either | `not_available_for_engine`, `requires_composition` |

Defaults are normalized, so omitted and explicit values hash equally. The section
is part of build identity (envelope `coloring_version: 1`); artwork enters by its
pinned SHA-256, never by reading files. Word-search projects serialize exactly as
before and keep their identities.

## Artwork requirements

- PNG (preferred) or JPEG, detected by content, not by extension. At most 64 MB
  and 80 megapixels. 8-bit modes only (1, L, LA, P, RGB, RGBA, CMYK).
- SVG is refused (`svg_not_supported`): vector files can carry scripts and remote
  references, and there is no safe SVG renderer yet. Export a PNG instead.
- Full-page art needs at least 2175 x 2925 px: 300 DPI over 7.25 x 9.75 in, the
  live area of the 8.5 x 11 in profile. That is the largest area art can print in,
  so the measured DPI is the lowest the drawing can have in a book.
- Black lines on white. Color, gray paper and transparency are reported, not
  converted.

## Import and storage

Originals are copied byte-for-byte into the project's `coloring-assets/`
under `<stem>-<sha12>.<ext>`. The stem is an ASCII slug of the file name (accents
folded, anything else a hyphen; `artwork` when nothing is left); the title keeps the
original Unicode name. Directory parts of a name are ignored. Identical bytes are
stored once, under any name. A different file already holding the target name is
refused (`asset_collision`), never replaced.

A batch is all-or-nothing. Every file is decoded and inspected first, and one
failure refuses the batch with every failing file listed. Then files are staged,
fsynced, read back and linked into place (never over an existing file), and
`book.yaml` is replaced once, revision-checked (`source_changed` if it changed
meanwhile). If that write fails, files the batch created are removed. Re-importing
bytes the library already holds adds nothing. `import` and `remove` rewrite
`book.yaml` canonically: comments and formatting are not preserved.

Every read re-checks that `coloring-assets/` is a real directory directly inside the
resolved project (`asset_unsafe` otherwise) and that the bytes still match the
pinned digest (`artwork_changed`, `artwork_missing`). One project never reads another
project's files.

## Inspection

Facts: SHA-256, format, bytes, color mode, stored and upright pixels (EXIF
orientation), aspect ratio, alpha channel, transparent pixels, DPI metadata
(recorded, never trusted), effective DPI and printed size fitted whole inside the
live area, share of the area filled, ink coverage, background level, color, and a
64-bit difference hash. Measures use a box-reduced copy (at most 1,024 px) and are
rounded, so reports are deterministic for a given Pillow version.

| Finding | Severity | When |
| --- | --- | --- |
| `artwork_resolution_too_low` | blocking | under 150 DPI |
| `artwork_empty` | blocking | under 0.1 % ink |
| `artwork_low_resolution` | warning | 150 to 300 DPI (KDP asks for 300) |
| `artwork_gray_background` | warning | median level under 230 |
| `artwork_transparency` | warning | any transparent pixel (prints as paper) |
| `artwork_in_color` | warning | over 1 % of pixels colored |
| `artwork_cmyk` | warning | CMYK file |
| `artwork_shape_mismatch` | warning | fills under 60 % of the live area |
| `artwork_touches_edge` | warning | over 2 % ink in a 1 % edge strip |

Only 300 DPI is a KDP value; the other thresholds are PuzzlePress conventions.
Findings never stop an import. Unreadable or unsupported files are failures, not
findings.

## Duplicates

Confirmed duplicates are facts: entries pinning the same SHA-256 (`same_file`) and
artwork on several pages (`repeated_pages`). Possible duplicates are a heuristic:
two different files within 10 of 64 hash bits and 6.5 gray levels on a 16 x 16 map.
Measured on synthetic drawings: copies and JPEG re-encodes measured at most 4 bits
and 4.97 levels, and 1,770 pairs of different drawings at least 12 bits and 7.56
levels. Real scans may behave differently. Unreadable artwork is listed under
`not_compared`, and the report is then incomplete. Ordering is stable. Nothing is
removed or replaced.

## Removal and trash

Removing an artwork entry changes `book.yaml` only. It refuses while pages show the
artwork (`artwork_in_use`) unless their removal is asked for too. The original
stays in `coloring-assets/`. The asset library lists artwork with its uses and
moves a file to `coloring-assets/.trash/` only when nothing in the saved source
(or Studio's draft) references it; it can be restored, and purging is a separate
step.

## Line-art preparation

`coloring.prepare` decodes the verified original in memory (EXIF orientation,
transparency composited onto white) and applies the settings in a fixed order:

1. gray: luma, or each pixel's darkest channel (`grayscale: false`; keeps light
   colored lines, such as yellow, dark). The result is always grayscale.
2. invert (white-on-black artwork);
3. brightness and contrast, one lookup table around mid-gray;
4. background cleanup: the paper level (95th percentile) is stretched to white,
   then levels within `cleanup x 64` of white become white;
5. despeckle: ink marks of at most 4/9/16/36/64 px (levels 1-5) with no other ink
   within 6 px are removed, so pieces of faint or dashed lines stay. Deliberate
   stippling with dots further apart than 6 px is removed too (keep it at 0 then);
6. threshold (optional): black at or below `threshold x 255`, white above; without
   it, anti-aliased gray edges are kept;
7. line weight: a 3 or 5 px minimum filter thickens, a maximum filter thins.

Defaults reproduce the original's gray levels exactly. Nothing is written: the
original is never touched and prepared pixels are derived in memory. A preparation
is named by `pp1-prepared-sha256-` over the source digest, the normalized
settings, `PREPARATION_VERSION` (1) and the Pillow version, so a changed file,
setting or algorithm is a different key. Work is bounded: 40 MP to prepare
(`too_large_to_prepare`) and 3 M ink pixels per region scan. Over the scan bound,
stroke and speck measures are listed as `not_measured` and despeckling refuses
(`too_much_ink_to_despeckle`); nothing falls back to other settings.

Measures compare the result with the unadjusted original (steps 1-2 only). Ink is
gray at or below 128; regions are 8-connected (run-length labeling with union-find,
checked against a pixel flood fill in the tests).

| Finding | Severity | When |
| --- | --- | --- |
| `prepared_blank` | blocking | under 0.1 % ink after preparation (a hint when luma hides colored lines) |
| `thin_lines_destroyed`, `thin_lines_lost` | blocking, warning | under 60 %, 90 % of lines at most 2 px wide kept (what a 3 x 3 opening removes) |
| `excessive_ink`, `heavy_ink` | blocking, warning | over 60 %, 35 % ink (an Invert hint when off) |
| `detail_lost` | warning | under 60 % of the original line work kept |
| `strokes_broken` | warning | more than 1.25 x + 3 strokes, counted on ink both images share |
| `background_tint` | warning | median non-ink level under 240 |
| `specks_remaining` | warning | over 5 isolated marks per megapixel |
| `prepared_touches_edge` | warning | ink reaches an image edge the original did not |
| `large_change` | warning | mean change over 40 levels: a prompt to compare, not a defect |

All thresholds are PuzzlePress conventions, not KDP values or print-quality
guarantees. Most findings report measured damage. `large_change` is different: it
only asks for a visual comparison.

### Calibration

Measured on synthetic 2175 x 2925 fixtures in `tests/coloring_helpers.py` (fine 1, 2,
3 and 6 px lines, circles, zigzag glyphs and a crosshatch; a soft gray pencil
sketch; a dense mandala; a noisy scan on gray paper with specks; white-on-black;
transparent; yellow lines), each under 15 settings:

- Fine-line retention was either at least 0.99 (defaults, threshold 0.5,
  thickening, cleanup, despeckle) or at most 0.05 (thinning, a 0.35 threshold on
  pencil). The 0.90 and 0.60 limits sit inside that gap; no fixture produced a value
  between them.
- Line work kept: thinning 9 px strokes by one step kept 74 % (no finding), by two
  48 %; the dense pattern thinned once kept 58 %.
- Ink: clean art 3.5-4.1 %, the dense pattern 21 %, thickened twice 37 %; inverted
  pages 78-99 %.
- Isolated marks: clean fixtures 0-1.3 per MP; the noisy scan 43, 14.8 after
  despeckle 3 (which leaves its 13-21 px dots, visibly dusty in review) and 0 after
  despeckle 4. The warning was lowered from 20 to 5 after that review.
- Breaks: thinning the dense pattern twice split 1 region into 22,717.
- Paper: the noisy scan 224 (tint), 255 after cleanup 0.6; pencil 246.

Timing here (Windows, Python 3.13): 0.6-2.5 s for a full page, up to 3 s for the
dense pattern; mostly-ink pages stop at the scan bound in under 1 s.

![Original, prepared and difference for seven cases](images/coloring/preparation-samples.png)

## CLI

```text
puzzlepress coloring import BOOK FILE... [--no-page] [--json]
puzzlepress coloring list BOOK [--json]
puzzlepress coloring inspect BOOK [ID...] [--file FILE...] [--json]
puzzlepress coloring duplicates BOOK [--json]
puzzlepress coloring remove BOOK ID [--with-pages] [--trash] [--json]
puzzlepress coloring prepare BOOK ID [--set KEY=VALUE...] [--reset] [--output DIR] [--json]
puzzlepress coloring adjust BOOK ID (--set KEY=VALUE... | --reset) [--json]
```

Exit codes: 0 done; 1 refused, blocking findings among those inspected or
prepared, or duplicates found or not all compared; 2 usage. `inspect --file` checks
files without importing them. `prepare` previews the saved settings, or those with
`--set` overrides, and saves nothing. With `--output` it writes
`<ID>-original.png`, `-prepared.png` (full resolution) and `-difference.png` to a
folder outside the book. `adjust` saves settings revision-checked; `--reset`
restores the defaults.

## Studio

A coloring book opens with Overview and Artwork only; no word-search section is
shown. Artwork imports several files at once (one upload each, sent as raw bytes
with the saved revision), shows a Python thumbnail, the facts and findings above,
the pages using each drawing, duplicates, and files no artwork uses. Removing asks
whether to remove the drawing's pages too. API:

| Endpoint | Result |
| --- | --- |
| `GET /api/projects/{key}/coloring` | Saved revision and library report |
| `POST /api/projects/{key}/coloring/artwork?name=&revision=` | Raw PNG/JPEG body (SVG and unlabeled bodies reach Python to be explained); imports and saves |
| `POST /api/projects/{key}/coloring/remove` | `{artwork, revision, with_pages}` |
| `GET /api/projects/{key}/coloring/thumbnail?artwork=` | Grayscale PNG, 360 px |
| `POST /api/projects/{key}/coloring/prepare` | `{artwork, adjustments?}`: saved or given settings; measures, findings and image URLs (422 `invalid_adjustments` with issues) |
| `GET /api/projects/{key}/coloring/prepared/{key}/{kind}` | `original`, `prepared` or `difference` PNG (at most 1200 px) from a bounded in-memory cache of this project; 404 `preview_expired` |
| `POST /api/projects/{key}/coloring/adjustments` | `{artwork, revision, adjustments}`; `null` restores the defaults; 409 `source_changed` |

Each artwork row's Prepare line art panel has the settings, the original, prepared
and difference previews (before/after or one at a time), the findings and
measurements, and Save, Reset to defaults and Revert to saved. Previews are
debounced and numbered; only the latest answer is shown, so the preview always
matches the settings on screen. One preparation runs at a time; others wait up to
30 s.

## Limitations

No pages are laid out, so the DPI is measured against the profile's live area,
not a page design, and no build reads the prepared pixels yet. 8.5 x 11 in only.
The similarity heuristic and every preparation threshold were measured on synthetic
drawings only; real scans need review. The difference preview colors changes of
ink (level 128 or darker) only, so a faint gray stroke that fades further is not
shown. Prepared images exist only in memory (Studio cache) or where `prepare
--output` writes them; nothing is cached on disk. Studio has no editing of titles
or page order yet, and no artwork trash controls (the CLI's `remove --trash` and
the asset library API do this). Inspection costs about 0.1 s and preparation 0.6-3 s
per full-size drawing.
