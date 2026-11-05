import { afterEach, expect, test, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import pagesProject from './fixtures/coloring-pages-project.json';
import projectData from './fixtures/project.json';
import type { Project } from './types';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
type Body = { source: NonNullable<Project['source']>; revision?: string };
const profiles = [
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
];

afterEach(() => vi.restoreAllMocks());

function mockApi(project: Project) {
  const saves: Body[] = [];
  const key = project.key;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    if (url === '/api/project-types') return json({ types: [], profiles });
    if (url === `/api/projects/${key}`) return json(project);
    if (url === `/api/projects/${key}/draft/save`) {
      saves.push(body!);
      return json({ ...project, revision: 'next', source: body!.source });
    }
    if (url === `/api/projects/${key}/draft/validate`)
      return json(
        {
          error: {
            code: 'invalid_project',
            message: 'Project validation failed.',
            issues: [
              {
                path: 'catalog.subject',
                code: 'text',
                message: 'Expected 1..120 characters of single-line text.',
              },
            ],
          },
        },
        422,
      );
    return json({ error: { code: 'x', message: `unexpected ${url}`, issues: [] } }, 500);
  });
  return saves;
}

test('coloring settings edit book details, catalog and paper in one save', async () => {
  const project = pagesProject as unknown as Project;
  const saves = mockApi(project);
  history.pushState(null, '', `/books/${project.key}/settings`);
  render(<App />);
  const user = userEvent.setup();
  const title = await screen.findByRole('textbox', { name: 'Book title' });
  expect(title).toHaveValue(project.source!.book.title);
  await user.clear(title);
  await user.type(title, 'Garden Shapes');
  const author = screen.getByRole('textbox', { name: 'Author or pen name (optional)' });
  await user.clear(author);
  await user.type(author, 'A. Artist');
  await user.type(screen.getByRole('textbox', { name: 'Collection (optional)' }), 'Shapes');
  await user.click(await screen.findByRole('radio', { name: /Cream paper/ }));
  expect(screen.getByText(/This change is not saved yet/)).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(saves).toHaveLength(1));
  const sent = saves[0].source;
  expect(sent.book).toEqual({
    ...project.source!.book,
    title: 'Garden Shapes',
    author: 'A. Artist',
  });
  expect(sent.catalog).toEqual({ collection: 'Shapes' });
  expect(sent.print).toEqual({ profile: 'paperback-8.5x11-cream' });
  expect(sent.coloring).toEqual(project.source!.coloring);
  // Settings is in the coloring navigation; Pages no longer repeats the title field.
  const nav = screen.getByRole('navigation', { name: 'Project' });
  expect(within(nav).getByRole('link', { name: 'Settings', current: 'page' })).toBeVisible();
});

test('clearing a catalog field removes it, and Python issues show beside it', async () => {
  const project = structuredClone(pagesProject) as unknown as Project;
  project.source!.catalog = { subject: 'Shapes' };
  const saves = mockApi(project);
  history.pushState(null, '', `/books/${project.key}/settings`);
  render(<App />);
  const user = userEvent.setup();
  const subject = await screen.findByRole('textbox', { name: 'Subject (optional)' });
  await user.click(screen.getByRole('button', { name: 'Validate draft' }));
  await waitFor(() => expect(subject).toHaveAttribute('aria-invalid', 'true'));
  await user.clear(subject);
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(saves).toHaveLength(1));
  expect(saves[0].source.catalog).toBeUndefined();
});

test('word-search settings edit the title-page details in one place and keep the rest', async () => {
  const project = projectData as unknown as Project;
  const saves = mockApi(project);
  history.pushState(null, '', `/books/${project.key}/settings`);
  render(<App />);
  const user = userEvent.setup();
  const details = await screen.findByRole('region', { name: 'Project details' });
  const subtitle = within(details).getByRole('textbox', { name: 'Subtitle (optional)' });
  await user.type(subtitle, 'Fifty puzzles');
  await user.type(
    within(details).getByRole('textbox', { name: 'Imprint or publisher (optional)' }),
    'Garden Press',
  );
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(saves).toHaveLength(1));
  const sent = saves[0].source;
  expect(sent.book).toEqual({
    ...project.source!.book,
    subtitle: 'Fifty puzzles',
    imprint: 'Garden Press',
  });
  // Nothing else changes: puzzles, composition and output are sent back as they were.
  expect({ ...sent, book: project.source!.book }).toEqual(project.source);
  // Clearing an optional detail writes null, as Python normalizes it.
  await user.clear(within(details).getByRole('textbox', { name: 'Subtitle (optional)' }));
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(saves).toHaveLength(2));
  expect(saves[1].source.book.subtitle).toBeNull();
});

test('the puzzles editor shows the book details and links to Settings', async () => {
  const project = projectData as unknown as Project;
  mockApi(project);
  history.pushState(null, '', `/books/${project.key}/edit`);
  render(<App />);
  const link = await screen.findByRole('link', {
    name: 'Edit the title, language and other book details in Settings',
  });
  expect(link).toHaveAttribute('href', `/books/${project.key}/settings`);
  expect(screen.queryByRole('textbox', { name: 'Book title' })).toBeNull();
});
