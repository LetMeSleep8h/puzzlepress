"""Pure validation and normalization; expected failures have structured issues."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import cast

from .coloring_validation import validate_coloring
from .composition_validation import divider_issues, validate_composition
from .content_validation import validate_word_search_content
from .cover_validation import validate_cover
from .engines.kind import EngineKind, detect_engine
from .errors import MAX_SEED
from .errors import ProjectError as ProjectError
from .errors import ValidationIssue as ValidationIssue
from .models import Book, Build, Content, Output, Project
from .publishing_validation import validate_publishing

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ValidationResult:
    project: Project | None
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return self.project is not None and not self.issues

    def require_project(self) -> Project:
        if self.issues:
            raise ProjectError(self.issues)
        if self.project is None:
            raise RuntimeError("Validation result has neither a project nor issues")
        return self.project


def validate_project(data: object) -> ValidationResult:
    """Validate a decoded source mapping, collecting independent schema errors.

    Schema dispatch lives here: future versions can have separate validators.
    Unknown versions are never interpreted using v1 rules.
    """
    issues: list[ValidationIssue] = []

    def issue(path: str, code: str, message: str) -> None:
        issues.append(ValidationIssue(path, code, message))

    def mapping(value: object, path: str, allowed: set[str]) -> dict[str, object]:
        if not isinstance(value, dict):
            issue(path, "type", "Expected a mapping.")
            return {}
        if any(not isinstance(key, str) for key in value):
            issue(path, "key_type", "Mapping keys must be strings.")
        for key in sorted(key for key in value if isinstance(key, str)):
            if key not in allowed:
                issue(f"{path}.{key}" if path else key, "unknown_field", "Unknown field.")
        return cast(dict[str, object], value)

    def required(source: dict[str, object], key: str, path: str) -> object:
        if key not in source:
            issue(path, "required", "Required field is missing.")
        return source.get(key)

    def string(value: object, path: str, optional: bool = False) -> str | None:
        if optional and value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            issue(path, "type", "Expected a nonempty string.")
            return None
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            issue(path, "unicode", "Text must contain valid Unicode scalar values.")
            return None
        return value.strip()

    root = mapping(
        data,
        "",
        {
            "schema_version",
            "book",
            "build",
            "content",
            "output",
            "word_search",
            "coloring",
            "composition",
            "cover",
            "publishing",
            "interior",
        },
    )
    version = required(root, "schema_version", "schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        if "schema_version" in root:
            issue(
                "schema_version",
                "unsupported_version",
                f"Unsupported PuzzlePress schema version: {version!r}. Supported versions: 1.",
            )
        return ValidationResult(None, tuple(issues))

    book = mapping(
        required(root, "book", "book"),
        "book",
        {"id", "title", "language", "subtitle", "description", "author", "imprint"},
    )
    book_values: dict[str, str | None] = {}
    for key in ("id", "title", "language"):
        if key not in book:
            required(book, key, f"book.{key}")
            book_values[key] = None
        else:
            book_values[key] = string(book[key], f"book.{key}")
    for key in ("subtitle", "description", "author", "imprint"):
        book_values[key] = string(book.get(key), f"book.{key}", optional=True)
    book_id = book_values["id"]
    if book_id and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", book_id):
        issue("book.id", "format", "Use lowercase ASCII letters/digits separated by hyphens.")
    # These names cannot safely serve as output directories on Windows.
    if book_id and re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])", book_id):
        issue("book.id", "reserved", "This identifier is reserved on Windows.")
    language = book_values["language"]
    if language and not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language):
        issue("book.language", "format", "Expected a language tag such as en or en-US.")

    build = mapping(required(root, "build", "build"), "build", {"seed"})
    seed = required(build, "seed", "build.seed")
    if isinstance(seed, str) and re.fullmatch(r"[0-9]+", seed.strip()):
        digits = seed.strip().lstrip("0") or "0"
        seed = int(digits) if len(digits) <= 20 else MAX_SEED + 1
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        if "seed" in build:
            issue("build.seed", "seed", f"Expected an integer or decimal string in 0..{MAX_SEED}.")

    content = mapping(root.get("content", {}), "content", {"items"})
    raw_items = content.get("items", [])
    items: list[str] = []
    if not isinstance(raw_items, list):
        issue("content.items", "type", "Expected an ordered list of nonempty strings.")
    else:
        for index, item in enumerate(raw_items):
            normalized = string(item, f"content.items.{index}")
            if normalized is not None:
                items.append(normalized)

    output = mapping(root.get("output", {}), "output", {"directory"})
    directory = string(output.get("directory", f"../build/{book_id}"), "output.directory")
    if directory:
        windows = PureWindowsPath(directory)
        if (
            windows.drive
            or windows.root
            or PurePosixPath(directory).is_absolute()
            or "\\" in directory
            or any(ord(char) < 32 for char in directory)
            or any(char in directory for char in '<>:"|?*')
            or any(
                part.endswith((" ", "."))
                for part in directory.split("/")
                if part not in (".", "..")
            )
        ):
            issue("output.directory", "path", "Use a relative path with forward slashes.")

    # The engine is derived from the content section; a second engine's section, or one
    # this version cannot build, is reported rather than read with word-search rules.
    engine, engine_issues = detect_engine(root)
    issues.extend(engine_issues)
    word_search = None
    if "word_search" in root:
        word_search, content_issues = validate_word_search_content(root["word_search"])
        issues.extend(content_issues)
    coloring = None
    if engine is EngineKind.COLORING:
        coloring, coloring_issues = validate_coloring(root["coloring"])
        issues.extend(coloring_issues)
    composition = None
    if "composition" in root:
        composition, composition_issues = validate_composition(
            root["composition"], "word_search" in root, coloring=engine is EngineKind.COLORING
        )
        issues.extend(composition_issues)
    if engine is EngineKind.COLORING:
        # Covers, publishing metadata and interior styles read word-search content in
        # this version; coloring books get them in a later version, never half-applied.
        for section in ("cover", "publishing", "interior"):
            if section in root:
                issue(
                    section,
                    "not_available_for_engine",
                    f"Coloring books cannot have a {section} section in this version. "
                    "Remove it; the coloring interior builds without it.",
                )
    cover = None
    if "cover" in root and engine is not EngineKind.COLORING:
        cover, cover_issues = validate_cover(root["cover"], "composition" in root)
        issues.extend(cover_issues)
    publishing = None
    if "publishing" in root and engine is not EngineKind.COLORING:
        publishing, publishing_issues = validate_publishing(
            root["publishing"], "composition" in root
        )
        issues.extend(publishing_issues)
    if composition is not None and composition.dividers is not None and word_search is not None:
        issues.extend(divider_issues(composition, word_search.puzzles))
    interior = None
    if "interior" in root and engine is not EngineKind.COLORING:
        from .interior_style_validation import validate_interior_style

        interior, interior_issues = validate_interior_style(root["interior"], "composition" in root)
        issues.extend(interior_issues)
        if interior is not None and word_search is not None:
            themes = {puzzle.theme for puzzle in word_search.puzzles}
            for index, divider in enumerate(interior.dividers.photos):
                if divider.theme not in themes:
                    issue(
                        f"interior.dividers.photos.{index}.theme",
                        "unknown_theme",
                        f"No puzzle has the theme {divider.theme!r}.",
                    )
    if issues:
        return ValidationResult(None, tuple(issues))
    return ValidationResult(
        Project(
            schema_version=SCHEMA_VERSION,
            book=Book(
                id=cast(str, book_id),
                title=cast(str, book_values["title"]),
                language=cast(str, language),
                subtitle=book_values["subtitle"],
                description=book_values["description"],
                author=book_values["author"],
                imprint=book_values["imprint"],
            ),
            build=Build(cast(int, seed)),
            content=Content(tuple(items)),
            output=Output(cast(str, directory)),
            word_search=word_search,
            composition=composition,
            cover=cover,
            publishing=publishing,
            interior=interior,
            coloring=coloring,
        ),
        (),
    )
