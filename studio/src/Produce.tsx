import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, request } from './api';
import {
  duration,
  isActive,
  isNewer,
  preservedText,
  progressText,
  stateText,
  type JobState,
} from './produce-state';
import type { Project } from './types';
import { ErrorState, Loading, Status } from './ui';

// Produce: Python's `book produce` for the saved source, run as a job in its own
// worker process and followed from Studio. Every state, step, count, finding, file
// and verdict is Python's; the browser starts the job, shows its record and links
// to files Python has verified. Job records outlive Studio, so a reload shows the
// job as it is.

interface Item {
  source: string;
  code: string;
  message: string;
}
export interface ProduceJob {
  job_id: string;
  seq: number;
  state: JobState;
  outcome: 'ready' | 'blocked' | null;
  revision: string;
  engine?: string;
  created?: string;
  started: string | null;
  finished: string | null;
  step: string | null;
  step_label: string | null;
  steps: string[];
  progress: {
    stage: string;
    done: number | null;
    total: number | null;
    label?: string | null;
  } | null;
  seconds: number | null;
  cancellable: boolean;
  cancel_requested: boolean;
  queue_position: number | null;
  release_preserved: string | null;
  error: {
    code: string;
    message: string;
    stage?: string | null;
    issues?: { code: string; message: string }[];
  } | null;
  result?: Record<string, unknown> | null;
  notes: string[];
  limits?: Record<string, unknown>;
}
export interface ProduceStatus {
  key: string;
  revision: string;
  directory: string;
  cancellable: boolean;
  run: ProduceJob | null;
  release: {
    verified: boolean;
    problem: string | null;
    engine?: string;
    /** The print profile the release was built with (production.json). */
    profile?: string | null;
    stale?: boolean;
    manifest_sha256?: string | null;
    result?: Record<string, unknown>;
    files: { name: string; bytes: number; sha256: string }[];
    validation?: {
      blocking: Item[];
      warnings: Item[];
      manual_review: Item[];
      verified: string[];
    } | null;
    package?: boolean;
  } | null;
  recovery_pending?: boolean;
  history?: {
    job_id: string;
    state: JobState;
    outcome: string | null;
    created: string;
    seconds: number | null;
    error: string | null;
  }[];
  workers?: { running: number; limit: number };
}

/** The cheap poll (`GET .../produce/job`): the job record only, never release files. */
export interface ProduceJobPoll {
  key: string;
  revision: string;
  directory: string;
  run: ProduceJob | null;
  release_manifest_sha256: string | null;
  release_checked: false;
  recovery_pending: boolean;
  workers: { running: number; limit: number };
}

function size(bytes: number) {
  return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

function when(stamp: string | null | undefined) {
  if (!stamp) return '';
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? stamp : date.toLocaleString();
}

export function Produce({ project, dirty }: { project: Project; dirty: boolean }) {
  const api = `/api/projects/${encodeURIComponent(project.key)}/produce`;
  const [status, setStatus] = useState<ProduceStatus>();
  const [error, setError] = useState<Error>();
  const [actionError, setActionError] = useState<ApiError>();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  // What is on screen, for the poll to compare against (state updates run later).
  const shown = useRef<ProduceStatus | undefined>(undefined);
  // Verified-status requests the poll starts; aborted only when the page goes away.
  const verifying = useRef(new AbortController());
  useEffect(() => {
    const controller = new AbortController();
    verifying.current = controller;
    return () => controller.abort();
  }, []);
  useEffect(() => {
    shown.current = status;
  }, [status]);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);

  // Responses may arrive out of order; an older job, or an earlier view of the same
  // job, never replaces a newer one (Python numbers each job's events).
  const accept = useCallback((next: ProduceStatus) => {
    setStatus((current) => (current && !isNewer(current.run, next.run) ? current : next));
  }, []);

  const load = useCallback(
    (signal: AbortSignal) =>
      request<ProduceStatus>(api, signal)
        .then((data) => !signal.aborted && accept(data))
        .catch((err: Error) => !signal.aborted && setError(err)),
    [api, accept],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, attempt]);
  const active = isActive(status?.run?.state);
  // While a job is queued or running, follow its record once a second through the
  // cheap poll (no file is read back there). The verified status, the only source
  // of release files and downloads, is fetched again once the job ends or
  // production.json changes.
  const poll = useCallback(
    (signal: AbortSignal) =>
      request<ProduceJobPoll>(`${api}/job`, signal)
        .then((next) => {
          const current = shown.current;
          if (signal.aborted || !current || !isNewer(current.run, next.run)) return;
          const refresh =
            !isActive(next.run?.state) ||
            (next.release_manifest_sha256 ?? null) !== (current.release?.manifest_sha256 ?? null);
          accept({
            ...current,
            revision: next.revision,
            run: next.run,
            recovery_pending: next.recovery_pending,
            workers: next.workers,
          });
          // The verified status outlives this poll: polling stops as soon as the job
          // has ended, which must not cancel the request that shows its release.
          if (refresh) void load(verifying.current.signal);
        })
        .catch((err: Error) => !signal.aborted && setError(err)),
    [api, load, accept],
  );
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const timer = setInterval(() => void poll(controller.signal), 1000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [active, poll]);
  const finished = status?.run && !active;
  useEffect(() => {
    if (finished) {
      setConfirming(false);
      heading.current?.focus();
    }
  }, [finished]);
  useEffect(() => {
    if (confirming) confirmButton.current?.focus();
  }, [confirming]);

  async function act(path: string, body: object) {
    setBusy(true);
    setActionError(undefined);
    try {
      accept(await request<ProduceStatus>(path, new AbortController().signal, body));
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err : new ApiError((err as Error).message, 'unavailable'),
      );
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorState error={error} retry={() => setAttempt((n) => n + 1)} />;
  if (!status) return <Loading>Reading the last production job…</Loading>;
  const run = status.run;
  const release = status.release;
  const validation = release?.validation;
  const files = release?.files ?? [];
  const file = (name: string) => `${api}/file?name=${encodeURIComponent(name)}`;
  const failed = run && ['failed', 'interrupted', 'cancelled'].includes(run.state);
  const [label, tone] = run ? stateText(run.state, run.outcome) : ['', 'neutral' as const];
  const counted = run ? progressText(run.progress) : null;
  const preserved = run ? preservedText(run.release_preserved) : null;
  const startLabel = active
    ? 'Producing…'
    : run && failed
      ? 'Retry production'
      : release
        ? 'Produce again'
        : 'Produce';
  return (
    <div className="produce">
      <div className="section-heading">
        <div>
          <h2 ref={heading} tabIndex={-1}>
            Produce
          </h2>
          <p className="muted">
            One verified run of <code>book produce</code> for the saved source, in its own worker
            process: the interior and its checks, the cover, readiness and the upload package when
            nothing blocks. Files go to <code>{status.directory}</code> beside the build folder.
            Nothing is sent to Amazon.
          </p>
        </div>
        <div className="editor-actions">
          <button
            type="button"
            className="primary"
            disabled={busy || active || dirty}
            aria-describedby="produce-note"
            onClick={() => void act(api, { revision: status.revision })}
          >
            {startLabel}
          </button>
          {active && !confirming && (
            <button
              type="button"
              ref={cancelButton}
              disabled={busy || !run?.cancellable}
              onClick={() => setConfirming(true)}
            >
              {run?.cancel_requested ? 'Stopping at the next safe point…' : 'Cancel production'}
            </button>
          )}
        </div>
      </div>
      <p className="small muted" id="produce-note">
        {dirty
          ? 'Save your changes first: production uses the saved source.'
          : 'A job can be cancelled while it runs: it stops at the next safe point inside the current step, and the previous release stays as it was. Once the verified release is being put in place, the job finishes.'}
      </p>
      {confirming && active && (
        <div className="notice produce-confirm" role="group" aria-labelledby="produce-confirm">
          <p id="produce-confirm">
            Stop this production job? Work done so far is discarded; the previous release is kept.
          </p>
          <div className="button-row">
            <button
              type="button"
              ref={confirmButton}
              className="danger"
              disabled={busy}
              onClick={() => {
                setConfirming(false);
                void act(`${api}/cancel`, {}).then(() => cancelButton.current?.focus());
              }}
            >
              Stop production
            </button>
            <button
              type="button"
              onClick={() => {
                setConfirming(false);
                requestAnimationFrame(() => cancelButton.current?.focus());
              }}
            >
              Keep running
            </button>
          </div>
        </div>
      )}
      {actionError && (
        <div role="alert" className="notice error">
          <p>{actionError.message}</p>
        </div>
      )}
      {status.recovery_pending && (
        <div role="status" className="notice">
          <p>
            An interrupted job moved the previous release aside. The next job puts it back before it
            starts.
          </p>
        </div>
      )}

      {run && (
        <section aria-labelledby="produce-run" className="produce-run">
          <h3 id="produce-run">
            {active ? 'Current job' : 'Last job'} <Status tone={tone}>{label}</Status>
          </h3>
          <p role="status" aria-live="polite">
            {active
              ? run.state === 'queued'
                ? `Waiting for a free worker${run.queue_position ? ` (position ${run.queue_position})` : ''}.`
                : `${run.step_label ?? 'Starting'}${counted ? `: ${counted}` : ''} · ${duration(run.seconds)}`
              : `${label}. Took ${duration(run.seconds)}.`}
          </p>
          {active && counted && run.progress?.total ? (
            <progress
              className="produce-progress"
              value={run.progress.done ?? 0}
              max={run.progress.total}
              aria-label={`${run.step_label ?? 'Current step'}: ${counted}`}
            />
          ) : null}
          <dl className="produce-facts small">
            <dt>Job</dt>
            <dd>
              <code>{run.job_id}</code>
            </dd>
            {run.started && (
              <>
                <dt>Started</dt>
                <dd>{when(run.started)}</dd>
              </>
            )}
            {run.finished && (
              <>
                <dt>Ended</dt>
                <dd>{when(run.finished)}</dd>
              </>
            )}
            {typeof run.result?.peak_memory_mb === 'number' && (
              <>
                <dt>Peak memory</dt>
                <dd>{run.result.peak_memory_mb} MB</dd>
              </>
            )}
          </dl>
          {run.steps.length > 0 && (
            <ol className="produce-steps" aria-label="Steps run">
              {run.steps.map((step, i) => (
                <li key={`${step}-${i}`} aria-current={active && i === run.steps.length - 1}>
                  {step.replaceAll('_', ' ')}
                </li>
              ))}
            </ol>
          )}
          {run.error && run.state !== 'cancelled' && (
            <div role="alert" className="notice error">
              <p>
                {run.error.message} <code>{run.error.code}</code>
              </p>
              {(run.error.issues ?? []).length > 0 && (
                <ul>
                  {(run.error.issues ?? []).map((issue, i) => (
                    <li key={i}>
                      <code>{issue.code}</code>: {issue.message}
                    </li>
                  ))}
                </ul>
              )}
              {preserved && <p className="small">{preserved}</p>}
              <p className="small">Fix the cause if one is named, then retry.</p>
            </div>
          )}
          {run.state === 'cancelled' && (
            <p className="small">
              {run.error?.message} {preserved}
            </p>
          )}
          {run.notes.length > 0 && (
            <ul className="small muted" aria-label="Recovered from an earlier job">
              {run.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section aria-labelledby="produce-release" className="produce-release">
        <h3 id="produce-release">Release</h3>
        {!release ? (
          <p className="muted">Nothing has been produced yet.</p>
        ) : !release.verified ? (
          <div role="alert" className="notice error">
            <p>
              The release on disk does not match its manifest: {release.problem} Its files are not
              offered for download. Produce again.
            </p>
          </div>
        ) : (
          <>
            <p>
              <Status tone="pass">Every file verified</Status>{' '}
              {release.stale && (
                <Status tone="review">Out of date: the saved book changed since this run</Status>
              )}{' '}
              {active && <Status tone="neutral">Kept until the new job verifies</Status>}
            </p>
            {release.profile && (
              <p className="small">
                Print profile <code>{release.profile}</code>
                {release.profile.endsWith('-bleed')
                  ? ': full bleed. In KDP, choose Bleed (PDF only) for the interior.'
                  : ': no bleed.'}
              </p>
            )}
            {validation && (
              <div className="produce-findings">
                {(
                  [
                    ['blocking', 'Blocking', 'fail'],
                    ['warnings', 'Warnings', 'review'],
                    ['manual_review', 'Needs a person', 'neutral'],
                  ] as const
                ).map(([key, title, itemTone]) => (
                  <details key={key} open={key === 'blocking' && validation[key].length > 0}>
                    <summary>
                      <Status tone={itemTone}>
                        {title}: {validation[key].length}
                      </Status>
                    </summary>
                    <ul>
                      {validation[key].map((item, i) => (
                        <li key={i}>
                          <strong>{item.source.replaceAll('_', ' ')}</strong>{' '}
                          <code>{item.code}</code>: {item.message}
                        </li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
            )}
            <div className="button-row">
              <a className="button" href={file('production.json')} download>
                Download production.json
              </a>
              {release.package && (
                <a className="button primary" href={`${api}/package.zip`} download>
                  Download upload package (ZIP)
                </a>
              )}
            </div>
            <details>
              <summary>All {files.length} files</summary>
              <ul className="produce-files">
                {files.map((f) => (
                  <li key={f.name}>
                    <a href={file(f.name)} download>
                      {f.name}
                    </a>{' '}
                    <span className="small muted">
                      {size(f.bytes)} · sha256 {f.sha256.slice(0, 12)}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          </>
        )}
      </section>

      {(status.history?.length ?? 0) > 1 && (
        <details className="produce-history">
          <summary>Recent jobs</summary>
          <ul className="small">
            {status.history!.map((job) => (
              <li key={job.job_id}>
                {when(job.created)}: {stateText(job.state, job.outcome)[0]}
                {job.error ? ` (${job.error})` : ''}
                {job.seconds !== null ? `, ${duration(job.seconds)}` : ''}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
