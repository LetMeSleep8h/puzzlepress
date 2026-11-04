# Project format and identity

## Schema v1

The minimal example at
[`tests/fixtures/legacy-automotive/book.yaml`](../tests/fixtures/legacy-automotive/book.yaml)
(formerly `books/automotive/book.yaml`) contains three authored items, not generated
puzzles:

```yaml
schema_version: 1
book:
  id: automotive-word-search
  title: Automotive Word Search
  language: en-US
build:
  seed: 2026
content:
  items:
    - ENGINE
    - CLUTCH
    - PISTON
output:
  directory: ../../build/automotive-word-search
```

| Field | Contract |
| --- | --- |
| `schema_version` | Required integer `1`; unsupported versions fail before interpreting version-specific fields. |
| `book.id` | Required stable identifier: lowercase ASCII letters/digits separated by hyphens; Windows device names are rejected. |
| `book.title` | Required nonempty string. |
| `book.language` | Required language tag such as `en` or `en-US`; basic syntax check, not a language registry lookup. |
| `book.subtitle`, `description`, `author`, `imprint` | Optional nonempty strings or null, under `book`. |
| `build.seed` | Required unsigned 64-bit integer (`0` through `18446744073709551615`) or decimal digit string. |
| `content.items` | Ordered nonempty strings; omitted content/items defaults to an empty list. Duplicates and order are preserved. No puzzle-specific rules apply. |
| `output.directory` | Relative path from the resolved YAML file's directory; defaults to `../build/<book.id>`. |
| `word_search` | Optional banks, explicit difficulty profiles, themed puzzle definitions, and quality settings. See [batch schema](batch-quality.md). Omit for legacy projects; null is rejected. |
| `coloring` | Optional coloring book (version 1): artwork library pinned by SHA-256, page order, adjustment settings, layout. Not with `word_search` (`engine_conflict`) or `composition` yet. Part of build identity. See [coloring books](coloring.md). |
| `composition` | Optional book composition: front/back matter, solution and page-number policy. Requires `word_search`. See [book composition](book-composition.md). |
| `cover` | Optional versioned paperback cover: photograph, crop, type and fill. Requires `composition`. Excluded from build identity. See [cover](cover.md). |
| `publishing` | Optional versioned KDP paperback metadata, AI disclosure and author confirmations. Requires `composition`. Excluded from build identity. See [publishing](publishing.md). |

The content engine is derived from the content section, never authored: a source
without another engine's section (legacy ones included) is a `word_search` book.
`inspect` prints it and Studio's project detail reports it; it is not serialized
and not part of build identity.

A book plan is not part of `book.yaml`: it is a separate versioned document,
`planning.yaml`, beside it, with its own identity and revision. No build reads it.
See [book planning](book-planning.md).

Unknown fields are errors, including nested typos. Text is trimmed at its edges;
internal whitespace, case, and Unicode normalization form are preserved. Omitted
optional book fields normalize to null. Quote numeric-looking titles/items.

Seeds such as `42`, `"42"`, and `" 00042 "` normalize to the same integer.
Booleans, floats, negative values, signs in strings, hex strings, arbitrary text,
and out-of-range values are rejected. No random or clock-derived default exists.

Source is one UTF-8 YAML document (an optional BOM is accepted). Duplicate keys,
aliases, merge keys, and explicit tags are rejected. Date-like values and
`yes`/`no`/`on`/`off` stay strings; lowercase `true`/`false` are booleans. Decimal
integers have no implicit octal/hex conversion. Serialization emits normalized
YAML; comments and source formatting are not preserved.

### Filesystem boundaries

Pass either a source file or a directory containing exactly `book.yaml`. Loading
does not search parent directories, enumerate content, or depend on filesystem
ordering. Input paths may be absolute or relative to the caller's working directory.

Each book directory is authoritative source. Generated artifacts belong in a
separate tree, normally repository-root `build/<book.id>/` as in the example.
Output paths use forward slashes, including on Windows. Absolute paths, drive
paths, backslashes, and invalid path characters are rejected. Relative `..`
components are intentional: they allow output outside the book source tree.

Loading resolves symlinks and rejects output that is inside, equal to, or an
ancestor of the source directory, and an output path that is an existing file.
Only `book build` writes: it creates the output directory, rechecks separation at
write time, replaces only an interior whose manifest names the same book, and
never deletes directories (see [print interior](print-interior.md)). Never place
authoritative data in build directories. `build/`, environments,
test caches, and packaging artifacts are ignored by Git.

## Build identity

`canonical_build_inputs` returns UTF-8 JSON with sorted keys, compact separators,
and an envelope containing identity format version `1`, engine version `0.1.0`,
and the normalized project values, excluding output. SHA-256 produces an identity
formatted as `pp1-sha256-<64 hex characters>`.

- Book metadata, seed, content order, and content values affect identity.
- YAML comments, mapping order, formatting, equivalent seeds, and omitted versus
  explicit defaults do not affect identity.
- Source paths, output location, timestamps, environment variables, and process
  hash randomization are excluded.
- Engine version changes intentionally invalidate identities. Identity-format
  changes require a new identity version; schema changes require explicit dispatch.

Only inline source content is supported. Future external content/assets must be
included by content digest before they influence generation. The current identity
is a fingerprint of declared inputs, not a guarantee of reproducible PDF bytes
or a complete release-environment manifest.

This is a toolchain/build-input identity because it includes the engine version.
Projects with `word_search` include the entire normalized section and an envelope
field `word_search_pipeline_version: 1`. This covers banks, profiles, themes,
selection order, generation limits, similarity/reuse thresholds, and screening
words. Declared unused banks/profiles also affect identity. Sequence order is
preserved, except direction sets use enum order and prohibited search forms are sorted.

A `cover` section is never part of canonical build inputs: it is presentation of
the printed edition, identified by its own cover identity, so editing a crop never
stales the interior. Its photograph lives in the project's `cover-assets/` folder.
Likewise a `publishing` section is never part of canonical build inputs; it has its
own `pp1-publishing-sha256-` identity, so editing keywords never stales a build.
An `interior` style section is excluded too: its resolved design enters the
interior identity only. `composition.puzzles.dividers` is composition and is part
of canonical inputs when present.

Two optional authored files may sit beside `book.yaml`, outside every identity
and read by no build: `reviews.yaml` (editorial reviews) and `proofs.yaml` (proof
records). Each is revision-checked and written atomically; see
[production design](production-design-polish.md). Removed assets go to
`cover-assets/.trash/`, which no import or listing reads. Project cover templates
live in `cover-templates/<id>.json` (at most 100 files of 256 KB each). They are
read only when Studio lists or applies them, never by a build, and are outside
every identity: applying one writes an ordinary `cover` section
([cover templates and rich text](cover-templates-rich-text.md)).

Absent `word_search` is omitted from canonical inputs, preserving all legacy
identities. Likewise, a present `composition` is included in full with envelope
field `composition_version: 1`; an absent one leaves identities unchanged. Present sections require valid nonempty banks, profiles, and puzzles.
Schema v1 is extended additively; older engines reject the new section explicitly
as unknown. The pipeline version covers seed derivation and quality/report
semantics. Future changes must review this version and the engine version.
Ad hoc `puzzle generate` inputs are still outside the project fingerprint.
