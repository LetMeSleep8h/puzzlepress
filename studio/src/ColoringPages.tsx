import { useEffect, useRef, useState, type DragEvent } from 'react';
import { ApiError, request } from './api';
import { MatterList } from './Composer';
import { DraftToolbar, type Draft } from './draft';
import { Field, FieldErrors, SelectField, matchIssues, type Source } from './editor-fields';
import type {
  ColoringPlanPage,
  ColoringPlanResult,
  ColoringSource,
  InteriorStatus,
  Issue,
  MatterItem,
} from './types';
import { Issues, Status } from './ui';

// Pages: the order of drawings and section dividers, front and back matter, blank
// backs, borders and page numbers. The browser edits the authored source only; which
// physical page each entry lands on, every blank page and every number come from
// Python's verified plan, and the built pages from Print proof.

type Entry = ColoringSource['pages'][number];
type ColoringComposition = {
  front_matter: MatterItem[];
  artwork: { start: string };
  back_matter: MatterItem[];
  page_numbers: {
    scheme: string;
    show_front_matter: boolean;
    show_artwork: boolean;
    show_back_matter: boolean;
  };
};

const BLANK_REASONS: Record<string, string> = {
  reverse_blank: 'Back of the page before, left blank so markers do not show through',
  section_recto_start: 'Added so the drawings start on a right-hand page',
  artwork_recto_start: 'Added so this coloring page stays on a right-hand page',
  divider_recto_start: 'Added so the divider starts on a right-hand page',
};
const MATTER_NAMES: Record<string, string> = {
  title_page: 'Title page',
  copyright_page: 'Copyright page',
  instructions: 'Instructions',
  about: 'About page',
  notes: 'Notes page',
};

function coloringMatter(kind: string): MatterItem {
  if (kind === 'copyright_page') return { kind, text: '' };
  if (kind === 'instructions')
    return { kind, title: 'How to Use This Book', text: 'Color each drawing however you like.' };
  if (kind === 'about') return { kind, title: 'About', text: '' };
  if (kind === 'notes') return { kind, title: 'Notes' };
  return { kind };
}

function starter(): ColoringComposition {
  return {
    front_matter: [{ kind: 'title_page' }, { kind: 'copyright_page', text: '' }],
    artwork: { start: 'recto' },
    back_matter: [],
    page_numbers: {
      scheme: 'continuous',
      show_front_matter: false,
      show_artwork: true,
      show_back_matter: true,
    },
  };
}

function describe(page: ColoringPlanPage): string {
  if (page.kind === 'coloring')
    return `Coloring page: ${page.artwork?.title || page.artwork?.id || 'drawing'}`;
  if (page.kind === 'divider') return `Section divider: ${page.divider?.title ?? ''}`;
  if (page.kind === 'blank') return 'Blank page (added automatically)';
  return MATTER_NAMES[page.kind] ?? page.kind;
}

export function ColoringPages({ d }: { d: Draft }) {
  const source = d.draft;
  const coloring = source.coloring!;
  const composition = source.composition as unknown as ColoringComposition | undefined;
  const issues = d.issues;
  const [plan, setPlan] = useState<ColoringPlanResult>();
  const [planIssues, setPlanIssues] = useState<Issue[]>([]);
  const [planError, setPlanError] = useState<Error>();
  const [checking, setChecking] = useState(false);
  const [status, setStatus] = useState<InteriorStatus>();
  const [announce, setAnnounce] = useState('');
  const [dragging, setDragging] = useState<number>();
  const [adding, setAdding] = useState(coloring.artwork[0]?.id ?? '');
  const history = useRef<Source[]>([]);
  const [undoCount, setUndoCount] = useState(0);
  const sequence = useRef(0);
  // Python runs one preparation at a time; a busy answer is retried, a few times.
  const [retry, setRetry] = useState(0);
  const retries = useRef(0);
  const api = `/api/projects/${encodeURIComponent(d.key)}`;
  const base = `/books/${encodeURIComponent(d.key)}`;

  // A save, reload or revert starts a fresh undo history.
  useEffect(() => {
    history.current = [];
    setUndoCount(0);
  }, [d.epoch]);

  // Python plans every draft (debounced); only the latest answer is shown, so a slow
  // answer never replaces a newer draft's plan.
  useEffect(() => {
    if (!composition) return;
    const number = ++sequence.current;
    const controller = new AbortController();
    setChecking(true);
    const timer = setTimeout(() => {
      request<ColoringPlanResult>(`${api}/draft/plan`, controller.signal, { source })
        .then((data) => {
          if (controller.signal.aborted || number !== sequence.current) return;
          if (!data.plan?.pages || !data.verification)
            throw new ApiError('Studio received an incomplete plan.', 'malformed_response');
          retries.current = 0;
          setPlan(data);
          setPlanIssues([]);
          setPlanError(undefined);
        })
        .catch((err: Error) => {
          if (controller.signal.aborted || number !== sequence.current) return;
          if (err instanceof ApiError && err.code === 'generation_busy' && retries.current < 20) {
            retries.current += 1;
            setTimeout(() => setRetry((n) => n + 1), 1500);
            return;
          }
          setPlan(undefined);
          setPlanError(err);
          setPlanIssues(err instanceof ApiError ? err.issues : []);
        })
        .finally(() => {
          if (number === sequence.current) setChecking(false);
        });
    }, 400);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // The draft source is the whole input of the plan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, JSON.stringify(source), retry]);

  // The built interior's state for the saved source: rebuilt in Print proof.
  useEffect(() => {
    const controller = new AbortController();
    request<InteriorStatus>(`${api}/interior`, controller.signal)
      .then((data) => !controller.signal.aborted && setStatus(data))
      .catch(() => !controller.signal.aborted && setStatus(undefined));
    return () => controller.abort();
  }, [api, d.saved.revision]);

  const change = (next: Source, said?: string) => {
    history.current = [...history.current.slice(-49), source];
    setUndoCount(history.current.length);
    d.change(next);
    if (said) setAnnounce(said);
  };
  const undo = () => {
    const previous = history.current.pop();
    setUndoCount(history.current.length);
    if (previous) {
      d.change(previous);
      setAnnounce('Undid the last change.');
    }
  };
  const setPages = (pages: Entry[], said?: string) =>
    change({ ...source, coloring: { ...coloring, pages } } as Source, said);
  const setLayout = (layout: Partial<ColoringSource['layout']>) =>
    change({
      ...source,
      coloring: { ...coloring, layout: { ...coloring.layout, ...layout } },
    } as Source);
  const setComposition = (next: ColoringComposition) =>
    change({ ...source, composition: next } as unknown as Source);

  if (!composition)
    return (
      <div className="editor composer">
        <DraftToolbar d={d} title="Pages" jump={{ href: `${base}/print`, label: 'Print proof' }} />
        <section className="coloring-start">
          <h3>Compose this coloring book</h3>
          <p>
            A composition adds front matter (title and copyright pages), page numbers and the option
            to start drawings on right-hand pages. Nothing is saved until you choose Save changes.
          </p>
          <button type="button" className="primary" onClick={() => setComposition(starter())}>
            Start the composition
          </button>
        </section>
      </div>
    );

  const titles = new Map(coloring.artwork.map((a) => [a.id, a.title || a.id]));
  const uses = new Map<string, number>();
  for (const entry of coloring.pages)
    if ('artwork' in entry) uses.set(entry.artwork, (uses.get(entry.artwork) ?? 0) + 1);
  // Physical pages of each entry, read from Python's plan in source order.
  const physical: number[] = [];
  for (const page of plan?.plan.pages ?? [])
    if (page.section === 'artwork' && page.kind !== 'blank') physical.push(page.index);
  const name = (entry: Entry) =>
    'artwork' in entry
      ? (titles.get(entry.artwork) ?? entry.artwork)
      : `Divider: ${entry.divider.title}`;

  const moveEntry = (from: number, to: number) => {
    if (to < 0 || to >= coloring.pages.length || from === to) return;
    const pages = [...coloring.pages];
    const [item] = pages.splice(from, 1);
    pages.splice(to, 0, item);
    setPages(pages, `Moved ${name(item)} to position ${to + 1} of ${pages.length}.`);
  };
  const drop = (event: DragEvent, to: number) => {
    event.preventDefault();
    if (dragging !== undefined) moveEntry(dragging, to);
    setDragging(undefined);
  };
  const stats = plan?.plan.statistics;
  const pageIssues = [
    ...planIssues,
    ...(plan?.verification.valid ? [] : (plan?.verification.issues ?? [])),
  ];
  const findings = status?.report?.findings ?? [];
  const count = (severity: string) => findings.filter((f) => f.severity === severity).length;

  return (
    <div className="editor composer coloring-pages">
      <DraftToolbar d={d} title="Pages" jump={{ href: `${base}/print`, label: 'Print proof' }} />
      <p role="status" aria-live="polite" className="sr-only">
        {announce}
      </p>
      <div className="coloring-pages-layout">
        <div className="coloring-pages-editor">
          <section aria-labelledby="pages-order">
            <div className="section-heading">
              <div>
                <h3 id="pages-order">Drawings and dividers</h3>
                <p className="small muted">
                  In printing order. Drag a row, or use Up and Down. Blank pages are never listed
                  here: Python adds them where the layout needs one.
                </p>
              </div>
              <button type="button" disabled={!undoCount} onClick={undo}>
                Undo
              </button>
            </div>
            <FieldErrors id="coloring.pages" issues={matchIssues(issues, 'coloring.pages')} />
            {coloring.pages.length === 0 && (
              <p className="muted">No pages yet. Add a drawing below.</p>
            )}
            <ol className="page-order" aria-label="Drawings and dividers in printing order">
              {coloring.pages.map((entry, i) => {
                const label = name(entry);
                const page = physical[i];
                const at = `coloring.pages.${i}`;
                return (
                  <li
                    key={i}
                    className={dragging === i ? 'dragging' : undefined}
                    draggable
                    onDragStart={(e) => {
                      setDragging(i);
                      e.dataTransfer.effectAllowed = 'move';
                    }}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => drop(e, i)}
                    onDragEnd={() => setDragging(undefined)}
                  >
                    <span className="drag-handle" aria-hidden="true">
                      ⋮⋮
                    </span>
                    {'artwork' in entry ? (
                      <img
                        className="page-thumb"
                        alt=""
                        loading="lazy"
                        src={`${api}/coloring/thumbnail?artwork=${encodeURIComponent(entry.artwork)}`}
                      />
                    ) : (
                      <span className="page-thumb divider-thumb" aria-hidden="true">
                        §
                      </span>
                    )}
                    <div className="page-order-body">
                      <strong>{label}</strong>
                      <span className="small muted">
                        {page
                          ? `PDF page ${page} · ${page % 2 ? 'right-hand' : 'left-hand'}`
                          : 'Page not planned yet'}
                        {'artwork' in entry && (uses.get(entry.artwork) ?? 0) > 1 && (
                          <> · used {uses.get(entry.artwork)} times (intended?)</>
                        )}
                      </span>
                      {'divider' in entry && (
                        <div className="field-pair">
                          <Field
                            label="Divider title"
                            path={`${at}.divider.title`}
                            value={entry.divider.title}
                            issues={issues}
                            onChange={(title) =>
                              setPages(
                                coloring.pages.map((x, j) =>
                                  j === i ? { divider: { ...entry.divider, title } } : x,
                                ),
                              )
                            }
                          />
                          <Field
                            label="Description (optional)"
                            path={`${at}.divider.text`}
                            value={entry.divider.text ?? ''}
                            issues={issues}
                            multiline
                            onChange={(text) =>
                              setPages(
                                coloring.pages.map((x, j) =>
                                  j === i
                                    ? {
                                        divider: text
                                          ? { title: entry.divider.title, text }
                                          : { title: entry.divider.title },
                                      }
                                    : x,
                                ),
                              )
                            }
                          />
                        </div>
                      )}
                      <FieldErrors
                        id={at}
                        issues={issues.filter((x) => x.path === at || x.path === `${at}.artwork`)}
                      />
                    </div>
                    <div className="page-order-actions">
                      <button
                        type="button"
                        aria-label={`Move ${label} up`}
                        disabled={i === 0}
                        onClick={() => moveEntry(i, i - 1)}
                      >
                        Up
                      </button>
                      <button
                        type="button"
                        aria-label={`Move ${label} down`}
                        disabled={i === coloring.pages.length - 1}
                        onClick={() => moveEntry(i, i + 1)}
                      >
                        Down
                      </button>
                      {'artwork' in entry && (
                        <button
                          type="button"
                          aria-label={`Use ${label} again after this page`}
                          onClick={() => {
                            const pages = [...coloring.pages];
                            pages.splice(i + 1, 0, { artwork: entry.artwork });
                            setPages(pages, `Added ${label} again as page entry ${i + 2}.`);
                          }}
                        >
                          Repeat
                        </button>
                      )}
                      <button
                        type="button"
                        aria-label={`Remove ${label} from the book`}
                        onClick={() =>
                          setPages(
                            coloring.pages.filter((_, j) => j !== i),
                            `Removed ${label}. The drawing stays in the artwork library.`,
                          )
                        }
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                );
              })}
            </ol>
            <div className="add-entry">
              {coloring.artwork.length > 0 ? (
                <>
                  <SelectField
                    label="Drawing to add"
                    path="add-drawing"
                    value={adding}
                    options={coloring.artwork.map((a) => [a.id, a.title || a.id])}
                    issues={[]}
                    onChange={setAdding}
                  />
                  <button
                    type="button"
                    disabled={!adding}
                    onClick={() =>
                      setPages(
                        [...coloring.pages, { artwork: adding }],
                        `Added ${titles.get(adding) ?? adding} at the end.`,
                      )
                    }
                  >
                    Add drawing at the end
                  </button>
                </>
              ) : (
                <p className="small muted">
                  Import drawings in <a href={`${base}/artwork`}>Artwork</a> first.
                </p>
              )}
              <button
                type="button"
                onClick={() =>
                  setPages(
                    [...coloring.pages, { divider: { title: 'New section' } }],
                    'Added a section divider at the end.',
                  )
                }
              >
                Add section divider
              </button>
            </div>
          </section>

          <section aria-labelledby="pages-front">
            <h3 id="pages-front">Book details and front matter</h3>
            <Field
              label="Title"
              path="book.title"
              value={source.book.title}
              issues={issues}
              onChange={(title) => change({ ...source, book: { ...source.book, title } })}
            />
            <Field
              label="Language"
              path="book.language"
              value={source.book.language}
              issues={issues}
              hint="A language tag such as en or fr-CA; Python checks it against KDP's paperback languages in Publishing."
              onChange={(language) => change({ ...source, book: { ...source.book, language } })}
            />
            <MatterList
              items={composition.front_matter}
              kinds={['title_page', 'copyright_page', 'instructions']}
              path="composition.front_matter"
              issues={issues}
              draft={source}
              make={coloringMatter}
              titleNote="edit it above"
              onBook={(book) => change({ ...source, book })}
              onChange={(front_matter) => setComposition({ ...composition, front_matter })}
            />
          </section>

          <section aria-labelledby="pages-back">
            <h3 id="pages-back">Back matter</h3>
            <MatterList
              items={composition.back_matter}
              kinds={['about', 'notes']}
              path="composition.back_matter"
              issues={issues}
              draft={source}
              make={coloringMatter}
              titleNote="edit it above"
              onBook={(book) => change({ ...source, book })}
              onChange={(back_matter) => setComposition({ ...composition, back_matter })}
            />
          </section>

          <section aria-labelledby="pages-layout">
            <h3 id="pages-layout">Layout and page numbers</h3>
            <label className="check">
              <input
                type="checkbox"
                checked={coloring.layout.blank_reverse}
                onChange={(e) => setLayout({ blank_reverse: e.target.checked })}
              />
              <span>
                Blank backs: print each drawing on a right-hand page with a blank page behind it
              </span>
            </label>
            <SelectField
              label="Page border"
              path="coloring.layout.border"
              value={coloring.layout.border}
              options={[
                ['none', 'No border'],
                ['thin', 'Thin rule'],
                ['double', 'Double rule'],
              ]}
              issues={issues}
              onChange={(border) => setLayout({ border })}
            />
            <SelectField
              label="First drawing starts on"
              path="composition.artwork.start"
              value={composition.artwork.start}
              options={[
                ['recto', 'A right-hand (recto) page'],
                ['any', 'The next page'],
              ]}
              issues={issues}
              onChange={(start) => setComposition({ ...composition, artwork: { start } })}
            />
            <SelectField
              label="Numbering"
              path="composition.page_numbers.scheme"
              value={composition.page_numbers.scheme}
              options={[
                ['continuous', 'Continuous arabic numbers'],
                ['roman_front_matter', 'Roman numerals for front matter'],
              ]}
              issues={issues}
              onChange={(scheme) =>
                setComposition({
                  ...composition,
                  page_numbers: { ...composition.page_numbers, scheme },
                })
              }
            />
            <fieldset className="choice-group">
              <legend>Print page numbers on</legend>
              {(
                [
                  ['show_front_matter', 'Front matter pages'],
                  ['show_artwork', 'Coloring pages'],
                  ['show_back_matter', 'Back matter pages'],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={composition.page_numbers[key]}
                    onChange={(e) =>
                      setComposition({
                        ...composition,
                        page_numbers: { ...composition.page_numbers, [key]: e.target.checked },
                      })
                    }
                  />
                  <span>{label}</span>
                </label>
              ))}
              <small className="muted">Blank and divider pages never print a number.</small>
            </fieldset>
          </section>
        </div>

        <aside className="coloring-pages-preview" aria-labelledby="pages-preview">
          <div className="section-heading">
            <div>
              <h3 id="pages-preview">Page preview</h3>
              <p className="small muted">
                Python&apos;s plan of this draft. Outlines show the live area and the art box; Print
                proof shows the built pages.
              </p>
            </div>
            {checking ? (
              <Status tone="neutral">Planning…</Status>
            ) : plan?.plan.complete && plan.verification.valid ? (
              <Status tone="pass">Plan verified</Status>
            ) : (
              <Status tone="fail">Incomplete</Status>
            )}
          </div>
          <InteriorState
            status={status}
            base={base}
            dirty={d.dirty}
            counts={[count('error'), count('warning'), count('info')]}
          />
          {planError && !planIssues.length && <p className="notice error">{planError.message}</p>}
          {pageIssues.length > 0 && <Issues issues={pageIssues} />}
          {plan?.artwork.failures.map((f) => (
            <p key={f.id} className="notice error">
              {f.id}: {f.message}
            </p>
          ))}
          {stats && (
            <dl className="plan-stats">
              <div>
                <dt>Physical pages</dt>
                <dd>{plan.plan.pages.length}</dd>
              </div>
              <div>
                <dt>Coloring pages</dt>
                <dd>{stats.artwork_pages ?? 0}</dd>
              </div>
              <div>
                <dt>Blank pages (automatic)</dt>
                <dd>{stats.blank_pages ?? 0}</dd>
              </div>
              <div>
                <dt>Dividers</dt>
                <dd>{stats.divider_pages ?? 0}</dd>
              </div>
            </dl>
          )}
          {plan && <Spreads plan={plan} api={api} />}
        </aside>
      </div>
    </div>
  );
}

function InteriorState({
  status,
  base,
  dirty,
  counts,
}: {
  status?: InteriorStatus;
  base: string;
  dirty: boolean;
  counts: [number, number, number];
}) {
  if (!status) return null;
  const [blocking, warnings, manual] = counts;
  const text =
    status.state === 'missing'
      ? 'No interior has been built yet.'
      : status.state === 'stale'
        ? 'The built interior is out of date: the saved pages changed after it was built.'
        : status.state === 'current'
          ? `The built interior matches the saved source: ${blocking} blocking, ${warnings} warnings, ${manual} manual review.`
          : 'The built interior does not match its manifest.';
  return (
    <div className={`print-state ${status.state}`}>
      <p className="small">
        {text}
        {dirty && ' Unsaved changes are not built.'} <a href={`${base}/print`}>Open Print proof</a>
      </p>
    </div>
  );
}

function Spreads({ plan, api }: { plan: ColoringPlanResult; api: string }) {
  const pages = plan.plan.pages;
  // Page 1 is a right-hand page alone; then left-right spreads.
  const spreads: ColoringPlanPage[][] = [[pages[0]].filter(Boolean)];
  for (let i = 1; i < pages.length; i += 2) spreads.push(pages.slice(i, i + 2));
  return (
    <ol className="page-spreads" aria-label="Physical pages in order">
      {spreads.map((spread, i) => (
        <li key={i} className={i === 0 ? 'spread first' : 'spread'}>
          {spread.map((page) => (
            <PageCard key={page.index} page={page} plan={plan} api={api} />
          ))}
        </li>
      ))}
    </ol>
  );
}

function PageCard({
  page,
  plan,
  api,
}: {
  page: ColoringPlanPage;
  plan: ColoringPlanResult;
  api: string;
}) {
  const g = plan.geometry;
  const side = g.sides[page.side];
  const blank = page.kind === 'blank';
  const reason = page.blank ? (BLANK_REASONS[page.blank.reason] ?? page.blank.reason) : null;
  // PDF points have their origin at the bottom-left; SVG at the top-left.
  const rect = (b: { x: number; y: number; width: number; height: number }) => ({
    x: b.x,
    y: g.trim.height - b.y - b.height,
    width: b.width,
    height: b.height,
  });
  return (
    <figure className={`page-card ${page.side}${blank ? ' automatic' : ''}`}>
      <svg viewBox={`0 0 ${g.trim.width} ${g.trim.height}`} role="img" aria-label={describe(page)}>
        <rect className="trim" x="0" y="0" width={g.trim.width} height={g.trim.height} />
        <rect className="live" {...rect(side.live)} />
        {page.kind === 'coloring' && page.artwork && (
          <>
            <rect className="art" {...rect(side.art)} />
            <image
              href={`${api}/coloring/thumbnail?artwork=${encodeURIComponent(page.artwork.id)}`}
              {...rect(side.art)}
              preserveAspectRatio="xMidYMid meet"
            />
          </>
        )}
        {page.kind === 'divider' && (
          <text x={g.trim.width / 2} y={g.trim.height / 2} textAnchor="middle" className="label">
            {page.divider?.title}
          </text>
        )}
        {page.matter && page.kind !== 'blank' && (
          <text x={g.trim.width / 2} y={g.trim.height / 3} textAnchor="middle" className="label">
            {MATTER_NAMES[page.kind] ?? page.kind}
          </text>
        )}
      </svg>
      <figcaption>
        <span>
          <strong>{page.index}</strong> {page.side === 'recto' ? 'Right' : 'Left'}
          {page.number.displayed && <> · prints “{page.number.label}”</>}
        </span>
        <span className="small muted">{blank ? reason : describe(page)}</span>
      </figcaption>
    </figure>
  );
}
