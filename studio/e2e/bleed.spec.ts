import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

// Full bleed (Interval 9) on a SYNTHETIC coloring book (e2e/server.py, profile
// paperback-8.5x11-bleed): fill a page, see Python's crop, save, build, and see the
// trim and bleed on the built PDF's own raster.
test('fill a page to the bleed, see the crop, build and inspect trim and bleed', async ({
  page,
}) => {
  test.setTimeout(240000);
  await page.goto('/books/coloring-bleed/pages');
  await expect(page.getByText('Plan verified')).toBeVisible({ timeout: 60000 });
  await page
    .getByRole('button', { name: /^Design page \d+$/ })
    .first()
    .click();
  const fill = page.getByRole('radio', { name: /Fill the bleed area/ });
  await expect(fill).toBeEnabled();
  await fill.check();
  await expect(
    page.getByText(/Of the drawing's line work, [\d.]+% is cut off the page/),
  ).toBeVisible({ timeout: 60000 });
  await expect(page.getByRole('list', { name: 'What the outlines show' })).toContainText(
    'Bleed: printed, then cut away',
  );
  await expect(page.getByRole('slider', { name: 'Zoom' })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  const saved = page.waitForResponse((r) => r.url().endsWith('/draft/save'));
  await page.getByRole('button', { name: 'Save changes' }).click();
  expect((await saved).status()).toBe(200);

  await page.goto('/books/coloring-bleed/print');
  await page.getByRole('button', { name: /Build interior/ }).click();
  await expect(page.getByTestId('overlay-1')).toBeVisible({ timeout: 120000 });
  await page.getByRole('checkbox', { name: /Trim line/ }).check();
  await page.getByRole('checkbox', { name: /Bleed/ }).check();
  await expect(page.locator('.overlay-trim').first()).toBeAttached();
  await expect(page.locator('.overlay-bleed').first()).toBeAttached();
  // The raster is the whole bleed page: 8.625 x 11.25 in.
  const ratio = await page
    .locator('.sheet-paper img')
    .first()
    .evaluate(
      (img) => (img as HTMLImageElement).naturalWidth / (img as HTMLImageElement).naturalHeight,
    );
  expect(ratio).toBeCloseTo(8.625 / 11.25, 2);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.goto('/books/coloring-bleed/settings');
  await expect(
    page.getByRole('radio', { name: /8\.5 × 11 in, white paper, full bleed/ }),
  ).toBeChecked();
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBeTruthy();
  }
});
