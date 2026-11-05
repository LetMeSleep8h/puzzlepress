import { afterEach, expect, test, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import { starterPublishing } from './Publishing';
import pagesProject from './fixtures/coloring-pages-project.json';
import type { Project } from './types';

// Python output for tests/coloring_production.py; its declarations are SYNTHETIC.
const project = pagesProject as unknown as Project;

afterEach(() => vi.restoreAllMocks());

function setup() {
  const saves: { source: NonNullable<Project['source']> }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (url === '/api/projects/coloring-pages') return Response.json(project);
    if (url.endsWith('/draft/save')) {
      saves.push(body);
      return Response.json({ ...project, revision: 'next', source: body.source });
    }
    // Readiness and the draft check are Python's; this test is about the form.
    return Response.json(
      { error: { code: 'unavailable', message: 'Not in this test.', issues: [] } },
      { status: 503 },
    );
  });
  history.pushState(null, '', '/books/coloring-pages/publishing');
  render(<App />);
  return saves;
}

test('a coloring book declares artwork origins and rights, in its own words', async () => {
  const saves = setup();
  const user = userEvent.setup();
  const interior = await screen.findByRole('group', {
    name: 'Interior drawings (the coloring pages)',
  });
  expect(within(interior).getByRole('radio', { name: /Created by people/ })).toBeChecked();
  // Two groups share the name: who made the cover artwork, and the rights to it.
  const [coverOrigin, coverRights] = screen.getAllByRole('group', {
    name: 'Cover artwork or photograph',
  });
  expect(within(coverOrigin).getByRole('radio', { name: /No artwork on the cover/ })).toBeChecked();
  expect(within(coverRights).getByRole('radio', { name: /No artwork on the cover/ })).toBeChecked();
  expect(
    screen.getByRole('group', { name: "Images: KDP's one answer for cover and interior artwork" }),
  ).toBeVisible();
  const rights = screen.getByRole('heading', { name: 'Artwork rights' }).parentElement!;
  expect(
    within(rights).getByText(/Having an image file is not a right to publish it/),
  ).toBeVisible();
  const drawings = within(rights).getByRole('group', { name: 'Interior drawings' });
  expect(within(drawings).getByRole('radio', { name: /My own work/ })).toBeChecked();
  await user.click(within(drawings).getByRole('radio', { name: /Licensed/ }));
  await user.click(within(interior).getByRole('radio', { name: /AI-generated/ }));
  expect(
    screen.getByRole('radio', { name: /KDP lists coloring books as not generally/ }),
  ).toBeChecked();
  // Book details are edited in Settings for coloring books.
  const details = screen.getByText(/Edit them in/);
  expect(within(details).getByRole('link', { name: 'Settings' })).toHaveAttribute(
    'href',
    '/books/coloring-pages/settings',
  );
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(saves).toHaveLength(1));
  const saved = saves[0].source.publishing!;
  expect(saved.content_rights?.interior_artwork).toBe('licensed');
  expect(saved.ai_disclosure.interior_artwork).toBe('ai_generated');
  // The browser never decides consistency: `images` is left as authored for Python.
  expect(saved.ai_disclosure.images).toBe('human');
});

test('a new coloring publishing section starts undecided, word search unchanged', () => {
  const coloring = starterPublishing(true);
  expect(coloring.ai_disclosure).toEqual({
    text: 'unknown',
    images: 'unknown',
    translations: 'unknown',
    interior_artwork: 'unknown',
    cover_artwork: 'unknown',
  });
  expect(coloring.content_rights).toEqual({
    interior_artwork: 'undecided',
    cover_artwork: 'undecided',
    text: 'undecided',
    notes: null,
  });
  const wordSearch = starterPublishing();
  expect(wordSearch.content_rights).toBeUndefined();
  expect(Object.keys(wordSearch.ai_disclosure)).toEqual(['text', 'images', 'translations']);
});
