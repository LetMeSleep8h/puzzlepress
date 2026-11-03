import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';
import { App } from './App';
import { starterPublishing } from './Publishing';
import type { PublishingDraftCheck, PublishingStatus } from './types';
import blocked from './fixtures/publishing-blocked.json';
import draftCheck from './fixtures/publishing-draft.json';
import exported from './fixtures/publishing-exported.json';
import project from './fixtures/publishing-project.json';
import ready from './fixtures/publishing-ready.json';

type Call = { url: string; body: Record<string, unknown> };

afterEach(() => vi.restoreAllMocks());

function setup({
  status = blocked as object,
  source = project as object,
  draft = draftCheck as object,
}: { status?: object; source?: object; draft?: object } = {}) {
  let saved = structuredClone(source) as typeof project;
  const calls: Call[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
    const path = String(url);
    const body = options?.body ? JSON.parse(String(options.body)) : {};
    calls.push({ url: path, body });
    if (path.endsWith('/draft/publishing')) return new Response(JSON.stringify(draft));
    if (path.endsWith('/publishing/export')) return new Response(JSON.stringify(exported));
    if (path.endsWith('/publishing')) return new Response(JSON.stringify(status));
    if (path.endsWith('/draft/save')) {
      saved = { ...saved, source: body.source as typeof saved.source, revision: 'sha256-new' };
    }
    return new Response(JSON.stringify(saved));
  });
  history.replaceState(null, '', '/books/publishing-demo/publishing');
  render(<App />);
  return calls;
}

const readiness = () => screen.getByRole('complementary', { name: 'Readiness' });
const workspace = () => document.querySelector('.publishing') as HTMLElement;

test('shows what blocks the package, as text, with the real cover', async () => {
  setup();
  await screen.findByText('AI content disclosure is not yet declared.');
  expect(screen.getByRole('link', { name: 'Publishing', current: 'page' })).toBeVisible();
  const panel = readiness();
  expect(within(panel).getByText('Your confirmations are incomplete.')).toBeVisible();
  expect(within(panel).getByText('Interior current and KDP ready.')).toBeVisible();
  expect(within(panel).getByText('Cover current and KDP ready.')).toBeVisible();
  expect(within(panel).getByRole('button', { name: 'Export package' })).toBeDisabled();
  const cover = screen.getByRole('img', { name: /Front cover of Harbour Light Word Searches/ });
  const status = blocked as unknown as PublishingStatus;
  expect(cover.getAttribute('src')).toContain(`pdf=${status.cover_preview!.pdf_sha256}`);
  const verdicts = screen.getByLabelText('Publishing verdicts');
  expect(within(verdicts).getByText('Not ready')).toBeVisible();
  expect(within(verdicts).getAllByText('KDP ready')).toHaveLength(2);
  expect(screen.getByText('35')).toBeVisible();
  expect(screen.getByText('0.0788 in')).toBeVisible();
});

test('never preselects disclosure or confirmations', async () => {
  setup();
  await screen.findByText('AI content disclosure is not yet declared.');
  for (const name of ['rights', 'AI content declaration', 'accurately represent'])
    expect(await screen.findByRole('checkbox', { name: new RegExp(name) })).not.toBeChecked();
  const text = screen.getByRole('group', { name: /Text \(word lists/ });
  expect(within(text).getByRole('radio', { name: /Not yet reviewed/ })).toBeChecked();
  const starter = starterPublishing();
  expect(Object.values(starter.attestations).some(Boolean)).toBe(false);
  expect(starter.isbn.mode).toBe('undecided');
  expect(starter.low_content).toBeNull();
  expect(starter.audience.sexually_explicit).toBeNull();
});

test('Python field findings appear beside the fields they concern', async () => {
  // The same nine keywords the draft-check fixture was produced from.
  const nine = structuredClone(project);
  nine.source.publishing.keywords.push('Harbour Vocabulary', 'best puzzles', 'a', 'b');
  const calls = setup({ source: nine });
  await screen.findByText('AI content disclosure is not yet declared.');
  fireEvent.change(screen.getByLabelText('Keywords 9'), { target: { value: 'harbour words' } });
  await waitFor(() =>
    expect(
      calls.some(
        (c) =>
          c.url.endsWith('/draft/publishing') && JSON.stringify(c.body).includes('harbour words'),
      ),
    ).toBe(true),
  );
  const keywords = screen.getByRole('group', { name: /Keywords/ });
  expect(await within(keywords).findByText(/9 keywords; KDP allows 7/)).toBeVisible();
  const duplicate = within(keywords).getByLabelText('Keywords 6');
  expect(duplicate).toHaveAttribute('aria-invalid', 'true');
  expect(within(keywords).getAllByText('Blocking').length).toBeGreaterThan(0);
  expect(within(keywords).getAllByText('Review').length).toBeGreaterThan(0);
});

test('confirmations save through the shared draft and block export until saved', async () => {
  const calls = setup({ status: ready });
  await screen.findByText('Package ready for manual KDP submission.');
  const user = userEvent.setup();
  const exportButton = within(readiness()).getByRole('button', { name: 'Export package' });
  expect(exportButton).toBeEnabled();
  await user.click(await screen.findByRole('checkbox', { name: /accurately represent/ }));
  expect(within(workspace()).getByText('Unsaved changes')).toBeVisible();
  expect(exportButton).toBeDisabled();
  expect(screen.getByText(/Save the draft first: packages build from saved source/)).toBeVisible();
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/draft/save'))).toBe(true));
  const save = calls.find((c) => c.url.endsWith('/draft/save'))!;
  const saved = (save.body.source as { publishing: { attestations: Record<string, unknown> } })
    .publishing.attestations;
  // The browser records the review identity Python reported; it never computes one.
  const reported = (draftCheck as unknown as PublishingDraftCheck).metadata.confirmations.find(
    (c) => c.name === 'metadata',
  )!.current;
  expect(saved.metadata).toBe(reported);
  expect(saved.rights).toBeNull();
});

test('the book details title links to its editable field and reflects the saved title', async () => {
  const calls = setup();
  await screen.findByText('AI content disclosure is not yet declared.');
  const user = userEvent.setup();
  const details = screen.getByRole('region', { name: 'Book details' });
  expect(within(details).getByText('Harbour Light Word Searches')).toBeVisible();
  await user.click(within(details).getByRole('link', { name: 'Puzzles' }));
  expect(screen.getByRole('link', { name: /Puzzles/, current: 'page' })).toBeVisible();
  const field = screen.getByRole('textbox', { name: 'Book title' });
  expect(field).toBeVisible();
  expect(field).toHaveValue('Harbour Light Word Searches');
  await user.clear(field);
  await user.type(field, 'Harbour Light Word Search Puzzle Book for Adults');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  expect(await screen.findByText('Saved and reloaded from source.')).toBeVisible();
  const save = calls.find((c) => c.url.endsWith('/draft/save'))!;
  const book = (save.body.source as typeof project.source).book;
  expect(book).toEqual({
    ...project.source.book,
    title: 'Harbour Light Word Search Puzzle Book for Adults',
  });
  await user.click(screen.getByRole('link', { name: 'Publishing' }));
  const after = await screen.findByRole('region', { name: 'Book details' });
  expect(within(after).getByText('Harbour Light Word Search Puzzle Book for Adults')).toBeVisible();
  // Readiness is fetched again for the saved revision, never trusted from before.
  const fetched = calls.filter((c) => c.url.endsWith('/publishing'));
  expect(fetched.length).toBeGreaterThan(1);
});

function withConfirmation(state: 'confirmed' | 'stale' | 'legacy', upgrade = false) {
  const check = structuredClone(draftCheck) as unknown as PublishingDraftCheck;
  const metadata = check.metadata.confirmations.find((c) => c.name === 'metadata')!;
  metadata.state = state;
  metadata.message =
    state === 'stale'
      ? 'Something it covers changed after you confirmed it: title, keywords. Review and confirm again.'
      : metadata.message;
  if (upgrade)
    check.upgrade = { ...structuredClone(project.source.publishing), version: 2 } as never;
  return check;
}

test('a stale confirmation is unchecked and says why review is needed again', async () => {
  setup({ draft: withConfirmation('stale') });
  const box = await screen.findByRole('checkbox', { name: /accurately represent/ });
  expect(box).not.toBeChecked();
  const state = document.getElementById(box.getAttribute('aria-describedby')!)!;
  expect(state.textContent).toContain('Review again');
  expect(state.textContent).toContain('changed after you confirmed it');
  const confirmed = await screen.findByRole('checkbox', { name: /hold the rights/ });
  expect(confirmed).not.toBeChecked(); // Unconfirmed in the fixture: never preselected.
});

test('a confirmed statement shows its state and can be withdrawn', async () => {
  const check = withConfirmation('confirmed');
  const confirmedSource = structuredClone(project);
  const attestations = confirmedSource.source.publishing.attestations as Record<string, unknown>;
  attestations.metadata = check.metadata.confirmations.find((c) => c.name === 'metadata')!.current;
  const calls = setup({ source: confirmedSource, draft: check });
  const user = userEvent.setup();
  const box = await screen.findByRole('checkbox', { name: /accurately represent/ });
  expect(box).toBeChecked();
  const state = document.getElementById(box.getAttribute('aria-describedby')!)!;
  expect(state.textContent).toContain('Confirmed');
  box.focus();
  await user.keyboard(' ');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/draft/save'))).toBe(true));
  const save = calls.find((c) => c.url.endsWith('/draft/save'))!;
  const source = save.body.source as { publishing: { attestations: Record<string, unknown> } };
  expect(source.publishing.attestations.metadata).toBeNull();
});

test('version 1 confirmations never count and the section upgrades on request', async () => {
  const legacy = structuredClone(project);
  const section = legacy.source.publishing as unknown as Record<string, unknown>;
  section.version = 1;
  section.attestations = { rights: true, ai_disclosure: true, metadata: true, isbn: false };
  const calls = setup({ source: legacy, draft: withConfirmation('legacy', true) });
  const user = userEvent.setup();
  // The upgrade offer comes from the debounced Python draft check: wait for the page,
  // then for that check, as the other tests here do, so no single wait spans both.
  await screen.findByText('AI content disclosure is not yet declared.');
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/draft/publishing'))).toBe(true));
  const upgrade = await screen.findByRole('button', { name: 'Upgrade publishing section' });
  const box = screen.getByRole('checkbox', { name: /accurately represent/ });
  expect(box).not.toBeChecked();
  expect(box).toBeDisabled();
  await user.click(upgrade);
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/draft/save'))).toBe(true));
  const save = calls.find((c) => c.url.endsWith('/draft/save'))!;
  const saved = (save.body.source as { publishing: Record<string, unknown> }).publishing;
  expect(saved.version).toBe(2);
  expect(saved.attestations).toEqual({
    rights: null,
    ai_disclosure: null,
    metadata: null,
    isbn: null,
  });
});

test('exports the saved revision and summarizes the files without claiming submission', async () => {
  const calls = setup({ status: ready });
  await screen.findByText('Package ready for manual KDP submission.');
  const user = userEvent.setup();
  await user.click(screen.getByRole('checkbox', { name: /Also write/ }));
  await user.click(within(readiness()).getByRole('button', { name: 'Export package' }));
  const request = calls.find((c) => c.url.endsWith('/publishing/export'))!;
  expect(request.body).toEqual({
    revision: (project as { revision: string }).revision,
    archive: true,
  });
  expect(await screen.findByText('Package exported')).toBeVisible();
  expect(screen.getByText(/Not submitted to Amazon/)).toBeVisible();
  expect(
    screen.getByText('Package exported and current. Upload it in KDP yourself.'),
  ).toBeVisible();
  expect(screen.getByText(/It has not been uploaded or submitted/)).toBeVisible();
  const checklist = screen.getByLabelText('KDP upload checklist');
  expect(checklist.textContent).toContain('Nothing on this list has been done in KDP');
});

test('stale cover states say why and link to Cover', async () => {
  const status = structuredClone(ready) as unknown as PublishingStatus;
  status.readiness.verdicts.cover = { state: 'stale', structural: 'invalid', kdp: 'ready' };
  status.readiness.verdicts.package = 'not_ready';
  status.readiness.findings.unshift({
    ...status.readiness.findings[0],
    code: 'cover_matches_interior',
    severity: 'error',
    area: 'cover',
    field: null,
    message: 'Cover is out of date because the interior paper changed (white -> cream).',
  });
  setup({ status });
  const panel = await screen.findByRole('complementary', { name: 'Readiness' });
  const line = within(panel).getAllByText(/interior paper changed/)[0];
  expect(line).toBeVisible();
  expect(within(panel).getByRole('link', { name: 'Rebuild in Cover' })).toHaveAttribute(
    'href',
    '/books/publishing-demo/cover',
  );
  expect(within(panel).getByRole('button', { name: 'Export package' })).toBeDisabled();
});

test('a book without publishing metadata starts explicitly', async () => {
  const bare = structuredClone(project) as unknown as { source: { publishing?: unknown } };
  delete bare.source.publishing;
  setup({ source: bare });
  const start = await screen.findByRole('button', { name: 'Start publishing metadata' });
  await userEvent.setup().click(start);
  expect(screen.getByLabelText(/Description \(0 of 4,000 characters\)/)).toBeVisible();
  expect(within(workspace()).getByText('Unsaved changes')).toBeVisible();
});
