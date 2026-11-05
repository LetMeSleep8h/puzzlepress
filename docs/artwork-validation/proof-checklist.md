# Printed-proof review checklist

For the print-validation proof built by `tests/proof_project.py` (or any coloring
book). Fill it in with the printed copy in hand, in daylight or a daylight lamp,
beside `proof/interior.pdf` on screen at 100 %. Record what you see; "not checked"
is an honest answer. PuzzlePress has not seen this proof: nothing below is filled in
by software.

Proof details: order date ______  received ______  paper (white/cream) ______
printer/marketplace ______  interior.pdf SHA-256 (first 12) ______

## Printing and inspection guide (Interval 9)

Status 2026-11-05: the 41-page NOT FOR SALE proof (`tests/proof_project.py`) has not
been ordered or inspected; nothing here is filled in. To print it, upload its
`interior.pdf` and `cover.pdf` to a KDP draft yourself and order a printed proof (KDP
charges for it; PuzzlePress never orders). With the copy in hand, in daylight, beside
the PDF at 100 %:

- **Faint lines:** pencil-weight and 1 px strokes (pages for drawings 4, 5, 9): continuous,
  or broken into dots? Compare with the difference images.
- **Tinted backgrounds:** pages for drawings 1-6 and 10-12 after cleanup: is any gray
  paper tone or grain printed (11 kept gray 201)?
- **Dense engraving detail:** Doré (16) and Tenniel (17): do hatched areas fill in or stay
  open enough to color?
- **Border clipping:** thin-bordered pages: is the border whole and evenly inside the
  trim on every page, rectos and versos?
- **Margins and gutter:** nothing within 0.25 in of the cut edges; open the book flat:
  does any drawing disappear into the binding?
- **Reverse pages:** every drawing on a right-hand page with a blank back; how much
  shows through the back when held to the light?
- **Paper appearance:** white or cream as ordered; do markers bleed through?
- **Full bleed (if a bleed proof is ordered):** the cut edge runs where Print proof's
  Trim line shows it (within KDP's tolerance), no white sliver at the outside, top or
  bottom; the inside margin stays clear.

Record answers below. Until then every conclusion in findings.md is digital evidence.

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
