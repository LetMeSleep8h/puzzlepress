# KDP publishing package

PuzzlePress turns a current, verified interior and cover, plus validated KDP
metadata and the author's own declarations, into a deterministic package for
**manual** upload in Amazon KDP. Nothing here contacts Amazon, logs in, uploads
or publishes. A ready package means the KDP checks PuzzlePress models passed and
the author confirmed what software cannot verify. Amazon KDP reviews the book
and decides.

```text
book.yaml (book details + publishing section) ──> metadata validation
interior.pdf/json ──> fresh interior preflight (39 rules) ─┐
cover.pdf/json + photo ──> fresh cover preflight (25 rules) ┼──> PublishingReadinessReport
saved preflight reports ──> compared, never trusted ────────┘            │
                                                         ready? ──> PublishingPackage
                                                                         │
                                       <output>/publishing/ (+ publishing.zip) ──> you, in KDP
```

```text
puzzlepress publish validate books/publishing-demo
puzzlepress publish inspect books/publishing-demo
puzzlepress publish package books/publishing-demo --zip
```

Code lives in `puzzlepress.publishing`: `rules` (catalogue, KDP values, sources),
`metadata` (validation, AI disclosure meaning, confirmation states), `review`
(review identities), `isbn`, `text`
(detectors), `identity`, `readiness`, `provenance`, `submission` (metadata record,
checklist) and `package` (assembly, verification, the only writer). The schema is
`publishing_config.py` / `publishing_validation.py`; the CLI is `publish_cli.py`;
Studio's adapter is `studio/publishing.py`.

## Publishing section

An optional, versioned `publishing` section of `book.yaml`, edited through the
same draft, revision check and atomic save as everything else. It requires a
`composition`. Title, subtitle, author, imprint and language are **not** repeated:
they stay in `book`, so the cover, the interior title page and KDP all use the
same values. (`book.description` is an older build-identity field and is not the
KDP description.)

```yaml
publishing:
  version: 2                       # required; 1 is read as legacy, others rejected
  description: |-                  # plain text, line breaks allowed
    Twenty word searches from harbour walls, tide pools and lighthouse paths.
  keywords: [coastal word puzzles, harbour vocabulary]
  categories: [Humor & Entertainment > Puzzles & Games > Word Search]
  contributors: [{role: editor, name: A. Editor}]
  audience: {sexually_explicit: false, reading_age: {minimum: null, maximum: null}}
  low_content: false               # true | false | null (undecided)
  isbn: {mode: kdp_free, value: null}   # undecided | kdp_free | own | none
  edition: 1                       # or null
  series: null                     # or {title, number}
  ai_disclosure: {text: human, images: human, translations: none}
  attestations:                    # review identities you confirmed, or null
    rights: pp1-review-sha256-...
    ai_disclosure: pp1-review-sha256-...
    metadata: pp1-review-sha256-...
    isbn: null
  notes: null
```

| Field | Values | Required for a package |
| --- | --- | --- |
| `description` | 1..10,000 characters of plain text (KDP limit 4,000 is a finding) | yes |
| `keywords` | 0..20 single-line entries (KDP limit 7 is a finding) | no |
| `categories` | 0..10 paths, segments joined by ` > ` (KDP limit 3 is a finding) | no (warning) |
| `contributors` | role `author`, `editor`, `illustrator`, `photographer`, `translator`, `foreword`, `introduction`, `preface`; name | no |
| `audience.sexually_explicit` | `true`, `false`, `null` | answered |
| `audience.reading_age` | `minimum`/`maximum` 0..18 (18 = 18+), both or neither | no |
| `low_content` | `true`, `false`, `null` | decided |
| `isbn` | `mode`; `value` only with `own`, kept exactly as entered | decided |
| `edition` | 1..999 or null | no |
| `series` | `title` (title rules apply), optional `number` | no |
| `ai_disclosure` | per `text`, `images`, `translations`: `human`, `ai_assisted`, `ai_generated`, `unknown`; `translations` also `none` | no `unknown` |
| `attestations` | review identity or null (version 1: booleans) | rights, ai_disclosure, metadata; isbn with an own ISBN, each current |
| `notes` | plain text for the author, shown in the checklist | no |

Schema validation only decides whether values are interpretable; generous
bounds keep a draft savable. Every KDP limit is a **finding** with its source
(below), so eight keywords save and are reported precisely. Unknown fields, YAML
`yes`/`no` booleans and wrong types are schema errors with structured paths.
Text is trimmed at its edges and never otherwise rewritten.

**Identity.** The section is excluded from the build identity (editing keywords
never stales an interior or cover). `pp1-publishing-sha256-...` covers the
section, the book details it references, the schema version and engine version.

## Metadata rules

`publish validate` / `validate_metadata(project)` reads only the project. Each
finding has a stable code, severity (`error` blocks, `warning` asks for review,
`info` notes), scope, basis, official source URL, field path, measured and
required values, the action a person must take and the Studio area that fixes it.

| Code | Severity | Checks |
| --- | --- | --- |
| `publishing_configured` | error | A publishing section exists |
| `title_length` | error | Title + subtitle under 200 characters (KDP wording conflicts: "fewer than 200" and "200 or less"; stricter applies) |
| `title_content` | error | Title, subtitle, series title: no HTML, placeholders (`n/a`, `unknown`...) or punctuation only |
| `title_review` | warning | Sales rank or promotion ("bestselling", "free"), repeated generic words |
| `author_present` | error | A primary author |
| `names_content` | error | Author, contributor, imprint: no HTML or placeholders |
| `contributors_review` | warning | Duplicates; the primary author repeated |
| `imprint_length` | error | At most 100 characters |
| `language_supported` | error | `book.language` is one of KDP's 39 paperback languages |
| `description_present` | error | A description (PuzzlePress rule) |
| `description_length` | error | At most 4,000 characters |
| `description_markup` | error | Plain text: no angle brackets or HTML (PuzzlePress rule; KDP accepts a small HTML subset) |
| `description_prohibited` | error | No URLs, emails, phone numbers, prices, review requests, emoji or invisible characters |
| `description_review` | warning | Possible reviews or testimonials, promotional or time-sensitive wording, keyword stuffing |
| `description_claims` | error | Puzzle counts in the description equal the book's puzzles; no mention of solutions the book omits |
| `keywords_count` | error | At most 7 |
| `keywords_format` | error | No quotation marks, HTML, Amazon program names or exact duplicates |
| `keywords_review` | warning | Spacing/plural variants, subjective or time-sensitive words, generic words, repeats of title, contributors or categories |
| `keywords_present` | info | None entered |
| `categories_count` | error | At most 3 |
| `categories_format` | error | Path segments, no HTML, no duplicates |
| `categories_present` | warning | None saved (you still choose them in KDP) |
| `categories_unverified` | info | Saved preferences are not verified as currently available |
| `audience_explicit` | error | KDP's explicit-content question answered |
| `audience_reading_age` | error | Both ages or neither; none below 18 when explicit |
| `low_content_decided` | error | Classification decided |
| `low_content_review` | warning | Marked low-content although KDP lists puzzle books as not generally low-content |
| `isbn_decided` | error | ISBN option chosen |
| `isbn_valid` | error | Own ISBN: ISBN-13, 978/979, correct check digit |
| `isbn_eligibility` | error | No free ISBN for low-content books; no ISBN only for low-content books |
| `isbn_imprint` | warning | Own ISBN without an imprint; free ISBN lists "Independently published" |
| `series_eligibility` | error | Low-content books cannot have a series |
| `ai_disclosure_complete` | error | Every content kind declared |
| `ai_disclosure_required` | info | What must be disclosed as AI-generated in KDP |
| `attestations` | error | Each required confirmation given for the content as it is now |

Detectors are deterministic patterns that quote what they matched. Unambiguous
patterns are errors; pattern guesses (testimonials, promotion, stuffing) are
warnings for human judgment. Count claims understand digits and number words
("Twenty word searches", "twenty-five puzzles") and ignore dimensions ("14 x 14
grid") and counts of other things ("8 words in each puzzle").

### Keywords and categories

Up to seven keywords; PuzzlePress does not estimate search volume, research
competitors or suggest keywords. KDP's keywords page states no per-keyword length
(only that the text field has a limit), so PuzzlePress checks none; the 200-character
schema bound only keeps a draft interpretable. Ruleset 1 warned above an assumed
50 characters; ruleset 2 removed that unsourced rule. Ruleset 3 adds the cover
display checks below. Categories are stored as the author's
preferences. KDP's category list differs by marketplace and format and changes
over time, so PuzzlePress has no taxonomy and never calls a category available:
the checklist asks you to select it in KDP's selector.

### ISBN

| Mode | Meaning |
| --- | --- |
| `undecided` | Blocks the package. PuzzlePress never invents an ISBN. |
| `kdp_free` | KDP assigns a free ISBN during setup, usable only on KDP; KDP lists the imprint as "Independently published". The number is not known in advance and is recorded as `assigned_by_kdp_during_setup`. |
| `own` | Your ISBN-13 as typed. The format and check digit are verified; registration, ownership and the agency's title, author and imprint record are not. You confirm that separately. |
| `none` | Only for low-content books. |

PuzzlePress never generates, buys, assigns or encodes ISBNs and draws no barcode;
KDP prints its own barcode in the area the cover reserves.

### Low-content classification

KDP describes low-content books as repetitive pages to fill in (journals, log
books, planners) and lists **puzzle books as "not generally low-content"**, with
exceptions. Word-search books therefore usually are not low-content, but this is
the author's decision: `low_content: null` blocks, `true` is allowed with a
warning and the KDP consequences (no free ISBN, no series) are enforced.

## AI disclosure

KDP's Content Guidelines require disclosure of **AI-generated** content (text,
images or translations created by an AI-based tool, even if substantially
edited afterwards) and do not require disclosure of **AI-assisted** content (your
own work edited, refined or checked with AI tools). PuzzlePress maps each
declared origin onto KDP's question:

| Declared | KDP |
| --- | --- |
| `human` | no disclosure required |
| `ai_assisted` | no disclosure required |
| `ai_generated` | disclose |
| `none` (translations) | not applicable |
| `unknown` | undecided: blocks the package |

Nothing is inferred. PuzzlePress's grids are placed by a seeded, deterministic
program and verified independently; that is recorded as a machine fact, but it
does not classify the book's word lists, instructions, description or
photograph, which the author declares. Photographs are never assumed to be
AI-generated or human-made.

## Author confirmations

| Name | Statement |
| --- | --- |
| `rights` | I hold the rights to publish this book's text, word lists and cover photograph. |
| `ai_disclosure` | I reviewed the AI content declaration above, and it is accurate. |
| `metadata` | The title, author and other book details, description, keywords, categories and audience accurately represent this book. |
| `isbn` | My ISBN is registered with this title, author and imprint exactly as entered (own ISBN only). |

A confirmation records exactly what was reviewed. Each stores the **review
identity** of the content its statement covers (`publishing.review`):
`pp1-review-sha256-` over canonical JSON of the review version, book ID,
confirmation name and these values. No timestamps, paths, file names or labels;
the photograph counts by its pinned SHA-256.

| Confirmation | Covers |
| --- | --- |
| `rights` | puzzle titles, themes and word lists (as printed), front and back matter text, the solutions heading, the cover's back text, the photograph; when used, extra cover text and imported fonts (digest, license, source) |
| `ai_disclosure` | the declaration, everything `rights` covers, and the description |
| `metadata` | title, subtitle, author, contributors, series, edition, language, description, keywords, categories, audience |
| `isbn` | ISBN option and number, title, subtitle, author, imprint |

States: **confirmed** (the stored identity equals the current one), **stale**
(it names other content: something covered changed), **unconfirmed** (null) and
**legacy** (a version 1 `true`). Only confirmed counts. Editing covered content
asks for review again; edits outside a confirmation's scope (crop, cover design,
seeds, solution layout, puzzle order, notes, low-content, output directory)
leave it current. Semantics are identity, not time: restoring exactly the
reviewed content makes a stale confirmation apply again. Confirmations are not
part of any review identity, so confirming one never stales another.

Python computes identities and states; Studio and the CLI only display them. To
confirm, Studio records the identity Python reported for the draft; on the
command line, `publish validate` prints each pending statement's current
identity to copy into `book.yaml` after you review it. They are never set by
PuzzlePress and are part of the publishing identity. A digest identifies
content: copyright, authorship, ISBN ownership and the accuracy of an AI
declaration are never claimed as verified.

**Version 1.** Sections written before identity binding (`version: 1`) stored
booleans. They still load and save unchanged, but a `true` never counts: it
reports "Review again" because nothing recorded what was reviewed. Studio offers
**Upgrade publishing section** (the version 2 form Python returns, with every
confirmation null and all metadata kept); by hand, set `version: 2`, set every
confirmation to null, then confirm again. A boolean in a version 2 section is a
schema error (`confirmation_identity`). Bump `REVIEW_VERSION` if what a
confirmation covers ever changes: every stored confirmation then goes stale.

## Readiness

`publish inspect` / `evaluate_readiness(project, source, output)` builds an
immutable, deterministic `PublishingReadinessReport`. It reads `interior.pdf`,
`interior.json`, `cover.pdf` and `cover.json` by fixed name from a
boundary-checked build directory and runs the authoritative interior and cover
preflight **afresh**; the rules are consumed, never reimplemented. Nothing is
written, rebuilt or repaired.

| Verdict | Values |
| --- | --- |
| metadata | `missing`, `valid`, `invalid` |
| disclosure | `complete`, `incomplete` |
| attestations | `complete`, `incomplete` |
| interior | state `missing`/`current`/`stale`/`invalid`; structural `valid`/`invalid`; KDP `ready`/`not_ready` |
| cover | state `no_config`/`missing`/`current`/`stale`/`invalid`; structural; KDP |
| artifacts | `current`, `stale`, `mismatched`, `missing`, `unavailable` |
| package | `ready`, `not_ready` |

Package is ready when no error rule failed **or went unevaluated** in any scope.
Preflight errors keep blocking; preflight warnings stay warnings
(`interior_warnings`, `cover_warnings`); KDP readiness of a structurally invalid
artifact is not evaluated, which blocks. Stale findings say why: "Interior is
out of date: The project source changed after this interior was built" or
"Cover is out of date because the interior paper changed (white -> cream)."

Artifact and consistency rules: `output_directory`, `interior_present`,
`interior_structural`, `interior_kdp`, `interior_warnings`, `cover_present`,
`cover_structural`, `cover_kdp`, `cover_warnings`, `cover_text_matches` (the
built cover prints the current title, subtitle, author and imprint: KDP requires
cover and details to match; a cover version 2 display override must equal the
detail apart from spacing, line breaks and capitals; a cover template keeps the
book's own details, and rich back-cover text is compared and confirmed as its
plain words, so neither causes a mismatch), `cover_text_omitted`
(warning: the cover hides the title or author; KDP's wording requires a match
but does not state that the title must appear, so the author decides; hiding
cover text never changes the book details), `cover_matches_interior` (page count, paper, profile, trim and
ink equal the current interior's), `saved_reports` (warning: a missing,
outdated or forged `preflight.json`/`cover-preflight.json` is named and ignored).

The report records identities (source, publishing, interior recorded/expected,
cover recorded/expected), the print configuration read from the verified files
(trim, ink, paper, interior bleed, page count, cover size, spine width), artifact
and fresh-report digests, counts, sorted findings and every rule's outcome. Its
statement is either "Ready for manual KDP submission: the supported KDP checks
passed and the author's confirmations are complete. Amazon KDP reviews and
decides." or the number of blocking findings and unevaluated checks. It never
says approved, accepted, guaranteed or verified.

## Package

`publish package` assembles only from a ready report, using the exact bytes
readiness inspected, and writes `<output>/publishing/`:

| File | Why |
| --- | --- |
| `interior.pdf` | Upload as the manuscript |
| `cover.pdf` | Upload as the print-ready cover |
| `metadata.json` | KDP field values exactly as authored, with category and ISBN status |
| `kdp-checklist.md` | Manual steps for a person in KDP |
| `readiness.json` | Every verdict, finding and rule with its source |
| `interior-preflight.json` | Fresh interior preflight for these bytes |
| `cover-preflight.json` | Fresh cover preflight for these bytes |
| `provenance.json` | Machine facts and author declarations, kept separate |
| `package.json` | Each file's purpose, SHA-256 and size, and the package identity |

No source project files are included. **Identity**: `pp1-package-sha256-...` over
the package version, book ID, source, publishing, interior and cover identities,
print configuration, the publishing (`puzzlepress-kdp-publishing` v1), interior
and cover ruleset versions and every file's digest. No timestamps or paths.

**Export.** Files are staged in a temporary sibling directory, fsynced, read back
and verified against `package.json`; the previous package (only if this book
wrote it and it holds only package files) is moved aside, the staged directory
renamed into place and the old one removed file by file. A failed export leaves
the previous complete package and no staging directory. Refused: a
`publishing` path that is a file or holds foreign files, another book's package,
output overlapping source, a build directory without this book's interior.
`export_state` reports `none`, `current`, `stale` (the book changed since) or
`damaged` (a file no longer matches `package.json`).

**ZIP.** `--zip` (Studio: "Also write publishing.zip") writes `<output>/publishing.zip`:
entries in name order under `publishing/`, the 1980-01-01 ZIP date, Unix 0644
attributes and stored (uncompressed) entries, so no compressor version can change
bytes. It is reopened and compared before an atomic replace, and never replaces
an archive written for another book.

### Provenance

`provenance.json` separates **machine facts** (engine and pipeline versions;
source, publishing, interior and cover identities; PDF digests; page count;
renderer versions; no raster images in the interior; the photograph's SHA-256,
format and pixel size and that its metadata is not carried into `cover.pdf`)
from **author declarations** (AI disclosure with KDP meaning, each confirmation
with its exact wording, low-content and ISBN choices) and states its limits: a
digest identifies bytes and proves nothing about authorship, copyright or
ownership. No paths, times, EXIF, GPS or XMP.

### Checklist

`kdp-checklist.md` follows KDP's three paperback pages with the book's real
values: language, title, subtitle, series, edition, author, contributors, the
description, publishing rights, the explicit-content answer, reading age,
marketplace, category preferences, the low-content box, keywords in order, the
AI-content answers, the ISBN option, ink and paper, trim, no bleed, cover finish,
the interior and cover files with digests and sizes, Print Previewer review, KDP
warnings, territories and pricing (not modeled), an optional printed proof, and
submitting yourself. Then warnings to review and your confirmations. Every item is
an unchecked box; nothing claims a step was done in KDP.

## CLI

All commands read the project's output directory or `--output DIR`.

- `publish validate PROJECT [--json]`: metadata, disclosure and confirmations only.
  Exit 0 when all three are complete.
- `publish inspect PROJECT [--output DIR] [--json]`: full readiness, print
  configuration and the exported package's state. `--json` prints exactly the
  readiness report. Exit 0 when the package is ready. Read-only.
- `publish package PROJECT [--output DIR] [--zip] [--json]`: write the package when
  ready; otherwise list blocking findings and write nothing. Exit 0 written.

Exit **1** for expected validation or readiness failures, **2** for usage. No
command opens a network connection (tested with sockets disabled).

## Studio

The **Publishing** tab ([studio](studio.md#publishing)) edits the publishing
section in the shared draft with Python findings beside each field, shows the
real front cover, separate verdicts, ordered state lines with links to Print and
Cover, findings with sources, and exports the saved revision.

## Determinism

Identical controlled inputs give byte-identical metadata records, readiness
reports, provenance, checklists, package files, `package.json` and ZIP, tested in
process and in separate processes with different working directories and
`PYTHONHASHSEED`; CI rebuilds on Linux and Windows and compares every file. The
interior and cover inherit their own determinism (ReportLab invariant mode,
pinned fonts, Pillow and ReportLab versions).

## Official sources

Ruleset 2 (Interval 10.1): confirmations bind to reviewed content and the
unsourced 50-character keyword warning is gone. Plain-text descriptions remain a
PuzzlePress rule; KDP's HTML subset is a possible future enhancement, not a blocker.

Read on 2026-10-08 from official KDP help pages; search results were used only to
locate pages. Values live in `publishing.rules` only.

| Topic | Page | Used for |
| --- | --- | --- |
| Title, subtitle, series, author, contributors, keywords, categories | [Metadata Guidelines for Books](https://kdp.amazon.com/en_US/help/topic/G201097560) | title rules, under 200 characters, no HTML or placeholders, three categories |
| Title and edition | [Books Titles & Editions](https://kdp.amazon.com/en_US/help/topic/GW7J4WEKBVU25YEC) | "200 characters or less" (conflict noted), edition numbers |
| Description | [Write a Book Description](https://kdp.amazon.com/en_US/help/topic/G201189630) | 4,000 characters, prohibited content, supported HTML subset |
| Keywords | [Make Your Book More Discoverable with Keywords](https://kdp.amazon.com/en_US/help/topic/G201298500) | seven keywords, what to avoid; no numeric length stated |
| Categories | [KDP Categories](https://kdp.amazon.com/en_US/help/topic/G200652170) | three categories, differ by marketplace/format, change over time |
| Languages | [Book Supported Languages](https://kdp.amazon.com/en_US/help/topic/G200673300) | 39 paperback languages |
| Audience | [Primary Audience and Reading Age](https://kdp.amazon.com/en_US/help/topic/G201506310) | explicit-content question required, reading age bands |
| ISBN and imprint | [What is an ISBN and Imprint?](https://kdp.amazon.com/en_US/help/topic/G201834170) | free ISBN only on KDP, own ISBN must match agency record, 100-character imprint |
| Low-content | [Low-Content Books](https://kdp.amazon.com/en_US/help/topic/GGE5T76TWKA85DJM) | puzzle books "not generally low-content", ISBN and series limits |
| AI content | [Content Guidelines](https://kdp.amazon.com/en_US/help/topic/G200672390) | AI-generated vs AI-assisted, misleading content |
| Cover/details match | [Fix Paperback and Hardcover Formatting Issues](https://kdp.amazon.com/en_US/help/topic/G201834260) | files must match book details |
| Proofs | [Create a Book](https://kdp.amazon.com/en_US/help/topic/G202172740) | ordering a proof is optional |

Classification of what is encoded:

- **KDP requirements**: limits and prohibitions above; ISBN eligibility; the
  explicit-content answer; AI-generated disclosure.
- **KDP recommendations**: keyword advice (variants, subjective words), low-content
  guidance for puzzle books.
- **Ambiguous**: title length wording (stricter applies); contributor roles beyond author, editor,
  illustrator and translator are taken from KDP's form, not its help pages; the
  language-name to tag mapping is PuzzlePress's (for example Provençal as `oc`).
- **PuzzlePress rules**: a description is required, descriptions are plain text,
  category path format, readiness and package semantics.
- **Not modeled**: pricing, royalties, territories, marketplace, cover finish,
  publishing rights options, public-domain content, pre-orders, A+ content,
  Expanded Distribution, KDP's own review.

To update: re-read the pages, change values only in `publishing/rules.py`, bump
`RULESET_VERSION` when a verdict can change, update this table and add boundary
tests (`tests/test_publishing_metadata.py`).

## Coloring books

A coloring book uses the same section, readiness and package, judged by a
separate ruleset, `puzzlepress-kdp-publishing-coloring` v1, so word-search
reports, packages and identities keep their bytes. Shared rules keep their codes.
The official pages behind the coloring additions were re-read on **2026-11-04**:

| Page | What it says (paraphrased) | Used for |
| --- | --- | --- |
| [Content Guidelines](https://kdp.amazon.com/en_US/help/topic/G200672390) | Disclose AI-generated text, images or translations; content created by an AI-based tool is AI-generated "even if you applied substantial edits afterwards"; AI-assisted content (your own work edited, refined or checked with AI tools) need not be disclosed; AI-generated images "include cover and interior images and artwork". Publishers are responsible for rights; copyrighted content freely available on the web is not accepted unless the owner provided it; public-domain content is allowed and KDP may ask for proof. | artwork origins, the images answer, rights warnings |
| [Low-Content Books](https://kdp.amazon.com/en_US/help/topic/GGE5T76TWKA85DJM) | Low-content books are repetitive pages designed to be filled in (journals, log books, planners). Coloring books and puzzle books are listed as "not generally low-content". Low-content books get no free KDP ISBN, no series and no Expanded Distribution. | low-content wording; the existing ISBN and series checks |

The exact options KDP's form shows for its AI question were not found on an
official help page, so PuzzlePress models only what the guidelines state and does
not reproduce the form's choices.

```yaml
publishing:
  ai_disclosure:
    text: human              # captions, dividers, instructions, description
    images: human            # KDP's one answer for cover AND interior images
    translations: none
    interior_artwork: human  # coloring books only: who drew the coloring pages
    cover_artwork: none      # coloring books only; `none` = no artwork on the cover
  content_rights:            # coloring books only; recorded, never verified
    interior_artwork: own_work   # own_work | commissioned | licensed | public_domain
    cover_artwork: none          #   | ai_tool_terms | undecided (cover also: none)
    text: own_work
    notes: null                  # licence names, sources, agreements
```

| Code | Severity | Checks |
| --- | --- | --- |
| `artwork_origin_declared` | error | `interior_artwork` and `cover_artwork` declared (not `unknown`) |
| `artwork_origin_consistent` | error | `images` equals the most disclosing artwork origin (AI-generated over AI-assisted over human); a cover with no artwork contributes nothing |
| `content_rights_declared` | error | `content_rights` present and no kind `undecided` |
| `content_rights_review` | warning | licensed, public domain, commissioned or AI-tool-terms content (keep the evidence); AI-generated artwork declared as your own work; a cover declared without artwork whose origin says otherwise |
| `low_content_decided`, `low_content_review` | error, warning | coloring wording: KDP lists coloring books as not generally low-content |
| `description_claims` | error | counts of drawings, designs, illustrations, pictures or coloring pages equal the coloring pages (or the different drawings); no mention of solutions |

Both artwork fields, and `content_rights`, are refused on word-search books
(`not_applicable_for_engine`). Having a file is never treated as a right to
publish it. The rights confirmation reads "I hold the rights to publish this
book's artwork, cover images and text, on the basis I declared; owning a copy of a
file is not that right." Its review identity covers every printed drawing by its
SHA-256 and caption, divider titles and text, front and back matter, the rights
declaration and the cover's text, fonts and images; reordering pages leaves it
valid, replacing or retitling a drawing makes it stale. Provenance records the
drawing digests and that PuzzlePress prepared the author's files with fixed image
adjustments, never that anyone owns them.

Not modeled for coloring books either: list price, royalty, territories and
marketplaces, which KDP asks for during setup.

## Demos

`books/publishing-demo` is the cover demo's twenty puzzles with 13 x 13 varied
grids and complete metadata. Its interior and cover are KDP ready; AI disclosure is
`unknown` and no confirmation is given, so `publish package` refuses until a
person decides (Studio or `book.yaml`). Tests and CI make synthetic decisions on
temporary copies only. `composition-demo` remains the negative example (no
metadata, 11 pages, no cover).

## Limitations

Paperback only, one trim, black ink, white or cream paper. Plain-text
descriptions (no KDP HTML subset). No category taxonomy, keyword research,
ISBN purchase or assignment, barcode, pricing, royalties or marketing. No KDP
login, browser automation, upload or submission, and no ebook or hardcover.
Confirmations bind to content, not to a person or time, and keep no history.
The production overview, editorial reviews and proof records that sit beside
readiness are described in [production design](production-design-polish.md#publishing-readiness-and-human-proofing);
none of them changes readiness verdicts or the package.
Heuristic detectors can miss or
over-report; warnings exist for that reason. KDP may apply checks PuzzlePress does
not model; its Print Previewer and reviewers decide.
