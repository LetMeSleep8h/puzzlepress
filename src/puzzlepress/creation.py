"""Create a new project folder with a starter `book.yaml`, atomically and never over
anything that exists. The CLI (`puzzlepress book new`) and Studio (`POST
/api/projects`) both create books here, so their projects are the same files.

A new book is a folder `<key>` directly inside a parent directory (Studio's book
library). The folder is reserved with an exclusive `mkdir`, marked as being
created, given a `book.yaml` staged, fsynced, read back and moved into place, and
only then unmarked. Discovery ignores a folder without `book.yaml`, so a creation
never shows half a project. A failure removes exactly what this call wrote; an
interrupted creation (a crash) leaves a marked folder holding only the marker and
staged files, which the next creation of the same key recognises and replaces.
Anything else at that path is an existing project and is refused.

Starter content is visible and labelled: a word-search book starts with one
starter puzzle titled as a placeholder (word search needs one puzzle to be a valid
book), a coloring book with no artwork, so it cannot pass readiness until the
author adds drawings. No legal text, declaration or finished-looking filler is
written.
"""

import hashlib
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .catalog_config import Catalog
from .engines.kind import LABELS, EngineKind
from .errors import ProjectError, ValidationIssue
from .models import Project
from .print_config import PROFILE_IDS
from .project import load_project, resolve_output_directory
from .validation import validate_project
from .yaml_io import dump_project

CREATION_MARKER = ".puzzlepress-creating"
STAGED_PREFIX = ".puzzlepress-"
MAX_KEY = 64
KEY_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
RESERVED = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])")
# Relative to the new folder, so output lands beside the library, never inside a book
# (the demos' convention). `resolve_output_directory` still checks disjointness.
OUTPUT_PATTERN = "../../build/{key}"
STARTER_TITLE = "Starter puzzle: replace before publishing"


@dataclass(frozen=True)
class ProjectTemplate:
    id: str
    kind: EngineKind
    label: str
    description: str


TEMPLATES = (
    ProjectTemplate(
        "starter",
        EngineKind.WORD_SEARCH,
        "Starter puzzle",
        "A title page, one placeholder puzzle titled 'Starter puzzle: replace before "
        "publishing' with the words SAMPLE, STARTER, REPLACE and WORDS, and answers at "
        "the back. Replace it with your own puzzles.",
    ),
    ProjectTemplate(
        "simple",
        EngineKind.COLORING,
        "Simple",
        "A title page, then every drawing on a right-hand page with a blank back. No "
        "drawings yet: import artwork next.",
    ),
    ProjectTemplate(
        "with-notes",
        EngineKind.COLORING,
        "Title, instructions and notes",
        "Like Simple, plus a short instructions page you can rewrite and a Notes page at the back.",
    ),
)
DEFAULT_TEMPLATE = {EngineKind.WORD_SEARCH: "starter", EngineKind.COLORING: "simple"}


@dataclass(frozen=True)
class NewProject:
    """What the author asked for. Text is validated by the book schema afterwards."""

    kind: str
    key: str
    title: str
    language: str = "en"
    subtitle: str | None = None
    author: str | None = None
    subject: str | None = None
    collection: str | None = None
    profile: str | None = None  # None: no print section (the default profile applies).
    template: str | None = None


@dataclass(frozen=True)
class CreatedProject:
    path: Path  # The new book.yaml.
    project: Project
    revision: str
    recovered: bool  # An interrupted earlier creation of this key was cleared first.


def _issue(path: str, code: str, message: str) -> ProjectError:
    return ProjectError((ValidationIssue(path, code, message),))


def suggest_key(title: str) -> str:
    """A folder name from a title: lowercase ASCII words joined by hyphens."""
    words = re.findall(r"[a-z0-9]+", title.lower())
    key = "-".join(words)[:MAX_KEY].strip("-")
    return key or "new-book"


def check_key(key: str) -> None:
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key) or len(key) > MAX_KEY:
        raise _issue(
            "key",
            "invalid_key",
            f"Use 1..{MAX_KEY} lowercase letters and digits separated by single hyphens, "
            "such as woodland-coloring. Paths, dots and spaces are not allowed.",
        )
    if RESERVED.fullmatch(key):
        raise _issue("key", "reserved", "This name is reserved on Windows; choose another.")


def starter_source(request: NewProject) -> dict[str, object]:
    """The starter `book.yaml` mapping for a request (not yet validated)."""
    try:
        kind = EngineKind(request.kind)
    except ValueError:
        raise _issue(
            "kind", "unsupported_type", f"Choose one of: {', '.join(k.value for k in EngineKind)}."
        ) from None
    template = request.template or DEFAULT_TEMPLATE[kind]
    if not any(t.id == template and t.kind is kind for t in TEMPLATES):
        raise _issue(
            "template",
            "unknown_template",
            f"No {LABELS[kind].lower()} template named {template!r}.",
        )
    if request.profile is not None and request.profile not in PROFILE_IDS:
        raise _issue(
            "profile",
            "unsupported_profile",
            f"Unknown print profile. Supported: {', '.join(PROFILE_IDS)}.",
        )
    book: dict[str, object] = {"id": request.key, "title": request.title}
    for field in ("subtitle", "author"):
        value = getattr(request, field)
        if value is not None and str(value).strip():
            book[field] = value
    book["language"] = request.language
    source: dict[str, object] = {
        "schema_version": 1,
        "book": book,
        # An explicit seed, written out: derived from the key, so it is reproducible.
        "build": {"seed": int(hashlib.sha256(request.key.encode()).hexdigest()[:12], 16)},
        "output": {"directory": OUTPUT_PATTERN.format(key=request.key)},
    }
    numbers: dict[str, object] = {
        "scheme": "continuous",
        "show_front_matter": False,
        "show_back_matter": True,
    }
    if kind is EngineKind.WORD_SEARCH:
        words = ("SAMPLE", "STARTER", "REPLACE", "WORDS")
        source["word_search"] = {
            "banks": [
                {
                    "id": "starter-words",
                    "entries": [{"id": w.lower(), "display": w} for w in words],
                }
            ],
            "profiles": [
                {"id": "starter", "width": 10, "height": 10, "directions": ["right", "down"]}
            ],
            "puzzles": [
                {
                    "id": "starter-puzzle",
                    "title": STARTER_TITLE,
                    "theme": "Starter",
                    "bank": "starter-words",
                    "target_ids": [w.lower() for w in words],
                    "difficulty": "starter",
                }
            ],
        }
        source["composition"] = {
            "front_matter": [{"kind": "title_page"}],
            "puzzles": {"start": "any"},
            "solutions": {"placement": "end", "title": "Solutions", "start": "any"},
            "back_matter": [],
            "page_numbers": numbers | {"show_solutions": True},
        }
    else:
        source["coloring"] = {"version": 1}
        front: list[dict[str, object]] = [{"kind": "title_page"}]
        back: list[dict[str, object]] = []
        if template == "with-notes":
            front.append(
                {
                    "kind": "instructions",
                    "title": "How to Use This Book",
                    "text": "Color each drawing however you like.",
                }
            )
            back.append({"kind": "notes", "title": "Notes"})
        source["composition"] = {
            "front_matter": front,
            "artwork": {"start": "recto"},
            "back_matter": back,
            "page_numbers": numbers | {"show_artwork": True},
        }
    catalog = Catalog(
        (request.subject or "").strip() or None, (request.collection or "").strip() or None
    )
    if catalog.to_dict():
        source["catalog"] = catalog.to_dict()
    if request.profile is not None:
        source["print"] = {"profile": request.profile}
    return source


def _staged_name(name: str) -> bool:
    return name == CREATION_MARKER or (name.startswith(STAGED_PREFIX) and name.endswith(".tmp"))


def interrupted(folder: Path) -> bool:
    """True when `folder` is what an interrupted creation leaves: a real directory
    (not a link) holding the creation marker and nothing but staged files."""
    try:
        if folder.is_symlink() or not folder.is_dir():
            return False
        entries = list(os.scandir(folder))
        return any(e.name == CREATION_MARKER for e in entries) and all(
            _staged_name(e.name) and e.is_file(follow_symlinks=False) for e in entries
        )
    except OSError:
        return False


def _clear(folder: Path) -> None:
    """Remove an interrupted creation: only its marker and staged files, then the
    folder. Rechecked immediately before; anything else stops the removal."""
    if not interrupted(folder):
        raise _issue("key", "project_exists", "A project folder with this name already exists.")
    for entry in os.scandir(folder):
        if not (_staged_name(entry.name) and entry.is_file(follow_symlinks=False)):
            raise _issue("key", "project_exists", "A project folder with this name exists.")
        os.unlink(entry.path)
    folder.rmdir()


def create_project(parent: str | Path, request: NewProject) -> CreatedProject:
    """Create `parent/<key>/book.yaml`. Raises ProjectError for every expected failure."""
    check_key(request.key)
    source = starter_source(request)
    project = validate_project(source).require_project()
    try:
        root = Path(parent).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _issue(
            "parent", "library_unavailable", "The book library folder is unavailable."
        ) from error
    if not root.is_dir():
        raise _issue("parent", "library_unavailable", "The book library is not a folder.")
    folder = root / request.key
    if folder.resolve().parent != root:
        raise _issue("key", "invalid_key", "The project folder must be directly in the library.")
    resolve_output_directory(project, folder)  # Disjoint from the new folder (not created).
    recovered = False
    if os.path.lexists(folder) and interrupted(folder):
        _clear(folder)
        recovered = True
    try:
        folder.mkdir()
    except FileExistsError:
        raise _issue(
            "key", "project_exists", f"A project folder named {request.key!r} already exists."
        ) from None
    except OSError as error:
        raise _issue("key", "create_failed", f"Could not create the folder: {error}") from error
    marker = folder / CREATION_MARKER
    staged: Path | None = None
    target = folder / "book.yaml"
    try:
        token = secrets.token_hex(8)
        marker.write_text(json.dumps({"creation_version": 1, "token": token}), encoding="utf-8")
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=STAGED_PREFIX, suffix=".tmp", dir=folder, delete=False
        ) as stream:
            staged = Path(stream.name)
            stream.write(dump_project(project).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if load_project(staged).project != project:
            raise RuntimeError("Serialized starter source failed round-trip verification")
        # The folder is ours (exclusive mkdir); book.yaml cannot have appeared in it
        # unless something else writes here, which is refused rather than replaced.
        if os.path.lexists(target):
            raise _issue("key", "project_exists", "book.yaml appeared while creating.")
        os.replace(staged, target)
        staged = None
        marker.unlink()
        loaded = load_project(target)
        if loaded.project != project:
            raise _issue("book.yaml", "save_unconfirmed", "book.yaml reads back differently.")
        raw = target.read_bytes()
        return CreatedProject(
            target, project, "sha256-" + hashlib.sha256(raw).hexdigest(), recovered
        )
    except BaseException:
        # Remove exactly what this call wrote: the staged file, book.yaml and the marker.
        for path in (staged, target, marker):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        try:
            folder.rmdir()
        except OSError:
            pass
        raise


def project_types() -> list[dict[str, object]]:
    """The book types a project can be created as, with their templates. Engines that
    PuzzlePress cannot build are not listed here; Studio shows them as unavailable."""
    return [
        {
            "kind": kind.value,
            "label": LABELS[kind],
            "default_template": DEFAULT_TEMPLATE[kind],
            "templates": [
                {"id": t.id, "label": t.label, "description": t.description}
                for t in TEMPLATES
                if t.kind is kind
            ],
        }
        for kind in EngineKind
    ]
