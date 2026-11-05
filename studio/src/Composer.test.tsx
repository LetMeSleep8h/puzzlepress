import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { test, expect, vi } from 'vitest';
import { App } from './App';
import composed from './fixtures/composition-project.json';
import planData from './fixtures/plan.json';
import legacy from './fixtures/project.json';

type Call = { url: string; body: Record<string, unknown> };

function setup(project: object = composed, fail?: string) {
  let saved = structuredClone(project) as typeof composed;
  const calls: Call[] = [];
  const error = (status: number, code: string, message: string, issues: object[] = []) =>
    new Response(JSON.stringify({ error: { code, message, issues } }), { status });
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
    const path = String(url);
    const body = options?.body ? JSON.parse(String(options.body)) : {};
    calls.push({ url: path, body });
    const source = body.source as typeof composed.source | undefined;
    if (path.endsWith('/validate') && source?.composition?.solutions.title === '')
      return error(422, 'invalid_project', 'Project validation failed.', [
        {
          path: 'composition.solutions.title',
          code: 'text',
          message: 'Expected 1..200 characters.',
        },
      ]);
    if (path.endsWith('/save')) {
      if (fail === 'source_changed') return error(409, fail, 'Source changed. Reload to review.');
      if (fail) return error(503, fail, 'Save failed. The source was not replaced.');
      saved = { ...saved, source: source!, revision: 'sha256-new' };
    }
    if (path.endsWith('/plan')) return new Response(JSON.stringify(planData));
    return new Response(JSON.stringify(saved));
  });
  history.replaceState(null, '', `/books/${(project as { key: string }).key}/book`);
  render(<App />);
  return calls;
}

const composer = () => document.querySelector('.composer') as HTMLElement;
const status = (text: string) =>
  waitFor(() =>
    expect(document.querySelector('.composer [role="status"]')).toHaveTextContent(text),
  );
const planCalls = (calls: Call[]) => calls.filter((c) => c.url.endsWith('/draft/plan'));

test('opens the saved book plan with sections, numbering, blanks and statistics', async () => {
  const calls = setup();
  await status('Publication plan ready. Source has not changed.');
  expect(planCalls(calls)).toHaveLength(1);
  for (const name of ['Front matter', 'Puzzles', 'Solutions', 'Back matter', 'Page numbers'])
    expect(screen.getByRole('heading', { name, level: 3 })).toBeVisible();
  const table = screen.getByRole('table', { name: 'Logical pages in reading order' });
  for (const name of ['Front matter', 'Puzzles', 'Solutions', 'Back matter'])
    expect(within(table).getByRole('rowheader', { name })).toBeVisible();
  expect(within(table).getByText('Intentional blank')).toBeVisible();
  expect(within(table).getByText('section_recto_start')).toBeVisible();
  expect(within(table).getByText(/^\(iv\)/)).toHaveTextContent('(iv) not printed');
  expect(within(table).getByText('Puzzle 1: Along the Shoreline')).toBeVisible();
  expect(within(table).getAllByText(/solution on page 5/, { selector: 'small' })).toHaveLength(2);
  expect(screen.getByText('Plan independently verified')).toBeVisible();
  expect(screen.getByText('logical page 9')).toBeVisible();
  expect(screen.getByRole('link', { name: 'Book', current: 'page' })).toBeVisible();
});

test('edits matter, policies and keyboard order, then previews and saves the draft', async () => {
  const calls = setup();
  const user = userEvent.setup();
  await status('Publication plan ready. Source has not changed.');
  fireEvent.change(screen.getByLabelText('Copyright notice'), {
    target: { value: 'Copyright 2026 Example Author.' },
  });
  // The title page prints the book details; they are edited in Settings, not here.
  expect(screen.getByRole('link', { name: 'Edit book details in Settings' })).toHaveAttribute(
    'href',
    '/books/composition-demo/settings',
  );
  expect(within(composer()).getByText('Unsaved changes')).toBeVisible();
  expect(screen.getByText(/Your draft changed\. Choose Preview plan/)).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();

  const up = screen.getByRole('button', { name: 'Move By the Harbour up' });
  up.focus();
  await user.keyboard('{Enter}');
  expect(screen.getByRole('button', { name: 'Move By the Harbour up' })).toHaveFocus();
  await user.keyboard('{Enter}');
  // At the top, Up is disabled; focus stays on the moved puzzle's other control.
  expect(screen.getByRole('button', { name: 'Move By the Harbour down' })).toHaveFocus();
  const order = screen.getByRole('list', { name: 'Puzzle publication order' });
  expect(within(order).getAllByRole('listitem')[0]).toHaveTextContent('By the Harbour');

  await user.selectOptions(screen.getByLabelText('Puzzle section starts on'), 'any');
  await user.click(screen.getByRole('radio', { name: /^Continuous/ }));
  await user.click(screen.getByRole('checkbox', { name: 'Front matter pages' }));
  await user.click(screen.getByRole('button', { name: 'Remove Notes page' }));
  await user.click(screen.getByRole('button', { name: 'Add about page' }));
  expect(screen.getByLabelText('About page text')).toHaveValue('');

  await user.click(screen.getByRole('button', { name: 'Preview plan' }));
  expect(await screen.findByRole('heading', { name: 'Unsaved draft plan' })).toBeVisible();
  const draft = planCalls(calls).at(-1)!.body.source as typeof composed.source;
  expect(draft.word_search!.puzzles.map((p) => p.id)).toEqual([
    'harbour',
    'shoreline',
    'rockpool',
    'dunes',
  ]);
  expect(draft.book).toEqual(composed.source.book);
  expect(draft.composition).toEqual({
    ...composed.source.composition,
    front_matter: [
      { kind: 'title_page' },
      { kind: 'copyright_page', text: 'Copyright 2026 Example Author.' },
      composed.source.composition.front_matter[2],
    ],
    puzzles: { start: 'any' },
    solutions: composed.source.composition.solutions,
    back_matter: [{ kind: 'about', title: 'About', text: '' }],
    page_numbers: {
      scheme: 'continuous',
      show_front_matter: true,
      show_solutions: true,
      show_back_matter: true,
    },
  });

  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await status('Saved and reloaded from source. Publication plan refreshed.');
  const save = calls.find((c) => c.url.endsWith('/save'))!;
  expect(save.body.revision).toBe(composed.revision);
  expect(save.body.source).toEqual(draft);
  expect(within(composer()).queryByText('Unsaved changes')).not.toBeInTheDocument();
  expect(planCalls(calls)).toHaveLength(3);
});

test('omitting solutions removes solution-only settings from the draft', async () => {
  const calls = setup();
  const user = userEvent.setup();
  await status('Publication plan ready. Source has not changed.');
  await user.click(screen.getByRole('radio', { name: /^Omit solutions/ }));
  expect(screen.queryByText(/solutions on each printed page/)).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Validate draft' }));
  await status('Draft is valid. Python accepted the proposed project.');
  const source = calls.at(-1)!.body.source as typeof composed.source;
  expect(source.composition.solutions).toEqual({ placement: 'omit' });
});

test('Python validation errors attach to composer fields; edits clear them', async () => {
  setup();
  const user = userEvent.setup();
  await status('Publication plan ready. Source has not changed.');
  const heading = screen.getByLabelText('Section heading');
  fireEvent.change(heading, { target: { value: '' } });
  await user.click(screen.getByRole('button', { name: 'Validate draft' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not complete the request');
  expect(heading).toHaveAttribute('aria-invalid', 'true');
  expect(heading).toHaveAccessibleDescription(/Expected 1\.\.200 characters/);
  fireEvent.change(heading, { target: { value: 'Answers' } });
  expect(heading).not.toHaveAttribute('aria-invalid');
});

test.each(['save_failed', 'source_changed'])(
  'retains the composition draft after %s and reverts only on confirmation',
  async (code) => {
    setup(composed, code);
    const user = userEvent.setup();
    await status('Publication plan ready. Source has not changed.');
    fireEvent.change(screen.getByLabelText('Section heading'), { target: { value: 'Keep me' } });
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      code === 'source_changed' ? 'Saved source has changed' : 'Save failed',
    );
    expect(screen.getByLabelText('Section heading')).toHaveValue('Keep me');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await user.click(screen.getByRole('button', { name: 'Revert draft' }));
    expect(screen.getByLabelText('Section heading')).toHaveValue('Keep me');
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole('button', { name: 'Revert draft' }));
    expect(screen.getByLabelText('Section heading')).toHaveValue('Solutions');
  },
);

test('composition draft is shared with the authoring desk and survives tabs', async () => {
  setup();
  const user = userEvent.setup();
  await status('Publication plan ready. Source has not changed.');
  await user.click(screen.getByRole('button', { name: 'Move In the Rock Pool up' }));
  const projectNav = screen.getByRole('navigation', { name: 'Project' });
  await user.click(within(projectNav).getByRole('link', { name: /^Puzzles/ }));
  expect(screen.getByRole('button', { name: /^1\. In the Rock Pool/ })).toBeVisible();
  expect(screen.getByText('Unsaved changes')).toBeVisible();
  await user.click(within(projectNav).getByRole('link', { name: 'Book' }));
  const order = screen.getByRole('list', { name: 'Puzzle publication order' });
  expect(within(order).getAllByRole('listitem')[0]).toHaveTextContent('In the Rock Pool');
});

test('projects without composition start one explicitly, with no invented legal text', async () => {
  const calls = setup(legacy);
  const user = userEvent.setup();
  await screen.findByRole('heading', { name: 'This project has no book composition yet' });
  expect(screen.getByRole('button', { name: 'Preview plan' })).toBeDisabled();
  expect(planCalls(calls)).toHaveLength(0);
  await user.click(screen.getByRole('button', { name: 'Start book composition' }));
  expect(within(composer()).getByText('Unsaved changes')).toBeVisible();
  expect(screen.queryByLabelText('Copyright notice')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Add copyright page' }));
  expect(screen.getByLabelText('Copyright notice')).toHaveValue('');
  expect(screen.getByLabelText('Copyright notice')).toHaveAccessibleDescription(
    /does not supply legal text/,
  );
  await waitFor(() => expect(planCalls(calls)).toHaveLength(0));
});
