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
  await expect(nav.getByRole('link')).toHaveText(['Overview', 'Artwork']);
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
