import { expect, test } from 'vitest';
import { offeredFor, profileLabel } from './print-profiles';

const letter = { paper: 'white', trim: { width: 612, height: 792 } };

test('full-bleed profiles say so and are offered to coloring books only', () => {
  expect(profileLabel(letter)).toBe('8.5 × 11 in, white paper');
  expect(profileLabel({ ...letter, bleed: true })).toBe('8.5 × 11 in, white paper, full bleed');
  expect(offeredFor({ bleed: true }, true)).toBe(true);
  expect(offeredFor({ bleed: true }, false)).toBe(false);
  expect(offeredFor({ bleed: false }, false)).toBe(true);
  expect(offeredFor({}, false)).toBe(true);
});
