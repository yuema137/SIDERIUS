"""Step 11 C2 (F-11-1) — a host-RAM OOM must not be invisible to the tuner.

The defect. ``core/sandbox_executor.py`` has produced the status
``oom_host_ram`` at three sites since the 2026-04-20 incident — training
(:1654), inference (:1923), scoring (:2116). Repo-wide, **nothing read
it**: every other occurrence was the message text or a comment. The tuner
asked ``status.get("status") == "error"`` directly, so a host-OOM training
failure missed the failure branch and was carried forward as a normal
outcome — a crashed subprocess treated as a trained model.

What this module owns, and what it deliberately does not:

* the CONSUMER contract — the failure predicate covers exactly `error`
  and `oom_host_ram`, and the two production branches ask it;
* the Q-11-3 = A boundary — the record a host OOM produces does NOT carry
  an ``_oom``-suffixed status, so the planner's "NOT ATTRIBUTED" note does
  not newly render and **planner-facing prompt bytes do not change**. That
  is the executable form of "Gate 1 NOT REQUIRED", asserted through the
  real gating predicate rather than by assertion in prose;
* it does NOT consolidate the five OOM matchers (F-11-9, non-goal) and
  does NOT invent a fourth failure state — a bare SIGKILL stays
  unattributable.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from nodes.ml_hyperparameter_tune_agent.records import (
    HOST_RAM_OOM_STATUS,
    _build_execution_failure_record,
    is_execution_failure,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

_HOST_OOM_MESSAGE = (
    "[oom_host_ram] Host RAM exhaustion detected — either RLIMIT_AS "
    "refused an allocation or the kernel OOM-killer reaped the child."
)


def _failure_record(phase: str, *, status: str, message: str) -> dict:
    return _build_execution_failure_record(
        {"status": status, "message": message},
        phase=phase,
        exp_id="c2",
        model_type="fcnet",
        file_index=0,
        record_params={},
        expert_advice_str="",
        hypothesis="",
        round_index=0,
        attempt_in_round=0,
    )


class TestTheFailurePredicate:
    """The single authority both production branches now ask."""

    def test_host_oom_is_a_failure(self):
        assert is_execution_failure({"status": HOST_RAM_OOM_STATUS}) is True

    def test_plain_error_is_still_a_failure(self):
        assert is_execution_failure({"status": "error"}) is True

    def test_success_is_not(self):
        assert is_execution_failure({"status": "success"}) is False

    def test_no_fourth_state_is_invented(self):
        """A bare `-9` SIGKILL must remain unattributable — the sandbox
        already returns `error` for it and `failure_attribution`
        deliberately answers `unknown`. The predicate must not grow a
        third member to "handle" it.
        """
        assert is_execution_failure({"status": "skipped_resource_admission"}) is False
        assert is_execution_failure({"status": "wall_clock_timeout"}) is False
        assert is_execution_failure({}) is False

    def test_the_status_string_agrees_with_the_producer(self):
        """The consumer's constant and the producer's literal are the same
        string. Two independently-spelled statuses is how the defect
        existed at all.
        """
        src = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        assert (
            src.count(f'status = "{HOST_RAM_OOM_STATUS}" if _is_oom_failure(e) else "error"') == 3
        )


class TestBothProductionBranchesAskIt:
    """Reachability: the predicate must be on the production path, not
    merely importable. A test that only calls the helper would pass with
    the branches left as they were — which is exactly how F-11-1 survived.
    """

    @staticmethod
    def _execution_tree() -> ast.Module:
        return ast.parse(
            (REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "execution.py").read_text(
                encoding="utf-8"
            )
        )

    def test_the_two_phase_branches_call_the_authority(self):
        calls = [
            node
            for node in ast.walk(self._execution_tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "is_execution_failure"
        ]
        assert len(calls) == 2, (
            "training and inference must both route through the one "
            f"authority; found {len(calls)} call site(s)"
        )

    def test_no_branch_compares_the_status_string_directly(self):
        """The replaced form must not come back beside the authority."""
        src = (REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "execution.py").read_text(
            encoding="utf-8"
        )
        assert 'train_status.get("status") == "error"' not in src
        assert 'inf_status.get("status") == "error"' not in src


class TestTheRecordAHostOomProduces:
    """Q-11-3 = A, asserted through the real gating predicate."""

    @pytest.mark.parametrize(
        ("phase", "expected"),
        [("training", "error_training"), ("inference", "error_inference")],
    )
    def test_a_host_oom_records_the_plain_phase_failure(self, phase, expected):
        record = _failure_record(phase, status=HOST_RAM_OOM_STATUS, message=_HOST_OOM_MESSAGE)
        assert record["status"] == expected

    @pytest.mark.parametrize("phase", ["training", "inference"])
    def test_the_planner_oom_note_does_not_render_for_it(self, phase):
        """The gate is `str(status).endswith("_oom")`
        (`agent/prompts.py:1265-1270`). `oom_host_ram` ends in `_ram`, and
        the RECORD's status is the plain phase failure, so neither string
        can trip it. This is what makes Gate 1 NOT REQUIRED executable.
        """
        record = _failure_record(phase, status=HOST_RAM_OOM_STATUS, message=_HOST_OOM_MESSAGE)
        assert not str(record["status"]).endswith("_oom")
        assert not HOST_RAM_OOM_STATUS.endswith("_oom")

    @pytest.mark.parametrize(
        ("phase", "expected"),
        [("training", "error_training_oom"), ("inference", "error_inference_oom")],
    )
    def test_device_oom_classification_is_unchanged(self, phase, expected):
        """A real CUDA OOM must still reach the `_oom` family — C2 must not
        blur the device/host distinction it exists to preserve.
        """
        record = _failure_record(
            phase, status="error", message="CUDA out of memory. Tried to allocate 2.00 GiB"
        )
        assert record["status"] == expected
        assert str(record["status"]).endswith("_oom")

    @pytest.mark.parametrize(
        ("phase", "expected"),
        [("training", "error_training"), ("inference", "error_inference")],
    )
    def test_ordinary_errors_are_unchanged(self, phase, expected):
        record = _failure_record(phase, status="error", message="ValueError: bad config")
        assert record["status"] == expected


_NOTE_HEADING = "NOTE - OUT-OF-MEMORY NOT ATTRIBUTED TO YOUR CONFIG"


class TestPlannerPromptBytes:
    """The Q-11-3 = A parity claim, driven through the REAL renderer.

    Not a re-implementation of the gating predicate — that would be the
    self-referential shape the repository forbids. The production
    `get_planner_user_prompt` is called with a one-record history and the
    rendered bytes are inspected.
    """

    @staticmethod
    def _render(record: dict) -> str:
        from agent.prompts import get_planner_user_prompt

        return get_planner_user_prompt([record])

    def test_a_host_oom_renders_no_unattributed_oom_note(self):
        prompt = self._render(
            _failure_record("training", status=HOST_RAM_OOM_STATUS, message=_HOST_OOM_MESSAGE)
        )
        assert _NOTE_HEADING not in prompt, (
            "a host-RAM OOM must not newly render the NOT ATTRIBUTED note — "
            "that is option B, which would require Gate 1"
        )

    def test_the_note_still_renders_for_the_device_oom_it_was_written_for(self):
        """The counterfactual. Without it the test above would pass on a
        renderer that had stopped emitting the note at all.
        """
        prompt = self._render(
            _failure_record(
                "training",
                status="error",
                message="CUDA out of memory. Tried to allocate 2.00 GiB",
            )
        )
        assert _NOTE_HEADING in prompt

    def test_a_host_oom_renders_the_same_bytes_as_an_ordinary_failure(self):
        """The strongest available parity statement: to the planner, a
        host-OOM attempt is indistinguishable from any other crashed
        subprocess apart from the message text the sandbox already wrote.
        """
        host = self._render(
            _failure_record("training", status=HOST_RAM_OOM_STATUS, message=_HOST_OOM_MESSAGE)
        )
        plain = self._render(_failure_record("training", status="error", message=_HOST_OOM_MESSAGE))
        assert host == plain
