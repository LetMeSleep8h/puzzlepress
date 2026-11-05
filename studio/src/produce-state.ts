// Production job states as Python reports them, and the rules the Produce page
// follows to show them. Python owns every state; nothing here decides one.

export type JobState =
  | 'queued'
  | 'starting'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted';

export interface JobRef {
  job_id: string;
  seq: number;
}

export const ACTIVE: ReadonlySet<JobState> = new Set([
  'queued',
  'starting',
  'running',
  'cancelling',
]);

export function isActive(state: JobState | undefined): boolean {
  return state !== undefined && ACTIVE.has(state);
}

/**
 * Whether `next` may replace `current`. Responses can arrive out of order (a slow
 * poll answered after a newer one), so a view of an older job, or an earlier view of
 * the same job, never overwrites what is shown. Job IDs sort by creation time;
 * `seq` counts the job's events and only grows. A status without a job (`null`) is
 * shown only while nothing newer is.
 */
export function isNewer(current: JobRef | null | undefined, next: JobRef | null | undefined) {
  if (!current) return true;
  if (!next) return false;
  if (next.job_id !== current.job_id) return next.job_id > current.job_id;
  return next.seq >= current.seq;
}

type Tone = 'pass' | 'fail' | 'review' | 'neutral';

export function stateText(state: JobState, outcome: string | null): [string, Tone] {
  switch (state) {
    case 'queued':
      return ['Waiting for a free worker', 'neutral'];
    case 'starting':
      return ['Starting the worker', 'neutral'];
    case 'running':
      return ['Running', 'neutral'];
    case 'cancelling':
      return ['Stopping at the next safe point', 'neutral'];
    case 'completed':
      return outcome === 'ready'
        ? ['Complete: nothing blocks', 'pass']
        : ['Finished with blocking findings', 'review'];
    case 'cancelled':
      return ['Cancelled', 'neutral'];
    case 'interrupted':
      return ['Interrupted', 'fail'];
    case 'failed':
      return ['Failed', 'fail'];
  }
}

/** "12 of 40 pages drawn": only when Python counted real work units. */
export function progressText(
  progress: { stage?: unknown; done?: unknown; total?: unknown; label?: unknown } | null,
): string | null {
  if (!progress) return null;
  const { done, total, label } = progress;
  if (typeof done !== 'number' || typeof total !== 'number' || total <= 0) return null;
  const what =
    typeof label === 'string' ? label : String(progress.stage ?? 'units').replaceAll('_', ' ');
  return `${done} of ${total} ${what}`;
}

export function preservedText(preserved: string | null): string | null {
  switch (preserved) {
    case 'unchanged':
      return 'The previous release is unchanged.';
    case 'none':
      return 'There was no previous release; nothing was written.';
    case 'pending_recovery':
      return 'The previous release was moved aside when the job stopped; the next job puts it back.';
    case 'changed':
      return 'The release on disk changed since this job was requested (another run wrote it).';
    default:
      return null;
  }
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '';
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
}
