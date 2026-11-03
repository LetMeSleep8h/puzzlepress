# Production run, previous-book duplicates and photographs

## Puzzle inventories

`puzzle inventory SOURCE` lists a book's puzzles as normalized word sets and grids.
SOURCE is a project (`book.yaml` or its folder; puzzles are regenerated, so the
inventory is authoritative), an interior PDF, a release folder holding
`interior.pdf`, or a saved inventory `.json`. Sources are only read.

PDF import reads text with positions. A page yields a puzzle only when it holds a
rectangular letter grid and a word list and every listed word is found in that
grid; otherwise it is `unverified` with the reason. Image-only (scanned) or
unreadable pages, grids without word lists (usually solutions) and pages without
puzzles are listed. Coverage is:

| Status | Meaning |
| --- | --- |
| `complete` | project source with every puzzle generated, or a PDF whose verified count equals `--expected-puzzles` with nothing unverified or unreadable |
| `unconfirmed` | a PDF with nothing wrong, but no expected count was given |
| `incomplete` | anything unverified, unreadable, or a count mismatch |

Spread layouts (word list facing the grid) are paired. PDFs not made by
PuzzlePress may not extract; they are then reported incomplete, never assumed.

## Comparison

`puzzle compare PROJECT --previous SOURCE [...]` compares every new puzzle with
every previous puzzle and new puzzles pairwise.

- Exact: equal word sets (order and spaces ignored) or equal grids, including
  rotations and mirror images.
- Near: word Jaccard >= `--near-jaccard` (0.6); word overlap (shared / smaller
  set) >= `--near-overlap` (0.8) with >= `--min-shared` (3) shared words; grid
  agreement (same letter in the same cell, best symmetry) >= `--near-grid` (0.5;
  random grids agree near 0.04).

The report (`duplicate-report.json`/`.md` with `--output`) lists puzzles examined,
exact and near duplicates, unverified puzzles and recommended replacements (how
many shared words to swap, with unused words from the same bank). It is `clean`
only when nothing matched and every source's coverage is complete. Exit 0 only
when clean. These measures flag candidates for review; they are not an
originality guarantee.

## Photographs

`cover photos PROJECT --manifest FILE` (or `--photo PATH`, repeatable) checks
only the files named; folders are never scanned. A manifest:

```yaml
photo_manifest_version: 1
base_directory: 'E:\cameras'      # optional; else relative to the manifest
photos:
  - path: '2025\Track Day\IMG_0412.JPG'
    role: cover                   # cover | interior
```

Each file is read, never modified: present, JPEG/PNG within the import limits,
upright pixels, aspect ratio, and the DPI it delivers at cover-fit on the 8.5 x
11 in front panel with bleed (cover) or the interior live area. Below 300 DPI
warns; below 150 is an error. `--import` copies usable files into `cover-assets/`
(content-addressed, never overwriting). Crop with the cover `crop` or photo
elements, and add a [watermark](cover.md#watermark). Nothing is uploaded.

## One-command production

```text
puzzlepress book produce PROJECT --output DIR [--previous SOURCE ...]
    [--expected-puzzles N] [--photos MANIFEST] [threshold flags] [--json]
```

Writes to DIR: `interior.pdf` (puzzles and solutions), `interior.json`,
`preflight.json`, `cover.pdf`/`cover.json`/`cover-preflight.json` (when a cover is
configured), `duplicate-report.json`/`.md`, `photo-check.json` (with `--photos`),
`publishing-validation.json`/`.md` and `production.json` (inputs, toolchain and
every file's SHA-256). DIR must not overlap the project, any `--previous` source or
the photo archive (the manifest's `base_directory`, else the manifest's folder), and is reused only for the same book.

`publishing-validation` separates blocking failures (failed or unevaluated error
rules, duplicates, incomplete coverage, a missing cover, unusable photos, an
answer-key mismatch), warnings, and manual review (content, Print Previewer,
proof, cover appearance, rights and metadata). It names under `verified` only
what passed. The answer key is read back from the built PDF: every puzzle needs
one solution grid with the same letters whose marked letters spell every listed
word and nothing else. Exit 0 only with no blocking failure. Nothing contacts
Amazon.

Determinism: no times are recorded and PDFs are rendered in ReportLab invariant
mode, so the same source, seed and toolchain (engine, ReportLab, Pillow, fonts)
give byte-identical files. A different toolchain version can change PDF bytes;
`production.json` records it.
