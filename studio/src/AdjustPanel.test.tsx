import { expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';
import coloringProject from './fixtures/coloring-project.json';
import coloringListing from './fixtures/coloring-listing.json';
import plain from './fixtures/coloring-preparation.json';
import thin from './fixtures/coloring-preparation-thin.json';

const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

type Handler = (body: Record<string, unknown>) => Promise<Response> | Response;

function mockApi(prepare: Handler, adjust?: Handler) {
  const sent: { url: string; body: Record<string, unknown> }[] = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    if (url === '/api/projects/coloring-demo') return json(coloringProject);
    if (url === '/api/projects/coloring-demo/coloring') return json(coloringListing);
    if (url.endsWith('/coloring/prepare')) {
      sent.push({ url, body });
      return prepare(body);
    }
    if (url.endsWith('/coloring/adjustments') && adjust) {
      sent.push({ url, body });
      return adjust(body);
    }
    throw new Error(`Unexpected request ${url}`);
  });
  return sent;
}

async function openPanel() {
  history.pushState(null, '', '/books/coloring-demo/artwork');
  const user = userEvent.setup();
  render(<App />);
  const list = await screen.findByRole('list', { name: 'Artwork' });
  const row = within(list).getAllByRole('listitem')[0];
  await user.click(within(row).getByRole('button', { name: 'Prepare line art…' }));
  const panel = within(row).getByRole('region', {
    name: /Prepare .Fox in the Ferns. for printing/,
  });
  return { user, panel: within(panel) };
}

test('the panel previews the saved settings with Python images and checks', async () => {
  const sent = mockApi(() => json(plain));
  const { panel } = await openPanel();
  expect(await panel.findByText('Preview shows these settings')).toBeVisible();
  expect(panel.getByRole('img', { name: 'Original: Fox in the Ferns' })).toHaveAttribute(
    'src',
    plain.images.original,
  );
  expect(panel.getByRole('img', { name: 'Prepared: Fox in the Ferns' })).toBeVisible();
  expect(panel.getByText('No findings')).toBeVisible();
  expect(panel.getByRole('button', { name: 'Save settings' })).toBeDisabled();
  expect(sent[0].body).toEqual({ artwork: 'fox-in-the-ferns', adjustments: plain.adjustments });
});

test('a slower answer for older settings never replaces the current preview', async () => {
  let releaseFirst: (value: Response) => void = () => undefined;
  const sent = mockApi((body) => {
    const weight = (body.adjustments as { line_weight: number }).line_weight;
    if (weight === 0) return new Promise<Response>((resolve) => (releaseFirst = resolve));
    return json(thin);
  });
  const { user, panel } = await openPanel();
  await waitFor(() => expect(sent).toHaveLength(1));
  await user.selectOptions(panel.getByRole('combobox', { name: 'Line weight' }), '-2');
  expect(await panel.findByText(/no longer printed as ink/)).toBeVisible();
  releaseFirst(json(plain)); // The answer for the first settings arrives last.
  await new Promise((resume) => setTimeout(resume, 50));
  expect(panel.getByText(/no longer printed as ink/)).toBeVisible();
  expect(panel.queryByText('No findings')).not.toBeInTheDocument();
  expect(panel.getByText('Preview shows these settings')).toBeVisible();
  expect(panel.getByText(/Unsaved settings/)).toBeVisible();
});

test('save sends the settings with the saved revision; reset sends defaults as null', async () => {
  const savedListing = structuredClone(coloringListing);
  const sent = mockApi(
    (body) => json((body.adjustments as { line_weight: number }).line_weight === 0 ? plain : thin),
    (body) => {
      savedListing.revision = 'sha256-after';
      savedListing.report.artwork[0].adjustments.line_weight = body.adjustments
        ? (body.adjustments as { line_weight: number }).line_weight
        : 0;
      return json({ ...savedListing, artwork: 'fox-in-the-ferns' });
    },
  );
  const { user, panel } = await openPanel();
  await panel.findByText('Preview shows these settings');
  await user.selectOptions(panel.getByRole('combobox', { name: 'Line weight' }), '-2');
  await user.click(panel.getByRole('button', { name: 'Save settings' }));
  expect(await panel.findByText(/Settings saved. The original file is unchanged/)).toBeVisible();
  const save = sent.find((item) => item.url.endsWith('/adjustments'))!;
  expect(save.body).toEqual({
    artwork: 'fox-in-the-ferns',
    revision: coloringListing.revision,
    adjustments: { ...plain.adjustments, line_weight: -2 },
  });
  await user.click(panel.getByRole('button', { name: 'Reset to defaults' }));
  expect(panel.getByRole('combobox', { name: 'Line weight' })).toHaveValue('0');
  await user.click(panel.getByRole('button', { name: 'Save settings' }));
  await waitFor(() =>
    expect(sent.filter((item) => item.url.endsWith('/adjustments'))).toHaveLength(2),
  );
  const reset = sent.filter((item) => item.url.endsWith('/adjustments'))[1];
  expect(reset.body).toEqual({
    artwork: 'fox-in-the-ferns',
    revision: 'sha256-after',
    adjustments: null,
  });
});

test('revert restores the saved settings and failures are shown, never hidden', async () => {
  mockApi((body) =>
    (body.adjustments as { contrast: number }).contrast === 1
      ? json(plain)
      : json(
          { error: { code: 'too_much_ink_to_despeckle', message: 'Too much ink.', issues: [] } },
          422,
        ),
  );
  const { user, panel } = await openPanel();
  await panel.findByText('Preview shows these settings');
  // jsdom has no keyboard stepping for range inputs; the browser test drives the real one.
  fireEvent.change(panel.getByRole('slider', { name: 'Contrast' }), { target: { value: '1.5' } });
  expect(await panel.findByRole('alert')).toHaveTextContent('Too much ink.');
  expect(panel.getByText('Preview failed')).toBeVisible();
  await user.click(panel.getByRole('button', { name: 'Revert to saved' }));
  expect(await panel.findByText('Preview shows these settings')).toBeVisible();
  expect(panel.queryByRole('alert')).not.toBeInTheDocument();
});
