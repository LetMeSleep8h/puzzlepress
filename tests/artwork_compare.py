"""Compare a review's measures with Interval 7's recorded ones (same verified files).

    python tests/artwork_compare.py REVIEW_DIR [RECORD]

REVIEW_DIR is an `artwork_review.py` output made with `--manifest` and the same
settings as the record (default: docs/artwork-validation/interval7-cleanup-measures.json,
cleanup 0.6 + despeckle 2). Prints a Markdown table: fine lines kept and light strokes
kept, then and now, and the line-loss findings now. Digital evidence only: whether a
change is right is settled by a person at 100 % and by the printed proof.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs" / "artwork-validation" / "interval7-cleanup-measures.json"
LINE_LOSS = ("thin_lines_destroyed", "thin_lines_lost", "detail_lost", "faint_strokes_erased")


def _pct(value: object) -> str:
    return f"{float(value):.0%}" if isinstance(value, int | float) else "n/a"


def compare(review: Path, record: Path = RECORD) -> str:
    then = json.loads(record.read_text(encoding="utf-8"))
    rows = [
        "| Drawing | Fine lines kept (then -> now) | Light strokes kept (then -> now) | "
        "Line-loss findings now |",
        "| --- | --- | --- | --- |",
    ]
    for name, old in sorted(then["drawings"].items()):
        path = review / Path(name).stem / "measures.json"
        if not path.is_file():
            rows.append(f"| {name} | {_pct(old['thin_kept'])} -> not reviewed | | |")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if "refused" in data:
            rows.append(f"| {name} | refused: {data['refused']['code']} | | |")
            continue
        settings = data["adjustments"]
        for key, value in then["settings"].items():
            if settings.get(key) != value:
                raise SystemExit(f"{path}: reviewed with {key}={settings.get(key)}, not {value}.")
        measures = data["preparation"]["measures"]
        codes = sorted(
            {f["code"] for f in data["preparation"]["findings"] if f["code"] in LINE_LOSS}
        )
        rows.append(
            f"| {name} | {_pct(old['thin_kept'])} -> {_pct(measures['thin_line_retention'])} | "
            f"{_pct(old['light_kept'])} -> {_pct(measures['faint_line_retention'])} | "
            f"{', '.join(codes) or 'none'} |"
        )
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("review", type=Path)
    parser.add_argument("record", type=Path, nargs="?", default=RECORD)
    args = parser.parse_args(argv)
    sys.stdout.write(compare(args.review, args.record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
