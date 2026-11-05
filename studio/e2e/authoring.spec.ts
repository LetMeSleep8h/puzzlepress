import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// The whole coloring journey without YAML: create, import, arrange, place, settings,
// build and view. Drawings are SYNTHETIC (tests/coloring_helpers.py).
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOTS = path.resolve(HERE, '..', '..', 'docs', 'images', 'authoring');
const WORD_SEARCH_TERMS = /\b(puzzles?|solutions?|word search(es)?|word banks?|grids?)\b/i;

function drawings(): string[] {
  const folder = mkdtempSync(path.join(tmpdir(), 'puzzlepress-journey-'));
  const python = path.resolve(
    HERE,
    '..',
    '..',
    '.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
  );
  const script = [
    'import sys',
    "sys.path.insert(0, 'tests')",
    'from pathlib import Path',
    'from coloring_helpers import png',
    'out = Path(sys.argv[1])',
    "(out / 'Meadow fox.png').write_bytes(png(11))",
    "(out / 'Meadow owl.png').write_bytes(png(12))",
    "(out / 'Meadow hare.png').write_bytes(png(13))",
  ].join('\n');
  execFileSync(python, ['-c', script, folder], { cwd: path.resolve(HERE, '..', '..') });
  return ['Meadow fox.png', 'Meadow owl.png', 'Meadow hare.png'].map((n) => path.join(folder, n));
}

async function check(page: Page, name: string, widths = [1440, 1024, 768, 390]) {
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  mkdirSync(SHOTS, { recursive: true });
  for (const width of widths) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      `${name} overflows at ${width}px`,
    ).toBeTruthy();
    if (width === 1440 || width === 390)
      await page.screenshot({ path: path.join(SHOTS, `${name}-${width}.png`) });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

function rows(page: Page) {
  return page
    .getByRole('list', { name: 'Drawings and dividers in printing order' })
    .getByRole('listitem');
}

// Every action gives up after a minute, so a stall names its step instead of using up
// the whole test budget (CI runners are much slower than a desktop at Python's work).
test.use({ actionTimeout: 60000 });

const started = Date.now();
function mark(step: string) {
  // Printed with a failure on CI: where the journey was and how long it had taken.
  console.log(`[journey] ${((Date.now() - started) / 1000).toFixed(1)} s: ${step}`);
}

test('a coloring book from New book to a built, zoomable proof, without YAML', async ({ page }) => {
  test.setTimeout(600000);
  mark('start');
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/books');
  await page.getByRole('main').getByRole('link', { name: 'New book' }).click();
  await expect(page.getByRole('heading', { name: 'New book', level: 1 })).toBeVisible();
  await expect(page.getByRole('radio', { name: /Sudoku/ })).toBeDisabled();
  await page.getByRole('radio', { name: /Coloring Book/ }).check();
  await expect(page.getByRole('heading', { name: /About your coloring book/ })).toBeFocused();
  await page.getByRole('textbox', { name: 'Book title' }).fill('Meadow Coloring');
  await page.getByRole('textbox', { name: 'Author or pen name (optional)' }).fill('A. Artist');
  await page.getByRole('textbox', { name: 'Subject (optional)' }).fill('Nature');
  await page.getByRole('radio', { name: 'Cream paper' }).check();
  await check(page, 'create');
  mark('created');
  await page.getByRole('button', { name: 'Create book' }).click();
  await expect(page).toHaveURL(/\/books\/meadow-coloring\/artwork$/);

  // Creating the same folder again is refused and nothing is replaced.
  await page.goto('/create');
  await page.getByRole('radio', { name: /Coloring Book/ }).check();
  await page.getByRole('textbox', { name: 'Book title' }).fill('Meadow Coloring');
  await page.getByRole('button', { name: 'Create book' }).click();
  await expect(
    page.getByRole('heading', { name: 'That project folder already exists' }),
  ).toBeVisible();
  await page.goto('/books');
  await expect(page.locator('article.book-row', { hasText: 'Meadow Coloring' })).toContainText(
    'Nature',
  );

  await page.goto('/books/meadow-coloring');
  await expect(page.getByText(/has no coloring pages yet/)).toBeVisible();
  mark('import');
  await page.goto('/books/meadow-coloring/artwork');
  await page.getByLabel('Import artwork (PNG or JPEG, several at once)').setInputFiles(drawings());
  await expect(page.getByRole('img', { name: /Meadow hare/ }).first()).toBeVisible({
    timeout: 60000,
  });

  mark('pages');
  await page.goto('/books/meadow-coloring/pages');
  await expect(page.getByText('Plan verified')).toBeVisible({ timeout: 90000 });
  await expect(rows(page)).toHaveCount(3);
  await page.getByRole('button', { name: /^Design Meadow owl/ }).click();
  const designer = page.getByRole('region', { name: /Designing entry 2/ });
  await designer.getByRole('slider', { name: 'Size' }).fill('0.75');
  await designer.getByRole('slider', { name: 'Vertical position' }).fill('1');
  await expect(designer.getByText(/DPI\./)).toBeVisible({ timeout: 60000 });
  await expect(page.getByText('Plan verified')).toBeVisible({ timeout: 90000 });
  mark('zoom designer');
  // Zoom and pan the designed page; the view only resizes what is drawn.
  await designer.getByRole('button', { name: 'Zoom in' }).click();
  await designer.getByRole('button', { name: 'Zoom in' }).click();
  await designer.getByRole('combobox', { name: 'Zoom level' }).selectOption('width');
  await designer.getByRole('button', { name: 'Reset view' }).click();
  await expect(designer.getByRole('combobox', { name: 'Zoom level' })).toHaveValue('page');
  mark('reorder and undo');
  // Keyboard reorder and undo/redo.
  await page.getByRole('button', { name: /^Move Meadow hare up/ }).focus();
  await page.keyboard.press('Enter');
  await expect(rows(page).nth(1)).toContainText('Meadow hare');
  await page.getByRole('heading', { name: 'Drawings and dividers' }).click();
  await page.keyboard.press('Control+z');
  await expect(rows(page).nth(1)).toContainText('Meadow owl');
  await page.keyboard.press('Control+Shift+z');
  await expect(rows(page).nth(1)).toContainText('Meadow hare');
  await expect(page.getByText('Plan verified')).toBeVisible({ timeout: 90000 });
  await expect(page.getByRole('main')).not.toHaveText(WORD_SEARCH_TERMS);
  mark('pages checks');
  await check(page, 'pages');
  const saved = page.waitForResponse((r) => r.url().endsWith('/draft/save'));
  await page.getByRole('button', { name: 'Save changes' }).click();
  expect((await saved).status()).toBe(200);
  await page.reload();
  await expect(page.getByText('Plan verified')).toBeVisible({ timeout: 90000 });
  await expect(page.getByText(/placed 75%/)).toBeVisible();

  mark('settings');
  await page.goto('/books/meadow-coloring/settings');
  await expect(page.getByRole('radio', { name: /Cream paper/ })).toBeChecked();
  await page.getByRole('textbox', { name: 'Collection (optional)' }).fill('Meadow series');
  await check(page, 'settings');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('Saved and reloaded from source.')).toBeVisible();

  mark('print');
  await page.goto('/books/meadow-coloring/print');
  await expect(page.getByText(/from this book.s/)).toBeVisible({ timeout: 60000 });
  mark('build');
  await page.getByRole('button', { name: 'Build interior' }).click();
  const zoom = page.getByRole('combobox', { name: 'Zoom level' });
  await expect(zoom).toBeVisible({ timeout: 120000 });
  mark('zoom proof');
  await zoom.selectOption('width');
  await page.getByRole('button', { name: 'Zoom in' }).click();
  const canvas = page.locator('.print-canvas');
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 120, box.y + box.height / 2 - 120, { steps: 5 });
  await page.mouse.up();
  expect(await canvas.evaluate((e) => e.scrollTop + e.scrollLeft)).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Reset view' }).click();
  await expect(zoom).toHaveValue('fit');
  mark('print checks');
  await check(page, 'print', [1440, 390]);
});
