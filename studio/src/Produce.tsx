import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, request } from './api';
import type { Project } from './types';
import { ErrorState, Loading, Status } from './ui';

// Produce: Python's `book produce` for the saved source, started and followed from
// Studio. Every step, finding, file and verdict is Python's; the browser starts the
// run, shows its progress and links to files Python has verified.

interface Item {
  source: string;
  code: string;
  message: string;
}
export interface ProduceStatus {
  key: string;
  revision: string;
  directory: string;
  cancellable: boolean;
  run: {
    state: 'running' | 'complete' | 'blocked' | 'cancelled' | 'failed';
    revision: string;
    step: string | null;
    step_label: string | null;
    steps: string[];
    seconds: number;
    cancellable: boolean;
    cancel_requested: boolean;
    error: { code: string; message: string; issues: { code: string; message: string }[] } | null;
    notes: string[];
  } | null;
  release: {
    verified: boolean;
    problem: string | null;
    engine?: string;
    stale?: boolean;
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
}

const RUN_TEXT: Record<string, [string, 'pass' | 'fail' | 'review' | 'neutral']> = {
  running: ['Running', 'neutral'],
  complete: ['Complete: nothing blocks', 'pass'],
  blocked: ['Finished with blocking findings', 'review'],
  cancelled: ['Cancelled; the previous release is unchanged', 'neutral'],
  failed: ['Failed; nothing was reported as produced', 'fail'],
};

function size(bytes: number) {
  return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

export function Produce({ project, dirty }: { project: Project; dirty: boolean }) {
  const api = `/api/projects/${encodeURIComponent(project.key)}/produce`;
  const [status, setStatus] = useState<ProduceStatus>();
  const [error, setError] = useState<Error>();
  const [actionError, setActionError] = useState<ApiError>();
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);

  const load = useCallback(
    (signal: AbortSignal) =>
      request<ProduceStatus>(api, signal)
        .then((data) => !signal.aborted && setStatus(data))
        .catch((err: Error) => !signal.aborted && setError(err)),
    [api],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, attempt]);
  const running = status?.run?.state === 'running';
  // While a run is active, follow it once a second; the run itself is Python's.
  useEffect(() => {
    if (!running) return;
    const controller = new AbortController();
    const timer = setInterval(() => void load(controller.signal), 1000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [running, load]);
  const finished = status?.run && status.run.state !== 'running';
  useEffect(() => {
    if (finished) heading.current?.focus();
  }, [finished]);

  async function act(path: string, body: object) {
    setBusy(true);
    setActionError(undefined);
    try {
      setStatus(await request<ProduceStatus>(path, new AbortController().signal, body));
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err : new ApiError((err as Error).message, 'unavailable'),
      );
    } finally {
      setBusy(false);
    }
  }

  if (error) return <ErrorState error={error} retry={() => setAttempt((n) => n + 1)} />;
  if (!status) return <Loading>Reading the last production run…</Loading>;
  const run = status.run;
  const release = status.release;
  const validation = release?.validation;
  const files = release?.files ?? [];
  const file = (name: string) => `${api}/file?name=${encodeURIComponent(name)}`;
  return (
    <div className="produce">
      <div className="section-heading">
        <div>
          <h2 ref={heading} tabIndex={-1}>
            Produce
          </h2>
          <p className="muted">
            One verified run of <code>book produce</code> for the saved source: the interior and its
            checks, the cover, readiness and the upload package when nothing blocks. Files go to{' '}
            <code>{status.directory}</code> beside the build folder. Nothing is sent to Amazon.
          </p>
        </div>
        <div className="editor-actions">
          <button
            type="button"
            className="primary"
            disabled={busy || running || dirty}
            aria-describedby="produce-note"
            onClick={() => void act(api, { revision: status.revision })}
          >
            {running ? 'Producing…' : release ? 'Produce again' : 'Produce'}
          </button>
          {running && (
            <button
              type="button"
              disabled={busy || !run?.cancellable || run.cancel_requested}
              onClick={() => void act(`${api}/cancel`, {})}
            >
              {run?.cancel_requested ? 'Stopping at the next step…' : 'Cancel'}
            </button>
          )}
        </div>
      </div>
      <p className="small muted" id="produce-note">
        {dirty
          ? 'Save your changes first: production uses the saved source.'
          : status.cancellable
            ? 'A coloring run can be cancelled between steps; the previous release stays as it was.'
            : 'A word-search run writes in place and finishes once started (it cannot stop safely midway).'}
      </p>
      {actionError && (
        <div role="alert" className="notice error">
          <p>{actionError.message}</p>
        </div>
      )}

      {run && (
        <section aria-labelledby="produce-run" className="produce-run">
          <h3 id="produce-run">
            {running ? 'Current run' : 'Last run'}{' '}
            <Status tone={RUN_TEXT[run.state][1]}>{RUN_TEXT[run.state][0]}</Status>
          </h3>
          <p role="status" aria-live="polite">
            {running
              ? `${run.step_label ?? 'Starting'}… (${run.seconds} s)`
              : `Took ${run.seconds} s.`}
          </p>
          {run.steps.length > 0 && (
            <ol className="produce-steps" aria-label="Steps run">
              {run.steps.map((step, i) => (
                <li key={`${step}-${i}`} aria-current={running && i === run.steps.length - 1}>
                  {step.replaceAll('_', ' ')}
                </li>
              ))}
            </ol>
          )}
          {run.error && run.state !== 'cancelled' && (
            <div role="alert" className="notice error">
              <p>{run.error.message}</p>
              {run.error.issues.length > 0 && (
                <ul>
                  {run.error.issues.map((issue, i) => (
                    <li key={i}>
                      <code>{issue.code}</code>: {issue.message}
                    </li>
                  ))}
                </ul>
              )}
              <p className="small">Nothing was replaced; fix the cause and produce again.</p>
            </div>
          )}
          {run.notes.length > 0 && (
            <ul className="small muted" aria-label="Recovered from an earlier run">
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
              )}
            </p>
            {validation && (
              <div className="produce-findings">
                {(
                  [
                    ['blocking', 'Blocking', 'fail'],
                    ['warnings', 'Warnings', 'review'],
                    ['manual_review', 'Needs a person', 'neutral'],
                  ] as const
                ).map(([key, label, tone]) => (
                  <details key={key} open={key === 'blocking' && validation[key].length > 0}>
                    <summary>
                      <Status tone={tone}>
                        {label}: {validation[key].length}
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
    </div>
  );
}
