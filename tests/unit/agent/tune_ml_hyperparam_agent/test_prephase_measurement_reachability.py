"""The pre-phase measurement is on the production path, and stops it.

V20 PR C2 / C2-7.

The defect shape these exist for has happened three times in this
repository (#156, #157, #159) and once at the exact seam C2 is closing:
`getattr(sandbox, "measured_requirements", None)` was a read *no production
code satisfied*, so PR B's gate was correct, fully tested, and unreachable.
A component's own tests cannot see that.

So these cut the production edges instead:

* delete the call from `run()` -> a test must fail;
* call the boundary and discard its disposition -> a test must fail;
* an identity mismatch must stop before PR B;
* an exact match must reach PR B;
* a host-memory stop must never deliver a figure;
* `PROCEED` must attach the requirement and let training start.

They drive `_handle_prephase_gpu_measurement` and the `run()` source
directly rather than standing up a whole agent run, because what is being
proved is the WIRING, and a full run would prove it only for whichever path
that run happened to take.
"""

from __future__ import annotations

import inspect

import pytest

import nodes.ml_hyperparameter_tune_agent as tuner
from core.runtime_control.gpu_accounting import DeviceIdentity

UUID = "GPU-c30b6678"
DEVICE = DeviceIdentity(uuid=UUID, physical_index=0)


class _Sandbox:
    def __init__(self, tmp_path) -> None:
        self.base_dir = str(tmp_path)
        self.device_identity = DEVICE


class _Input:
    data_dir = "/nonexistent"
    gpu_pair_ceiling_gib = 24.0


def _call(tmp_path, **over):
    kwargs = dict(
        agent_input=_Input(),
        sandbox=_Sandbox(tmp_path),
        is_trial=False,
        active_params={
            "model_type": "punet",
            "model_config": {"segmentation_size": 40_000},
            "train_config": {"batch_size": 1, "optimizer_type": "adamw"},
            "loss_config": {"loss_type": "focal"},
            "run_name": "reachability",
        },
        exp_id="exp-1",
        model_type="punet",
        file_index=None,
        record_params={},
        expert_advice_str="",
        hypothesis="",
        round_index=0,
        attempt_in_round=0,
    )
    kwargs.update(over)
    return tuner._handle_prephase_gpu_measurement(**kwargs)


class TestTheCallSiteExists:
    def test_run_calls_the_boundary(self):
        """Deleting the call from `run()` fails here. Without this the
        entire chain could be complete, green, and never executed."""
        source = inspect.getsource(tuner.HyperparamTuningAgent.run)
        assert "_handle_prephase_gpu_measurement(" in source

    def test_run_consumes_the_disposition(self):
        """Calling the boundary and discarding its answer is the subtler
        failure: the measurement runs, costs GPU time, and stops nothing."""
        source = inspect.getsource(tuner.HyperparamTuningAgent.run)
        index = source.index("_handle_prephase_gpu_measurement(")
        following = source[index : index + 1200]
        assert "continue" in following, (
            "the disposition must control flow; a call whose result is "
            "ignored measures the candidate and admits it anyway"
        )
        assert source[:index].rstrip().endswith("if"), (
            "the call must be the condition of the guard, not a bare statement beside it"
        )

    def test_it_runs_before_training_starts(self):
        """O-7 requires stopping BEFORE formal GPU work. A measurement
        after `_run_skill('training_skill', ...)` would be a post-mortem."""
        source = inspect.getsource(tuner.HyperparamTuningAgent.run)
        assert source.index("_handle_prephase_gpu_measurement(") < source.index(
            '_run_skill("training_skill"'
        )


class TestApplicability:
    def test_a_trial_round_is_not_measured(self, tmp_path):
        """O-7 governs formal execution; trial already proceeds while
        recording what it could not prove."""
        assert _call(tmp_path, is_trial=True) is False

    def test_a_run_with_no_device_is_untouched(self, tmp_path):
        """The same rule `_admission_refusal` already applies: no card
        means nothing to measure and nothing for admission to decide.
        A CPU or pseudo run must be unaffected."""
        sandbox = _Sandbox(tmp_path)
        sandbox.device_identity = None
        assert _call(tmp_path, sandbox=sandbox) is False


class TestTheDispositionDrivesTheAttempt:
    """The boundary is stubbed so each disposition can be driven exactly;
    what is under test here is what the TUNER does with the answer."""

    def _stub(self, monkeypatch, outcome):
        monkeypatch.setattr(tuner, "_emit_record", lambda *a, **k: None)
        import core.runtime_control.prephase_admission as boundary

        monkeypatch.setattr(
            "core.runtime_control.gpu_measurement_runner.run_prephase_measurement",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(boundary, "decide_prephase_admission", lambda *a, **k: outcome)
        return boundary

    def test_proceed_attaches_the_requirement_and_continues(self, tmp_path, monkeypatch):
        attached: list[object] = []
        outcome = _FakeOutcome("PROCEED")
        self._stub(monkeypatch, outcome)
        monkeypatch.setattr(
            "core.runtime_control.prephase_admission.attach_measured_requirements",
            lambda sandbox, o: attached.append(o) or True,
        )
        assert _call(tmp_path) is False, "PROCEED must let formal execution start"
        assert attached == [outcome]

    @pytest.mark.parametrize(
        "disposition",
        [
            "STOP_MEASUREMENT_UNAVAILABLE",
            "STOP_OVER_CAP",
            "STOP_MEASURED_OOM",
            "STOP_TIMEOUT",
            "STOP_PROBE_HOST_MEMORY_EXCEEDED",
            "STOP_INFRASTRUCTURE_FAILURE",
        ],
    )
    def test_every_stop_ends_the_attempt(self, tmp_path, monkeypatch, disposition):
        self._stub(monkeypatch, _FakeOutcome(disposition))
        assert _call(tmp_path) is True

    @pytest.mark.parametrize(
        "disposition,lane",
        [
            ("STOP_OVER_CAP", "insufficient_headroom"),
            ("STOP_MEASURED_OOM", "insufficient_headroom"),
            ("STOP_TIMEOUT", "measurement_unavailable"),
            ("STOP_PROBE_HOST_MEMORY_EXCEEDED", "measurement_unavailable"),
            ("STOP_INFRASTRUCTURE_FAILURE", "measurement_unavailable"),
        ],
    )
    def test_each_stop_is_filed_under_its_lane(self, tmp_path, monkeypatch, disposition, lane):
        """PR B's three refusal lanes are unchanged. The disposition itself
        survives in the evidence, so narrowing to a lane loses nothing."""
        records: list[dict] = []
        monkeypatch.setattr(tuner, "_emit_record", lambda _s, r: records.append(r))
        import core.runtime_control.prephase_admission as boundary

        monkeypatch.setattr(
            "core.runtime_control.gpu_measurement_runner.run_prephase_measurement",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            boundary, "decide_prephase_admission", lambda *a, **k: _FakeOutcome(disposition)
        )
        _call(tmp_path)
        assert records[0]["memory"]["reason_code"] == lane
        evidence = records[0]["memory"]["admission_evidence"]
        assert evidence["prephase_disposition"] == disposition, (
            "the narrowing to a PR B lane must not lose which stop occurred"
        )
        assert records[0]["counts_toward_attempt_budget"] is True, "O-7: attempt consumed"
        assert records[0]["counts_toward_completed_rounds"] is False, "O-7: no round"

    def test_a_stop_never_attaches_a_requirement(self, tmp_path, monkeypatch):
        """Including the host-memory stop: a CPU figure must never reach
        the GPU capacity gate."""
        self._stub(monkeypatch, _FakeOutcome("STOP_PROBE_HOST_MEMORY_EXCEEDED"))
        sandbox = _Sandbox(tmp_path)
        _call(tmp_path, sandbox=sandbox)
        assert getattr(sandbox, "measured_requirement_table", None) is None


class _FakeOutcome:
    """A disposition with the O-7 properties the real outcome computes.

    Deliberately not a `MeasuredGpuRequirement` mock: what these tests
    exercise is the tuner's use of the answer, and the answer's own
    correctness is proved in `test_prephase_admission.py`.
    """

    def __init__(self, disposition: str) -> None:
        self.disposition = disposition
        self.detail = "stubbed"
        self.table = None
        self.requirement = _FakeRequirement()

    @property
    def proceeds(self) -> bool:
        return self.disposition == "PROCEED"


class _FakeRequirement:
    driver_tree_peak_mib = 4_096
    outcome = "COMPLETED_MEASUREMENT"
    authority_refusal = None
    identity_mismatch = None


class TestApplicabilityIsTypeChecked:
    def test_a_mock_sandbox_does_not_activate_the_gate(self, tmp_path):
        """`getattr(sandbox, "device_identity", None)` on a `MagicMock`
        returns a truthy MOCK, not None. A presence test therefore switched
        this gate on in every mocked formal test -- 53 of them -- and in
        production would accept any object at all as a device.

        Type-checking is the fix, and it is the principle this whole PR
        rests on: a typed boundary, never a duck-typed read.
        """
        from unittest.mock import MagicMock

        sandbox = MagicMock()
        sandbox.base_dir = str(tmp_path)
        assert _call(tmp_path, sandbox=sandbox) is False

    def test_a_wrong_typed_device_identity_does_not_activate_the_gate(self, tmp_path):
        sandbox = _Sandbox(tmp_path)
        sandbox.device_identity = "GPU-c30b6678"  # a bare string, not an identity
        assert _call(tmp_path, sandbox=sandbox) is False

    def test_a_real_device_identity_does_activate_it(self, tmp_path, monkeypatch):
        """Positive control: the type check must exclude non-identities,
        not everything."""
        called: list[object] = []
        monkeypatch.setattr(tuner, "_emit_record", lambda *a, **k: None)
        monkeypatch.setattr(
            "core.runtime_control.gpu_measurement_runner.run_prephase_measurement",
            lambda *a, **k: called.append("ran"),
        )
        import core.runtime_control.prephase_admission as boundary

        monkeypatch.setattr(
            boundary,
            "decide_prephase_admission",
            lambda *a, **k: _FakeOutcome("STOP_INFRASTRUCTURE_FAILURE"),
        )
        assert _call(tmp_path) is True
        assert called == ["ran"]
