"""Live cover variables: facts of the built interior, filled in by the cover layout.

A version 3 text box may contain `{page_count}` or `{trim_size}`. They are not
book details and are never resolved when a template is applied: the text keeps
the variable, and Python's cover layout replaces it with the value read from the
verified interior it is laying the cover out for (the same facts that size the
spine). A rebuilt interior with a different page count therefore changes the
printed number together with the spine width, and the cover identity (which
covers the interior's physical facts) marks the old cover out of date.

Only these exact tokens are variables. Any other text in braces is literal, so
covers written before variables existed keep their words and bytes. There is no
escape: a cover cannot print the literal token `{page_count}`.
"""

import re
from dataclasses import replace

from ..cover_richtext import RichText
from ..interior.spec import to_inches
from .geometry import CoverGeometry

LIVE_VARIABLES: tuple[str, ...] = ("page_count", "trim_size")
TOKEN = re.compile(r"\{(page_count|trim_size)\}")


def _number(value: float) -> str:
    """Inches as written on a cover: up to three decimals, no trailing zeros."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def live_values(geometry: CoverGeometry) -> dict[str, str]:
    """Each live variable's text for this cover's interior. Deterministic."""
    width, height = to_inches(geometry.front.width), to_inches(geometry.front.height)
    return {
        "page_count": str(geometry.page_count),
        "trim_size": f"{_number(width)} x {_number(height)} in",
    }


def has_live(text: str) -> bool:
    return TOKEN.search(text) is not None


def resolve(text: str, values: dict[str, str]) -> str:
    return TOKEN.sub(lambda match: values[match[1]], text)


def resolve_rich(document: RichText, values: dict[str, str]) -> RichText:
    """The document with every run's variables filled in; unchanged when it has none."""
    if not any(has_live(run.text) for block in document.blocks for run in block.runs):
        return document
    return replace(
        document,
        blocks=tuple(
            replace(
                block,
                runs=tuple(replace(run, text=resolve(run.text, values)) for run in block.runs),
            )
            for block in document.blocks
        ),
    )
