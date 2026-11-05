import { useState, type ReactNode } from 'react';
import { Inspector, Quality } from './Puzzles';
import type { Definition } from './types';
import { Empty, Status } from './ui';
import { ContentEditor } from './ContentEditor';
import { DraftToolbar, type Draft } from './draft';

import { Field, move, type Content } from './editor-fields';
import {
  REVIEW_LABELS,
  ReviewBadge,
  ReviewControls,
  ReviewProgress,
  puzzleSignature,
  useReviews,
} from './review';
import type { ReviewState } from './types';

const STARTER: Content = {
  banks: [{ id: 'words', entries: [{ id: 'word-1', display: '' }] }],
  profiles: [
    {
      id: 'custom',
      width: 10,
      height: 10,
      directions: ['right', 'down'],
      max_restarts: 20,
      max_attempts: 100000,
    },
  ],
  puzzles: [
    {
      id: 'puzzle-1',
      title: 'New puzzle',
      theme: '',
      bank: 'words',
      target_ids: ['word-1'],
      difficulty: 'custom',
    },
  ],
  quality: {
    max_word_reuse: 2,
    target_similarity_threshold: 0.8,
    grid_similarity_threshold: 0.9,
    prohibited_words: [],
  },
};

export function Editor({ d }: { d: Draft }) {
  const { draft, issues, busy, preview, saved, dirty } = d;
  const change = d.change;
  const [selected, setSelected] = useState(0);
  const [epoch, setEpoch] = useState(d.epoch);
  const [view, setView] = useState<'puzzle' | 'quality'>('puzzle');
  const [query, setQuery] = useState('');
  const [theme, setTheme] = useState('');
  const [level, setLevel] = useState('');
  const [reviewFilter, setReviewFilter] = useState<ReviewState | ''>('');
  const reviews = useReviews(d.key, saved.revision);
  const reviewStates = new Map(
    (reviews.data?.report.puzzles ?? []).map((review) => [review.puzzle, review]),
  );
  if (epoch !== d.epoch) {
    // Saved, reloaded or reverted drafts start again at the first definition.
    setEpoch(d.epoch);
    setSelected(0);
  }

  function content(next: Content) {
    change({ ...draft, word_search: next });
  }
  function updatePuzzle(patch: Partial<Definition>) {
    if (!draft.word_search) return;
    content({
      ...draft.word_search,
      puzzles: draft.word_search.puzzles.map((p, i) => (i === selected ? { ...p, ...patch } : p)),
    });
  }
  const ws = draft.word_search;
  const puzzle = ws?.puzzles[selected];
  const path = `word_search.puzzles.${selected}`;
  const result = preview?.report.puzzles[selected];
  return (
    <div className="editor">
      <DraftToolbar
        d={d}
        title="Puzzles"
        preview="preview"
        previewLabel="Preview draft"
        previewDisabled={!ws}
        jump={{ href: '#draft-preview', label: 'Jump to preview' }}
      />
      <div className={`editor-layout${ws ? ' with-navigator' : ''}`}>
        {ws && (
          <PuzzleNavigator
            puzzles={ws.puzzles}
            selected={selected}
            onSelect={setSelected}
            query={query}
            setQuery={setQuery}
            theme={theme}
            setTheme={setTheme}
            level={level}
            setLevel={setLevel}
            flagged={flaggedPuzzles(
              issues.map((i) => i.path),
              preview,
            )}
            reviews={reviewStates}
            reviewFilter={reviewFilter}
            setReviewFilter={setReviewFilter}
            progress={<ReviewProgress data={reviews.data} />}
            onAdd={() => {
              let n = 1;
              while (ws.puzzles.some((p) => p.id === `puzzle-${n}`)) n++;
              content({
                ...ws,
                puzzles: [
                  ...ws.puzzles,
                  {
                    id: `puzzle-${n}`,
                    title: 'New puzzle',
                    theme: '',
                    bank: ws.banks[0]?.id ?? '',
                    target_ids: [],
                    difficulty: ws.profiles[0]?.id ?? '',
                  },
                ],
              });
              setSelected(ws.puzzles.length);
              setQuery('');
              setTheme('');
              setLevel('');
            }}
          />
        )}
        <form aria-label="Project authoring" onSubmit={(event) => event.preventDefault()}>
          <fieldset className="authoring-fields" disabled={busy}>
            <legend className="sr-only">Project draft</legend>
            {/* Book details are edited in one place, Settings; this shows them. */}
            <section className="book-fields" aria-labelledby="book-fields-heading">
              <h3 id="book-fields-heading">Book</h3>
              <p className="small">
                <strong>{draft.book.title}</strong> · {draft.book.language}.{' '}
                <a href={`/books/${encodeURIComponent(d.key)}/settings`}>
                  Edit the title, language and other book details in Settings
                </a>
              </p>
            </section>
            {!ws ? (
              <Empty title="No word-search content">
                <span>
                  This legacy project has no banks, profiles or puzzle definitions. Add its first
                  word-search content explicitly.
                </span>
                <button type="button" onClick={() => content(structuredClone(STARTER))}>
                  Add word-search content
                </button>
              </Empty>
            ) : puzzle ? (
              <section className="puzzle-fields" aria-labelledby="puzzle-fields-heading">
                <div className="puzzle-fields-heading">
                  <h3 id="puzzle-fields-heading">
                    Puzzle {selected + 1} <span className="muted">of {ws.puzzles.length}</span>
                  </h3>
                  <div className="button-row">
                    <button
                      type="button"
                      className="small-button"
                      disabled={selected === 0}
                      onClick={() => setSelected(selected - 1)}
                    >
                      ← Previous
                    </button>
                    <button
                      type="button"
                      className="small-button"
                      disabled={selected === ws.puzzles.length - 1}
                      onClick={() => setSelected(selected + 1)}
                    >
                      Next →
                    </button>
                  </div>
                </div>
                <PuzzleFindings id={puzzle.id} preview={preview} dirty={dirty} />
                <ReviewControls
                  projectKey={d.key}
                  review={reviewStates.get(puzzle.id)}
                  data={reviews.data}
                  onSaved={reviews.setData}
                  unsaved={
                    saved.source !== undefined &&
                    puzzleSignature(draft, puzzle.id) !== puzzleSignature(saved.source, puzzle.id)
                  }
                />
                <Field
                  label="Puzzle title"
                  path={`${path}.title`}
                  value={puzzle.title}
                  issues={issues}
                  onChange={(title) => updatePuzzle({ title })}
                />
                <div className="field-pair">
                  <Field
                    label="Puzzle ID"
                    path={`${path}.id`}
                    value={puzzle.id}
                    issues={issues}
                    onChange={(id) => updatePuzzle({ id })}
                  />
                  <Field
                    label="Theme"
                    path={`${path}.theme`}
                    value={puzzle.theme}
                    issues={issues}
                    onChange={(theme) => updatePuzzle({ theme })}
                  />
                </div>
                <ContentEditor
                  content={ws}
                  puzzle={puzzle}
                  selected={selected}
                  issues={issues}
                  onChange={content}
                  onPuzzle={updatePuzzle}
                />
                <div className="button-row order-actions">
                  <button
                    type="button"
                    className="small-button"
                    aria-label={`Move puzzle ${selected + 1} up`}
                    disabled={selected === 0}
                    onClick={() => {
                      content({ ...ws, puzzles: move(ws.puzzles, selected, -1) });
                      setSelected(selected - 1);
                    }}
                  >
                    Move up
                  </button>
                  <button
                    type="button"
                    className="small-button"
                    aria-label={`Move puzzle ${selected + 1} down`}
                    disabled={selected === ws.puzzles.length - 1}
                    onClick={() => {
                      content({ ...ws, puzzles: move(ws.puzzles, selected, 1) });
                      setSelected(selected + 1);
                    }}
                  >
                    Move down
                  </button>
                  <button
                    type="button"
                    className="small-button"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Remove “${puzzle.title}” from this draft? Its word bank will remain.`,
                        )
                      ) {
                        content({
                          ...ws,
                          puzzles: ws.puzzles.filter((_, i) => i !== selected),
                        });
                        setSelected(Math.max(0, selected - 1));
                      }
                    }}
                  >
                    Remove puzzle
                  </button>
                </div>
              </section>
            ) : (
              <p>Add a puzzle definition to continue. Python requires at least one.</p>
            )}
            <details className="editor-settings">
              <summary>Shared seed</summary>
              <Field
                label="Project seed"
                path="build.seed"
                value={draft.build.seed}
                issues={issues}
                onChange={(seed) => change({ ...draft, build: { seed } })}
              />
              <p className="small muted">
                Shared by every puzzle. Puzzle IDs determine their individual seeds; changing an ID
                changes its grid.
              </p>
            </details>
          </fieldset>
        </form>
        <div className="draft-preview" id="draft-preview" tabIndex={-1} aria-label="Draft preview">
          <div className="section-heading">
            <h3>
              {preview
                ? dirty
                  ? 'Unsaved draft preview'
                  : 'Preview of saved content'
                : 'Your draft on paper'}
            </h3>
            {preview && (
              <div className="segmented-inline" role="group" aria-label="Preview">
                <button
                  type="button"
                  aria-pressed={view === 'puzzle'}
                  onClick={() => setView('puzzle')}
                >
                  Selected puzzle
                </button>
                <button
                  type="button"
                  aria-pressed={view === 'quality'}
                  onClick={() => setView('quality')}
                >
                  Whole-book quality
                </button>
              </div>
            )}
          </div>
          {!preview ? (
            <div className="preview-empty">
              <h2>See what your edits make.</h2>
              <p>
                Preview validates the whole draft, generates every puzzle and checks quality.
                Nothing is saved until you choose Save changes.
              </p>
            </div>
          ) : view === 'quality' ? (
            <Quality generation={preview} />
          ) : (
            result && (
              <Inspector
                key={result.id}
                project={{ ...saved, source: draft }}
                generation={preview}
                result={result}
              />
            )
          )}
        </div>
      </div>
    </div>
  );
}

function flaggedPuzzles(paths: string[], preview: Draft['preview']): Set<number | string> {
  const flagged = new Set<number | string>();
  for (const path of paths) {
    const match = path.match(/^word_search\.puzzles\.(\d+)/);
    if (match) flagged.add(Number(match[1]));
  }
  for (const finding of preview?.report.findings ?? [])
    for (const id of finding.puzzle_ids) flagged.add(id);
  for (const result of preview?.report.puzzles ?? []) if (!result.puzzle) flagged.add(result.id);
  return flagged;
}

// A compact, filterable list: only the selected puzzle's editor is rendered.
function PuzzleNavigator({
  puzzles,
  selected,
  onSelect,
  query,
  setQuery,
  theme,
  setTheme,
  level,
  setLevel,
  flagged,
  onAdd,
  reviews,
  reviewFilter,
  setReviewFilter,
  progress,
}: {
  reviews: Map<string, { state: ReviewState }>;
  reviewFilter: ReviewState | '';
  setReviewFilter: (value: ReviewState | '') => void;
  progress: ReactNode;
  puzzles: Definition[];
  selected: number;
  onSelect: (index: number) => void;
  query: string;
  setQuery: (value: string) => void;
  theme: string;
  setTheme: (value: string) => void;
  level: string;
  setLevel: (value: string) => void;
  flagged: Set<number | string>;
  onAdd: () => void;
}) {
  const themes = [...new Set(puzzles.map((p) => p.theme).filter(Boolean))].sort();
  const levels = [...new Set(puzzles.map((p) => p.difficulty).filter(Boolean))];
  const needle = query.trim().toLowerCase();
  const shown = puzzles
    .map((puzzle, index) => ({ puzzle, index }))
    .filter(
      ({ puzzle }) =>
        (!theme || puzzle.theme === theme) &&
        (!level || puzzle.difficulty === level) &&
        (!reviewFilter || (reviews.get(puzzle.id)?.state ?? 'not_reviewed') === reviewFilter) &&
        (!needle ||
          puzzle.title.toLowerCase().includes(needle) ||
          puzzle.id.toLowerCase().includes(needle) ||
          puzzle.theme.toLowerCase().includes(needle)),
    );
  return (
    <section className="puzzle-navigator" aria-labelledby="puzzle-navigator-heading">
      <div className="tool-heading">
        <h3 id="puzzle-navigator-heading">
          Puzzles <span className="muted">({puzzles.length})</span>
        </h3>
        <button type="button" className="small-button" onClick={onAdd}>
          Add puzzle
        </button>
      </div>
      <div className="navigator-filters">
        <label className="sr-only" htmlFor="puzzle-search">
          Search puzzles
        </label>
        <input
          id="puzzle-search"
          type="search"
          placeholder="Search title, ID or theme"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="field-pair">
          <div>
            <label className="sr-only" htmlFor="puzzle-theme-filter">
              Filter by theme
            </label>
            <select
              id="puzzle-theme-filter"
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
            >
              <option value="">All themes</option>
              {themes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="sr-only" htmlFor="puzzle-level-filter">
              Filter by difficulty
            </label>
            <select
              id="puzzle-level-filter"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
            >
              <option value="">All levels</option>
              {levels.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>
      <div className="field-pair">
        <div>
          <label className="sr-only" htmlFor="puzzle-review-filter">
            Filter by review state
          </label>
          <select
            id="puzzle-review-filter"
            value={reviewFilter}
            onChange={(e) => setReviewFilter(e.target.value as ReviewState | '')}
          >
            <option value="">All reviews</option>
            {(Object.keys(REVIEW_LABELS) as ReviewState[]).map((state) => (
              <option key={state} value={state}>
                {REVIEW_LABELS[state]}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          className="small-button"
          onClick={() => {
            const order = puzzles.map((p, index) => ({ p, index }));
            const next =
              order.find(
                ({ p, index }) =>
                  index > selected && (reviews.get(p.id)?.state ?? 'not_reviewed') !== 'reviewed',
              ) ??
              order.find(({ p }) => (reviews.get(p.id)?.state ?? 'not_reviewed') !== 'reviewed');
            if (next) onSelect(next.index);
          }}
        >
          Next unreviewed
        </button>
      </div>
      {progress}
      <p className="small muted navigator-count" aria-live="polite">
        {shown.length === puzzles.length
          ? `All ${puzzles.length} puzzles`
          : `Showing ${shown.length} of ${puzzles.length}`}
      </p>
      <ol className="definition-list" aria-label="Puzzle definitions">
        {shown.map(({ puzzle, index }) => (
          <li key={index}>
            <button
              type="button"
              className="definition-select"
              aria-pressed={index === selected}
              onClick={() => onSelect(index)}
            >
              <span className="ordinal">{index + 1}.</span>
              <span className="definition-text">
                <span>{puzzle.title || 'Untitled puzzle'}</span>
                <small>
                  {puzzle.theme || 'No theme'} · {puzzle.difficulty}
                </small>
              </span>
              {reviews.has(puzzle.id) && (
                <ReviewBadge state={reviews.get(puzzle.id)!.state} compact />
              )}
              {(flagged.has(index) || flagged.has(puzzle.id)) && (
                <span className="status review">
                  <span aria-hidden="true" className="status-mark" />
                  <span className="sr-only">Has findings</span>
                </span>
              )}
            </button>
          </li>
        ))}
        {shown.length === 0 && <li className="small muted">No puzzle matches these filters.</li>}
      </ol>
    </section>
  );
}

// Findings Python reported for this puzzle in the last preview, beside its fields.
function PuzzleFindings({
  id,
  preview,
  dirty,
}: {
  id: string;
  preview: Draft['preview'];
  dirty: boolean;
}) {
  if (!preview) return null;
  const result = preview.report.puzzles.find((p) => p.id === id);
  const findings = preview.report.findings.filter((f) => f.puzzle_ids.includes(id));
  if (result && result.puzzle && !findings.length)
    return (
      <p className="small puzzle-findings">
        <Status tone="pass">Generated</Status> No quality findings for this puzzle in the last
        preview{dirty ? '; later edits are not checked yet' : ''}.
      </p>
    );
  return (
    <div className="puzzle-findings" role="group" aria-label="Findings for this puzzle">
      {result && !result.puzzle && (
        <p className="small">
          <Status tone="fail">Not generated</Status> {result.errors.map((e) => e.message).join(' ')}
        </p>
      )}
      {findings.map((finding, i) => (
        <p key={i} className="small">
          <Status tone="review">Review</Status> <strong>{finding.code.replaceAll('_', ' ')}</strong>
          : {finding.message}
        </p>
      ))}
    </div>
  );
}
