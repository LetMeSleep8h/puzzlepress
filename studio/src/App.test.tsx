import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, test, expect } from 'vitest';
import { App } from './App';
import { Inspector, Quality } from './Puzzles';
import type { Generation, Project } from './types';
import projectData from './fixtures/project.json';
import generationData from './fixtures/generation.json';
import libraryData from './fixtures/library.json';

const project: Project = projectData;
const generated: Generation = generationData;

function mockApi() {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input);
    return new Response(
      JSON.stringify(
        url.endsWith('/generation') ? generated : url === '/api/projects' ? libraryData : project,
      ),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    );
  });
}

test('library exposes real project content, accessible shell and search', async () => {
  mockApi();
  const user = userEvent.setup();
  render(<App />);
  expect(screen.getByRole('navigation', { name: 'Library' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main');
  expect(await screen.findByRole('link', { name: 'Garden Word Searches' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Automotive Word Search' })).toBeInTheDocument();
  const garden = screen.getByRole('link', { name: 'Garden Word Searches' }).closest('article')!;
  expect(within(garden).getByText('Type').nextElementSibling).toHaveTextContent('Word search');
  await user.type(screen.getByRole('searchbox'), 'garden');
  expect(screen.queryByRole('link', { name: 'Automotive Word Search' })).not.toBeInTheDocument();
  await user.clear(screen.getByRole('searchbox'));
  await user.type(screen.getByRole('searchbox'), 'no matching book');
  expect(screen.getByRole('heading', { name: 'No matching books' })).toBeInTheDocument();
});

test('project navigation reuses one generation and preserves stable deep links', async () => {
  const fetcher = mockApi();
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('link', { name: 'Garden Word Searches' }));
  expect(
    await screen.findByRole('heading', { name: 'The source at a glance' }),
  ).toBeInTheDocument();
  expect(location.pathname).toBe('/books/garden-demo');
  expect(screen.getByRole('main')).toHaveFocus();
  expect(screen.getByText('Book type').nextElementSibling).toHaveTextContent('Word search');
  await user.click(screen.getByRole('link', { name: 'Generate & review puzzles' }));
  await user.click(await screen.findByRole('link', { name: 'In the Flower Bed' }));
  expect(await screen.findByRole('table')).toBeInTheDocument();
  expect(location.pathname).toBe('/books/garden-demo/puzzles/flowers');
  await user.click(screen.getByRole('link', { name: 'Quality' }));
  expect(await screen.findByRole('heading', { name: 'A considered review' })).toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/generation'))).toHaveLength(1);
  expect(screen.getByRole('link', { name: 'Quality' })).toHaveAttribute('aria-current', 'page');
});

test.each(['flowers', 'herbs'])(
  'inspector renders exact grid and authoritative solution cells for %s',
  async (id) => {
    const user = userEvent.setup();
    const result = generated.report.puzzles.find((p) => p.id === id)!;
    render(<Inspector project={project} generation={generated} result={result} />);
    const table = screen.getByRole('table');
    expect(
      within(table)
        .getAllByRole('cell')
        .map((cell) => cell.textContent)
        .join(''),
    ).toBe(result.puzzle!.grid.join(''));
    expect(table.querySelectorAll('.solution-cell')).toHaveLength(0);
    const toggle = screen.getByRole('button', { name: 'Show solution' });
    toggle.focus();
    await user.keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    const expectedCells = new Set(
      Object.values(generated.solution_cells[id])
        .flat()
        .map((cell) => `${cell.x},${cell.y}`),
    );
    const actualCells = new Set(
      Array.from(table.querySelectorAll<HTMLElement>('.solution-cell')).map(
        (cell) => `${cell.dataset.x},${cell.dataset.y}`,
      ),
    );
    expect(actualCells).toEqual(expectedCells);
    expect(screen.getByRole('heading', { name: 'Solution register' })).toBeInTheDocument();
    expect(screen.getByText('Independently verified')).toBeInTheDocument();
    expect(screen.getByText(result.seed)).toBeInTheDocument();
    await user.keyboard(' ');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(table.querySelectorAll('.solution-cell')).toHaveLength(0);
  },
);

test('quality findings are review items and incomplete screening stays explicit', () => {
  const data = structuredClone(generated);
  data.report.clean = false;
  data.report.findings = [
    {
      code: 'scan_truncated',
      message: 'Screening is incomplete.',
      puzzle_ids: ['flowers'],
      words: [],
      severity: 'warning',
    },
  ];
  render(<Quality generation={data} />);
  expect(screen.getByText('Review findings')).toHaveClass('review');
  expect(screen.getByText('Screening is incomplete.')).toBeInTheDocument();
  expect(screen.queryByText('Generation failed')).not.toBeInTheDocument();
});

test('generation failure displays errors without a fake grid or quality pass', () => {
  const result = structuredClone(generated.report.puzzles[0]);
  result.puzzle = null;
  result.quality = null;
  result.errors = [
    { path: 'generation', code: 'search_exhausted', message: 'Search budget exhausted.' },
  ];
  render(<Inspector project={project} generation={generated} result={result} />);
  expect(screen.getByRole('heading', { name: 'Generation failed' })).toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Show solution' })).not.toBeInTheDocument();
  expect(screen.getByText(/Grid quality checks are unavailable/)).toBeInTheDocument();
});

test('empty project library is useful', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ projects: [] })));
  render(<App />);
  expect(
    await screen.findByRole('heading', { name: 'A place for your next puzzle book' }),
  ).toBeInTheDocument();
});

test('loading state is announced until API completes', () => {
  vi.spyOn(globalThis, 'fetch').mockReturnValue(new Promise(() => {}));
  render(<App />);
  expect(screen.getByRole('status')).toHaveTextContent('Reading the local book library');
});

test('network failure offers retry and recovers', async () => {
  const fetcher = vi
    .spyOn(globalThis, 'fetch')
    .mockRejectedValueOnce(new TypeError('Failed to fetch'))
    .mockImplementation(async () => new Response(JSON.stringify(libraryData)));
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Studio cannot reach the local server',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(await screen.findByRole('link', { name: 'Garden Word Searches' })).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

test('invalid project issues are rendered safely', async () => {
  history.replaceState(null, '', '/books/broken');
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({
        error: {
          code: 'invalid_project',
          message: 'Project validation failed.',
          issues: [{ path: 'book.title', code: 'type', message: '<script>invalid</script>' }],
        },
      }),
      { status: 422 },
    ),
  );
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Project validation failed');
  expect(screen.getByText(/<script>invalid/)).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
});

test('deep-link missing puzzle is distinguishable from generation failure', async () => {
  history.replaceState(null, '', '/books/garden-demo/puzzles/missing');
  mockApi();
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent('This puzzle is not defined');
});

test('API server errors render useful messages', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('unavailable', { status: 500 }));
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole('alert')).toHaveTextContent(
      'The server could not complete this request',
    ),
  );
});

test('the router leaves download links (template Export, interior.pdf) to the browser', async () => {
  // Regression: the client router used to swallow a template's Export click and push
  // the API URL as a Studio page ("This Studio page does not exist").
  mockApi();
  render(<App />);
  await screen.findByRole('link', { name: 'Garden Word Searches' });
  const start = location.pathname;
  const click = (link: HTMLAnchorElement) => {
    document.body.append(link);
    const event = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    link.dispatchEvent(event);
    link.remove();
    return event;
  };
  const exported = document.createElement('a');
  exported.href = '/api/projects/garden-demo/cover/templates/mine/export';
  exported.setAttribute('download', '');
  exported.textContent = 'Export';
  expect(click(exported).defaultPrevented).toBe(false);
  expect(location.pathname).toBe(start);
  // An ordinary same-origin link is still a Studio route.
  const page = document.createElement('a');
  page.href = '/books/garden-demo';
  expect(click(page).defaultPrevented).toBe(true);
  expect(location.pathname).toBe('/books/garden-demo');
});
