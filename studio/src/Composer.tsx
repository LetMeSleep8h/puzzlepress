import { useEffect, useRef, useState, type ReactNode } from 'react';
import { request } from './api';
import { DraftToolbar, type Draft } from './draft';
import { Field, FieldErrors, SelectField, matchIssues, move, type Source } from './editor-fields';
import type { Composition, InteriorStatus, Issue, MatterItem, PlanPage, PlanResult } from './types';
import { Empty, Issues, Status } from './ui';

// Presentation of authored composition and the Python plan. Page assignment,
// numbering and verification are never computed here.
const KIND_NAMES: Record<string, string> = {
  title_page: 'Title page',
  copyright_page: 'Copyright page',
  instructions: 'Instructions',
  about: 'About page',
  notes: 'Notes page',
};
const SECTION_NAMES: Record<string, string> = {
  front_matter: 'Front matter',
  puzzles: 'Puzzles',
  solutions: 'Solutions',
  back_matter: 'Back matter',
};
const STARTS: [string, string][] = [
  ['any', 'Next page (no blank)'],
  ['recto', 'Right-hand (recto) page'],
];

export function newItem(kind: string): MatterItem {
  if (kind === 'copyright_page') return { kind, text: '' };
  if (kind === 'instructions')
    return {
      kind,
      title: 'How to Play',
      text: 'Find each listed word hidden in the grid. Words run in straight lines.',
    };
  if (kind === 'about') return { kind, title: 'About', text: '' };
  if (kind === 'notes') return { kind, title: 'Notes' };
  return { kind };
}

export const STARTER: Composition = {
  front_matter: [{ kind: 'title_page' }, newItem('instructions')],
  puzzles: { start: 'any' },
  solutions: { placement: 'end', title: 'Solutions', per_page: 4, start: 'any' },
  back_matter: [],
  page_numbers: {
    scheme: 'continuous',
    show_front_matter: false,
    show_solutions: true,
    show_back_matter: true,
  },
};

function Choice({
  legend,
  path,
  value,
  options,
  issues,
  onChange,
}: {
  legend: string;
  path: string;
  value: string;
  options: [string, string, string][];
  issues: Issue[];
  onChange: (value: string) => void;
}) {
  const matching = matchIssues(issues, path);
  return (
    <fieldset
      className="choice-group"
      aria-describedby={matching.length ? `${path}-issues` : undefined}
    >
      <legend>{legend}</legend>
      {options.map(([option, label, hint]) => (
        <label key={option}>
          <input
            type="radio"
            name={path}
            value={option}
            checked={value === option}
            onChange={() => onChange(option)}
          />
          <span>
            {label}
            <small>{hint}</small>
          </span>
        </label>
      ))}
      <FieldErrors id={path} issues={matching} />
    </fieldset>
  );
}

function Check({
  label,
  path,
  checked,
  issues,
  onChange,
}: {
  label: string;
  path: string;
  checked: boolean;
  issues: Issue[];
  onChange: (checked: boolean) => void;
}) {
  const matching = matchIssues(issues, path);
  return (
    <>
      <label className="check">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          aria-invalid={matching.length ? true : undefined}
          aria-describedby={matching.length ? `${path}-issues` : undefined}
        />
        {label}
      </label>
      <FieldErrors id={path} issues={matching} />
    </>
  );
}

function OutlineSection({
  id,
  title,
  note,
  children,
}: {
  id: string;
  title: string;
  note: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="outline-section" aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`}>{title}</h3>
      <p className="small muted">{note}</p>
      {children}
    </section>
  );
}

export function MatterList({
  items,
  kinds,
  path,
  issues,
  draft,
  onChange,
  onBook,
  make = newItem,
  titleNote = 'edit it at the top of Puzzles',
}: {
  items: MatterItem[];
  kinds: string[];
  path: string;
  issues: Issue[];
  draft: Source;
  onChange: (items: MatterItem[]) => void;
  onBook: (book: Source['book']) => void;
  /** A new page of this kind; coloring books start with their own instructions. */
  make?: (kind: string) => MatterItem;
  titleNote?: string;
}) {
  const missing = kinds.filter((kind) => !items.some((item) => item.kind === kind));
  return (
    <>
      <FieldErrors id={path} issues={issues.filter((i) => i.path === path)} />
      {items.length === 0 && <p className="muted">No pages in this section.</p>}
      <ol className="matter-list">
        {items.map((item, i) => {
          const at = `${path}.${i}`;
          const name = KIND_NAMES[item.kind] ?? item.kind;
          const update = (patch: Partial<MatterItem>) =>
            onChange(items.map((x, j) => (j === i ? { ...x, ...patch } : x)));
          const book = (key: 'subtitle' | 'author' | 'imprint', label: string) => (
            <Field
              label={label}
              path={`book.${key}`}
              value={draft.book[key] ?? ''}
              issues={issues}
              onChange={(value) => onBook({ ...draft.book, [key]: value === '' ? null : value })}
            />
          );
          return (
            <li key={i}>
              <div className="matter-head">
                <h4>{name}</h4>
                <button
                  type="button"
                  aria-label={`Move ${name} up`}
                  disabled={i === 0}
                  onClick={() => onChange(move(items, i, -1))}
                >
                  Up
                </button>
                <button
                  type="button"
                  aria-label={`Move ${name} down`}
                  disabled={i === items.length - 1}
                  onClick={() => onChange(move(items, i, 1))}
                >
                  Down
                </button>
                <button
                  type="button"
                  aria-label={`Remove ${name}`}
                  onClick={() => onChange(items.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </div>
              <FieldErrors
                id={at}
                issues={issues.filter((x) => x.path === at || x.path === `${at}.kind`)}
              />
              {item.kind === 'title_page' && (
                <>
                  <p className="small">
                    Uses the book’s metadata. Title: <strong>{draft.book.title}</strong>{' '}
                    <span className="muted">({titleNote})</span>
                  </p>
                  <div className="field-pair">
                    {book('subtitle', 'Subtitle (optional)')}
                    {book('author', 'Author (optional)')}
                  </div>
                  {book('imprint', 'Imprint or publisher (optional)')}
                </>
              )}
              {item.title !== undefined && (
                <Field
                  label={`${name} heading`}
                  path={`${at}.title`}
                  value={item.title}
                  issues={issues}
                  onChange={(title) => update({ title })}
                />
              )}
              {item.text !== undefined && (
                <Field
                  label={item.kind === 'copyright_page' ? 'Copyright notice' : `${name} text`}
                  path={`${at}.text`}
                  value={item.text}
                  issues={issues}
                  multiline
                  hint={
                    item.kind === 'copyright_page'
                      ? 'Write your own notice. PuzzlePress does not supply legal text.'
                      : 'Plain text; line breaks are kept.'
                  }
                  onChange={(text) => update({ text })}
                />
              )}
            </li>
          );
        })}
      </ol>
      {missing.length > 0 && (
        <div className="editor-actions">
          {missing.map((kind) => (
            <button
              type="button"
              key={kind}
              onClick={() =>
                onChange(kind === 'title_page' ? [make(kind), ...items] : [...items, make(kind)])
              }
            >
              Add {KIND_NAMES[kind].toLowerCase()}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

function describe(page: PlanPage, label: (index: number | null) => string): ReactNode {
  const matter = page.matter;
  if (page.blank)
    return (
      <>
        <em>Intentional blank</em>
        <small>
          {SECTION_NAMES[page.blank.before_section ?? '']} begin on a right-hand page ·{' '}
          <code>{page.blank.reason}</code>
        </small>
      </>
    );
  if (page.puzzle)
    return (
      <>
        <strong>
          Puzzle {page.puzzle.ordinal}: {page.puzzle.title}
        </strong>
        <small>
          {page.puzzle.theme} ·{' '}
          {page.solution_page ? `solution on page ${label(page.solution_page)}` : 'no solution'}
          {!page.puzzle.digest && (
            <>
              {' '}
              · <Status tone="fail">Not generated</Status>
            </>
          )}
        </small>
      </>
    );
  if (page.solutions.length)
    return (
      <>
        <strong>{page.heading ? `${page.heading} begin` : 'Solutions continued'}</strong>
        <small>
          {page.solutions
            .map((s) => `Puzzle ${s.puzzle.ordinal} (page ${label(s.puzzle_page)})`)
            .join(', ')}
        </small>
      </>
    );
  const name = KIND_NAMES[page.kind] ?? page.kind;
  if (page.kind === 'title_page')
    return (
      <>
        <strong>{name}</strong>
        <small>
          {[matter?.title, matter?.subtitle, matter?.author, matter?.imprint]
            .filter(Boolean)
            .join(' · ')}
        </small>
      </>
    );
  return (
    <>
      <strong>{matter?.title ? `${name}: ${matter.title}` : name}</strong>
      {matter?.text && <small className="plan-excerpt">{matter.text}</small>}
    </>
  );
}

// Every logical page in spreads (page 1 alone on the right), by section, with
// blanks marked: Python's plan drawn as a strip, never a print preview.
function PageSequence({ pages }: { pages: PlanPage[] }) {
  const spreads: (PlanPage | null)[][] = [[null, pages[0] ?? null]];
  for (let i = 1; i < pages.length; i += 2) spreads.push([pages[i], pages[i + 1] ?? null]);
  const sections = [...new Set(pages.map((p) => p.section))];
  const summary = sections
    .map((section) => {
      const own = pages.filter((p) => p.section === section);
      return `${SECTION_NAMES[section]} ${own.length} (pages ${own[0].index}–${own.at(-1)!.index})`;
    })
    .join('; ');
  const blanks = pages.filter((p) => p.blank).length;
  return (
    <figure className="page-sequence">
      <div
        className="sequence-strip"
        role="img"
        aria-label={`Page sequence: ${summary}; ${blanks} intentional ${blanks === 1 ? 'blank' : 'blanks'}.`}
      >
        {spreads.map((spread, i) => (
          <span className="sequence-spread" key={i}>
            {spread.map((page, j) =>
              page ? (
                <span
                  key={j}
                  className={`sequence-page ${page.section}${page.blank ? ' blank' : ''}`}
                  title={`Page ${page.index} · ${SECTION_NAMES[page.section]}${page.blank ? ' · blank' : ''}`}
                />
              ) : (
                <span key={j} className="sequence-page none" />
              ),
            )}
          </span>
        ))}
      </div>
      <figcaption className="sequence-legend">
        {sections.map((section) => {
          const own = pages.filter((p) => p.section === section);
          return (
            <span key={section}>
              <span className={`sequence-key ${section}`} aria-hidden="true" />
              {SECTION_NAMES[section]} <strong>{own.length}</strong>
            </span>
          );
        })}
        <span>
          <span className="sequence-key blank" aria-hidden="true" />
          Blank <strong>{blanks}</strong>
        </span>
      </figcaption>
    </figure>
  );
}

// The saved book's built interior, for comparing actual pages with this plan.
function BuiltPages({ projectKey, planned }: { projectKey: string; planned: number }) {
  const [status, setStatus] = useState<InteriorStatus | null>();
  useEffect(() => {
    const controller = new AbortController();
    request<InteriorStatus>(
      `/api/projects/${encodeURIComponent(projectKey)}/interior`,
      controller.signal,
    )
      .then((data) => !controller.signal.aborted && setStatus(data))
      .catch(() => !controller.signal.aborted && setStatus(null));
    return () => controller.abort();
  }, [projectKey]);
  if (status === undefined) return <p className="small muted">Reading the built interior…</p>;
  const pages = status?.preview?.page_count;
  if (!status || status.state === 'missing' || pages === undefined)
    return (
      <p className="small muted">
        No built interior yet: build it in{' '}
        <a href={`/books/${encodeURIComponent(projectKey)}/print`}>Print proof</a> to compare actual
        pages with this plan.
      </p>
    );
  return (
    <p className="small built-pages">
      <Status tone={status.state === 'current' && pages === planned ? 'pass' : 'review'}>
        Built interior: {pages} pages
      </Status>{' '}
      {status.state === 'current'
        ? pages === planned
          ? 'matches this plan page for page.'
          : `; this plan has ${planned}.`
        : `(${status.state}; rebuild in Print proof to match this plan of ${planned} pages).`}
    </p>
  );
}

function PlanView({ result, projectKey }: { result: PlanResult; projectKey: string }) {
  const { plan, verification, generation } = result;
  const s = plan.statistics;
  const label = (index: number | null) => (index ? plan.pages[index - 1]?.number.label : '?');
  const groups: { section: string; pages: PlanPage[] }[] = [];
  for (const page of plan.pages) {
    if (groups.at(-1)?.section !== page.section) groups.push({ section: page.section, pages: [] });
    groups.at(-1)!.pages.push(page);
  }
  return (
    <>
      <div className="plan-status">
        <Status tone={verification.valid ? 'pass' : 'fail'}>
          {verification.valid ? 'Plan independently verified' : 'Plan verification failed'}
        </Status>
        <Status tone={plan.complete ? 'pass' : 'fail'}>
          {plan.complete ? 'Every puzzle generated' : 'Incomplete: a puzzle did not generate'}
        </Status>
      </div>
      {plan.diagnostics.length > 0 && <Issues issues={plan.diagnostics} />}
      {!verification.valid && <Issues issues={verification.issues} />}
      <PageSequence pages={plan.pages} />
      <BuiltPages projectKey={projectKey} planned={s.logical_pages} />
      <dl className="plan-stats">
        <div>
          <dt>Logical pages</dt>
          <dd>{s.logical_pages}</dd>
        </div>
        <div>
          <dt>Puzzles</dt>
          <dd>{s.puzzles}</dd>
        </div>
        <div>
          <dt>Solutions</dt>
          <dd>
            {s.solutions} on {s.solution_pages} {s.solution_pages === 1 ? 'page' : 'pages'}
          </dd>
        </div>
        <div>
          <dt>Front / back matter</dt>
          <dd>
            {s.front_matter_pages} / {s.back_matter_pages}
          </dd>
        </div>
        <div>
          <dt>Intentional blanks</dt>
          <dd>{s.blank_pages}</dd>
        </div>
        <div>
          <dt>First puzzle</dt>
          <dd>{s.first_puzzle_page ? `logical page ${s.first_puzzle_page}` : 'none'}</dd>
        </div>
        <div>
          <dt>First solution</dt>
          <dd>{s.first_solution_page ? `logical page ${s.first_solution_page}` : 'none'}</dd>
        </div>
      </dl>
      <p className="small muted">
        Logical pages in reading order; page 1 is a right-hand (recto) page. This is not a print
        preview: physical layout and the final printed page count are not decided here. Numbers in
        parentheses are counted but not printed.
      </p>
      <p className="small muted">
        Quality review is separate: {generation.quality_findings}{' '}
        {generation.quality_findings === 1 ? 'finding' : 'findings'}. Inspect them with Preview
        draft in Puzzles.
      </p>
      <div className="table-scroll">
        <table className="plan-table">
          <caption className="sr-only">Logical pages in reading order</caption>
          <thead>
            <tr>
              <th scope="col">Page</th>
              <th scope="col">Side</th>
              <th scope="col">Number</th>
              <th scope="col">Content</th>
            </tr>
          </thead>
          {groups.map((group) => (
            <tbody key={group.pages[0].index}>
              <tr className="plan-section">
                <th scope="rowgroup" colSpan={4}>
                  {SECTION_NAMES[group.section]}
                </th>
              </tr>
              {group.pages.map((page) => (
                <tr key={page.index} className={page.blank ? 'plan-blank' : undefined}>
                  <td className="plan-index">{page.index}</td>
                  <td className="plan-side">{page.side}</td>
                  <td className="plan-folio">
                    {page.number.displayed ? (
                      page.number.label
                    ) : (
                      <span className="muted">
                        ({page.number.label})<span className="sr-only"> not printed</span>
                      </span>
                    )}
                  </td>
                  <td className="plan-entry">{describe(page, label)}</td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
      <details className="details">
        <summary>Plan identity</summary>
        <div>
          <p className="small">Plan version {plan.plan_version}. Same inputs, same plan.</p>
          <code className="identity">{plan.identity}</code>
        </div>
      </details>
    </>
  );
}

export function Composer({ d }: { d: Draft }) {
  const { draft, issues } = d;
  const composition = draft.composition;
  const ws = draft.word_search;
  const focusAfter = useRef<string | null>(null);
  const planned = useRef<string | undefined>(undefined);
  useEffect(() => {
    // Keep keyboard focus on the moved puzzle's control after reordering.
    if (!focusAfter.current) return;
    const button = document.getElementById(focusAfter.current) as HTMLButtonElement | null;
    focusAfter.current = null;
    if (button && !button.disabled) button.focus();
    else button?.parentElement?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
  });
  useEffect(() => {
    // Show the saved book's plan once per saved revision; drafts preview explicitly.
    if (!composition || d.dirty || d.plan || d.busy || d.error) return;
    if (planned.current === d.saved.revision) return;
    // After a save or reload, keep its announcement and add the refreshed plan.
    const done = planned.current ? `${d.message} Publication plan refreshed.` : undefined;
    planned.current = d.saved.revision;
    void d.run('plan', done);
  });
  const set = (next: Composition) => d.change({ ...draft, composition: next });
  const path = 'composition';
  return (
    <div className="editor composer">
      <DraftToolbar
        d={d}
        title="Book composer"
        preview="plan"
        previewLabel="Preview plan"
        previewDisabled={!composition}
        jump={{ href: '#plan-preview', label: 'Jump to plan' }}
      />
      {!ws ? (
        <Empty title="Add puzzles before composing a book">
          This project has no word-search puzzle definitions. A book plan arranges existing puzzles,
          so add them in Puzzles first.
        </Empty>
      ) : !composition ? (
        <Empty title="This project has no book composition yet">
          <span>
            Start with a title page, editable instructions and all solutions at the end. Nothing is
            saved until you choose Save changes. No copyright text is invented for you.
          </span>{' '}
          <button type="button" onClick={() => set(structuredClone(STARTER))}>
            Start book composition
          </button>
        </Empty>
      ) : (
        <div className="editor-layout">
          <form aria-label="Book composition" onSubmit={(event) => event.preventDefault()}>
            <fieldset className="authoring-fields" disabled={d.busy}>
              <legend className="sr-only">Book composition draft</legend>
              <nav className="outline-jump" aria-label="Composition sections">
                {[
                  ['front', 'Front matter'],
                  ['puzzles', 'Puzzles'],
                  ['solutions', 'Solutions'],
                  ['back', 'Back matter'],
                  ['numbers', 'Page numbers'],
                ].map(([id, name]) => (
                  <a key={id} href={`#${id}-heading`}>
                    {name}
                  </a>
                ))}
              </nav>
              <OutlineSection
                id="front"
                title="Front matter"
                note="Each item is one logical page, in this order. The title page must come first."
              >
                <MatterList
                  items={composition.front_matter}
                  kinds={['title_page', 'copyright_page', 'instructions']}
                  path={`${path}.front_matter`}
                  issues={issues}
                  draft={draft}
                  onChange={(front_matter) => set({ ...composition, front_matter })}
                  onBook={(book) => d.change({ ...draft, book })}
                />
              </OutlineSection>
              <OutlineSection
                id="puzzles"
                title="Puzzles"
                note="One puzzle per logical page. This is the project’s single puzzle order: reordering here also reorders Edit and reports, and never changes a grid, because seeds follow puzzle IDs."
              >
                <SelectField
                  label="Puzzle section starts on"
                  path={`${path}.puzzles.start`}
                  value={composition.puzzles.start}
                  options={STARTS}
                  issues={issues}
                  onChange={(start) => set({ ...composition, puzzles: { start } })}
                />
                <ol className="outline-list" aria-label="Puzzle publication order">
                  {ws.puzzles.map((p, i) => (
                    <li key={`${p.id}-${i}`}>
                      <span className="ordinal">{String(i + 1).padStart(2, '0')}</span>
                      <span className="outline-title">
                        <strong>{p.title || 'Untitled puzzle'}</strong>
                        <small>
                          {p.id} · {p.theme || 'no theme'}
                        </small>
                      </span>
                      {[-1, 1].map((dir) => (
                        <button
                          type="button"
                          key={dir}
                          id={`order-${dir < 0 ? 'up' : 'down'}-${i}`}
                          aria-label={`Move ${p.title || p.id} ${dir < 0 ? 'up' : 'down'}`}
                          disabled={dir < 0 ? i === 0 : i === ws.puzzles.length - 1}
                          onClick={() => {
                            d.change({
                              ...draft,
                              word_search: { ...ws, puzzles: move(ws.puzzles, i, dir) },
                            });
                            focusAfter.current = `order-${dir < 0 ? 'up' : 'down'}-${i + dir}`;
                          }}
                        >
                          {dir < 0 ? 'Up' : 'Down'}
                        </button>
                      ))}
                    </li>
                  ))}
                </ol>
              </OutlineSection>
              <OutlineSection
                id="solutions"
                title="Solutions"
                note="Solutions follow the puzzles in the same order. Grouping says which solutions share a logical page; their arrangement on paper is a later layout decision."
              >
                <Choice
                  legend="Solution placement"
                  path={`${path}.solutions.placement`}
                  value={composition.solutions.placement}
                  issues={issues}
                  options={[
                    ['end', 'At the end of the book', 'Every puzzle gets exactly one solution.'],
                    ['omit', 'Omit solutions', 'The book contains no solutions.'],
                  ]}
                  onChange={(placement) =>
                    set({
                      ...composition,
                      solutions:
                        placement === 'omit'
                          ? { placement }
                          : { placement, title: 'Solutions', per_page: 4, start: 'any' },
                    })
                  }
                />
                {composition.solutions.placement === 'end' && (
                  <>
                    <Field
                      label="Section heading"
                      path={`${path}.solutions.title`}
                      value={composition.solutions.title ?? ''}
                      issues={issues}
                      onChange={(title) =>
                        set({ ...composition, solutions: { ...composition.solutions, title } })
                      }
                    />
                    <p className="small">
                      {composition.solutions.per_page ?? 4} solutions on each printed page. Choose
                      and preview the answer layout in{' '}
                      <a href={`/books/${encodeURIComponent(d.key)}/interior#answers`}>
                        Interior design
                      </a>
                      .
                    </p>
                    <div className="field-pair">
                      <SelectField
                        label="Solutions section starts on"
                        path={`${path}.solutions.start`}
                        value={composition.solutions.start ?? 'any'}
                        options={STARTS}
                        issues={issues}
                        onChange={(start) =>
                          set({ ...composition, solutions: { ...composition.solutions, start } })
                        }
                      />
                    </div>
                  </>
                )}
              </OutlineSection>
              <OutlineSection
                id="back"
                title="Back matter"
                note="Optional pages after the solutions, one logical page each."
              >
                <MatterList
                  items={composition.back_matter}
                  kinds={['about', 'notes']}
                  path={`${path}.back_matter`}
                  issues={issues}
                  draft={draft}
                  onChange={(back_matter) => set({ ...composition, back_matter })}
                  onBook={(book) => d.change({ ...draft, book })}
                />
              </OutlineSection>
              <OutlineSection
                id="numbers"
                title="Page numbers"
                note="Every page is counted, including blanks. These settings decide which numbers are printed and in what style; placement and type are later layout decisions."
              >
                <Choice
                  legend="Numbering scheme"
                  path={`${path}.page_numbers.scheme`}
                  value={composition.page_numbers.scheme}
                  issues={issues}
                  options={[
                    ['continuous', 'Continuous', 'Arabic numbers from the first page.'],
                    [
                      'roman_front_matter',
                      'Roman front matter',
                      'i, ii, iii… for front matter; arabic restarts at 1 on the first puzzle section page.',
                    ],
                  ]}
                  onChange={(scheme) =>
                    set({ ...composition, page_numbers: { ...composition.page_numbers, scheme } })
                  }
                />
                <fieldset className="choice-group">
                  <legend>Print numbers on</legend>
                  {(
                    [
                      ['show_front_matter', 'Front matter pages'],
                      ['show_solutions', 'Solution pages'],
                      ['show_back_matter', 'Back matter pages'],
                    ] as const
                  ).map(([key, label]) => (
                    <Check
                      key={key}
                      label={label}
                      path={`${path}.page_numbers.${key}`}
                      checked={composition.page_numbers[key]}
                      issues={issues}
                      onChange={(value) =>
                        set({
                          ...composition,
                          page_numbers: { ...composition.page_numbers, [key]: value },
                        })
                      }
                    />
                  ))}
                  <p className="small muted">
                    Puzzle pages always print their numbers so solutions can refer to them. Blank
                    pages never print a number.
                  </p>
                </fieldset>
              </OutlineSection>
            </fieldset>
          </form>
          <section
            className="draft-preview plan-preview"
            id="plan-preview"
            tabIndex={-1}
            aria-labelledby="plan-heading"
          >
            <div className="section-heading">
              <h3 id="plan-heading">
                {d.plan && d.dirty ? 'Unsaved draft plan' : 'Publication plan'}
              </h3>
            </div>
            {d.plan ? (
              <PlanView result={d.plan} projectKey={d.key} />
            ) : (
              <div className="preview-empty">
                <h2>The book, in reading order.</h2>
                <p>
                  {d.dirty
                    ? 'Your draft changed. Choose Preview plan to see the new page order.'
                    : 'Preview plan validates the project, generates every puzzle and lists each logical page with its side and number.'}{' '}
                  Nothing is saved until you choose Save changes.
                </p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
