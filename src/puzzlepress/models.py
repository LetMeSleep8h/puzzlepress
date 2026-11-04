"""Immutable, normalized schema-v1 values produced by validation."""

from dataclasses import asdict, dataclass

from .coloring_config import ColoringBook
from .composition import Composition
from .content import WordSearchContent
from .cover_config import CoverConfig
from .engines.kind import EngineKind
from .interior_style import InteriorStyle
from .publishing_config import PublishingConfig


@dataclass(frozen=True)
class Book:
    id: str
    title: str
    language: str
    subtitle: str | None = None
    description: str | None = None
    author: str | None = None
    imprint: str | None = None


@dataclass(frozen=True)
class Build:
    seed: int


@dataclass(frozen=True)
class Content:
    """Ordered authored items; no puzzle-specific interpretation in schema v1."""

    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class Output:
    directory: str


@dataclass(frozen=True)
class Project:
    schema_version: int
    book: Book
    build: Build
    content: Content
    output: Output
    word_search: WordSearchContent | None = None
    composition: Composition | None = None
    cover: CoverConfig | None = None
    publishing: PublishingConfig | None = None
    interior: InteriorStyle | None = None
    coloring: ColoringBook | None = None

    @property
    def engine(self) -> EngineKind:
        """Derived from the content section, never stored: a schema-v1 project without
        another engine's section is a word-search project (legacy ones included)."""
        return EngineKind.COLORING if self.coloring is not None else EngineKind.WORD_SEARCH

    def to_dict(self) -> dict[str, object]:
        """Return an independent, JSON/YAML-compatible source representation."""
        data = asdict(self)
        data["content"]["items"] = list(self.content.items)
        if self.word_search is None:
            del data["word_search"]
        else:
            data["word_search"] = self.word_search.to_dict()
        if self.composition is None:
            del data["composition"]
        else:
            data["composition"] = self.composition.to_dict()
        if self.cover is None:
            del data["cover"]
        else:
            data["cover"] = self.cover.to_dict()
        if self.publishing is None:
            del data["publishing"]
        else:
            data["publishing"] = self.publishing.to_dict()
        if self.interior is None:
            del data["interior"]
        else:
            data["interior"] = self.interior.to_dict()
        if self.coloring is None:
            del data["coloring"]
        else:
            data["coloring"] = self.coloring.to_dict()
        return data
