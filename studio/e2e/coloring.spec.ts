import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

// SYNTHETIC line art drawn by tests/coloring_helpers.py, written to a scratch folder.
function drawings(): { full: string; small: string; copy: string; svg: string } {
  const folder = mkdtempSync(path.join(tmpdir(), 'puzzlepress-art-'));
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
    'from coloring_helpers import encode, line_art, png',
    'out = Path(sys.argv[1])',
    "(out / 'Fox in the Ferns.png').write_bytes(png(1))",
    "(out / 'Small owl.png').write_bytes(encode(line_art(4, size=(600, 800))))",
    "(out / 'Fox again.jpg').write_bytes(encode(line_art(1).convert('RGB'), 'JPEG', quality=90))",
  ].join('\n');
  execFileSync(python, ['-c', script, folder], { cwd: path.resolve(HERE, '..', '..') });
  const svg = path.join(folder, 'vector.svg');
  writeFileSync(svg, "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>");
  return {
    full: path.join(folder, 'Fox in the Ferns.png'),
    small: path.join(folder, 'Small owl.png'),
    copy: path.join(folder, 'Fox again.jpg'),
    svg,
  };
}

const WORD_SEARCH_TERMS = /\b(puzzles?|solutions?|word search(es)?|word banks?|grids?)\b/i;

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
}

test('coloring artwork: import, check, refuse SVG, find look-alikes, remove', async ({ page }) => {
  const files = drawings();
  await page.goto('/books');
  const row = page.locator('article.book-row', { hasText: 'Synthetic Coloring Book' });
  await expect(row.getByText('Coloring book', { exact: true }).last()).toBeVisible();

  await page.goto('/books/coloring-demo');
  const nav = page.getByRole('navigation', { name: 'Project' });
  await expect(nav.getByRole('link')).toHaveText([
    'Overview',
    'Settings',
    'Artwork',
    'Pages',
    'Cover',
    'Print proof',
    'Publishing',
    'Produce',
    'Audit',
  ]);
  await expect(page.getByRole('main')).not.toHaveText(WORD_SEARCH_TERMS);
  await page.getByRole('link', { name: 'Open the artwork library' }).click();
  await expect(page.getByRole('heading', { name: 'Artwork library' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'No artwork yet' })).toBeVisible();

  const input = page.getByLabel('Import artwork (PNG or JPEG, several at once)');
  await input.setInputFiles([files.full, files.small, files.svg]);
  const alert = page.getByRole('alert');
  await expect(alert).toContainText('vector.svg');
  await expect(alert).toContainText('SVG artwork is not supported');
  const list = page.getByRole('list', { name: 'Artwork' });
  await expect(list.locator('.artwork-row')).toHaveCount(2);
  const fox = list.locator('.artwork-row', { hasText: 'Fox in the Ferns' });
  await expect(fox.getByText('300 DPI at full size')).toBeVisible();
  await expect(fox.getByText('Ready')).toBeVisible();
  await expect(fox.getByRole('img', { name: 'Artwork: Fox in the Ferns' })).toBeVisible();
  const owl = list.locator('.artwork-row', { hasText: 'Small owl' });
  await expect(owl.getByText('Blocking')).toBeVisible();
  await expect(page.getByText('1 with blocking problems')).toBeVisible();

  // Re-importing the same bytes adds nothing; a JPEG of the same drawing is a look-alike.
  await input.setInputFiles([files.full, files.copy]);
  await expect(page.getByText('1 added, 1 already in the library.')).toBeVisible();
  await expect(list.locator('.artwork-row')).toHaveCount(3);
  await expect(page.getByText(/look alike \(a heuristic/)).toContainText('fox-again');

  await page.reload();
  await expect(list.locator('.artwork-row')).toHaveCount(3);
  await expect(page.getByRole('main')).not.toHaveText(WORD_SEARCH_TERMS);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await owl.getByRole('button', { name: 'Remove…' }).click();
  const remove = owl.getByRole('button', { name: 'Remove from book' });
  await expect(remove).toBeDisabled();
  await owl.getByRole('checkbox', { name: /Also remove its pages/ }).check();
  await remove.click();
  await expect(list.locator('.artwork-row')).toHaveCount(2);
  await expect(page.getByText(/Its original file is kept in the project/)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Files no artwork uses' })).toBeVisible();

  for (const width of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await noOverflow(page);
  }
  await page.setViewportSize({ width: 390, height: 900 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test('line-art preparation: preview, findings, difference, save, reload, reset', async ({
  page,
}) => {
  await page.goto('/books/coloring-prepare/artwork');
  const row = page.locator('.artwork-row', { hasText: 'Fine detail' });
  await row.getByRole('button', { name: 'Prepare line art…' }).click();
  const panel = row.getByRole('region', { name: /Prepare .Fine detail. for printing/ });
  await expect(panel.getByText('Preview shows these settings')).toBeVisible({ timeout: 20000 });
  await expect(panel.getByText('No findings')).toBeVisible();
  await expect(panel.getByRole('img', { name: 'Original: Fine detail' })).toBeVisible();
  await expect(panel.getByRole('img', { name: 'Prepared: Fine detail' })).toBeVisible();

  // Thinning destroys the 1 and 2 px lines: Python blocks it and the preview follows.
  await panel.getByRole('combobox', { name: 'Line weight' }).selectOption('-1');
  await expect(panel.getByText(/Most fine lines .* are gone/)).toBeVisible({ timeout: 20000 });
  await expect(panel.getByText('Blocking').first()).toBeVisible();
  await expect(panel.getByText('Unsaved settings.')).toBeVisible();
  await panel.getByText('Difference', { exact: true }).click();
  await expect(panel.getByRole('img', { name: 'Difference: Fine detail' })).toBeVisible();
  await expect(panel.getByText(/red: ink removed/)).toBeVisible();

  // A real range input, moved by keyboard, re-previews; thickening keeps fine lines.
  await panel.getByRole('combobox', { name: 'Line weight' }).selectOption('1');
  const contrast = panel.getByRole('slider', { name: 'Contrast' });
  await contrast.focus();
  await page.keyboard.press('ArrowRight');
  await expect(contrast).toHaveValue('1.05');
  await expect(panel.getByText('Preview shows these settings')).toBeVisible({ timeout: 20000 });
  await expect(panel.getByText(/Most fine lines/)).toHaveCount(0);
  await panel.getByRole('button', { name: 'Save settings' }).click();
  await expect(panel.getByText(/Settings saved. The original file is unchanged/)).toBeVisible();

  await page.reload();
  await row.getByRole('button', { name: 'Prepare line art…' }).click();
  await expect(panel.getByRole('combobox', { name: 'Line weight' })).toHaveValue('1');
  await expect(panel.getByText('Saved settings.')).toBeVisible({ timeout: 20000 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await panel.getByRole('button', { name: 'Reset to defaults' }).click();
  await expect(panel.getByRole('combobox', { name: 'Line weight' })).toHaveValue('0');
  await panel.getByRole('button', { name: 'Save settings' }).click();
  await expect(panel.getByText(/Settings saved/)).toBeVisible();
  await page.reload();
  await row.getByRole('button', { name: 'Prepare line art…' }).click();
  await expect(panel.getByRole('button', { name: 'Reset to defaults' })).toBeDisabled();

  for (const width of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await noOverflow(page);
  }
  await expect(panel.getByText('Preview shows these settings')).toBeVisible({ timeout: 20000 });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test('coloring print proof: build, every page, blank backs, findings, export', async ({ page }) => {
  test.setTimeout(180000); // A real build: preparation, layout, render and preflight.
  await page.goto('/books/coloring-print/print');
  await expect(page.getByText('No interior has been built.')).toBeVisible();
  await page.getByRole('button', { name: 'Build interior' }).click();
  await expect(page.getByText('Interior built and preflight complete.')).toBeVisible({
    timeout: 120000,
  });
  const verdict = page.getByLabel('Preflight status');
  await expect(verdict.getByText('Valid')).toBeVisible();
  // Title, copyright, a drawing and its blank back, the divider and its back, a drawing
  // and its back: eight physical pages, drawings and the divider on right-hand pages.
  const thumbs = page.getByRole('navigation', { name: 'Pages' }).getByRole('button');
  await expect(thumbs).toHaveCount(8);
  await expect(thumbs.nth(2)).toHaveAccessibleName(/^Page 3 · Recto \(right\) · Coloring page/);
  await expect(thumbs.nth(3)).toHaveAccessibleName('Page 4 · Verso (left) · Intentional blank');
  await expect(thumbs.nth(4)).toHaveAccessibleName(/^Page 5 · Recto \(right\) · divider/);
  await thumbs.nth(3).click();
  await expect(page.getByText('Blank: back of the coloring page').first()).toBeVisible();
  await thumbs.nth(4).click();
  await expect(page.getByText('Section divider: Woodland').first()).toBeVisible();
  // Placement preview: Python's element bounds drawn over the real page raster.
  await thumbs.nth(2).click();
  await page.getByRole('checkbox', { name: /Element bounds/ }).check();
  await expect(page.locator('.overlay-element').first()).toBeVisible();
  const findings = page.getByRole('region', { name: 'Preflight findings' });
  await expect(findings.getByText(/prints at \d+ DPI/).first()).toBeVisible();
  await expect(page.getByRole('main')).not.toHaveText(WORD_SEARCH_TERMS);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: 'Download interior.pdf' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('interior.pdf');
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  for (const width of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await noOverflow(page);
  }
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
