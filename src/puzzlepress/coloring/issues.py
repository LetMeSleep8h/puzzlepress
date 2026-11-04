"""Structured coloring-artwork failures and findings.

A failure (`ArtworkError`) means a file cannot be imported or read at all. A finding
(`ArtworkFinding`) is a print-quality observation about a readable file. Findings
never stop an import: they are reported beside it, as blocking or warning.
"""

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


@dataclass(frozen=True)
class ArtworkFinding:
    code: str
    severity: Severity
    message: str
    actual: str | None = None
    required: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "actual": self.actual,
            "required": self.required,
        }


class ArtworkError(Exception):
    """An expected failure for one file or reference: nothing was written for it."""

    def __init__(self, code: str, message: str, subject: str = "") -> None:
        self.code = code
        self.message = message
        self.subject = subject  # The file name or artwork reference concerned.
        super().__init__(f"{subject}: {message}" if subject else message)

    def about(self, subject: str) -> "ArtworkError":
        return ArtworkError(self.code, self.message, subject)

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "subject": self.subject}


class ImportRejected(Exception):
    """A batch import refused as a whole: every failing file is listed."""

    def __init__(self, errors: tuple[ArtworkError, ...]) -> None:
        self.errors = errors
        super().__init__("; ".join(str(error) for error in errors))
