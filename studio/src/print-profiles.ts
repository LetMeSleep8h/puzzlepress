// How Studio names a print profile: Python's trim (PDF points) and paper, as text.

const inches = (points: number) => String(Number((points / 72).toFixed(2)));

export function trimLabel(trim: { width: number; height: number }): string {
  return `${inches(trim.width)} × ${inches(trim.height)} in`;
}

export function profileLabel(profile: {
  paper: string;
  trim: { width: number; height: number };
  bleed?: boolean;
}): string {
  return `${trimLabel(profile.trim)}, ${profile.paper} paper${profile.bleed ? ', full bleed' : ''}`;
}

/** Whether a book of this kind may choose the profile (full bleed: coloring only). */
export function offeredFor(profile: { bleed?: boolean }, coloring: boolean): boolean {
  return !profile.bleed || coloring;
}
