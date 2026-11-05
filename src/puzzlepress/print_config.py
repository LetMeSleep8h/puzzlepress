"""Schema-v1 optional `print` section: the print profile the author chose.

A profile fixes trim and paper together (see `interior.spec`); PuzzlePress never
infers paper. Without this section a build uses the profile it is given (CLI
`--profile`, Studio's choice) or the default, exactly as before. With it, builds
use the authored profile and refuse a different explicit one, and the section is
part of the build identity, so changing paper makes the built interior, and the
cover sized from it, report out of date.
"""

from dataclasses import dataclass

from .errors import ValidationIssue

# The built-in profile identifiers (`interior.spec.PROFILES`; a test keeps the two
# equal). Listed here so validating a source never imports the PDF toolchain.
PROFILE_IDS = (
    "paperback-8.5x11",
    "paperback-8.5x11-cream",
    "paperback-6x9",
    "paperback-6x9-cream",
    "paperback-8x10",
    "paperback-8x10-cream",
    "paperback-8.5x8.5",
    "paperback-8.5x8.5-cream",
)


@dataclass(frozen=True)
class PrintSettings:
    profile: str

    def to_dict(self) -> dict[str, object]:
        return {"profile": self.profile}


def validate_print(value: object) -> tuple[PrintSettings | None, tuple[ValidationIssue, ...]]:
    if not isinstance(value, dict):
        return None, (ValidationIssue("print", "type", "Expected a mapping."),)
    issues = [
        ValidationIssue(f"print.{key}", "unknown_field", "Unknown field.")
        for key in sorted(str(k) for k in value)
        if key != "profile"
    ]
    profile = value.get("profile")
    if "profile" not in value:
        issues.append(ValidationIssue("print.profile", "required", "Required field is missing."))
    elif profile not in PROFILE_IDS:
        issues.append(
            ValidationIssue(
                "print.profile",
                "unsupported_profile",
                f"Unknown print profile {profile!r}. Supported: {', '.join(PROFILE_IDS)}.",
            )
        )
    if issues:
        return None, tuple(issues)
    assert isinstance(profile, str)
    return PrintSettings(profile), ()


def chosen_profile(authored: PrintSettings | None, requested: str | None) -> str | None:
    """The profile a build uses: the authored one, or the requested one when the book
    has none. A requested profile that differs from the authored one raises
    `ProfileConflict`; None means the caller's own default applies."""
    if authored is None:
        return requested
    if requested is not None and requested != authored.profile:
        raise ProfileConflict(authored.profile, requested)
    return authored.profile


class ProfileConflict(Exception):
    def __init__(self, authored: str, requested: str) -> None:
        self.authored = authored
        self.requested = requested
        super().__init__(
            f"This book's print settings choose {authored}; {requested} was requested. "
            "Change print.profile in the book settings instead."
        )
