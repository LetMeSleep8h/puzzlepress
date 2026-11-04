import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// A SYNTHETIC composed coloring book (e2e/server.py): three drawings, thin border.
const WORD_SEARCH_TERMS = /\b(puzzles?|solutions?|word search(es)?|word banks?|grids?)\b/i;

function rows(page: Page) {
  return page
    .getByRole('list', { name: 'Drawings and dividers in printing order' })
    .getByRole('listitem');
}

async function names(page: Page) {
  return rows(page).locator('strong').allTextContents();
}

test('coloring pages: reorder by keyboard and drag, divider, save, reload, accessibility', async ({
  page,
}) => {
  test.setTimeout(180000); // Python prepares and plans real drawings.
  await page.goto('/books/coloring-pages/pages');
  await expect(page.getByText('Plan verified')).toBeVisible({ timeout: 60000 });
  const before = await names(page);
  expect(before).toHaveLength(3);
  // Python's plan: each entry on a right-hand page, with blank backs in between.
  await expect(rows(page).first()).toContainText(/PDF page \d+ · right-hand/);
  await expect(page.getByText(/Back of the page before/).first()).toBeVisible();

  // Keyboard: focus Down on the first drawing and press Enter.
  await page.getByRole('button', { name: `Move ${before[0]} down` }).focus();
  await page.keyboard.press('Enter');
  expect(await names(page)).toEqual([before[1], before[0], before[2]]);
  // Drag the last row onto the first.
  await rows(page).nth(2).dragTo(rows(page).nth(0));
  expect(await names(page)).toEqual([before[2], before[1], before[0]]);
  // A section divider at the end, then titled.
  await page.getByRole('button', { name: 'Add section divider' }).click();
  await page.getByLabel('Divider title').fill('Woodland');
  await expect(page.getByText('Section divider: Woodland').first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('Plan verified')).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole('main')).not.toHaveText(WORD_SEARCH_TERMS);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const saved = page.waitForResponse((r) => r.url().endsWith('/draft/save'));
  await page.getByRole('button', { name: 'Save changes' }).click();
  expect((await saved).status()).toBe(200);
  await expect(page.getByText('Saved and reloaded from source.')).toBeVisible();
  await page.reload();
  await expect(page.getByText('Plan verified')).toBeVisible({ timeout: 60000 });
  expect(await names(page)).toEqual([before[2], before[1], before[0], 'Divider: Woodland']);

  for (const width of [1440, 1024, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBeTruthy();
    // Touch targets stay usable at every width.
    const small = await page
      .locator('.page-order-actions button')
      .evaluateAll(
        (buttons) =>
          buttons.filter((b) => (b as HTMLElement).getBoundingClientRect().height < 40).length,
      );
    expect(small).toBe(0);
  }
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
