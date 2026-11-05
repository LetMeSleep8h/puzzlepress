# Real-artwork validation: findings (Interval 7)

17 approved files (see [approved.json](approved.json) and
[candidates.md](candidates.md)): six 1861-1900 patent drawings scanned by the
National Archives from the original inked sheets, one tiny 1911 patent crop, four
Van Gogh drawings, two Meyer ornament plates, two Britton & Brown botanical drawings
(1913), one Doré engraving and one Tenniel illustration. Downloaded 2026-11-05 and
checked against Wikimedia Commons' SHA-1; originals kept unmodified outside the
repository. Reviewed with `tests/artwork_review.py` under three settings: defaults,
`background_cleanup 0.6 + despeckle 2` ("cleanup"), and cleanup plus `threshold 0.5`.

**Who looked.** The visual observations below were made on screen at 100 % by the
coding agent (Claude), not by the author, and no printed proof has been reviewed.
They are evidence for questions to settle in print, not print validation.

## Results by drawing

Measured values are PuzzlePress's. "Thin kept" is the fine-line retention measure;
"ink still printing" is the share of the original's ink pixels (gray <= 128) still
gray <= 224 after cleanup, computed separately for this review.

| # | Drawing | Paper level | Defaults: findings | Cleanup: thin kept / light strokes kept | Ink still printing (cleanup) | What the eye sees (cleanup, 100 %) | Agreement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Libbey automobile | 226 | gray background, color, specks 10.5/MP | 74 % (lost) / 93 % | 100 % | Every line intact, paper texture gone, edges slightly lighter | **Disagree**: no thin lines lost |
| 2 | Lose one-wheel | 227 | gray background, specks 21.6/MP | 70 % (lost) / 87 % | 99.9 % | Spokes intact | **Disagree** |
| 3 | Knight bag machine | 224 | gray, color, edge, faint lines, specks 70/MP | 58 % (**destroyed**, blocking) / 89 % | 99.3 % | Structure intact; fine vertical hatching lighter and slightly broken | Partly: weakening real, "destroyed" overstated |
| 4 | Deere plow | 217 | gray, color, faint lines | 50 % (**destroyed**) / 44 % (erased) | 99.8 % | Outlines intact; fine shading hatch lighter but present | **Disagree** on destroyed; erased light strokes partly true |
| 5 | Edison lamp | 223 | gray, color, faint lines | 66 % (lost) / 58 % | 99.9 % | Text and filaments intact | **Disagree** |
| 6 | Otis elevator | 213 | gray, color, shape, edge, specks 56/MP | 47 % (**destroyed**) / 49 % (erased) | 99.8 % | Not inspected at 100 % in detail; measures behave as 3-5 | Not judged |
| 7 | Steering gear crop | 255 | **resolution too low (64 DPI)** | n/a | n/a | Tiny crop | Agree: correctly blocked |
| 8 | Van Gogh, Enclosed Wheatfield | n/a | **refused: 45 MP over the 40 MP bound** | n/a | n/a | n/a | Agree with the bound; a smaller copy would be a resampled new file |
| 9 | Van Gogh, Cypresses | 190 | **"empty"** (0.04 % ink), gray, color, faint lines | 3 % / 7 % (erased), prepared blank | 98 % | Faint chalk strokes on dark-gray paper; cleanup breaks them into grain | Blocking right; **"blank" wording wrong** (fixed) |
| 10 | Van Gogh, Montmajour | 222 | gray, color, edge; specks not measured | 74 % (lost) / 100 % | 100 % | Reed-pen marks intact | **Disagree** |
| 11 | Van Gogh, Pollard Willows | 158 | gray, color, low resolution (270 DPI), specks 89/MP | 0.6 % (destroyed) / 65 % | 99.9 % | Lines intact; background still gray (201 after cleanup); textured sky erased | Disagree on destroyed; agree on tint and erased sky |
| 12 | Meyer ornament 1900 | 221 | gray, color, low resolution (268), edge, specks 16/MP | 73 % (lost), strokes broken | 99.9 % | Not inspected in detail | Not judged |
| 13 | Meyer "Kreis" | 235 | low resolution (208), edge, tint | 89 % (lost), strokes broken | 100 % | Not inspected in detail | Not judged |
| 14 | Juncus gerardii | 255 | **none** | 100 % / n/a | n/a | Clean line drawing | Agree |
| 15 | Vitis labrusca | 255 | low resolution (210), specks 54/MP | 100 % / n/a | n/a | Not inspected in detail | Not judged |
| 16 | Doré, Quixote | 148 | **excessive ink**, gray, color, edge; specks and strokes not measured | despeckle refused: 7.9 M ink pixels over the 3 M analysis bound | n/a | Dense tonal engraving, not colorable line art | Agree (excessive ink); refusal message clear |
| 17 | Tenniel, Alice | 255 | heavy ink, low resolution (296), edge, specks 8.8/MP | 100 % / n/a | n/a | Dense hatching | Agree on heavy ink |

Every scan on tinted paper (1-6, 9-12, 16) reports gray background and, at defaults,
specks of 10-140 per megapixel, which is paper grain, not dust. Cleanup 0.6 with
despeckle 2 brings 1, 4, 5 and 10 under the 5/MP warning and leaves 2, 3, 6, 11 and
12 above it.

## What the evidence shows

1. **Fine-line retention is biased by background cleanup on tinted paper.** Cleanup
   stretches the paper (213-235 here) to white, which lightens every mid-tone. Edge
   pixels just darker than the 128 ink level become just lighter, so the measure
   counts them as lost although they still print: across the nine tinted line-art
   scans, 99.3-100 % of the original ink pixels are still darker than the
   paper-relative equivalent of 128, while the measure reports 47-89 %. On white
   paper (synthetic fixtures, 14, 15, 17) there is no stretch and no bias. The same
   applies to "line work kept" and, in part, to "light strokes erased".
   **Not changed in this interval.** Lowering the thresholds would hide real losses on
   white-paper art; the fix belongs in the measure (judge retention relative to the
   paper level after cleanup), and the printed proof is meant to settle whether
   pages 3, 4 and 6 really print acceptably. Recommended for Interval 8 once the proof
   is reviewed.
2. **The speck warning (5/MP) fires on every aged-paper scan at defaults.** It is
   correct that grain prints as a tint at defaults; whether 5/MP is the right bound
   after cleanup needs the printed proof (pages 2, 3, 6, 11, 12).
3. **Faint drawings on tinted paper were called "blank"** (#9, 0.04 % ink on gray-190
   paper). Fixed: inspection now says "No line work darker than mid-gray: the drawing
   is too faint to print as ink on this tinted paper", and preparation says only pale
   gray strokes remain, instead of "blank" or "light colored lines". Blocking severity
   unchanged. Synthetic regression test: `tests/test_coloring_faint.py`.
4. **Bounds behave as documented.** The 40 MP preparation bound refused #8; the 3 M
   ink-pixel analysis bound refused despeckling #16 with an actionable message; #7 was
   blocked at 64 DPI.
5. **Effective resolution findings are accurate.** Book scans at 1,317-2,143 px wide
   (12, 13, 15, 17) and the 1,956 px Van Gogh print at 208-296 DPI full-page and are
   reported; the National Archives scans print at 461-649 DPI.

No threshold was changed. Every threshold remains as classified in
[coloring.md](../coloring.md#calibration).

## Physical proof

`python tests/proof_project.py docs/artwork-validation/approved.json ORIGINALS/ OUT/`
built a 41-page proof (15 drawings in four sections, blank backs, one placed page,
an "Artwork sources" page) and a front-photo cover from drawing 1, both labelled NOT
FOR SALE, with `sources.json` tracing every printed page to its file, SHA-256 and
source. Interior preflight: 4 `coloring_thin_lines` errors (pages for 3, 4, 6, 11:
the biased measure above), 5 `kdp_image_resolution` errors (the under-300-DPI scans,
kept on purpose), 1 `coloring_excessive_ink` (Doré), warnings for line quality, faint
lines and gray paper. Cover preflight: only the usual RGB color-space warning. The
proof is not KDP ready by PuzzlePress's rules, deliberately: it exists to compare
those findings with paper. Nothing has been ordered. Review it with
[proof-checklist.md](proof-checklist.md).
