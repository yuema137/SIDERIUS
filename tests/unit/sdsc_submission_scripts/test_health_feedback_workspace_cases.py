"""The three approved CB5-c workspace cases (pr3_healthgate_feedback.md §11-CB5).

End-to-end pseudo composition over the REAL components (mock LLM only):
interpreter run → digest at the chain path convention → committed
manifest → typed restore → iteration-2 interpreter → proposer protocol →
proposer reasoning prompt. Context snapshots are asserted on the ACTUAL
prompt strings, never inferred from schema state alone.

Case 1 — Workspace A, flag ON, two iterations: iteration-1's collapse
fingerprint reaches the iteration-2 PROPOSER context, and the manifest /
lock policy stamps agree.
Case 2 — Workspace A resumed with flag OFF: RunInvariantsViolation
naming the field and both values.
Case 3 — Separate Workspace B, OFF from creation: no treatment text in
any agent-facing prompt, while artifacts carry the recording-only
structured provenance.
"""

import json
import os
from unittest.mock import patch

import pytest

from agent.schemas.interpretation import InterpretationInput
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.resume import load_latest_fingerprint_history
from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    ensure_run_invariants,
)
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import _build_reasoning_prompt
from nodes.result_interpretation_agent import (
    ResultInterpretationAgent,
    tuning_output_to_model_run_summary,
)
from tests.unit.agent.result_interpretation_agent.test_interpretation_agent import (
    _llm_dispatch,
)
from tests.unit.agent.result_interpretation_agent.test_round_health_summary import (
    _gate_result,
    _output,
    _record,
)

SIG = "output_diversity_blocking:n_unique_int8_values=1"

POLICY = {
    "enable_structured_health_feedback": True,
    "history_window_iterations": 3,
    "max_entries_per_model": 8,
}


def _invariants(ws, *, on: bool) -> RunInvariants:
    return RunInvariants(
        resolved_data_scope=list(range(20)),
        health_gate_enabled=False,
        health_config_sha256=None,
        structured_health_feedback_enabled=on,
    )


def _collapse_summary(exp_prefix: str):
    return tuning_output_to_model_run_summary(
        _output(
            _record(
                f"{exp_prefix}_001",
                status="failed_mode_collapse",
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="[output_diversity_blocking] unique=1",
                health_gate_results=[_gate_result()],
            ),
            _record(f"{exp_prefix}_002", denoising_score=1.1),
        )
    )


def _agent():
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = _llm_dispatch
        a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        return a


def _run_interp(ws, iteration, *, on: bool, history=None, scratch_tag="s"):
    inp = InterpretationInput(
        summaries=[_collapse_summary(f"wavenet_iter_{iteration:03d}")],
        storage={
            "backend": "local",
            "local": {"workspace": os.path.join(ws, f"scratch_{scratch_tag}"), "run_name": "r"},
        },
        iteration=iteration,
        enable_structured_health_feedback=on,
        collapse_fingerprint_history=history or {},
    )
    agent = _agent()
    output = agent.run(inp)
    return agent, output


def _write_digest_at_chain_path(ws, iter_idx, output):
    run_name = f"iter_{iter_idx:03d}"
    d = os.path.join(ws, run_name, f"iteration_{iter_idx:03d}")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"interpretation_{run_name}.json"), "w") as f:
        f.write(output.model_dump_json())


def _propose_prompt(interpretation, ws, *, on: bool) -> str:
    storage = StorageConfig(
        backend="local", local=LocalStorageConfig(workspace=ws, run_name="cb5c")
    )
    propose_input = local_full_context(
        interpretation, storage, enable_structured_health_feedback=on
    )
    return _build_reasoning_prompt(propose_input)


class TestCase1WorkspaceAFlagOn:
    def test_iter1_fingerprint_reaches_iter2_proposer_context(self, tmp_path):
        ws = str(tmp_path)
        assert ensure_run_invariants(ws, _invariants(ws, on=True)) == "created"

        # --- iteration 1: interpreter produces + persists the digest ---
        _, out1 = _run_interp(ws, 1, on=True, scratch_tag="i1")
        assert out1.per_model_collapse_fingerprints["wavenet"][0].signature == SIG
        _write_digest_at_chain_path(ws, 1, out1)

        # --- iteration-2 startup: typed restore from the digest ---
        restored = load_latest_fingerprint_history(ws, 2, [1])
        assert [o.iteration for o in restored["wavenet"][0].occurrences] == [1]

        # --- iteration 2: interpreter merges restored + fresh evidence ---
        _, out2 = _run_interp(
            ws,
            2,
            on=True,
            history={k: list(v) for k, v in restored.items()},
            scratch_tag="i2",
        )
        [entry] = out2.collapse_fingerprint_history["wavenet"]
        assert [o.iteration for o in entry.occurrences] == [1, 2]

        # --- the ACTUAL iteration-2 proposer context ---
        prompt = _propose_prompt(out2, ws, on=True)
        assert "[HEALTHGATE EVIDENCE]" in prompt
        assert f"- {SIG}: 2 occurrence(s) across iteration(s) 1, 2" in prompt

    def test_policy_stamps_agree_between_manifest_and_lock(self, tmp_path):
        import importlib.util
        import sys
        from pathlib import Path

        repo = Path(__file__).resolve().parents[3]
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        spec = importlib.util.spec_from_file_location(
            "roi_ws_cases", repo / "sdsc_submission_scripts" / "run_one_iteration.py"
        )
        roi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(roi)

        ws = str(tmp_path)
        lock = _invariants(ws, on=True)
        ensure_run_invariants(ws, lock)
        iter_dir = os.path.join(ws, "iter_001")
        os.makedirs(iter_dir, exist_ok=True)
        manifest = roi.write_manifest(
            iter_dir, "iter_001", results=[], health_feedback_policy=POLICY
        )
        stamped = manifest["health_feedback_policy"]
        assert stamped["enable_structured_health_feedback"] == (
            lock.structured_health_feedback_enabled
        )
        assert stamped["history_window_iterations"] == (
            lock.health_feedback_history_window_iterations
        )
        assert stamped["max_entries_per_model"] == (
            lock.health_feedback_history_max_entries_per_model
        )


class TestCase2WorkspaceAResumedOff:
    def test_flag_off_resume_rejected_naming_field_and_values(self, tmp_path):
        ws = str(tmp_path)
        ensure_run_invariants(ws, _invariants(ws, on=True))
        with pytest.raises(RunInvariantsViolation) as exc:
            ensure_run_invariants(ws, _invariants(ws, on=False))
        msg = str(exc.value)
        assert "structured_health_feedback_enabled" in msg
        assert "locked=True" in msg and "this run=False" in msg


class TestCase3WorkspaceBOffFromCreation:
    def test_no_treatment_text_but_recording_only_provenance(self, tmp_path):
        ws = str(tmp_path)
        assert ensure_run_invariants(ws, _invariants(ws, on=False)) == "created"

        agent, output = _run_interp(ws, 1, on=False, scratch_tag="b")

        # Interpreter context snapshot: the ACTUAL prompts the mock LLM
        # received carry no treatment text.
        for call in agent.bridge.generate.call_args_list:
            system_prompt = call.kwargs.get("system_prompt") or call.args[0]
            user_prompt = call.kwargs.get("user_prompt") or call.args[1]
            assert "HealthGate summary" not in user_prompt
            assert "[GATE " not in user_prompt
            assert "Structured HealthGate evidence" not in system_prompt

        # Recording-only provenance IS in the artifact...
        assert output.per_model_collapse_fingerprints["wavenet"][0].signature == SIG
        assert output.collapse_fingerprint_history["wavenet"]
        digest = json.loads(output.model_dump_json())
        assert digest["collapse_fingerprint_history"]["wavenet"]

        # ...and the proposer context snapshot has no treatment block.
        prompt = _propose_prompt(output, ws, on=False)
        assert "[HEALTHGATE EVIDENCE]" not in prompt
        assert SIG not in prompt
