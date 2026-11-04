"""Every demo book still produces exactly the outputs pinned before the engine refactor.

The baseline (`tests/fixtures/golden/baseline.json`) was recorded by
`tests/golden_baseline.py` from the engine at main `693aa00` (branch commit `270d3dd`
adds only documentation) before any engine change. Never rewrite it to make this
test pass: a difference is a behavior change to explain.
"""

import json

import pytest

from tests.golden_baseline import BASELINE, SOURCE_ONLY, collect, encode, toolchain


@pytest.fixture(scope="module")
def pinned() -> dict:
    return json.loads(BASELINE.read_bytes())


@pytest.fixture(scope="module")
def current() -> dict:
    return collect()


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


def test_every_output_matches(pinned, current):
    """PDFs, manifests and reports are byte-identical under the recorded toolchain."""
    if toolchain() != pinned["toolchain"]:
        pytest.skip(
            f"PDF bytes were pinned under {pinned['toolchain']}; installed {toolchain()}. "
            "Only source-only outputs are compared."
        )
    assert _differences(pinned, current) == []
