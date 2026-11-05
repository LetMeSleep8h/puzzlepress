import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from './App';
import libraryData from './fixtures/library.json';
import project from './fixtures/coloring-print-project.json';
import built from './fixtures/coloring-interior.json';
import missing from './fixtures/coloring-interior-missing.json';

// Fixtures are the Studio API's own output for a SYNTHETIC coloring book
// (tests/web/test_coloring_print_api.py checks they still match it).
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

function mockApi(status: object, after: object = built) {
  const calls: string[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input);
    calls.push(url);
    if (url === '/api/projects') return json({ projects: [...libraryData.projects, project] });
    if (url === '/api/projects/coloring-print') return json(project);
    if (url === '/api/projects/coloring-print/interior') return json(status);
    if (url === '/api/projects/coloring-print/interior/build')
      return json({ build: { success: true }, ...after });
    throw new Error(`Unexpected request ${url}`);
  });
  history.pushState(null, '', '/books/coloring-print/print');
  render(<App />);
  return calls;
}

const WORD_SEARCH_TERMS = /\b(puzzles?|solutions?|word search(es)?|word banks?|grids?)\b/i;

test('the coloring proof shows physical pages, blank backs and manual-review prompts', async () => {
  mockApi(built);
  const verdict = await screen.findByLabelText('Preflight status');
  expect(within(verdict).getByText('Valid')).toBeVisible();
  expect(within(verdict).getByText('Not ready')).toBeVisible();
  expect(
    within(verdict).getByRole('link', { name: '3 blocking · 1 warning · 1 to review' }),
  ).toBeVisible();
  const nav = screen.getByRole('navigation', { name: 'Project' });
  expect(
    within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent),
  ).toEqual([
    'Overview',
    'Settings',
    'Artwork',
    'Pages',
    'Cover',
    'Print proof',
    'Publishing',
    'Produce',
  ]);
  // Every physical page, including each drawing's blank back, is a thumbnail.
  const pages = screen.getByRole('navigation', { name: 'Pages' });
  const thumbs = within(pages).getAllByRole('button');
  expect(thumbs).toHaveLength(6);
  expect(thumbs[2]).toHaveAccessibleName(
    /^Page 3 · Recto \(right\) · Coloring page · number 3 printed, 1 blocking/,
  );
  expect(thumbs[3]).toHaveAccessibleName('Page 4 · Verso (left) · Intentional blank');
  await userEvent.setup().click(thumbs[3]);
  expect(screen.getAllByText('Blank: back of the coloring page')[0]).toBeVisible();
  const findings = screen.getByRole('region', { name: 'Preflight findings' });
  expect(within(findings).getByRole('heading', { name: 'Manual review (1)' })).toBeVisible();
  expect(within(findings).queryByRole('heading', { name: /Information/ })).toBeNull();
  expect(within(findings).getAllByText('Manual review')[0]).toBeVisible();
  // Both low-resolution pages name the pixels the placement needs.
  expect(within(findings).getAllByText(/Supply at least 2020 x 2717 pixels/)).toHaveLength(2);
  const download = screen.getByRole('link', { name: 'Download interior.pdf' });
  expect(download).toHaveAttribute(
    'href',
    `/api/projects/coloring-print/interior/pdf?pdf=${built.preview.pdf_sha256}`,
  );
  expect(screen.getByRole('main')).not.toHaveTextContent(WORD_SEARCH_TERMS);
});

test('a stale coloring interior offers a rebuild but no production rebuilds', async () => {
  const stale = {
    ...built,
    state: 'stale',
    report: {
      ...built.report,
      findings: [
        ...built.report.findings,
        {
          ...built.report.findings[0],
          rule: 'source_current',
          scope: 'structural',
          message: 'The project source changed after this interior was built. Rebuild it.',
        },
      ],
    },
  };
  mockApi(stale);
  expect(await screen.findByText('This interior is out of date.')).toBeVisible();
  const banner = screen
    .getByText('This interior is out of date.')
    .closest('.stale-banner') as HTMLElement;
  expect(
    within(banner).getByText(
      'The project source changed after this interior was built. Rebuild it.',
    ),
  ).toBeVisible();
  expect(screen.getAllByRole('button', { name: 'Rebuild interior' })[0]).toBeEnabled();
  expect(screen.queryByRole('button', { name: /Rebuild outdated artifacts/ })).toBeNull();
});

test('a coloring book without an interior builds it from the saved source', async () => {
  const calls = mockApi(missing);
  expect(await screen.findByText('No interior has been built.')).toBeVisible();
  expect(screen.queryByRole('link', { name: 'Download interior.pdf' })).toBeNull();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Build interior' }));
  expect(await screen.findByText('Interior built and preflight complete.')).toBeVisible();
  expect(calls).toContain('/api/projects/coloring-print/interior/build');
  expect(screen.getByRole('link', { name: 'Download interior.pdf' })).toBeVisible();
});
