import { useCallback, useEffect, useRef, useState } from 'react';
import { AdjustPanel } from './AdjustPanel';
import { ApiError, request, upload } from './api';
import { ColoringPages } from './ColoringPages';
import { Cover } from './Cover';
import { useDraft } from './draft';
import { Print } from './Print';
import { Publishing } from './Publishing';
import { Produce } from './Produce';
import { Settings } from './Settings';
import type { ArtworkEntry, ColoringListing, Project } from './types';
import { Empty, ErrorState, Loading, Status } from './ui';

// Coloring books: artwork library, pages, cover, print proofs and publishing. Every
// fact, finding, page and duplicate below is Python's; the browser only displays it,
// edits the authored source and sends files.
const SECTIONS: [string, string][] = [
  ['settings', 'Settings'],
  ['artwork', 'Artwork'],
  ['pages', 'Pages'],
  ['cover', 'Cover'],
  ['print', 'Print proof'],
  ['publishing', 'Publishing'],
  ['produce', 'Produce'],
];
const DRAFT_SECTIONS = ['settings', 'pages', 'cover', 'publishing'];

export function ColoringNav({ base, section }: { base: string; section: string }) {
  return (
    <nav className="project-nav" aria-label="Project">
      <a
        className="nav-overview"
        href={base}
        aria-current={section === 'overview' ? 'page' : undefined}
      >
        Overview
      </a>
      <div className="nav-group">
        <span className="nav-group-label" id="nav-create">
          Create
        </span>
        <ul aria-labelledby="nav-create">
          {SECTIONS.map(([key, label]) => (
            <li key={key}>
              <a href={`${base}/${key}`} aria-current={section === key ? 'page' : undefined}>
                {label}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}

export function ColoringWorkspace({
  project,
  section,
  onDirty = () => {},
  onSaved = () => {},
}: {
  project: Project;
  section: string;
  onDirty?: (dirty: boolean) => void;
  onSaved?: (project: Project) => void;
}) {
  // One draft for Settings, Pages, Cover and Publishing, saved atomically with a
  // revision check.
  const draft = useDraft(project, onSaved, onDirty);
  // The artwork panel saves imports, removals and settings directly. Coming back to the
  // draft sections, a clean draft reloads the saved source so it sees them; a draft
  // with unsaved edits is kept, and saving it then reports the changed source.
  const previous = useRef(section);
  useEffect(() => {
    const left = previous.current;
    previous.current = section;
    if (
      DRAFT_SECTIONS.includes(section) &&
      !DRAFT_SECTIONS.includes(left) &&
      !draft.dirty &&
      !draft.busy
    )
      void draft.run('reload');
    // Only a change of section triggers a reload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section]);
  if (section === 'overview') return <ColoringOverview project={project} />;
  if (section === 'artwork') return <Artwork projectKey={project.key} />;
  if (section === 'print') return <Print project={draft.saved} dirty={draft.dirty} />;
  if (section === 'settings') return <Settings d={draft} />;
  if (section === 'pages') return <ColoringPages d={draft} />;
  if (section === 'cover') return <Cover d={draft} />;
  if (section === 'publishing') return <Publishing d={draft} />;
  if (section === 'produce') return <Produce project={draft.saved} dirty={draft.dirty} />;
  return (
    <Empty title="This page does not exist for coloring books">Use the navigation above.</Empty>
  );
}

function ColoringOverview({ project }: { project: Project }) {
  const source = project.source!;
  const coloring = source.coloring!;
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>The source at a glance</h2>
          <p className="muted">Authored settings for this coloring book.</p>
        </div>
        <Status tone="pass">Validation passed</Status>
      </div>
      <div className="overview-columns">
        <section>
          <h3>Book details</h3>
          <dl className="facts">
            <div>
              <dt>Book type</dt>
              <dd>{project.engine?.label ?? 'Unknown'}</dd>
            </div>
            <div>
              <dt>Book ID</dt>
              <dd>{source.book.id}</dd>
            </div>
            <div>
              <dt>Language</dt>
              <dd>{source.book.language}</dd>
            </div>
            <div>
              <dt>Artwork</dt>
              <dd>{coloring.artwork.length}</dd>
            </div>
            <div>
              <dt>Coloring pages</dt>
              <dd>{coloring.pages.filter((page) => 'artwork' in page).length}</dd>
            </div>
            <div>
              <dt>Section dividers</dt>
              <dd>{coloring.pages.filter((page) => 'divider' in page).length}</dd>
            </div>
            <div>
              <dt>Blank reverse pages</dt>
              <dd>{coloring.layout.blank_reverse ? 'Yes (single-sided)' : 'No'}</dd>
            </div>
            <div>
              <dt>Schema / engine</dt>
              <dd>
                {source.schema_version} / {project.engine_version}
              </dd>
            </div>
          </dl>
        </section>
        <section className="review-start">
          <h3>{coloring.artwork.length ? 'Your next steps' : 'Start with the artwork.'}</h3>
          {!coloring.pages.some((page) => 'artwork' in page) && (
            <p className="notice">
              This book has no coloring pages yet, so it cannot pass the print and publishing
              checks. Import drawings and put them on pages first.
            </p>
          )}
          <ol className="journey">
            <li>
              <a href={`/books/${project.key}/settings`}>Settings</a>: title, author, language,
              paper.
            </li>
            <li>
              <a href={`/books/${project.key}/artwork`}>Artwork</a>: import PNG or JPEG line art and
              prepare it ({coloring.artwork.length} drawings).
            </li>
            <li>
              <a href={`/books/${project.key}/pages`}>Pages</a>: order, dividers, matter and
              placement ({coloring.pages.length} entries).
            </li>
            <li>
              <a href={`/books/${project.key}/print`}>Print proof</a>: build the interior PDF and
              review every page.
            </li>
            <li>
              <a href={`/books/${project.key}/cover`}>Cover</a>: designed and sized from the built
              interior.
            </li>
            <li>
              <a href={`/books/${project.key}/publishing`}>Publishing</a>: KDP details, your
              declarations and the upload package.
            </li>
          </ol>
          <a className="button primary" href={`/books/${project.key}/artwork`}>
            Open the artwork library
          </a>
          <p className="small muted">
            Studio keeps each original unchanged and reports its print resolution and possible
            problems. Nothing is sent to Amazon; you upload the package yourself.
          </p>
        </section>
      </div>
    </>
  );
}

const STATUS_TONE = { blocking: 'fail', warning: 'review' } as const;

function Artwork({ projectKey }: { projectKey: string }) {
  const path = `/api/projects/${encodeURIComponent(projectKey)}/coloring`;
  const [listing, setListing] = useState<ColoringListing>();
  const [error, setError] = useState<Error>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>();
  const [failures, setFailures] = useState<ApiError[]>([]);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    request<ColoringListing>(path, controller.signal)
      .then(setListing)
      .catch((err: Error) => {
        if (!controller.signal.aborted) setError(err);
      });
    return () => controller.abort();
  }, [path, attempt]);

  const importFiles = useCallback(
    async (files: File[]) => {
      if (!listing) return;
      setBusy(true);
      setFailures([]);
      setMessage(undefined);
      let revision = listing.revision;
      let added = 0;
      const failed: ApiError[] = [];
      for (const file of files) {
        const query = new URLSearchParams({ name: file.name, revision });
        try {
          const next = await upload<ColoringListing & { imported: { added: boolean }[] }>(
            `${path}/artwork?${query}`,
            new AbortController().signal,
            file,
            file.type || 'application/octet-stream',
          );
          revision = next.revision;
          added += next.imported.filter((item) => item.added).length;
          setListing(next);
        } catch (err) {
          failed.push(
            err instanceof ApiError
              ? new ApiError(`${file.name}: ${err.message}`, err.code)
              : new ApiError(`${file.name}: the upload failed.`, 'upload_failed'),
          );
        }
      }
      setFailures(failed);
      setMessage(
        `${added} added${files.length - added - failed.length > 0 ? `, ${files.length - added - failed.length} already in the library` : ''}${failed.length ? `, ${failed.length} not imported` : ''}.`,
      );
      setBusy(false);
    },
    [listing, path],
  );

  const remove = async (entry: ArtworkEntry, withPages: boolean) => {
    if (!listing) return;
    setBusy(true);
    setFailures([]);
    try {
      const next = await request<ColoringListing>(`${path}/remove`, new AbortController().signal, {
        artwork: entry.id,
        revision: listing.revision,
        with_pages: withPages,
      });
      setListing(next);
      setMessage(`Removed '${entry.id}' from the book. Its original file is kept in the project.`);
    } catch (err) {
      setFailures([err instanceof ApiError ? err : new ApiError('Removal failed.', 'failed')]);
    }
    setBusy(false);
  };

  if (error) return <ErrorState error={error} retry={() => setAttempt((x) => x + 1)} />;
  if (!listing) return <Loading>Reading and checking the artwork…</Loading>;
  const report = listing.report;
  const duplicates = report.duplicates;
  const confirmed =
    duplicates.confirmed.same_file.length + duplicates.confirmed.repeated_pages.length;
  return (
    <>
      <div className="section-heading">
        <div>
          <h2>Artwork library</h2>
          <p className="muted">
            {report.artwork.length} artwork · {report.pages} pages · originals are never changed
          </p>
        </div>
        <Status tone={report.blocking ? 'fail' : 'pass'}>
          {report.blocking ? `${report.blocking} with blocking problems` : 'No blocking problems'}
        </Status>
      </div>
      <div className="artwork-import">
        <label className={`button primary file-button${busy ? ' disabled' : ''}`}>
          Import artwork…
          <input
            type="file"
            multiple
            accept="image/png,image/jpeg,.svg"
            disabled={busy}
            aria-label="Import artwork (PNG or JPEG, several at once)"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              event.target.value = '';
              if (files.length) void importFiles(files);
            }}
          />
        </label>
        <p className="small muted">
          PNG or JPEG line art, at least 2175 × 2925 px for a full page at 300 DPI. SVG is not
          supported.
        </p>
      </div>
      <div aria-live="polite" className="small">
        {busy ? 'Working…' : message}
      </div>
      {failures.length > 0 && (
        <div role="alert" className="notice error">
          <h2>Some files were not imported</h2>
          <ul>
            {failures.map((failure, index) => (
              <li key={index}>
                {failure.message} <code>{failure.code}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.artwork.length === 0 ? (
        <Empty title="No artwork yet">Import PNG or JPEG line art to start the book.</Empty>
      ) : (
        <ul className="artwork-list" aria-label="Artwork">
          {report.artwork.map((entry) => (
            <ArtworkRow
              key={entry.id}
              projectKey={projectKey}
              entry={entry}
              busy={busy}
              remove={remove}
              revision={listing.revision}
              onSaved={(next) => setListing(next)}
            />
          ))}
        </ul>
      )}
      <section aria-labelledby="duplicates-heading">
        <h3 id="duplicates-heading">Duplicates</h3>
        {confirmed === 0 && duplicates.possible.similar.length === 0 ? (
          <p>
            <Status tone="pass">None found</Status> No repeated files, repeated pages or look-alike
            drawings.
          </p>
        ) : (
          <ul className="plain-list">
            {duplicates.confirmed.same_file.map((group) => (
              <li key={group.sha256}>
                <Status tone="fail">Confirmed</Status> The same file is used by{' '}
                {group.artwork.join(', ')}.
              </li>
            ))}
            {duplicates.confirmed.repeated_pages.map((repeat) => (
              <li key={repeat.artwork}>
                <Status tone="fail">Confirmed</Status> &lsquo;{repeat.artwork}&rsquo; is on pages{' '}
                {repeat.pages.join(', ')}.
              </li>
            ))}
            {duplicates.possible.similar.map((pair) => (
              <li key={pair.artwork.join('|')}>
                <Status tone="review">Possible</Status> {pair.artwork[0]} and {pair.artwork[1]} look
                alike (a heuristic; compare them yourself).
              </li>
            ))}
          </ul>
        )}
        {!duplicates.complete && (
          <p className="small muted">
            Not compared, because they cannot be read: {duplicates.not_compared.join(', ')}.
          </p>
        )}
      </section>
      {report.unreferenced_files.length > 0 && (
        <section aria-labelledby="unreferenced-heading">
          <h3 id="unreferenced-heading">Files no artwork uses</h3>
          <p className="small muted">
            Kept in the project&rsquo;s coloring-assets folder. Nothing is deleted automatically.
          </p>
          <ul className="plain-list">
            {report.unreferenced_files.map((file) => (
              <li key={file}>
                <code>{file}</code>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function ArtworkRow({
  projectKey,
  entry,
  busy,
  remove,
  revision,
  onSaved,
}: {
  projectKey: string;
  entry: ArtworkEntry;
  busy: boolean;
  remove: (entry: ArtworkEntry, withPages: boolean) => Promise<void>;
  revision: string;
  onSaved: (listing: ColoringListing) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const [withPages, setWithPages] = useState(false);
  const info = entry.inspection?.info;
  const findings = entry.inspection?.findings ?? [];
  const title = entry.title ?? entry.id;
  const thumbnail = `/api/projects/${encodeURIComponent(projectKey)}/coloring/thumbnail?${new URLSearchParams({ artwork: entry.id, sha: entry.sha256 })}`;
  return (
    <li className="artwork-row">
      <div className="artwork-thumb">
        {info ? <img src={thumbnail} alt={`Artwork: ${title}`} /> : <span>Unreadable</span>}
      </div>
      <div className="artwork-body">
        <h3>{title}</h3>
        <p className="small muted">
          <code>{entry.id}</code> ·{' '}
          {entry.pages.length ? `page ${entry.pages.join(', ')}` : 'not on a page'}
        </p>
        {info ? (
          <dl className="inline-facts">
            <div>
              <dt>Pixels</dt>
              <dd>
                {info.pixels[0]} × {info.pixels[1]}
              </dd>
            </div>
            <div>
              <dt>Print resolution</dt>
              <dd>{Math.round(info.effective_dpi)} DPI at full size</dd>
            </div>
            <div>
              <dt>File</dt>
              <dd>
                {info.format.toUpperCase()} · {info.mode} · {Math.round(info.bytes / 1024)} KB
              </dd>
            </div>
            <div>
              <dt>Transparency</dt>
              <dd>{info.transparent_pixels ? 'Yes' : 'None'}</dd>
            </div>
          </dl>
        ) : null}
        {entry.error && (
          <p>
            <Status tone="fail">Blocking</Status> {entry.error.message}
          </p>
        )}
        {findings.length > 0 ? (
          <ul className="plain-list">
            {findings.map((finding) => (
              <li key={finding.code}>
                <Status tone={STATUS_TONE[finding.severity]}>
                  {finding.severity === 'blocking' ? 'Blocking' : 'Warning'}
                </Status>{' '}
                {finding.message}
              </li>
            ))}
          </ul>
        ) : (
          info && (
            <p>
              <Status tone="pass">Ready</Status> No problems found in the file.
            </p>
          )
        )}
        {confirming ? (
          <div className="artwork-confirm" role="group" aria-label={`Remove ${title}`}>
            {entry.pages.length > 0 && (
              <label>
                <input
                  type="checkbox"
                  checked={withPages}
                  onChange={(event) => setWithPages(event.target.checked)}
                />{' '}
                Also remove its pages ({entry.pages.join(', ')})
              </label>
            )}
            <button
              type="button"
              disabled={busy || (entry.pages.length > 0 && !withPages)}
              onClick={() => void remove(entry, withPages).then(() => setConfirming(false))}
            >
              Remove from book
            </button>
            <button type="button" onClick={() => setConfirming(false)}>
              Cancel
            </button>
            <p className="small muted">The original file stays in the project.</p>
          </div>
        ) : (
          <div className="artwork-actions">
            {info && (
              <button
                type="button"
                aria-expanded={adjusting}
                onClick={() => setAdjusting((open) => !open)}
              >
                {adjusting ? 'Close preparation' : 'Prepare line art…'}
              </button>
            )}
            <button type="button" disabled={busy} onClick={() => setConfirming(true)}>
              Remove…
            </button>
          </div>
        )}
      </div>
      {adjusting && info && (
        <AdjustPanel
          projectKey={projectKey}
          entry={entry}
          title={title}
          revision={revision}
          onSaved={onSaved}
        />
      )}
    </li>
  );
}
