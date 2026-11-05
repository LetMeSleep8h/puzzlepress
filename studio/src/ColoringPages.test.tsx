import { afterEach, expect, test, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import pagesProject from './fixtures/coloring-pages-project.json';
import pagesPlan from './fixtures/coloring-pages-plan.json';
import type { ColoringPlanResult, Project } from './types';

// Fixtures are real Python output for tests/coloring_production.py (synthetic art).
const project = pagesProject as unknown as Project;
const plan = pagesPlan as unknown as ColoringPlanResult;
const WORD_SEARCH_TERMS = /\b(puzzles?|solutions?|word search(es)?|word banks?|grids?)\b/i;

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

type Body = { source: NonNullable<Project['source']>; revision?: string };

function mockApi(onPlan: (body: Body) => Response | Promise<Response> = () => json(plan)) {
  const saves: Body[] = [];
  const plans: Body[] = [];
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    if (url === '/api/projects/coloring-pages') return json(project);
    if (url === '/api/projects/coloring-pages/draft/plan') {
      plans.push(body!);
      return onPlan(body!);
    }
    if (url === '/api/projects/coloring-pages/interior')
      return json({
        key: 'coloring-pages',
        revision: project.revision,
        state: 'stale',
        report: null,
        preview: null,
        ruleset: 2,
      });
    if (url === '/api/projects/coloring-pages/draft/save') {
      saves.push(body!);
      return json({ ...project, revision: 'next', source: body!.source });
    }
    throw new Error(`Unexpected request ${url}`);
  });
  return { fetcher, saves, plans };
}

afterEach(() => {
  vi.useRealTimers();
});

function order() {
  const list = screen.getByRole('list', { name: 'Drawings and dividers in printing order' });
  return within(list)
    .getAllByRole('listitem')
    .map((item) => item.querySelector('strong')!.textContent);
}

async function open() {
  history.pushState(null, '', '/books/coloring-pages/pages');
  render(<App />);
  await screen.findByRole('heading', { name: 'Drawings and dividers' });
  await screen.findByText('Plan verified');
}

test('coloring books navigate to pages, cover and publishing in plain terms', async () => {
  mockApi();
  await open();
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
  expect(screen.getByRole('main')).not.toHaveTextContent(WORD_SEARCH_TERMS);
});

test('the preview shows Python physical pages, sides and automatic blanks', async () => {
  mockApi();
  await open();
  const pages = screen.getByRole('list', { name: 'Physical pages in order' });
  expect(within(pages).getAllByRole('figure')).toHaveLength(plan.plan.pages.length);
  expect(screen.getByText('Physical pages').nextElementSibling).toHaveTextContent('28');
  expect(screen.getAllByText(/Back of the page before/).length).toBe(12);
  expect(screen.getByText('Added so the drawings start on a right-hand page')).toBeVisible();
  // Each entry shows the PDF page Python planned for it.
  expect(screen.getByText('PDF page 5 · right-hand')).toBeVisible();
  expect(screen.getByText(/out of date/)).toBeVisible();
});

test('reordering by buttons and by drag edits the draft, re-plans and saves with the revision', async () => {
  const { saves, plans } = mockApi();
  const user = userEvent.setup();
  await open();
  expect(order().slice(0, 3)).toEqual(['shape-01', 'shape-02', 'shape-03']);
  await user.click(screen.getByRole('button', { name: 'Move shape-03 up' }));
  expect(order().slice(0, 3)).toEqual(['shape-01', 'shape-03', 'shape-02']);
  expect(screen.getByText('Moved shape-03 to position 2 of 12.')).toBeInTheDocument();
  // Drag the first row onto the third.
  const rows = document.querySelectorAll('ol.page-order > li');
  fireEvent.dragStart(rows[0], { dataTransfer: { effectAllowed: '' } });
  fireEvent.dragOver(rows[2]);
  fireEvent.drop(rows[2]);
  expect(order().slice(0, 3)).toEqual(['shape-03', 'shape-02', 'shape-01']);
  await waitFor(() =>
    expect(plans.at(-1)!.source.coloring!.pages.slice(0, 3)).toEqual([
      { artwork: 'shape-03' },
      { artwork: 'shape-02' },
      { artwork: 'shape-01' },
    ]),
  );
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(saves).toHaveLength(1));
  expect(saves[0].revision).toBe(project.revision);
  expect(saves[0].source.coloring!.pages[0]).toEqual({ artwork: 'shape-03' });
});

test('drawings are added, repeated and removed; dividers are edited; undo restores', async () => {
  mockApi();
  const user = userEvent.setup();
  await open();
  await user.click(screen.getByRole('button', { name: 'Use shape-02 again after this page' }));
  expect(order().slice(0, 4)).toEqual(['shape-01', 'shape-02', 'shape-02', 'shape-03']);
  expect(screen.getAllByText(/used 2 times/)).toHaveLength(2);
  await user.click(screen.getAllByRole('button', { name: 'Remove shape-02 from the book' })[1]);
  expect(order()).toHaveLength(12);
  await user.click(screen.getByRole('button', { name: 'Add section divider' }));
  const title = screen.getByLabelText('Divider title');
  await user.clear(title);
  await user.type(title, 'Garden');
  expect(order().at(-1)).toBe('Divider: Garden');
  await user.selectOptions(screen.getByLabelText('Drawing to add'), 'shape-07');
  await user.click(screen.getByRole('button', { name: 'Add drawing at the end' }));
  expect(order().at(-1)).toBe('shape-07');
  const undo = screen.getByRole('button', { name: 'Undo' });
  await user.click(undo);
  expect(order().at(-1)).toBe('Divider: Garden');
  expect(screen.getByRole('main')).not.toHaveTextContent(WORD_SEARCH_TERMS);
});

test('front matter, layout and numbering edit the composition the plan reads', async () => {
  const { plans } = mockApi();
  const user = userEvent.setup();
  await open();
  await user.click(screen.getByRole('checkbox', { name: /Blank backs/ }));
  await user.selectOptions(screen.getByLabelText('Page border'), 'double');
  await user.click(screen.getByRole('checkbox', { name: 'Coloring pages' }));
  await user.click(screen.getByRole('button', { name: 'Remove Instructions' }));
  await waitFor(() => {
    const source = plans.at(-1)!.source;
    expect(source.coloring!.layout).toEqual({ blank_reverse: false, border: 'double' });
    const composition = source.composition as unknown as {
      front_matter: { kind: string }[];
      page_numbers: { show_artwork: boolean };
    };
    expect(composition.page_numbers.show_artwork).toBe(true);
    expect(composition.front_matter.map((item) => item.kind)).toEqual([
      'title_page',
      'copyright_page',
    ]);
  });
});

test('a slow plan answer never replaces the plan of a newer draft', async () => {
  let release: (value: Response) => void = () => {};
  let calls = 0;
  const { plans } = mockApi(() => {
    calls += 1;
    if (calls === 2) return new Promise<Response>((resolve) => (release = resolve));
    if (calls === 3)
      return json({ ...plan, plan: { ...plan.plan, pages: plan.plan.pages.slice(0, 26) } });
    return json(plan);
  });
  const user = userEvent.setup();
  await open();
  await user.click(screen.getByRole('button', { name: 'Move shape-02 up' }));
  await waitFor(() => expect(plans).toHaveLength(2)); // held by the server
  await user.click(screen.getByRole('button', { name: 'Move shape-02 down' }));
  await waitFor(() =>
    expect(screen.getByText('Physical pages').nextElementSibling).toHaveTextContent('26'),
  );
  await act(async () => release(json(plan)));
  expect(screen.getByText('Physical pages').nextElementSibling).toHaveTextContent('26');
});

test('a busy Python is retried instead of shown as an error', async () => {
  let calls = 0;
  mockApi(() => {
    calls += 1;
    return calls === 1
      ? json(
          { error: { code: 'generation_busy', message: 'Generation is running.', issues: [] } },
          409,
        )
      : json(plan);
  });
  history.pushState(null, '', '/books/coloring-pages/pages');
  render(<App />);
  expect(await screen.findByText('Plan verified', {}, { timeout: 4000 })).toBeVisible();
  expect(screen.queryByText(/Generation is running/)).not.toBeInTheDocument();
  expect(calls).toBe(2);
});

test('an incomplete plan reports what blocks it', async () => {
  mockApi(() =>
    json({
      ...plan,
      plan: { ...plan.plan, complete: false },
      verification: {
        valid: false,
        issues: [
          {
            path: 'coloring.pages',
            code: 'no_coloring_pages',
            message: 'Add at least one drawing.',
          },
        ],
      },
    }),
  );
  history.pushState(null, '', '/books/coloring-pages/pages');
  render(<App />);
  expect(await screen.findByText(/Add at least one drawing/)).toBeVisible();
  expect(screen.getByText('Incomplete')).toBeVisible();
});

test('redo and keyboard shortcuts step through edits; a save clears the history', async () => {
  const { saves } = mockApi();
  const user = userEvent.setup();
  await open();
  const undo = screen.getByRole('button', { name: 'Undo' });
  const redo = screen.getByRole('button', { name: 'Redo' });
  expect(undo).toBeDisabled();
  expect(redo).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Move shape-03 up' }));
  await user.click(screen.getByRole('button', { name: 'Move shape-03 up' }));
  expect(order().slice(0, 3)).toEqual(['shape-03', 'shape-01', 'shape-02']);
  await user.keyboard('{Control>}z{/Control}');
  expect(order().slice(0, 3)).toEqual(['shape-01', 'shape-03', 'shape-02']);
  await user.click(undo);
  expect(order().slice(0, 3)).toEqual(['shape-01', 'shape-02', 'shape-03']);
  expect(undo).toBeDisabled();
  await user.keyboard('{Control>}{Shift>}z{/Shift}{/Control}');
  expect(order().slice(0, 3)).toEqual(['shape-01', 'shape-03', 'shape-02']);
  await user.click(redo);
  expect(order().slice(0, 3)).toEqual(['shape-03', 'shape-01', 'shape-02']);
  expect(redo).toBeDisabled();
  // Typing in a field keeps the browser's own undo: no page edit is undone.
  await user.click(screen.getByLabelText('Drawing to add'));
  await user.keyboard('{Control>}z{/Control}');
  expect(order()[0]).toBe('shape-03');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(saves).toHaveLength(1));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled());
});

test('the page designer replaces, places, duplicates and inserts around one entry', async () => {
  const { plans } = mockApi();
  const user = userEvent.setup();
  await open();
  await user.click(screen.getByRole('button', { name: 'Design shape-02' }));
  const designer = screen.getByRole('region', { name: /Designing entry 2: shape-02/ });
  expect(within(designer).getByText(/right-hand \(recto\)/)).toBeVisible();
  expect(within(designer).getByRole('toolbar', { name: 'Selected page: view' })).toBeVisible();
  await user.selectOptions(within(designer).getByLabelText('Drawing on this page'), 'shape-07');
  expect(order().slice(0, 3)).toEqual(['shape-01', 'shape-07', 'shape-03']);
  const size = within(designer).getByRole('slider', { name: 'Size' });
  fireEvent.change(size, { target: { value: '0.7' } });
  fireEvent.change(size, { target: { value: '0.65' } });
  fireEvent.change(within(designer).getByRole('slider', { name: 'Vertical position' }), {
    target: { value: '1' },
  });
  await waitFor(() =>
    expect(plans.at(-1)!.source.coloring!.pages[1]).toEqual({
      artwork: 'shape-07',
      placement: { scale: 0.65, x: 0, y: 1 },
    }),
  );
  expect(screen.getByText(/placed 65%/)).toBeVisible();
  // One drag of the size slider is one undo step.
  await user.click(screen.getByRole('button', { name: 'Undo' }));
  expect(within(designer).getByRole('slider', { name: 'Vertical position' })).toHaveValue('0');
  await user.click(screen.getByRole('button', { name: 'Undo' }));
  expect(within(designer).getByRole('slider', { name: 'Size' })).toHaveValue('1');
  await user.click(screen.getByRole('button', { name: 'Redo' }));
  await user.click(within(designer).getByRole('button', { name: 'Reset placement' }));
  await waitFor(() =>
    expect(plans.at(-1)!.source.coloring!.pages[1]).toEqual({ artwork: 'shape-07' }),
  );
  await user.click(within(designer).getByRole('button', { name: 'Insert divider after' }));
  expect(order().slice(0, 4)).toEqual(['shape-01', 'shape-07', 'Divider: New section', 'shape-03']);
  // The divider is now selected; duplicating it adds a second one after it.
  expect(screen.getByRole('region', { name: /Designing entry 3: Divider/ })).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Duplicate page' }));
  expect(order().slice(2, 5)).toEqual(['Divider: New section', 'Divider: New section', 'shape-03']);
  expect(screen.getByRole('main')).not.toHaveTextContent(WORD_SEARCH_TERMS);
});
