import { useEffect, useState } from 'react';
import { request } from './api';
import type { Project } from './types';
import { Empty, ErrorState, Issues, Loading, Status } from './ui';

export function Library() {
  const [projects, setProjects] = useState<Project[]>();
  const [error, setError] = useState<Error>();
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setError(undefined);
    request<{ projects: Project[] }>('/api/projects', controller.signal)
      .then((data) => setProjects(data.projects))
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => controller.abort();
  }, [attempt]);
  const visible = projects?.filter((p) =>
    `${p.source?.book.title ?? ''} ${p.key} ${p.source?.book.id ?? ''}`
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  return (
    <>
      <header className="page-heading">
        <div>
          <h1>Your books</h1>
          <p>From the first word to a puzzle worth publishing.</p>
        </div>
        <span className="source-note">Local project library</span>
      </header>
      <div className="library-toolbar">
        <p>{projects ? `${projects.length} source projects` : 'Reading your library'}</p>
        <label className="search">
          Find a book
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title or ID"
          />
        </label>
      </div>
      {error ? (
        <ErrorState error={error} retry={() => setAttempt((x) => x + 1)} />
      ) : !projects ? (
        <Loading>Reading the local book library…</Loading>
      ) : !projects.length ? (
        <Empty title="A place for your next puzzle book">
          Add a project folder containing book.yaml under the configured books directory, then
          reload this page.
        </Empty>
      ) : !visible?.length ? (
        <Empty title="No matching books">Try another title or project ID.</Empty>
      ) : (
        <div className="book-list">
          {visible.map((project) => {
            const source = project.source;
            const content = source?.word_search;
            return (
              <article className="book-row" key={project.key}>
                <div className="book-specimen" aria-hidden="true">
                  <div className="specimen-spine" />
                  <span>PuzzlePress</span>
                  <strong>{source?.book.title ?? project.key}</strong>
                  <small>{content ? 'Word search' : 'Source fixture'}</small>
                </div>
                <div className="book-description">
                  <Status tone={project.validation.valid ? 'pass' : 'fail'}>
                    {project.validation.valid ? 'Source valid' : 'Validation failed'}
                  </Status>
                  <h2>
                    <a href={`/books/${encodeURIComponent(project.key)}`}>
                      {source?.book.title ?? project.key}
                    </a>
                  </h2>
                  {source?.book.subtitle && <p>{source.book.subtitle}</p>}
                  <p className="muted">{source?.book.id ?? project.key}</p>
                  {source ? (
                    <dl className="inline-facts">
                      <div>
                        <dt>Type</dt>
                        <dd>{project.engine?.label ?? 'Unknown'}</dd>
                      </div>
                      <div>
                        <dt>Puzzles</dt>
                        <dd>{content?.puzzles.length ?? 0} definitions</dd>
                      </div>
                      <div>
                        <dt>Language</dt>
                        <dd>{source.book.language}</dd>
                      </div>
                      <div>
                        <dt>Profiles</dt>
                        <dd>
                          {content?.profiles.map((p) => p.id).join(' · ') ?? 'Not configured'}
                        </dd>
                      </div>
                    </dl>
                  ) : (
                    <Issues issues={project.validation.issues} />
                  )}
                  {!content && source && (
                    <p className="muted">Authored content fixture. No word-search definitions.</p>
                  )}
                </div>
                <a
                  className="book-open"
                  href={`/books/${encodeURIComponent(project.key)}`}
                  aria-label={`Open ${source?.book.title ?? project.key}`}
                >
                  Open project <span aria-hidden="true">↗</span>
                </a>
              </article>
            );
          })}
        </div>
      )}
      <p className="library-footnote">
        Source projects stay on your machine. Generated analysis does not change your books.
      </p>
    </>
  );
}
