"""Pinned outputs of every demo book, recorded from the engine before a refactor.

`collect()` copies each book into a scratch directory and runs the real CLI
in-process: identity, `book plan --json`, interior build and preflight, cover
build and preflight, publishing validate/inspect, `book produce`, and the
standalone generator. It records each command's exit code, the SHA-256 of its
stdout and stderr, and the SHA-256 of every file it wrote.

One normalization only: the human-readable commands print the absolute paths they
read and wrote, so in stdout/stderr each path under the scratch root becomes
`<scratch>/...` with `/` separators. Nothing else is touched: baseline version 1
also turned every backslash into `/` on Windows, which corrupted JSON escapes such
as `\n` and made those digests platform-dependent (found by Linux CI). Written
files are hashed as produced, so an absolute path or time in them, or in JSON
stdout, shows up as instability between two runs.

Baseline version 3 records which zlib family compressed the pinned PDFs (classic
zlib 1.3.1, Python 3.13 on Windows); the pinned values are version 2's, unchanged.

Write the baseline (only from an unchanged engine):
    python tests/golden_baseline.py --write
Check two fresh runs agree without writing:
    python tests/golden_baseline.py --check-determinism
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import zlib
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "fixtures" / "golden" / "baseline.json"
BASELINE_VERSION = 3

# (name, source folder; None writes the synthetic production book)
BOOKS = (
    ("legacy-automotive", ROOT / "tests" / "fixtures" / "legacy-automotive"),
    ("garden-demo", ROOT / "books" / "garden-demo"),
    ("composition-demo", ROOT / "books" / "composition-demo"),
    ("cover-demo", ROOT / "books" / "cover-demo"),
    ("publishing-demo", ROOT / "books" / "publishing-demo"),
    ("synthetic-production", None),
)

# Values that depend only on the engine and the authored source. Everything else
# (PDF bytes, interior/cover identities, reports that embed them) also depends on
# the library versions recorded under `toolchain`.
SOURCE_ONLY = ("build_identity", "validate", "plan", "batch", "generate")
# What writes the PDF files: ReportLab draws them, Pillow encodes their images,
# PyYAML reads the source and Python's zlib compresses every stream. pypdf only
# reads them back (for reports), so a pypdf release cannot change PDF bytes but may
# change report bytes.
PDF_WRITERS = ("reportlab", "pillow", "PyYAML", "zlib")


def zlib_family() -> str:
    """Which deflate implementation Python links. Python 3.14's Windows builds ship
    zlib-ng, which compresses identical input to different (valid) bytes than classic
    zlib; Linux builds use the system's classic zlib. Classic zlib releases share one
    deflate output, so the family, not the release, is what the bytes depend on."""
    return "zlib-ng" if "zlib-ng" in zlib.ZLIB_RUNTIME_VERSION else "zlib"


def toolchain() -> dict[str, str]:
    versions = {name: version(name) for name in ("reportlab", "pillow", "pypdf", "PyYAML")}
    return {**versions, "zlib": zlib_family()}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SCRATCH: list[str] = []


def _text(value: str) -> bytes:
    for root in _SCRATCH:
        value = re.sub(
            re.escape(root) + r"[^\s\"'()<>|]*",
            lambda match, root=root: "<scratch>" + match[0][len(root) :].replace("\\", "/"),
            value,
        )
    return value.encode("utf-8")


def _run(argv: list[str]) -> dict[str, object]:
    from puzzlepress.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return {
        "exit": code,
        "stdout_sha256": _digest(_text(out.getvalue())),
        "stderr_sha256": _digest(_text(err.getvalue())),
    }


def _files(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): _digest(path.read_bytes())
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _book(name: str, source: Path, scratch: Path) -> dict[str, object]:
    from puzzlepress import load_project
    from puzzlepress.identity import build_identity

    project = load_project(source).project
    record: dict[str, object] = {
        "build_identity": build_identity(project),
        "validate": _run(["validate", str(source)]),
    }
    if project.word_search is not None:
        record["batch"] = _run(["puzzle", "batch", str(source), "--json"])
    if project.composition is None:
        return record
    record["plan"] = _run(["book", "plan", str(source), "--json"])
    out = scratch / "out" / name
    record["interior_build"] = _run(["book", "build", str(source), "--output", str(out)])
    record["interior_preflight"] = _run(
        ["book", "preflight", str(source), "--output", str(out), "--json", "--no-write"]
    )
    if project.cover is not None:
        record["cover_build"] = _run(["cover", "build", str(source), "--output", str(out)])
        record["cover_preflight"] = _run(
            ["cover", "preflight", str(source), "--output", str(out), "--json", "--no-write"]
        )
    if project.publishing is not None:
        record["publish_validate"] = _run(["publish", "validate", str(source), "--json"])
        record["publish_inspect"] = _run(
            ["publish", "inspect", str(source), "--output", str(out), "--json"]
        )
    record["interior_files"] = _files(out)
    produced = scratch / "produce" / name
    record["produce"] = _run(["book", "produce", str(source), "--output", str(produced)])
    record["produce_files"] = _files(produced)
    return record


def collect() -> dict[str, object]:
    sys.path.insert(0, str(ROOT / "tests"))
    from production_book import write_production_book

    books: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="pp-golden-") as temporary:
        scratch = Path(temporary).resolve()
        _SCRATCH[:] = [str(scratch), temporary]
        for name, folder in BOOKS:
            source = scratch / "books" / name
            if folder is None:
                write_production_book(source)
            else:
                shutil.copytree(folder, source)
            books[name] = _book(name, source, scratch)
    generate = _run(
        ["puzzle", "generate", "--width", "10", "--height", "8", "--seed", "2026"]
        + ["--word", "ENGINE", "--word", "PISTON", "--solution"]
    )
    return {
        "baseline_version": BASELINE_VERSION,
        "toolchain": toolchain(),
        "generate": generate,
        "books": books,
    }


def encode(data: dict[str, object]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check-determinism", action="store_true")
    action.add_argument("--print", action="store_true")
    args = parser.parse_args()
    first = encode(collect())
    if args.print:
        sys.stdout.write(first.decode("utf-8"))
        return 0
    if args.check_determinism:
        second = encode(collect())
        print("deterministic" if first == second else "NONDETERMINISTIC")
        return 0 if first == second else 1
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_bytes(first)
    print(f"wrote {BASELINE.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
