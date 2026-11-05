import { useEffect, useState } from 'react';
import { request } from './api';
import { DraftToolbar, type Draft } from './draft';
import { Field, FieldErrors, matchIssues, type Source } from './editor-fields';
import { offeredFor, profileLabel } from './print-profiles';
import type { ProjectTypes } from './types';

// Book settings: what the book is (project details), how the author files it
// (catalog) and how it prints (trim and paper). Content lives in Pages or Puzzles and
// KDP metadata in Publishing; this page links there instead of repeating them. Python
// validates every value when the draft is checked or saved.

type Book = Source['book'];

export function Settings({ d }: { d: Draft }) {
  const source = d.draft;
  const issues = d.issues;
  const coloring = Boolean(source.coloring);
  const base = `/books/${encodeURIComponent(d.key)}`;
  const [profiles, setProfiles] = useState<ProjectTypes['profiles']>();
  useEffect(() => {
    const controller = new AbortController();
    request<ProjectTypes>('/api/project-types', controller.signal)
      .then((data) => setProfiles(data.profiles))
      .catch(() => !controller.signal.aborted && setProfiles([]));
    return () => controller.abort();
  }, []);

  const book = (patch: Partial<Book>) =>
    d.change({ ...source, book: { ...source.book, ...patch } });
  const optional = (key: 'subtitle' | 'author' | 'imprint' | 'description') => (value: string) =>
    book({ [key]: value.trim() === '' ? null : value });
  const catalog = (key: 'subject' | 'collection', value: string) => {
    const next = { ...(source.catalog ?? {}) };
    if (value.trim()) next[key] = value;
    else delete next[key];
    const rest = { ...source };
    delete rest.catalog;
    d.change(Object.keys(next).length ? { ...rest, catalog: next } : rest);
  };
  const paper = (profile: string) => {
    const rest = { ...source };
    delete rest.print;
    d.change(profile ? { ...rest, print: { profile } } : rest);
  };
  const chosen = source.print?.profile ?? '';
  const saved = d.saved.source?.print?.profile ?? '';

  return (
    <div className="editor settings">
      <DraftToolbar d={d} title="Settings" jump={{ href: `${base}/print`, label: 'Print proof' }} />
      <div className="settings-grid">
        <section aria-labelledby="settings-project" className="book-fields">
          <h3 id="settings-project">Project details</h3>
          <p className="small muted">
            The book itself: printed on the title page and cover and sent to KDP from Publishing.
            Changing them makes the built interior and cover out of date.
          </p>
          <div className="field-pair">
            <Field
              label="Book title"
              path="book.title"
              value={source.book.title}
              issues={issues}
              onChange={(title) => book({ title })}
            />
            <Field
              label="Subtitle (optional)"
              path="book.subtitle"
              value={source.book.subtitle ?? ''}
              issues={issues}
              onChange={optional('subtitle')}
            />
          </div>
          <div className="field-pair">
            <Field
              label="Author or pen name (optional)"
              path="book.author"
              value={source.book.author ?? ''}
              issues={issues}
              onChange={optional('author')}
            />
            <Field
              label="Imprint or publisher (optional)"
              path="book.imprint"
              value={source.book.imprint ?? ''}
              issues={issues}
              onChange={optional('imprint')}
            />
          </div>
          <Field
            label="Language"
            path="book.language"
            value={source.book.language}
            issues={issues}
            hint="A language tag such as en or fr-CA. Publishing checks it against KDP's paperback languages."
            onChange={(language) => book({ language })}
          />
          <Field
            label="Book description (optional)"
            path="book.description"
            value={source.book.description ?? ''}
            issues={issues}
            multiline
            hint="Your own note about the book, shown in Studio. The KDP description is separate, in Publishing."
            onChange={optional('description')}
          />
          <p className="small muted">
            Folder <code>{d.key}</code> · book ID <code>{source.book.id}</code> (fixed once created)
          </p>
        </section>

        <section aria-labelledby="settings-catalog">
          <h3 id="settings-catalog">Catalog</h3>
          <p className="small muted">
            How you file this book in your library. Nothing is printed or sent to KDP; a collection
            is not a KDP series (that is in Publishing).
          </p>
          <FieldErrors id="catalog" issues={matchIssues(issues, 'catalog')} />
          <div className="field-pair">
            <Field
              label="Subject (optional)"
              path="catalog.subject"
              value={source.catalog?.subject ?? ''}
              issues={issues}
              onChange={(value) => catalog('subject', value)}
            />
            <Field
              label="Collection (optional)"
              path="catalog.collection"
              value={source.catalog?.collection ?? ''}
              issues={issues}
              onChange={(value) => catalog('collection', value)}
            />
          </div>
        </section>

        <section aria-labelledby="settings-print">
          <h3 id="settings-print">Print settings</h3>
          <fieldset className="choice-group" aria-describedby="paper-note">
            <legend>Trim and paper</legend>
            <label>
              <input type="radio" name="paper" checked={chosen === ''} onChange={() => paper('')} />
              <span>Not chosen here: Print proof builds with the trim and paper chosen there</span>
            </label>
            {(profiles ?? [])
              .filter((p) => offeredFor(p, coloring))
              .map((p) => (
                <label key={p.id}>
                  <input
                    type="radio"
                    name="paper"
                    checked={chosen === p.id}
                    onChange={() => paper(p.id)}
                  />
                  <span>{profileLabel(p)}</span>
                </label>
              ))}
            {profiles === undefined && <p className="small muted">Reading print profiles…</p>}
          </fieldset>
          <FieldErrors id="print.profile" issues={matchIssues(issues, 'print')} />
          <p className="small muted" id="paper-note">
            Trim is the page size; paper sets the spine width. Every choice is black ink, from KDP's
            standard paperback sizes, with no bleed unless it says full bleed.
            {coloring &&
              ' Full bleed (coloring books) makes every page 0.125 in wider and 0.25 in taller; drawings may then fill the page in Pages.'}{' '}
            Saving a different choice makes the built interior and the cover out of date; Print
            proof and Cover then rebuild with it. A smaller page can make a word-search grid too
            small to print; the build then says so.
            {chosen !== saved && ' This change is not saved yet.'}
          </p>
        </section>

        <section aria-labelledby="settings-elsewhere">
          <h3 id="settings-elsewhere">Content and publishing</h3>
          <ul className="link-list">
            {coloring ? (
              <>
                <li>
                  <a href={`${base}/artwork`}>Artwork</a>: import drawings and prepare line art.
                </li>
                <li>
                  <a href={`${base}/pages`}>Pages</a>: page order, dividers, front and back matter,
                  borders, placement and page numbers.
                </li>
              </>
            ) : (
              <>
                <li>
                  <a href={`${base}/edit`}>Puzzles</a>: word banks, grids and puzzle definitions.
                </li>
                <li>
                  <a href={`${base}/book`}>Book</a>: matter, order and page numbers.
                </li>
              </>
            )}
            <li>
              <a href={`${base}/publishing`}>Publishing</a>: KDP description, keywords, categories
              and declarations.
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
