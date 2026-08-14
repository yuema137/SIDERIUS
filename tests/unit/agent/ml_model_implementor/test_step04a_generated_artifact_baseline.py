"""CHECKPOINT 0 — generated-artifact byte baseline for a fixed spec.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §5 (Stage-A parity, row
*"generated plugin for a fixed TIDMAD spec — CAPTURE FIRST"*) and §16 C1.

**The defect only this module catches.** PR 04a rewrites how the plugin
template's contract comments, the generated test file's assertions and the
implementor's own self-check obtain the class count: today three separate
literals, afterwards one derivation from the normalized contract. The
existing oracles do not cover the assembled *bytes* — ``pb5_*`` covers the
prompts sent to the LLM, and ``test_output_contract_end_to_end.py`` proves
the generated test *passes* without pinning what it says. A derivation that
produced ``[B, 256.0, T]``, reordered the comment, or dropped the
``PLUGIN_OUTPUT_TYPE`` trailing comment would pass every one of those and
still change every candidate the chain writes to disk.

**Why bytes and not a parse.** Parent §8: for a *fixed* spec the template's
contribution is fully deterministic, so a byte diff is meaningful and is not
a snapshot of LLM behaviour. The LLM's contribution here is frozen in
``tests.helpers.step04a_fixtures.CODE_BY_OUTPUT_TYPE``.

Captured at ``3e9728c8`` (the frozen design head, whose production tree is
identical to master ``e802b810``), clean tree, before any PR-04a production
edit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nodes.ml_model_implementor.ml_model_implementor import _assemble_plugin, _assemble_test
from tests.helpers.golden import assert_golden
from tests.helpers.step04a_fixtures import (
    CODE_BY_OUTPUT_TYPE,
    MODEL_NAMES,
    implementor_input,
    tidmad_model_io,
)

GOLDENS = Path(__file__).parent / "goldens"


def _render_plugin(output_type: str, workspace: str) -> str:
    """Assemble the candidate exactly as the production writer does."""
    return _assemble_plugin(
        implementor_input(output_type, model_io=tidmad_model_io(), workspace=workspace),
        CODE_BY_OUTPUT_TYPE[output_type],
    )


@pytest.mark.parametrize("output_type", ["classifier", "regressor"])
def test_generated_plugin_bytes_match_the_fixed_spec_baseline(tmp_path, output_type):
    """The assembled candidate is byte-identical to the captured baseline.

    Fails when: any template byte moves — a changed contract comment, a
    reordered field, a lost ``PLUGIN_OUTPUT_TYPE`` annotation, altered
    indentation of the LLM-supplied bodies.
    """
    assert_golden(
        _render_plugin(output_type, str(tmp_path)),
        GOLDENS / f"s04a_generated_plugin_{output_type}.txt",
        surface=f"S04a-C0 generated plugin ({output_type}, fixed TIDMAD spec)",
    )


@pytest.mark.parametrize("output_type", ["classifier", "regressor"])
def test_generated_plugin_bytes_are_reproducible(tmp_path, output_type):
    """Two renders of one spec agree — the baseline pins a function, not a run.

    Fails when: assembly acquires a nondeterministic input (a timestamp, a
    dict iteration order that escapes, an unseeded value). Without this the
    golden above could be a lucky capture rather than a contract, and C1's
    acceptance criterion explicitly requires reproducibility twice in a row.
    """
    first = _render_plugin(output_type, str(tmp_path))
    second = _render_plugin(output_type, str(tmp_path / "second"))
    assert first == second


def test_generated_test_file_bytes_match_the_baseline():
    """The rendered test file is pinned for the fixed spec.

    Fails when: the generated test body changes. It did change once, at C4,
    when the class count became a render-time placeholder — and the golden is
    what made that delta reviewable: **comment text only, every numeric value
    byte-identical**. That is the parity claim, and it is visible in the diff
    rather than asserted in prose.
    """
    assert_golden(
        _assemble_test(MODEL_NAMES["classifier"], tidmad_model_io()),
        GOLDENS / "s04a_generated_test.txt",
        surface="S04a-C0 generated test file (fixed TIDMAD spec)",
    )


def test_the_legacy_path_renders_the_same_test_file_under_tidmad():
    """§15.1 row 1: a prose-only caller emits byte-identical artifacts.

    Fails when: the derived and legacy renderings diverge for the shipped
    task — which would mean a legacy caller silently started generating
    different candidates. Comparing the two paths directly is stronger than
    comparing each to the golden, because it also catches the case where both
    drift together.
    """
    assert _assemble_test(MODEL_NAMES["classifier"], None) == _assemble_test(
        MODEL_NAMES["classifier"], tidmad_model_io()
    )
