import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect, vi } from 'vitest';
import { App } from './App';
import projectData from './fixtures/project.json';
import generated from './fixtures/generation.json';

// Book details (title, language) are edited in Settings; the editor links there.
function setup(fail?: string, page = 'edit') {
  let saved = structuredClone(projectData);
  const calls: { url: string; body: Record<string, unknown> }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
    const path = String(url);
    const body = options?.body ? JSON.parse(String(options.body)) : {};
    calls.push({ url: path, body });
    if (path.endsWith('/save')) {
      if (fail)
        return new Response(
          JSON.stringify({
            error: {
              code: fail,
              message:
                fail === 'source_changed' ? 'Source changed. Reload to review.' : 'Save failed.',
              issues: [],
            },
          }),
          { status: 409 },
        );
      saved = { ...saved, source: body.source, revision: 'sha256-new' };
      saved.source.word_search.puzzles[0].title = saved.source.word_search.puzzles[0].title.trim();
    }
    if (path.endsWith('/validate') && !String(body.source.book.title).trim())
      return new Response(
        JSON.stringify({
          error: {
            code: 'invalid_project',
            message: 'Project validation failed.',
            issues: [{ path: 'book.title', code: 'type', message: 'Expected a nonempty string.' }],
          },
        }),
        { status: 422 },
      );
    // Stands in for Python's language tag check; the browser never checks tags itself.
    if (path.endsWith('/validate') && body.source.book.language === 'en_US')
      return new Response(
        JSON.stringify({
          error: {
            code: 'invalid_project',
            message: 'Project validation failed.',
            issues: [
              {
                path: 'book.language',
                code: 'format',
                message: 'Expected a language tag such as en or en-US.',
              },
            ],
          },
        }),
        { status: 422 },
      );
    if (path.endsWith('/validate') && !body.source.word_search.puzzles[0].title)
      return new Response(
        JSON.stringify({
          error: {
            code: 'invalid_project',
            message: 'Project validation failed.',
            issues: [
              {
                path: 'word_search.puzzles.0.title',
                code: 'text',
                message: 'Expected nonempty text.',
              },
            ],
          },
        }),
        { status: 422 },
      );
    return new Response(JSON.stringify(path.endsWith('/preview') ? generated : saved));
  });
  history.replaceState(null, '', `/books/garden-demo/${page}`);
  render(<App />);
  return calls;
}

// The word-search editor stays mounted (hidden) in other sections, so a message
// can be in the DOM twice; only what is shown counts.
const VISIBLE = { ignore: '[hidden] *, script, style' };

// Background requests (such as editorial reviews) can start at any moment, so a
// test answers only the request it means instead of whichever fetch comes next.
function answerOnce(suffix: string, answer: () => Promise<Response>) {
  const fallback = vi.mocked(fetch).getMockImplementation()!;
  let used = false;
  vi.mocked(fetch).mockImplementation((url, options) => {
    if (!used && String(url).endsWith(suffix)) {
      used = true;
      return answer();
    }
    return fallback(url, options);
  });
}

test('loads, edits, validates, previews and saves authoritative returned state', async () => {
  const calls = setup();
  const user = userEvent.setup();
  const title = await screen.findByLabelText('Puzzle title');
  fireEvent.change(title, { target: { value: '  Edited flowers  ' } });
  expect(screen.getByText('Unsaved changes')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Validate draft' }));
  expect(
    await screen.findByText('Draft is valid. Python accepted the proposed project.'),
  ).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Preview draft' }));
  expect(await screen.findByText('Unsaved draft preview')).toBeVisible();
  expect(screen.getByRole('table')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Whole-book quality' }));
  expect(screen.getByText('No target words are shared between definitions.')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByText('Saved and reloaded from source.', VISIBLE)).toBeVisible();
  expect(title).toHaveValue('Edited flowers');
  expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();
  expect(calls.find((c) => c.url.endsWith('/save'))?.body.revision).toBe(projectData.revision);
});

test('the book title is visible on opening, saves only the title and reloads', async () => {
  const calls = setup(undefined, 'settings');
  const user = userEvent.setup();
  const field = await screen.findByRole('textbox', { name: 'Book title' });
  // Publishing and Book link here to change the title: it must not be tucked away.
  expect(field).toBeVisible();
  expect(field).toHaveValue('Garden Word Searches');
  await user.clear(field);
  await user.type(field, 'Garden Word Search Puzzle Book for Adults');
  expect(screen.getByText('Unsaved draft')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByText('Saved and reloaded from source.', VISIBLE)).toBeVisible();
  const sent = calls.find((c) => c.url.endsWith('/save'))!.body.source as typeof projectData.source;
  expect(sent).toEqual({
    ...projectData.source,
    book: { ...projectData.source.book, title: 'Garden Word Search Puzzle Book for Adults' },
  });
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
    'Garden Word Search Puzzle Book for Adults',
  );
  expect(screen.getByRole('textbox', { name: 'Book title' })).toHaveValue(
    'Garden Word Search Puzzle Book for Adults',
  );
  expect(screen.queryByText('Unsaved draft')).not.toBeInTheDocument();
});

test('a blank book title is reported beside its field by Python validation', async () => {
  setup(undefined, 'settings');
  const user = userEvent.setup();
  const field = await screen.findByRole('textbox', { name: 'Book title' });
  await user.clear(field);
  await user.click(screen.getByRole('button', { name: 'Validate draft' }));
  await waitFor(() => expect(field).toHaveAttribute('aria-invalid', 'true'));
  const beside = document.getElementById('book.title-issues')!;
  expect(beside).toBeVisible();
  expect(beside).toHaveTextContent('book.title: Expected a nonempty string.');
  expect(field).toHaveAccessibleDescription(/Expected a nonempty string/);
  expect(screen.queryByText('Saved and reloaded from source.', VISIBLE)).not.toBeInTheDocument();
});

test('the language is beside the title, prepopulated, and saves only the language', async () => {
  const calls = setup(undefined, 'settings');
  const user = userEvent.setup();
  const field = await screen.findByRole('textbox', { name: 'Language' });
  // Publishing's language_supported finding links here: the field must be in view.
  expect(field).toBeVisible();
  expect(field).toHaveValue('en');
  expect(field.closest('.book-fields')).toContainElement(
    screen.getByRole('textbox', { name: 'Book title' }),
  );
  await user.clear(field);
  await user.type(field, 'en-GB');
  expect(screen.getByText('Unsaved draft')).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByText('Saved and reloaded from source.', VISIBLE)).toBeVisible();
  const sent = calls.find((c) => c.url.endsWith('/save'))!.body.source as typeof projectData.source;
  expect(sent).toEqual({
    ...projectData.source,
    book: { ...projectData.source.book, language: 'en-GB' },
  });
  expect(screen.getByRole('textbox', { name: 'Language' })).toHaveValue('en-GB');
  expect(screen.queryByText('Unsaved draft')).not.toBeInTheDocument();
});

test('a malformed language is reported beside its field by Python validation', async () => {
  const calls = setup(undefined, 'settings');
  const user = userEvent.setup();
  const field = await screen.findByRole('textbox', { name: 'Language' });
  await user.clear(field);
  await user.type(field, 'en_US');
  // No browser-side tag check: nothing is flagged until Python reports it.
  expect(field).not.toHaveAttribute('aria-invalid');
  await user.click(screen.getByRole('button', { name: 'Validate draft' }));
  await waitFor(() => expect(field).toHaveAttribute('aria-invalid', 'true'));
  expect(calls.find((c) => c.url.endsWith('/validate'))).toBeDefined();
  const beside = document.getElementById('book.language-issues')!;
  expect(beside).toBeVisible();
  expect(beside).toHaveTextContent('book.language: Expected a language tag such as en or en-US.');
  expect(field).toHaveAccessibleDescription(/Expected a language tag/);
  expect(screen.getByRole('textbox', { name: 'Book title' })).not.toHaveAttribute('aria-invalid');
});

test('a failed title save keeps the draft and never reports success', async () => {
  setup('save_failed', 'settings');
  const user = userEvent.setup();
  const field = await screen.findByRole('textbox', { name: 'Book title' });
  await user.clear(field);
  await user.type(field, 'Retitled garden');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByText(/Save failed/, VISIBLE)).toBeVisible();
  expect(screen.queryByText('Saved and reloaded from source.', VISIBLE)).not.toBeInTheDocument();
  expect(field).toHaveValue('Retitled garden');
  expect(screen.getByText('Unsaved draft')).toBeVisible();
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Garden Word Searches');
});

test('word editing, target ordering, puzzle management and shared profile selection', async () => {
  const calls = setup();
  const user = userEvent.setup();
  await screen.findByLabelText('Puzzle title');
  fireEvent.change(screen.getByLabelText('Word 1'), { target: { value: 'ASTER' } });
  await user.click(screen.getByRole('button', { name: 'Move target 2 up' }));
  await user.selectOptions(screen.getByLabelText('Difficulty profile'), 'varied');
  await user.click(screen.getByRole('button', { name: 'Add word' }));
  const count = projectData.source.word_search.banks[0].entries.length + 1;
  fireEvent.change(screen.getByLabelText(`Word ${count}`), { target: { value: 'BUD' } });
  await user.selectOptions(screen.getByLabelText(/Add a target from/), 'word-1');
  await user.click(screen.getByRole('button', { name: 'Add puzzle' }));
  expect(screen.getByLabelText('Puzzle ID')).toHaveValue('puzzle-1');
  await user.click(screen.getByRole('button', { name: 'Move puzzle 3 up' }));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  await user.click(screen.getByRole('button', { name: 'Remove puzzle' }));
  await user.click(screen.getByRole('button', { name: 'Validate draft' }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/validate'))).toBe(true));
  const source = calls.find((c) => c.url.endsWith('/validate'))!.body
    .source as typeof projectData.source;
  expect(source.word_search.puzzles).toHaveLength(2);
  expect(source.word_search.banks[0].entries[0].display).toBe('ASTER');
  expect(source.word_search.puzzles[0].difficulty).toBe('varied');
  expect(source.word_search.puzzles[0].target_ids.at(-1)).toBe('word-1');
});

test.each(['save_failed', 'source_changed'])(
  'retains draft after %s and supports deliberate revert',
  async (code) => {
    setup(code);
    const user = userEvent.setup();
    fireEvent.change(await screen.findByLabelText('Puzzle title'), {
      target: { value: 'Keep my work' },
    });
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(screen.getByLabelText('Puzzle title')).toHaveValue('Keep my work');
    expect(screen.getByText('Unsaved changes')).toBeVisible();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await user.click(screen.getByRole('button', { name: 'Revert draft' }));
    expect(screen.getByLabelText('Puzzle title')).toHaveValue('Keep my work');
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole('button', { name: 'Revert draft' }));
    expect(screen.getByLabelText('Puzzle title')).toHaveValue('In the Flower Bed');
  },
);

test('structured validation is associated with the input and edits invalidate old results', async () => {
  setup();
  const user = userEvent.setup();
  const title = await screen.findByLabelText('Puzzle title');
  fireEvent.change(title, { target: { value: '' } });
  await user.click(screen.getByRole('button', { name: 'Validate draft' }));
  await screen.findByRole('alert');
  expect(title).toHaveAttribute('aria-invalid', 'true');
  expect(title).toHaveAccessibleDescription(/Expected nonempty text/);
  fireEvent.change(title, { target: { value: 'Repaired' } });
  expect(title).not.toHaveAttribute('aria-invalid');
  await user.click(screen.getByRole('button', { name: 'Preview draft' }));
  await screen.findByRole('table');
  fireEvent.change(title, { target: { value: 'Newer draft' } });
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

test('draft survives project tabs, blocks leaving and warns on browser unload', async () => {
  setup();
  const user = userEvent.setup();
  fireEvent.change(await screen.findByLabelText('Puzzle title'), {
    target: { value: 'Keep draft' },
  });
  await user.click(screen.getByRole('link', { name: 'Overview' }));
  await user.click(screen.getByRole('link', { name: /^Puzzles/ }));
  expect(screen.getByLabelText('Puzzle title')).toHaveValue('Keep draft');
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  await user.click(screen.getByRole('link', { name: 'Books' }));
  expect(confirm).toHaveBeenCalled();
  expect(location.pathname).toBe('/books/garden-demo/edit');
});

test.each(['unavailable', 'malformed'])('preserves edits after %s response', async (failure) => {
  setup();
  const user = userEvent.setup();
  fireEvent.change(await screen.findByLabelText('Puzzle title'), { target: { value: 'Retained' } });
  answerOnce('/save', async () => {
    if (failure === 'unavailable') throw new TypeError('Network error');
    return new Response('not json');
  });
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    failure === 'unavailable' ? 'cannot reach' : 'unreadable response',
  );
  expect(screen.getByLabelText('Puzzle title')).toHaveValue('Retained');
  expect(screen.getByText('Unsaved changes')).toBeVisible();
});

test('pending operations disable changes and unmounted preview responses are ignored', async () => {
  setup();
  const user = userEvent.setup();
  const title = await screen.findByLabelText('Puzzle title');
  let finish!: (response: Response) => void;
  answerOnce(
    '/preview',
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  await user.click(screen.getByRole('button', { name: 'Preview draft' }));
  expect(title).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  await user.click(screen.getByRole('link', { name: 'Books' }));
  finish(new Response(JSON.stringify(generated)));
  await waitFor(() => expect(location.pathname).toBe('/books'));
  expect(
    screen.queryByText('Draft preview ready. Source has not changed.'),
  ).not.toBeInTheDocument();
});

test('the puzzle navigator searches, filters and steps without rendering every editor', async () => {
  setup();
  const user = userEvent.setup();
  await screen.findByLabelText('Puzzle title');
  const list = screen.getByRole('list', { name: 'Puzzle definitions' });
  expect(list.querySelectorAll('li')).toHaveLength(2);
  // Only the selected puzzle's fields exist.
  expect(screen.getAllByLabelText('Puzzle title')).toHaveLength(1);
  await user.type(screen.getByLabelText('Search puzzles'), 'herb');
  expect(screen.getByText('Showing 1 of 2')).toBeVisible();
  await user.click(screen.getByRole('button', { name: /The Herb Garden/ }));
  expect(screen.getByLabelText('Puzzle title')).toHaveValue('The Herb Garden');
  await user.clear(screen.getByLabelText('Search puzzles'));
  await user.selectOptions(screen.getByLabelText('Filter by theme'), 'Flowers');
  expect(screen.getByText('Showing 1 of 2')).toBeVisible();
  await user.selectOptions(screen.getByLabelText('Filter by theme'), '');
  await user.selectOptions(screen.getByLabelText('Filter by difficulty'), 'varied');
  expect(screen.getByRole('button', { name: /The Herb Garden/ })).toBeVisible();
  await user.selectOptions(screen.getByLabelText('Filter by difficulty'), '');
  await user.click(screen.getByRole('button', { name: '← Previous' }));
  expect(screen.getByLabelText('Puzzle title')).toHaveValue('In the Flower Bed');
  expect(screen.getByRole('button', { name: '← Previous' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Next →' }));
  expect(screen.getByRole('heading', { name: 'Puzzle 2 of 2' })).toBeVisible();
});
