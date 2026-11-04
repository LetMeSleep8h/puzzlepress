import { test, expect, type Page, type Request } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// Cover templates, rich text and the Cover Studio fixes, on a disposable copy of the
// cover demo. Every preview and thumbnail is Python's; these tests check that browsing
// saves nothing, applying only changes the undoable draft, and formatting stays on the
// selection.

const KEY = 'template-demo';
const shot = (name: string) => `../docs/images/studio/${name}.png`;
const WIDTHS: [string, number, number][] = [
  ['1440', 1440, 1000],
  ['1024', 1024, 900],
  ['768', 768, 1000],
  ['390', 390, 844],
];
type Sent = {
  book: { title: string };
  cover: {
    version: number;
    back_text?: string | { rich: number; blocks: { runs: Record<string, unknown>[] }[] };
    elements?: { id: string }[];
  };
};

async function noAxeViolations(page: Page) {
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
}

// No horizontal page scroll; on failure, name what sticks out.
async function noOverflow(page: Page) {
  const wide = await page.evaluate(() => {
    if (document.documentElement.scrollWidth <= window.innerWidth) return [];
    return Array.from(document.querySelectorAll('body *'))
      .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
      .slice(0, 5)
      .map((el) => `${el.tagName.toLowerCase()}.${el.className}`);
  });
  expect(wide).toEqual([]);
}

async function capture(page: Page, name: string, fullPage: boolean) {
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: shot(name), fullPage });
}

function draft(page: Page, accept: (source: Sent) => boolean = () => true) {
  return page.waitForResponse(
    (r) =>
      r.url().endsWith('/draft/cover') &&
      r.status() === 200 &&
      accept((r.request().postDataJSON() as { source: Sent }).source),
  );
}

const backText = (source: Sent) => JSON.stringify(source.cover.back_text ?? '');
const isRich = (source: Sent) => typeof source.cover.back_text === 'object';

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

// The source each draft request sends, newest last.
function record(page: Page): Sent[] {
  const sent: Sent[] = [];
  page.on('request', (request: Request) => {
    if (request.url().endsWith('/draft/cover'))
      sent.push((request.postDataJSON() as { source: Sent }).source);
  });
  return sent;
}

async function saved(page: Page): Promise<Sent> {
  return page.evaluate(async (key) => {
    const response = await fetch(`/api/projects/${key}`);
    return ((await response.json()) as { source: Sent }).source;
  }, KEY);
}

async function save(page: Page) {
  const done = page.waitForResponse((r) => r.url().endsWith('/draft/save'));
  await page.getByRole('button', { name: 'Save changes' }).click();
  expect((await done).status()).toBe(200);
  await expect(page.locator('.toolbar-message:visible')).toHaveText(
    'Saved and reloaded from source.',
  );
}

test.describe.configure({ mode: 'serial' });

test('photo library: in-use photos link to their layer; unused photos go to the trash', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/books/${KEY}/print`);
  const built = page.waitForResponse((r) => r.url().endsWith('/interior/build'));
  await page.getByRole('button', { name: 'Build interior' }).click();
  expect((await built).status()).toBe(200);

  await openCover(page);
  await page.getByRole('tab', { name: 'Photos' }).click();
  // The cover's photograph cannot be removed and says where it is used.
  await expect(
    page.getByRole('button', { name: /^Remove harbour-dusk.* \(unavailable: in use\)$/ }),
  ).toBeDisabled();
  const uses = page.locator('.photo-uses');
  await expect(uses).toHaveCount(1);
  await uses.getByRole('button').first().click();
  await expect(page.getByRole('group', { name: /Photograph selected/ })).toBeVisible();

  // An unused photograph is removed only after confirmation, to the project's trash.
  const remove = page.getByRole('button', { name: /^Remove spare-photo.* from the project$/ });
  await expect(remove).toBeEnabled();
  page.once('dialog', (dialog) => void dialog.dismiss());
  await remove.click();
  await expect(remove).toBeVisible();
  page.once('dialog', (dialog) => {
    expect(dialog.message()).toMatch(/moves to this project's trash/);
    void dialog.accept();
  });
  const trashed = page.waitForResponse((r) => r.url().endsWith('/assets/trash'));
  await remove.click();
  expect((await trashed).status()).toBe(200);
  await expect(page.getByText(/Moved spare-photo.* to the project's trash/)).toBeVisible();
  await expect(remove).toHaveCount(0);
  await noAxeViolations(page);
  await page.locator('.cover-tools').screenshot({ path: shot('cover-photo-library') });
});

test('templates: browse without saving, preview, apply, undo, save and reuse', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const writes: string[] = [];
  page.on('request', (request) => {
    if (
      request.method() === 'POST' &&
      /\/draft\/save$|\/cover\/templates(\/import|\/[^/]+\/(update|duplicate|delete))?$/.test(
        request.url(),
      )
    )
      writes.push(request.url());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openCover(page);
  const sent = record(page);
  const before = await saved(page);

  await page.getByRole('tab', { name: 'Templates' }).click();
  const gallery = page.getByRole('list', { name: 'Built-in templates' });
  await expect(gallery.getByRole('heading')).toHaveText([
    'Photographic Editorial',
    'Bold Garage',
    'Motorsport Energy',
    'Vintage Motoring',
    'Modern Minimal',
    'Technical Blueprint',
    'Classic Puzzle Collection',
    'Premium Editorial',
  ]);
  // Thumbnails are this book rendered by Python with each template.
  const thumb = page.getByRole('img', { name: /Photographic Editorial applied to this book/ });
  await expect(thumb).toBeVisible({ timeout: 20000 });
  await expect
    .poll(() => thumb.evaluate((i) => (i as HTMLImageElement).naturalWidth), { timeout: 20000 })
    .toBeGreaterThan(0);
  // Browsing writes nothing and does not touch the draft.
  expect(writes).toEqual([]);
  expect(sent).toEqual([]);

  await page
    .getByRole('button', { name: 'Preview Photographic Editorial before applying' })
    .click();
  const dialog = page.getByRole('dialog', { name: 'Photographic Editorial' });
  await expect(dialog.getByText(before.book.title, { exact: true })).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'Replaced by the template' })).toBeVisible();
  await expect(dialog.getByText(/every declaration are untouched/)).toBeVisible();
  await expect(
    dialog.getByRole('img', { name: /Your book with Photographic Editorial/ }),
  ).toBeVisible({ timeout: 20000 });
  await noAxeViolations(page);
  await dialog.screenshot({ path: shot('cover-template-preview') });
  // Cancel keeps the draft as it was.
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
  expect(sent).toEqual([]);

  // Apply: only the draft changes; the book's details stay.
  await page
    .getByRole('button', { name: 'Preview Photographic Editorial before applying' })
    .click();
  let next = draft(page);
  await dialog.getByRole('button', { name: 'Apply template' }).click();
  await next;
  await coverReady(page);
  expect(sent.at(-1)!.cover.version).toBe(3);
  expect(sent.at(-1)!.book).toEqual(before.book);
  await expect(page.getByText(/Applied “Photographic Editorial” to the draft/)).toBeVisible();
  expect(writes).toEqual([]);
  // Every applied element is an ordinary, editable layer.
  await page.getByRole('tab', { name: 'Layers' }).click();
  const layers = page.getByRole('list', { name: 'Design layers, top first' });
  expect(await layers.locator('.layer-name').count()).toBeGreaterThan(1);

  // Undo restores the previous cover exactly.
  next = draft(page);
  await page.getByRole('button', { name: 'Undo' }).click();
  await next;
  expect(sent.at(-1)!.cover).toEqual(before.cover);

  // Apply a second template and save: the title and book details are unchanged.
  await page.getByRole('tab', { name: 'Templates' }).click();
  await page.getByRole('button', { name: 'Preview Bold Garage before applying' }).click();
  next = draft(page);
  await page
    .getByRole('dialog', { name: 'Bold Garage' })
    .getByRole('button', { name: 'Apply template' })
    .click();
  await next;
  await coverReady(page);
  await save(page);
  const after = await saved(page);
  expect(after.book).toEqual(before.book);
  expect(after.cover.version).toBe(3);

  // Save the current design as a project template, then delete it with confirmation.
  await page.getByRole('tab', { name: 'Templates' }).click();
  await page.getByText('Save the current design as a template').click();
  await page.getByLabel('Template name').fill('Harbour house style');
  await page.getByLabel('Description').fill('Charcoal with the harbour photograph.');
  const created = page.waitForResponse((r) => /\/cover\/templates$/.test(r.url()));
  await page.getByRole('button', { name: 'Save as template' }).click();
  expect((await created).status()).toBe(200);
  const mine = page.getByRole('list', { name: 'Your templates' });
  await expect(mine.getByRole('heading', { name: 'Harbour house style' })).toBeVisible();
  // Regression: a click on Export downloads the file; the client router used to
  // swallow it and show "This Studio page does not exist".
  const [exported] = await Promise.all([
    page.waitForEvent('download'),
    mine.getByRole('link', { name: 'Export Harbour house style as a file' }).click(),
  ]);
  expect(exported.suggestedFilename()).toMatch(/\.json$/);
  await expect(page).toHaveURL(/\/books\/template-demo\/cover$/);
  await expect(page.getByRole('list', { name: 'Your templates' })).toBeVisible();
  // Built-in templates are protected.
  await expect(page.getByRole('button', { name: 'Delete Bold Garage' })).toHaveCount(0);
  await noAxeViolations(page);
  await page.locator('.cover-tools').screenshot({ path: shot('cover-templates') });
  page.once('dialog', (d) => void d.accept());
  const deleted = page.waitForResponse((r) => r.url().endsWith('/delete'));
  await page.getByRole('button', { name: 'Delete Harbour house style' }).click();
  expect((await deleted).status()).toBe(200);
  await expect(page.getByRole('list', { name: 'Your templates' })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('the template gallery and overlay menu fit at every width', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openCover(page);
  await page.getByRole('tab', { name: 'Templates' }).click();
  // Every card shows this book rendered with its template before the captures.
  const thumbs = page.getByRole('list', { name: 'Built-in templates' }).locator('img');
  await expect(thumbs).toHaveCount(8, { timeout: 30000 });
  await expect
    .poll(() =>
      thumbs.evaluateAll((all) => all.every((i) => (i as HTMLImageElement).naturalWidth > 0)),
    )
    .toBe(true);
  for (const [name, width, height] of WIDTHS) {
    await page.setViewportSize({ width, height });
    await noOverflow(page);
    const menu = page.locator('.stage-toolbar details.menu');
    await menu.locator('summary').click();
    const body = (await menu.locator('.menu-body').boundingBox())!;
    expect(body.x).toBeGreaterThanOrEqual(0);
    expect(body.x + body.width).toBeLessThanOrEqual(width);
    await noAxeViolations(page);
    await menu.locator('summary').click();
    await capture(page, `cover-templates-${name}`, name === '390');
  }
});

test('rich text: format the selection, keep it through typing and undo, save and build', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openCover(page);
  const sent = record(page);
  await page.getByRole('tab', { name: 'Text' }).click();
  await page
    .getByRole('list', { name: 'Cover text layers' })
    .getByRole('button', { name: /^Back-cover text/ })
    .click();
  const editor = page.getByRole('textbox', { name: 'Back-cover text' });
  await expect(editor).toContainText('Twenty word searches');
  const toolbar = page.getByRole('toolbar', { name: 'Back-cover text formatting' });

  // Select the first word by keyboard and make it bold with the shortcut.
  await editor.click();
  await page.keyboard.press('Control+Home');
  await page.keyboard.press('Control+Shift+ArrowRight');
  // Edits reach Python after a debounce, so an earlier preview can still be in flight:
  // wait for the preview of this edit, not merely the next response.
  let next = draft(page, isRich);
  await page.keyboard.press('Control+b');
  await next;
  const rich = () => {
    const value = sent.at(-1)!.cover.back_text;
    expect(typeof value).toBe('object');
    return value as Exclude<Sent['cover']['back_text'], string | undefined>;
  };
  expect(rich().blocks[0].runs[0]).toEqual({ text: 'Twenty', bold: true });
  expect(rich().blocks[0].runs[1]).toMatchObject({ text: expect.stringMatching(/^ word/) });
  await expect(toolbar.getByRole('button', { name: 'Bold' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  // Bold italic is not a bundled sans face, so Italic says why it is unavailable.
  await expect(toolbar.getByRole('button', { name: 'Italic' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );

  // Typing at the end of the text keeps the bold word as it is.
  await page.keyboard.press('Control+End');
  next = draft(page, (source) => backText(source).includes('Enjoy.'));
  await page.keyboard.type(' Enjoy.');
  await next;
  expect(rich().blocks[0].runs[0]).toEqual({ text: 'Twenty', bold: true });
  await expect(editor).toContainText('Enjoy.');
  // Undo removes the typing, not the formatting.
  next = draft(page, (source) => isRich(source) && !backText(source).includes('Enjoy.'));
  await page.getByRole('button', { name: 'Undo' }).click();
  await next;
  await expect(editor).not.toContainText('Enjoy.');
  expect(rich().blocks[0].runs[0]).toEqual({ text: 'Twenty', bold: true });
  await noAxeViolations(page);
  await page
    .locator('.rich-editor')
    .first()
    .screenshot({ path: shot('cover-rich-text') });

  // Saved and built: Python lays out the rich text in the cover PDF.
  await save(page);
  const source = await saved(page);
  expect(source.cover.back_text).toMatchObject({ rich: 1 });
  await page.getByRole('tab', { name: /Checks/ }).click();
  const cover = page.waitForResponse((r) => r.url().endsWith('/cover/build'));
  await page.getByRole('button', { name: /Build cover|Rebuild cover/ }).click();
  expect((await cover).status()).toBe(200);
  await expect(page.getByText('Cover built and preflight complete.')).toBeVisible();
});
