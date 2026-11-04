import type { Project } from './types';
import { Details, Empty, Status } from './ui';

export function Overview({ project }: { project: Project }) {
  const source = project.source!;
  const content = source.word_search;
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>The source at a glance</h2>
          <p className="muted">Authored settings for this book.</p>
        </div>
        <Status tone="pass">Validation passed</Status>
      </div>
      <div className="overview-columns">
        <section>
          <h3>Book details</h3>
          <dl className="facts">
            <div>
              <dt>Book ID</dt>
              <dd>{source.book.id}</dd>
            </div>
            <div>
              <dt>Language</dt>
              <dd>{source.book.language}</dd>
            </div>
            {source.book.author && (
              <div>
                <dt>Author</dt>
                <dd>{source.book.author}</dd>
              </div>
            )}
            {source.book.imprint && (
              <div>
                <dt>Imprint</dt>
                <dd>{source.book.imprint}</dd>
              </div>
            )}
            <div>
              <dt>Project seed</dt>
              <dd>
                <code>{source.build.seed}</code>
              </dd>
            </div>
            <div>
              <dt>Book type</dt>
              <dd>{project.engine?.label ?? 'Unknown'}</dd>
            </div>
            <div>
              <dt>Schema / engine</dt>
              <dd>
                {source.schema_version} / {project.engine_version}
              </dd>
            </div>
          </dl>
          {source.book.description && <p>{source.book.description}</p>}
        </section>
        <section className="review-start">
          <h3>Read the puzzle, then the solution.</h3>
          <p>
            Generate the authored definitions to inspect letter grids, verified placements, and
            quality findings.
          </p>
          {content ? (
            <a className="button primary" href={`/books/${project.key}/puzzles`}>
              Generate & review puzzles
            </a>
          ) : (
            <p>No word-search definitions in this source fixture.</p>
          )}
          <p className="small muted">Generation uses the book’s explicit seed and profiles.</p>
        </section>
      </div>
      {content ? (
        <>
          <section>
            <div className="section-heading">
              <h2>Puzzle definitions</h2>
              <span>{content.puzzles.length} in source order</span>
            </div>
            <div className="definition-list">
              {content.puzzles.map((p, index) => (
                <a
                  className="definition-row"
                  href={`/books/${project.key}/puzzles/${p.id}`}
                  key={p.id}
                >
                  <span className="ordinal">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>{p.title}</h3>
                    <p>
                      {p.theme} · {p.target_ids.length} targets
                    </p>
                  </div>
                  <span>{p.difficulty}</span>
                  <span aria-hidden="true">↗</span>
                </a>
              ))}
            </div>
          </section>
          <section>
            <h2>Difficulty profiles</h2>
            <p className="muted">
              Named generation settings. These labels are not measured difficulty scores.
            </p>
            <div className="profile-list">
              {content.profiles.map((p) => (
                <div key={p.id}>
                  <h3>{p.id}</h3>
                  <p>
                    <strong>
                      {p.width} × {p.height}
                    </strong>{' '}
                    grid · {p.directions.length} directions
                  </p>
                  <p className="small">{p.directions.join(', ')}</p>
                  <p className="small muted">
                    Up to {p.max_attempts.toLocaleString()} attempts · {p.max_restarts} restarts
                  </p>
                </div>
              ))}
            </div>
          </section>
          <section>
            <h2>Word banks</h2>
            {content.banks.map((bank) => (
              <Details key={bank.id} title={`${bank.id} · ${bank.entries.length} entries`}>
                <ul className="bank-words">
                  {bank.entries.map((entry) => (
                    <li key={entry.id}>
                      {entry.display} <code>{entry.id}</code>
                    </li>
                  ))}
                </ul>
              </Details>
            ))}
          </section>
          <section>
            <h2>Quality configuration</h2>
            <dl className="inline-facts">
              <div>
                <dt>Word reuse limit</dt>
                <dd>{content.quality.max_word_reuse} puzzles</dd>
              </div>
              <div>
                <dt>Target similarity threshold</dt>
                <dd>{content.quality.target_similarity_threshold}</dd>
              </div>
              <div>
                <dt>Grid agreement threshold</dt>
                <dd>{content.quality.grid_similarity_threshold}</dd>
              </div>
            </dl>
            <p>
              {content.quality.prohibited_words.length
                ? `Prohibited-word screening: ${content.quality.prohibited_words.join(', ')}`
                : 'Prohibited-word screening is disabled. No policy words are configured.'}
            </p>
          </section>
        </>
      ) : (
        <Empty title="A source fixture, ready to inspect">
          This project has {source.content.items.length} authored items:{' '}
          {source.content.items.join(', ')}. They are not implicitly treated as puzzle targets.
        </Empty>
      )}
      <Details title="Source identity & developer details">
        <p>Build identity includes engine version and all output-affecting authored inputs.</p>
        <code className="identity">{project.identity}</code>
        <pre>{JSON.stringify(source, null, 2)}</pre>
      </Details>
    </>
  );
}
