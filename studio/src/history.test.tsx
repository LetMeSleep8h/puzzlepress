import { expect, test } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { recordEdit, stepBack, stepForward, useHistory, HISTORY_LIMIT } from './history';
import { keepCentre, stepZoom, svgRect, viewScale } from './zoom';

test('edits, undo and redo move between values and drop the redo branch', () => {
  let state = recordEdit<string>({ past: [], future: [] }, 'a');
  state = recordEdit(state, 'b'); // now showing 'c'
  const [back, afterBack] = stepBack(state, 'c')!;
  expect(back).toBe('b');
  const [forward, afterForward] = stepForward(afterBack, back)!;
  expect(forward).toBe('c');
  expect(afterForward).toEqual(state);
  expect(recordEdit(afterBack, 'b').future).toEqual([]);
  expect(stepBack({ past: [], future: [] }, 'x')).toBeNull();
  expect(stepForward({ past: [], future: [] }, 'x')).toBeNull();
  let long = { past: [] as number[], future: [] as number[] };
  for (let i = 0; i < HISTORY_LIMIT + 10; i++) long = recordEdit(long, i);
  expect(long.past).toHaveLength(HISTORY_LIMIT);
});

test('the hook groups one gesture, resets on a new epoch and reports disabled states', () => {
  let value = 0;
  const { result, rerender } = renderHook(
    ({ epoch }) => useHistory(value, (n) => (value = n), epoch),
    {
      initialProps: { epoch: 0 },
    },
  );
  expect(result.current.canUndo).toBe(false);
  act(() => result.current.edit(1, 'drag'));
  rerender({ epoch: 0 });
  act(() => result.current.edit(2, 'drag'));
  rerender({ epoch: 0 });
  act(() => result.current.edit(3));
  rerender({ epoch: 0 });
  expect(result.current.canUndo).toBe(true);
  act(() => void result.current.undo());
  rerender({ epoch: 0 });
  expect(value).toBe(2);
  act(() => void result.current.undo());
  rerender({ epoch: 0 });
  expect(value).toBe(0); // The two drag steps were one undo step.
  expect(result.current.canUndo).toBe(false);
  expect(result.current.canRedo).toBe(true);
  act(() => void result.current.redo());
  rerender({ epoch: 0 });
  expect(value).toBe(2);
  rerender({ epoch: 1 }); // Saved: nothing to undo past the saved source.
  expect(result.current.canUndo).toBe(false);
  expect(result.current.canRedo).toBe(false);
});

test('zoom fits the page or width, steps, keeps the centre and maps PDF boxes', () => {
  const page = { width: 816, height: 1056 };
  expect(viewScale('page', { width: 408, height: 2000 }, page)).toBe(0.5);
  expect(viewScale('page', { width: 2000, height: 528 }, page)).toBe(0.5);
  expect(viewScale('width', { width: 1632, height: 100 }, page)).toBe(2);
  expect(viewScale(150, { width: 1, height: 1 }, page)).toBe(1.5);
  expect(stepZoom(100, 1)).toBe(150);
  expect(stepZoom(60, -1)).toBe(50);
  expect(stepZoom(400, 1)).toBe(400);
  expect(stepZoom(25, -1)).toBe(25);
  expect(keepCentre({ left: 0, top: 0 }, { width: 100, height: 100 }, 1, 2)).toEqual({
    left: 50,
    top: 50,
  });
  expect(svgRect({ x: 10, y: 20, width: 30, height: 40 }, 792)).toEqual({
    x: 10,
    y: 732,
    width: 30,
    height: 40,
  });
});
