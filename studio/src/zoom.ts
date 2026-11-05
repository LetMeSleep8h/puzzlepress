// Page-view arithmetic for zoom and pan. Pure: a view never re-renders a PDF, it only
// draws the same raster (or Python's boxes) at another size and scroll position.

/** Fit the whole page, fit the width, or a fixed percentage of print size. */
export type ZoomMode = 'page' | 'width' | number;

export const ZOOM_STEPS = [25, 50, 75, 100, 150, 200, 300, 400];
export const CSS_PX_PER_PT = 96 / 72;

export interface Size {
  width: number;
  height: number;
}

/** CSS pixels per CSS pixel at print size (100% = the page's printed size). */
export function viewScale(mode: ZoomMode, viewport: Size, page: Size, gutter = 0): number {
  const width = Math.max(1, viewport.width - gutter);
  const height = Math.max(1, viewport.height - gutter);
  if (mode === 'width') return width / page.width;
  if (mode === 'page') return Math.min(width / page.width, height / page.height);
  return mode / 100;
}

/** The next step in `direction` from the current scale (as a percentage). */
export function stepZoom(percent: number, direction: 1 | -1): number {
  if (direction > 0) return ZOOM_STEPS.find((z) => z > percent + 0.5) ?? ZOOM_STEPS.at(-1)!;
  return [...ZOOM_STEPS].reverse().find((z) => z < percent - 0.5) ?? ZOOM_STEPS[0];
}

/**
 * Scroll offsets that keep the same content point under the viewport centre after the
 * scale changes from `before` to `after`.
 */
export function keepCentre(
  scroll: { left: number; top: number },
  viewport: Size,
  before: number,
  after: number,
): { left: number; top: number } {
  const ratio = after / before;
  return {
    left: Math.max(0, (scroll.left + viewport.width / 2) * ratio - viewport.width / 2),
    top: Math.max(0, (scroll.top + viewport.height / 2) * ratio - viewport.height / 2),
  };
}

/** A PDF-point rectangle (origin bottom-left) as an SVG rectangle (origin top-left). */
export function svgRect(
  box: { x: number; y: number; width: number; height: number },
  pageHeight: number,
) {
  return { x: box.x, y: pageHeight - box.y - box.height, width: box.width, height: box.height };
}
