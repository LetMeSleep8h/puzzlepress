import { afterEach, expect, test, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Produce, type ProduceJob, type ProduceStatus } from './Produce';
import type { Project } from './types';

const project = { key: 'meadow', validation: { valid: true, issues: [] } } as Project;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const base: ProduceStatus = {
  key: 'meadow',
  revision: 'sha256-r1',
  directory: 'meadow-release',
  cancellable: true,
  run: null,
  release: null,
};
const job = (changes: Partial<ProduceJob> = {}): ProduceJob => ({
  job_id: '20261105T120000000000Z-aaaaaaaa',
  seq: 3,
  state: 'running',
  outcome: null,
  revision: 'sha256-r1',
  started: '2026-11-05T12:00:00.000Z',
  finished: null,
  step: 'interior',
  step_label: 'Building the interior PDF',
  steps: ['interior'],
  progress: null,
  seconds: 1.2,
  cancellable: true,
  cancel_requested: false,
  queue_position: null,
  release_preserved: null,
  error: null,
  notes: [],
  ...changes,
});
const running = (changes: Partial<ProduceJob> = {}): ProduceStatus => ({
  ...base,
  run: job(changes),
});
const verified: ProduceStatus['release'] = {
  verified: true,
  problem: null,
  engine: 'coloring',
  stale: false,
  files: [
    { name: 'interior.pdf', bytes: 2_000_000, sha256: 'a'.repeat(64) },
    { name: 'publishing/package.json', bytes: 900, sha256: 'b'.repeat(64) },
  ],
  validation: {
    blocking: [
      { source: 'publishing', code: 'content_rights_declared', message: 'Declare rights.' },
    ],
    warnings: [],
    manual_review: [{ source: 'interior_preflight', code: 'look_alike', message: 'Compare.' }],
    verified: ['page parity'],
  },
  package: true,
};
const done: ProduceStatus = {
  ...base,
  run: job({
    seq: 9,
    state: 'completed',
    outcome: 'blocked',
    step: 'release_swap',
    steps: ['interior', 'interior_preflight', 'release_verify', 'release_swap'],
    finished: '2026-11-05T12:01:00.000Z',
    seconds: 60,
    cancellable: false,
    result: { peak_memory_mb: 180.5 },
  }),
  release: verified,
};

afterEach(() => vi.restoreAllMocks());

test('starting a job shows Python steps and counted progress, then the verified release', async () => {
  const sent: { url: string; body?: unknown }[] = [];
  let polls = 0;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    sent.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url === '/api/projects/meadow/produce' && init?.method === 'POST')
      return json(running({ seq: 1, state: 'starting', step: null, steps: [] }));
    polls += 1;
    return json(
      polls === 1
        ? base
        : polls < 3
          ? running({
              seq: 5,
              progress: { stage: 'render_pages', done: 12, total: 40, label: 'pages drawn' },
            })
          : done,
    );
  });
  render(<Produce project={project} dirty={false} />);
  const user = userEvent.setup();
  expect(await screen.findByText('Nothing has been produced yet.')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Produce' }));
  expect(sent.find((c) => c.body)?.body).toEqual({ revision: 'sha256-r1' });
  expect(await screen.findByText(/12 of 40 pages drawn/, {}, { timeout: 5000 })).toBeVisible();
  expect(screen.getByRole('progressbar')).toHaveAttribute('max', '40');
  expect(screen.getByRole('button', { name: 'Producing…' })).toBeDisabled();
  await waitFor(() => expect(screen.getByText('Every file verified')).toBeVisible(), {
    timeout: 12000,
  });
  expect(screen.getAllByText('Finished with blocking findings')[0]).toBeVisible();
  expect(screen.getByText('180.5 MB')).toBeVisible();
  expect(screen.getByText(/content_rights_declared/)).toBeVisible();
  expect(screen.getByRole('link', { name: 'Download upload package (ZIP)' })).toHaveAttribute(
    'href',
    '/api/projects/meadow/produce/package.zip',
  );
  expect(screen.getByRole('link', { name: 'publishing/package.json' })).toHaveAttribute(
    'href',
    '/api/projects/meadow/produce/file?name=publishing%2Fpackage.json',
  );
  const steps = screen.getByRole('list', { name: 'Steps run' });
  expect(
    within(steps)
      .getAllByRole('listitem')
      .map((li) => li.textContent),
  ).toEqual(['interior', 'interior preflight', 'release verify', 'release swap']);
}, 15000); // Three one-second polls, plus a busy machine's margin.

test('no number is shown for a step Python did not count', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
    json(running({ progress: { stage: 'interior', done: null, total: null } })),
  );
  render(<Produce project={project} dirty={false} />);
  expect(await screen.findByText(/Building the interior PDF ·/)).toBeVisible();
  expect(screen.queryByRole('progressbar')).toBeNull();
  expect(screen.queryByText(/%/)).toBeNull();
});

test('cancelling asks first, then shows Python stopping the job', async () => {
  const cancels: string[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith('/cancel')) {
      cancels.push(url);
      return json(
        running({ seq: 4, state: 'cancelling', cancel_requested: true, cancellable: false }),
      );
    }
    return json({
      ...running(),
      release: {
        verified: false,
        problem: 'preflight.json differs from production.json.',
        files: [],
      },
    });
  });
  render(<Produce project={project} dirty={false} />);
  const user = userEvent.setup();
  expect(await screen.findByText(/does not match its manifest/)).toBeVisible();
  expect(screen.queryByRole('link', { name: /Download/ })).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Cancel production' }));
  const confirm = screen.getByRole('group', { name: /Stop this production job/ });
  expect(within(confirm).getByRole('button', { name: 'Stop production' })).toHaveFocus();
  await user.click(within(confirm).getByRole('button', { name: 'Keep running' }));
  expect(cancels).toEqual([]);
  await user.click(screen.getByRole('button', { name: 'Cancel production' }));
  await user.keyboard('{Enter}');
  expect(cancels).toHaveLength(1);
  expect(
    await screen.findByRole('button', { name: 'Stopping at the next safe point…' }),
  ).toBeDisabled();
});

test('a failed job explains itself, says the release is unchanged and offers a retry', async () => {
  const posts: unknown[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
    if (init?.method === 'POST') {
      posts.push(JSON.parse(String(init.body)));
      return json(
        running({ job_id: '20261105T130000000000Z-bbbbbbbb', seq: 1, state: 'starting' }),
      );
    }
    return json({
      ...base,
      run: job({
        state: 'interrupted',
        cancellable: false,
        finished: '2026-11-05T12:00:05.000Z',
        release_preserved: 'unchanged',
        error: {
          code: 'worker_exited',
          message: 'The worker stopped (exit code 9) before finishing.',
        },
      }),
      release: verified,
    });
  });
  render(<Produce project={project} dirty={false} />);
  const user = userEvent.setup();
  expect(await screen.findByText(/exit code 9/)).toBeVisible();
  expect(screen.getByText('worker_exited')).toBeVisible();
  expect(screen.getByText('The previous release is unchanged.')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Retry production' }));
  expect(posts).toEqual([{ revision: 'sha256-r1' }]);
  expect(await screen.findByText('Starting the worker')).toBeVisible();
});

test('a slow answer about an older view never replaces a newer one', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let resolveSlow: (value: Response) => void = () => {};
  let calls = 0;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    calls += 1;
    if (calls === 1) return json(running({ seq: 3, step_label: 'Checking the interior' }));
    if (calls === 2) return new Promise<Response>((resolve) => (resolveSlow = resolve));
    return json(running({ seq: 7, step_label: 'Writing the upload package' }));
  });
  render(<Produce project={project} dirty={false} />);
  expect(await screen.findByText(/Checking the interior/)).toBeVisible();
  await act(async () => vi.advanceTimersByTime(1100)); // Poll 2: slow.
  await act(async () => vi.advanceTimersByTime(1000)); // Poll 3: newer, answered first.
  expect(
    await screen.findByText(/Writing the upload package/, {}, { timeout: 5000 }),
  ).toBeVisible();
  await act(async () =>
    resolveSlow(json(running({ seq: 4, step_label: 'Checking the interior' }))),
  );
  expect(screen.getByText(/Writing the upload package/)).toBeVisible();
  expect(screen.queryByText(/Checking the interior/)).toBeNull();
  vi.useRealTimers();
});

test('unsaved changes block production of the saved source', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(base));
  render(<Produce project={project} dirty />);
  expect(await screen.findByRole('button', { name: 'Produce' })).toBeDisabled();
  expect(screen.getByText(/Save your changes first/)).toBeVisible();
});
