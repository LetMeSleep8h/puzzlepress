"""Terminal adapter for `book new`: the same creation Studio's New book uses."""

import argparse
from pathlib import Path

from .creation import TEMPLATES, NewProject, create_project
from .print_config import PROFILE_IDS


def add_new_action(actions: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    new = actions.add_parser(
        "new", help="Create a new project folder with a starter book.yaml (never overwrites)"
    )
    new.add_argument("folder", help="The new project folder; its parent must exist")
    new.add_argument("--type", required=True, choices=["word_search", "coloring"])
    new.add_argument("--title", required=True)
    new.add_argument("--language", default="en", help="Language tag (default en)")
    new.add_argument("--subtitle")
    new.add_argument("--author", help="Author or pen name")
    new.add_argument("--subject")
    new.add_argument("--collection")
    new.add_argument("--profile", choices=PROFILE_IDS, help="Print profile (trim and paper)")
    new.add_argument("--template", choices=sorted({t.id for t in TEMPLATES}))


def run_new(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    created = create_project(
        folder.parent,
        NewProject(
            kind=args.type,
            key=folder.name,
            title=args.title,
            language=args.language,
            subtitle=args.subtitle,
            author=args.author,
            subject=args.subject,
            collection=args.collection,
            profile=args.profile,
            template=args.template,
        ),
    )
    if created.recovered:
        print("Cleared an interrupted earlier creation of this folder.")
    print(f"Created {created.path}")
    print(f"Engine: {created.project.engine.value}")
    if created.project.coloring is not None:
        print("No artwork yet: import drawings with `puzzlepress coloring import` or Studio.")
    else:
        print("One starter puzzle is a placeholder: replace it before publishing.")
    return 0
