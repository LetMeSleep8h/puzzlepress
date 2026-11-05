"""Every demo book still produces exactly the outputs pinned before the engine refactor.

The baseline (`tests/fixtures/golden/baseline.json`) was recorded by
`tests/golden_baseline.py` from the engine at main `693aa00` (branch commits `270d3dd`
and `a9e076a` add only documentation and tests) before any engine change. Never
rewrite it to make this test pass: a difference is a behavior change to explain.

Baseline version 2 re-recorded the same pre-refactor engine with the corrected
stdout normalization (see `golden_baseline.py`). Only five JSON stdout digests
changed, and they equal the values Linux CI computed for version 1's run.

Intentional policy changes since the baseline are recorded, never written over it, in
`tests/fixtures/golden/migrations.json`: each names its reason, the report changes,
and every pinned value it changes with the value before (which must still be the
baseline's) and after (which the engine must now produce exactly). Everything a
migration does not name must still equal the baseline. Interval 8's migration is
interior preflight ruleset 5 (the verified KDP 8.5 x 11 white maximum, 590).
"""

import json

import pytest

from tests.golden_baseline import BASELINE, PDF_WRITERS, SOURCE_ONLY, collect, encode, toolchain

MIGRATIONS = BASELINE.parent / "migrations.json"


@pytest.fixture(scope="module")
def pinned() -> dict:
    return json.loads(BASELINE.read_bytes())


@pytest.fixture(scope="module")
def current() -> dict:
    return collect()


def migrated(pinned: dict) -> dict:
    """The baseline with every recorded migration applied, checked against its record."""
    data = json.loads(json.dumps(pinned))
    for migration in json.loads(MIGRATIONS.read_bytes())["migrations"]:
        assert migration["from_baseline_version"] == pinned["baseline_version"]
        for path, change in migration["changes"].items():
            *parents, leaf = path.strip("/").split("/")
            node = data
            for key in parents:
                node = node[key]
            assert node[leaf] == change["was"], f"{path} is not the baseline's value"
            node[leaf] = change["now"]
    return data


def test_migrations_name_only_report_values(pinned):
    """A migration may change reports, never a PDF, identity, plan or generator output."""
    for migration in json.loads(MIGRATIONS.read_bytes())["migrations"]:
        assert migration["reason"] and migration["report_changes"]
        for path in migration["changes"]:
            parts = path.strip("/").split("/")
            assert not path.endswith(".pdf"), path
            assert not set(parts) & {*SOURCE_ONLY, "generate", "toolchain"}, path
    migrated(pinned)  # Every "was" is still the pinned baseline value.


def _differences(expected: object, actual: object, path: str = "") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        found: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            if key not in actual:
                found.append(f"{path}/{key}: missing")
            elif key not in expected:
                found.append(f"{path}/{key}: unexpected")
            else:
                found += _differences(expected[key], actual[key], f"{path}/{key}")
        return found
    return [] if expected == actual else [f"{path}: {expected!r} -> {actual!r}"]


def test_baseline_file_is_canonical(pinned):
    # A Windows checkout may turn the line endings into CRLF; the content is what counts.
    assert BASELINE.read_bytes().replace(b"\r\n", b"\n") == encode(pinned)


def test_source_only_outputs_match(pinned, current):
    """Identities, validation, plans and generation do not depend on PDF libraries."""
    assert current["books"].keys() == pinned["books"].keys()
    found = _differences(pinned["generate"], current["generate"], "/generate")
    for name, record in pinned["books"].items():
        for key in SOURCE_ONLY:
            if key in record or key in current["books"][name]:
                found += _differences(
                    record.get(key), current["books"][name].get(key), f"/{name}/{key}"
                )
    assert found == []


def _pdfs(record: dict) -> dict[str, str]:
    return {
        f"{group}/{name}": digest
        for group in ("interior_files", "produce_files")
        for name, digest in record.get(group, {}).items()
        if name.endswith(".pdf")
    }


def test_pdf_files_match(pinned, current):
    """Interior and cover PDFs need only the same writing libraries, not the same pypdf."""
    installed = toolchain()
    wanted = {name: pinned["toolchain"][name] for name in PDF_WRITERS}
    if {name: installed[name] for name in PDF_WRITERS} != wanted:
        pytest.skip(f"PDF bytes were pinned under {wanted}; installed {installed}.")
    found: list[str] = []
    for name, record in pinned["books"].items():
        found += _differences(_pdfs(record), _pdfs(current["books"][name]), f"/{name}")
    assert found == []


def test_every_output_matches(pinned, current):
    """PDFs, manifests and reports are byte-identical under the recorded toolchain, apart
    from exactly the values a recorded migration changes (to exactly its new values)."""
    if toolchain() != pinned["toolchain"]:
        pytest.skip(
            f"PDF bytes were pinned under {pinned['toolchain']}; installed {toolchain()}. "
            "Only source-only outputs are compared."
        )
    assert _differences(migrated(pinned), current) == []
