"""Repeatable review of line art against the preparation and coloring preflight checks.

    python tests/artwork_review.py INPUT_DIR OUTPUT_DIR [--set key=value ...]
    python tests/artwork_review.py --synthetic OUTPUT_DIR

For every PNG or JPEG directly in INPUT_DIR (read only; never written, moved or
renamed) it writes, under OUTPUT_DIR:

- `<name>/original.png`, `prepared.png`, `difference.png` at full resolution (red:
  ink removed, blue: ink added, orange: light strokes erased);
- `<name>/measures.json`: inspection facts and findings, preparation measures and
  findings, and the thresholds they were judged against;
- `print/interior.pdf` and `print/preflight.json`: every drawing on its own page at
  8.5 x 11 in, through the same build and coloring preflight as a real book (a
  scratch book in `book/` holds copies of the files);
- `review.md`: one row per drawing with the measured values, and the fields only a
  person can fill in (source and licence, what the eye sees at 100 %, what a printed
  proof shows), all "not recorded" until someone records them.

Nothing here decides whether a drawing is good, licensed or printable: it measures
and lays out evidence. `--synthetic` writes the SYNTHETIC cases from
tests/coloring_helpers.py into OUTPUT_DIR/inputs and reviews those, to exercise the
harness; their results say nothing about real artwork.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from puzzlepress.coloring import prepare  # noqa: E402
from puzzlepress.coloring.inspection import inspect_artwork  # noqa: E402
from puzzlepress.coloring.issues import ArtworkError  # noqa: E402
from puzzlepress.coloring.library import import_files  # noqa: E402
from puzzlepress.coloring_validation import validate_adjustments  # noqa: E402
from puzzlepress.creation import NewProject, create_project  # noqa: E402

SUFFIXES = {".png", ".jpg", ".jpeg"}
NOT_RECORDED = "not recorded"
THRESHOLDS = {
    # Every value below was set on SYNTHETIC drawings (docs/coloring.md, Calibration);
    # none has been checked against real artwork or a printed proof.
    "thin_line_warning": prepare.THIN_WARNING,
    "thin_line_blocking": prepare.THIN_BLOCKING,
    "detail_warning": prepare.DETAIL_WARNING,
    "heavy_ink_warning": prepare.HEAVY_INK_WARNING,
    "heavy_ink_blocking": prepare.HEAVY_INK_BLOCKING,
    "paper_warning_level": prepare.PAPER_WARNING,
    "specks_per_megapixel_warning": prepare.SPECKS_PER_MP_WARNING,
    "faint_core_level": prepare.FAINT_CORE,
    "faint_erased_share": prepare.FAINT_ERASED,
    "mean_change_review": prepare.CHANGE_REVIEW,
}


def synthetic_inputs(folder: Path) -> None:
    """The SYNTHETIC review cases: stand-ins for the kinds real artwork should cover."""
    from coloring_helpers import (
        dense_pattern,
        encode,
        fine_detail,
        light_colored_lines,
        line_art,
        noisy_scan,
        pencil_sketch,
    )

    folder.mkdir(parents=True, exist_ok=False)
    cases = {
        "synthetic-outline": line_art(3),
        "synthetic-fine-detail": fine_detail(),
        "synthetic-dense-pattern": dense_pattern(),
        "synthetic-pencil": pencil_sketch(2),
        "synthetic-noisy-scan": noisy_scan(4),
        "synthetic-light-colored-lines": light_colored_lines(5),
    }
    for name, image in cases.items():
        (folder / f"{name}.png").write_bytes(encode(image))


def _settings(pairs: list[str]) -> dict[str, object]:
    values: dict[str, object] = {}
    for pair in pairs:
        key, _, raw = pair.partition("=")
        values[key] = json.loads(raw) if raw not in ("", "none") else None
    return values


def _ratio(value: object) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"  # type: ignore[arg-type]


def review(inputs: Path, output: Path, settings: dict[str, object]) -> Path:
    inputs, output = inputs.resolve(), output.resolve()
    if output.is_relative_to(inputs) or inputs.is_relative_to(output):
        raise SystemExit("OUTPUT_DIR must be outside INPUT_DIR (and not contain it).")
    files = sorted(p for p in inputs.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)
    if not files:
        raise SystemExit(f"No PNG or JPEG files directly in {inputs}.")
    adjustments, issues = validate_adjustments(settings)
    if adjustments is None:
        raise SystemExit("; ".join(f"{i.path}: {i.message}" for i in issues))
    output.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    imported: list[tuple[str, bytes]] = []
    for path in files:
        data = path.read_bytes()
        folder = output / path.stem
        folder.mkdir(exist_ok=True)
        record: dict[str, object] = {
            "file": path.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "adjustments": adjustments.to_dict(),
            "thresholds": THRESHOLDS,
            "evidence": "measured by PuzzlePress; no human review recorded",
        }
        try:
            inspection = inspect_artwork(data, path.name)
            prepared = prepare.prepare_artwork(data, adjustments, path.name)
        except ArtworkError as error:
            record["refused"] = {"code": error.code, "message": str(error)}
            (folder / "measures.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            rows.append(f"| {path.name} | refused: {error.code} | | | | | | | |")
            continue
        imported.append((path.name, data))
        prepared.reference.save(folder / "original.png")
        prepared.image.save(folder / "prepared.png")
        prepare.difference_image(prepared.reference, prepared.image).save(folder / "difference.png")
        record["inspection"] = inspection.to_dict()
        record["preparation"] = prepared.to_dict()
        (folder / "measures.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        m = prepared.measures
        codes = sorted({f.code for f in (*inspection.findings, *prepared.findings)}) or ["none"]
        info = inspection.info
        rows.append(
            f"| {path.name} | {record['sha256'][:12]} | {info.pixels[0]} x {info.pixels[1]} "
            f"| {info.effective_dpi:.0f} | {_ratio(m.thin_line_retention)} "
            f"| {_ratio(m.faint_line_retention)} | {m.specks_per_megapixel_after} "
            f"| {m.paper_level_after} | {', '.join(codes)} |"
        )
    pdf_note = _print_book(output, imported, adjustments.to_dict()) if imported else "none"
    sheet = output / "review.md"
    sheet.write_text(
        "\n".join(
            [
                "# Artwork review",
                "",
                f"Inputs: `{inputs}` (read only). Settings: `{json.dumps(adjustments.to_dict())}`.",
                f"Print-size PDF: {pdf_note}.",
                "",
                "Measured values come from PuzzlePress. The thresholds they were judged",
                "against were calibrated on synthetic drawings only (see measures.json).",
                "Nothing below says a drawing is licensed or prints well until a person",
                "records it.",
                "",
                "| File | SHA-256 | Pixels | DPI at full fit | Thin lines kept | Light strokes "
                "kept | Specks / MP | Paper level | Findings |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
                *rows,
                "",
                "## Human review (fill in; leave 'not recorded' when not done)",
                "",
                "| File | Source and licence | On screen at 100 % | Printed proof | Finding "
                "missed or false |",
                "| --- | --- | --- | --- | --- |",
                *(
                    f"| {p.name} | {NOT_RECORDED} | {NOT_RECORDED} | {NOT_RECORDED} | "
                    f"{NOT_RECORDED} |"
                    for p in files
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return sheet


def _print_book(output: Path, files: list[tuple[str, bytes]], adjustments: dict) -> str:
    """Copies in a scratch book, every drawing on its own page, built and preflighted."""
    from puzzlepress.interior import (
        DEFAULT_PROFILE,
        InteriorError,
        build_interior,
        print_profile,
        write_interior,
    )
    from puzzlepress.interior.build import write_preflight_report
    from puzzlepress.preflight import preflight_interior, read_interior_artifacts, report_bytes
    from puzzlepress.project import load_project
    from puzzlepress.source_store import replace_source, source_revision
    from puzzlepress.validation import validate_project

    book = output / "book"
    if not book.exists():
        create_project(output, NewProject("coloring", "book", "Artwork review (scratch)"))
        import_files(book, files)
        loaded = load_project(book)
        data = loaded.project.to_dict()
        for artwork in data["coloring"]["artwork"]:  # type: ignore[index]
            artwork["adjustments"] = adjustments
        project = validate_project(data).require_project()
        replace_source(loaded.source_path, project, source_revision(loaded.source_path))
    project = load_project(book).project
    spec = print_profile(DEFAULT_PROFILE)
    folder = output / "print"
    try:
        build = build_interior(project, spec, book)  # type: ignore[arg-type]
    except InteriorError as error:
        return "not built: " + "; ".join(f"{i.code}: {i.message}" for i in error.issues)
    write_interior(build, folder, book)
    result = preflight_interior(
        project, read_interior_artifacts(folder), build, source_directory=book
    )
    write_preflight_report(report_bytes(result.report), project.book.id, folder, book)
    counts: dict[str, int] = {}
    for finding in result.report.findings:
        counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
    return f"`print/interior.pdf` ({len(build.layout.pages)} pages; preflight findings {counts})"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths", nargs="+", help="INPUT_DIR OUTPUT_DIR, or OUTPUT_DIR with --synthetic"
    )
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args(argv)
    if args.synthetic:
        (output,) = (Path(p) for p in args.paths)
        inputs = output / "inputs"
        synthetic_inputs(inputs)
        output = output / "review"
    else:
        inputs, output = (Path(p) for p in args.paths)
    print(review(inputs, output, _settings(args.set)))


if __name__ == "__main__":
    main()
