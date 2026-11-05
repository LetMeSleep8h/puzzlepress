import { useCallback, useEffect, useRef, useState } from 'react';

// Scoped undo/redo over one value (a draft source). The history belongs to the hook's
// owner: one project's editor, never another's. It covers unsaved edits only: a save,
// reload or revert (a new `epoch`) starts it afresh, so nothing ever undoes past the
// saved source. Destructive or remote actions (asset deletion, exports) never pass
// through it.

export interface HistoryState<T> {
  past: T[];
  future: T[];
}

export const HISTORY_LIMIT = 50;

/** Record `current` before it is replaced by an edit; any redo branch is dropped. */
export function recordEdit<T>(state: HistoryState<T>, current: T, limit = HISTORY_LIMIT) {
  return { past: [...state.past, current].slice(-limit), future: [] };
}

/** Step back: the value to show, and the history that remembers `current` for redo. */
export function stepBack<T>(state: HistoryState<T>, current: T): [T, HistoryState<T>] | null {
  if (!state.past.length) return null;
  const previous = state.past[state.past.length - 1];
  return [previous, { past: state.past.slice(0, -1), future: [current, ...state.future] }];
}

export function stepForward<T>(state: HistoryState<T>, current: T): [T, HistoryState<T>] | null {
  if (!state.future.length) return null;
  const [next, ...rest] = state.future;
  return [next, { past: [...state.past, current], future: rest }];
}

export interface History<T> {
  /**
   * Apply an edit, remembering the value it replaces. Consecutive edits with the same
   * `group` (one slider drag, one field being typed) are one undo step.
   */
  edit: (next: T, group?: string) => void;
  undo: () => boolean;
  redo: () => boolean;
  canUndo: boolean;
  canRedo: boolean;
}

/**
 * Undo/redo for `value`, applied through `apply` (for example a draft's `change`).
 * `epoch` marks the saved source: when it changes, the history is cleared.
 */
export function useHistory<T>(value: T, apply: (next: T) => void, epoch: number): History<T> {
  const [state, setState] = useState<HistoryState<T>>({ past: [], future: [] });
  const latest = useRef({ value, state, apply });
  latest.current = { value, state, apply };
  useEffect(() => setState({ past: [], future: [] }), [epoch]);
  const group = useRef<string | undefined>(undefined);
  useEffect(() => {
    group.current = undefined;
  }, [epoch]);
  const edit = useCallback((next: T, name?: string) => {
    const { value: current, apply: write } = latest.current;
    if (!name || name !== group.current) setState((now) => recordEdit(now, current));
    group.current = name;
    write(next);
  }, []);
  const move = useCallback((step: typeof stepBack) => {
    const { value: current, state: now, apply: write } = latest.current;
    const result = step(now, current);
    group.current = undefined;
    if (!result) return false;
    setState(result[1]);
    write(result[0] as T);
    return true;
  }, []);
  return {
    edit,
    undo: useCallback(() => move(stepBack), [move]),
    redo: useCallback(() => move(stepForward), [move]),
    canUndo: state.past.length > 0,
    canRedo: state.future.length > 0,
  };
}

function editingText(target: EventTarget | null) {
  const element = target as HTMLElement | null;
  return Boolean(element?.closest?.('input, textarea, select, [contenteditable="true"]'));
}

/**
 * Ctrl/Cmd+Z undoes, Ctrl/Cmd+Shift+Z and Ctrl+Y redo, while `enabled`. A text field
 * keeps its own undo, so shortcuts typed in one are left to the browser.
 */
export function useUndoShortcuts(enabled: boolean, undo: () => boolean, redo: () => boolean) {
  useEffect(() => {
    if (!enabled) return;
    const keys = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || editingText(event.target)) return;
      const key = event.key.toLowerCase();
      const wantsRedo = (key === 'z' && event.shiftKey) || (key === 'y' && !event.shiftKey);
      const wantsUndo = key === 'z' && !event.shiftKey;
      if (!wantsRedo && !wantsUndo) return;
      event.preventDefault();
      if (wantsUndo) undo();
      else redo();
    };
    document.addEventListener('keydown', keys);
    return () => document.removeEventListener('keydown', keys);
  }, [enabled, undo, redo]);
}
