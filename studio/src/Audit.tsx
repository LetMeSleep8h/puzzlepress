import { useEffect, useMemo, useState } from 'react';
import { request } from './api';
import type { AuditRecommendation, AuditResponse, Project } from './types';
import { ErrorState, Loading, Status } from './ui';

// The book audit: Python's prioritized, read-only recommendations for the saved
// source, with links to the Studio page that changes each one and to the printed
// pages concerned. Nothing here computes a finding; the page only filters and links.

const PRIORITY: Record<AuditRecommendation['priority'], ['fail' | 'review' | 'neutral', string]> = {
  high: ['fail', 'High'],
  medium: ['review', 'Medium'],
  low: ['neutral', 'Low'],
};
const BASIS: Record<AuditRecommendation['basis'], string> = {
  kdp_help: 'KDP help page',
  measured: 'Measured',
  judgment: 'Your judgment',
};
const CATEGORY: Record<AuditRecommendation['category'], string> = {
  listing: 'Listing',
  print: 'Print',
  content: 'Puzzles',
  series: 'Series',
  evidence: 'Evidence',
};
// Python's Studio areas, mapped to this project's pages (coloring books edit their
// pages in Pages; word-search puzzles in Puzzles).
function areaPath(area: string, coloring: boolean): string | null {
  const paths: Record<string, string> = {
    plan: 'planning',
    planning: 'planning',
    puzzles: coloring ? 'pages' : 'edit',
    edit: coloring ? 'pages' : 'edit',
    quality: coloring ? 'print' : 'quality',
    book: coloring ? 'pages' : 'book',
    settings: 'settings',
    print: 'print',
    cover: 'cover',
    publishing: 'publishing',
  };
  return paths[area] ?? null;
}

export function auditCounts(items: AuditRecommendation[]) {
  return {
    high: items.filter((r) => r.priority === 'high').length,
    medium: items.filter((r) => r.priority === 'medium').length,
    low: items.filter((r) => r.priority === 'low').length,
  };
}

export function Audit({ project }: { project: Project }) {
  const [data, setData] = useState<AuditResponse>();
  const [error, setError] = useState<Error>();
  const [attempt, setAttempt] = useState(0);
  const [category, setCategory] = useState<string>('all');
  const key = project.key;
  useEffect(() => {
    const controller = new AbortController();
    setError(undefined);
    request<AuditResponse>(`/api/projects/${encodeURIComponent(key)}/audit`, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setData(next);
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => controller.abort();
  }, [key, attempt, project.revision]);
  const download = useMemo(
    () =>
      data && typeof URL.createObjectURL === 'function'
        ? URL.createObjectURL(new Blob([data.markdown], { type: 'text/markdown' }))
        : undefined,
    [data],
  );
  useEffect(() => () => void (download && URL.revokeObjectURL(download)), [download]);
  if (error) return <ErrorState error={error} retry={() => setAttempt((n) => n + 1)} />;
  if (!data)
    return <Loading>Auditing the saved book: listing, print, puzzles and evidence…</Loading>;
  const audit = data.audit;
  const base = `/books/${encodeURIComponent(key)}`;
  const coloring = audit.engine === 'coloring';
  const shown = audit.recommendations.filter((r) => category === 'all' || r.category === category);
  const counts = auditCounts(audit.recommendations);
  const categories = Array.from(new Set(audit.recommendations.map((r) => r.category)));
  return (
    <section className="audit" aria-labelledby="audit-heading">
      <div className="section-heading">
        <h2 id="audit-heading">Book audit</h2>
        <div className="audit-actions">
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            Run again
          </button>
          {download && (
            <a className="button" href={download} download={`${key}-audit.md`}>
              Download report
            </a>
          )}
        </div>
      </div>
      <p className="small">{audit.statement}</p>
      <p className="audit-summary" aria-live="polite">
        <Status tone={counts.high ? 'fail' : 'pass'}>{counts.high} high</Status>{' '}
        <Status tone={counts.medium ? 'review' : 'pass'}>{counts.medium} medium</Status>{' '}
        <Status>{counts.low} low</Status>
        <span className="small muted">
          {' '}
          · {audit.page_count} pages · saved revision only
          {data.compared.length > 0 && ` · compared with ${data.compared.join(', ')}`}
        </span>
      </p>
      {categories.length > 1 && (
        <div className="segmented audit-filter" role="group" aria-label="Filter recommendations">
          {['all', ...categories].map((c) => (
            <button
              type="button"
              key={c}
              aria-pressed={category === c}
              onClick={() => setCategory(c)}
            >
              {c === 'all' ? 'All' : CATEGORY[c as AuditRecommendation['category']]}
            </button>
          ))}
        </div>
      )}
      {shown.length === 0 ? (
        <p>
          <Status tone="pass">Nothing to recommend</Status> in this view.
        </p>
      ) : (
        <ol className="audit-list" aria-label="Recommendations, highest priority first">
          {shown.map((r, index) => {
            const path = areaPath(r.area, coloring);
            return (
              <li key={`${r.code}-${r.field ?? ''}-${index}`} className={`audit-${r.priority}`}>
                <div className="guide-head">
                  <Status tone={PRIORITY[r.priority][0]}>{PRIORITY[r.priority][1]}</Status>
                  <strong>{r.title}</strong>
                  <span className="basis-label small">
                    {CATEGORY[r.category]} · {BASIS[r.basis]}
                  </span>
                </div>
                <p className="small">{r.evidence}</p>
                <p className="small">
                  <strong>Next:</strong> {r.action}{' '}
                  {path && <a href={`${base}/${path}`}>Open {path}</a>}
                  {r.source && (
                    <>
                      {' · '}
                      <a href={r.source} target="_blank" rel="noreferrer">
                        KDP source
                      </a>
                    </>
                  )}
                </p>
                {r.field && (
                  <p className="small muted">
                    Field <code>{r.field}</code>
                  </p>
                )}
                {r.pages.length > 0 && (
                  <p className="small audit-pages">
                    Pages:{' '}
                    {r.pages.slice(0, 16).map((page) => (
                      <a key={page} href={`${base}/print?page=${page}`}>
                        {page}
                      </a>
                    ))}
                    {r.pages.length > 16 && (
                      <span className="muted"> and {r.pages.length - 16} more</span>
                    )}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {audit.levels.length > 0 && (
        <>
          <h3>Difficulty by level</h3>
          <p className="small muted">
            Facts of the generated grids. Backward words read right to left or bottom to top.
          </p>
          <div className="table-scroll">
            <table className="audit-levels">
              <thead>
                <tr>
                  <th scope="col">Level</th>
                  <th scope="col">Puzzles</th>
                  <th scope="col">Grids</th>
                  <th scope="col">Words</th>
                  <th scope="col">Directions</th>
                  <th scope="col">Diagonal</th>
                  <th scope="col">Backward</th>
                  <th scope="col">Longest</th>
                </tr>
              </thead>
              <tbody>
                {audit.levels.map((level) => (
                  <tr key={level.profile}>
                    <th scope="row">{level.profile}</th>
                    <td>{level.puzzles}</td>
                    <td>{level.grids.join(', ')}</td>
                    <td>
                      {level.words.min}–{level.words.max}
                    </td>
                    <td>{level.allowed_directions}</td>
                    <td>
                      {level.placed_diagonal.min}–{level.placed_diagonal.max}
                    </td>
                    <td>
                      {level.placed_backward.min}–{level.placed_backward.max}
                    </td>
                    <td>{level.longest_word}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <h3>Manual checks</h3>
      <p className="small muted">Only a printed proof or your judgment can settle these.</p>
      <ul className="audit-manual">
        {audit.manual_checks.map((check) => (
          <li key={check.code}>
            <Status
              tone={
                check.status === 'recorded'
                  ? 'pass'
                  : check.status === 'manual'
                    ? 'neutral'
                    : 'review'
              }
            >
              {check.status === 'recorded'
                ? 'Recorded'
                : check.status === 'stale'
                  ? 'Recorded for earlier files'
                  : check.status === 'manual'
                    ? 'Check by hand'
                    : 'Not recorded'}
            </Status>{' '}
            <strong>{check.title}</strong> <span className="small muted">{check.why}</span>
          </li>
        ))}
      </ul>
      <h3>Not assessed</h3>
      <ul className="small">
        {audit.not_assessed.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {!data.collection && (
        <p className="small muted">
          Add this book to a collection in Settings to compare it with the other books of that
          collection in the library.
        </p>
      )}
    </section>
  );
}
