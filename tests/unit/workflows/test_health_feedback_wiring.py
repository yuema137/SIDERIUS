"""Workflow wiring for the structured-health-feedback policy (CB5-b).

Source-surface assertions in the PR 2 override-surface style: the
policy reaches the workflow's lock call, the interpreter input, and the
proposer protocol call — and the history carry is one-directional
(restored seed → interpreter merge output replaces the loop variable).
The end-to-end three-workspace pseudo cases land in CB5-c.
"""

import inspect
import re
from pathlib import Path

from workflows.model_exploration import run_workflow

_SRC = (Path(__file__).resolve().parents[3] / "workflows/model_exploration.py").read_text()


class TestRunWorkflowSignature:
    def test_policy_params_with_locked_defaults(self):
        sig = inspect.signature(run_workflow)
        assert sig.parameters["enable_structured_health_feedback"].default is False
        assert sig.parameters["health_feedback_history_window_iterations"].default == 3
        assert sig.parameters["health_feedback_history_max_entries_per_model"].default == 8
        assert sig.parameters["restored_collapse_fingerprint_history"].default is None


class TestLockCall:
    def test_workflow_lock_call_passes_policy_explicitly(self):
        call = re.search(
            r"_run_invariants, _ = build_run_invariants\((.*?)\n    \)", _SRC, re.DOTALL
        ).group(1)
        for kwarg in (
            "structured_health_feedback_enabled=enable_structured_health_feedback",
            "health_feedback_history_window_iterations=",
            "health_feedback_history_max_entries_per_model=",
        ):
            assert kwarg in call, f"workflow lock call missing {kwarg}"


class TestThreading:
    def test_interpretation_input_receives_policy_and_history(self):
        block = re.search(
            r"interp_input = InterpretationInput\((.*?)\n        \)", _SRC, re.DOTALL
        ).group(1)
        assert "enable_structured_health_feedback=enable_structured_health_feedback" in block
        assert "health_feedback_history_window_iterations=" in block
        assert "health_feedback_history_max_entries_per_model=" in block
        assert "collapse_fingerprint_history=current_collapse_fingerprint_history" in block

    def test_proposer_protocol_receives_flag(self):
        call = re.search(
            r"propose_input = local_full_context\((.*?)\n                \)", _SRC, re.DOTALL
        ).group(1)
        assert "enable_structured_health_feedback=" in call

    def test_history_carry_is_one_directional(self):
        """The loop variable is seeded from the restored history and
        REPLACED by the interpreter's merged output — never merged in the
        workflow, never read from proposer output or prompts."""
        flat = re.sub(r"\s+", " ", _SRC)
        assert (
            "current_collapse_fingerprint_history: dict = dict( "
            "restored_collapse_fingerprint_history or {} )"
            in flat
            or "current_collapse_fingerprint_history: dict = "
            "dict(restored_collapse_fingerprint_history or {})"
            in flat
        )
        assert (
            "current_collapse_fingerprint_history = "
            "dict(interpretation.collapse_fingerprint_history)" in flat
        )
        # Exactly the seed (annotated) + the replacement assignment — no
        # other write site, i.e. no reverse construction anywhere.
        assignments = re.findall(r"current_collapse_fingerprint_history(?::\s*dict)?\s*=", _SRC)
        assert len(assignments) == 2
        assert "propose_output.collapse_fingerprint" not in _SRC
