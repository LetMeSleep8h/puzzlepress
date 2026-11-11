import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// The SYNTHETIC 60-puzzle production book: 95 pages, so KDP will count 96.
test('the audit lists prioritized recommendations and links pages into Print proof', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/books/production-book');
  await page
    .getByRole('navigation', { name: 'Project' })
    .getByRole('link', { name: 'Audit' })
    .click();
  await expect(page).toHaveURL(/\/books\/production-book\/audit$/);
  await expect(page.getByRole('heading', { name: 'Book audit' })).toBeVisible();
  const list = page.getByRole('list', { name: /highest priority first/ });
  await expect(list).toBeVisible({ timeout: 90_000 });
  const odd = list.getByRole('listitem').filter({ hasText: 'KDP will count 96' });
  await expect(odd).toBeVisible();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByText('PuzzlePress has no access to Amazon data')).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await odd.getByRole('link', { name: '95', exact: true }).click();
  await expect(page).toHaveURL(/\/books\/production-book\/print\?page=95$/);
  await page.goBack();
  await page.setViewportSize({ width: 375, height: 800 });
  await expect(page.getByRole('heading', { name: 'Book audit' })).toBeVisible();
  await expect(page.getByRole('list', { name: /highest priority first/ })).toBeVisible({
    timeout: 90_000,
  });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  expect(errors).toEqual([]);
});
