import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, request } from './api';
import { Field } from './editor-fields';
import { profileLabel } from './print-profiles';
import type { Issue, Project, ProjectTypes } from './types';
import { ErrorState, Issues, Loading } from './ui';

// New book: the type, then the details. Python creates the folder and its starter
// book.yaml (puzzlepress.creation) and validates every value; this form only collects
// them and shows Python's answer beside each field.

const DESCRIPTIONS: Record<string, string> = {
  word_search:
    'Generated word-search grids with answers at the back. Starts with one placeholder puzzle you replace with your own.',
  coloring:
    'Your own line drawings, one per right-hand page, with blank backs. Starts empty: import artwork next. It cannot pass the production checks until it has enough drawings.',
};
// Shown so authors know what is planned; none of these can be created yet.
const FUTURE = [
  'Maze',
  'Crossword',
  'Sudoku',
  'Mixed activity book',
  'Educational workbook',
  'Photography book',
  'Illustrated book',
];

function Specimen({ kind }: { kind: string }) {
  if (kind === 'word_search')
    return (
      <svg viewBox="0 0 60 60" className="type-specimen" aria-hidden="true">
        <rect x="4" y="4" width="52" height="52" rx="3" className="sheet" />
        {'WORDSEARCHGRIDLETTER'.split('').map((letter, i) => (
          <text key={i} x={12 + (i % 5) * 9} y={17 + Math.floor(i / 5) * 10} className="glyph">
            {letter}
          </text>
        ))}
        <rect x="8" y="9" width="47" height="11" rx="5" className="found" />
      </svg>
    );
  if (kind === 'coloring')
    return (
      <svg viewBox="0 0 60 60" className="type-specimen" aria-hidden="true">
        <rect x="4" y="4" width="52" height="52" rx="3" className="sheet" />
        <circle cx="30" cy="27" r="6" className="line" />
        {[0, 72, 144, 216, 288].map((angle) => (
          <ellipse
            key={angle}
            cx="30"
            cy="16"
            rx="5"
            ry="8"
            className="line"
            transform={`rotate(${angle} 30 27)`}
          />
        ))}
        <path d="M30 33 C30 42 28 47 26 52 M30 42 C34 40 38 41 40 44" className="line" />
      </svg>
    );
  return (
    <svg viewBox="0 0 60 60" className="type-specimen future" aria-hidden="true">
      <rect x="4" y="4" width="52" height="52" rx="3" className="sheet" />
    </svg>
  );
}

function open(path: string) {
  history.pushState(null, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function CreateBook() {
  const [types, setTypes] = useState<ProjectTypes>();
  const [error, setError] = useState<Error>();
  const [attempt, setAttempt] = useState(0);
  const [kind, setKind] = useState<string>();
  const [values, setValues] = useState({
    title: '',
    subtitle: '',
    author: '',
    key: '',
    subject: '',
    collection: '',
    language: 'en',
    profile: '',
    template: '',
  });
  const [issues, setIssues] = useState<Issue[]>([]);
  const [failure, setFailure] = useState<Error>();
  const [busy, setBusy] = useState(false);
  const details = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    request<ProjectTypes>('/api/project-types', controller.signal)
      .then(setTypes)
      .catch((err: Error) => !controller.signal.aborted && setError(err));
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => {
    if (kind) details.current?.focus();
  }, [kind]);
  if (error) return <ErrorState error={error} retry={() => setAttempt((n) => n + 1)} />;
  if (!types) return <Loading>Reading the book types…</Loading>;
  const type = types.types.find((t) => t.kind === kind);
  const set = (key: keyof typeof values) => (value: string) =>
    setValues((v) => ({ ...v, [key]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!type || busy) return;
    setBusy(true);
    setIssues([]);
    setFailure(undefined);
    const optional = (value: string) => (value.trim() ? value : null);
    try {
      const created = await request<Project>('/api/projects', new AbortController().signal, {
        kind: type.kind,
        key: values.key.trim(),
        title: values.title,
        language: values.language,
        subtitle: optional(values.subtitle),
        author: optional(values.author),
        subject: optional(values.subject),
        collection: optional(values.collection),
        profile: optional(values.profile),
        template: values.template || type.default_template,
      });
      open(
        `/books/${encodeURIComponent(created.key)}${type.kind === 'coloring' ? '/artwork' : ''}`,
      );
    } catch (err) {
      setFailure(err as Error);
      setIssues(err instanceof ApiError ? err.issues : []);
    } finally {
      setBusy(false);
    }
  }

  // Python names a field by its book.yaml path; the request's own fields by name.
  const fieldIssues = issues.map((i) =>
    i.path === 'parent' || i.path === 'kind' || i.path === 'template' ? { ...i, path: 'form' } : i,
  );
  return (
    <div className="create-book">
      <header className="page-heading">
        <div>
          <h1>New book</h1>
          <p>Choose a type, then name it. Studio creates the project folder for you.</p>
        </div>
        <a href="/books">Back to your books</a>
      </header>
      <section aria-labelledby="type-heading">
        <h2 id="type-heading">1. Book type</h2>
        <div className="type-choices" role="radiogroup" aria-labelledby="type-heading">
          {types.types.map((t) => (
            <label key={t.kind} className={`type-card${kind === t.kind ? ' chosen' : ''}`}>
              <input
                type="radio"
                name="book-type"
                value={t.kind}
                checked={kind === t.kind}
                onChange={() => {
                  setKind(t.kind);
                  setValues((v) => ({ ...v, template: t.default_template }));
                }}
              />
              <Specimen kind={t.kind} />
              <strong>{t.kind === 'coloring' ? 'Coloring Book' : 'Word Search'}</strong>
              <span className="small">{DESCRIPTIONS[t.kind] ?? t.label}</span>
            </label>
          ))}
          {FUTURE.map((label) => (
            <label key={label} className="type-card unavailable" aria-disabled="true">
              <input type="radio" name="book-type" disabled />
              <Specimen kind="future" />
              <strong>{label}</strong>
              <span className="small muted">Not available yet</span>
            </label>
          ))}
        </div>
      </section>
      {type && (
        <form className="editor create-details" onSubmit={(e) => void submit(e)} aria-busy={busy}>
          <h2 ref={details} tabIndex={-1}>
            2. About your {type.kind === 'coloring' ? 'coloring book' : 'word search book'}
          </h2>
          <fieldset disabled={busy}>
            <legend className="sr-only">Book details</legend>
            <div className="field-pair">
              <Field
                label="Book title"
                path="book.title"
                value={values.title}
                issues={fieldIssues}
                onChange={set('title')}
              />
              <Field
                label="Subtitle (optional)"
                path="book.subtitle"
                value={values.subtitle}
                issues={fieldIssues}
                onChange={set('subtitle')}
              />
            </div>
            <div className="field-pair">
              <Field
                label="Author or pen name (optional)"
                path="book.author"
                value={values.author}
                issues={fieldIssues}
                onChange={set('author')}
              />
              <Field
                label="Language"
                path="book.language"
                value={values.language}
                issues={fieldIssues}
                hint="A language tag such as en, en-GB or fr."
                onChange={set('language')}
              />
            </div>
            <Field
              label="Project folder name (optional)"
              path="key"
              value={values.key}
              issues={fieldIssues}
              hint="Lowercase letters and digits joined by hyphens, such as woodland-coloring. Leave it empty to name the folder after the title. It cannot be changed later."
              onChange={set('key')}
            />
            <div className="field-pair">
              <Field
                label="Subject (optional)"
                path="catalog.subject"
                value={values.subject}
                issues={fieldIssues}
                onChange={set('subject')}
              />
              <Field
                label="Collection (optional)"
                path="catalog.collection"
                value={values.collection}
                issues={fieldIssues}
                onChange={set('collection')}
              />
            </div>
            <fieldset className="choice-group">
              <legend>Trim and paper</legend>
              <p className="small muted">KDP standard paperback sizes, black ink, no bleed.</p>
              <label>
                <input
                  type="radio"
                  name="profile"
                  checked={values.profile === ''}
                  onChange={() => set('profile')('')}
                />
                <span>
                  Decide later (Print proof builds 8.5 × 11 in, white paper, unless you choose)
                </span>
              </label>
              {types.profiles.map((p) => (
                <label key={p.id}>
                  <input
                    type="radio"
                    name="profile"
                    checked={values.profile === p.id}
                    onChange={() => set('profile')(p.id)}
                  />
                  <span>{profileLabel(p)}</span>
                </label>
              ))}
            </fieldset>
            <fieldset className="choice-group">
              <legend>Start from</legend>
              {type.templates.map((t) => (
                <label key={t.id}>
                  <input
                    type="radio"
                    name="template"
                    checked={(values.template || type.default_template) === t.id}
                    onChange={() => set('template')(t.id)}
                  />
                  <span>
                    {t.label} <small className="muted">{t.description}</small>
                  </span>
                </label>
              ))}
            </fieldset>
          </fieldset>
          {failure && (
            <div role="alert" className="notice error">
              <h3>
                {failure instanceof ApiError && issues.some((i) => i.code === 'project_exists')
                  ? 'That project folder already exists'
                  : 'The book was not created'}
              </h3>
              <p>{failure.message} Nothing was written; your answers are still here.</p>
              <Issues issues={issues} />
            </div>
          )}
          <div className="editor-actions">
            <button type="submit" className="primary" disabled={busy || !values.title.trim()}>
              {busy ? 'Creating…' : 'Create book'}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
