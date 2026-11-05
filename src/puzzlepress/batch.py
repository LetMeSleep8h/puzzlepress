"""Project-driven generation and quality reporting; no printing or filesystem I/O."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from itertools import combinations

from .cancellation import checkpoint
from .content import PIPELINE_VERSION, QualityConfig, WordSearchContent
from .content_validation import validate_word_search_content
from .errors import ProjectError, ValidationIssue
from .identity import build_identity
from .models import Project
from .quality import (
    PuzzleQuality,
    PuzzleSimilarity,
    QualityFinding,
    WordReuse,
    analyze_word_search,
    compare_target_sets,
)
from .validation import validate_project
from .wordsearch import (
    GenerationStats,
    WordSearch,
    WordSearchError,
    generate_word_search,
    normalize_targets,
    verify_word_search,
)
from .wordsearch.validation import normalize_seed


@dataclass(frozen=True)
class ContentAnalysis:
    reuse: tuple[WordReuse, ...]
    similarities: tuple[PuzzleSimilarity, ...]
    findings: tuple[QualityFinding, ...]


@dataclass(frozen=True)
class PuzzleResult:
    id: str
    title: str
    theme: str
    difficulty: str
    seed: int
    puzzle: WordSearch | None
    quality: PuzzleQuality | None
    errors: tuple[ValidationIssue, ...] = ()
    failure_stats: GenerationStats | None = None


@dataclass(frozen=True)
class BatchReport:
    identity: str
    puzzles: tuple[PuzzleResult, ...]
    content: ContentAnalysis
    findings: tuple[QualityFinding, ...]
    quality_config: QualityConfig = QualityConfig()
    pipeline_version: int = PIPELINE_VERSION

    @property
    def success(self) -> bool:
        return all(result.puzzle is not None and not result.errors for result in self.puzzles)

    @property
    def clean(self) -> bool:
        return self.success and not self.findings

    def to_dict(self) -> dict[str, object]:
        """Independent JSON-compatible presentation for terminal or web adapters."""
        return {
            "pipeline_version": self.pipeline_version,
            "identity": self.identity,
            "success": self.success,
            "clean": self.clean,
            "quality_config": asdict(self.quality_config),
            "puzzles": [
                {
                    "id": result.id,
                    "title": result.title,
                    "theme": result.theme,
                    "difficulty": result.difficulty,
                    "seed": str(result.seed),
                    "errors": [asdict(error) for error in result.errors],
                    "failure_stats": asdict(result.failure_stats) if result.failure_stats else None,
                    "quality": asdict(result.quality) if result.quality else None,
                    "puzzle": _puzzle_dict(result.puzzle) if result.puzzle else None,
                }
                for result in self.puzzles
            ],
            "reuse": [asdict(reuse) for reuse in self.content.reuse],
            "similarities": [asdict(similarity) for similarity in self.content.similarities],
            "findings": [asdict(finding) for finding in self.findings],
        }


def _puzzle_dict(puzzle: WordSearch) -> dict[str, object]:
    return {
        "generation_version": puzzle.generation_version,
        "config": {
            "width": puzzle.config.size.width,
            "height": puzzle.config.size.height,
            "directions": [d.name.lower().replace("_", "-") for d in puzzle.config.directions],
            "max_restarts": puzzle.config.max_restarts,
            "max_attempts": puzzle.config.max_attempts,
        },
        "grid": list(puzzle.grid.rows),
        "targets": [asdict(target) for target in puzzle.targets],
        "stats": asdict(puzzle.stats),
        "placements": [
            {
                "target_id": p.target_id,
                "search": p.search,
                "start": asdict(p.start),
                "end": asdict(p.end),
                "direction": p.direction.name.lower().replace("_", "-"),
            }
            for p in puzzle.solution.placements
        ],
    }


def puzzle_digest(puzzle: WordSearch) -> str:
    """Content digest of a generated puzzle's reported grid, targets and solution."""
    material = json.dumps(
        _puzzle_dict(puzzle), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return "sha256-" + hashlib.sha256(material).hexdigest()


def derive_puzzle_seed(seed: int | str, puzzle_id: str) -> int:
    """Stable SHA-256 domain-separated derivation, independent of batch order."""
    if not isinstance(puzzle_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", puzzle_id):
        raise WordSearchError((ValidationIssue("puzzle_id", "id", "Expected a valid puzzle ID."),))
    material = json.dumps(
        ["puzzlepress-word-search", PIPELINE_VERSION, normalize_seed(seed), puzzle_id],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def analyze_content(content: WordSearchContent) -> ContentAnalysis:
    """Analyze authored reuse/duplicates even before generating any grids."""
    normalized, issues = validate_word_search_content(content.to_dict())
    if normalized is None:
        raise ProjectError(issues)
    return _analyze_content(normalized, {})


def _analyze_content(
    content: WordSearchContent, generated: dict[str, WordSearch]
) -> ContentAnalysis:
    forms = {
        definition.id: frozenset(
            t.search for t in normalize_targets(content.entries_for(definition))
        )
        for definition in content.puzzles
    }
    usage: dict[str, list[str]] = {}
    for definition in content.puzzles:
        for word in sorted(forms[definition.id]):
            usage.setdefault(word, []).append(definition.id)
    reuse = tuple(
        WordReuse(word, tuple(ids)) for word, ids in sorted(usage.items()) if len(ids) > 1
    )
    findings: list[QualityFinding] = []
    for item in reuse:
        if len(item.puzzle_ids) > content.quality.max_word_reuse:
            findings.append(
                QualityFinding(
                    "word_reuse",
                    "Word exceeds configured reuse limit.",
                    item.puzzle_ids,
                    (item.word,),
                )
            )
    similarities: list[PuzzleSimilarity] = []
    for left, right in combinations(content.puzzles, 2):
        a, b = generated.get(left.id), generated.get(right.id)
        similarity = compare_target_sets(
            left.id,
            right.id,
            forms[left.id],
            forms[right.id],
            a.grid if a else None,
            b.grid if b else None,
        )
        similarities.append(similarity)
        if similarity.identical_targets:
            findings.append(
                QualityFinding(
                    "duplicate_targets",
                    "Puzzles use identical normalized target sets.",
                    (left.id, right.id),
                    similarity.shared_words,
                )
            )
        elif similarity.target_jaccard >= content.quality.target_similarity_threshold:
            findings.append(
                QualityFinding(
                    "similar_targets",
                    "Target Jaccard similarity meets the configured threshold.",
                    (left.id, right.id),
                    similarity.shared_words,
                )
            )
        if (
            similarity.grid_agreement is not None
            and similarity.grid_agreement >= content.quality.grid_similarity_threshold
        ):
            findings.append(
                QualityFinding(
                    "similar_grids",
                    "Grid agreement meets the configured threshold.",
                    (left.id, right.id),
                )
            )
    return ContentAnalysis(reuse, tuple(similarities), tuple(findings))


def generate_batch(project: Project) -> BatchReport:
    """Generate every definition (see content.MAX_*); keep successes and expected failures.

    Invalid source fails validation before generation. Bounded placement failures
    are recorded per puzzle and do not prevent later definitions from running.
    Warnings never silently trigger regeneration or change authored inputs.
    """
    project = validate_project(project.to_dict()).require_project()
    content = project.word_search
    if content is None:
        raise ProjectError(
            (ValidationIssue("word_search", "required", "Project has no puzzle definitions."),)
        )
    results: list[PuzzleResult] = []
    findings: list[QualityFinding] = []
    generated: dict[str, WordSearch] = {}
    for index, definition in enumerate(content.puzzles):
        checkpoint("generate_puzzles", index, len(content.puzzles))
        seed = derive_puzzle_seed(project.build.seed, definition.id)
        try:
            puzzle = generate_word_search(
                content.entries_for(definition), content.config_for(definition), seed
            )
        except WordSearchError as error:
            results.append(
                PuzzleResult(
                    definition.id,
                    definition.title,
                    definition.theme,
                    definition.difficulty,
                    seed,
                    None,
                    None,
                    error.issues,
                    error.stats,
                )
            )
            continue
        verification = verify_word_search(puzzle)
        if not verification.valid:
            raise RuntimeError(f"Generated puzzle failed verification: {verification.issues!r}")
        quality = analyze_word_search(puzzle, content.quality.prohibited_words)
        generated[definition.id] = puzzle
        results.append(
            PuzzleResult(
                definition.id,
                definition.title,
                definition.theme,
                definition.difficulty,
                seed,
                puzzle,
                quality,
            )
        )
        for code, scan in (
            ("accidental_target", quality.accidental_targets),
            ("prohibited_word", quality.prohibited),
        ):
            if scan.occurrences:
                findings.append(
                    QualityFinding(
                        code,
                        "Grid contains flagged word occurrences; inspect coordinates.",
                        (definition.id,),
                        tuple(sorted({o.word for o in scan.occurrences})),
                    )
                )
            if scan.truncated:
                findings.append(
                    QualityFinding(
                        "scan_truncated",
                        f"{code} scan reached its report limit; screening is incomplete.",
                        (definition.id,),
                    )
                )
    analysis = _analyze_content(content, generated)
    return BatchReport(
        build_identity(project),
        tuple(results),
        analysis,
        (*analysis.findings, *findings),
        quality_config=content.quality,
    )
