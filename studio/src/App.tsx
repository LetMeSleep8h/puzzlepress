import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, request } from './api';
import { Library } from './Library';
import { Overview } from './Overview';
import { Inspector, PuzzleList, Quality } from './Puzzles';
import type { Generation, Project } from './types';
import { Empty, ErrorState, Loading } from './ui';
import { Editor } from './Editor';
import { Composer } from './Composer';
import { Print } from './Print';
import { Cover } from './Cover';
import { Publishing } from './Publishing';
import { Planning } from './Planning';
import { Interior } from './Interior';
import { useDraft } from './draft';
import { ColoringNav, ColoringWorkspace } from './Coloring';

function usePath(allow: (next: string, current: string) => boolean) {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const update = () => {
      if (allow(window.location.pathname, path)) setPath(window.location.pathname);
      else history.pushState(null, '', path);
    };
    const click = (event: MouseEvent) => {
      const link = (event.target as Element).closest('a');
      if (
        !link ||
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey ||
        link.target ||
        // A download is a file from the API, never a Studio page: the browser handles it.
        link.hasAttribute('download') ||
        link.origin !== window.location.origin ||
        link.hash
      )
        return;
      event.preventDefault();
      if (link.pathname === window.location.pathname) return;
      if (!allow(link.pathname, path)) return;
      history.pushState(null, '', link.pathname);
      update();
    };
    window.addEventListener('popstate', update);
    document.addEventListener('click', click);
    return () => {
      window.removeEventListener('popstate', update);
      document.removeEventListener('click', click);
    };
  }, [allow, path]);
  return path;
}

function DraftWorkspace({
  project,
  section,
  onDirty,
  onSaved,
}: {
  project: Project;
  section: string;
  onDirty: (dirty: boolean) => void;
  onSaved: (project: Project) => void;
}) {
  const draft = useDraft(project, onSaved, onDirty);
  return (
    <>
      <div hidden={section !== 'edit'}>
        <Editor d={draft} />
      </div>
      {section === 'book' && <Composer d={draft} />}
      {section === 'interior' && <Interior d={draft} />}
      {section === 'cover' && <Cover d={draft} />}
      {section === 'publishing' && <Publishing d={draft} />}
    </>
  );
}

function ProjectWorkspace({
  projectKey,
  section,
  puzzleId,
  onDirty,
}: {
  projectKey: string;
  section: string;
  puzzleId?: string;
  onDirty: (dirty: boolean) => void;
}) {
  const [project, setProject] = useState<Project>();
  const [error, setError] = useState<Error>();
  const [generation, setGeneration] = useState<Generation>();
  const [generationError, setGenerationError] = useState<Error>();
  const [loadingGeneration, setLoadingGeneration] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // The book draft (book.yaml) and the plan draft (planning.yaml) are separate
  // documents; leaving the project is guarded while either has unsaved edits.
  const [dirty, setDirty] = useState(false);
  const [planDirty, setPlanDirty] = useState(false);
  const [planningOpened, setPlanningOpened] = useState(section === 'planning');
  useEffect(() => onDirty(dirty || planDirty), [dirty, planDirty, onDirty]);
  useEffect(() => {
    if (section === 'planning') setPlanningOpened(true);
  }, [section]);
  const trackDirty = useCallback((next: boolean) => setDirty(next), []);
  const trackPlanDirty = useCallback((next: boolean) => setPlanDirty(next), []);
  const generationController = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError(undefined);
    request<Project>(`/api/projects/${encodeURIComponent(projectKey)}`, controller.signal)
      .then(setProject)
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => {
      controller.abort();
      generationController.current?.abort();
    };
  }, [projectKey, attempt]);
  const needsGeneration = ![
    'overview',
    'edit',
    'book',
    'interior',
    'print',
    'cover',
    'publishing',
    'planning',
  ].includes(section);
  useEffect(() => {
    if (
      !needsGeneration ||
      !project?.source?.word_search ||
      generation ||
      generationError ||
      generationController.current
    )
      return;
    const controller = new AbortController();
    generationController.current = controller;
    setLoadingGeneration(true);
    request<Generation>(
      `/api/projects/${encodeURIComponent(projectKey)}/generation`,
      controller.signal,
      { identity: project.identity },
    )
      .then((data) => {
        if (!controller.signal.aborted) setGeneration(data);
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) setGenerationError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingGeneration(false);
        generationController.current = null;
      });
  }, [needsGeneration, project, projectKey, generation, generationError]);
  const retryGeneration = () => {
    setGenerationError(undefined);
    setProject(undefined);
    setAttempt((x) => x + 1);
  };
  if (error) return <ErrorState error={error} retry={() => setAttempt((x) => x + 1)} />;
  if (!project) return <Loading />;
  const base = `/books/${encodeURIComponent(projectKey)}`;
  const result = generation?.report.puzzles.find((p) => p.id === puzzleId);
  const count = project.source?.word_search?.puzzles.length ?? 0;
  const book = project.source?.book;
  const heading = (
    <header className="project-heading">
      <h1>
        <a href={base} aria-current={section === 'overview' ? 'page' : undefined}>
          {book?.title ?? projectKey}
        </a>
      </h1>
      <p className="muted">
        {book?.subtitle && <span>{book.subtitle} · </span>}
        {book?.id} · {book?.language}
        {(dirty || planDirty) && (
          <span className="draft-chip">
            <span aria-hidden="true" className="status-mark" /> Unsaved draft
          </span>
        )}
      </p>
    </header>
  );
  // Coloring books have their own, smaller workspace; nothing word-search mounts.
  if (project.engine?.kind === 'coloring' && project.source?.coloring)
    return (
      <>
        {heading}
        <ColoringNav base={base} section={section} />
        <ColoringWorkspace
          project={project}
          section={section}
          onDirty={trackDirty}
          onSaved={(next) => setProject(next)}
        />
      </>
    );
  return (
    <>
      {heading}
      <ProjectNav base={base} section={section} count={count} />
      {project.source && (
        <DraftWorkspace
          project={project}
          section={section}
          onDirty={trackDirty}
          onSaved={(next) => {
            setProject(next);
            setGeneration(undefined);
            setGenerationError(undefined);
          }}
        />
      )}
      {planningOpened && (
        <div hidden={section !== 'planning'}>
          <Planning projectKey={projectKey} onDirty={trackPlanDirty} />
        </div>
      )}
      {['edit', 'book', 'interior', 'cover', 'publishing', 'planning'].includes(
        section,
      ) ? null : section === 'print' ? (
        <Print project={project} dirty={dirty} />
      ) : section === 'overview' ? (
        <Overview project={project} />
      ) : !project.source?.word_search ? (
        <Empty title="No puzzle definitions">
          This source fixture does not configure word searches. Its authored content is available in
          Overview.
        </Empty>
      ) : generationError ? (
        <ErrorState error={generationError} retry={retryGeneration} />
      ) : loadingGeneration || !generation ? (
        <Loading>Generating and independently verifying the authored puzzles…</Loading>
      ) : section === 'quality' ? (
        <Quality generation={generation} />
      ) : puzzleId ? (
        result ? (
          <Inspector key={puzzleId} project={project} generation={generation} result={result} />
        ) : (
          <ErrorState
            error={new ApiError('This puzzle is not defined in the project.', 'puzzle_not_found')}
          />
        )
      ) : (
        <PuzzleList project={project} generation={generation} />
      )}
      {generation && (
        <footer className="analysis-footer">
          Generated analysis · pipeline {generation.report.pipeline_version} ·{' '}
          <DetailsIdentity identity={generation.report.identity} />
        </footer>
      )}
    </>
  );
}

// Sections grouped by stage, in workflow order. Every earlier URL is unchanged.
const NAV: { group: string; items: [string, string, string?][] }[] = [
  {
    group: 'Create',
    items: [
      ['planning', 'Plan'],
      ['edit', 'Puzzles', 'count'],
      ['book', 'Book'],
      ['interior', 'Interior'],
      ['cover', 'Cover'],
    ],
  },
  {
    group: 'Review',
    items: [
      ['print', 'Print proof'],
      ['puzzles', 'Solutions'],
      ['quality', 'Quality'],
    ],
  },
  { group: 'Publish', items: [['publishing', 'Publishing']] },
];

function ProjectNav({ base, section, count }: { base: string; section: string; count: number }) {
  return (
    <nav className="project-nav" aria-label="Project">
      <a
        className="nav-overview"
        href={base}
        aria-current={section === 'overview' ? 'page' : undefined}
      >
        Overview
      </a>
      {NAV.map(({ group, items }, index) => (
        <div className="nav-group" key={group}>
          {index > 0 && (
            <span className="nav-arrow" aria-hidden="true">
              →
            </span>
          )}
          <span className="nav-group-label" id={`nav-${group.toLowerCase()}`}>
            {group}
          </span>
          <ul aria-labelledby={`nav-${group.toLowerCase()}`}>
            {items.map(([key, label, extra]) => (
              <li key={key}>
                <a href={`${base}/${key}`} aria-current={section === key ? 'page' : undefined}>
                  {label}
                  {extra === 'count' && <span className="nav-count">{count}</span>}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function DetailsIdentity({ identity }: { identity: string }) {
  return (
    <details>
      <summary>Source identity</summary>
      <code className="identity">{identity}</code>
    </details>
  );
}

class RenderBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <section role="alert" className="notice error">
        <h1>Studio could not display this view</h1>
        <p>Reload the page. If this continues, check the server log.</p>
        <button onClick={() => window.location.reload()}>Reload Studio</button>
      </section>
    ) : (
      this.props.children
    );
  }
}

export function App() {
  const [dirty, setDirty] = useState(false);
  const path = usePath((next, current) => {
    const currentKey = current.split('/')[2];
    return (
      !dirty ||
      next.startsWith(`/books/${currentKey}/`) ||
      next === `/books/${currentKey}` ||
      window.confirm('Leave this project and discard unsaved changes?')
    );
  });
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  useEffect(() => {
    document.title = 'PuzzlePress Studio';
    if (!first.current) {
      main.current?.focus();
      window.scrollTo?.(0, 0);
    }
    first.current = false;
  }, [path]);
  const match = path.match(
    /^\/books\/([^/]+)(?:\/(puzzles|quality|edit|book|interior|print|cover|publishing|planning|artwork|pages)(?:\/([^/]+))?)?\/?$/,
  );
  const isLibrary = path === '/' || path === '/books' || path === '/books/';
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="appbar">
        <a className="brand" href="/books">
          <img src="/logo.png" alt="" />
          <span>PuzzlePress</span>
        </a>
        <nav aria-label="Library" className="appbar-nav">
          <a href="/books" aria-current={isLibrary ? 'page' : undefined}>
            Books
          </a>
        </nav>
        <span className="appbar-note">Local studio · files stay on this machine</span>
      </header>
      <div className="workspace">
        <main id="main" ref={main} tabIndex={-1} className={isLibrary ? 'library-main' : undefined}>
          <RenderBoundary>
            {isLibrary ? (
              <Library />
            ) : match &&
              !(
                [
                  'quality',
                  'edit',
                  'book',
                  'interior',
                  'print',
                  'cover',
                  'publishing',
                  'planning',
                  'artwork',
                  'pages',
                ].includes(match[2]) && match[3]
              ) ? (
              <ProjectWorkspace
                key={match[1]}
                projectKey={match[1]}
                section={match[2] ?? 'overview'}
                puzzleId={match[3]}
                onDirty={setDirty}
              />
            ) : (
              <ErrorState error={new ApiError('This Studio page does not exist.', 'not_found')} />
            )}
          </RenderBoundary>
        </main>
      </div>
    </div>
  );
}
