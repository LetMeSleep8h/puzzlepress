import { expect, test } from 'vitest';
import { isActive, isNewer, preservedText, progressText, stateText } from './produce-state';

const a = '20261105T120000000000Z-aaaaaaaa';
const b = '20261105T130000000000Z-bbbbbbbb';

test('views of a newer job or a later event replace what is shown; older ones never do', () => {
  expect(isNewer(undefined, { job_id: a, seq: 0 })).toBe(true);
  expect(isNewer({ job_id: a, seq: 3 }, { job_id: a, seq: 4 })).toBe(true);
  expect(isNewer({ job_id: a, seq: 3 }, { job_id: a, seq: 3 })).toBe(true);
  expect(isNewer({ job_id: a, seq: 3 }, { job_id: a, seq: 2 })).toBe(false);
  expect(isNewer({ job_id: a, seq: 9 }, { job_id: b, seq: 0 })).toBe(true);
  expect(isNewer({ job_id: b, seq: 0 }, { job_id: a, seq: 9 })).toBe(false);
  expect(isNewer({ job_id: a, seq: 1 }, null)).toBe(false);
});

test('only queued, starting, running and cancelling jobs are followed', () => {
  expect(['queued', 'starting', 'running', 'cancelling'].every((s) => isActive(s as never))).toBe(
    true,
  );
  expect(
    ['completed', 'failed', 'cancelled', 'interrupted'].some((s) => isActive(s as never)),
  ).toBe(false);
  expect(isActive(undefined)).toBe(false);
});

test('progress is shown only for counted work units', () => {
  expect(progressText(null)).toBeNull();
  expect(progressText({ stage: 'interior', done: null, total: null })).toBeNull();
  expect(progressText({ stage: 'render_pages', done: 0, total: 0 })).toBeNull();
  expect(progressText({ stage: 'render_pages', done: 3, total: 9, label: 'pages drawn' })).toBe(
    '3 of 9 pages drawn',
  );
  expect(progressText({ stage: 'render_pages', done: 3, total: 9 })).toBe('3 of 9 render pages');
});

test('completed jobs are told apart by outcome, and failures from cancellations', () => {
  expect(stateText('completed', 'ready')).toEqual(['Complete: nothing blocks', 'pass']);
  expect(stateText('completed', 'blocked')[1]).toBe('review');
  expect(stateText('cancelled', null)[1]).toBe('neutral');
  expect(stateText('failed', null)[1]).toBe('fail');
  expect(preservedText('unchanged')).toMatch(/unchanged/);
  expect(preservedText(null)).toBeNull();
});
