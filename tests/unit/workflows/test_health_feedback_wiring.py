"""Workflow wiring for the structured-health-feedback policy (CB5-b).

Source-surface assertions in the PR 2 override-surface style: the
policy reaches the workflow's lock call, the interpreter input, and the
proposer protocol call — and the history carry is one-directional
(restored seed → interpreter merge output replaces the loop variable).
The end-to-end three-workspace pseudo cases land in CB5-c.
"""

import ast
import inspect
import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[3] / "src/workflows/model_exploration.py").read_text()


class TestLockCall:
    def test_workflow_lock_call_passes_policy_explicitly(self):
        # Preparation moved; both edges must still carry the run's policy.
        startup = (
            Path(__file__).resolve().parents[3] / "src/workflows/training_startup.py"
        ).read_text()
        for source, callee, expected in (
            (
                _SRC,
                "prepare_training_run",
                {
                    "launch": "launch",
                    "enable_structured_health_feedback": "enable_structured_health_feedback",
                },
            ),
            (
                startup,
                "build_run_invariants",
                {
                    "structured_health_feedback_enabled": "enable_structured_health_feedback",
                    "health_feedback_history_window_iterations": "launch.health_feedback_history_window_iterations",
                    "health_feedback_history_max_entries_per_model": "launch.health_feedback_history_max_entries_per_model",
                },
            ),
        ):
            calls = [
                n
                for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == callee
            ]
            assert len(calls) == 1, f"expected one live {callee} call"
            actual = {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}
            for name, value in expected.items():
                assert actual.get(name) == value, f"{callee} dropped/swapped {name}"


class TestThreading:
    def test_interpretation_input_receives_policy_and_history(self):
        block = re.search(
            r"interp_input = InterpretationInput\((.*?)\n        \)", _SRC, re.DOTALL
        ).group(1)
        # Step 09.5a C3: the VALUE now comes from the run-binding carrier.
        # The invariant this pin owns is unchanged — the workflow passes the
        # RUN'S policy, never a literal and never a renamed attribute — so
        # the pattern accepts the carrier spelling and rejects everything
        # else, exactly as C5d did for `launch.<field>`.
        assert re.search(
            r"enable_structured_health_feedback=\(?\s*(bindings\.)?"
            r"enable_structured_health_feedback\s*\)?",
            block,
        ), block
        assert "health_feedback_history_window_iterations=" in block
        assert "health_feedback_history_max_entries_per_model=" in block
        # Step 09.5a C4: the carry lives on ChainState; the wiring is the same.
        assert "collapse_fingerprint_history=state.current_collapse_fingerprint_history" in block

    def test_proposer_protocol_receives_flag(self):
        call = re.search(
            r"propose_input = local_full_context\((.*?)\n                \)", _SRC, re.DOTALL
        ).group(1)
        assert "enable_structured_health_feedback=" in call

    def test_history_carry_is_one_directional(self):
        """The loop variable is seeded from the restored history and
        REPLACED by the interpreter's merged output — never merged in the
        workflow, never read from proposer output or prompts."""
        # Step 09.5a C4 split SEED from REPLACE across two files, so the
        # assertion follows them. The invariant is unchanged and is still the
        # one that matters: exactly one seed, exactly one replacement, and no
        # reverse construction anywhere.
        from pathlib import Path as _P

        chain_state_src = (
            _P(__file__).resolve().parents[3] / "src/core/chain_state.py"
        ).read_text()
        flat_state = re.sub(r"\s+", " ", chain_state_src)
        assert (
            "state.current_collapse_fingerprint_history = dict( "
            "restored_collapse_fingerprint_history or {} )"
            in flat_state
            or "state.current_collapse_fingerprint_history = "
            "dict(restored_collapse_fingerprint_history or {})"
            in flat_state
        ), "ChainState no longer seeds the history from the restored value"

        flat = re.sub(r"\s+", " ", _SRC)
        assert (
            "state.current_collapse_fingerprint_history = "
            "dict(interpretation.collapse_fingerprint_history)"
            in flat
            or "state.current_collapse_fingerprint_history = dict( "
            "interpretation.collapse_fingerprint_history )"
            in flat
        ), "the interpreter's output no longer REPLACES the carried history"

        # Exactly ONE write site in the workflow (the replacement) and ONE in
        # the carrier (the seed) — a second write in either would be a merge,
        # which is what this one-directional carry forbids.
        workflow_writes = re.findall(r"state\.current_collapse_fingerprint_history\s*=(?!=)", _SRC)
        assert len(workflow_writes) == 1, workflow_writes
        carrier_writes = re.findall(
            r"state\.current_collapse_fingerprint_history\s*=(?!=)", chain_state_src
        )
        assert len(carrier_writes) == 1, carrier_writes
        assert "propose_output.collapse_fingerprint" not in _SRC
