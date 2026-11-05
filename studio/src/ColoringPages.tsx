import { useEffect, useRef, useState, type DragEvent } from 'react';
import { ApiError, request } from './api';
import { MatterList } from './Composer';
import { DraftToolbar, type Draft } from './draft';
import { Field, FieldErrors, SelectField, matchIssues, type Source } from './editor-fields';
import { useHistory, useUndoShortcuts } from './history';
import type {
  BleedCrop,
  ColoringPlanPage,
  ColoringPlanResult,
  ColoringSource,
  InteriorStatus,
  Issue,
  MatterItem,
  Placement,
} from './types';
import { Issues, Status } from './ui';
import { PageViewport } from './viewport';
import { CSS_PX_PER_PT, svgRect } from './zoom';

// Pages: the order of drawings and section dividers, front and back matter, blank
// backs, borders, placement and page numbers. The browser edits the authored source
// only; which physical page each entry lands on, every blank page, every number and
// where each drawing prints come from Python's verified plan, and the built pages
// from Print proof.

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

const CENTRED: Placement = { scale: 1, x: 0, y: 0 };
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

/** A placement equal to the centred default is written as no placement at all; fill
 * is written only when chosen (Python normalizes the same way). */
function withPlacement(entry: { artwork: string }, placement: Placement): Entry {
  const fill = placement.fit === 'fill';
  const rounded: Placement = {
    scale: Math.round(placement.scale * 100) / 100,
    x: Math.round(placement.x * 100) / 100,
    y: Math.round(placement.y * 100) / 100,
    ...(fill ? { fit: 'fill' as const } : {}),
  };
  return !fill && rounded.scale === 1 && rounded.x === 0 && rounded.y === 0
    ? { artwork: entry.artwork }
    : { artwork: entry.artwork, placement: rounded };
}

type Geometry = ColoringPlanResult['geometry'];
type Side = Geometry['sides']['recto'];

/** The PDF page's size: the trim plus bleed on a full-bleed profile, else the trim. */
function mediaOf(g: Geometry) {
  return g.media ?? g.trim;
}

/** The side's trim box in page coordinates (at the origin without bleed). */
function trimOf(g: Geometry, side: Side) {
  return side.trim_box ?? { x: 0, y: 0, width: g.trim.width, height: g.trim.height };
}

/** Python's crop measure, as a sentence; numbers only from Python. */
function cropSummary(crop: BleedCrop | null | undefined) {
  if (!crop) return null;
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
  return `Of the drawing's line work, ${pct(crop.hidden)} is cut off the page, ${pct(crop.trimmed)} prints only in the bleed (cut at trimming) and ${pct(crop.unsafe)} lies outside the safe area.`;
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
  const [selected, setSelected] = useState(0);
  const [adding, setAdding] = useState(coloring.artwork[0]?.id ?? '');
  // Undo and redo cover this project's unsaved edits; a save, reload or revert
  // (a new epoch) starts afresh.
  const history = useHistory<Source>(source, d.change, d.epoch);
  useUndoShortcuts(!d.busy, history.undo, history.redo);
  const sequence = useRef(0);
  // Python runs one preparation at a time; a busy answer is retried, a few times.
  const [retry, setRetry] = useState(0);
  const retries = useRef(0);
  const api = `/api/projects/${encodeURIComponent(d.key)}`;
  const base = `/books/${encodeURIComponent(d.key)}`;

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

  const change = (next: Source, said?: string, group?: string) => {
    history.edit(next, group);
    if (said) setAnnounce(said);
  };
  const undo = () => history.undo() && setAnnounce('Undid the last change.');
  const redo = () => history.redo() && setAnnounce('Redid the change.');
  const setPages = (pages: Entry[], said?: string, group?: string) =>
    change({ ...source, coloring: { ...coloring, pages } } as Source, said, group);
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
  const current = Math.min(selected, Math.max(coloring.pages.length - 1, 0));
  const chosen = coloring.pages[current] as Entry | undefined;

  const moveEntry = (from: number, to: number) => {
    if (to < 0 || to >= coloring.pages.length || from === to) return;
    const pages = [...coloring.pages];
    const [item] = pages.splice(from, 1);
    pages.splice(to, 0, item);
    if (selected === from) setSelected(to);
    setPages(pages, `Moved ${name(item)} to position ${to + 1} of ${pages.length}.`);
  };
  const insertAfter = (at: number, entry: Entry, said: string) => {
    const pages = [...coloring.pages];
    pages.splice(at + 1, 0, entry);
    setSelected(at + 1);
    setPages(pages, said);
  };
  const removeAt = (at: number) => {
    const entry = coloring.pages[at];
    setPages(
      coloring.pages.filter((_, j) => j !== at),
      'artwork' in entry
        ? `Removed ${name(entry)}. The drawing stays in the artwork library.`
        : `Removed ${name(entry)}.`,
    );
    if (selected >= at && selected > 0) setSelected(selected - 1);
  };
  const replaceAt = (at: number, entry: Entry, said?: string, group?: string) =>
    setPages(
      coloring.pages.map((x, j) => (j === at ? entry : x)),
      said,
      group,
    );
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
                  In printing order. Select a page to design it; drag a row, or use Up and Down.
                  Blank pages are never listed here: Python adds them where the layout needs one.
                </p>
              </div>
              <div className="history-actions" role="group" aria-label="Edit history">
                <button
                  type="button"
                  disabled={!history.canUndo}
                  onClick={undo}
                  aria-keyshortcuts="Control+Z"
                  title="Undo (Ctrl+Z)"
                >
                  Undo
                </button>
                <button
                  type="button"
                  disabled={!history.canRedo}
                  onClick={redo}
                  aria-keyshortcuts="Control+Shift+Z Control+Y"
                  title="Redo (Ctrl+Shift+Z)"
                >
                  Redo
                </button>
              </div>
            </div>
            <FieldErrors id="coloring.pages" issues={matchIssues(issues, 'coloring.pages')} />
            {coloring.pages.length === 0 && (
              <p className="muted">
                No pages yet.{' '}
                {coloring.artwork.length
                  ? 'Add a drawing below.'
                  : 'Import drawings in Artwork first, then add them here.'}
              </p>
            )}
            <ol className="page-order" aria-label="Drawings and dividers in printing order">
              {coloring.pages.map((entry, i) => {
                const label = name(entry);
                const page = physical[i];
                const at = `coloring.pages.${i}`;
                const placed = 'artwork' in entry && entry.placement;
                return (
                  <li
                    key={i}
                    className={[
                      dragging === i ? 'dragging' : '',
                      current === i ? 'selected' : '',
                    ].join(' ')}
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
                        {placed && <> · placed {Math.round(placed.scale * 100)}%</>}
                      </span>
                      {'divider' in entry && (
                        <div className="field-pair">
                          <Field
                            label="Divider title"
                            path={`${at}.divider.title`}
                            value={entry.divider.title}
                            issues={issues}
                            onChange={(title) =>
                              replaceAt(
                                i,
                                { divider: { ...entry.divider, title } },
                                undefined,
                                `${at}.title`,
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
                              replaceAt(
                                i,
                                {
                                  divider: text
                                    ? { title: entry.divider.title, text }
                                    : { title: entry.divider.title },
                                },
                                undefined,
                                `${at}.text`,
                              )
                            }
                          />
                        </div>
                      )}
                      <FieldErrors
                        id={at}
                        issues={issues.filter(
                          (x) => x.path === at || x.path.startsWith(`${at}.artwork`),
                        )}
                      />
                    </div>
                    <div className="page-order-actions">
                      <button
                        type="button"
                        aria-pressed={current === i}
                        aria-label={`Design ${label}`}
                        onClick={() => setSelected(i)}
                      >
                        Design
                      </button>
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
                          onClick={() =>
                            insertAfter(
                              i,
                              { artwork: entry.artwork },
                              `Added ${label} again as page entry ${i + 2}.`,
                            )
                          }
                        >
                          Repeat
                        </button>
                      )}
                      <button
                        type="button"
                        aria-label={`Remove ${label} from the book`}
                        onClick={() => removeAt(i)}
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
                    onClick={() => {
                      setSelected(coloring.pages.length);
                      setPages(
                        [...coloring.pages, { artwork: adding }],
                        `Added ${titles.get(adding) ?? adding} at the end.`,
                      );
                    }}
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
            <h3 id="pages-front">Front matter</h3>
            <p className="small muted">
              Title, subtitle, author and language are book details:{' '}
              <a href={`${base}/settings`}>edit them in Settings</a>.
            </p>
            <MatterList
              items={composition.front_matter}
              kinds={['title_page', 'copyright_page', 'instructions']}
              path="composition.front_matter"
              issues={issues}
              draft={source}
              make={coloringMatter}
              settings={`${base}/settings`}
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
              settings={`${base}/settings`}
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
          {chosen && (
            <PageDesigner
              key={current}
              entry={chosen}
              index={current}
              plan={plan}
              physicalPage={physical[current]}
              api={api}
              artwork={coloring.artwork.map((a) => [a.id, a.title || a.id])}
              checking={checking}
              name={name(chosen)}
              onReplace={(entry, said, group) => replaceAt(current, entry, said, group)}
              onDuplicate={() =>
                insertAfter(
                  current,
                  structuredClone(chosen),
                  `Duplicated ${name(chosen)} as page entry ${current + 2}.`,
                )
              }
              onDivider={() =>
                insertAfter(
                  current,
                  { divider: { title: 'New section' } },
                  `Inserted a section divider after ${name(chosen)}.`,
                )
              }
            />
          )}
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
          {plan && (
            <Spreads
              plan={plan}
              api={api}
              selectedPage={physical[current]}
              onSelect={(page) => {
                const at = physical.indexOf(page);
                if (at >= 0) setSelected(at);
              }}
            />
          )}
        </aside>
      </div>
    </div>
  );
}

function PageDesigner({
  entry,
  index,
  plan,
  physicalPage,
  api,
  artwork,
  checking,
  name,
  onReplace,
  onDuplicate,
  onDivider,
}: {
  entry: Entry;
  index: number;
  plan?: ColoringPlanResult;
  physicalPage?: number;
  api: string;
  artwork: [string, string][];
  checking: boolean;
  name: string;
  onReplace: (entry: Entry, said?: string, group?: string) => void;
  onDuplicate: () => void;
  onDivider: () => void;
}) {
  const page = plan?.plan.pages.find((p) => p.index === physicalPage);
  const placed = physicalPage ? plan?.placements?.[String(physicalPage)] : undefined;
  const placement = ('artwork' in entry && entry.placement) || CENTRED;
  const set = (patch: Partial<Placement>, group: string) =>
    'artwork' in entry &&
    onReplace(withPlacement(entry, { ...placement, ...patch }), undefined, group);
  const g = plan?.geometry;
  const fill = placement.fit === 'fill';
  const media = g ? mediaOf(g) : undefined;
  return (
    <section className="page-designer" aria-labelledby="designer-heading">
      <h4 id="designer-heading">
        Designing entry {index + 1}: {name}
      </h4>
      <p className="small">
        {page ? (
          <>
            PDF page <strong>{page.index}</strong> ·{' '}
            {page.side === 'recto' ? 'right-hand (recto)' : 'left-hand (verso)'} ·{' '}
            {page.number.displayed ? `prints “${page.number.label}”` : 'no printed number'}
          </>
        ) : (
          'Not planned yet.'
        )}
      </p>
      {g && page && media && (
        <PageViewport
          label="Selected page"
          page={{ width: media.width * CSS_PX_PER_PT, height: media.height * CSS_PX_PER_PT }}
        >
          {(scale) => {
            const side = g.sides[page.side];
            const trim = trimOf(g, side);
            const r = (b: { x: number; y: number; width: number; height: number }) =>
              svgRect(b, media.height);
            const drawing = placed?.fit === 'fill' ? placed.drawing : placed?.box;
            // The gutter: from the binding edge of the trim to the fill area (bleed only).
            const gutter =
              g.bleed && side.fill
                ? page.side === 'recto'
                  ? { x: trim.x, y: trim.y, width: side.fill.x - trim.x, height: trim.height }
                  : {
                      x: side.fill.x + side.fill.width,
                      y: trim.y,
                      width: trim.x + trim.width - side.fill.x - side.fill.width,
                      height: trim.height,
                    }
                : null;
            return (
              <svg
                width={media.width * CSS_PX_PER_PT * scale}
                height={media.height * CSS_PX_PER_PT * scale}
                viewBox={`0 0 ${media.width} ${media.height}`}
                role="img"
                aria-label={`${describe(page)}, with the ${g.bleed ? 'bleed, trim, safe area, gutter, ' : ''}live area${placed ? ', art box and drawing' : ''} outlined`}
                className={`designer-page ${page.side}`}
              >
                {g.bleed && (
                  <rect
                    className="bleed-area"
                    x="0"
                    y="0"
                    width={media.width}
                    height={media.height}
                  />
                )}
                <rect className="trim" {...r(trim)} />
                {gutter && <rect className="gutter" {...r(gutter)} />}
                <rect className="live" {...r(side.live)} />
                {g.bleed && side.safe && <rect className="safe" {...r(side.safe)} />}
                {page.kind === 'coloring' && !fill && <rect className="art" {...r(side.art)} />}
                {page.kind === 'coloring' && placed && page.artwork && drawing && (
                  <>
                    <line
                      className="guide"
                      x1={trim.x + trim.width / 2}
                      x2={trim.x + trim.width / 2}
                      y1="0"
                      y2={media.height}
                    />
                    {placed.fit === 'fill' && placed.box && (
                      <>
                        <clipPath id="designer-fill-clip">
                          <rect {...r(placed.box)} />
                        </clipPath>
                        {/* The whole drawing, faint: what the page crops off. */}
                        <image
                          className="crop-ghost"
                          href={`${api}/coloring/thumbnail?artwork=${encodeURIComponent(page.artwork.id)}`}
                          {...r(drawing)}
                          preserveAspectRatio="none"
                        />
                      </>
                    )}
                    <image
                      href={`${api}/coloring/thumbnail?artwork=${encodeURIComponent(page.artwork.id)}`}
                      {...r(drawing)}
                      preserveAspectRatio="none"
                      clipPath={placed.fit === 'fill' ? 'url(#designer-fill-clip)' : undefined}
                    />
                    {g.bleed && placed.fit === 'fill' && (
                      // Hatch what trimming cuts away: the page beyond the trim.
                      <path
                        className="trimmed-band"
                        fillRule="evenodd"
                        d={`M0 0h${media.width}v${media.height}h${-media.width}z M${trim.x} ${media.height - trim.y - trim.height}h${trim.width}v${trim.height}h${-trim.width}z`}
                      />
                    )}
                    <rect className="placed" {...r(placed.box ?? drawing)} />
                  </>
                )}
                {page.kind === 'divider' && (
                  <text
                    x={trim.x + trim.width / 2}
                    y={media.height / 2}
                    textAnchor="middle"
                    className="label"
                  >
                    {page.divider?.title}
                  </text>
                )}
                <text
                  x={page.side === 'recto' ? media.width - 18 : 18}
                  y="24"
                  textAnchor={page.side === 'recto' ? 'end' : 'start'}
                  className="side-label"
                >
                  {page.side === 'recto' ? 'Recto (right)' : 'Verso (left)'}
                </text>
              </svg>
            );
          }}
        </PageViewport>
      )}
      {g?.bleed && page && (
        <ul className="designer-legend small" aria-label="What the outlines show">
          <li>
            <span className="key bleed" aria-hidden="true" /> Bleed: printed, then cut away
          </li>
          <li>
            <span className="key trim" aria-hidden="true" /> Trim: the finished page edge
          </li>
          <li>
            <span className="key safe" aria-hidden="true" /> Safe area: KDP margins for this page
            count
          </li>
          <li>
            <span className="key gutter" aria-hidden="true" /> Gutter: the binding side, kept clear
          </li>
        </ul>
      )}
      {'artwork' in entry && (
        <div className="designer-controls">
          <SelectField
            label="Drawing on this page"
            path={`coloring.pages.${index}.artwork`}
            value={entry.artwork}
            options={artwork}
            issues={[]}
            onChange={(id) =>
              onReplace(
                entry.placement ? { artwork: id, placement: entry.placement } : { artwork: id },
                `Replaced the drawing on entry ${index + 1}.`,
              )
            }
          />
          <fieldset className="placement-fit">
            <legend>How the drawing sits on the page</legend>
            <label>
              <input
                type="radio"
                name={`fit-${index}`}
                checked={!fill}
                onChange={() =>
                  onReplace(
                    { artwork: entry.artwork },
                    'Fit inside the page: whole drawing, centred.',
                  )
                }
              />{' '}
              Fit inside the page (the whole drawing, never cropped)
            </label>
            <label>
              <input
                type="radio"
                name={`fit-${index}`}
                checked={fill}
                disabled={!g?.bleed}
                aria-describedby={`fill-note-${index}`}
                onChange={() =>
                  onReplace(
                    withPlacement(entry, { scale: 1, x: 0, y: 0, fit: 'fill' }),
                    'Fill the bleed area: the drawing runs past the trim; what falls outside is cropped.',
                  )
                }
              />{' '}
              Fill the bleed area (runs past the trim; the crop is shown)
            </label>
            <p className="small muted" id={`fill-note-${index}`}>
              {g?.bleed
                ? 'Filling covers the page to the bleed edge on the top, bottom and outside, and stops at the inside margin so nothing disappears into the binding.'
                : 'Filling needs a full-bleed print profile: choose one in Settings (Print). This profile has no bleed.'}
            </p>
          </fieldset>
          <fieldset className="placement-fields">
            <legend>{fill ? 'Crop and zoom' : 'Placement in the art box'}</legend>
            <Slider
              label={fill ? 'Zoom' : 'Size'}
              value={placement.scale}
              min={fill ? 1 : 0.5}
              max={fill ? 3 : 1}
              format={(v) =>
                fill
                  ? `${Math.round(v * 100)}% of the size that covers the page`
                  : `${Math.round(v * 100)}% of the full fit`
              }
              onChange={(scale) => set({ scale }, `placement.scale.${index}`)}
            />
            <Slider
              label="Horizontal position"
              value={placement.x}
              min={-1}
              max={1}
              format={(v) =>
                v === 0
                  ? 'centred'
                  : fill
                    ? v < 0
                      ? 'keeps the left edge'
                      : 'keeps the right edge'
                    : v < 0
                      ? 'toward the left'
                      : 'toward the right'
              }
              onChange={(x) => set({ x }, `placement.x.${index}`)}
            />
            <Slider
              label="Vertical position"
              value={placement.y}
              min={-1}
              max={1}
              format={(v) =>
                v === 0
                  ? 'centred'
                  : fill
                    ? v < 0
                      ? 'keeps the bottom edge'
                      : 'keeps the top edge'
                    : v < 0
                      ? 'toward the bottom'
                      : 'toward the top'
              }
              onChange={(y) => set({ y }, `placement.y.${index}`)}
            />
            <div className="button-row">
              <button
                type="button"
                disabled={placement.x === 0 && placement.y === 0}
                onClick={() => set({ x: 0, y: 0 }, 'centre')}
              >
                Centre
              </button>
              <button
                type="button"
                disabled={placement === CENTRED}
                onClick={() =>
                  onReplace(
                    { artwork: entry.artwork },
                    'Placement reset: fit inside, whole, centred.',
                  )
                }
              >
                Reset placement
              </button>
            </div>
            <p className="small muted" aria-live="polite">
              {checking
                ? 'Python is placing the drawing…'
                : placed?.error
                  ? 'This page cannot be built: filling needs a full-bleed print profile.'
                  : placed?.fit === 'fill' && placed.drawing
                    ? `The drawing is ${(placed.drawing.width / 72).toFixed(2)} × ${(placed.drawing.height / 72).toFixed(2)} in from ${placed.pixels.width} × ${placed.pixels.height} pixels: ${placed.effective_dpi} DPI. ${cropSummary(placed.crop) ?? ''}`
                    : placed?.box
                      ? `Prints ${(placed.box.width / 72).toFixed(2)} × ${(placed.box.height / 72).toFixed(2)} in from ${placed.pixels.width} × ${placed.pixels.height} pixels: ${placed.effective_dpi} DPI.`
                      : 'Placement appears once Python plans this page.'}{' '}
              {fill
                ? 'Its own pixels, never resampled: the faint part outside the page and the hatched bleed are cut away; zooming or moving changes only what is cropped.'
                : 'The drawing always prints whole, inside the art box, with its own pixels: making it smaller never crops or resamples it.'}
            </p>
          </fieldset>
        </div>
      )}
      <div className="button-row">
        <button type="button" onClick={onDuplicate}>
          Duplicate page
        </button>
        <button type="button" onClick={onDivider}>
          Insert divider after
        </button>
      </div>
    </section>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
}) {
  const id = `slider-${label.toLowerCase().replace(/\W+/g, '-')}`;
  return (
    <div className="editor-field slider-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={0.05}
        value={value}
        aria-valuetext={format(value)}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <span className="small muted">{format(value)}</span>
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

// Long books render many spreads: only those near the viewport draw their pages.
function Spreads({
  plan,
  api,
  selectedPage,
  onSelect,
}: {
  plan: ColoringPlanResult;
  api: string;
  selectedPage?: number;
  onSelect: (page: number) => void;
}) {
  const pages = plan.plan.pages;
  // Page 1 is a right-hand page alone; then left-right spreads.
  const spreads: ColoringPlanPage[][] = [[pages[0]].filter(Boolean)];
  for (let i = 1; i < pages.length; i += 2) spreads.push(pages.slice(i, i + 2));
  return (
    <ol className="page-spreads" aria-label="Physical pages in order">
      {spreads.map((spread, i) => (
        <li key={i} className={i === 0 ? 'spread first' : 'spread'}>
          {spread.map((page) => (
            <PageCard
              key={page.index}
              page={page}
              plan={plan}
              api={api}
              selected={page.index === selectedPage}
              onSelect={onSelect}
            />
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
  selected,
  onSelect,
}: {
  page: ColoringPlanPage;
  plan: ColoringPlanResult;
  api: string;
  selected: boolean;
  onSelect: (page: number) => void;
}) {
  const g = plan.geometry;
  const side = g.sides[page.side];
  const blank = page.kind === 'blank';
  const reason = page.blank ? (BLANK_REASONS[page.blank.reason] ?? page.blank.reason) : null;
  const placed = plan.placements?.[String(page.index)];
  const media = mediaOf(g);
  const trim = trimOf(g, side);
  const rect = (b: { x: number; y: number; width: number; height: number }) =>
    svgRect(b, media.height);
  const selectable = page.section === 'artwork' && !blank;
  const clip = `card-clip-${page.index}`;
  const filled = placed?.fit === 'fill' && placed.box && placed.drawing;
  return (
    <figure
      className={`page-card ${page.side}${blank ? ' automatic' : ''}${selected ? ' selected' : ''}`}
    >
      <svg viewBox={`0 0 ${media.width} ${media.height}`} role="img" aria-label={describe(page)}>
        {g.bleed && (
          <rect className="bleed-area" x="0" y="0" width={media.width} height={media.height} />
        )}
        <rect className="trim" {...rect(trim)} />
        <rect className="live" {...rect(side.live)} />
        {page.kind === 'coloring' && page.artwork && (
          <>
            {!filled && <rect className="art" {...rect(side.art)} />}
            {filled && (
              <clipPath id={clip}>
                <rect {...rect(placed.box!)} />
              </clipPath>
            )}
            {placed?.error ? (
              <text x={media.width / 2} y={media.height / 2} textAnchor="middle" className="label">
                Needs bleed
              </text>
            ) : (
              <image
                href={`${api}/coloring/thumbnail?artwork=${encodeURIComponent(page.artwork.id)}`}
                {...rect(filled ? placed.drawing! : (placed?.box ?? side.art))}
                preserveAspectRatio={placed ? 'none' : 'xMidYMid meet'}
                clipPath={filled ? `url(#${clip})` : undefined}
              />
            )}
          </>
        )}
        {page.kind === 'divider' && (
          <text x={media.width / 2} y={media.height / 2} textAnchor="middle" className="label">
            {page.divider?.title}
          </text>
        )}
        {page.matter && page.kind !== 'blank' && (
          <text x={media.width / 2} y={media.height / 3} textAnchor="middle" className="label">
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
        {selectable && !selected && (
          <button
            type="button"
            className="link-button small"
            onClick={() => onSelect(page.index)}
            aria-label={`Design page ${page.index}`}
          >
            Design
          </button>
        )}
      </figcaption>
    </figure>
  );
}
