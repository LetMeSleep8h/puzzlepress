import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// Produce from Studio on a SYNTHETIC coloring book (e2e/server.py): Python's job in
// its own worker process, followed step by step, reported only once every file is
// verified.
test('produce a coloring book from Studio and download its verified files', async ({ page }) => {
  test.setTimeout(300000);
  await page.goto('/books/coloring-produce/produce');
  await expect(page.getByText('Nothing has been produced yet.')).toBeVisible();
  await expect(page.getByText(/can be cancelled while it runs/)).toBeVisible();
  await page.getByRole('button', { name: 'Produce', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Producing…' })).toBeDisabled();
  await expect(page.getByText('Every file verified')).toBeVisible({ timeout: 240000 });
  await expect(page.getByRole('heading', { name: /Last job/ })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Steps run' })).toContainText('release swap');
  // A download link: the browser saves the file; Python served the verified bytes.
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download production.json' }).click();
  expect((await download).suggestedFilename()).toBe('production.json');
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

// A job outlives the page: reloading shows it still running; cancelling asks first,
// works from the keyboard, and the job ends cancelled with nothing replaced.
test('a running job survives a reload and is cancelled after confirmation', async ({ page }) => {
  test.setTimeout(300000);
  await page.goto('/books/coloring-produce-slow/produce');
  await page.getByRole('button', { name: 'Produce', exact: true }).click();
  await expect(page.getByRole('heading', { name: /Current job/ })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Steps run' })).toContainText('duplicates', {
    timeout: 120000,
  });
  await page.reload();
  await expect(page.getByRole('heading', { name: /Current job/ })).toBeVisible();
  await expect(page.getByText('Running', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Producing…' })).toBeDisabled();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  const cancel = page.getByRole('button', { name: 'Cancel production' });
  await cancel.focus();
  await page.keyboard.press('Enter');
  const confirm = page.getByRole('group', { name: /Stop this production job/ });
  await expect(confirm.getByRole('button', { name: 'Stop production' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(confirm.getByRole('button', { name: 'Keep running' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(confirm).toBeHidden();
  await cancel.click();
  await confirm.getByRole('button', { name: 'Stop production' }).click();
  await expect(page.getByRole('heading', { name: /Last job/ })).toBeVisible({ timeout: 60000 });
  await expect(page.getByText('Cancelled', { exact: true })).toBeVisible();
  await expect(page.getByText(/no previous release; nothing was written/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry production' })).toBeEnabled();
  for (const width of [1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBeTruthy();
  }
});
