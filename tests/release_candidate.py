"""Build the coloring-book release-candidate demonstration (Interval 10).

    python tests/release_candidate.py APPROVED_JSON ORIGINALS_DIR OUTPUT_DIR

A technical demonstration of the whole pipeline on real artwork, NOT a book for sale:
the only artwork with a recorded rights basis here is the historical set approved
for testing (docs/artwork-validation/approved.json, "not for publication or sale").

1. `tests/proof_project.py` builds the NOT FOR SALE coloring project from the
   SHA-256-verified originals (sections, dividers, sources page, front-photo cover).
2. A publishing section is added with only factual, non-attesting values. Every
   decision that belongs to the author stays undecided: AI disclosure (`unknown`),
   content rights (`undecided`), ISBN, attestations, categories. Nothing is invented.
3. Two copies are produced through Studio's HTTP API, the same requests the Produce
   page makes, with the job running in its worker process:
   - `standard/`: `paperback-8.5x11`;
   - `bleed/`: `paperback-8.5x11-bleed`, page numbers off on artwork pages, the
     automotive and machine patent drawings filling their pages.
4. `summary.json` and `summary.md` record each release: status, files, blocking
   findings, warnings, manual review and what blocks KDP submission.

The publishing package (`publishing/`) is written only when readiness passes, which
it cannot until the author decides; that is the expected, honest outcome. Nothing is
uploaded, ordered or submitted.
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

FILL = ("01-libbey-automobile.jpg", "02-lose-one-wheel.jpg", "06-otis-elevator.jpg")
DESCRIPTION = (
    "A technical demonstration of PuzzlePress coloring-book production, not a book "
    "for sale: historical patent drawings, botanical plates, ornament and engravings, "
    "each on its own right-hand page with a blank back, grouped in sections with an "
    "artwork sources page."
)


def _publishing(project_data: dict) -> dict:
    """Factual values only; every author decision undecided."""
    return {
        "version": 2,
        "description": DESCRIPTION,
        "keywords": [],
        "categories": [],
        "contributors": [],
        "edition": 1,
        "isbn": {"mode": "undecided", "value": None},
        "low_content": None,
        "series": None,
        "notes": "Technical demonstration; not for publication or sale.",
        "audience": {"reading_age": {"minimum": None, "maximum": None}, "sexually_explicit": None},
        "ai_disclosure": {"text": "unknown", "images": "unknown", "translations": "unknown"},
        "content_rights": {
            "interior_artwork": "undecided",
            "cover_artwork": "undecided",
            "text": "undecided",
        },
        "attestations": {"rights": None, "ai_disclosure": None, "metadata": None, "isbn": None},
    }


def _edit(book: Path, change) -> None:  # type: ignore[no-untyped-def]
    from puzzlepress import load_project, validate_project
    from puzzlepress.source_store import replace_source, source_revision

    path = book / "book.yaml"
    data = load_project(book).project.to_dict()
    change(data)
    result = validate_project(data)
    if result.project is None:
        raise SystemExit("; ".join(f"{i.path}: {i.code} {i.message}" for i in result.issues))
    replace_source(path, result.project, source_revision(path))


def _produce(library: Path, frontend: Path, key: str) -> dict:
    from fastapi.testclient import TestClient

    from puzzlepress.studio.server import create_app

    client = TestClient(create_app(library, frontend))
    revision = client.get(f"/api/projects/{key}").json()["revision"]
    started = client.post(f"/api/projects/{key}/produce", json={"revision": revision})
    if started.status_code != 200:
        raise SystemExit(started.text)
    while True:
        job = client.get(f"/api/projects/{key}/produce/job").json()["run"]
        if job["state"] in {"completed", "failed", "cancelled", "interrupted"}:
            break
        time.sleep(1)
    return client.get(f"/api/projects/{key}/produce").json()


def build(approved: Path, originals: Path, output: Path) -> Path:
    from proof_project import build as build_proof

    output.mkdir(parents=True, exist_ok=True)
    source_book = build_proof(approved, originals, output / "proof-source") / "book"
    frontend = output / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    summary: dict[str, object] = {
        "kind": "puzzlepress-release-candidate-demo",
        "status": "technical demonstration; not for publication or sale",
        "artwork": "historical drawings approved for testing only (approved.json)",
        "variants": {},
    }
    for variant, profile in (("standard", "paperback-8.5x11"), ("bleed", "paperback-8.5x11-bleed")):
        library = output / variant
        if library.exists():
            shutil.rmtree(library)
        library.mkdir(parents=True)
        book = library / "demo"
        shutil.copytree(source_book, book)
        release = f"../../{variant}-build/demo"

        def change(data: dict, profile: str = profile, release: str = release) -> None:
            data["output"] = {"directory": release}
            data["print"] = {"profile": profile}
            data["publishing"] = _publishing(data)
            if profile.endswith("-bleed"):
                data["composition"]["page_numbers"]["show_artwork"] = False
                files = {a["id"]: a["path"] for a in data["coloring"]["artwork"]}
                for page in data["coloring"]["pages"]:
                    path = files.get(page.get("artwork", ""), "")
                    if any(Path(name).stem in path for name in FILL):
                        page["placement"] = {"fit": "fill"}

        _edit(book, change)
        status = _produce(library, frontend, "demo")
        release_info = status["release"] or {}
        validation = release_info.get("validation") or {}
        summary["variants"][variant] = {  # type: ignore[index]
            "profile": profile,
            "job": status["run"]["state"],
            "outcome": status["run"].get("outcome"),
            "release_verified": release_info.get("verified"),
            "release_status": (release_info.get("result") or {}).get("status"),
            "files": [f["name"] for f in release_info.get("files", [])],
            "blocking": validation.get("blocking", []),
            "warnings": validation.get("warnings", []),
            "manual_review": validation.get("manual_review", []),
            "release_directory": str((library / release).resolve()),
        }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# Release-candidate demonstration", "", str(summary["status"]), ""]
    for variant, data in summary["variants"].items():  # type: ignore[attr-defined]
        lines += [
            f"## {variant} ({data['profile']})",
            "",
            f"Job {data['job']} ({data['outcome']}); release verified: {data['release_verified']};"
            f" status {data['release_status']}.",
            "",
            f"Blocking ({len(data['blocking'])}):",
            *[f"- [{i['source']}] {i['code']}: {i['message']}" for i in data["blocking"]],
            "",
        ]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output / "summary.json"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("approved", type=Path)
    parser.add_argument("originals", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    print(build(args.approved, args.originals, args.output))


if __name__ == "__main__":
    main()
