import { expect, test, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import coloringProject from './fixtures/coloring-project.json';
import coloringListing from './fixtures/coloring-listing.json';
import libraryData from './fixtures/library.json';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

function mockApi(
  overrides: (url: string, init?: RequestInit) => Response | undefined = () => undefined,
) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const custom = overrides(url, init);
    if (custom) return custom;
    if (url === '/api/projects')
      return json({ projects: [...libraryData.projects, coloringProject] });
    if (url === '/api/projects/coloring-demo') return json(coloringProject);
    if (url === '/api/projects/coloring-demo/coloring') return json(coloringListing);
    throw new Error(`Unexpected request ${url}`);
  });
}

// Whole words only: "PuzzlePress" and "Print resolution" are not word-search terms.
const WORD_SEARCH_TERMS = /\b(puzzles?|solutions?|word search(es)?|word banks?|grids?)\b/i;

test('the library names a coloring book and counts its artwork', async () => {
  mockApi();
  render(<App />);
  const link = await screen.findByRole('link', { name: 'Synthetic Coloring Book' });
  const row = link.closest('article')!;
  expect(within(row).getByText('Type').nextElementSibling).toHaveTextContent('Coloring book');
  expect(within(row).getByText('Artwork').nextElementSibling).toHaveTextContent('2');
  expect(within(row).getByText('Pages').nextElementSibling).toHaveTextContent('2');
  expect(row).not.toHaveTextContent(WORD_SEARCH_TERMS);
  expect(within(row).queryByText(/^Profiles$/)).not.toBeInTheDocument();
});

test('a coloring book opens its own workspace without word-search sections', async () => {
  history.pushState(null, '', '/books/coloring-demo');
  mockApi();
  render(<App />);
  expect(await screen.findByRole('heading', { name: 'Start with the artwork.' })).toBeVisible();
  const nav = screen.getByRole('navigation', { name: 'Project' });
  expect(
    within(nav)
      .getAllByRole('link')
      .map((link) => link.textContent),
  ).toEqual(['Overview', 'Artwork', 'Print proof']);
  expect(screen.getByText('Book type').nextElementSibling).toHaveTextContent('Coloring book');
  expect(screen.getByRole('main')).not.toHaveTextContent(WORD_SEARCH_TERMS);
});

test('the artwork page shows Python facts, findings and duplicates', async () => {
  history.pushState(null, '', '/books/coloring-demo/artwork');
  mockApi();
  render(<App />);
  const list = await screen.findByRole('list', { name: 'Artwork' });
  const rows = within(list)
    .getAllByRole('listitem')
    .filter((item) => item.matches('.artwork-row'));
  expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByRole('heading', { name: 'Fox in the Ferns' })).toBeVisible();
  expect(within(rows[0]).getByText('300 DPI at full size')).toBeVisible();
  expect(within(rows[0]).getByText('Ready')).toBeVisible();
  expect(within(rows[1]).getByText('Blocking')).toBeVisible();
  expect(within(rows[1]).getByText(/line art needs 300/)).toBeVisible();
  expect(screen.getByText('1 with blocking problems')).toBeVisible();
  expect(screen.getByText('None found')).toBeVisible();
  expect(screen.getByRole('main')).not.toHaveTextContent(WORD_SEARCH_TERMS);
});

test('an import sends the raw file with the saved revision and reports refusals', async () => {
  history.pushState(null, '', '/books/coloring-demo/artwork');
  const sent: { url: string; type: string | null }[] = [];
  mockApi((url, init) => {
    if (!url.includes('/coloring/artwork?')) return undefined;
    sent.push({ url, type: new Headers(init?.headers).get('Content-Type') });
    return json(
      {
        error: {
          code: 'svg_not_supported',
          message: 'SVG artwork is not supported in this version.',
          issues: [],
        },
      },
      422,
    );
  });
  const user = userEvent.setup();
  render(<App />);
  const input = await screen.findByLabelText('Import artwork (PNG or JPEG, several at once)');
  await user.upload(input, new File(['<svg/>'], 'vector.svg', { type: 'image/svg+xml' }));
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('vector.svg: SVG artwork is not supported in this version.');
  expect(sent).toHaveLength(1);
  const query = new URLSearchParams(sent[0].url.split('?')[1]);
  expect(query.get('name')).toBe('vector.svg');
  expect(query.get('revision')).toBe(coloringListing.revision);
  expect(sent[0].type).toBe('image/svg+xml');
});

test('removing artwork that is on a page requires removing its pages too', async () => {
  history.pushState(null, '', '/books/coloring-demo/artwork');
  let removal: unknown;
  mockApi((url, init) => {
    if (!url.endsWith('/coloring/remove')) return undefined;
    removal = JSON.parse(String(init?.body));
    return json(coloringListing);
  });
  const user = userEvent.setup();
  render(<App />);
  const list = await screen.findByRole('list', { name: 'Artwork' });
  const row = within(list).getAllByRole('listitem')[0];
  await user.click(within(row).getByRole('button', { name: 'Remove…' }));
  const confirm = within(row).getByRole('button', { name: 'Remove from book' });
  expect(confirm).toBeDisabled();
  await user.click(within(row).getByRole('checkbox', { name: /Also remove its pages/ }));
  await user.click(confirm);
  expect(removal).toEqual({
    artwork: 'fox-in-the-ferns',
    revision: coloringListing.revision,
    with_pages: true,
  });
});
