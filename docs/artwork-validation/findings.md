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

## Interval 8: paper-relative measures

The fix recommended in point 1 is in measures version 2 (docs/coloring.md,
"Paper-relative line measures"): line measures read each image relative to its own
local paper level, so cleanup that whitens tinted paper is no longer counted as
fine-line loss, while thinning, erasing or lightening strokes relative to their
paper still is. No threshold changed.

Evidence is **digital and synthetic only**. The 17 approved originals were kept
outside the repository and were not present on this machine in Interval 8;
downloading them again needs the author's go-ahead, so the table above was not
re-measured. On scan-like synthetic pages built to reproduce the bias (ink 70,
scanner blur, grainy paper 158-226, uneven aging) version 1 reported 21-70 % fine
lines kept after cleanup 0.6 and version 2 reports 98-100 %, with real thinning
still 0 %. Expected effect on the real table: drawings 1-6 and 10-12 should no longer
report `thin_lines_lost` or `thin_lines_destroyed` under cleanup alone; drawings 4
and 6 may still report erased light strokes, which the review judged partly true.
To confirm: re-download the files listed in approved.json (SHA-256 pinned), run
`tests/artwork_review.py` on both versions, and compare.

Remaining uncertainty: the paper estimate uses a 20 px window floored at 80 % of the
page's 95th-percentile level, so a tinted area wider than that which is genuinely
part of the drawing (a wash) is read as paper; whether the measures now agree with
printed pages needs the physical proof.

**Physical proof status (2026-11-05):** not ordered, not inspected. Nothing in this
file is print validation. The questions only a printed copy answers are listed in
[proof-checklist.md](proof-checklist.md#questions-only-print-answers).

## Interval 9: revalidation status

The 17 originals were still not on this machine (searched 2026-11-05), and downloading
them again was not authorized in this interval, so they were **not re-measured**: no
real-artwork result for measures version 2 exists yet, and none is claimed. The
procedure is now repeatable and integrity-checked:

```
python tests/artwork_fetch.py docs/artwork-validation/approved.json ORIGINALS
python tests/artwork_review.py ORIGINALS OUT --manifest docs/artwork-validation/approved.json --set background_cleanup=0.6 --set despeckle=2
python tests/artwork_compare.py OUT
```

`artwork_fetch.py` keeps only files whose bytes and SHA-256 match `approved.json`,
never overwrites and refuses a folder inside the repository; `--manifest` refuses to
measure unless the folder holds exactly those files; `artwork_compare.py` prints
Interval 7's recorded measures (`interval7-cleanup-measures.json`) beside the new ones.
To record from the result: false positives (a loss finding where the 100 % view shows
the lines intact), false negatives (lines visibly lost without a finding), and which
need the printed proof. Thresholds stay unchanged unless such records justify it.

## Interval 10: the 17 originals re-measured

All 17 approved originals were downloaded again on 2026-11-05 with
`tests/artwork_fetch.py` (Wikimedia rate-limited once; the script waited 600 s), each
kept only after its bytes and SHA-256 matched `approved.json`, and stored outside the
repository (`../puzzlepress-validation-originals`). Reviewed with
`tests/artwork_review.py --manifest` under defaults, cleanup 0.6 + despeckle 2, and
cleanup + threshold 0.5; compared with `tests/artwork_compare.py`; looked at with
`tests/artwork_contact_sheet.py` and full-resolution crops of the worst regions. The
visual review was made on screen by the coding agent, not by the author, and no
printed page exists: everything here is digital evidence.

Two measure changes came from this review (measures version 3, coloring preflight
ruleset 5; no threshold changed):

1. Fine-line retention tolerates a 1 px rim shift. With version 2, Libbey and Lose
   still reported `thin_lines_lost` (88 %, 86 %) while full-resolution crops showed
   every line intact: single rim pixels flipped across the ink level (cleanup
   stretches by the page's 95th-percentile paper; the measure divides by the local
   paper). Now 98-100 % on every patent scan; thinning one step on the same files
   still reads 0-32 % kept with `thin_lines_destroyed` and `detail_lost`.
2. `dark_edge_band`: the Otis scan keeps the scanner's black frame (69-88 % ink in the
   outermost 1 % of each edge), which prints as bars; no other drawing exceeds 26 %.
   The specks message now names dust, grain or deliberate stippling (Vitis labrusca's
   stippled leaf raised it).

| # | Source | Pixels (effective DPI full page) | Settings | Interval 7 findings | Interval 10 findings | Visual review (screen, 100 %) | Remaining uncertainty | Recommended action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Libbey automobile, US 652,851 (NARA) | 3040 x 4515 (463) | cleanup | fine lines 74 % (lost) | none (fine lines 100 %) | every line intact, paper white | thin pale hatching on paper | proof page; keep cleanup |
| 2 | Lose one-wheel vehicle (NARA) | 2995 x 4494 (461) | cleanup | 70 % (lost), specks | specks 6/MP (fine lines 98 %) | hatching intact; scattered grain dots | whether grain prints | despeckle 3 and compare; proof |
| 3 | Knight bag machine (NARA) | 2976 x 4543 (466) | cleanup | 58 % (**destroyed**) | faint lines, specks 20/MP (99 %) | structure intact, fine vertical hatch lighter | how pale hatch prints | raise contrast slightly; proof page 3 |
| 4 | Deere plow (NARA) | 4704 x 5935 (649) | cleanup | 50 % (**destroyed**), light strokes 44 % | faint lines (99 %, light strokes 100 %) | outlines intact, shading hatch present; seal stamp kept | pale shading in print | proof; threshold 0.5 erases the gray shadow wash (reported, correct) |
| 5 | Edison lamp (NARA) | 3003 x 4494 (461) | cleanup | 66 % (lost) | none (100 %) | text and filaments intact | none digital | proof |
| 6 | Otis elevator (NARA) | 4000 x 2703 (552) | cleanup | 47 % (**destroyed**) | `dark_edge_band`, specks 9/MP (100 %) | lines intact; black scan frame on all edges | none for lines; frame is real | crop the scan frame before import |
| 7 | Steering gear crop | 462 x 549 (64) | any | resolution too low | resolution too low (blocking) | tiny | none | replace with a larger scan |
| 8 | Van Gogh, Enclosed Wheatfield | 7686 x 5851 | any | refused: 45 MP over 40 MP | refused: same bound | not reviewed | none | export a smaller copy (a new file needing its own approval) |
| 9 | Van Gogh, Cypresses | 3955 x 2898 (546) | cleanup | 3 % (destroyed), "blank" wording | `prepared_blank` (blocking), faint lines | pale chalk on dark paper: almost nothing reaches ink | none: correctly blocked | not suitable as coloring line art |
| 10 | Van Gogh, Montmajour | 3864 x 3120 (533) | cleanup | 74 % (lost) | faint lines (100 %) | reed-pen marks intact | how dense marks print | proof |
| 11 | Van Gogh, Pollard Willows | 1956 x 1461 (270) | cleanup | 0.6 % (destroyed), tint | background tint (201), faint lines, specks 70/MP, low resolution | lines intact; gray sky kept | tint and grain in print | stronger cleanup or a better scan |
| 12 | Meyer ornament 1900 | 1650 x 2612 (268) | cleanup | 73 % (lost), strokes broken | specks 8/MP, low resolution (100 %) | intact drawn frame and ornaments | grain dots | proof; larger scan for 300 DPI |
| 13 | Meyer "Kreis" | 1317 x 2026 (208) | cleanup | 89 % (lost), strokes broken | low resolution only (100 %) | intact | none for lines | larger scan for 300 DPI |
| 14 | Juncus gerardii (Britton & Brown) | 2230 x 2788 (308) | cleanup | none | none | clean | none | ready as line art |
| 15 | Vitis labrusca (Britton & Brown) | 1523 x 2000 (210) | cleanup | specks, low resolution | specks 44/MP (stippling), low resolution | stippled leaf is deliberate | none: wording now says so | do not despeckle; larger scan |
| 16 | Doré, Don Quixote | 3090 x 3878 (426) | defaults | excessive ink; despeckle refused | excessive ink (blocking); despeckle refused | tonal engraving, not line art | none | not suitable as coloring art |
| 17 | Tenniel, Alice | 2143 x 1760 (296) | cleanup | heavy ink | heavy ink, specks 6/MP, low resolution (296) | dense hatching, intact | colorable areas small | proof; author's judgement |

False positives found and removed: the line-loss findings on 1-6 and 10-13 under
cleanup (Interval 7) and on 1-2 (Interval 8). False positives remaining: the specks
warning on stippled art (now worded neutrally, not removed). False negatives found:
the Otis scan frame (now `dark_edge_band`). Not verifiable digitally: how pale hatch
and gray grain print, show-through, and whether dense hatching is enjoyable to color.
Physical proof: not started ([proof-status.md](proof-status.md)).
