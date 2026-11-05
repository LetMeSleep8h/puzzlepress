"""Download the approved real-artwork originals again, verified (run by the author).

    python tests/artwork_fetch.py docs/artwork-validation/approved.json ORIGINALS_DIR

For each entry, in order, one at a time: skip a file already in ORIGINALS_DIR with the
recorded byte count and SHA-256; refuse (and leave alone) one that differs; otherwise
download `source_url` to a temporary file, check its byte count and SHA-256 against
the manifest, and only then move it into place. A mismatch is reported and the
download discarded: no other image is ever kept in its place. Waits between requests
and honours Retry-After (Wikimedia rate-limits). ORIGINALS_DIR must be outside this
repository: real artwork never enters the engine's tree. Nothing here runs in tests
or CI; it contacts only the URLs the manifest records.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAUSE = 5.0  # Seconds between downloads.
USER_AGENT = "PuzzlePress-artwork-review/1.0 (local verification of approved originals)"


def _download(url: str, attempts: int = 4) -> bytes:
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                return bytes(response.read())
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == attempts - 1:
                raise
            wait = float(error.headers.get("Retry-After") or 30)
            print(f"  rate-limited; waiting {wait:g} s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch(manifest: Path, folder: Path) -> int:
    folder = folder.resolve()
    if folder.is_relative_to(ROOT):
        raise SystemExit("ORIGINALS_DIR must be outside the repository.")
    folder.mkdir(parents=True, exist_ok=True)
    entries = json.loads(manifest.read_text(encoding="utf-8"))["artworks"]
    failures = 0
    for entry in entries:
        name, size, digest = str(entry["file"]), int(entry["bytes"]), str(entry["sha256"])
        target = folder / name
        if target.exists():
            data = target.read_bytes()
            if len(data) == size and hashlib.sha256(data).hexdigest() == digest:
                print(f"ok (already present): {name}")
                continue
            print(f"REFUSED: {name} exists with other bytes; left untouched", file=sys.stderr)
            failures += 1
            continue
        try:
            data = _download(str(entry["source_url"]))
        except (urllib.error.URLError, OSError) as error:
            print(f"FAILED: {name}: {error}", file=sys.stderr)
            failures += 1
            continue
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            print(
                f"MISMATCH: {name}: the source now serves other bytes; discarded", file=sys.stderr
            )
            failures += 1
            continue
        handle, staged = tempfile.mkstemp(prefix=".fetch-", dir=folder)
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(staged, target)
        print(f"ok: {name} ({size} bytes, SHA-256 verified)")
        time.sleep(PAUSE)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    return 1 if fetch(args.manifest, args.folder) else 0


if __name__ == "__main__":
    sys.exit(main())
