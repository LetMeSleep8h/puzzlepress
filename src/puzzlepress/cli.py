"""Terminal presentation only; all project behavior lives in reusable APIs."""

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .book_cli import add_book_command, run_book_command
from .coloring.issues import ArtworkError
from .coloring_cli import add_coloring_command, run_coloring_command
from .cover_cli import add_cover_command, run_cover_command
from .engines.kind import LABELS
from .identity import build_identity
from .planning_cli import add_plan_command, run_plan_command
from .project import load_project
from .publish_cli import add_publish_command, run_publish_command
from .puzzle_cli import add_puzzle_command, run_puzzle_command
from .validation import ProjectError
from .wordsearch import WordSearchError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="puzzlepress",
        description="Plan books, validate projects, generate word searches, build interiors "
        "and covers, and prepare KDP publishing packages.",
    )
    parser.add_argument("--version", action="version", version=f"PuzzlePress {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "Validate a book project"),
        ("inspect", "Show normalized project and build identity"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("project", help="YAML file or directory containing book.yaml")
    add_puzzle_command(commands)
    add_book_command(commands)
    add_cover_command(commands)
    add_publish_command(commands)
    add_plan_command(commands)
    add_coloring_command(commands)
    args = parser.parse_args(argv)
    try:
        if args.command == "coloring":
            return run_coloring_command(args)
        if args.command == "puzzle":
            return run_puzzle_command(args)
        if args.command == "book":
            return run_book_command(args)
        if args.command == "cover":
            return run_cover_command(args)
        if args.command == "publish":
            return run_publish_command(args)
        if args.command == "plan":
            return run_plan_command(args)
        loaded = load_project(args.project)
    except ArtworkError as error:
        print(f"{error.subject or 'artwork'} [{error.code}]: {error.message}", file=sys.stderr)
        return 1
    except (ProjectError, WordSearchError) as error:
        for issue in error.issues:
            location = f" (line {issue.line}, column {issue.column})" if issue.line else ""
            print(
                f"{issue.path or 'project'} [{issue.code}]{location}: {issue.message}",
                file=sys.stderr,
            )
        return 1
    project = loaded.project
    if args.command == "validate":
        print(f"Valid: {project.book.id} ({loaded.source_path})")
    else:
        content: tuple[tuple[str, object], ...] = (
            (
                ("Artwork", len(project.coloring.artwork)),
                ("Coloring pages", len(project.coloring.pages)),
            )
            if project.coloring is not None
            else (
                ("Content items", len(project.content.items)),
                (
                    "Puzzle definitions",
                    len(project.word_search.puzzles) if project.word_search else 0,
                ),
            )
        )
        for label, value in (
            ("Book ID", project.book.id),
            ("Title", project.book.title),
            ("Schema version", project.schema_version),
            ("Engine", f"{project.engine.value} ({LABELS[project.engine]})"),
            ("Language", project.book.language),
            ("Seed", project.build.seed),
            *content,
            ("Build identity", build_identity(project)),
            ("Source", loaded.source_path),
            ("Output directory", loaded.output_directory),
        ):
            print(f"{label}: {value}")
    return 0
