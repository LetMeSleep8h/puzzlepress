"""Time a SYNTHETIC coloring book through build, preflight (twice) and produce.

    python tests/coloring_benchmark.py WORK_DIR [--drawings 150]

Writes a book of full-size synthetic line art (2175 x 2925 px, blank backs) into
WORK_DIR/book, then, in this one process as `book produce` and Studio do: builds the
interior, preflights it twice, and produces into WORK_DIR/release. Prints seconds per
step and the process's peak memory as JSON. Compare runs on one machine and day only.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coloring_helpers import FULL_SIZE, composed_coloring_book  # noqa: E402


def peak_memory_mb() -> float | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
            process, ctypes.byref(counters), counters.cb
        )
        return round(counters.PeakWorkingSetSize / 2**20, 1) if ok else None
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (2**20 if sys.platform == "darwin" else 2**10), 1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("work")
    parser.add_argument("--drawings", type=int, default=150)
    args = parser.parse_args(argv)
    work = Path(args.work)
    book = work / "book"
    if not book.exists():
        composed_coloring_book(book, args.drawings, size=FULL_SIZE)

    from puzzlepress.interior import DEFAULT_PROFILE, build_interior, print_profile, write_interior
    from puzzlepress.preflight import preflight_interior, read_interior_artifacts
    from puzzlepress.production.produce import produce
    from puzzlepress.project import load_project

    project = load_project(book).project
    spec = print_profile(DEFAULT_PROFILE)
    times: dict[str, float] = {}
    start = time.perf_counter()
    build = build_interior(project, spec, book)  # type: ignore[arg-type]
    write_interior(build, work / "interior", book)
    times["build"] = time.perf_counter() - start
    for name in ("first_preflight", "second_preflight"):
        start = time.perf_counter()
        preflight_interior(
            project, read_interior_artifacts(work / "interior"), source_directory=book
        )
        times[name] = time.perf_counter() - start
    start = time.perf_counter()
    result = produce(book, work / "release")
    times["produce"] = time.perf_counter() - start
    print(
        json.dumps(
            {
                "drawings": args.drawings,
                "pages": len(build.layout.pages),
                "seconds": {k: round(v, 1) for k, v in times.items()},
                "peak_memory_mb": peak_memory_mb(),
                "produce_blocking": len(result.validation.blocking),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
