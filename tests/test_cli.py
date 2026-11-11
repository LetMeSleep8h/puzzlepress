import os
import subprocess
import sys

import pytest

from puzzlepress import __version__, build_identity, load_project
from puzzlepress.cli import main
from tests.helpers import installed_puzzlepress


def run_cli(*args, cwd=None, env=None):
    return subprocess.run(
        [sys.executable, "-m", "puzzlepress", *map(str, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_version():
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout.strip() == f"PuzzlePress {__version__}"
    assert not result.stderr


def test_validate_and_inspect(example_path):
    result = run_cli("validate", example_path.parent)
    assert result.returncode == 0
    assert "Valid: automotive-word-search" in result.stdout
    assert not result.stderr
    result = run_cli("inspect", example_path)
    assert result.returncode == 0
    for expected in (
        "Title: Automotive Word Search",
        "Seed: 2026",
        "Schema version: 1",
        str(example_path),
        build_identity(load_project(example_path).project),
    ):
        assert expected in result.stdout


@pytest.mark.parametrize(
    "source", ["book: [", "schema_version: 7", "schema_version: 1\nbook: {}\nbuild: {}"]
)
def test_configuration_failure_exit_code_and_no_traceback(tmp_path, source):
    path = tmp_path / "book.yaml"
    path.write_text(source, encoding="utf-8")
    result = run_cli("validate", path)
    assert result.returncode == 1
    assert result.stderr
    assert not result.stdout
    assert "Traceback" not in result.stderr


def test_missing_path(tmp_path):
    result = run_cli("inspect", tmp_path / "missing")
    assert result.returncode == 1
    assert "[not_found]" in result.stderr


def test_cli_rejects_source_output_overlap(source, tmp_path):
    path = tmp_path / "book.yaml"
    path.write_text(source.replace("../../build/automotive-word-search", "."), encoding="utf-8")
    before = path.read_bytes()
    result = run_cli("validate", path)
    assert result.returncode == 1
    assert "[source_overlap]" in result.stderr
    assert path.read_bytes() == before


@pytest.mark.parametrize("args", [(), ("build",), ("inspect",)])
def test_usage_failure(args):
    result = run_cli(*args)
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_installed_console_script(example_path):
    result = subprocess.run(
        [str(installed_puzzlepress()), "validate", str(example_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Valid:" in result.stdout


def test_unexpected_programmer_error_is_not_misreported(monkeypatch):
    def broken_loader(path):
        raise RuntimeError("internal defect")

    monkeypatch.setattr("puzzlepress.cli.load_project", broken_loader)
    with pytest.raises(RuntimeError, match="internal defect"):
        main(["validate", "anything"])


def test_puzzle_cli_success_determinism_and_solution(tmp_path):
    width, height = 8, 6
    args = (
        "puzzle",
        "generate",
        "--width",
        width,
        "--height",
        height,
        "--word",
        "QUARTZ",
        "--word",
        "AXLE",
        "--word",
        "FUEL PUMP",
    )

    def generate(seed, hash_seed):
        result = run_cli(
            *args,
            "--seed",
            seed,
            "--solution",
            cwd=tmp_path,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
        )
        assert result.returncode == 0, result.stderr
        assert not result.stderr
        seed_line, grid_size, *body = result.stdout.splitlines()
        assert seed_line == f"Seed: {seed}"
        assert grid_size == f"Grid: {width} x {height}"
        grid = [row.split() for row in body[:height]]
        assert len(grid) == height
        assert all(len(row) == width for row in grid)

        targets, verification, solution, *placements = body[height:]
        assert targets == "Targets: QUARTZ; AXLE; FUEL PUMP"
        assert verification.startswith("Verified:")
        assert solution == "Solution (zero-based column, row):"
        assert [line.strip().split(" (", 1)[0] for line in placements] == [
            "word-1: QUARTZ",
            "word-2: AXLE",
            "word-3: FUELPUMP",
        ]
        return grid, placements

    grid, placements = generate(2026, "1")
    assert generate(2026, "98765") == (grid, placements)
    other_grid, _ = generate(2027, "1")
    assert other_grid != grid

    without_solution = run_cli(*args, "--seed", "2026", cwd=tmp_path)
    assert without_solution.returncode == 0
    assert not without_solution.stderr
    assert "Solution" not in without_solution.stdout


@pytest.mark.parametrize(
    "extra,code",
    [
        (("--word", "A!"), "characters"),
        (("--word", "ABCD"), "cannot_fit"),
        (("--word", "ABC", "--word", "DEF", "--max-restarts", "0"), "search_exhausted"),
        (("--word", "A", "--seed", "-1"), "seed"),
        (("--word", "A", "--seed", "20x6"), "seed"),
        (("--word", "A", "--width", "0"), "range"),
        (("--word", "A", "--word", "a"), "duplicate_search"),
    ],
)
def test_puzzle_cli_expected_failures(extra, code):
    result = run_cli("puzzle", "generate", "--width", "3", "--height", "1", "--seed", "1", *extra)
    assert result.returncode == 1
    assert f"[{code}]" in result.stderr
    assert "Traceback" not in result.stderr
    assert not result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ("puzzle",),
        ("puzzle", "generate"),
        ("puzzle", "generate", "--direction", "sideways"),
        ("puzzle", "generate", "--width", "wide"),
    ],
)
def test_puzzle_cli_usage(args):
    assert run_cli(*args).returncode == 2


def test_puzzle_cli_direction_subset():
    result = run_cli(
        "puzzle",
        "generate",
        "--width",
        "3",
        "--height",
        "1",
        "--seed",
        "0",
        "--word",
        "ABC",
        "--direction",
        "left",
        "--solution",
    )
    assert result.returncode == 0
    assert "C B A" in result.stdout
    assert "(2, 0) -> (0, 0) left" in result.stdout
