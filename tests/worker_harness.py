"""The real production worker with injected delays, crashes or tampering (tests only).

    python tests/worker_harness.py [--slow STEP SECONDS] [--slow-stage STAGE SECONDS]
                                   [--crash STEP] [--tamper] [--hold SECONDS] JOB

`--slow` sleeps after a step starts, `--slow-stage` sleeps at every checkpoint of a
stage (so cancellation lands inside the step), `--crash` ends the process abruptly
(`os._exit`, no cleanup, like a killed worker) when a step starts, `--tamper`
changes a staged file just before the release is verified, and `--hold` sleeps
before the worker starts (a slow start). Everything else is `production.worker`.
"""

import argparse
import os
import sys
import time
from pathlib import Path

from puzzlepress.production import jobs, worker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slow", nargs=2, action="append", default=[])
    parser.add_argument("--slow-stage", nargs=2, action="append", default=[])
    parser.add_argument("--crash")
    parser.add_argument("--tamper", action="store_true")
    parser.add_argument("--hold", type=float, default=0.0)
    parser.add_argument("job")
    args = parser.parse_args()
    slow = {name: float(seconds) for name, seconds in args.slow}
    slow_stage = {name: float(seconds) for name, seconds in args.slow_stage}
    step, checkpoint = worker.Reporter.step, worker.Reporter.checkpoint

    def patched_step(self: worker.Reporter, name: str) -> None:
        if name == args.crash:
            os._exit(9)
        if args.tamper and name == "release_verify":
            spec = jobs.read_spec(Path(args.job))
            target = Path(spec.release)
            for staged in target.parent.glob(jobs.staging_prefix(target) + "*"):
                (staged / "release" / "interior.pdf").write_bytes(b"%PDF-1.4 tampered")
        step(self, name)
        time.sleep(slow.get(name, 0.0))

    def patched_checkpoint(
        self: worker.Reporter, stage: str, done: int | None, total: int | None
    ) -> None:
        checkpoint(self, stage, done, total)
        time.sleep(slow_stage.get(stage, 0.0))

    worker.Reporter.step = patched_step  # type: ignore[method-assign]
    worker.Reporter.checkpoint = patched_checkpoint  # type: ignore[method-assign]
    time.sleep(args.hold)
    return worker.main([args.job])


if __name__ == "__main__":
    sys.exit(main())
