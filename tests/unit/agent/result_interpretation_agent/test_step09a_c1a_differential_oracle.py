"""Step-09a C1a — the pre-refactor differential oracle.

Design: ``docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/
pr_09a_interpreter_evidence_ordering.md`` §4.1.

The defect this file alone catches
----------------------------------
Step 09a extracts the interpreter's deterministic evidence / ordering /
prediction logic into private node modules (C1b) and then re-owns its
semantics (C2-C6). Without a baseline captured from the UNMODIFIED tree,
"behaviour-preserving" and "the only deltas are the declared ones" are
assertions with nothing behind them: a silently dropped field, a reordered
LLM call, a changed prompt render or a shifted prediction outcome would all
pass every existing test, because no existing test looks at the WHOLE digest
for ONE fixed input.

Two goldens own that:

``step09a_differential_digest.json``
    the complete ``InterpretationOutput`` for the fixed input, so any field
    that moves shows up as a field-level diff;
``step09a_differential_llm_calls.json``
    the ordered ``(label, sha256(system), sha256(user))`` sequence plus the
    Stability-Filter markers, so a changed prompt render or a changed call
    sequence is caught even when the digest happens not to move.

Update policy (Step-00 §17): the goldens are NEVER regenerated to make a test
green. Each later Step-09a commit that changes them must declare the delta and
attribute it to a §3 rule of the design; an undeclared delta is a STOP.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.helpers.golden import assert_json_golden
from tests.unit.agent.result_interpretation_agent import _step09a_fixture as fx

GOLDENS = Path(__file__).parent / "goldens"
DIGEST_GOLDEN = GOLDENS / "step09a_differential_digest.json"
LLM_CALLS_GOLDEN = GOLDENS / "step09a_differential_llm_calls.json"

# The call sequence this fixture causes, hardcoded rather than read back from
# the recorder (a self-referential expectation would pass for any sequence).
#
#   effective_types sorted -> [bidirectional_gated_tcn, punet, wavenet]
#     bidirectional_gated_tcn : cache MISS      -> per_model, then a fresh entry
#     punet                   : stable, skipped -> marker only, no LLM call
#     wavenet                 : active cache HIT -> per_model, then the
#                               consolidator's two list merges
#   then one cross-model synthesis.
EXPECTED_CALL_LABELS = [
    "interpretation.per_model",
    "interpretation.per_model",
    "cache_consolidator.list_merge",
    "cache_consolidator.list_merge",
    "interpretation.synthesis",
]
EXPECTED_MARKERS = [
    {
        "label": "interpretation.per_model_skipped",
        "extra": {"reason": "stable", "model_type": fx.PUNET},
    }
]


def _run_fixture(workspace: Path) -> tuple[dict, fx.RecordingStubBridge]:
    """Run the REAL agent over the FIXED input; return (digest, recorder)."""
    recorder = fx.RecordingStubBridge(str(workspace))
    agent = ResultInterpretationAgent(bridge_factory=lambda **_kw: recorder)
    output = agent.run(fx.build_input(str(workspace)))
    return json.loads(output.model_dump_json()), recorder


def _call_manifest(recorder: fx.RecordingStubBridge) -> dict:
    return {"calls": recorder.calls, "markers": recorder.markers}


class TestTheFixedInputDigest:
    def test_digest_matches_the_committed_oracle(self, tmp_path):
        digest, _ = _run_fixture(tmp_path)
        assert_json_golden(
            digest,
            DIGEST_GOLDEN,
            surface="Step-09a C1a differential interpretation digest",
        )

    def test_the_persisted_file_equals_the_in_memory_digest(self, tmp_path):
        digest, _ = _run_fixture(tmp_path)
        on_disk = json.loads((tmp_path / "interpretation_step09a.json").read_text(encoding="utf-8"))
        assert on_disk == digest, (
            "the persisted digest diverged from the returned object — persistence "
            "parity is part of the baseline C1b must preserve"
        )

    def test_the_digest_is_workspace_independent_and_repeatable(self, tmp_path):
        """Two runs, two DIFFERENT workspaces, one digest.

        Repeating the run proves determinism; changing the workspace proves the
        one genuinely run-varying string on the path never reaches the digest.
        """
        first, _ = _run_fixture(tmp_path / "ws_a")
        second, _ = _run_fixture(tmp_path / "ws_b")
        assert first == second


class TestTheLLMCallBoundary:
    def test_call_sequence_matches_the_committed_oracle(self, tmp_path):
        _, recorder = _run_fixture(tmp_path)
        assert_json_golden(
            _call_manifest(recorder),
            LLM_CALLS_GOLDEN,
            surface="Step-09a C1a differential LLM-call sequence",
        )

    def test_the_labels_and_markers_are_exactly_the_expected_ones(self, tmp_path):
        """A hardcoded shape check beside the golden.

        The golden pins the prompt BYTES (through their digests); this pins the
        call STRUCTURE in a form a reviewer can read without opening a JSON
        file, and fails loudly if a future change adds or drops a call site.
        """
        _, recorder = _run_fixture(tmp_path)
        assert [c["label"] for c in recorder.calls] == EXPECTED_CALL_LABELS
        assert recorder.markers == EXPECTED_MARKERS

    def test_the_recorded_prompts_are_repeatable_across_workspaces(self, tmp_path):
        _, first = _run_fixture(tmp_path / "ws_a")
        _, second = _run_fixture(tmp_path / "ws_b")
        assert first.calls == second.calls, (
            "prompt digests moved between workspaces — the workspace "
            "normalisation in RecordingStubBridge is not covering every "
            "interpolation site"
        )


class TestTheOracleIsStrict:
    """Anti-vacuity: prove the comparison would actually catch a regression."""

    def test_a_single_perturbed_field_is_reported(self):
        expected = json.loads(DIGEST_GOLDEN.read_text(encoding="utf-8"))
        expected.pop("_captured_at", None)
        perturbed = dict(expected)
        perturbed["total_experiments"] = expected["total_experiments"] + 1

        with pytest.raises(AssertionError) as excinfo:
            assert_json_golden(
                perturbed,
                DIGEST_GOLDEN,
                surface="Step-09a C1a oracle strictness probe",
            )
        assert "total_experiments" in str(excinfo.value)

    def test_a_perturbed_prompt_digest_is_reported(self):
        expected = json.loads(LLM_CALLS_GOLDEN.read_text(encoding="utf-8"))
        expected.pop("_captured_at", None)
        perturbed = json.loads(json.dumps(expected))
        perturbed["calls"][0]["user_sha256"] = "0" * 64

        with pytest.raises(AssertionError) as excinfo:
            assert_json_golden(
                perturbed,
                LLM_CALLS_GOLDEN,
                surface="Step-09a C1a call-sequence strictness probe",
            )
        assert "user_sha256" in str(excinfo.value)
