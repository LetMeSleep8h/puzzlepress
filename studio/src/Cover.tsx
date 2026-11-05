import { useEffect, useRef, useState } from 'react';
import { ApiError, request } from './api';
import { CoverCanvas, OVERLAYS, ZOOMS, type Overlay } from './cover-canvas';
import {
  LayerInspector,
  PhotoInspector,
  Readiness,
  Failure,
  flaggedLayers,
} from './cover-inspector';
import {
  VIEWS,
  clamp,
  layerName,
  layerOf,
  panelOf,
  round,
  setLayer,
  starterCover,
  viewBox,
  type View,
} from './cover-model';
import { CoverTools, PhotoLibrary, Tabs, type ToolTab } from './cover-tools';
import { ConvertDialog, ElementInspector, RegionInspector } from './cover-elements';
import {
  ALLOWED,
  addElement,
  elementOf,
  moveElement,
  photoCrop,
  setPhotoCrop,
  updateElement,
} from './cover-elements-model';
import { DraftToolbar, type Draft } from './draft';
import type { Source } from './editor-fields';
import type {
  CoverAsset,
  CoverConfig,
  CoverDraft,
  CoverStatus,
  ElementRegion,
  Issue,
  PtBox,
} from './types';
import { ErrorState, Loading, Status } from './ui';

// Cover Studio. The preview is a PDFium raster of a real cover PDF rendered by
// Python from the draft; geometry, text boxes, crop windows, DPI, spine
// eligibility and verdicts all come from Python. This view edits authored values
// (choices, overrides, offsets in points, the normalized focal point) and maps
// pointer and key presses onto them; it never lays out a cover.

export { dragFocal, starterCover, viewBox } from './cover-model';

const STEP = 0.01;
const BIG_STEP = 0.05;
const UNDO_LIMIT = 50;
type Mode = 'wide' | 'medium' | 'narrow';
type Side = 'properties' | 'checks';
type Dock = 'tools' | Side;

function useMode(): Mode {
  const query = (width: number) =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(`(min-width: ${width}px)`).matches
      : true;
  const read = (): Mode => (query(1200) ? 'wide' : query(800) ? 'medium' : 'narrow');
  const [mode, setMode] = useState<Mode>(read);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const lists = [
      window.matchMedia('(min-width: 1200px)'),
      window.matchMedia('(min-width: 800px)'),
    ];
    const update = () => setMode(read());
    lists.forEach((list) => list.addEventListener?.('change', update));
    return () => lists.forEach((list) => list.removeEventListener?.('change', update));
    // read() only consults matchMedia.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return mode;
}

export function Cover({ d }: { d: Draft }) {
  const cover = d.draft.cover;
  const mode = useMode();
  const [status, setStatus] = useState<CoverStatus>();
  const [statusError, setStatusError] = useState<Error>();
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState<CoverDraft>();
  const [draftIssues, setDraftIssues] = useState<Issue[]>([]);
  const [draftError, setDraftError] = useState<Error>();
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [source, setSource] = useState<'draft' | 'built'>('draft');
  const [notice, setNotice] = useState('');
  const [overlays, setOverlays] = useState<Set<Overlay>>(new Set());
  const [view, setView] = useState<View>('wrap');
  const [zoom, setZoom] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [toolTab, setToolTab] = useState<ToolTab>('photo');
  const [region, setRegion] = useState<ElementRegion>('wrap');
  const [converting, setConverting] = useState(false);
  const [side, setSide] = useState<Side>('properties');
  const [dock, setDock] = useState<Dock>('tools');
  const [trial, setTrial] = useState<CoverAsset | null>(null);
  const [announce, setAnnounce] = useState('');
  const [focus, setFocus] = useState<{ box: PtBox; key: number } | null>(null);
  const history = useRef<CoverConfig[]>([]);
  const [epoch, setEpoch] = useState(d.epoch);
  const base = `/api/projects/${encodeURIComponent(d.key)}`;
  if (epoch !== d.epoch) {
    // A save, reload or revert starts a fresh undo history.
    setEpoch(d.epoch);
    history.current = [];
  }
  const latest = useRef(d.draft);
  latest.current =
    trial && d.draft.cover?.image
      ? ({
          ...d.draft,
          cover: { ...d.draft.cover, image: { path: trial.path, sha256: trial.sha256! } },
        } as Source)
      : d.draft;
  const signature = JSON.stringify([cover, d.draft.book, trial?.path]);

  useEffect(() => {
    const controller = new AbortController();
    setStatusError(undefined);
    request<CoverStatus>(`${base}/cover`, controller.signal)
      .then((data) => !controller.signal.aborted && setStatus(data))
      .catch((err: Error) => !controller.signal.aborted && setStatusError(err));
    return () => controller.abort();
  }, [base, d.saved.revision, attempt]);

  useEffect(() => {
    if (!cover) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setPending(true);
      request<CoverDraft>(`${base}/draft/cover`, controller.signal, { source: latest.current })
        .then((data) => {
          if (controller.signal.aborted) return;
          setDraft(data);
          setDraftIssues([]);
          setDraftError(undefined);
        })
        .catch((err: Error) => {
          if (controller.signal.aborted) return;
          if (err instanceof ApiError && err.code === 'invalid_project') setDraftIssues(err.issues);
          else setDraftError(err);
        })
        .finally(() => !controller.signal.aborted && setPending(false));
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // `signature` captures every draft value the cover depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, signature, d.saved.revision, attempt]);

  const update = (next: CoverConfig) => {
    if (!cover) return;
    if (next.back_text === undefined) delete next.back_text;
    history.current = [...history.current.slice(-(UNDO_LIMIT - 1)), cover];
    d.change({ ...d.draft, cover: next } as Source);
  };
  const undo = () => {
    const previous = history.current.at(-1);
    if (!previous) return;
    history.current = history.current.slice(0, -1);
    d.change({ ...d.draft, cover: previous } as Source);
    setAnnounce('Undid the last cover change.');
  };
  const select = (layer: string | null) => {
    setSelected(layer);
    if (layer) {
      setSide('properties');
      if (mode !== 'wide') setDock('properties');
    }
  };
  const nudgeCrop = (key: string, big: boolean) => {
    if (!cover || !selected) return false;
    const crop = photoCrop(cover, selected);
    if (!crop || elementOf(cover, selected)?.locked) return false;
    const step = big ? BIG_STEP : STEP;
    const { x, y, zoom: z } = crop;
    const moves: Record<string, Partial<typeof crop>> = {
      ArrowLeft: { x: round(clamp(x - step, 0, 1)) },
      ArrowRight: { x: round(clamp(x + step, 0, 1)) },
      ArrowUp: { y: round(clamp(y - step, 0, 1)) },
      ArrowDown: { y: round(clamp(y + step, 0, 1)) },
      '+': { zoom: round(clamp(z + (big ? 0.25 : 0.05), 1, 4)) },
      '=': { zoom: round(clamp(z + (big ? 0.25 : 0.05), 1, 4)) },
      '-': { zoom: round(clamp(z - (big ? 0.25 : 0.05), 1, 4)) },
      '0': { x: 0.5, y: 0.5, zoom: 1 },
    };
    const move = moves[key];
    if (!move) return false;
    update(setPhotoCrop(cover, selected, { ...crop, ...move }));
    return true;
  };
  const moveLayer = (layer: string, delta: { x: number; y: number }) => {
    if (!cover) return;
    if (layer.startsWith('element:')) {
      const next = moveElement(cover, layer.slice(8), delta.x, delta.y);
      if (next !== cover) update(next);
      return;
    }
    const offset = layerOf(cover, layer).offset ?? { x: 0, y: 0 };
    update(
      setLayer(cover, layer, {
        offset: { x: round(offset.x + delta.x, 2), y: round(offset.y + delta.y, 2) },
      }),
    );
  };
  const build = async () => {
    setBusy(true);
    setMessage(
      'Building the cover from the saved source and the built interior, then running preflight…',
    );
    try {
      const data = await request<CoverStatus>(`${base}/cover/build`, new AbortController().signal, {
        revision: d.saved.revision,
      });
      setStatus(data);
      setMessage(
        data.build?.success
          ? 'Cover built and preflight complete.'
          : 'The cover did not build. Nothing was written.',
      );
      if (data.build?.success) setSource('built');
    } catch (err) {
      setMessage(
        err instanceof ApiError && err.code === 'source_changed'
          ? 'The saved source changed on disk. Reload the project before building.'
          : err instanceof Error
            ? err.message
            : 'The build request did not complete.',
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
          A cover is sized from the built interior. Compose the book in Book, save, and build the
          interior in Print first.
        </p>
      </section>
    );
  const issues = [...d.issues, ...draftIssues];
  if (!cover)
    return (
      <div className="editor cover-studio">
        <DraftToolbar
          d={d}
          title="Cover"
          jump={{ href: '#cover-start', label: 'Choose a photo' }}
        />
        <section className="cover-start" id="cover-start">
          <h2>Start a cover from your photograph</h2>
          <p>
            Choose or import one of your own photographs. PuzzlePress copies it into this project,
            sizes the full wrap from the built interior, and sets the book&apos;s title, subtitle
            and author over it. Nothing is saved until you save.
          </p>
          <PhotoLibrary
            projectKey={d.key}
            cover={starterCover({ path: '', sha256: '' })}
            trial={null}
            onChoose={(asset) =>
              asset.sha256 &&
              d.change({
                ...d.draft,
                cover: starterCover({ path: asset.path, sha256: asset.sha256 }),
              } as Source)
            }
            notice={notice}
            setNotice={setNotice}
          />
        </section>
      </div>
    );
  const builtLayout = status?.state === 'current' ? (status.layout ?? undefined) : undefined;
  const showBuilt = source === 'built' && status?.preview;
  const stageLayout = showBuilt ? (builtLayout ?? draft?.layout) : draft?.layout;
  const pdf = showBuilt ? status!.preview!.pdf_sha256 : draft?.preview?.pdf_sha256;
  const scales = (showBuilt ? status!.preview!.scales : draft?.preview?.scales) ?? { preview: 1 };
  const checks = draft?.checks ?? [];
  const blocking = checks.filter((c) => c.severity === 'error').length;
  const resolution = draft?.layout?.resolution;
  const interactive = !showBuilt && Boolean(draft?.success) && !trial;

  const choosePhoto = (asset: CoverAsset) => {
    if (!asset.sha256) return;
    const image = { path: asset.path, sha256: asset.sha256 };
    setTrial(null);
    if (cover.image) {
      update({ ...cover, image });
      return;
    }
    const chosen = elementOf(cover, selected);
    if (chosen?.type === 'photo') {
      update(updateElement(cover, chosen.id, { image }));
      return;
    }
    const layout = draft?.layout;
    if (!layout || !ALLOWED.photo.includes(region)) {
      setNotice('Photographs go on the back, the front or the full wrap, not the spine.');
      return;
    }
    const [next, layer] = addElement(cover, 'photo', region, layout, image);
    update(next);
    select(layer);
  };
  const tools = (
    <CoverTools
      tab={toolTab}
      setTab={setToolTab}
      projectKey={d.key}
      source={d.draft}
      cover={cover}
      layout={draft?.layout}
      library={draft?.library}
      display={draft?.display}
      selected={selected}
      region={region}
      onRegion={(next) => {
        setRegion(next);
        setView(next === 'wrap' ? 'wrap' : next);
        if (cover.regions) select(`region:${next}`);
      }}
      onSelect={select}
      update={update}
      issues={issues}
      trial={trial}
      onTrial={(asset) => {
        setTrial(asset);
        setSource('draft');
      }}
      onChoosePhoto={choosePhoto}
      onConvert={() => setConverting(true)}
      onApplyTemplate={(next, template) => {
        update(next);
        setSelected(null);
        setTrial(null);
        setAnnounce(
          `Applied the ${template.name} template to the draft. Undo restores the previous cover.`,
        );
      }}
      notice={notice}
      setNotice={setNotice}
    />
  );
  const element = elementOf(cover, selected);
  const firstPhoto = draft?.layout?.photos?.[0]?.layer ?? (cover.image ? 'photo' : null);
  const properties = element ? (
    <ElementInspector
      element={element}
      cover={cover}
      layout={draft?.layout}
      library={draft?.library}
      checks={checks}
      issues={issues}
      update={update}
      onSelect={select}
    />
  ) : selected?.startsWith('region:') || (!selected && !cover.image) ? (
    <RegionInspector
      cover={cover}
      region={(selected?.slice(7) as ElementRegion | undefined) ?? region}
      issues={issues}
      update={update}
    />
  ) : selected && selected !== 'photo' ? (
    <LayerInspector
      layer={selected}
      cover={cover}
      book={d.draft.book}
      library={draft?.library}
      layout={draft?.layout}
      checks={checks}
      issues={issues}
      update={update}
      onSelect={select}
    />
  ) : cover.crop && cover.image ? (
    <PhotoInspector
      name={cover.image.path}
      crop={cover.crop}
      path="cover.crop"
      resolution={resolution}
      center={draft?.layout?.photo?.center}
      onCrop={(crop) => update({ ...cover, crop })}
      issues={issues}
    />
  ) : null;
  const readiness = statusError ? (
    <ErrorState error={statusError} retry={() => setAttempt((n) => n + 1)} />
  ) : (
    <Readiness
      dirty={d.dirty}
      draft={draft}
      status={status}
      busy={busy}
      onBuild={() => void build()}
      onSelect={select}
    />
  );
  function selectionBox(layer: string | null): PtBox | undefined {
    const layout = draft?.layout;
    if (!layer || !layout) return undefined;
    return (
      layout.elements?.find((e) => e.layer === layer)?.bounds ??
      layout.texts.find((t) => t.layer === layer)?.box ??
      (layer === 'photo' ? layout.photo?.region : undefined)
    );
  }
  function fitSelection() {
    const layout = draft?.layout;
    const target = selectionBox(selected);
    if (!layout || !target || !cover || !selected) return;
    const element = elementOf(cover, selected);
    const panel =
      element && element.region !== 'wrap'
        ? element.region
        : selected === 'photo' || element
          ? 'wrap'
          : panelOf(selected, cover);
    const frame = viewBox(layout.geometry, panel);
    const room = Math.min(frame.width / target.width, frame.height / target.height) * 0.6;
    const next = [...ZOOMS].reverse().find((z) => z <= room) ?? 1;
    setView(panel);
    setZoom(next);
    setFocus({ box: target, key: Date.now() });
    setAnnounce(`Zoomed to ${layerName(cover, selected)}.`);
  }
  const sideTabs = [
    ['properties', 'Properties'],
    ['checks', blocking ? `Checks (${blocking})` : 'Checks'],
  ] as const;

  return (
    <div
      className="editor cover-studio"
      onKeyDown={(event) => {
        const editable = (event.target as HTMLElement).closest?.('input, textarea, select');
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !editable) {
          undo();
          event.preventDefault();
        }
      }}
    >
      <DraftToolbar d={d} title="Cover" jump={{ href: '#cover-canvas', label: 'Skip to canvas' }} />
      <p role="status" aria-live="polite" className="sr-only">
        {announce}
      </p>
      <div className={`cover-workspace mode-${mode}`}>
        {mode === 'wide' && tools}
        <section className="cover-stage" aria-label="Cover preview" id="cover-canvas" tabIndex={-1}>
          <div className="stage-toolbar" role="toolbar" aria-label="Canvas">
            <span className="group-label" id="cover-preview-label">
              Preview
            </span>
            <div role="group" aria-labelledby="cover-preview-label" className="segmented-inline">
              {VIEWS.map(([key, name]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={view === key}
                  onClick={() => {
                    setView(key);
                    setRegion(key);
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
            <div role="group" aria-label="Canvas zoom" className="segmented-inline">
              <button
                type="button"
                aria-label="Zoom out"
                disabled={zoom <= ZOOMS[0]}
                onClick={() =>
                  setZoom(ZOOMS[Math.max(0, ZOOMS.indexOf(zoom as (typeof ZOOMS)[number]) - 1)])
                }
              >
                −
              </button>
              <button type="button" aria-pressed={zoom === 1} onClick={() => setZoom(1)}>
                {zoom === 1 ? 'Fit' : `${Math.round(zoom * 100)}%`}
              </button>
              <button
                type="button"
                aria-label="Zoom in"
                disabled={zoom >= ZOOMS[ZOOMS.length - 1]}
                onClick={() =>
                  setZoom(
                    ZOOMS[
                      Math.min(ZOOMS.length - 1, ZOOMS.indexOf(zoom as (typeof ZOOMS)[number]) + 1)
                    ],
                  )
                }
              >
                +
              </button>
            </div>
            <details className="menu">
              <summary>Overlays{overlays.size ? ` (${overlays.size})` : ''}</summary>
              <fieldset className="menu-body" disabled={showBuilt ? !builtLayout : !draft?.success}>
                <legend>Guides drawn from Python geometry (never in the PDF)</legend>
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
                      <span className={`overlay-key cover-${key}`} aria-hidden="true" />
                      {label}
                      <small>{hint}</small>
                    </span>
                  </label>
                ))}
              </fieldset>
            </details>
            <button
              type="button"
              disabled={!selectionBox(selected)}
              title="Zoom to the selected layer"
              onClick={() => fitSelection()}
            >
              Fit selection
            </button>
            <button
              type="button"
              disabled={history.current.length === 0}
              onClick={undo}
              aria-keyshortcuts="Control+Z"
            >
              Undo
            </button>
            <div
              role="group"
              aria-label="Draft or built cover"
              className="segmented-inline stage-source"
            >
              <button type="button" aria-pressed={!showBuilt} onClick={() => setSource('draft')}>
                Draft
              </button>
              <button
                type="button"
                aria-pressed={Boolean(showBuilt)}
                disabled={!status?.preview}
                onClick={() => setSource('built')}
              >
                Built PDF
              </button>
            </div>
          </div>
          {converting && (
            <ConvertDialog
              projectKey={d.key}
              source={d.draft}
              onClose={() => setConverting(false)}
              onUse={(next) => {
                update(next);
                setConverting(false);
                setSelected(null);
                setToolTab('layers');
                setAnnounce('Converted to a region design. Undo restores the previous layout.');
              }}
            />
          )}
          {trial && cover.image && (
            <div className="compare-bar" role="status">
              <span>
                Comparing <strong>{trial.path.replace('cover-assets/', '')}</strong>; not applied.
              </span>
              <button
                type="button"
                className="primary small-button"
                onClick={() => {
                  update({ ...cover, image: { path: trial.path, sha256: trial.sha256! } });
                  setTrial(null);
                }}
              >
                Use this photo
              </button>
              <button type="button" className="small-button" onClick={() => setTrial(null)}>
                Keep current
              </button>
            </div>
          )}
          {draftError && !showBuilt && (
            <ErrorState error={draftError} retry={() => setAttempt((n) => n + 1)} />
          )}
          {draft && !draft.success && !showBuilt && (
            <Failure stage={draft.stage} diagnostics={draft.diagnostics ?? []} />
          )}
          {stageLayout && pdf ? (
            <CoverCanvas
              key={showBuilt ? 'built' : 'draft'}
              projectKey={d.key}
              layout={stageLayout}
              cover={cover}
              pdf={pdf}
              scales={scales}
              label={showBuilt ? 'Built cover.pdf' : trial ? 'Photo comparison' : 'Draft cover'}
              view={view}
              zoom={zoom}
              overlays={showBuilt && !builtLayout ? new Set() : overlays}
              interactive={interactive}
              selected={selected}
              flagged={flaggedLayers(checks)}
              onSelect={select}
              onCrop={(layer, focal) => {
                const crop = photoCrop(cover, layer);
                if (crop) update(setPhotoCrop(cover, layer, { ...crop, ...focal }));
              }}
              onNudgeCrop={nudgeCrop}
              onMoveLayer={moveLayer}
              onMoveElement={moveLayer}
              onAnnounce={setAnnounce}
              fitWidth={mode === 'narrow'}
              focus={focus}
            />
          ) : (
            !draftError &&
            !(draft && !draft.success) && <Loading>Rendering the draft cover from Python…</Loading>
          )}
          <div className="stage-footer">
            <span role="status" aria-live="polite">
              {pending
                ? 'Rendering the draft…'
                : message || (draft?.success ? 'Preview matches the draft.' : '')}
            </span>
            {selected && <span className="muted">Selected: {layerName(cover, selected)}</span>}
            {resolution && (
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  if (firstPhoto) select(firstPhoto);
                  setSide('properties');
                }}
              >
                <Status tone={resolution.status === 'ok' ? 'pass' : 'fail'}>
                  Photo {Math.round(resolution.effective_dpi)} DPI
                  {resolution.status === 'ok' ? '' : ` · needs ${resolution.minimum_dpi}`}
                </Status>
              </button>
            )}
            {stageLayout && (
              <span className="muted">
                {stageLayout.geometry.width_in.toFixed(3)} ×{' '}
                {stageLayout.geometry.height_in.toFixed(3)} in · spine{' '}
                {stageLayout.geometry.spine_width_in.toFixed(4)} in
                {d.draft.print?.profile.endsWith('-bleed') &&
                  ' · the interior is full bleed; the cover keeps its own 0.125 in bleed and the same size'}
              </span>
            )}
          </div>
        </section>
        {mode === 'wide' ? (
          <aside className="cover-panel cover-inspector" aria-label="Inspector">
            <Tabs
              label="Inspector"
              tabs={sideTabs}
              value={side}
              onChange={setSide}
              idPrefix="cover-side"
            />
            <div
              role="tabpanel"
              id={`cover-side-panel-${side}`}
              aria-labelledby={`cover-side-tab-${side}`}
              className="panel-body"
            >
              {side === 'properties' ? properties : readiness}
            </div>
          </aside>
        ) : (
          <aside className="cover-panel cover-dock" aria-label="Cover panels">
            <Tabs
              label="Cover panels"
              tabs={[['tools', 'Tools'], ...sideTabs] as const}
              value={dock}
              onChange={setDock}
              idPrefix="cover-dock"
            />
            <div
              role="tabpanel"
              id={`cover-dock-panel-${dock}`}
              aria-labelledby={`cover-dock-tab-${dock}`}
              className="panel-body"
            >
              {dock === 'tools' ? tools : dock === 'properties' ? properties : readiness}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
