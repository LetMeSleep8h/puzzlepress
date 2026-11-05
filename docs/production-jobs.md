# Production jobs (Studio)

Studio's **Produce** page runs `book produce` as a *job* in its own operating-system
process. The run itself is the unchanged `produce()` (same writers, checks and
files as the CLI); the job adds isolation, a durable record, cancellation and
recovery. Code: `production/worker.py`, `production/jobs.py`,
`production/release.py`, `production/limits.py`, `cancellation.py`,
`studio/producing.py`, `Produce.tsx`, `produce-state.ts`.

## Architecture

```text
Studio server (FastAPI)                     worker process (one per job)
  POST /produce ──► job.json (request)      python -m puzzlepress.production.worker JOB
                    Popen(worker) ────────►   starting: limits (priority, memory)
  GET /produce  ◄── events.jsonl ◄────────    takes .<release>.produce.lock
                    (fold, reconcile)         recovers leftovers, running
  POST /cancel  ──► cancel (file) ────────►   produce() into .<release>.job-staging-*/release
                                              verify vs production.json + build identity
                                              swap in, verify again, completed
```

No queue service, database or container: a job is a directory beside the release,

```text
.<name>-release.jobs/<job-id>/
  job.json       the request: key, book ID, engine, book.yaml path, revision, release,
                 created, memory limit, digest of the previous release's production.json
  events.jsonl   append-only, one JSON object per line: state, step, progress
  cancel         present once cancellation was requested
  worker.log     the worker's standard error (tracebacks of failures)
```

Job IDs are a UTC timestamp plus 8 random hex digits, so they never repeat and sort
by creation. The ten most recent finished jobs are kept per release; unfinished or
unreadable records are never removed.

## States

| State | Meaning |
| --- | --- |
| `queued` | Recorded; waiting for a free worker slot |
| `starting` | The worker process is up, not yet holding the release lock |
| `running` | The worker holds the lock and is producing |
| `cancelling` | Running, with a cancel request (shown by Studio; the worker reports the end) |
| `completed` | A verified release is in place; outcome `ready` or `blocked` (blocking findings) |
| `failed` | The worker reported an expected failure (`source_changed`, `verification_failed`, a build stage, `memory_limit`, `worker_error`, `worker_start_failed`) |
| `cancelled` | Stopped on request; nothing was swapped in |
| `interrupted` | Ended without the worker reporting an ending: `worker_exited` (the process died, with its exit code), `worker_lost` (seen after a restart: no worker holds the lock), `studio_stopped` (queued when Studio stopped) |

Transitions: queued → starting → running → completed | failed | cancelled, with
cancelling between running and cancelled; any non-terminal state → interrupted when
the worker is provably gone; queued → cancelled without a worker. A terminal state
is final: later lines never change it.

## Lifecycle and guarantees

- **One writer per release.** Studio refuses a second job while one is queued or
  running for the same release, and the worker takes the same OS lock
  `book produce` takes (`production/lock.py`), so the command line and Studio never
  write one release at once. The kernel releases the lock when the worker dies.
- **Different books run side by side**, up to `max(1, min(3, CPUs // 2))` workers;
  more wait as `queued` in request order.
- **Limits.** The worker caps its memory at 4096 MB (Windows Job Object per-process
  commit limit, POSIX `RLIMIT_AS`); an allocation past the cap fails as
  `memory_limit` and the release is kept. Priority is normal by default;
  `puzzlepress-studio --worker-priority low` runs workers below normal (Windows
  `BELOW_NORMAL`, POSIX `nice` +10), which yields to other work but measured about
  35 % slower while other processes competed for the CPU, with no measured benefit to
  Studio's own latency (the server is a separate process either way). The job records
  what took effect (Interval 8 records without the field read as below normal). The
  worker's peak memory is in the completed result. `worker.log` keeps its last 1 MB;
  ten finished jobs are kept per release; an event log over 4 MB is refused as damaged.
- **Source.** The worker refuses a job whose book.yaml no longer has the requested
  revision, and checks the produced manifest's build identity and book ID.
- **Previous release.** Replaced only by a staged release whose every file matched
  `production.json` (and nothing else is present), then verified again in place.
  A failed, cancelled or killed worker leaves it as it was; Studio reports
  `release_preserved` (`unchanged`, `none`, `pending_recovery`, `changed`).
- **Crash recovery.** A killed worker leaves its staging directory, and perhaps a
  backup if it died between the two renames of the swap. The next job, under the
  lock, restores such a backup when the release is missing, removes the rest and
  lists what it did in its notes. Studio shows `recovery_pending` meanwhile.
- **Restart.** Studio keeps no job state in memory that matters: after a restart it
  folds the latest job record, follows a worker that still holds the lock (it can be
  cancelled), and records `interrupted` for one that is gone. A queued or starting job
  another Studio process created gets 30 s to take the lock before it is called gone,
  so a second Studio never declares a booting worker dead; two workers racing for one
  release are settled by the lock (one writes, the other fails
  `production_in_progress`). There is no force-unlock: a lock held by a live process
  is never taken.
- **Responses.** Each status names the job and its event count (`seq`); the page
  never lets an older job, or an earlier view of the same job, replace a newer one.
- **Polling (Interval 9).** While a job runs, the page polls `GET .../produce/job`: the
  job record and the digest of `production.json`, with no release file read. When the
  job ends, or that digest changes, it fetches the verified status, which reads every
  listed file back; files and downloads come only from there, and each download
  verifies again. Studio reuses a parsed `book.yaml` only for byte-identical source
  (its SHA-256 is the revision). Measured median for 150 / 300 drawings: job poll
  3.3 / 3.1 ms, verified status 23 / 30 ms (was 127 / 236 ms, dominated by parsing the
  source on every request, not by hashing the release).
- **Project loading (Interval 10).** `ProjectStore.snapshot` reads and hashes book.yaml
  on every request and reuses a parsed project only for the same key's byte-identical
  source (at most 8 projects; invalid sources never kept), so every Studio request,
  Produce included, is cheap without ever serving a stale project. Cold / warm median
  for `GET /api/projects/{key}`: 1 drawing 24 / 4.0 ms, 150 drawings 111 / 6.6 ms, 300
  drawings 216 / 9.8 ms.

## Cancellation

Cancellation is cooperative, never a process kill. Studio creates `cancel`; the
worker checks it at every step boundary and at *checkpoints* inside the long loops
(`puzzlepress.cancellation.checkpoint`), at most every 0.2 s:

| Stage | Checkpoint | Work units shown |
| --- | --- | --- |
| `generate_puzzles` | before each puzzle | puzzles generated |
| `prepare_artwork` | before each drawing | drawings prepared |
| `render_pages` | before each page | pages drawn |
| `inspect_pdf`, `read_pdf_text`, `verify_images` | before each PDF page | PDF pages |
| `measure_artwork`, `compare_artwork` | before each drawing | drawings |
| `write_package` | before each package file | files written |

Between checkpoints work is not interruptible, and that is the cancellation
boundary: one drawing's preparation and measures (about 1-3 s for a full-page scan),
ReportLab's final save of the whole PDF, pypdf's parse of the whole file, a cover
render, and the swap itself (once `release_swap` starts, the job finishes). Without a
watcher (CLI, tests) checkpoints do nothing and every output is byte-identical
(`tests/test_production_jobs.py`, golden baseline). `Cancelled` derives from
BaseException so a broad handler cannot swallow it; every writer cleans its staging
files on the way out. Progress is reported only where Python counts real units; no
percentage is estimated.

## API

| Endpoint | |
| --- | --- |
| `GET /api/projects/{key}/produce` | `run` (the latest job: job_id, seq, state, outcome, step, step_label, steps, progress {stage, done, total, label}, seconds, started, finished, cancellable, cancel_requested, queue_position, release_preserved, error, result, notes, limits, pid), `release` (verified, problem, stale, manifest_sha256, files, validation, package), `recovery_pending`, `history` (last five), `workers` {running, limit} |
| `GET /api/projects/{key}/produce/job` | The cheap poll: `run` as above, `release_manifest_sha256`, `release_checked: false`, `recovery_pending`, `workers`; reads no release file and offers none |
| `POST /api/projects/{key}/produce` | `{revision}`; records and starts (or queues) a job; 409 `source_changed`, `production_in_progress` (a job, or another writer such as the CLI, holds the release) |
| `POST /api/projects/{key}/produce/cancel` | `{}`; requests cancellation (a queued job is cancelled at once); 409 `no_active_run`, `not_cancellable` (the release is being put in place) |
| `GET .../produce/file?name=`, `GET .../produce/package.zip` | Verified release files only, unchanged |

## Testing

`tests/test_production_jobs.py` (job records, lock probe, memory cap, worker in
process, byte-identical outputs with a watcher) and `tests/web/test_produce_api.py`
(real worker processes; `tests/worker_harness.py` injects slow steps, slow
checkpoints, a crash at any step or between the swap's two renames, a tampered staged
file, a slow start, a memory allocation, or log noise). Measurements:
`tests/production_benchmark.py` (see CONTEXT.md).
