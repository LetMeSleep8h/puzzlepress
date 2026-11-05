import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// Produce from Studio on a SYNTHETIC coloring book (e2e/server.py): Python's run,
// followed step by step, reported only once every file is verified.
test('produce a coloring book from Studio and download its verified files', async ({ page }) => {
  test.setTimeout(300000);
  await page.goto('/books/coloring-produce/produce');
  await expect(page.getByText('Nothing has been produced yet.')).toBeVisible();
  await expect(page.getByText(/can be cancelled between steps/)).toBeVisible();
  await page.getByRole('button', { name: 'Produce', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Producing…' })).toBeDisabled();
  await expect(page.getByText('Every file verified')).toBeVisible({ timeout: 240000 });
  await expect(page.getByRole('heading', { name: /Last run/ })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Steps run' })).toContainText('interior');
  const manifest = page.waitForResponse((r) =>
    r.url().includes('produce/file?name=production.json'),
  );
  await page.getByRole('link', { name: 'Download production.json' }).click();
  expect((await manifest).status()).toBe(200);
  await page.getByText(/All \d+ files/).click();
  await expect(page.getByRole('link', { name: 'interior.pdf', exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBeTruthy();
  }
});
