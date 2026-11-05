# Producing a full-bleed coloring book in Studio

A coloring book whose drawings run to the edge of the page. Every value below comes
from Python; Studio shows it. Rules and sources: [print-interior.md](print-interior.md#full-bleed-coloring-books-interval-9).

1. **Choose a full-bleed profile.** Settings → Print settings → a trim and paper ending
   in "full bleed" (offered to coloring books only). Save. Every page becomes 0.125 in
   wider and 0.25 in taller than the trim; the cover keeps its own bleed and size.
2. **Hide page numbers on artwork pages.** A number cannot print over a drawing that
   fills the page; the build says so (`folio_over_bleed_art`) instead of moving it.
   Pages → Page numbers → leave artwork pages unnumbered.
3. **Fill a page.** Pages → Design a page → "How the drawing sits on the page" →
   "Fill the bleed area". The preview, in the PDF page's own coordinates, shows:
   - the bleed (pink band): printed, then cut away;
   - the trim: the finished page edge;
   - the safe area (dashed): KDP's margins for this page count;
   - the gutter (blue): the binding side, which a filled drawing never enters;
   - the whole drawing, faint where the page crops it, and the bleed hatched.

   Zoom (100-300 %) and the two position sliders choose what shows. Under the preview,
   Python states the drawing's size and DPI and how much of its line work is cut off
   the page, printed only in the bleed, and outside the safe area. "Fit inside the page"
   or "Reset placement" returns to the whole drawing, never cropped.
4. **Check resolution.** Filling enlarges the drawing. Print proof → `kdp_image_resolution`
   names the pixels needed for 300 DPI at that size; supply a larger scan or zoom less.
5. **Build and inspect.** Print proof → Build interior. The page images are the whole
   bleed page. Turn on "Trim line" and "Bleed" to see what is cut; "KDP minimum
   margins" shows the safe area (0.375 in with bleed). `coloring_bleed_art` lists
   trimming effects per page: a review prompt, not a block.
6. **Cover and publishing.** Cover rebuilds for the new profile (same size and
   spine). Publishing → Format says "full bleed (choose Bleed in KDP)"; the KDP
   checklist says "Bleed settings: Bleed (PDF only)".
7. **Produce.** Produce runs the job in its own worker; the release states its print
   profile ("full bleed: in KDP, choose Bleed (PDF only) for the interior").
8. **Proof.** Order a printed proof yourself and check the cut edges against the
   preview: [proof-checklist.md](artwork-validation/proof-checklist.md).

What is not supported: bleed on word-search books, color interiors, art that runs
into the gutter, and borders on filled pages.
