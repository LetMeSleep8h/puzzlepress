import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from 'react';
import { keepCentre, stepZoom, viewScale, ZOOM_STEPS, type Size, type ZoomMode } from './zoom';

/**
 * A zoomable, pannable view of one page (or spread) of known print size. Zooming only
 * resizes what is already drawn; nothing is requested again. Pan by dragging, by the
 * scroll bars, or with the arrow keys once the view has focus; `+`, `-` and `0` zoom.
 */
export function PageViewport({
  page,
  label,
  children,
}: {
  /** Print size in CSS pixels at 100%. */
  page: Size;
  label: string;
  children: (scale: number) => ReactNode;
}) {
  const view = useRef<HTMLDivElement>(null);
  const id = `${label.toLowerCase().replace(/\W+/g, '-')}-zoom`;
  const [mode, setMode] = useState<ZoomMode>('page');
  const [size, setSize] = useState<Size>({ width: 600, height: 700 });
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const [panning, setPanning] = useState(false);
  useEffect(() => {
    const element = view.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width && height) setSize({ width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const scale = viewScale(mode, size, page, 24);
  const previous = useRef(scale);
  // Keep the centre of the view on the same spot of the page while zooming.
  useLayoutEffect(() => {
    const element = view.current;
    if (element && previous.current !== scale) {
      const next = keepCentre(
        { left: element.scrollLeft, top: element.scrollTop },
        size,
        previous.current,
        scale,
      );
      element.scrollLeft = next.left;
      element.scrollTop = next.top;
    }
    previous.current = scale;
  }, [scale, size]);
  const percent = Math.round(scale * 100);
  const zoom = useCallback(
    (direction: 1 | -1) => setMode(stepZoom(Math.round(scale * 100), direction)),
    [scale],
  );
  const reset = () => {
    setMode('page');
    if (view.current) view.current.scrollTo?.({ left: 0, top: 0 });
  };
  const keys = (event: KeyboardEvent) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === '+' || event.key === '=') zoom(1);
    else if (event.key === '-') zoom(-1);
    else if (event.key === '0') reset();
    else return;
    event.preventDefault();
  };
  const down = (event: PointerEvent) => {
    const element = view.current;
    if (!element || event.button !== 0) return;
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
  const move = (event: PointerEvent) => {
    const element = view.current;
    const start = drag.current;
    if (!element || !start) return;
    element.scrollLeft = start.left - (event.clientX - start.x);
    element.scrollTop = start.top - (event.clientY - start.y);
  };
  const up = () => {
    drag.current = null;
    setPanning(false);
  };
  return (
    <div className="page-viewport">
      <div className="viewport-toolbar" role="toolbar" aria-label={`${label}: view`}>
        <button
          type="button"
          aria-label="Zoom out"
          disabled={percent <= ZOOM_STEPS[0]}
          onClick={() => zoom(-1)}
        >
          −
        </button>
        <label className="sr-only" htmlFor={id}>
          Zoom level
        </label>
        <select
          id={id}
          value={typeof mode === 'number' ? String(mode) : mode}
          onChange={(e) =>
            setMode(
              e.target.value === 'page' || e.target.value === 'width'
                ? e.target.value
                : Number(e.target.value),
            )
          }
        >
          <option value="page">Fit page</option>
          <option value="width">Fit width</option>
          {ZOOM_STEPS.map((z) => (
            <option key={z} value={z}>
              {z}%
            </option>
          ))}
        </select>
        <button
          type="button"
          aria-label="Zoom in"
          disabled={percent >= ZOOM_STEPS.at(-1)!}
          onClick={() => zoom(1)}
        >
          +
        </button>
        <button type="button" onClick={reset}>
          Reset view
        </button>
        <span className="small muted" aria-live="polite">
          {percent}% of print size
        </span>
      </div>
      <div
        ref={view}
        className={`viewport-canvas${panning ? ' panning' : ''}`}
        tabIndex={0}
        role="group"
        aria-label={`${label}. Drag or use the arrow keys to pan; plus, minus and 0 zoom.`}
        onKeyDown={keys}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
      >
        <div
          className="viewport-content"
          style={{ width: page.width * scale, height: page.height * scale }}
        >
          {children(scale)}
        </div>
      </div>
    </div>
  );
}
