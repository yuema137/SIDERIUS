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
        """Step 09.5a C3 split these across two owners, so the assertion follows
        them rather than the old flat signature.

        `enable_structured_health_feedback` is a LOCKED RUN INVARIANT and stays
        an explicit authority on the signature; the two retention bounds are
        transit configuration and moved to the launch carrier.

        The restored fingerprint history was "a chain-state seed that stays
        explicit until C4" — Step 10 / P1 C5 is where it moved, into the ONE
        `restored_state` carrier (09.5a's C4b hand-off). The assertion follows
        it there rather than being deleted: what this test is for is that the
        DEFAULTS are unchanged, and an absent restored state must still mean
        an empty history exactly as `None` did.
        """
        from core.resume import RestoredState
        from workflows.run_config import WorkflowLaunchConfig

        sig = inspect.signature(run_workflow)
        assert sig.parameters["enable_structured_health_feedback"].default is False
        assert sig.parameters["restored_state"].default is None
        # Cold start and "restored nothing" must remain indistinguishable to
        # every consumer: both are falsy, which is what the consumers test.
        assert RestoredState().collapse_fingerprint_history == {}

        launch = WorkflowLaunchConfig()
        assert launch.health_feedback_history_window_iterations == 3
        assert launch.health_feedback_history_max_entries_per_model == 8


class TestLockCall:
    def test_workflow_lock_call_passes_policy_explicitly(self):
        # The second element of the unpack is deliberately NOT pinned. It was
        # `_` while the effective-config path was discarded; Step 12 / PR-12a
        # C1 binds it (`_run_effective_health_config`) so the workflow can hand
        # the tuner the config the run actually reads. This test's subject is
        # the POLICY KWARGS, and hardcoding a throwaway binding name made it
        # fail for a change that has nothing to do with them.
        match = re.search(
            r"_run_invariants, \w+ = build_run_invariants\((.*?)\n    \)", _SRC, re.DOTALL
        )
        assert match is not None, "the workflow's build_run_invariants call site was not found"
        call = match.group(1)
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

        chain_state_src = (_P(__file__).resolve().parents[3] / "core/chain_state.py").read_text()
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
