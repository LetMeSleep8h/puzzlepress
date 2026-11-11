import { afterEach, expect, test, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Audit, auditCounts } from './Audit';
import { requestedPage } from './Print';
import type { AuditRecommendation, AuditResponse, Project } from './types';

const project = { key: 'meadow', revision: 'sha256-r1' } as Project;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const item = (changes: Partial<AuditRecommendation>): AuditRecommendation => ({
  code: 'odd_page_count',
  priority: 'high',
  category: 'print',
  basis: 'kdp_help',
  title: '29 pages: KDP will count 30',
  evidence: 'KDP rounds the page count up to an even number.',
  action: 'Make the page count even with real content.',
  area: 'book',
  field: null,
  source: 'https://kdp.amazon.com/en_US/help/topic/G201857950',
  pages: [29],
  puzzles: [],
  ...changes,
});
const response = (recommendations: AuditRecommendation[]): AuditResponse => ({
  key: 'meadow',
  revision: 'sha256-r1',
  collection: null,
  compared: [],
  markdown: '# Book audit: Meadow\n',
  audit: {
    kind: 'puzzlepress-book-audit',
    audit_version: 1,
    book_id: 'meadow',
    engine: 'word_search',
    title: 'Meadow',
    page_count: 29,
    counts: auditCounts(recommendations),
    recommendations,
    manual_checks: [
      {
        code: 'physical_proof',
        title: 'Order a proof',
        why: 'Only print shows it.',
        status: 'not_recorded',
      },
    ],
    levels: [
      {
        profile: 'gentle',
        puzzles: 3,
        first_puzzle: 'p1',
        last_puzzle: 'p5',
        grids: ['10 x 8'],
        words: { min: 3, max: 3 },
        allowed_directions: 2,
        allows_diagonal: false,
        allows_backward: false,
        placed_diagonal: { min: 0, max: 0 },
        placed_backward: { min: 0, max: 0 },
        longest_word: 6,
      },
    ],
    compared_books: [],
    not_assessed: ['Sales and rankings: no Amazon data.'],
    statement: 'PuzzlePress has no access to Amazon sales.',
  },
});

afterEach(() => vi.restoreAllMocks());

test('recommendations show priority, evidence, the source and page links into Print', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
    json(
      response([
        item({}),
        item({
          code: 'keyword_repeats_metadata',
          priority: 'medium',
          category: 'listing',
          title: 'Keyword repeats the title',
          area: 'publishing',
          field: 'publishing.keywords.0',
          pages: [],
        }),
      ]),
    ),
  );
  render(<Audit project={project} />);
  const list = await screen.findByRole('list', { name: /highest priority first/ });
  const entries = within(list).getAllByRole('listitem');
  expect(entries).toHaveLength(2);
  expect(within(entries[0]).getByText('High')).toBeTruthy();
  expect(within(entries[0]).getByRole('link', { name: '29' }).getAttribute('href')).toBe(
    '/books/meadow/print?page=29',
  );
  expect(within(entries[0]).getByRole('link', { name: 'KDP source' }).getAttribute('href')).toBe(
    'https://kdp.amazon.com/en_US/help/topic/G201857950',
  );
  expect(
    within(entries[1]).getByRole('link', { name: 'Open publishing' }).getAttribute('href'),
  ).toBe('/books/meadow/publishing');
  expect(screen.getByText('publishing.keywords.0')).toBeTruthy();
  expect(screen.getByText('1 high')).toBeTruthy();
  expect(screen.getByRole('table')).toBeTruthy();
  expect(screen.getByText('Sales and rankings: no Amazon data.')).toBeTruthy();
  expect(screen.getByText('Not recorded')).toBeTruthy();
});

test('the category filter narrows the list without recomputing anything', async () => {
  const fetch = vi
    .spyOn(globalThis, 'fetch')
    .mockImplementation(async () =>
      json(response([item({}), item({ code: 'x', category: 'listing', title: 'Listing item' })])),
    );
  render(<Audit project={project} />);
  await screen.findByText('Listing item');
  await userEvent.click(screen.getByRole('button', { name: 'Print' }));
  expect(screen.queryByText('Listing item')).toBeNull();
  expect(screen.getByText('29 pages: KDP will count 30')).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole('button', { name: 'Run again' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
});

test('an empty audit says so, and a failed one offers retry', async () => {
  let fail = true;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
    fail
      ? json(
          { error: { code: 'output_unavailable', message: 'Output unavailable.', issues: [] } },
          503,
        )
      : json(response([])),
  );
  render(<Audit project={project} />);
  expect(await screen.findByText(/Output unavailable/)).toBeTruthy();
  fail = false;
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(await screen.findByText('Nothing to recommend')).toBeTruthy();
});

test('coloring books link puzzle areas to Pages', async () => {
  const data = response([item({ area: 'edit', pages: [] })]);
  data.audit.engine = 'coloring';
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => json(data));
  render(<Audit project={project} />);
  expect((await screen.findByRole('link', { name: 'Open pages' })).getAttribute('href')).toBe(
    '/books/meadow/pages',
  );
});

test('a ?page=N link opens that page only when it exists', () => {
  expect(requestedPage('?page=12', 40)).toBe(12);
  expect(requestedPage('?page=41', 40)).toBe(1);
  expect(requestedPage('?page=0', 40)).toBe(1);
  expect(requestedPage('?page=2.5', 40)).toBe(1);
  expect(requestedPage('?page=abc', 40)).toBe(1);
  expect(requestedPage('', 40)).toBe(1);
});
