"""V21 PR G G3 — measurement-identity batch alignment (Option A).

Pins the narrowed G3 contract (PR G doc §0.R.5 / §0.R.12):

* ``resolve_inference_batch`` prefers an explicit probe-derived batch and
  falls back to the registry table only when none exists — mirroring
  ``execute_inference``'s own resolution rule (payload truth, NOT a live
  measurement-path equality: the live path requests training-phase
  measurements only).
* **The 0.R.12 safety pin** — the property that makes G3 a safe
  one-argument change: ``planned_config_hash`` and TRAINING-phase
  ``compare_identities`` are batch-insensitive (payload 25 → 64 changes
  neither), while ``inference_workload_hash`` DOES change with the batch
  (what stops a batch-1 measurement answering for batch 25), and an
  INFERENCE-phase comparison still flags the mismatch (phase-aware
  semantics unchanged).
* **Delete-the-hop** on the tuner's pre-phase site
  (``_handle_prephase_gpu_measurement``): the hint present in
  ``active_params`` reaches the spec's planned identity AND its
  ``inference_batch_size``; a hint-less attempt records the table value
  (no fabricated hint).
"""

from __future__ import annotations

import pytest

import nodes.ml_hyperparameter_tune_agent as tuner_mod
from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    build_realized_identity,
    compare_identities,
    resolve_inference_batch,
)

_MC = {"segmentation_size": 16000}
_TC = {"batch_size": 1, "optimizer_type": "adam"}


class TestResolveInferenceBatch:
    def test_explicit_beats_table(self):
        """MUTATION PIN: reversing the precedence returns punet's table 25
        and fails here."""
        assert resolve_inference_batch("punet", explicit=64) == 64

    def test_absent_explicit_is_todays_table_value(self):
        assert resolve_inference_batch("punet") == 25
        assert resolve_inference_batch("rnn", explicit=None) == 10
        assert resolve_inference_batch("g3_unregistered_model") == 25

    @pytest.mark.parametrize("bad", [0, -3, True, False, 25.0, "25"])
    def test_invalid_explicit_rejected_loudly(self, bad):
        with pytest.raises(ValueError, match="explicit inference batch"):
            resolve_inference_batch("punet", explicit=bad)


class Test0R12SafetyPin:
    def test_planned_config_hash_is_batch_insensitive(self):
        """The 25→64 payload change must not move the training identity."""
        at_25 = build_planned_identity(
            model_type="punet", model_config=_MC, train_config=_TC, inference_batch_size=25
        )
        at_64 = build_planned_identity(
            model_type="punet", model_config=_MC, train_config=_TC, inference_batch_size=64
        )
        assert at_25.planned_config_hash == at_64.planned_config_hash
        assert at_25.inference_batch_size == 25
        assert at_64.inference_batch_size == 64

    def test_inference_workload_hash_changes_with_the_batch(self):
        """The workload's own identity MUST move with the batch — this is
        what stops a batch-25 measurement answering for batch 64."""
        at_25 = build_planned_identity(
            model_type="punet", model_config=_MC, train_config=_TC, inference_batch_size=25
        )
        at_64 = build_planned_identity(
            model_type="punet", model_config=_MC, train_config=_TC, inference_batch_size=64
        )
        none = build_planned_identity(
            model_type="punet", model_config=_MC, train_config=_TC, inference_batch_size=None
        )
        assert at_25.inference_workload_hash != at_64.inference_workload_hash
        assert none.inference_workload_hash is None

    def _pair(self, planned_batch: int, realized_batch: int):
        planned = build_planned_identity(
            model_type="punet",
            model_config=_MC,
            train_config=_TC,
            inference_batch_size=planned_batch,
        )
        realized = build_realized_identity(
            model_type="punet",
            optimizer_type="adam",
            seg_size=16000,
            batch_size=1,
            precision="float32",
            parameter_count=1000,
            trainable_parameter_count=1000,
            inference_batch_size=realized_batch,
        )
        return planned, realized

    def test_training_phase_comparison_ignores_the_inference_batch(self):
        planned, realized = self._pair(64, 25)
        mismatch = compare_identities(
            planned, realized, requested_id="rid", reported_id="rid", phase="training"
        )
        assert mismatch is None

    def test_inference_phase_comparison_still_flags_the_mismatch(self):
        """Phase-aware semantics unchanged: the future inference-phase
        caller keeps its 3.47x-under-read protection."""
        planned, realized = self._pair(64, 25)
        mismatch = compare_identities(
            planned, realized, requested_id="rid", reported_id="rid", phase="inference"
        )
        assert mismatch == "inference_batch_size_mismatch"


class _SpecCaptured(Exception):
    """Short-circuits the pre-phase helper after the spec is built."""

    def __init__(self, spec):
        self.spec = spec


class _FakeDeviceSandbox:
    base_dir = "/tmp/g3_prephase"
    plugin_dir = None
    loss_dir = None

    def __init__(self, device_identity):
        self.device_identity = device_identity


class _FakeAgentInput:
    gpu_pair_ceiling_gib = None
    data_dir = None


class TestPrephasePayloadTruth:
    """DELETE-THE-HOP: the tuner's pre-phase site resolves the identity
    batch from ``active_params`` — dropping the ``explicit=`` argument at
    tuner :760 fails the hinted case below."""

    def _captured_spec(self, monkeypatch, active_params: dict):
        from core.runtime_control import gpu_measurement_runner
        from core.runtime_control.gpu_accounting import DeviceIdentity

        def _capture(spec, *, device):
            raise _SpecCaptured(spec)

        monkeypatch.setattr(gpu_measurement_runner, "run_prephase_measurement", _capture)
        device = DeviceIdentity(uuid="GPU-g3-test", physical_index=0)
        with pytest.raises(_SpecCaptured) as excinfo:
            tuner_mod._handle_prephase_gpu_measurement(
                agent_input=_FakeAgentInput(),
                sandbox=_FakeDeviceSandbox(device),
                is_trial=False,
                active_params=active_params,
                exp_id="g3_exp",
                model_type="punet",
                file_index=None,
                record_params={},
                expert_advice_str="",
                hypothesis="",
                round_index=1,
                attempt_in_round=1,
            )
        return excinfo.value.spec

    def test_hint_reaches_planned_identity_and_spec(self, monkeypatch):
        spec = self._captured_spec(
            monkeypatch,
            {
                "model_type": "punet",
                "model_config": _MC,
                "train_config": _TC,
                "inference_batch": 64,
            },
        )
        assert spec.inference_batch_size == 64
        assert spec.request.planned_identity.inference_batch_size == 64

    def test_no_hint_records_the_table_value_not_a_fabrication(self, monkeypatch):
        spec = self._captured_spec(
            monkeypatch,
            {"model_type": "punet", "model_config": _MC, "train_config": _TC},
        )
        assert spec.inference_batch_size == 25
        assert spec.request.planned_identity.inference_batch_size == 25
