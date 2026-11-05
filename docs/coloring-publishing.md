# Creating and Publishing a Coloring Book with PuzzlePress

This guide takes one coloring book from an empty folder to a package you upload to
Amazon KDP yourself. PuzzlePress never contacts, logs in to or submits anything to
Amazon. A ready package means the checks PuzzlePress models passed and you made the
declarations only you can make; KDP reviews the book and decides.

Every step works from the CLI and from Studio (`puzzlepress-studio --books DIR`).
Reference: [coloring.md](coloring.md) (artwork, preparation, interior, preflight),
[cover.md](cover.md), [publishing.md](publishing.md#coloring-books),
[production-run.md](production-run.md#coloring-books).

## 1. New project

In Studio, **New book** (Library or the top bar) asks for the type, then the title,
optional subtitle, author or pen name, language, folder name (empty: named after
the title), subject, collection, paper (white, cream, or decide later; trim is
8.5 x 11 in) and a starting point (Simple, or with instructions and a Notes page).
Python creates the folder; a name that exists, contains path characters or is
reserved is refused beside its field with your answers kept. From the CLI:

```text
puzzlepress book new books/woodland-coloring --type coloring --title "Woodland Coloring"
```

Either way the folder holds a `book.yaml` like this (the seed is derived from the
folder name; `catalog` and `print` only when you set them):

```yaml
schema_version: 1
book: {id: woodland-coloring, title: Woodland Coloring, author: A. Artist, language: en}
build: {seed: 160829203453012}
output: {directory: ../../build/woodland-coloring}
coloring: {version: 1}
composition: {front_matter: [{kind: title_page}], artwork: {start: recto}, ...}
catalog: {subject: Nature}
print: {profile: paperback-8.5x11-cream}
```

A new coloring book has no drawings, so it cannot pass the print and publishing
checks until you add them; nothing is filled in for you. Creation is atomic: the
folder is reserved, `book.yaml` is staged and verified, and a failure removes only
what it wrote. If a creation is interrupted, creating the same name again clears
the half-made folder (only when it holds nothing but PuzzlePress's own staging
files). Keep the output directory outside the book folder; PuzzlePress refuses to
write inside it.

**Settings** holds the book details (title, subtitle, author, imprint, language,
your own description), the catalog (subject, collection; Library only, not a KDP
series) and the paper. The paper is part of the build identity: changing it makes
the interior and cover out of date, and builds then use it (a different `--profile`
is refused as `profile_conflict`).

## 2. Artwork import

```text
puzzlepress coloring import BOOK drawings/*.png
```

or **Artwork > Import** in Studio. PNG (preferred) or JPEG, black lines on white,
at least 2175 x 2925 px for a full page at 300 DPI. Originals are copied
byte-for-byte into `coloring-assets/` under a content-addressed name and are never
written again; a batch is all-or-nothing. Each file is inspected (pixels, DPI at
the art box, color, gray paper, transparency, edges) and compared with the others
for duplicates. Import adds each drawing to the page list.

## 3. Preparation

Each drawing keeps its own preparation settings (gray conversion, invert,
brightness, contrast, background cleanup, despeckle, threshold, line weight).
Preparation is configuration: the prepared pixels are derived in memory and the
original is untouched. In Studio, **Artwork > Prepare line art** shows the
original, the prepared page and a difference view (red: ink removed, blue: ink
added, orange: light strokes erased) with measured findings. From the CLI:

```text
puzzlepress coloring prepare BOOK fox --set contrast=1.3 --output previews/
puzzlepress coloring adjust BOOK fox --set contrast=1.3
```

Watch for `faint_strokes_erased`: pencil lines and soft detail lighter than ink
that the settings stop printing. Erasing construction lines may be what you want;
erasing detail is not. Findings are measurements, not judgements.

## 4. Page organization

In Studio, **Pages** lists drawings and section dividers in printing order. Select
a page with **Design** to see it at any zoom with its margins and art box, replace
its drawing, make it smaller and move it (it stays whole, never cropped or
resampled), duplicate it or insert a divider after it. Drag a row or use **Up** and
**Down**; **Add drawing at the end**, **Repeat** (use a drawing
again on purpose, flagged), **Remove** (the file stays in the library), **Add
section divider** (title and optional description). The front matter (title page,
copyright notice you write yourself, instructions), back matter, blank backs,
border, recto start and page numbering are on the same page. **Undo** and **Redo** (Ctrl+Z, Ctrl+Shift+Z) step
through your unsaved edits; **Save changes** writes `book.yaml` atomically and refuses if the
saved file changed meanwhile.

The preview is Python's plan of your draft: physical PDF pages as spreads, right-
and left-hand pages, every blank page PuzzlePress inserted and why (the back of a
coloring page, or to start drawings on a right-hand page), the printed numbers, and
the live area and art box. Blank pages are never authored; they follow from the
layout. The same plan from the CLI: `puzzlepress book plan BOOK`.

![Pages: drawings in printing order beside Python's plan as spreads, automatic blank backs hatched](images/coloring/studio-pages-desktop.png)
![Pages at phone width: the same controls, no horizontal scrolling](images/coloring/studio-pages-mobile.png)

## 5. Interior generation

```text
puzzlepress book build BOOK
puzzlepress book preflight BOOK
```

or **Print proof > Build** in Studio. Each drawing is prepared from its verified
original and embedded losslessly (1-bit or 8-bit gray, Flate), fitted whole into
the art box, never cropped or resampled. The PDF is reopened and every image is
decoded and compared with its prepared pixels. Preflight runs
`puzzlepress-kdp-coloring` v2: page boxes, margins, fonts, parity of coloring
pages and blank backs, image integrity, 300 DPI, line quality. Print proof shows
every built page with overlays, findings grouped as blocking, warnings and manual
review, and **Download interior.pdf**.

## 6. Cover design

The cover is the shared Cover Studio (`cover` section, see [cover.md](cover.md)).
It is sized from the built interior: page count read from `interior.pdf`, paper
from the print profile, spine width = pages x the paper's thickness, bleed, safe
areas and the barcode area from KDP's values. Build the interior first; a changed
page count makes the cover out of date until it is rebuilt.

In Studio, **Cover > Templates** applies a design without touching book details.
Text may use `{title}`, `{subtitle}`, `{author}`, `{imprint}` and `{artwork_count}`
(filled in when the template is applied) and the live `{page_count}` and
`{trim_size}` (filled in by Python every time the cover is laid out, from the
built interior). Import a cover drawing or photograph in **Cover > Photos**; the
cover's own pixels carry no source metadata. Then:

```text
puzzlepress cover build BOOK
puzzlepress cover preflight BOOK
```

![Cover Studio on a coloring book: the back prints "28 pages, 8.5 x 11 in" from the built interior](images/coloring/studio-cover.png)

## 7. Metadata

**Publishing** in Studio, or the `publishing` section of `book.yaml`. Besides the
shared fields (description, keywords, categories, audience, low-content, ISBN,
edition, series), a coloring book declares:

- **Who made the artwork** (`ai_disclosure.interior_artwork`, `cover_artwork`):
  human, AI-assisted (your own drawing refined with AI tools: no KDP disclosure)
  or AI-generated (made by an AI-based tool, even if you edited it substantially:
  disclose in KDP). KDP asks one images question for cover and interior together,
  so `images` must match the more disclosing of the two.
- **On what basis you may publish it** (`content_rights`): own work, commissioned,
  licensed, public domain or AI tool terms, for the interior artwork, the cover
  artwork and the text. Having a file is not a right to publish it.
- **Low-content**: KDP lists coloring books as "not generally low-content". If you
  choose low-content anyway, PuzzlePress enforces what KDP states (no free ISBN, no
  series).

![Publishing: artwork origin for the interior and cover, beside KDP's single images answer](images/coloring/studio-publishing-rights.png)

Nothing is preselected and undecided values block. PuzzlePress never invents an
ISBN, a declaration or a confirmation. List price and markets are set in KDP.

## 8. Preflight

```text
puzzlepress publish validate BOOK      # metadata, declarations, confirmations
puzzlepress publish inspect BOOK       # plus fresh interior and cover preflight
```

Readiness reruns both preflights on the files as they are and never trusts saved
reports. Confirm the three statements (rights, AI disclosure, metadata) in
Studio's Publishing page after reviewing what each covers; a confirmation records
exactly what you reviewed and goes stale when that changes (reordering pages does
not; replacing or retitling a drawing does).

## 9. Production package

```text
puzzlepress book produce BOOK --output release/
```

One verified, all-or-nothing run: interior and preflight, cover and cover
preflight, `artwork-integrity.json`, `artwork-duplicates.json`/`.md`, readiness
and KDP metadata, `publishing-validation.json`/`.md`, `production.json`, and
`publishing/` (the upload package) only when nothing blocks. The run is staged
beside `release/` and swapped in only after every file is read back; a failed run
leaves the previous release untouched. Exit 0 only with no blocking item.

In Studio, **Produce** runs the same thing for the saved book into
`<output.directory>-release`, shows each step, lets you cancel a coloring run between
steps (the previous release stays), and offers the files and the upload package as a
ZIP only after reading every file back against `production.json`.

Only one run may write an output at a time. The lock `.release.produce.lock` beside
it is an operating-system lock that ends with its process, so:

- a second run while one is active is refused, naming the active run's process and
  computer;
- after a crash, the next run reclaims the lock (it reports this on stderr), puts
  back a previous release that the crashed run had moved aside, and removes that
  run's staging folder;
- a lock file it cannot attribute (written by another computer on a shared drive,
  empty, or unreadable, as earlier PuzzlePress versions left them) is never removed:
  the run is refused with the file's path, to delete only once no run is active.


An example from the synthetic test book (`python tests/coloring_production.py
DIR` writes it, with SYNTHETIC declarations made for no real author):

```text
release/
  artwork-duplicates.json   artwork-duplicates.md   artwork-integrity.json
  cover-preflight.json      cover.json              cover.pdf
  interior.json             interior.pdf            preflight.json
  kdp-metadata.json         publishing-readiness.json
  publishing-validation.json  publishing-validation.md  production.json
  publishing/
    cover-preflight.json  cover.pdf  interior-preflight.json  interior.pdf
    kdp-checklist.md  metadata.json  package.json  provenance.json  readiness.json
```

## 10. Manual review and KDP submission

Automated checks cannot judge a drawing or guarantee acceptance. Before you
submit:

1. Read `publishing-validation.md`: no blocking items; decide on every warning.
2. Look at every page at print size (Print proof or the PDF): line weight, faint or
   broken strokes, clipped details, dense dark areas, whether it is good to color.
3. Keep the evidence behind your rights declaration (licences, agreements, AI tool
   terms).
4. Follow `publishing/kdp-checklist.md` in KDP: enter the metadata, answer the AI
   question for text and images from your declaration, upload `interior.pdf` and
   `cover.pdf`, and review every page in KDP's Print Previewer.
5. Order a printed proof: thin and light lines print differently on paper.
6. Submit yourself when satisfied. KDP then reviews the book.

## Real-artwork review

PuzzlePress's thresholds were calibrated on synthetic drawings only; no genuine
coloring artwork was available to this engine (Interval 6 looked again: the book
repository holds automotive cover photographs, not line art, and their licence is
not recorded). [coloring.md](coloring.md#calibration) lists which thresholds are
empirical on synthetic data, which are conservative heuristics and which rest on one
person's on-screen judgement. Until a person has reviewed real artwork, treat every
line-quality result as provisional. The harness makes that review repeatable:

```text
python tests/artwork_review.py REVIEW_INPUTS/ review-out/ [--set contrast=1.2 ...]
python tests/artwork_review.py --synthetic review-out/     # exercise it on synthetic art
```

It reads the folder without changing it and writes, per drawing, full-resolution
original, prepared and difference images and `measures.json` (inspection and
preparation measures, findings and the thresholds used), then a print-size
`print/interior.pdf` with coloring preflight from a scratch book of copies, and
`review.md`. Its source-and-licence, on-screen, printed-proof and missed-or-false
finding columns say "not recorded" until a person fills them in.

1. Choose a set you have the rights to use for testing, covering: detailed
   automotive or mechanical line art, nature or landscape drawings, fine pencil
   drawings, dense patterns, hand-drawn illustration and low-contrast scans. A file
   being on your disk or online is not a licence.
2. Run the harness with default settings, then with the settings you would use.
3. Compare original, prepared and difference images at 100 % zoom: fine and light
   lines, background tint, specks, broken outlines, clipped detail, dark areas, line
   weight. Record what you saw and whether a finding was missed or false.
4. Order one printed proof of `print/interior.pdf` and repeat step 3 on paper.
5. Change a threshold only from those recorded results.

## Measurements

Windows, Python 3.13, synthetic full-size line art (2175 x 2925 px), the same
machine and an otherwise idle system for both columns. Each 150-drawing row builds
and then preflights in one process, as `book produce` and Studio do. (Interval 4
recorded 19.7 s and 92.8 s for the same book on a less loaded day; compare columns,
not days.)

| Book | Step | main (Interval 4 code) | Interval 5 |
| --- | --- | --- | --- |
| 12 drawings, 28 pages, cover and publishing | `book produce` | refused | 24.5 s with the memo disabled, 14.3 s with it; byte-identical output |
| 150 drawings, 302 pages | `book build` | 20.2 s | 20.3 s |
| 150 drawings, 302 pages | first preflight after the build | 122.9 s | 100.6 s |
| 150 drawings, 302 pages | second preflight, same process | 118.4 s | 14.9 s |
| 150 drawings, 302 pages | peak working set (build + both preflights) | 147 MB | 141 MB |
| 150 drawings, 302 pages | `book produce` (no cover or publishing; blocked as expected) | refused | 125.1 s, 120 MB peak |

The first preflight is faster because its expected rebuild reuses the packed pixels
the build just prepared; the second, because every drawing's measures are already
known. Each light-stroke measure is skipped exactly when an original has too few
gray 129-200 pixels to be measured, so line art without them pays nothing for it.

The memo reuses line-quality measures and packed prepared pixels for the same
verified bytes, settings and versions within one process; it skips no check and
writes nothing to disk. A first preflight still measures every drawing.

### Interval 6 (production lock, placement and the memo review)

`python tests/coloring_benchmark.py DIR` (150 synthetic drawings, 302 pages, blank
backs; build, two preflights and `book produce` in one process). Two runs each,
alternating, same Windows machine and day, Python 3.13; main at `b42b5bd`:

| Step | main, run 1 / run 2 | Interval 6, run 1 / run 2 |
| --- | --- | --- |
| `book build` | 20.3 s / 27.9 s | 22.8 s / 20.2 s |
| first preflight after the build | 119.8 s / 111.8 s | 111.4 s / 144.3 s |
| second preflight, same process | 14.9 s / 15.0 s | 15.7 s / 18.1 s |
| `book produce` after both (memo warm) | 21.4 s / 22.8 s | 24.6 s / 22.9 s |
| peak working set (run 2) | 174.0 MB | 173.8 MB |

The run-to-run spread on one code base (up to 33 s on a first preflight) is larger
than any difference between the two, so these runs show no measurable change; the
lock adds a file open and an OS lock call per run. The four sample books of
`tests/coloring_samples.py` build byte-identical PDFs with equal build and interior
identities on both.

### Interval 7 (Studio production, the cap, repeated runs)

Same machine, Windows, Python 3.13, `tests/coloring_benchmark.py`:

| Workload | Measure | Result |
| --- | --- | --- |
| 300 drawings (the cap), 602 pages, fresh process | `book build` / first preflight / second preflight / `book produce` | 38.3 s / 193.1 s / 27.8 s / 40.5 s |
| 300 drawings | interior.pdf size; peak working set | 8.6 MB; 182 MB |
| 300 drawings | readiness | blocked, as it must be: 602 pages exceed KDP's 550-page cream maximum for 8.5 x 11 with blank backs (with two front-matter pages, 274 drawings is the most that fits) |
| 150 drawings, Studio `--studio`, two runs | first Studio run (fresh process) | 152-156 s, release verified |
| 150 drawings, Studio | second run in the same process | 27.3-27.6 s |
| 150 drawings, Studio | status requests while running (project + produce status) | median 231-249 ms, max 508-779 ms |
| 150 drawings, Studio | cancel requested during interior preflight to stop | 12.5-12.7 s (stops at the next step boundary); previous release still verified |
| 150 drawings, Studio | peak working set across three runs | 157-158 MB |

An earlier 300-drawing run showed a 1.9 GB peak because that process also generated
the 300 synthetic test images; run on the existing book in a fresh process it is
182 MB. Studio stays usable during a run, but each request waits a few hundred
milliseconds while the run holds the Python interpreter. Re-checking the release
on every poll was not the cause (a cache made no measurable difference and was
removed). Cancellation waits for the current step, which for a large book is the
interior preflight (up to about 3 minutes at 300 drawings).

**Unsupported sizes.** More than 300 drawings or 300 page entries is refused by the
schema (unchanged; not raised without measuring). With blank backs and two front-matter pages, more than 274
drawings exceeds KDP's page maximum on 8.5 x 11 (and 8.5 x 8.5); 6 x 9 and 8 x 10
allow up to 776 pages, but the 300 cap applies.

## Known limitations

- One trim (8.5 x 11 in, white or cream paper), no bleed: art prints inside the
  margins. No auto-crop or captions; placement only shrinks and moves a drawing
  inside its art box.
- The production lock relies on the operating system's file lock; on a network
  share that does not pass locks between computers, two computers could still
  write one output. A lock written by another computer is therefore never reclaimed
  automatically.
- No graphical illustration editor; preparation is a fixed set of adjustments.
- Line-quality thresholds are synthetic-calibrated conventions; see Real-artwork
  review. Light-stroke detection cannot tell construction lines from detail.
- Coloring PDFs are byte-reproducible only with the same zlib and Pillow.
- KDP's form wording for the AI question, prices and markets are not modeled.
- Categories are saved preferences, never verified as available.

## Full bleed (Interval 9)

A coloring book on a `-bleed` profile publishes the same way. Readiness and the
package record `interior_bleed: true` in the print configuration; the KDP checklist
says "Bleed settings: Bleed (PDF only)" (KDP trims the top, bottom and outside edges);
Publishing shows "full bleed (choose Bleed in KDP)". The cover's size and spine are
the same as without bleed (trim, page count and paper decide them), but a cover built
for the no-bleed profile reports out of date until rebuilt. See
[full-bleed-walkthrough.md](full-bleed-walkthrough.md).
