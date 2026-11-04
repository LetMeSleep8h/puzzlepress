# Cover templates and rich text

Cover templates are reusable cover designs, and rich text formats back-cover text
and text boxes. Both are cover configuration that Python validates, lays out and
renders. Studio shows Python's previews and never draws a cover itself.

## Templates

A template is a versioned JSON document (`template_version: 1`). Its `design`
holds a version 3 cover design: regions, elements, the type preset, the
legibility treatment, the spine text setting and text styling. It never holds
the book's identity.

| Field | Meaning |
| --- | --- |
| `id` | Lower-case letters, digits and hyphens. It is also the file name of a project template. |
| `name`, `description` | Up to 60 and 300 characters. |
| `category` | `photographic`, `bold`, `dynamic`, `classic`, `minimal`, `technical`, `puzzle`, `editorial` or `custom`. |
| `photo` | `required`, `optional` or `none`. |
| `palette` | Up to 8 `#rrggbb` colours, shown on gallery cards. |
| `provenance` | Where the design came from. Every built-in says it is an original PuzzlePress vector design with no logos and no third-party artwork. |
| `design.elements[]` | Version 3 elements. A photo element takes a `slot` from 1 to 4 instead of an image, and any element can take `requires_slot` so it is drawn only when that slot has a photograph. |
| `fonts` | Imported fonts the design uses, each pinned by path and SHA-256. |

Element coordinates are authored for an 8.5 x 11 in trim and scaled by the trim
ratio. `"width": "spine"` resolves to the spine width computed from the current
interior build. Text in elements may use two kinds of variable:

| Variable | Kind | Value |
| --- | --- | --- |
| `{title}` (the book title), `{subtitle}`, `{author}`, `{imprint}` | binding | Book details |
| `{puzzle_count}`, `{theme_count}`, `{solutions}` | binding | Word-search books only |
| `{artwork_count}` | binding | Coloring books: coloring pages in `coloring.pages` |
| `{page_count}` | live | The built interior's page count |
| `{trim_size}` | live | The built interior's trim, written `8.5 x 11 in` |

**Bindings** come from the book itself and are resolved once, when the template is
applied: the text box then holds ordinary words. A binding without a value removes
its element rather than printing an empty placeholder, so a word-search binding
never prints on a coloring cover. **Live variables** stay in the cover's text as
written; Python's cover layout fills them in from the verified interior it sizes
the spine from, so rebuilding the interior with another page count changes the
printed number with the spine width and makes the old cover out of date. Only
these exact tokens are variables; other text in braces is literal, so existing
covers keep their bytes, and there is no escape for printing `{page_count}`
itself. A binding typed into a text box by hand prints literally; Studio's Checks
tab warns about it (`template_binding_in_text`). Bindings never invent an author,
ISBN, price, rating, testimonial or endorsement.

A file is limited to 256 KB. Control characters are refused, and every value is
checked before a template is listed. A broken project template appears as a
problem in the gallery and is never applied.

### Built-in templates

Eight built-ins ship in the package (`src/puzzlepress/cover/templates/`). Each
one is drawn only from shapes, rules and the bundled type:

1. **Photographic Editorial**: a large front photograph under serif type, with a
   navy back and spine. This is the lead template for the automotive word search,
   and its barcode area stays empty.
2. **Bold Garage**: charcoal with stacked capitals and a yellow rule.
3. **Motorsport Energy**: diagonal speed stripes, with no logos, numbers or
   livery.
4. **Vintage Motoring**: cream paper tones, a double frame and serif display
   type.
5. **Modern Minimal**: white space, one accent rule and sans type.
6. **Technical Blueprint**: a blueprint grid and drafting rules. It shows no
   fabricated specifications.
7. **Classic Puzzle Collection**: top bands and a `{puzzle_count} PUZZLES`
   badge.
8. **Premium Editorial**: a deep colour field with fine rules and an optional
   photograph.

Each built-in is tested at 24, 95, 300 and 550 pages, on white and cream paper,
with and without a photograph or author. Every combination renders with no
layout issues: nothing sits in the barcode area, on the spine fold, or outside
the safe area.

### Applying a template

Applying a template:

- replaces the design: region colours, design elements, the type preset, text
  styling, the legibility treatment and the spine setting;
- keeps the book's title, subtitle, author and imprint, display-text overrides,
  hidden layers, the back-cover text, extra text layers, imported fonts and the
  cover's photographs. Photographs are re-placed in the template's slots in
  order;
- turns a missing required photograph into a grey placeholder frame, reported
  as `template_photo_placeholder`. No other picture is ever substituted;
- never changes the book details, the interior, publishing metadata or any
  declaration.

The result is an ordinary version 3 cover: every element can be edited, moved,
locked or deleted. In Studio, a template is applied only to the unsaved draft,
so Undo or Revert restores the previous cover exactly.

### Project templates

**Save as template** turns the current design into a project template in
`cover-templates/<id>.json` beside `book.yaml`. Saving converts the design as
follows:

- The book's words in text boxes become bindings.
- Photographs become empty numbered slots.
- Display-text overrides, back-cover text, extra layers and every attestation
  stay with the book.

Imported fonts are project assets, so a template that uses one is scoped to
projects holding the same font file (same path and SHA-256). Elsewhere it is
listed as needing that font and is not applied.

Project templates can be renamed, duplicated, exported and deleted. Writes are
atomic and read back to check them. Renaming or deleting needs the identity of
the version you last saw, deleting asks for confirmation, and symbolic links are
refused. Built-in templates cannot be overwritten or deleted, but duplicating
one makes an editable copy. **Import** checks the file completely and adds it as
a project template without applying it.

## Rich text

`cover.back_text` (cover version 2 or 3) and a text box's `rich` field
(version 3) accept a rich text document instead of a plain string:

```yaml
back_text:
  rich: 1
  blocks:
  - type: heading
    runs: [{text: "Sixty puzzles"}]
  - runs:
    - {text: "Grids from the "}
    - {text: "pit lane", italic: true}
    - {text: " to the showroom."}
  - list: bullet
    space_before: 4
    runs: [{text: "Solutions at the back"}]
```

| Level | Fields |
| --- | --- |
| Block | `type` (`paragraph`, `heading`), `align` (`left`, `center`, `right`), `list` (`bullet`, `number`), `line_spacing` (0.8–3.0), `space_before` and `space_after` (0–72 pt), `runs`. |
| Run | `text` (`\n` is an explicit line break), `bold`, `italic`, `underline`, `size` (4–160 pt), `font` (`sans`, `serif`, `serif-display` or an imported font's `id`), `color` (`#rrggbb`). |

A document holds at most 40 blocks of 80 runs each, and back-cover text keeps
its 1,200-character limit. Rich text is not HTML: there is no markup, link,
image or external reference.

Unset values inherit from the holding layer or text box. A field stays a plain
string until formatting is actually used. A document with no formatting renders
byte-identical PDFs to the plain string, and Studio stores it as a string.
Everything else in PuzzlePress (publishing checks, confirmation identities and
asset listings) reads the plain text, which is the block texts joined by line
breaks.

### Layout and faces

Python measures every run with the real font metrics, wraps at spaces and
explicit breaks, and aligns each line. It refuses to draw anything it cannot
draw correctly:

- `text_overflow`: a word is wider than its box.
- `text_box_overflow`: the text is taller than its box. It is never clipped.
- `unsupported_character`: a character has no glyph in its face.
- `font_variant_unavailable`: the formatting asks for a face that does not
  exist. The bundled sans has bold and italic but no bold italic, the serif has
  italic only, and the serif display has neither. An imported font is a single
  face. PuzzlePress never imitates a missing bold or italic.

These are layout issues, so the build refuses until they are fixed. Studio
previews the draft and points to the cause.

Applying a template can change the back-cover text's base face. If that new
face lacks a variant the text uses (for example, bold back text under a serif
template), the template preview reports `font_variant_unavailable` instead of
rendering. Remove that formatting or choose another font, then apply again.

### The Studio editor

The editor formats only the current selection. Bold, italic and underline have
toolbar buttons and the shortcuts Ctrl/⌘+B, I and U. The toolbar also sets font,
size and colour for the selection, and alignment, lists, heading and paragraph
spacing for the selected paragraphs. **Clear formatting** returns those
paragraphs to plain text.

Typing continues the style at the caret. Paste is always plain text. Undo,
deletion across paragraphs, cursor movement and IME composition keep the
document and the selection consistent. Variants the face lacks are disabled and
say why.

## Compatibility

Version 1, 2 and 3 covers without formatting render byte-identically to before.
A cover moves to version 2 only when its back text is formatted, and to version
3 only through explicit conversion or a template. Title, subtitle and author
text still has to match the book details: a template binds them from the book,
and publishing's `cover_text_matches` check compares plain text only, so
formatting never causes a false title mismatch.

## Advisory design checks

Studio's draft checks add two advisory findings that never block a build or
publishing:

- `low_contrast`: text on a solid background has a contrast ratio below 3:1.
- `template_photo_placeholder`: a template frame is waiting for a photograph.

Preflight is unchanged.
