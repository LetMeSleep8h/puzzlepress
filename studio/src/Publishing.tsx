import { ProductionOverview } from './production';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { PublishingChecklist } from './publishing-checklist';
import { ApiError, request } from './api';
import { DraftToolbar, type Draft } from './draft';
import { FieldErrors, type Source } from './editor-fields';
import type {
  Confirmation,
  ContentOrigin,
  Issue,
  RightsBasis,
  MetadataReport,
  PublishingConfig,
  PublishingDraftCheck,
  PublishingFinding,
  PublishingStatus,
} from './types';
import { ErrorState, Loading, Status } from './ui';

// Publishing workspace. Metadata rules, readiness verdicts, the checklist and the
// package come from Python (`puzzlepress publish` shares the same core). This view
// edits the draft's publishing section and presents findings; it never decides
// readiness, never uploads anything and never claims a KDP outcome.

export function starterPublishing(coloring = false): PublishingConfig {
  const starter: PublishingConfig = {
    version: 2,
    description: null,
    keywords: [],
    categories: [],
    contributors: [],
    audience: { sexually_explicit: null, reading_age: { minimum: null, maximum: null } },
    low_content: null,
    isbn: { mode: 'undecided', value: null },
    edition: null,
    series: null,
    ai_disclosure: { text: 'unknown', images: 'unknown', translations: 'unknown' },
    attestations: { rights: null, ai_disclosure: null, metadata: null, isbn: null },
    notes: null,
  };
  // Coloring books also declare who made the artwork and on what basis it is published.
  // Nothing is preselected: undecided values block until the author chooses.
  if (coloring) {
    starter.ai_disclosure = {
      ...starter.ai_disclosure,
      interior_artwork: 'unknown',
      cover_artwork: 'unknown',
    };
    starter.content_rights = {
      interior_artwork: 'undecided',
      cover_artwork: 'undecided',
      text: 'undecided',
      notes: null,
    };
  }
  return starter;
}

const RIGHTS: [RightsBasis, string, string][] = [
  ['own_work', 'My own work', 'Created by me or the contributors listed above'],
  ['commissioned', 'Commissioned', 'Made for me under an agreement that grants the rights'],
  ['licensed', 'Licensed', 'Used under a licence that allows commercial print sale'],
  ['public_domain', 'Public domain', 'No longer under copyright; KDP may ask for proof'],
  ['ai_tool_terms', 'AI tool terms', "Generated with an AI tool, used under the tool's terms"],
  ['undecided', 'Not decided', 'Blocks the package until you decide'],
];

const ROLES: [string, string][] = [
  ['author', 'Author'],
  ['editor', 'Editor'],
  ['illustrator', 'Illustrator'],
  ['photographer', 'Photographer'],
  ['translator', 'Translator'],
  ['foreword', 'Foreword'],
  ['introduction', 'Introduction'],
  ['preface', 'Preface'],
];
const ORIGINS: [ContentOrigin, string, string][] = [
  ['human', 'Created by people', 'No KDP disclosure required'],
  ['ai_assisted', 'AI-assisted', 'You created it; AI tools edited or refined it. No disclosure'],
  ['ai_generated', 'AI-generated', 'Created by an AI tool, even if edited later. Disclose in KDP'],
  ['unknown', 'Not yet reviewed', 'Blocks the package until you decide'],
];
// Statement, required flag and state come from Python's draft check (Confirmation).
const CONFIRMATION_STATE: Record<Confirmation['state'], [Tone, string]> = {
  confirmed: ['pass', 'Confirmed'],
  stale: ['review', 'Review again'],
  legacy: ['review', 'Review again'],
  unconfirmed: ['neutral', 'Not confirmed'],
};
type Tone = 'pass' | 'review' | 'fail' | 'neutral';
const SEVERITY = {
  error: ['fail', 'Blocking'],
  warning: ['review', 'Review'],
  info: ['neutral', 'Note'],
} as const;
const AREAS: Record<PublishingFinding['area'], string> = {
  publishing: 'Publishing',
  edit: 'Puzzles',
  book: 'Book',
  print: 'Print',
  cover: 'Cover',
};

// Book details (title, subtitle, author, imprint, language) are edited in Settings for
// every book. Coloring books compose in Pages; there is no Puzzles or Book page for them.
// Python's report keeps its own area names; only the link target is chosen here.
function areaRoute(f: Pick<PublishingFinding, 'area' | 'field'>, coloring: boolean): string {
  if (f.field?.startsWith('book.')) return 'settings';
  return coloring && (f.area === 'edit' || f.area === 'book') ? 'pages' : f.area;
}
function areaLabel(f: Pick<PublishingFinding, 'area' | 'field'>, coloring: boolean): string {
  if (f.field?.startsWith('book.')) return 'Settings';
  return coloring && (f.area === 'edit' || f.area === 'book') ? 'Pages' : AREAS[f.area];
}

// A whole number, null when empty, or the text itself so Python reports it.
function whole(value: string): number | null {
  if (value.trim() === '') return null;
  const n = Number(value);
  return Number.isInteger(n) ? n : (value as unknown as number);
}

function matching<T extends { path: string }>(items: T[], path: string) {
  return items.filter((i) => i.path === path || i.path.startsWith(path + '.'));
}

function FieldFindings({ id, findings }: { id: string; findings: PublishingFinding[] }) {
  const own = findings.filter((f) => f.field === id || f.field?.startsWith(id + '.'));
  if (!own.length) return null;
  return (
    <ul className="field-findings" id={`${id}-findings`}>
      {own.map((f, i) => (
        <li key={i}>
          <Status tone={SEVERITY[f.severity][0]}>{SEVERITY[f.severity][1]}</Status> {f.message}
        </li>
      ))}
    </ul>
  );
}

function described(id: string, findings: PublishingFinding[], issues: Issue[], hint?: string) {
  return (
    [
      hint ? `${id}-hint` : '',
      findings.some((f) => f.field === id || f.field?.startsWith(id + '.')) ? `${id}-findings` : '',
      matching(issues, id).length ? `${id}-issues` : '',
    ]
      .filter(Boolean)
      .join(' ') || undefined
  );
}

function Radios<T extends string>({
  legend,
  name,
  value,
  options,
  onChange,
  path,
  issues,
  findings,
}: {
  legend: string;
  name: string;
  value: T;
  options: [T, string, string?][];
  onChange: (value: T) => void;
  path: string;
  issues: Issue[];
  findings: PublishingFinding[];
}) {
  return (
    <fieldset
      className="choice-group"
      id={path}
      aria-describedby={described(path, findings, issues)}
    >
      <legend>{legend}</legend>
      {options.map(([v, text, hint]) => (
        <label key={v}>
          <input
            type="radio"
            name={name}
            value={v}
            checked={value === v}
            onChange={() => onChange(v)}
          />
          <span>
            {text}
            {hint && <small>{hint}</small>}
          </span>
        </label>
      ))}
      <FieldFindings id={path} findings={findings} />
      <FieldErrors id={path} issues={matching(issues, path)} />
    </fieldset>
  );
}

function TextList({
  legend,
  path,
  items,
  limit,
  hint,
  addLabel,
  onChange,
  issues,
  findings,
}: {
  legend: string;
  path: string;
  items: string[];
  limit: number;
  hint: string;
  addLabel: string;
  onChange: (items: string[]) => void;
  issues: Issue[];
  findings: PublishingFinding[];
}) {
  const list = useRef<HTMLOListElement>(null);
  return (
    <fieldset className="choice-group text-list" id={path}>
      <legend>
        {legend}{' '}
        <span className="muted">
          ({items.length} of {limit})
        </span>
      </legend>
      <p className="small muted field-hint" id={`${path}-hint`}>
        {hint}
      </p>
      <ol ref={list}>
        {items.map((item, i) => {
          const id = `${path}.${i}`;
          return (
            <li key={i}>
              <label htmlFor={id} className="visually-hidden">
                {legend} {i + 1}
              </label>
              <input
                id={id}
                value={item}
                aria-invalid={
                  matching(issues, id).length ||
                  findings.some((f) => f.field === id && f.severity === 'error')
                    ? true
                    : undefined
                }
                aria-describedby={described(id, findings, issues)}
                onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))}
              />
              <button
                type="button"
                aria-label={`Remove ${legend.toLowerCase()} ${i + 1}`}
                onClick={() => onChange(items.filter((_, j) => j !== i))}
              >
                Remove
              </button>
              <FieldFindings id={id} findings={findings} />
              <FieldErrors id={id} issues={matching(issues, id)} />
            </li>
          );
        })}
      </ol>
      <button
        type="button"
        onClick={() => {
          onChange([...items, '']);
          requestAnimationFrame(() =>
            list.current?.querySelector<HTMLInputElement>('li:last-child input')?.focus(),
          );
        }}
      >
        {addLabel}
      </button>
      <FieldFindings id={path} findings={findings.filter((f) => f.field === path)} />
    </fieldset>
  );
}

function Metadata({
  d,
  pub,
  update,
  issues,
  findings,
  check,
  replaceSection,
}: {
  d: Draft;
  pub: PublishingConfig;
  update: (next: Partial<PublishingConfig>) => void;
  issues: Issue[];
  findings: PublishingFinding[];
  check: PublishingDraftCheck | undefined;
  replaceSection: (next: PublishingConfig) => void;
}) {
  const book = d.draft.book;
  const coloring = !!d.draft.coloring;
  const base = `/books/${encodeURIComponent(d.key)}`;
  const description = pub.description ?? '';
  const age = pub.audience.reading_age;
  const setAge = (next: Partial<typeof age>) =>
    update({ audience: { ...pub.audience, reading_age: { ...age, ...next } } });
  const ages: [string, string][] = [
    ['', 'Not set'],
    ...Array.from({ length: 18 }, (_, n) => [String(n), String(n)] as [string, string]),
    ['18', '18+'],
  ];
  const text = (
    id: string,
    label: string,
    value: string,
    onChange: (value: string) => void,
    hint?: string,
    multiline = false,
  ) => {
    const props = {
      id,
      value,
      'aria-invalid':
        matching(issues, id).length ||
        findings.some((f) => f.field === id && f.severity === 'error')
          ? true
          : undefined,
      'aria-describedby': described(id, findings, issues, hint),
    };
    return (
      <div className="editor-field">
        <label htmlFor={id}>{label}</label>
        {multiline ? (
          <textarea {...props} rows={8} onChange={(e) => onChange(e.target.value)} />
        ) : (
          <input {...props} onChange={(e) => onChange(e.target.value)} />
        )}
        {hint && (
          <p className="small muted field-hint" id={`${id}-hint`}>
            {hint}
          </p>
        )}
        <FieldFindings id={id} findings={findings} />
        <FieldErrors id={id} issues={matching(issues, id)} />
      </div>
    );
  };
  return (
    <div className="publishing-form">
      <section aria-labelledby="pub-details">
        <h3 id="pub-details">Book details</h3>
        <dl className="facts">
          <div>
            <dt>Title</dt>
            <dd>{book.title}</dd>
          </div>
          <div>
            <dt>Subtitle</dt>
            <dd>{book.subtitle ?? 'None'}</dd>
          </div>
          <div>
            <dt>Author</dt>
            <dd>{book.author ?? 'None'}</dd>
          </div>
          <div>
            <dt>Imprint</dt>
            <dd>{book.imprint ?? 'None'}</dd>
          </div>
          <div>
            <dt>Language</dt>
            <dd>{book.language}</dd>
          </div>
        </dl>
        <FieldFindings id="book" findings={findings} />
        <p className="small muted">
          These come from the book and print on the cover, so KDP sees the same values. Edit them in{' '}
          <a href={`${base}/settings`}>Settings</a>.
        </p>
        <div className="field-pair">
          {text(
            'publishing.series.title',
            'Series title (optional)',
            pub.series?.title ?? '',
            (title) =>
              update({
                series: title ? { title, number: pub.series?.number ?? null } : null,
              }),
          )}
          {text(
            'publishing.series.number',
            'Series number',
            pub.series?.number == null ? '' : String(pub.series.number),
            (value) =>
              pub.series &&
              update({
                series: {
                  ...pub.series,
                  number: whole(value),
                },
              }),
          )}
        </div>
        {text(
          'publishing.edition',
          'Edition number (optional)',
          pub.edition == null ? '' : String(pub.edition),
          (value) =>
            update({
              edition: whole(value),
            }),
          'Enter 1 for a first edition. KDP does not let you change it after publishing.',
        )}
        <fieldset className="choice-group contributor-list" id="publishing.contributors">
          <legend>Contributors (optional)</legend>
          <p className="small muted field-hint">
            Additional people who worked on this book. The primary author is in the book details.
          </p>
          <ol>
            {pub.contributors.map((person, i) => {
              const id = `publishing.contributors.${i}`;
              const set = (next: Partial<typeof person>) =>
                update({
                  contributors: pub.contributors.map((c, j) => (j === i ? { ...c, ...next } : c)),
                });
              return (
                <li key={i}>
                  <label htmlFor={`${id}.role`} className="visually-hidden">
                    Contributor {i + 1} role
                  </label>
                  <select
                    id={`${id}.role`}
                    value={person.role}
                    onChange={(e) => set({ role: e.target.value })}
                  >
                    {ROLES.map(([v, t]) => (
                      <option key={v} value={v}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <label htmlFor={`${id}.name`} className="visually-hidden">
                    Contributor {i + 1} name
                  </label>
                  <input
                    id={`${id}.name`}
                    value={person.name}
                    aria-describedby={described(id, findings, issues)}
                    onChange={(e) => set({ name: e.target.value })}
                  />
                  <button
                    type="button"
                    aria-label={`Remove contributor ${i + 1}`}
                    onClick={() =>
                      update({ contributors: pub.contributors.filter((_, j) => j !== i) })
                    }
                  >
                    Remove
                  </button>
                  <FieldFindings id={id} findings={findings} />
                  <FieldErrors id={id} issues={matching(issues, id)} />
                </li>
              );
            })}
          </ol>
          <button
            type="button"
            onClick={() =>
              update({ contributors: [...pub.contributors, { role: 'editor', name: '' }] })
            }
          >
            Add contributor
          </button>
        </fieldset>
      </section>

      <section aria-labelledby="pub-description">
        <h3 id="pub-description">Description</h3>
        {text(
          'publishing.description',
          `Description (${description.length.toLocaleString('en-US')} of 4,000 characters)`,
          description,
          (value) => update({ description: value.trim() ? value : null }),
          'Plain text; separate paragraphs with a blank line. Describe what the book contains. KDP does not accept links, contact details, prices, reviews or keyword lists here. PuzzlePress never rewrites it.',
          true,
        )}
      </section>

      <section aria-labelledby="pub-discovery">
        <h3 id="pub-discovery">Keywords and categories</h3>
        <TextList
          legend="Keywords"
          path="publishing.keywords"
          items={pub.keywords}
          limit={7}
          hint="Up to seven words or short phrases a reader might search for. Avoid repeating the title, quotation marks, and claims such as best or new."
          addLabel="Add keyword"
          onChange={(keywords) => update({ keywords })}
          issues={issues}
          findings={findings}
        />
        <TextList
          legend="Category preferences"
          path="publishing.categories"
          items={pub.categories}
          limit={3}
          hint={
            coloring
              ? "Saved preferences, written as a path with ' > ' between levels. KDP's list changes by marketplace and over time: confirm each one in KDP's selector."
              : "Saved preferences, written as a path such as Humor & Entertainment > Puzzles & Games > Word Search. KDP's list changes by marketplace and over time: confirm each one in KDP's selector."
          }
          addLabel="Add category"
          onChange={(categories) => update({ categories })}
          issues={issues}
          findings={findings}
        />
      </section>

      <section aria-labelledby="pub-audience">
        <h3 id="pub-audience">Audience and classification</h3>
        <Radios
          legend="Sexually explicit images or title"
          name="pub-explicit"
          path="publishing.audience.sexually_explicit"
          value={String(pub.audience.sexually_explicit) as 'true' | 'false' | 'null'}
          options={[
            ['false', 'No'],
            ['true', 'Yes'],
            ['null', 'Not answered', 'KDP requires an answer'],
          ]}
          onChange={(v) =>
            update({
              audience: { ...pub.audience, sexually_explicit: v === 'null' ? null : v === 'true' },
            })
          }
          issues={issues}
          findings={findings}
        />
        <fieldset className="choice-group" id="publishing.audience.reading_age">
          <legend>Reading age (optional)</legend>
          <div className="field-pair">
            {(['minimum', 'maximum'] as const).map((which) => (
              <div className="editor-field" key={which}>
                <label htmlFor={`publishing.audience.reading_age.${which}`}>
                  {which === 'minimum' ? 'From' : 'To'}
                </label>
                <select
                  id={`publishing.audience.reading_age.${which}`}
                  value={age[which] == null ? '' : String(age[which])}
                  onChange={(e) =>
                    setAge({ [which]: e.target.value === '' ? null : Number(e.target.value) })
                  }
                >
                  {ages.map(([v, t]) => (
                    <option key={v} value={v}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
          <FieldFindings id="publishing.audience.reading_age" findings={findings} />
          <FieldErrors
            id="publishing.audience.reading_age"
            issues={matching(issues, 'publishing.audience.reading_age')}
          />
        </fieldset>
        <Radios
          legend="Low-content book"
          name="pub-low-content"
          path="publishing.low_content"
          value={String(pub.low_content) as 'true' | 'false' | 'null'}
          options={[
            [
              'false',
              'Not low-content',
              coloring
                ? 'KDP lists coloring books as not generally low-content'
                : 'KDP lists puzzle books as not generally low-content',
            ],
            ['true', 'Low-content', 'Repetitive pages to fill in, such as journals or log books'],
            ['null', 'Not decided', 'Blocks the package; PuzzlePress does not choose for you'],
          ]}
          onChange={(v) => update({ low_content: v === 'null' ? null : v === 'true' })}
          issues={issues}
          findings={findings}
        />
      </section>

      <section aria-labelledby="pub-isbn">
        <h3 id="pub-isbn">ISBN</h3>
        <Radios
          legend="ISBN option"
          name="pub-isbn"
          path="publishing.isbn.mode"
          value={pub.isbn.mode}
          options={[
            ['kdp_free', 'Free KDP ISBN', 'KDP assigns it during setup; usable only on KDP'],
            ['own', 'My own ISBN', 'One you registered with an ISBN agency'],
            ['none', 'No ISBN', 'Allowed for low-content books only'],
            ['undecided', 'Not decided', 'Blocks the package; PuzzlePress never invents an ISBN'],
          ]}
          onChange={(mode) =>
            update({ isbn: { mode, value: mode === 'own' ? pub.isbn.value : null } })
          }
          issues={issues}
          findings={findings}
        />
        {pub.isbn.mode === 'own' &&
          text(
            'publishing.isbn.value',
            'ISBN-13',
            pub.isbn.value ?? '',
            (value) => update({ isbn: { mode: 'own', value: value.trim() ? value : null } }),
            'Kept exactly as you type it. PuzzlePress checks the format and check digit only; it cannot verify registration or ownership.',
          )}
      </section>

      <section aria-labelledby="pub-ai">
        <h3 id="pub-ai">AI content disclosure</h3>
        {coloring ? (
          <p className="small muted">
            KDP asks you to disclose AI-generated text, images and translations, and counts cover
            and interior images and artwork as images: a drawing made with an AI tool is
            AI-generated even if you edited it substantially afterwards. Your own drawing refined
            with AI tools is AI-assisted and needs no disclosure. PuzzlePress prepares your files
            with fixed image adjustments; it does not generate or trace artwork. Nothing is
            preselected.
          </p>
        ) : (
          <p className="small muted">
            KDP asks you to disclose AI-generated text, images and translations. Content you created
            and only edited with AI tools is AI-assisted and needs no disclosure. PuzzlePress&apos;s
            puzzle grids are placed by a deterministic program, not an AI model, but you decide how
            the book&apos;s words, text and photograph were made. Nothing is preselected.
          </p>
        )}
        {coloring &&
          (['interior_artwork', 'cover_artwork'] as const).map((kind) => (
            <Radios
              key={kind}
              legend={
                kind === 'interior_artwork'
                  ? 'Interior drawings (the coloring pages)'
                  : 'Cover artwork or photograph'
              }
              name={`pub-ai-${kind}`}
              path={`publishing.ai_disclosure.${kind}`}
              value={pub.ai_disclosure[kind] ?? 'unknown'}
              options={
                kind === 'cover_artwork'
                  ? [...ORIGINS.slice(0, 3), ['none', 'No artwork on the cover'], ORIGINS[3]]
                  : ORIGINS
              }
              onChange={(origin) =>
                update({ ai_disclosure: { ...pub.ai_disclosure, [kind]: origin } })
              }
              issues={issues}
              findings={findings}
            />
          ))}
        {(['text', 'images', 'translations'] as const).map((kind) => (
          <Radios
            key={kind}
            legend={
              kind === 'text'
                ? coloring
                  ? 'Text (captions, dividers, instructions, description)'
                  : 'Text (word lists, instructions, description)'
                : kind === 'images'
                  ? coloring
                    ? "Images: KDP's one answer for cover and interior artwork"
                    : 'Images (cover photograph)'
                  : 'Translations'
            }
            name={`pub-ai-${kind}`}
            path={`publishing.ai_disclosure.${kind}`}
            value={pub.ai_disclosure[kind]}
            options={
              kind === 'translations'
                ? [['none', 'Not a translation'], ...ORIGINS.filter(([v]) => v !== 'human')]
                : ORIGINS
            }
            onChange={(origin) =>
              update({ ai_disclosure: { ...pub.ai_disclosure, [kind]: origin } })
            }
            issues={issues}
            findings={findings}
          />
        ))}
      </section>

      {coloring && (
        <section aria-labelledby="pub-rights">
          <h3 id="pub-rights">Artwork rights</h3>
          <p className="small muted">
            Having an image file is not a right to publish it. Declare the basis on which you may
            publish each kind of content. PuzzlePress records what you choose and cannot verify it;
            KDP holds you responsible for rights and may ask for proof.
          </p>
          {(
            [
              ['interior_artwork', 'Interior drawings'],
              ['cover_artwork', 'Cover artwork or photograph'],
              ['text', 'Text (captions, dividers, instructions, description)'],
            ] as const
          ).map(([kind, legend]) => (
            <Radios
              key={kind}
              legend={legend}
              name={`pub-rights-${kind}`}
              path={`publishing.content_rights.${kind}`}
              value={pub.content_rights?.[kind] ?? 'undecided'}
              options={
                kind === 'cover_artwork'
                  ? [...RIGHTS.slice(0, 5), ['none', 'No artwork on the cover', ''], RIGHTS[5]]
                  : RIGHTS
              }
              onChange={(basis) =>
                update({
                  content_rights: {
                    interior_artwork: 'undecided',
                    cover_artwork: 'undecided',
                    text: 'undecided',
                    notes: null,
                    ...pub.content_rights,
                    [kind]: basis,
                  },
                })
              }
              issues={issues}
              findings={findings}
            />
          ))}
          {text(
            'publishing.content_rights.notes',
            'Rights notes (optional)',
            pub.content_rights?.notes ?? '',
            (value) =>
              update({
                content_rights: {
                  interior_artwork: 'undecided',
                  cover_artwork: 'undecided',
                  text: 'undecided',
                  ...pub.content_rights,
                  notes: value.trim() ? value : null,
                },
              }),
            'Licence names, sources and agreements, for your records.',
            true,
          )}
        </section>
      )}

      <section aria-labelledby="pub-confirm">
        <h3 id="pub-confirm">Your confirmations</h3>
        <p className="small muted">
          Only you can confirm these. Each confirmation records exactly what you reviewed, with no
          date; editing anything it covers asks you to review it again. PuzzlePress cannot verify
          rights, authorship, ISBN registration or AI use.
        </p>
        <Confirmations
          pub={pub}
          check={check}
          update={update}
          replaceSection={replaceSection}
          issues={issues}
        />
      </section>

      <section aria-labelledby="pub-notes">
        <h3 id="pub-notes">Notes</h3>
        {text(
          'publishing.notes',
          'Publishing notes (optional)',
          pub.notes ?? '',
          (value) => update({ notes: value.trim() ? value : null }),
          'For you only. Included at the end of the checklist; never sent anywhere.',
          true,
        )}
      </section>
    </div>
  );
}

function Confirmations({
  pub,
  check,
  update,
  replaceSection,
  issues,
}: {
  pub: PublishingConfig;
  check: PublishingDraftCheck | undefined;
  update: (next: Partial<PublishingConfig>) => void;
  replaceSection: (next: PublishingConfig) => void;
  issues: Issue[];
}) {
  // Until Python has checked this exact draft, nothing shows as confirmed.
  const rows = check?.metadata.confirmations.filter((c) => c.required) ?? [];
  const upgrade = check?.upgrade ?? null;
  return (
    <fieldset
      className="choice-group confirmations"
      id="publishing.attestations"
      aria-busy={check ? undefined : true}
    >
      <legend className="visually-hidden">Confirmations</legend>
      {upgrade && (
        <div className="notice confirmation-upgrade">
          <p>
            This publishing section is version 1, which saved confirmations as yes or no without
            recording what you reviewed. They no longer count. Upgrade to version 2 to confirm the
            current content again; your metadata is kept and nothing is confirmed for you.
          </p>
          <button type="button" onClick={() => replaceSection(upgrade)}>
            Upgrade publishing section
          </button>
        </div>
      )}
      {!check && <p className="small muted">Checking confirmations…</p>}
      {rows.map((c) => {
        const [tone, label] = CONFIRMATION_STATE[c.state];
        const stateId = `confirm-${c.name}-state`;
        return (
          <div className="confirmation" key={c.name}>
            <label className="check">
              <input
                type="checkbox"
                checked={c.state === 'confirmed'}
                disabled={upgrade !== null}
                aria-describedby={stateId}
                onChange={(e) =>
                  update({
                    attestations: {
                      ...pub.attestations,
                      [c.name]: e.target.checked ? c.current : null,
                    },
                  })
                }
              />
              <span>{c.statement}</span>
            </label>
            <p className="small confirmation-state" id={stateId}>
              <Status tone={tone}>{label}</Status> {c.message}
            </p>
          </div>
        );
      })}
      <FieldErrors
        id="publishing.attestations"
        issues={matching(issues, 'publishing.attestations')}
      />
    </fieldset>
  );
}

function verdictLine(tone: 'pass' | 'review' | 'fail' | 'neutral', label: string): ReactNode {
  return <Status tone={tone}>{label}</Status>;
}

// Specific, ordered state lines; each states what is true and where to act.
function stateLines(status: PublishingStatus, key: string) {
  const r = status.readiness;
  const v = r.verdicts;
  const base = `/books/${encodeURIComponent(key)}`;
  const first = (code: string) => r.findings.find((f) => f.code === code)?.message;
  const lines: { tone: 'pass' | 'review' | 'fail'; text: ReactNode }[] = [];
  if (v.metadata === 'missing')
    lines.push({ tone: 'fail', text: 'Publishing metadata has not been started.' });
  else if (v.metadata === 'invalid')
    lines.push({ tone: 'fail', text: 'Metadata needs attention before packaging.' });
  else lines.push({ tone: 'pass', text: 'Metadata meets the supported KDP rules.' });
  const interior = v.interior!;
  if (interior.state === 'missing')
    lines.push({
      tone: 'fail',
      text: (
        <>
          No interior is built. <a href={`${base}/print`}>Build it in Print</a>.
        </>
      ),
    });
  else if (interior.state === 'stale')
    lines.push({
      tone: 'fail',
      text: (
        <>
          {first('interior_structural') ?? 'The interior is out of date.'}{' '}
          <a href={`${base}/print`}>Rebuild in Print</a>.
        </>
      ),
    });
  else if (interior.structural !== 'valid')
    lines.push({ tone: 'fail', text: 'The interior files do not agree; rebuild in Print.' });
  else if (interior.kdp !== 'ready')
    lines.push({
      tone: 'fail',
      text: (
        <>
          The interior is not KDP ready: {first('interior_kdp') ?? 'see blocking findings'}{' '}
          <a href={`${base}/print`}>Open Print</a>.
        </>
      ),
    });
  else lines.push({ tone: 'pass', text: 'Interior current and KDP ready.' });
  const cover = v.cover!;
  if (cover.state === 'no_config' || cover.state === 'missing')
    lines.push({
      tone: 'fail',
      text: (
        <>
          {cover.state === 'no_config' ? 'No cover is designed.' : 'No cover is built.'}{' '}
          <a href={`${base}/cover`}>Open Cover</a>.
        </>
      ),
    });
  else if (cover.state === 'stale' || r.findings.some((f) => f.code === 'cover_matches_interior'))
    lines.push({
      tone: 'fail',
      text: (
        <>
          {first('cover_matches_interior') ??
            first('cover_structural') ??
            'The cover is out of date.'}{' '}
          <a href={`${base}/cover`}>Rebuild in Cover</a>.
        </>
      ),
    });
  else if (cover.structural !== 'valid')
    lines.push({ tone: 'fail', text: 'The cover files do not agree; rebuild in Cover.' });
  else if (cover.kdp !== 'ready')
    lines.push({
      tone: 'fail',
      text: (
        <>
          The cover is not KDP ready: {first('cover_kdp') ?? 'see blocking findings'}{' '}
          <a href={`${base}/cover`}>Open Cover</a>.
        </>
      ),
    });
  else lines.push({ tone: 'pass', text: 'Cover current and KDP ready.' });
  if (v.disclosure !== 'complete')
    lines.push({ tone: 'fail', text: 'AI content disclosure is not yet declared.' });
  if (v.attestations !== 'complete')
    lines.push({ tone: 'fail', text: 'Your confirmations are incomplete.' });
  const exported = status.package.export.state;
  if (v.package === 'ready')
    lines.push({
      tone: 'pass',
      text:
        exported === 'current'
          ? 'Package exported and current. Upload it in KDP yourself.'
          : 'Package ready for manual KDP submission.',
    });
  if (exported === 'stale')
    lines.push({
      tone: 'review',
      text: 'The exported package no longer matches the book; export again.',
    });
  if (exported === 'damaged')
    lines.push({
      tone: 'fail',
      text: `The exported package is damaged: ${status.package.export.problem}`,
    });
  return lines;
}

function FindingGroups({
  findings,
  projectKey,
  coloring = false,
}: {
  findings: PublishingFinding[];
  projectKey: string;
  coloring?: boolean;
}) {
  const base = `/books/${encodeURIComponent(projectKey)}`;
  const groups: [string, PublishingFinding['severity']][] = [
    ['Blocking', 'error'],
    ['Review before upload', 'warning'],
    ['Notes', 'info'],
  ];
  return (
    <>
      {groups.map(([heading, severity]) => {
        const items = findings.filter((f) => f.severity === severity);
        if (!items.length) return null;
        return (
          <div key={severity}>
            <h4>
              {heading} ({items.length})
            </h4>
            <ul className="finding-list">
              {items.map((f, i) => (
                <li key={i}>
                  <div className="finding-head">
                    <Status tone={SEVERITY[severity][0]}>{SEVERITY[severity][1]}</Status>
                    <span className="finding-scope">{areaLabel(f, coloring)}</span>
                  </div>
                  <p>{f.message}</p>
                  {f.action && <p className="small">{f.action}</p>}
                  <p className="finding-meta">
                    {f.area === 'publishing' && f.field ? (
                      <a href={`#${f.field}`}>Go to field</a>
                    ) : (
                      <a href={`${base}/${areaRoute(f, coloring)}`}>
                        Open {areaLabel(f, coloring)}
                      </a>
                    )}{' '}
                    · <code>{f.code}</code>
                    {f.related && (
                      <>
                        {' '}
                        · <code>{f.related}</code>
                      </>
                    )}{' '}
                    ·{' '}
                    {f.source.url.startsWith('http') ? (
                      <a href={f.source.url} target="_blank" rel="noreferrer">
                        {f.source.title}
                      </a>
                    ) : (
                      f.source.title
                    )}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </>
  );
}

function Summary({ status, d }: { status: PublishingStatus; d: Draft }) {
  const r = status.readiness;
  const v = r.verdicts;
  const print = r.print;
  const book = d.saved.source!.book;
  const cover = print?.cover;
  const preview = status.cover_preview;
  const tone = (ok: boolean) => (ok ? 'pass' : 'fail');
  return (
    <section className="publishing-summary" aria-labelledby="pub-summary">
      <h3 id="pub-summary" className="visually-hidden">
        Publishing summary
      </h3>
      <div className="publishing-front">
        {preview && cover ? (
          <div className="front-window" style={{ aspectRatio: `${8.5} / ${11}` }}>
            <img
              src={`/api/projects/${encodeURIComponent(d.key)}/cover/preview?size=preview&pdf=${preview.pdf_sha256}`}
              alt={`Front cover of ${book.title}, from the built cover.pdf`}
              style={{
                width: `${(cover.width_in / 8.5) * 100}%`,
                left: `${(-(cover.bleed_in + 8.5 + cover.spine_width_in) / 8.5) * 100}%`,
                top: `${(-cover.bleed_in / 11) * 100}%`,
              }}
            />
          </div>
        ) : (
          <div className="front-window empty">
            <p className="small muted">No current cover.pdf to show.</p>
          </div>
        )}
      </div>
      <div>
        <p className="publishing-title">{book.title}</p>
        {book.subtitle && <p className="publishing-subtitle">{book.subtitle}</p>}
        <p>{book.author ?? 'No author'}</p>
        <dl className="facts publishing-facts">
          <div>
            <dt>Format</dt>
            <dd>
              Paperback{print ? `, ${print.trim_in[0]} x ${print.trim_in[1]} in, no bleed` : ''}
            </dd>
          </div>
          <div>
            <dt>Paper</dt>
            <dd>{print ? `${print.ink} ink on ${print.paper} paper` : 'Not built'}</dd>
          </div>
          <div>
            <dt>Pages</dt>
            <dd>{print?.page_count ?? 'Not built'}</dd>
          </div>
          <div>
            <dt>Spine</dt>
            <dd>{cover ? `${cover.spine_width_in.toFixed(4)} in` : 'No current cover'}</dd>
          </div>
        </dl>
        <dl className="print-verdict" aria-label="Publishing verdicts">
          <div>
            <dt>Metadata</dt>
            <dd>
              {verdictLine(
                v.metadata === 'valid' ? 'pass' : 'fail',
                v.metadata === 'valid' ? 'Valid' : v.metadata === 'missing' ? 'Missing' : 'Invalid',
              )}
            </dd>
          </div>
          <div>
            <dt>Interior</dt>
            <dd>
              {verdictLine(
                tone(v.interior?.kdp === 'ready' && v.interior.state === 'current'),
                v.interior?.state !== 'current'
                  ? (v.interior?.state ?? 'missing').replace('_', ' ')
                  : v.interior.kdp === 'ready'
                    ? 'KDP ready'
                    : 'Not KDP ready',
              )}
            </dd>
          </div>
          <div>
            <dt>Cover</dt>
            <dd>
              {verdictLine(
                tone(v.cover?.kdp === 'ready' && v.cover.state === 'current'),
                v.cover?.state !== 'current'
                  ? (v.cover?.state ?? 'missing').replace('no_config', 'not designed')
                  : v.cover.kdp === 'ready'
                    ? 'KDP ready'
                    : 'Not KDP ready',
              )}
            </dd>
          </div>
          <div>
            <dt>Package</dt>
            <dd>
              {verdictLine(
                tone(v.package === 'ready'),
                v.package === 'ready' ? 'Ready' : 'Not ready',
              )}
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

function Readiness({
  status,
  d,
  busy,
  archive,
  setArchive,
  onExport,
}: {
  status: PublishingStatus;
  d: Draft;
  busy: boolean;
  archive: boolean;
  setArchive: (value: boolean) => void;
  onExport: () => void;
}) {
  const r = status.readiness;
  const ready = r.verdicts.package === 'ready';
  const done = status.export?.success ? status.export : undefined;
  return (
    <aside
      className="publishing-readiness"
      id="publishing-readiness"
      tabIndex={-1}
      aria-labelledby="pub-readiness"
    >
      <h3 id="pub-readiness">Readiness</h3>
      <p className="small muted">
        Saved source{d.dirty ? '. Save your draft to update this column' : ''}. Ruleset{' '}
        {r.ruleset.id} v{r.ruleset.version}; KDP rules checked {r.ruleset.kdp_rules_checked}.
      </p>
      <ul className="state-lines">
        {stateLines(status, d.key).map((line, i) => (
          <li key={i}>
            <Status tone={line.tone}>
              {line.tone === 'pass' ? 'Done' : line.tone === 'review' ? 'Review' : 'To do'}
            </Status>
            <span>{line.text}</span>
          </li>
        ))}
      </ul>
      <p className="publishing-statement">{r.statement}</p>
      <h4 className="checklist-heading">Checklist</h4>
      <PublishingChecklist status={status} projectKey={d.key} />
      <section className="publishing-export" aria-labelledby="pub-export">
        <h3 id="pub-export">Export</h3>
        <p className="small">
          Writes the verified files to <code>{status.package.location}</code> (relative to the
          project folder). Nothing is uploaded; you submit in KDP yourself.
        </p>
        <label className="check">
          <input type="checkbox" checked={archive} onChange={(e) => setArchive(e.target.checked)} />
          <span>
            Also write <code>{status.package.archive.split('/').pop()}</code>
          </span>
        </label>
        <button
          type="button"
          className="primary"
          disabled={busy || d.dirty || !ready}
          onClick={onExport}
        >
          {status.package.export.state === 'current' ? 'Export package again' : 'Export package'}
        </button>
        {d.dirty && (
          <p className="draft-status small">
            Save the draft first: packages build from saved source.
          </p>
        )}
        {!ready && !d.dirty && (
          <p className="small muted">Export is available once nothing blocks the package.</p>
        )}
        {status.export && !status.export.success && (
          <div role="alert" className="notice error">
            <h4>No package was written</h4>
            <p>{status.export.message}</p>
          </div>
        )}
        {done && (
          <div className="export-summary" role="status">
            <h4>Package exported</h4>
            <p className="small">
              {done.files?.length ?? 0} files and package.json in{' '}
              <code>{status.package.location}</code>
              {done.archive ? ', plus the ZIP archive' : ''}. Not submitted to Amazon.
            </p>
            <code className="identity">{done.identity}</code>
          </div>
        )}
        <details className="details">
          <summary>Package contents ({status.package.files.length} files)</summary>
          <ul className="package-files">
            {status.package.files.map((f) => {
              const written = done?.files?.find((x) => x.name === f.name);
              return (
                <li key={f.name}>
                  <code>{f.name}</code> <span className="small muted">{f.purpose}</span>
                  {written && (
                    <span className="small muted"> · SHA-256 {written.sha256.slice(0, 16)}…</span>
                  )}
                </li>
              );
            })}
          </ul>
        </details>
        <details className="details">
          <summary>KDP upload checklist</summary>
          <pre className="checklist" tabIndex={0} aria-label="KDP upload checklist">
            {status.checklist}
          </pre>
        </details>
      </section>
      <section aria-labelledby="pub-findings" className="publishing-findings">
        <h3 id="pub-findings">All findings and checks</h3>
        <details className="details">
          <summary>Findings by severity ({r.findings.length})</summary>
          {r.findings.length === 0 ? (
            <p>No findings.</p>
          ) : (
            <FindingGroups findings={r.findings} projectKey={d.key} coloring={!!d.draft.coloring} />
          )}
        </details>
        <details className="details rule-list">
          <summary>All checks ({r.rules.length})</summary>
          <ul>
            {r.rules.map((rule) => (
              <li key={rule.code}>
                <strong>{rule.title}</strong>{' '}
                <span className="muted">{rule.outcome.replaceAll('_', ' ')}</span>
                {rule.note && <p>{rule.note}</p>}
                <p className="small muted">
                  {rule.source.title} · {rule.basis.replaceAll('_', ' ')} · <code>{rule.code}</code>
                </p>
              </li>
            ))}
          </ul>
        </details>
      </section>
    </aside>
  );
}

export function Publishing({ d }: { d: Draft }) {
  const pub = d.draft.publishing;
  const [status, setStatus] = useState<PublishingStatus>();
  const [statusError, setStatusError] = useState<Error>();
  const [attempt, setAttempt] = useState(0);
  // The latest draft check and the draft it describes; confirmations need an exact match.
  const [check, setCheck] = useState<{ signature: string; data: PublishingDraftCheck }>();
  const [checkIssues, setCheckIssues] = useState<Issue[]>([]);
  const [busy, setBusy] = useState(false);
  const [archive, setArchive] = useState(false);
  const [message, setMessage] = useState('');
  const base = `/api/projects/${encodeURIComponent(d.key)}`;
  const latest = useRef(d.draft);
  latest.current = d.draft;
  const signature = JSON.stringify([pub, d.draft.book]);

  useEffect(() => {
    const controller = new AbortController();
    setStatusError(undefined);
    request<PublishingStatus>(`${base}/publishing`, controller.signal)
      .then((data) => !controller.signal.aborted && setStatus(data))
      .catch((err: Error) => !controller.signal.aborted && setStatusError(err));
    return () => controller.abort();
  }, [base, d.saved.revision, attempt]);

  useEffect(() => {
    if (!pub) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      request<PublishingDraftCheck>(`${base}/draft/publishing`, controller.signal, {
        source: latest.current,
      })
        .then((data) => {
          if (controller.signal.aborted) return;
          setCheck({ signature, data });
          setCheckIssues([]);
        })
        .catch((err: Error) => {
          if (controller.signal.aborted) return;
          setCheck(undefined);
          setCheckIssues(err instanceof ApiError ? err.issues : []);
        });
    }, 350);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // `signature` captures every draft value the metadata check depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, signature]);

  const update = (next: Partial<PublishingConfig>) => {
    if (!pub) return;
    d.change({ ...d.draft, publishing: { ...pub, ...next } } as Source);
  };
  const exportPackage = async () => {
    setBusy(true);
    setMessage('Checking the saved book and writing the verified package…');
    try {
      const data = await request<PublishingStatus>(
        `${base}/publishing/export`,
        new AbortController().signal,
        {
          revision: d.saved.revision,
          archive,
        },
      );
      setStatus(data);
      setMessage(
        data.export?.success
          ? 'Package exported. It has not been uploaded or submitted.'
          : 'No package was written.',
      );
    } catch (err) {
      setMessage(
        err instanceof ApiError && err.code === 'source_changed'
          ? 'The saved source changed on disk. Reload the project before exporting.'
          : err instanceof Error
            ? err.message
            : 'The export request did not complete.',
      );
    } finally {
      setBusy(false);
    }
  };

  if (!d.draft.composition)
    return (
      <section className="notice">
        <h2>No book composition</h2>
        <p>
          A publishing package needs a built interior and cover. Compose the book in Book, build the
          interior in Print and the cover in Cover first.
        </p>
      </section>
    );
  const issues = [...d.issues, ...checkIssues];
  const metadata: MetadataReport | undefined = check?.data.metadata;
  const findings = metadata?.findings ?? [];
  const fresh = check?.signature === signature ? check.data : undefined;
  return (
    <div className="editor publishing">
      <DraftToolbar
        d={d}
        title="Publishing"
        jump={{ href: '#publishing-readiness', label: 'Jump to readiness' }}
      />
      <p role="status" aria-live="polite" className="small">
        {message}
      </p>
      {statusError && <ErrorState error={statusError} retry={() => setAttempt((n) => n + 1)} />}
      {status ? (
        <Summary status={status} d={d} />
      ) : (
        !statusError && <Loading>Checking metadata, interior and cover…</Loading>
      )}
      {d.draft.coloring ? (
        <p className="small muted">
          To build the interior, cover, artwork reports and this package in one verified run, use{' '}
          <code>puzzlepress book produce</code>. It writes nothing until every file is checked and
          never submits anything to Amazon.
        </p>
      ) : (
        <ProductionOverview
          projectKey={d.key}
          revision={d.saved.revision}
          dirty={d.dirty}
          onRebuilt={() => setAttempt((n) => n + 1)}
        />
      )}
      <div className="publishing-workspace">
        <div className="publishing-main">
          {pub ? (
            <>
              <p className="small muted publishing-draft-note">
                Fields are checked by Python as you type
                {metadata ? `: ${metadata.verdicts.metadata} metadata` : ''}. Blocking items must be
                resolved; review items are for your judgment.
              </p>
              <FieldErrors
                id="publishing"
                issues={matching(issues, 'publishing').filter((i) => i.path === 'publishing')}
              />
              <Metadata
                d={d}
                pub={pub}
                update={update}
                issues={issues}
                findings={findings}
                check={fresh}
                replaceSection={(next) => d.change({ ...d.draft, publishing: next } as Source)}
              />
            </>
          ) : (
            <section className="publishing-start" aria-labelledby="pub-start">
              <h3 id="pub-start">Prepare KDP paperback metadata</h3>
              <p>
                Add the description, keywords, categories, ISBN choice and AI disclosure KDP asks
                for. Every decision starts undecided; nothing is chosen or confirmed for you, and
                nothing is saved until you save.
              </p>
              <button
                type="button"
                className="primary"
                onClick={() =>
                  d.change({
                    ...d.draft,
                    publishing: starterPublishing(!!d.draft.coloring),
                  } as Source)
                }
              >
                Start publishing metadata
              </button>
            </section>
          )}
        </div>
        {status && (
          <Readiness
            status={status}
            d={d}
            busy={busy}
            archive={archive}
            setArchive={setArchive}
            onExport={() => void exportPackage()}
          />
        )}
      </div>
    </div>
  );
}
