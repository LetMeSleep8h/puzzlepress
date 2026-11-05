import { afterEach, expect, test, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Produce, type ProduceStatus } from './Produce';
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
const running = (step: string, steps: string[], cancel = false): ProduceStatus => ({
  ...base,
  run: {
    state: 'running',
    revision: 'sha256-r1',
    step,
    step_label: step === 'interior' ? 'Building the interior PDF' : 'Checking the interior',
    steps,
    seconds: 1.2,
    cancellable: true,
    cancel_requested: cancel,
    error: null,
    notes: [],
  },
});
const done: ProduceStatus = {
  ...base,
  run: { ...running('swap', ['interior', 'interior_preflight', 'swap']).run!, state: 'blocked' },
  release: {
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
  },
};

afterEach(() => vi.restoreAllMocks());

test('starting a run shows Python steps, then the verified release and its files', async () => {
  const sent: { url: string; body?: unknown }[] = [];
  let polls = 0;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    sent.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url === '/api/projects/meadow/produce' && init?.method === 'POST')
      return json(running('interior', ['interior']));
    polls += 1;
    return json(
      polls === 1
        ? base
        : polls < 3
          ? running('interior_preflight', ['interior', 'interior_preflight'])
          : done,
    );
  });
  render(<Produce project={project} dirty={false} />);
  const user = userEvent.setup();
  expect(await screen.findByText('Nothing has been produced yet.')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Produce' }));
  expect(sent.find((c) => c.body)?.body).toEqual({ revision: 'sha256-r1' });
  expect(await screen.findByText(/Building the interior PDF/)).toBeVisible();
  expect(screen.getByRole('button', { name: 'Producing…' })).toBeDisabled();
  await waitFor(() => expect(screen.getByText('Every file verified')).toBeVisible(), {
    timeout: 5000,
  });
  expect(screen.getByText('Finished with blocking findings')).toBeVisible();
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
  ).toEqual(['interior', 'interior preflight', 'swap']);
});

test('a coloring run can be cancelled; an unverified release offers no files', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('/cancel')) return json(running('interior', ['interior'], true));
    if (init?.method === 'POST') return json(running('interior', ['interior']));
    return json({
      ...running('interior', ['interior']),
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
  await user.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(await screen.findByRole('button', { name: 'Stopping at the next step…' })).toBeDisabled();
});

test('unsaved changes block production of the saved source', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
    json({ ...base, cancellable: false }),
  );
  render(<Produce project={project} dirty />);
  expect(await screen.findByRole('button', { name: 'Produce' })).toBeDisabled();
  expect(screen.getByText(/Save your changes first/)).toBeVisible();
});
