import { useEffect, useId, useRef, useState } from 'react';
import { ApiError, request } from './api';
import type { Adjustments, ArtworkEntry, ColoringListing, Preparation } from './types';
import { Status } from './ui';

// Line-art preparation for one artwork. Python prepares, measures and judges; the
// browser sends settings, shows Python's previews and saves through the revision check.

// Python's defaults; the server normalizes whatever is sent and remains authoritative.
export const DEFAULTS: Adjustments = {
  grayscale: true,
  threshold: null,
  brightness: 0,
  contrast: 1,
  background_cleanup: 0,
  despeckle: 0,
  line_weight: 0,
};
const DESPECKLE = ['Off', 'Up to 4 px', 'Up to 9 px', 'Up to 16 px', 'Up to 36 px', 'Up to 64 px'];
const LINE_WEIGHT: [number, string][] = [
  [-2, 'Thinner (5 px filter)'],
  [-1, 'Thinner (3 px filter)'],
  [0, 'Unchanged'],
  [1, 'Thicker (3 px filter)'],
  [2, 'Thicker (5 px filter)'],
];
const VIEWS: [string, string][] = [
  ['side', 'Before / after'],
  ['original', 'Original'],
  ['prepared', 'Prepared'],
  ['difference', 'Difference'],
];
const CAPTIONS: Record<string, string> = {
  original: 'Original (gray, before settings)',
  prepared: 'Prepared',
  difference: 'Gray: ink kept · red: ink removed · blue: ink added',
};
const MEASURES: [string, string][] = [
  ['ink_before', 'Ink, original'],
  ['ink_after', 'Ink, prepared'],
  ['thin_line_retention', 'Fine lines kept'],
  ['detail_retention', 'Line work kept'],
  ['strokes_before', 'Strokes, original'],
  ['strokes_after', 'Strokes, prepared'],
  ['specks_removed', 'Isolated marks removed'],
  ['specks_per_megapixel_after', 'Isolated marks left per MP'],
  ['paper_level_after', 'Paper level (255 is white)'],
  ['mean_change', 'Mean change (0 to 255)'],
];
const TONE = { blocking: 'fail', warning: 'review' } as const;
const DEBOUNCE_MS = 350;

export function normalized(adjustments: Adjustments): Adjustments {
  const { invert, ...rest } = { ...DEFAULTS, ...adjustments };
  return invert ? { ...rest, invert: true } : rest;
}

export const same = (a: Adjustments, b: Adjustments) =>
  JSON.stringify(normalized(a)) === JSON.stringify(normalized(b));

function measure(value: Preparation['measures'][string] | undefined, key: string) {
  if (value === null || value === undefined) return 'Not measured';
  if (typeof value !== 'number') return value.length ? value.join(', ') : 'None';
  return key.startsWith('ink') || key.endsWith('retention')
    ? `${(value * 100).toFixed(1)} %`
    : String(value);
}

export function AdjustPanel({
  projectKey,
  entry,
  title,
  revision,
  onSaved,
}: {
  projectKey: string;
  entry: ArtworkEntry;
  title: string;
  revision: string;
  onSaved: (listing: ColoringListing) => void;
}) {
  const base = `/api/projects/${encodeURIComponent(projectKey)}/coloring`;
  const saved = normalized(entry.adjustments);
  const [draft, setDraft] = useState<Adjustments>(saved);
  const [preview, setPreview] = useState<Preparation>();
  const [previewing, setPreviewing] = useState(true);
  const [error, setError] = useState<ApiError>();
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string>();
  const [view, setView] = useState('side');
  const sequence = useRef(0);
  const draftKey = JSON.stringify(normalized(draft));

  // Debounced preview of the settings on screen. Every request is numbered and only
  // the latest one's answer is shown, so the preview never shows other settings.
  useEffect(() => {
    const ticket = ++sequence.current;
    const controller = new AbortController();
    setPreviewing(true);
    const ask = (attempt: number): Promise<void> =>
      request<Preparation>(`${base}/prepare`, controller.signal, {
        artwork: entry.id,
        adjustments: JSON.parse(draftKey) as Adjustments,
      })
        .then((result) => {
          if (ticket !== sequence.current) return;
          setPreview(result);
          setError(undefined);
          setPreviewing(false);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted || ticket !== sequence.current) return;
          if (err instanceof ApiError && err.code === 'preparation_busy' && attempt < 3)
            return new Promise<void>((resume) => window.setTimeout(resume, 600)).then(() =>
              ask(attempt + 1),
            );
          setError(err instanceof ApiError ? err : new ApiError('The preview failed.', 'failed'));
          setPreviewing(false);
        });
    const timer = window.setTimeout(() => void ask(0), DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [base, entry.id, draftKey]);

  const change = (patch: Partial<Adjustments>) => {
    setMessage(undefined);
    setDraft((current) => normalized({ ...current, ...patch }));
  };
  const dirty = !same(draft, saved);
  const current = preview !== undefined && !previewing && same(preview.adjustments, draft);
  const save = async () => {
    setSaving(true);
    setMessage(undefined);
    try {
      const next = await request<ColoringListing>(
        `${base}/adjustments`,
        new AbortController().signal,
        {
          artwork: entry.id,
          revision,
          adjustments: same(draft, DEFAULTS) ? null : normalized(draft),
        },
      );
      onSaved(next);
      setError(undefined);
      setMessage(
        'Settings saved. The original file is unchanged. Rebuild the interior in Print proof to print them.',
      );
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError('Saving failed.', 'failed'));
    }
    setSaving(false);
  };
  const id = `adjust-${entry.id}`;
  const images = preview?.images;
  return (
    <section className="adjust-panel" aria-labelledby={`${id}-heading`}>
      <h4 id={`${id}-heading`}>Prepare &lsquo;{title}&rsquo; for printing</h4>
      <p className="small muted">
        Settings change a prepared copy only; the original file is never changed. Preparation runs
        in Python.
      </p>
      <div className="adjust-layout">
        <fieldset className="adjust-controls" disabled={saving}>
          <legend>Settings</legend>
          <div role="radiogroup" aria-label="Gray conversion" className="adjust-choice">
            <label>
              <input
                type="radio"
                name={`${id}-gray`}
                checked={draft.grayscale}
                onChange={() => change({ grayscale: true })}
              />{' '}
              Grayscale (luma)
            </label>
            <label>
              <input
                type="radio"
                name={`${id}-gray`}
                checked={!draft.grayscale}
                onChange={() => change({ grayscale: false })}
              />{' '}
              Darkest channel (light colored lines)
            </label>
          </div>
          <label className="adjust-check">
            <input
              type="checkbox"
              checked={Boolean(draft.invert)}
              onChange={(event) => change({ invert: event.target.checked })}
            />{' '}
            Invert (white lines on black)
          </label>
          <Slider
            label="Brightness"
            min={-1}
            max={1}
            step={0.05}
            value={draft.brightness}
            onChange={(brightness) => change({ brightness })}
          />
          <Slider
            label="Contrast"
            min={0.25}
            max={4}
            step={0.05}
            value={draft.contrast}
            onChange={(contrast) => change({ contrast })}
          />
          <Slider
            label="Background cleanup"
            min={0}
            max={1}
            step={0.05}
            value={draft.background_cleanup}
            onChange={(background_cleanup) => change({ background_cleanup })}
          />
          <label className="adjust-field">
            <span>Remove isolated marks</span>
            <select
              value={draft.despeckle}
              onChange={(event) => change({ despeckle: Number(event.target.value) })}
            >
              {DESPECKLE.map((label, value) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="adjust-check">
            <input
              type="checkbox"
              checked={draft.threshold !== null}
              onChange={(event) => change({ threshold: event.target.checked ? 0.5 : null })}
            />{' '}
            Black-and-white threshold
          </label>
          {draft.threshold !== null && (
            <Slider
              label="Threshold"
              min={0.05}
              max={0.95}
              step={0.01}
              value={draft.threshold}
              onChange={(threshold) => change({ threshold })}
            />
          )}
          <label className="adjust-field">
            <span>Line weight</span>
            <select
              value={draft.line_weight}
              onChange={(event) => change({ line_weight: Number(event.target.value) })}
            >
              {LINE_WEIGHT.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="adjust-buttons">
            <button
              type="button"
              className="primary"
              disabled={!dirty || saving}
              onClick={() => void save()}
            >
              Save settings
            </button>
            <button type="button" disabled={same(draft, DEFAULTS)} onClick={() => change(DEFAULTS)}>
              Reset to defaults
            </button>
            <button type="button" disabled={!dirty} onClick={() => change(saved)}>
              Revert to saved
            </button>
          </div>
        </fieldset>
        <div className="adjust-preview">
          <div role="radiogroup" aria-label="Preview" className="adjust-views">
            {VIEWS.map(([key, label]) => (
              <label key={key} className={view === key ? 'selected' : undefined}>
                <input
                  type="radio"
                  name={`${id}-view`}
                  checked={view === key}
                  onChange={() => setView(key)}
                />
                {label}
              </label>
            ))}
          </div>
          <p aria-live="polite" className="small adjust-status">
            {error ? (
              <Status tone="fail">Preview failed</Status>
            ) : previewing || !current ? (
              <Status tone="neutral">Updating preview…</Status>
            ) : (
              <Status tone="pass">Preview shows these settings</Status>
            )}{' '}
            {dirty ? 'Unsaved settings.' : 'Saved settings.'} {message}
          </p>
          {error && (
            <p role="alert" className="notice error small">
              {error.message} <code>{error.code}</code>
            </p>
          )}
          {images && (
            <div className="adjust-images" aria-busy={previewing}>
              {(view === 'side' ? ['original', 'prepared'] : [view]).map((kind) => (
                <figure key={kind}>
                  <img
                    src={images[kind as keyof typeof images]}
                    alt={`${kind[0].toUpperCase()}${kind.slice(1)}: ${title}`}
                  />
                  <figcaption>{CAPTIONS[kind]}</figcaption>
                </figure>
              ))}
            </div>
          )}
          {preview && (
            <>
              <h5>Preparation checks</h5>
              {preview.findings.length === 0 ? (
                <p>
                  <Status tone="pass">No findings</Status> No measured damage to the line work.
                </p>
              ) : (
                <ul className="plain-list" aria-label="Preparation findings">
                  {preview.findings.map((finding) => (
                    <li key={finding.code}>
                      <Status tone={TONE[finding.severity]}>
                        {finding.severity === 'blocking' ? 'Blocking' : 'Warning'}
                      </Status>{' '}
                      {finding.message}
                    </li>
                  ))}
                </ul>
              )}
              <details>
                <summary>Measurements</summary>
                <dl className="facts">
                  {MEASURES.map(([key, label]) => (
                    <div key={key}>
                      <dt>{label}</dt>
                      <dd>{measure(preview.measures[key], key)}</dd>
                    </div>
                  ))}
                </dl>
                <p className="small muted">
                  Thresholds were calibrated on synthetic fixtures. They flag measurable damage to
                  the line work, not print quality. Preparation version{' '}
                  {preview.preparation_version}.
                </p>
              </details>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function Slider({
  label,
  min,
  max,
  step,
  value,
  onChange,
}: {
  label: string;
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (value: number) => void;
}) {
  // The label names the range input itself: wrapping an <output> too would make the
  // label belong to the output (the first labelable element) and leave the slider unnamed.
  const id = useId();
  return (
    <div className="adjust-field">
      <span>
        <label htmlFor={id}>{label}</label>
        <output htmlFor={id}>{value.toFixed(2)}</output>
      </span>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  );
}
