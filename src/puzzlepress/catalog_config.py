"""Schema-v1 optional `catalog` section: how the author files the book in their library.

`subject` and `collection` are the author's own words. They describe the book in
the Library and nowhere else: no build, cover or publishing step reads them, so
they are outside every production identity. A collection is not a KDP series
(`publishing.series`); PuzzlePress never infers one from the other.
"""

from dataclasses import dataclass

from .errors import ValidationIssue

MAX_CATALOG_TEXT = 120


@dataclass(frozen=True)
class Catalog:
    subject: str | None = None
    collection: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {}
        if self.subject is not None:
            data["subject"] = self.subject
        if self.collection is not None:
            data["collection"] = self.collection
        return data


def validate_catalog(value: object) -> tuple[Catalog | None, tuple[ValidationIssue, ...]]:
    issues: list[ValidationIssue] = []
    if not isinstance(value, dict):
        return None, (ValidationIssue("catalog", "type", "Expected a mapping."),)
    for key in sorted(str(k) for k in value):
        if key not in {"subject", "collection"}:
            issues.append(ValidationIssue(f"catalog.{key}", "unknown_field", "Unknown field."))
    values: dict[str, str | None] = {}
    for key in ("subject", "collection"):
        raw = value.get(key)
        if raw is None:
            values[key] = None
            continue
        text = raw.strip() if isinstance(raw, str) else None
        if (
            not text
            or len(text) > MAX_CATALOG_TEXT
            or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in text)
        ):
            issues.append(
                ValidationIssue(
                    f"catalog.{key}",
                    "text",
                    f"Expected 1..{MAX_CATALOG_TEXT} characters of single-line text.",
                )
            )
            values[key] = None
        else:
            values[key] = text
    if issues:
        return None, tuple(issues)
    return Catalog(values["subject"], values["collection"]), ()
