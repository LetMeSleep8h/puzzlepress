"""Build a print-validation proof from approved, rights-checked artwork.

    python tests/proof_project.py APPROVED_JSON ORIGINALS_DIR OUTPUT_DIR

APPROVED_JSON lists each approved file with its provenance and how the proof uses it
(docs/artwork-validation/approved.json). ORIGINALS_DIR holds the downloaded files,
directly (as tests/artwork_fetch.py saves them) or each in a folder named after the
file's stem; they are read, checked against the
SHA-256 recorded in the manifest, copied into a new book and never written.

OUTPUT_DIR receives:

- `book/`: a coloring project created through `puzzlepress.creation`, holding copies
  of the included drawings, their recorded preparation settings and placements,
  section dividers, an "Artwork sources" page and a front-photo cover made from one
  approved drawing; titled and labelled NOT FOR SALE;
- `proof/`: interior.pdf, interior.json, preflight.json, cover.pdf, cover.json,
  cover-preflight.json, built and checked by the same code as `book produce`;
- `sources.json`: every physical page of the interior with the original file's
  SHA-256, source URL, rights basis and open questions, so each printed page traces to
  its source;
- `proof-checklist.md`: the review sheet for the printed copy.

It orders nothing and contacts no one. Ordering a proof is the author's decision.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from puzzlepress import validate_project  # noqa: E402
from puzzlepress.coloring.library import import_files  # noqa: E402
from puzzlepress.cover.assets import import_photo  # noqa: E402
from puzzlepress.creation import NewProject, create_project  # noqa: E402
from puzzlepress.project import load_project  # noqa: E402
from puzzlepress.source_store import replace_source, source_revision  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "docs" / "artwork-validation" / "proof-checklist.md"
TITLE = "PuzzlePress Print Validation Proof"
SUBTITLE = "Not for sale: public-domain test drawings"


def _original(originals: Path, entry: dict) -> bytes:
    # Flat (as tests/artwork_fetch.py saves them) or one folder per file (Interval 7).
    flat = originals / entry["file"]
    path = flat if flat.is_file() else originals / Path(entry["file"]).stem / entry["file"]
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry["sha256"]:
        raise SystemExit(f"{entry['file']}: SHA-256 {digest} differs from the manifest.")
    return data


def build(approved: Path, originals: Path, output: Path) -> Path:
    manifest = json.loads(approved.read_text(encoding="utf-8"))
    included = [e for e in manifest["artworks"] if e.get("proof", {}).get("include")]
    if not included:
        raise SystemExit("No approved artwork is marked for the proof.")
    output.mkdir(parents=True, exist_ok=True)
    created = create_project(
        output,
        NewProject(
            "coloring",
            "book",
            TITLE,
            subtitle=SUBTITLE,
            author="PuzzlePress test material",
            subject="Print validation",
            profile=manifest.get("profile", "paperback-8.5x11"),
        ),
    )
    book = created.path.parent
    imported = import_files(
        book, [(e["file"], _original(originals, e)) for e in included], add_pages=False
    )
    ids = {e["file"]: item.id for e, item in zip(included, imported, strict=True)}

    data = load_project(book).project.to_dict()
    coloring = data["coloring"]
    assert isinstance(coloring, dict)
    by_id = {a["id"]: a for a in coloring["artwork"]}
    pages: list[dict] = []
    section = None
    for entry in included:
        proof = entry["proof"]
        if proof.get("section") != section:
            section = proof.get("section")
            pages.append({"divider": {"title": section}})
        artwork = by_id[ids[entry["file"]]]
        artwork["title"] = entry["short_title"]
        if proof.get("adjustments"):
            artwork["adjustments"] = {**artwork["adjustments"], **proof["adjustments"]}
        page: dict = {"artwork": artwork["id"]}
        if proof.get("placement"):
            page["placement"] = proof["placement"]
        pages.append(page)
    coloring["pages"] = pages
    lines = [
        f"{n}. {e['short_title']}: {e['identifier']}; {e['source_host']}."
        for n, e in enumerate(included, start=1)
    ]
    data["composition"] = {
        "front_matter": [
            {"kind": "title_page"},
            {
                "kind": "copyright_page",
                "text": "Print validation proof made with PuzzlePress. NOT FOR SALE.\n"
                "The drawings were published before 1931 and are used here for testing "
                "only; sources are listed at the back and in sources.json.",
            },
        ],
        "artwork": {"start": "recto"},
        "back_matter": [{"kind": "about", "title": "Artwork sources", "text": "\n".join(lines)}],
        "page_numbers": {
            "scheme": "continuous",
            "show_front_matter": False,
            "show_artwork": True,
            "show_back_matter": True,
        },
    }
    cover_entry = next(e for e in included if e["proof"].get("cover"))
    photo = import_photo(book, _original(originals, cover_entry), cover_entry["file"])
    data["cover"] = {
        "version": 1,
        "layout": "front_photo",
        "image": {"path": photo.path, "sha256": photo.info.sha256},
        "crop": {"x": 0.5, "y": 0.5, "zoom": 1.0},
        "type": {"style": "minimal", "position": "top", "align": "center", "tone": "dark"},
        "legibility": "panel",
        "background": "#f4efe2",
        "spine_text": "auto",
        "back_text": "Print validation proof. NOT FOR SALE. Test drawings from public-domain "
        "sources, chosen to include hard cases: fine lines, faint strokes, dense detail, "
        "tinted paper.",
    }
    project = validate_project(data).require_project()
    replace_source(created.path, project, source_revision(created.path))

    proof = output / "proof"
    _build(book, proof)
    _sources(proof, included, output / "sources.json")
    shutil.copyfile(CHECKLIST, output / "proof-checklist.md")
    return output


def _build(book: Path, proof: Path) -> None:
    from puzzlepress.cover.build import build_cover, write_cover, write_cover_preflight
    from puzzlepress.cover.preflight import preflight_cover
    from puzzlepress.cover.preflight import report_bytes as cover_report_bytes
    from puzzlepress.interior import build_interior, print_profile, write_interior
    from puzzlepress.interior.build import write_preflight_report
    from puzzlepress.preflight import preflight_interior, read_interior_artifacts, report_bytes

    project = load_project(book).project
    assert project.printing is not None
    spec = print_profile(project.printing.profile)
    built = build_interior(project, spec, book)  # type: ignore[arg-type]
    write_interior(built, proof, book)
    result = preflight_interior(
        project, read_interior_artifacts(proof), built, source_directory=book
    )
    write_preflight_report(report_bytes(result.report), project.book.id, proof, book)
    write_cover(build_cover(project, book, proof), proof, book)
    cover = preflight_cover(project, book, proof)
    write_cover_preflight(cover_report_bytes(cover), project.book.id, proof, book)


def _sources(proof: Path, included: list[dict], target: Path) -> None:
    interior = json.loads((proof / "interior.json").read_text(encoding="utf-8"))
    by_sha = {e["sha256"]: e for e in included}
    pages = []
    # interior.json lists each printed drawing: physical page, pixels, placement in
    # inches, effective DPI, prepared digest and the original's SHA-256.
    for record in interior["artwork"]:
        entry = by_sha[record["source_sha256"]]
        pages.append(
            {
                "physical_page": record["page"],
                "file": entry["file"],
                "title": entry["title"],
                "original_sha256": record["source_sha256"],
                "prepared": record["prepared"],
                "effective_dpi": record["effective_dpi"],
                "placement_in": record["placement_in"],
                "source_url": entry["source_url"],
                "rights_basis": entry["rights_basis"],
                "uncertainty": entry["uncertainty"],
            }
        )
    target.write_text(
        json.dumps(
            {
                "proof": "NOT FOR SALE: print validation only",
                "interior_pdf_sha256": interior.get("pdf_sha256"),
                "interior_identity": interior.get("interior_identity"),
                "pages": pages,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("approved")
    parser.add_argument("originals")
    parser.add_argument("output")
    args = parser.parse_args()
    print(build(Path(args.approved), Path(args.originals), Path(args.output)))


if __name__ == "__main__":
    main()
