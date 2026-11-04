import { test, expect, type Locator, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// Production design and publishing polish, on a disposable copy of the cover demo.
// Every preview is Python's; these tests check the controls, keyboard paths and
// that nothing is claimed before the server confirms it.

const KEY = 'design-demo';
const shot = (name: string) => `../docs/images/studio/${name}.png`;

// Full-page captures start at the top with nothing focused, so the sticky header and
// the skip link are not painted halfway down the image.
async function capture(page: Page, name: string, fullPage: boolean) {
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: shot(name), fullPage });
}

// Element captures clip a full-page capture taken from the top, so tall elements are
// never scrolled under the sticky header.
async function captureElement(page: Page, selector: string | Locator, name: string) {
  const element = typeof selector === 'string' ? page.locator(selector) : selector;
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  const box = await element.boundingBox();
  if (!box) throw new Error(`${name}: element is not visible`);
  await page.screenshot({ path: shot(name), fullPage: true, clip: box });
}
const WIDTHS: [string, number, number][] = [
  ['1440', 1440, 1000],
  ['1024', 1024, 900],
  ['768', 768, 1000],
  ['390', 390, 844],
];

async function noAxeViolations(page: Page) {
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
}

function draft(page: Page, path = '/draft/cover') {
  return page.waitForResponse((r) => r.url().endsWith(path) && r.status() === 200);
}

async function coverReady(page: Page) {
  const image = page.locator('.cover-window img');
  await expect(image).toBeVisible();
  await expect
    .poll(() =>
      image.evaluate(
        (i) => (i as HTMLImageElement).complete && (i as HTMLImageElement).naturalWidth > 0,
      ),
    )
    .toBe(true);
}

async function openCover(page: Page) {
  const first = draft(page);
  await page.goto(`/books/${KEY}/cover`);
  await first;
  await coverReady(page);
}

async function save(page: Page) {
  const saved = page.waitForResponse((r) => r.url().endsWith('/draft/save'));
  await page.getByRole('button', { name: 'Save changes' }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.locator('.toolbar-message:visible')).toHaveText(
    'Saved and reloaded from source.',
  );
}

test.describe.configure({ mode: 'serial' });

test('region design: convert, add, nudge, lock, reorder, save and build', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/books/${KEY}/print`);
  const built = page.waitForResponse((r) => r.url().endsWith('/interior/build'));
  await page.getByRole('button', { name: 'Build interior' }).click();
  expect((await built).status()).toBe(200);

  await openCover(page);
  await page.getByRole('tab', { name: 'Layers' }).click();
  await page.getByRole('button', { name: 'Preview region design…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Convert to a region design' });
  await expect(dialog.getByText(/the PDFs are byte-identical/)).toBeVisible();
  await noAxeViolations(page);
  await captureElement(page, '.dialog', 'cover-convert');
  const converted = draft(page);
  await dialog.getByRole('button', { name: 'Use region design' }).press('Enter');
  await converted;
  await coverReady(page);

  // Keyboard: choose the front region, then add a rectangle there.
  await page.getByRole('button', { name: 'Front region' }).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('tab', { name: 'Shapes' }).click();
  let next = draft(page);
  await page.getByRole('button', { name: 'Add rectangle' }).click();
  await next;
  await expect(page.getByRole('heading', { name: 'Rectangle block-1' })).toBeVisible();
  const x = page.getByLabel('X from left');
  await expect(x).toHaveValue('198');

  // Arrow keys move an unlocked element by points; Python lays it out again.
  next = draft(page);
  await page.locator('.cover-canvas').focus();
  await page.keyboard.press('Shift+ArrowRight');
  await next;
  await expect(x).toHaveValue('208');

  // A locked element does not move from the canvas and its fields are read-only.
  await page.getByRole('tab', { name: 'Layers' }).click();
  await page.getByRole('button', { name: 'Lock Rectangle block-1' }).click();
  await page.locator('.cover-canvas').focus();
  await page.keyboard.press('Shift+ArrowRight');
  await expect(x).toHaveValue('208');
  await expect(x).toBeDisabled();

  // A second element, reordered from the layer list by keyboard, then deleted.
  await page.getByRole('tab', { name: 'Shapes' }).click();
  next = draft(page);
  await page.getByRole('button', { name: 'Add ellipse' }).click();
  await next;
  await page.getByRole('tab', { name: 'Layers' }).click();
  const layers = page.getByRole('list', { name: 'Design layers, top first' });
  await expect(layers.locator('.layer-name')).toHaveText([
    'Ellipse ellipse-1',
    'Rectangle block-1',
    'Photograph photo',
  ]);
  await page.getByRole('button', { name: 'Send Ellipse ellipse-1 backward' }).focus();
  await page.keyboard.press('Enter');
  await expect(layers.locator('.layer-name')).toHaveText([
    'Rectangle block-1',
    'Ellipse ellipse-1',
    'Photograph photo',
  ]);
  await captureElement(page, '.cover-studio', 'cover-layers-stack');
  await layers.getByRole('button', { name: /^Ellipse ellipse-1/ }).click();
  page.once('dialog', (d) => void d.accept());
  await page.getByRole('button', { name: 'Delete' }).click();
  await expect(layers.locator('.layer-name')).toHaveText(['Rectangle block-1', 'Photograph photo']);

  // Undo brings the element back; save; the reloaded design keeps its lock.
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(layers.locator('.layer-name')).toHaveCount(3);
  await save(page);
  await page.reload();
  await page.getByRole('tab', { name: 'Layers' }).click();
  await expect(page.getByRole('button', { name: 'Unlock Rectangle block-1' })).toBeVisible();

  // Build the region design from the saved source.
  await page.getByRole('tab', { name: /Checks/ }).click();
  const cover = page.waitForResponse((r) => r.url().endsWith('/cover/build'));
  await page.getByRole('button', { name: /Build cover|Rebuild cover/ }).click();
  expect((await cover).status()).toBe(200);
  await expect(page.getByText('Cover built and preflight complete.')).toBeVisible();
  await noAxeViolations(page);
  for (const [name, width, height] of WIDTHS) {
    await page.setViewportSize({ width, height });
    await noOverflow(page);
    await capture(page, `cover-regions-${name}`, name === '390');
  }
  expect(errors).toEqual([]);
});

test('assets: an unused photo goes to the trash and back; used assets are protected', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openCover(page);
  await page.getByRole('tab', { name: 'Assets' }).click();
  const list = page.getByRole('list', { name: 'Project assets' });
  await expect(list.locator('.asset-state.unused')).toHaveText(['Unused']);
  await expect(list.locator('.asset-state.in-use')).not.toHaveCount(0);
  await expect(page.getByRole('button', { name: /^Remove harbour-dusk/ })).toBeDisabled();
  const spare = page.getByRole('button', { name: /^Remove spare-photo/ });
  await spare.focus();
  await page.keyboard.press('Enter');
  const confirm = page.getByRole('alertdialog', { name: /^Remove spare-photo/ });
  await expect(confirm.getByText(/moves to this project's trash/)).toBeVisible();
  await expect(confirm.getByText(/^[0-9a-f]{64}$/)).toBeVisible();
  await noAxeViolations(page);
  await captureElement(page, '.dialog', 'assets-remove');
  await confirm.getByRole('button', { name: 'Cancel' }).press('Enter');
  await expect(confirm).toBeHidden();
  await spare.click();
  const trashed = page.waitForResponse((r) => r.url().endsWith('/assets/trash'));
  await page.getByRole('button', { name: 'Move to trash' }).press('Enter');
  expect((await trashed).status()).toBe(200);
  await expect(page.getByText(/Moved spare-photo.* to the project's trash/)).toBeVisible();
  await page.getByText('Trash (1)').click();
  await expect(page.getByRole('button', { name: 'Restore' })).toBeVisible();
  await captureElement(page, '.cover-tools', 'assets-library');
  // A full-page capture briefly resizes the page, which can move the tool panel between
  // layouts and close the trash; open it again before restoring.
  const trash = page.locator('.asset-trash');
  if (!(await trash.evaluate((d) => (d as HTMLDetailsElement).open)))
    await page.getByText('Trash (1)').click();
  const restored = page.waitForResponse((r) => r.url().endsWith('/assets/restore'));
  await page.getByRole('button', { name: 'Restore' }).click();
  expect((await restored).status()).toBe(200);
  await expect(page.getByText(/^Restored cover-assets\/spare-photo/)).toBeVisible();
  await noAxeViolations(page);
});

test('interior design: preset, dividers and Python sample pages', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/books/${KEY}/interior`);
  await page.getByRole('tab', { name: 'Theme' }).click();
  await page.getByRole('button', { name: 'Add an interior design' }).click();
  let preview = draft(page, '/draft/interior');
  await page.getByRole('radio', { name: /High Contrast/ }).check();
  await preview;
  const samples = page.locator('.preview-pages img');
  await expect(samples.first()).toBeVisible();
  await page.getByRole('tab', { name: 'Title & dividers' }).click();
  preview = draft(page, '/draft/interior');
  await page.getByRole('checkbox', { name: /Add theme divider pages/ }).focus();
  await page.keyboard.press('Space');
  await preview;
  await expect(page.getByText('Changes the page count')).toBeVisible();
  await page.getByRole('button', { name: 'Divider', exact: true }).click();
  await expect(page.getByRole('img', { name: /Draft divider/ })).toBeVisible();
  // Turn dividers off again: the built page count stays as it was.
  preview = draft(page, '/draft/interior');
  await page.getByRole('checkbox', { name: /Add theme divider pages/ }).uncheck();
  await preview;
  await expect(page.getByText('Changes the page count')).toBeHidden();
  await noAxeViolations(page);
  await save(page);
  for (const [name, width, height] of WIDTHS) {
    await page.setViewportSize({ width, height });
    await noOverflow(page);
    if (name === '1440' || name === '390')
      await capture(page, `interior-design-${name}`, name === '390');
  }
});

test('rebuild: the stale banner explains, plans and reports confirmed results', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/books/${KEY}/print`);
  const banner = page.locator('.stale-banner');
  await expect(banner.getByText('This interior is out of date.')).toBeVisible();
  await expect(banner.getByText(/interior style was added/)).toBeVisible();
  // The plan comes from GET /production, which reruns interior and cover preflight
  // in Python: wait for that response (like /rebuild below) instead of racing it
  // against the default assertion timeout on slower machines.
  const planned = page.waitForResponse(
    (r) => r.url().endsWith('/production') && r.request().method() === 'GET',
  );
  await banner.getByRole('button', { name: 'Rebuild outdated artifacts…' }).click();
  const panel = page.getByRole('region', { name: 'Rebuild outdated artifacts' });
  expect((await planned).status()).toBe(200);
  await expect(panel.getByText('Checking which artifacts are out of date…')).toBeHidden();
  await expect(panel.getByText('Rebuild the interior and its preflight report')).toBeVisible();
  await noAxeViolations(page);
  await captureElement(page, panel, 'rebuild-plan');
  const rebuilt = page.waitForResponse((r) => r.url().endsWith('/rebuild'));
  await panel.getByRole('button', { name: /^Rebuild \d steps?$/ }).focus();
  await page.keyboard.press('Enter');
  expect((await rebuilt).status()).toBe(200);
  const results = panel.getByRole('list', { name: 'Rebuild results' });
  await expect(results.getByText('succeeded').first()).toBeVisible();
  await expect(panel.getByText(/server confirmed every step/)).toBeVisible();
  await captureElement(page, panel, 'rebuild-results');
  await expect(page.locator('.stale-banner')).toBeHidden();
  await noOverflow(page);
});

test('editorial review: record, filter, move on, and see it go stale on edit', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/books/${KEY}/edit`);
  const recorded = page.waitForResponse((r) => r.url().endsWith('/reviews/record'));
  await page.getByRole('button', { name: 'Mark reviewed' }).focus();
  await page.keyboard.press('Enter');
  expect((await recorded).status()).toBe(200);
  await expect(page.getByLabel('Review progress')).toContainText('1 of 20 reviewed');
  await page.getByLabel('Filter by review state').selectOption('reviewed');
  await expect(page.getByText('Showing 1 of 20')).toBeVisible();
  await page.getByLabel('Filter by review state').selectOption('');
  await page.getByRole('button', { name: 'Next unreviewed' }).click();
  await expect(page.getByRole('heading', { name: /Puzzle 2/ })).toBeVisible();
  await noAxeViolations(page);
  await captureElement(page, '.editor-layout', 'puzzles-review');
  // Editing the reviewed puzzle and saving makes its review stale.
  await page.getByRole('button', { name: /^1\./ }).click();
  await page.getByLabel('Puzzle title').fill('Harbour Revisited');
  await expect(page.getByRole('button', { name: 'Mark reviewed' })).toBeDisabled();
  await save(page);
  await expect(page.locator('.review-head')).toContainText('Stale review');
  for (const [, width, height] of WIDTHS) {
    await page.setViewportSize({ width, height });
    await noOverflow(page);
  }
});

test('publishing: final steps keep decisions open and record a proof honestly', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  // Final steps come from GET /production, which reruns interior and cover preflight
  // in Python: wait for that response instead of racing it on slower machines.
  const assessed = page.waitForResponse(
    (r) => r.url().endsWith('/production') && r.request().method() === 'GET',
  );
  await page.goto(`/books/${KEY}/publishing`);
  expect((await assessed).status()).toBe(200);
  await expect(page.getByText('Checking every production step…')).toBeHidden();
  const overview = page.getByRole('region', { name: 'Final steps' });
  await expect(overview.getByRole('heading', { name: 'Final steps' })).toBeVisible();
  const checklist = overview.getByRole('list', { name: 'Production checklist' });
  await expect(checklist.getByText('Human content review')).toBeVisible();
  await expect(overview.getByRole('list', { name: 'Production stages' })).toContainText(
    'Not tracked',
  );
  await expect(overview.getByLabel('Your decision')).toHaveValue('undecided');
  const proof = page.waitForResponse((r) => r.url().endsWith('/proofs/record'));
  // Recording reloads the production status (GET /production) to list the record.
  const reassessed = page.waitForResponse(
    (r) => r.url().endsWith('/production') && r.request().method() === 'GET',
  );
  await overview.getByRole('button', { name: 'Record proof' }).click();
  expect((await proof).status()).toBe(200);
  expect((await reassessed).status()).toBe(200);
  await expect(overview.getByText(/Recorded proof-1/)).toBeVisible();
  await expect(overview.getByText('Print Previewer', { exact: true })).toBeVisible();
  await noAxeViolations(page);
  await captureElement(page, overview, 'publishing-final-steps');
  // Keyboard navigation from a checklist item to where it is fixed.
  const disclosure = checklist.getByRole('listitem').filter({ hasText: 'AI disclosure' });
  await disclosure.locator('summary').focus();
  await page.keyboard.press('Enter');
  const link = disclosure.getByRole('link', { name: 'Open publishing' });
  await expect(link).toHaveAttribute('href', `/books/${KEY}/publishing`);
  for (const [, width, height] of WIDTHS) {
    await page.setViewportSize({ width, height });
    await noOverflow(page);
  }
});
