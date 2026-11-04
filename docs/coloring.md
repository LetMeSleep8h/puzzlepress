# Coloring books: schema, artwork and library

This version can represent a coloring book, validate it, and import, inspect and
de-duplicate its artwork, from the CLI or Studio. It cannot yet prepare pixels,
lay out pages, build an interior, make a cover or package a coloring book: those
commands refuse coloring books (`engine_not_buildable`). Plan:
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
      adjustments:                       # optional; recorded, not yet applied
        grayscale: true                  # default
        threshold: null                  # null or 0.05..0.95
        brightness: 0.0                  # -1..1
        contrast: 1.0                    # 0.25..4
        background_cleanup: 0.0          # 0..1
        despeckle: 0                     # 0..5
        line_weight: 0                   # -2..2
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

## CLI

```text
puzzlepress coloring import BOOK FILE... [--no-page] [--json]
puzzlepress coloring list BOOK [--json]
puzzlepress coloring inspect BOOK [ID...] [--file FILE...] [--json]
puzzlepress coloring duplicates BOOK [--json]
puzzlepress coloring remove BOOK ID [--with-pages] [--trash] [--json]
```

Exit codes: 0 done; 1 refused, blocking findings among those inspected, or
duplicates found or not all compared; 2 usage. `inspect --file` checks files
without importing them.

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

## Limitations

Adjustments are stored but not applied. No pages are laid out, so the DPI is
measured against the profile's live area, not a page design. 8.5 x 11 in only. The
similarity heuristic was measured on synthetic drawings only. Studio has no editing
of titles, adjustments or page order yet, and no artwork trash controls (the CLI's
`remove --trash` and the asset library API do this). Inspection of a large library
in Studio costs about 0.1 s per full-size drawing on first view (cached by digest
afterwards).
