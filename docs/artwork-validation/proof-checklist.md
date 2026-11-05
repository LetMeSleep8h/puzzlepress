# Printed-proof review checklist

For the print-validation proof built by `tests/proof_project.py` (or any coloring
book). Fill it in with the printed copy in hand, in daylight or a daylight lamp,
beside `proof/interior.pdf` on screen at 100 %. Record what you see; "not checked"
is an honest answer. PuzzlePress has not seen this proof: nothing below is filled in
by software.

Proof details: order date ______  received ______  paper (white/cream) ______
printer/marketplace ______  interior.pdf SHA-256 (first 12) ______

## Per page

Use `sources.json` to find each drawing's physical page and source.

| Page | Drawing | Line sharpness | Faint detail survived | Black density (solid, even) | Specks / background tint | Clipped or near-edge detail | Show-through from the back | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |  |

Scale for each cell: good / acceptable / poor / not checked.

What each column means:

- **Line sharpness**: thin lines are crisp, not broken, doubled or jagged.
- **Faint detail survived**: light pencil strokes and fine hatching still print where
  the prepared image shows them (compare with `difference.png` from the review).
- **Black density**: solid areas are evenly black, without banding or mottling.
- **Specks / background tint**: no dust, scan noise or gray paper tone printed.
- **Clipped or near-edge detail**: nothing lost at the art box; parts of the drawing
  close to the margin are still easy to color.
- **Show-through**: hold the page to the light and look at the blank back; note how
  much of the drawing shows (markers will show more).

## Whole book

| Check | Result | Notes |
| --- | --- | --- |
| Margin safety: no line within 0.25 in of any trimmed edge |  |  |
| Page parity: every drawing on a right-hand page, blank back behind it |  |  |
| Page numbers present where expected, absent on blanks and dividers |  |  |
| Binding-side clearance: no drawing disappears into the gutter when the book lies open |  |  |
| Cover alignment: front image and text sit inside the trim, nothing cut |  |  |
| Spine placement: spine color and any text centered on the spine, not wrapping |  |  |
| Back cover: barcode area clear |  |  |
| Overall readability of text pages (title, copyright, sources) |  |  |
| Paper weight acceptable for the intended coloring tools |  |  |

## Compare with PuzzlePress's findings

For every finding in `proof/preflight.json` and every warning in the artwork review
(`review.md`), note whether the printed page confirms it, and note anything you saw
that PuzzlePress did not report.

| Finding or observation | Page | PuzzlePress said | Printed copy shows | Agree? |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

Only results recorded here count as physical-print evidence. Thresholds change only
from such records (docs/coloring.md, Calibration).

## Questions only print answers

Software measured these on screen; only the printed proof can settle them:

1. Do the fine hatching lines of drawings 3, 4 and 6 (patent scans, cleanup 0.6 +
   despeckle 2) print continuous and colorable, as measures version 2 now reports,
   or do they break up as version 1 claimed?
2. Does the lightened rim of strokes after cleanup (paper 213-235 stretched to white)
   print visibly thinner than on screen?
3. Is the speck warning (5 per megapixel) right after cleanup on pages 2, 3, 6, 11
   and 12: does paper grain print as dots?
4. Do the under-300-DPI pages (12, 13, 15, 17 at 208-296 DPI) look soft?
5. Does Doré's dense engraving (excessive ink) print as muddy solid areas?
6. How much does a drawing show through to its blank back on this paper?
7. Does a gray-201 background left on Pollard Willows (#11) print as a tint?

Record answers in the tables above; thresholds change only from such records.
