"""Revision-checked, atomic replacement of a project's book.yaml outside Studio.

The same contract as Studio's draft save: validate, serialize canonically (comments
and formatting are not preserved), stage a sibling file, fsync, reload and compare,
re-check the byte revision immediately before `os.replace`, then reload the saved
file. A changed source is refused, never merged; a failure leaves the source as it
was.
"""

import hashlib
import os
import tempfile
from pathlib import Path

from .errors import ProjectError, ValidationIssue
from .models import Project
from .project import load_project, resolve_output_directory
from .validation import validate_project
from .yaml_io import dump_project


def source_revision(path: Path) -> str:
    return "sha256-" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _refuse(code: str, message: str) -> ProjectError:
    return ProjectError((ValidationIssue("book.yaml", code, message),))


def replace_source(path: Path, project: Project, revision: str) -> str:
    """Write `project` over `path` if it still has `revision`; return the new revision."""
    path = Path(path)
    project = validate_project(project.to_dict()).require_project()
    resolve_output_directory(project, path.parent)
    temporary: Path | None = None
    try:
        if source_revision(path) != revision:
            raise _refuse("source_changed", "book.yaml changed while this command ran; retry it.")
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".puzzlepress-", suffix=".tmp", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(dump_project(project).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if load_project(temporary).project != project:
            raise RuntimeError("Serialized source failed round-trip verification")
        if source_revision(path) != revision:
            raise _refuse("source_changed", "book.yaml changed while this command ran; retry it.")
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise _refuse("save_failed", f"book.yaml was not replaced: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if load_project(path).project != project:
        raise _refuse("save_unconfirmed", "book.yaml was replaced but reads back differently.")
    return source_revision(path)
