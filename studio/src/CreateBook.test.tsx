import { afterEach, expect, test, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import pagesProject from './fixtures/coloring-pages-project.json';
import listing from './fixtures/coloring-listing.json';
import type { Project, ProjectTypes } from './types';

const types: ProjectTypes = {
  types: [
    {
      kind: 'word_search',
      label: 'Word search',
      default_template: 'starter',
      templates: [{ id: 'starter', label: 'Starter puzzle', description: 'One placeholder.' }],
    },
    {
      kind: 'coloring',
      label: 'Coloring book',
      default_template: 'simple',
      templates: [
        { id: 'simple', label: 'Simple', description: 'A title page.' },
        { id: 'with-notes', label: 'Title, instructions and notes', description: 'More.' },
      ],
    },
  ],
  profiles: [
    {
      id: 'paperback-8.5x11',
      description: 'White',
      paper: 'white',
      trim: { width: 612, height: 792 },
    },
    {
      id: 'paperback-8.5x11-cream',
      description: 'Cream',
      paper: 'cream',
      trim: { width: 612, height: 792 },
    },
  ],
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

afterEach(() => vi.restoreAllMocks());

function mockApi(onCreate: (body: Record<string, unknown>) => Response) {
  const created: Record<string, unknown>[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === '/api/project-types') return json(types);
    if (url === '/api/projects' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      created.push(body);
      return onCreate(body);
    }
    if (url === '/api/projects') return json({ projects: [] });
    if (url === '/api/projects/coloring-pages/coloring') return json(listing);
    if (url === '/api/projects/coloring-pages') return json(pagesProject);
    return json({ error: { code: 'x', message: `unexpected ${url}`, issues: [] } }, 500);
  });
  return created;
}

test('choosing a type, naming the book and creating opens it', async () => {
  const created = mockApi(() => json({ ...(pagesProject as unknown as Project) }, 201));
  history.pushState(null, '', '/books');
  render(<App />);
  const user = userEvent.setup();
  // The Library offers it beside the heading; the app bar on every page too.
  await screen.findByRole('heading', { name: 'A place for your next book' });
  expect(screen.getAllByRole('link', { name: 'New book' })).toHaveLength(2);
  await user.click(screen.getAllByRole('link', { name: 'New book' })[1]);
  expect(await screen.findByRole('heading', { name: 'New book', level: 1 })).toBeVisible();
  const group = screen.getByRole('radiogroup', { name: '1. Book type' });
  // Future types are listed but cannot be chosen.
  expect(within(group).getByText('Sudoku').closest('label')).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  const disabled = within(group)
    .getAllByRole('radio')
    .filter((radio) => (radio as HTMLInputElement).disabled);
  expect(disabled).toHaveLength(7);
  await user.click(within(group).getByRole('radio', { name: /Coloring Book/ }));
  const heading = screen.getByRole('heading', { name: /About your coloring book/ });
  expect(heading).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Create book' })).toBeDisabled();
  await user.type(screen.getByRole('textbox', { name: 'Book title' }), 'Woodland Coloring');
  await user.type(screen.getByRole('textbox', { name: 'Subject (optional)' }), 'Nature');
  await user.click(screen.getByRole('radio', { name: '8.5 × 11 in, cream paper' }));
  await user.click(screen.getByRole('radio', { name: /Title, instructions and notes/ }));
  await user.click(screen.getByRole('button', { name: 'Create book' }));
  await waitFor(() => expect(window.location.pathname).toBe('/books/coloring-pages/artwork'));
  expect(created).toEqual([
    {
      kind: 'coloring',
      key: '',
      title: 'Woodland Coloring',
      language: 'en',
      subtitle: null,
      author: null,
      subject: 'Nature',
      collection: null,
      profile: 'paperback-8.5x11-cream',
      template: 'with-notes',
    },
  ]);
});

test('Python refusals are shown beside the fields and keep the answers', async () => {
  mockApi(() =>
    json(
      {
        error: {
          code: 'invalid_project',
          message: 'Project validation failed.',
          issues: [
            {
              path: 'key',
              code: 'project_exists',
              message: "A project folder named 'woods' already exists.",
            },
          ],
        },
      },
      422,
    ),
  );
  history.pushState(null, '', '/create');
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('radio', { name: /Word Search/ }));
  await user.type(screen.getByRole('textbox', { name: 'Book title' }), 'Woods');
  const folder = screen.getByRole('textbox', { name: 'Project folder name (optional)' });
  await user.type(folder, 'woods');
  await user.click(screen.getByRole('button', { name: 'Create book' }));
  expect(
    await screen.findByRole('heading', { name: 'That project folder already exists' }),
  ).toBeVisible();
  await waitFor(() => expect(folder).toHaveAttribute('aria-invalid', 'true'));
  expect(folder).toHaveValue('woods');
  expect(screen.getByRole('textbox', { name: 'Book title' })).toHaveValue('Woods');
  expect(window.location.pathname).toBe('/create');
});
