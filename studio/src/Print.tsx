import { RebuildPanel } from './production';
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, request } from './api';
import type {
  BuildDiagnostic,
  InteriorStatus,
  Measure,
  PageGeometry,
  PreflightFinding,
  PreflightReport,
  PreflightRule,
  PreviewPage,
  Project,
  PtBox,
} from './types';
import { ErrorState, Loading, Status } from './ui';

// Proofing surface for the built interior. Pages are rasters of interior.pdf;
// every verdict, page meaning and overlay box comes from Python. Nothing here
// measures, judges or lays out the book.
const KIND_NAMES: Record<string, string> = {
  title_page: 'Title page',
  copyright_page: 'Copyright page',
  instructions: 'Instructions',
  about: 'About page',
  notes: 'Notes page',
  puzzle: 'Puzzle',
  solutions: 'Solutions',
  blank: 'Intentional blank',
  coloring: 'Coloring page',
};
const ZOOMS = [50, 75, 100, 150, 200, 300];
// 100% is physical size at the CSS reference of 96 px per inch.
const CSS_PX_PER_PT = 96 / 72;
const OVERLAYS = [
  ['live', 'Live area', 'The margins of the print profile'],
  [
    'kdp',
    'KDP minimum margins',
    'Gutter for this page count and 0.25 in outside (0.375 in with bleed)',
  ],
  ['trim', 'Trim line', 'Where the printed page is cut (full-bleed interiors)'],
  ['bleed', 'Bleed', 'Printed beyond the trim and cut away (full-bleed interiors)'],
  ['elements', 'Element bounds', 'Painted extent of every layout element'],
  ['findings', 'Finding regions', 'Regions named by preflight findings'],
] as const;
type Overlay = (typeof OVERLAYS)[number][0];
// Fit the page, fit the width, or a percentage of print size.
type Zoom = 'fit' | 'width' | number;

const SEVERITY = {
  error: { tone: 'fail', label: 'Blocking' },
  warning: { tone: 'review', label: 'Warning' },
  info: { tone: 'neutral', label: 'Info' },
} as const;
// The coloring ruleset's info findings ask for a person's judgement; they never block.
const COLORING_RULESET = 'puzzlepress-kdp-coloring';
const REVIEW = { tone: 'neutral', label: 'Manual review' } as const;

function severityOf(finding: PreflightFinding, review: boolean) {
  return review && finding.severity === 'info' ? REVIEW : SEVERITY[finding.severity];
}

function sideName(side: string | null) {
  return side === 'recto' ? 'Recto (right)' : side === 'verso' ? 'Verso (left)' : 'Side unknown';
}

export function pageLabel(page: PreviewPage | undefined, number: number) {
  const parts = [`Page ${number}`, sideName(page?.side ?? (number % 2 ? 'recto' : 'verso'))];
  if (page?.kind) parts.push(KIND_NAMES[page.kind] ?? page.kind);
  if (page?.folio) parts.push(`number ${page.folio} printed`);
  return parts.join(' · ');
}

// Facing pages as a bound book shows them: page 1 alone on the right.
export function spreadOf(page: number, total: number): [number | null, number | null] {
  const left = page % 2 === 0 ? page : page - 1;
  return [left >= 2 ? left : null, left + 1 <= total ? left + 1 : null];
}

function formatValue(value: number | string, unit: string | null) {
  return unit ? `${value} ${unit}` : String(value);
}

export function measureText(measure: Measure) {
  const words: Record<string, string> = {
    at_least: 'at least ',
    at_most: 'at most ',
    within: 'within ',
    equal: '',
  };
  const required =
    measure.required === null
      ? ''
      : ` · required ${words[measure.comparison ?? 'equal'] ?? ''}${formatValue(measure.required, measure.unit)}`;
  return `Measured ${formatValue(measure.actual, measure.unit)}${required}`;
}

function blocks(finding: PreflightFinding) {
  if (finding.severity !== 'error') return 'Does not block';
  return finding.scope === 'structural'
    ? 'Blocks structural validity and KDP readiness'
    : 'Blocks KDP readiness';
}

function Rect({ box, className }: { box: PtBox; className: string }) {
  return (
    <rect
      className={className}
      x={box.x}
      y={-(box.y + box.height)}
      width={box.width}
      height={box.height}
      vectorEffect="non-scaling-stroke"
    />
  );
}

function Sheet({
  status,
  number,
  width,
  overlays,
  selected,
}: {
  status: InteriorStatus;
  number: number;
  width: number;
  overlays: Set<Overlay>;
  selected?: PreflightFinding;
}) {
  const preview = status.preview!;
  const page = preview.pages[number - 1];
  const geometry: PageGeometry | undefined = preview.geometry?.[number - 1];
  const profile = status.report?.profile;
  // The rendered page is the media box (the trim plus bleed on a full-bleed interior).
  const trim =
    geometry?.media ??
    geometry?.trim ??
    (profile
      ? { x: 0, y: 0, width: profile.trim.width_in * 72, height: profile.trim.height_in * 72 }
      : { x: 0, y: 0, width: 612, height: 792 });
  const bleeds =
    !!geometry?.media &&
    (geometry.media.width !== geometry.trim.width ||
      geometry.media.height !== geometry.trim.height);
  const height = (width * trim.height) / trim.width;
  const dpr = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1;
  const size = width * dpr <= trim.width * preview.scales.page ? 'page' : 'detail';
  const src = `/api/projects/${encodeURIComponent(status.key)}/interior/pages/${number}?size=${size}&pdf=${preview.pdf_sha256}`;
  const regions = (status.report?.findings ?? []).filter(
    (f) => f.physical_page === number && f.bounds,
  );
  const highlight = selected?.physical_page === number ? selected.bounds : null;
  return (
    <figure className="sheet" style={{ width }}>
      <div className="sheet-paper" style={{ height }}>
        <img
          src={src}
          width={Math.round(width)}
          height={Math.round(height)}
          alt={`Rendered ${pageLabel(page, number)}${page?.description ? `: ${page.description}` : ''}`}
        />
        {geometry && (
          <svg
            className="sheet-overlay"
            viewBox={`0 ${-trim.height} ${trim.width} ${trim.height}`}
            preserveAspectRatio="none"
            aria-hidden="true"
            data-testid={`overlay-${number}`}
          >
            <rect
              className="overlay-binding"
              x={page?.side === 'verso' ? trim.width - 4 : 0}
              y={-trim.height}
              width={4}
              height={trim.height}
            />
            {bleeds && overlays.has('bleed') && (
              <path
                className="overlay-bleed"
                fillRule="evenodd"
                d={`M0 ${-trim.height}h${trim.width}v${trim.height}h${-trim.width}z M${geometry.trim.x} ${-(geometry.trim.y + geometry.trim.height)}h${geometry.trim.width}v${geometry.trim.height}h${-geometry.trim.width}z`}
              />
            )}
            {bleeds && overlays.has('trim') && (
              <Rect box={geometry.trim} className="overlay-trim" />
            )}
            {overlays.has('live') && <Rect box={geometry.live} className="overlay-live" />}
            {overlays.has('kdp') && geometry.kdp_safe && (
              <Rect box={geometry.kdp_safe} className="overlay-kdp" />
            )}
            {overlays.has('elements') &&
              geometry.elements.map((e, i) => (
                <Rect key={i} box={e.box} className="overlay-element" />
              ))}
            {overlays.has('findings') &&
              regions.map((f, i) => <Rect key={i} box={f.bounds!} className="overlay-finding" />)}
            {highlight && <Rect box={highlight} className="overlay-selected" />}
          </svg>
        )}
      </div>
      <figcaption>
        <strong>{pageLabel(page, number)}</strong>
        {page?.description && <span>{page.description}</span>}
      </figcaption>
    </figure>
  );
}

function Thumbnails({
  status,
  current,
  shown,
  onSelect,
}: {
  status: InteriorStatus;
  current: number;
  shown: number[];
  onSelect: (page: number) => void;
}) {
  const preview = status.preview!;
  const active = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    active.current?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [current]);
  return (
    <nav className="print-thumbs" aria-label="Pages">
      <ol>
        {preview.pages.map((page) => {
          const n = page.physical_page;
          const isCurrent = shown.includes(n);
          const errors = page.findings.error;
          const warnings = page.findings.warning;
          return (
            <li key={n}>
              <button
                type="button"
                ref={n === current ? active : undefined}
                aria-current={isCurrent ? 'page' : undefined}
                aria-label={`${pageLabel(page, n)}${errors ? `, ${errors} blocking` : ''}${warnings ? `, ${warnings} warning` : ''}`}
                onClick={() => onSelect(n)}
              >
                <img
                  src={`/api/projects/${encodeURIComponent(status.key)}/interior/pages/${n}?size=thumb&pdf=${preview.pdf_sha256}`}
                  alt=""
                  loading="lazy"
                  width={77}
                  height={100}
                />
                <span className="thumb-label">
                  {n}
                  <small>{page.side === 'verso' ? 'L' : 'R'}</small>
                  {errors > 0 && <span className="thumb-flag fail" aria-hidden="true" />}
                  {!errors && warnings > 0 && (
                    <span className="thumb-flag review" aria-hidden="true" />
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function FindingItem({
  finding,
  rule,
  selected,
  onSelect,
  review = false,
}: {
  finding: PreflightFinding;
  rule?: PreflightRule;
  selected: boolean;
  onSelect: () => void;
  review?: boolean;
}) {
  const severity = severityOf(finding, review);
  const where =
    finding.physical_page === null
      ? 'Whole book'
      : `Page ${finding.physical_page}${finding.side ? ` · ${finding.side}` : ''}${
          finding.page_kind ? ` · ${KIND_NAMES[finding.page_kind] ?? finding.page_kind}` : ''
        }${finding.folio ? ` · number ${finding.folio}` : ''}`;
  return (
    <li className={selected ? 'selected' : undefined}>
      <div className="finding-head">
        <Status tone={severity.tone}>{severity.label}</Status>
        <span className="finding-scope">
          {finding.scope === 'kdp' ? 'KDP readiness' : 'Structural'}
        </span>
      </div>
      <strong>{rule?.title ?? finding.rule.replaceAll('_', ' ')}</strong>
      <p>{finding.message}</p>
      {finding.measure && <p className="finding-measure">{measureText(finding.measure)}</p>}
      <p className="finding-meta">
        {where}
        {finding.subject ? ` · ${finding.subject}` : ''}
        {finding.region ? ` · region ${finding.region}` : ''}
        {' · '}
        {blocks(finding)}
        {' · '}
        <code>{finding.rule}</code>
      </p>
      {finding.physical_page !== null && (
        <button type="button" aria-pressed={selected} onClick={onSelect}>
          {finding.bounds ? 'Show region on page' : 'Show page'} {finding.physical_page}
        </button>
      )}
    </li>
  );
}

function RuleList({ title, rules }: { title: string; rules: PreflightRule[] }) {
  if (!rules.length) return null;
  return (
    <details className="details rule-list">
      <summary>
        {title} ({rules.length})
      </summary>
      <ul>
        {rules.map((rule) => (
          <li key={rule.code}>
            <strong>{rule.title}</strong>{' '}
            <span className="muted">{rule.scope === 'kdp' ? 'KDP' : 'Structural'}</span>
            {rule.note && <p>{rule.note}</p>}
            {rule.measure && rule.outcome === 'passed' && (
              <p className="finding-measure">{measureText(rule.measure)}</p>
            )}
            <p className="small muted">
              {rule.source}
              {rule.basis === 'kdp_ambiguous' ? ' · official wording is ambiguous' : ''} ·{' '}
              <code>{rule.code}</code>
            </p>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Verdict({ report }: { report: PreflightReport }) {
  const errors = report.findings.filter((f) => f.severity === 'error').length;
  const warnings = report.findings.filter((f) => f.severity === 'warning').length;
  const reviews =
    report.ruleset.id === COLORING_RULESET
      ? report.findings.filter((f) => f.severity === 'info').length
      : 0;
  return (
    <dl className="print-verdict" aria-label="Preflight status">
      <div>
        <dt>Structural</dt>
        <dd>
          {report.structural.status === 'valid' ? (
            <Status tone="pass">Valid</Status>
          ) : (
            <Status tone="fail">Invalid</Status>
          )}
        </dd>
      </div>
      <div>
        <dt>KDP readiness</dt>
        <dd>
          {report.kdp.status === 'ready' ? (
            <Status tone="pass">Ready</Status>
          ) : (
            <Status tone="fail">Not ready</Status>
          )}
        </dd>
      </div>
      <div>
        <dt>Findings</dt>
        <dd>
          <a href="#print-findings">
            {errors} blocking · {warnings} {warnings === 1 ? 'warning' : 'warnings'}
            {reviews > 0 && ` · ${reviews} to review`}
          </a>
        </dd>
      </div>
      <div>
        <dt>Interior</dt>
        <dd>
          {report.page_count ?? '?'} pages
          {report.profile
            ? ` · ${report.profile.trim.width_in} x ${report.profile.trim.height_in} in`
            : ''}
        </dd>
      </div>
    </dl>
  );
}

function Findings({
  report,
  selected,
  onSelect,
}: {
  report: PreflightReport;
  selected: number | null;
  onSelect: (index: number) => void;
}) {
  const rules = new Map(report.rules.map((r) => [r.code, r]));
  const review = report.ruleset.id === COLORING_RULESET;
  const groups: [string, PreflightFinding['severity']][] = [
    ['Blocking', 'error'],
    ['Warnings', 'warning'],
    [review ? 'Manual review' : 'Information', 'info'],
  ];
  return (
    <section
      className="print-findings"
      id="print-findings"
      tabIndex={-1}
      aria-labelledby="findings-heading"
    >
      <h3 id="findings-heading">Preflight findings</h3>
      <p className="small muted">
        Ruleset {report.ruleset.id} v{report.ruleset.version}; KDP rules checked{' '}
        {report.ruleset.kdp_rules_checked}. Preflight checks the constraints PuzzlePress models.
        Amazon KDP remains the final authority.
      </p>
      {report.findings.length === 0 && (
        <p>
          <Status tone="pass">No findings</Status> Every modeled check passed or does not apply.
        </p>
      )}
      {groups.map(([heading, severity]) => {
        const items = report.findings
          .map((finding, index) => ({ finding, index }))
          .filter(({ finding }) => finding.severity === severity);
        if (!items.length) return null;
        return (
          <div key={severity}>
            <h4>
              {heading} ({items.length})
            </h4>
            <ul className="finding-list">
              {items.map(({ finding, index }) => (
                <FindingItem
                  key={index}
                  finding={finding}
                  rule={rules.get(finding.rule)}
                  selected={selected === index}
                  onSelect={() => onSelect(index)}
                  review={review}
                />
              ))}
            </ul>
          </div>
        );
      })}
      <RuleList title="Passed checks" rules={report.rules.filter((r) => r.outcome === 'passed')} />
      <RuleList
        title="Not applicable"
        rules={report.rules.filter((r) => r.outcome === 'not_applicable')}
      />
      <RuleList
        title="Not evaluated"
        rules={report.rules.filter((r) => r.outcome === 'not_evaluated')}
      />
      <details className="details">
        <summary>Inspected artifacts</summary>
        <dl className="facts">
          <div>
            <dt>Print profile</dt>
            <dd>
              {report.profile ? `${report.profile.id} v${report.profile.version}` : 'Unknown'}
            </dd>
          </div>
          <div>
            <dt>PDF SHA-256</dt>
            <dd>
              <code className="identity">{report.artifacts.pdf?.sha256 ?? 'none'}</code>
            </dd>
          </div>
          <div>
            <dt>Interior identity</dt>
            <dd>
              <code className="identity">{report.artifacts.interior_identity ?? 'none'}</code>
            </dd>
          </div>
        </dl>
      </details>
    </section>
  );
}

function BuildFailure({ stage, diagnostics }: { stage?: string; diagnostics: BuildDiagnostic[] }) {
  return (
    <div role="alert" className="notice error">
      <h3>The interior did not build</h3>
      <p>
        Stage {stage}. Nothing was written; the previous interior, if any, is unchanged. Fix the
        source or composition, save, then build again.
      </p>
      <ul className="issue-list">
        {diagnostics.map((d, i) => (
          <li key={i}>
            <strong>{d.message}</strong> <code>{d.code}</code>
            {d.page !== null && ` · page ${d.page}`}
            {d.kind && ` · ${KIND_NAMES[d.kind] ?? d.kind}`}
            {d.actual && ` · measured ${d.actual}; allowed ${d.required}`}
          </li>
        ))}
      </ul>
    </div>
  );
}

function useStageWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth || 600);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function Viewer({ status }: { status: InteriorStatus }) {
  const preview = status.preview!;
  const report = status.report!;
  const total = preview.page_count;
  const [page, setPage] = useState(1);
  const [typed, setTyped] = useState('1');
  const [spread, setSpread] = useState(false);
  const [zoom, setZoom] = useState<Zoom>('fit');
  const [overlays, setOverlays] = useState<Set<Overlay>>(new Set());
  const [selected, setSelected] = useState<number | null>(null);
  const [stage, stageWidth] = useStageWidth();
  const shown = spread ? spreadOf(page, total).filter((n): n is number => n !== null) : [page];
  const go = useCallback(
    (next: number) => {
      const clamped = Math.min(Math.max(next, 1), total);
      setPage(clamped);
      setTyped(String(clamped));
    },
    [total],
  );
  const step = (direction: 1 | -1) => {
    if (!spread) return go(page + direction);
    const [left] = spreadOf(page, total);
    const base = left ?? 0;
    go(direction > 0 ? base + 2 : Math.max(base - 2, 1));
  };
  useEffect(() => {
    // Warm the browser cache for the next page; images are digest-addressed.
    const next = page + (spread ? 2 : 1);
    if (next <= total && typeof Image !== 'undefined') {
      const image = new Image();
      image.src = `/api/projects/${encodeURIComponent(status.key)}/interior/pages/${next}?size=page&pdf=${preview.pdf_sha256}`;
    }
  }, [page, spread, total, status.key, preview.pdf_sha256]);
  const columns = spread ? 2 : 1;
  const gap = spread ? 2 : 0;
  // The built PDF's own trim (points): pages are sized from it, never from 8.5 x 11.
  const pageTrim =
    preview.geometry?.[0]?.media ??
    preview.geometry?.[0]?.trim ??
    (report.profile
      ? { width: report.profile.trim.width_in * 72, height: report.profile.trim.height_in * 72 }
      : { width: 612, height: 792 });
  // Fit inside the canvas: its 16px padding, the page outline, and (by height) the
  // canvas's viewport-relative maximum less the caption under each page.
  const viewport = typeof window === 'undefined' ? 900 : window.innerHeight;
  const fitWidth = Math.max(
    160,
    Math.floor(
      Math.min(
        (stageWidth - 34 - gap) / columns,
        (viewport - 240) * (pageTrim.width / pageTrim.height),
      ),
    ),
  );
  const widthFit = Math.max(160, Math.floor((stageWidth - 34 - gap) / columns));
  const width =
    zoom === 'fit'
      ? fitWidth
      : zoom === 'width'
        ? widthFit
        : pageTrim.width * CSS_PX_PER_PT * (zoom / 100);
  // From a fitted view, zoom steps from the size it shows.
  const percent = (width / (pageTrim.width * CSS_PX_PER_PT)) * 100;
  const zoomIndex = typeof zoom === 'number' ? ZOOMS.indexOf(zoom) : -1;
  const zoomBy = (direction: 1 | -1) => {
    if (typeof zoom === 'number') {
      const next = ZOOMS[zoomIndex + direction];
      if (next) setZoom(next);
      return;
    }
    const next =
      direction > 0
        ? ZOOMS.find((z) => z > percent + 0.5)
        : [...ZOOMS].reverse().find((z) => z < percent - 0.5);
    setZoom(next ?? (direction > 0 ? ZOOMS[ZOOMS.length - 1] : ZOOMS[0]));
  };
  const resetView = () => {
    setZoom('fit');
    stage.current?.scrollTo?.({ left: 0, top: 0 });
  };
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const [panning, setPanning] = useState(false);
  const panStart = (event: React.PointerEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    if (event.button !== 0) return;
    if (element.scrollWidth <= element.clientWidth && element.scrollHeight <= element.clientHeight)
      return;
    drag.current = {
      x: event.clientX,
      y: event.clientY,
      left: element.scrollLeft,
      top: element.scrollTop,
    };
    element.setPointerCapture?.(event.pointerId);
    setPanning(true);
  };
  const panMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (!start) return;
    event.currentTarget.scrollLeft = start.left - (event.clientX - start.x);
    event.currentTarget.scrollTop = start.top - (event.clientY - start.y);
  };
  const panEnd = () => {
    drag.current = null;
    setPanning(false);
  };
  const selectedFinding = selected === null ? undefined : report.findings[selected];
  const keys = (event: React.KeyboardEvent) => {
    if ((event.target as HTMLElement).closest('input, select, textarea')) return;
    const actions: Record<string, () => void> = {
      ArrowRight: () => step(1),
      PageDown: () => step(1),
      ArrowLeft: () => step(-1),
      PageUp: () => step(-1),
      Home: () => go(1),
      End: () => go(total),
      '+': () => zoomBy(1),
      '=': () => zoomBy(1),
      '-': () => zoomBy(-1),
      '0': resetView,
    };
    const action = actions[event.key];
    if (action) {
      event.preventDefault();
      action();
    }
  };
  const current = preview.pages[page - 1];
  return (
    <div className="print-workspace">
      <Thumbnails status={status} current={page} shown={shown} onSelect={go} />
      <section className="print-stage" aria-label="Page preview" onKeyDown={keys}>
        <div className="print-toolbar" role="toolbar" aria-label="Page navigation and view">
          <div className="print-nav">
            <button
              type="button"
              onClick={() => go(1)}
              disabled={page === 1}
              aria-label="First page"
            >
              First
            </button>
            <button
              type="button"
              onClick={() => step(-1)}
              disabled={shown[0] === 1}
              aria-label={spread ? 'Previous spread' : 'Previous page'}
            >
              Previous
            </button>
            <form
              className="page-jump"
              onSubmit={(event) => {
                event.preventDefault();
                const value = Number.parseInt(typed, 10);
                if (Number.isFinite(value)) go(value);
                else setTyped(String(page));
              }}
            >
              <label htmlFor="page-number">Page</label>
              <input
                id="page-number"
                inputMode="numeric"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                onBlur={() => {
                  const value = Number.parseInt(typed, 10);
                  if (Number.isFinite(value)) go(value);
                  else setTyped(String(page));
                }}
              />
              <span>of {total}</span>
            </form>
            <button
              type="button"
              onClick={() => step(1)}
              disabled={shown[shown.length - 1] === total}
              aria-label={spread ? 'Next spread' : 'Next page'}
            >
              Next
            </button>
            <button
              type="button"
              onClick={() => go(total)}
              disabled={page === total}
              aria-label="Last page"
            >
              Last
            </button>
          </div>
          <div className="print-view">
            <div role="group" aria-label="View">
              <button type="button" aria-pressed={!spread} onClick={() => setSpread(false)}>
                Single page
              </button>
              <button type="button" aria-pressed={spread} onClick={() => setSpread(true)}>
                Spread
              </button>
            </div>
            <div role="group" aria-label="Zoom">
              <button
                type="button"
                aria-label="Zoom out"
                disabled={zoomIndex === 0 || (zoomIndex < 0 && percent <= ZOOMS[0] + 0.5)}
                onClick={() => zoomBy(-1)}
              >
                −
              </button>
              <label className="sr-only" htmlFor="zoom-level">
                Zoom level
              </label>
              <select
                id="zoom-level"
                value={String(zoom)}
                onChange={(event) =>
                  setZoom(
                    event.target.value === 'fit' || event.target.value === 'width'
                      ? event.target.value
                      : Number(event.target.value),
                  )
                }
              >
                <option value="fit">Fit page</option>
                <option value="width">Fit width</option>
                {ZOOMS.map((z) => (
                  <option key={z} value={z}>
                    {z}%
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-label="Zoom in"
                disabled={
                  zoomIndex === ZOOMS.length - 1 ||
                  (zoomIndex < 0 && percent >= ZOOMS[ZOOMS.length - 1] - 0.5)
                }
                onClick={() => zoomBy(1)}
              >
                +
              </button>
              <button type="button" onClick={resetView}>
                Reset view
              </button>
            </div>
          </div>
        </div>
        <p className="print-current" role="status" aria-live="polite">
          {spread && shown.length === 2
            ? `Spread: pages ${shown[0]} and ${shown[1]} of ${total}`
            : spread
              ? `Spread: page ${shown[0]} of ${total} alone (${shown[0] === 1 ? 'first page is a recto' : 'last page is a verso'})`
              : `${pageLabel(current, page)} of ${total}`}
        </p>
        <div
          className={`print-canvas${panning ? ' panning' : ''}`}
          ref={stage}
          tabIndex={0}
          aria-label="Rendered pages. Use arrow keys, Page Up, Page Down, Home and End to turn pages; plus, minus and 0 zoom; drag to pan when zoomed in."
          onPointerDown={panStart}
          onPointerMove={panMove}
          onPointerUp={panEnd}
          onPointerCancel={panEnd}
        >
          <div className={`print-pages${spread ? ' spread' : ''}`}>
            {spread && spreadOf(page, total)[0] === null && (
              <div className="sheet sheet-empty" style={{ width }} aria-hidden="true" />
            )}
            {shown.map((n) => (
              <Sheet
                key={n}
                status={status}
                number={n}
                width={width}
                overlays={overlays}
                selected={selectedFinding}
              />
            ))}
          </div>
        </div>
        <fieldset className="print-overlays" disabled={!preview.geometry}>
          <legend>Overlays (preview only, never in the PDF)</legend>
          {OVERLAYS.map(([key, label, hint]) => (
            <label key={key} className="check">
              <input
                type="checkbox"
                checked={overlays.has(key)}
                onChange={(event) => {
                  const next = new Set(overlays);
                  if (event.target.checked) next.add(key);
                  else next.delete(key);
                  setOverlays(next);
                }}
              />
              <span>
                <span className={`overlay-key ${key}`} aria-hidden="true" />
                {label}
                <small>{hint}</small>
              </span>
            </label>
          ))}
          {!preview.geometry && (
            <p className="small muted">
              Overlays need an interior built from the current saved source.
            </p>
          )}
        </fieldset>
        <p className="small muted">
          Pages are rasterized from interior.pdf, the file you would upload. The page images carry
          no text for assistive technology; page descriptions and findings are provided as text. The
          binding edge is marked on each page.
        </p>
      </section>
      <Findings
        report={report}
        selected={selected}
        onSelect={(index) => {
          setSelected(index);
          const target = report.findings[index].physical_page;
          if (target) go(target);
          if (report.findings[index].bounds) setOverlays((o) => new Set(o).add('findings'));
        }}
      />
    </div>
  );
}

const STALE_RULES = [
  'source_current',
  'plan_current',
  'print_profile_current',
  'toolchain_current',
];
const STATE_NOTES: Record<string, ReactNode> = {
  invalid: (
    <>
      <strong>This interior failed structural checks.</strong> The files on disk do not match a
      coherent PuzzlePress build. See the blocking findings, then rebuild.
    </>
  ),
};

export function Print({ project, dirty }: { project: Project; dirty: boolean }) {
  const [status, setStatus] = useState<InteriorStatus>();
  const [error, setError] = useState<Error>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [failure, setFailure] = useState<InteriorStatus['build']>();
  const [attempt, setAttempt] = useState(0);
  const [profile, setProfile] = useState<string>();
  const [rebuilding, setRebuilding] = useState(false);
  const base = `/api/projects/${encodeURIComponent(project.key)}/interior`;
  useEffect(() => {
    const controller = new AbortController();
    setError(undefined);
    request<InteriorStatus>(base, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setStatus(data);
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => controller.abort();
  }, [base, project.revision, attempt]);
  const build = async () => {
    setBusy(true);
    setFailure(undefined);
    setMessage('Building the interior from the saved source, then running preflight…');
    try {
      const data = await request<InteriorStatus>(`${base}/build`, new AbortController().signal, {
        revision: project.revision,
        ...(profile && !status?.authored_profile ? { profile } : {}),
      });
      setStatus(data);
      if (data.build?.success) setMessage('Interior built and preflight complete.');
      else {
        setFailure(data.build);
        setMessage('The interior did not build. Nothing was written.');
      }
    } catch (err) {
      setMessage(
        err instanceof ApiError && err.code === 'source_changed'
          ? 'The saved source changed on disk. Reload the project before building.'
          : err instanceof ApiError
            ? err.message
            : 'The build request did not complete.',
      );
    } finally {
      setBusy(false);
    }
  };
  const coloring = project.engine?.kind === 'coloring';
  if (!project.source?.composition)
    return (
      <section className="notice">
        <h2>No book composition</h2>
        {coloring ? (
          <p>
            Print proofs need a composed book. Add a <code>composition</code> section to book.yaml
            (front matter, where the artwork starts, page numbers), then return here to build the
            interior.
          </p>
        ) : (
          <p>
            Print proofs need a composed book. Choose Book to start a composition, save it, then
            return here to build the interior.
          </p>
        )}
      </section>
    );
  if (error) return <ErrorState error={error} retry={() => setAttempt((n) => n + 1)} />;
  if (!status) return <Loading>Reading the built interior and running preflight…</Loading>;
  return (
    <div className="print">
      <div className="editor-toolbar print-heading">
        <div>
          <h2>Print proof</h2>
          <p className="muted">
            The built interior, page by page, with structural and KDP preflight. Builds use the
            saved source only.
          </p>
        </div>
        <div className="editor-actions">
          {status.authored_profile ? (
            <p className="small print-profile">
              Paper:{' '}
              <strong>
                {status.profiles?.find((p) => p.id === status.authored_profile)?.paper === 'cream'
                  ? 'Cream'
                  : 'White'}
              </strong>
              , from this book&apos;s{' '}
              <a href={`/books/${encodeURIComponent(status.key)}/settings`}>Settings</a>
            </p>
          ) : (
            status.profiles && (
              <div className="editor-field print-profile">
                <label htmlFor="print-profile">Paper</label>
                <select
                  id="print-profile"
                  value={profile ?? status.profile}
                  disabled={busy}
                  aria-describedby="print-profile-hint"
                  onChange={(event) => setProfile(event.target.value)}
                >
                  {status.profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.description}
                    </option>
                  ))}
                </select>
                <span className="sr-only" id="print-profile-hint">
                  Paper sets the cover's spine width. Pages are laid out identically.
                </span>
              </div>
            )
          )}
          <button
            type="button"
            className="primary"
            disabled={busy || dirty}
            onClick={() => void build()}
          >
            {status.state === 'missing' ? 'Build interior' : 'Rebuild interior'}
          </button>
        </div>
      </div>
      {dirty && (
        <p className="draft-status">
          You have unsaved changes. This proof shows the saved source; save before building.
        </p>
      )}
      <p role="status" aria-live="polite" className="small">
        {message}
      </p>
      {failure && !failure.success && (
        <BuildFailure stage={failure.stage} diagnostics={failure.diagnostics ?? []} />
      )}
      {status.state === 'missing' ? (
        <div className="preview-empty print-empty">
          <h2>No interior has been built.</h2>
          <p>
            Build interior lays out the saved book, writes interior.pdf with its manifest and
            preflight report, and then shows every page here.
          </p>
        </div>
      ) : (
        <>
          {status.report && <Verdict report={status.report} />}
          {status.state === 'stale' && (
            <div className="print-state stale stale-banner" role="status">
              <p>
                <strong>This interior is out of date.</strong> The pages below show the old PDF.
              </p>
              <ul className="small">
                {(status.report?.findings ?? [])
                  .filter((f) => STALE_RULES.includes(f.rule))
                  .map((f, i) => (
                    <li key={i}>{f.message}</li>
                  ))}
              </ul>
              <div className="button-row">
                <button
                  type="button"
                  className="primary small-button"
                  disabled={busy || dirty}
                  onClick={() => void build()}
                >
                  Rebuild interior
                </button>
                {!coloring && (
                  <button
                    type="button"
                    className="small-button"
                    aria-expanded={rebuilding}
                    onClick={() => setRebuilding((open) => !open)}
                  >
                    Rebuild outdated artifacts…
                  </button>
                )}
              </div>
            </div>
          )}
          {STATE_NOTES[status.state] && (
            <p className={`print-state ${status.state}`}>{STATE_NOTES[status.state]}</p>
          )}
          {coloring && status.preview && (
            <p className="small">
              <a
                className="button small-button"
                href={`${base}/pdf?pdf=${status.preview.pdf_sha256}`}
                download="interior.pdf"
                // A file, not a Studio page: a target keeps the client router out of it.
                target="_blank"
                rel="noopener"
              >
                Download interior.pdf
              </a>{' '}
              <span className="muted">
                {status.preview.page_count} pages, exactly the file preflight inspected.
              </span>
            </p>
          )}
          {rebuilding && !coloring && (
            <RebuildPanel
              projectKey={project.key}
              revision={project.revision}
              dirty={dirty}
              onDone={() => setAttempt((n) => n + 1)}
              onClose={() => setRebuilding(false)}
            />
          )}
          {status.preview && status.report ? (
            <Viewer key={status.preview.pdf_sha256} status={status} />
          ) : (
            status.report && (
              <Findings report={status.report} selected={null} onSelect={() => undefined} />
            )
          )}
        </>
      )}
    </div>
  );
}
