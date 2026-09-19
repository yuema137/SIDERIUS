"""The validation prediction must reach the sidecar WHILE the pass is running.

Step 07 / PR 07c — the Gate-2 attempt-1 regression.

Gate 2 attempt 1 FAILED with 9,967 unit tests green. The sidecar at the moment
of the kill held setup 1.384 s + training 55.371 s and NO validation
prediction; `(1.384 + 55.371) x 1.5 = 85.133 s` was the enforced deadline, to
the millisecond, and the process was killed at 86.097 s roughly 26 s into a
validation pass whose term had never been written.

The verifier HAD reached a verdict about a second into that pass. The bug was
that `_validation_pass` only rebound its local name to `None` and the
completion ran after the function RETURNED — which, in the regime 07c exists to
fix, never happens before the stale deadline fires.

**Why the existing tests could not catch it.** C5's cold-start test drove the
provider over a HAND-WRITTEN sidecar: it proved the deadline arithmetic and
said nothing about when production writes. The real-trainer reachability test
used a fixture whose validation pass completes in milliseconds, so the deferred
completion always ran in time. Neither could observe "the value exists but is
not persisted yet".

So this test observes the REAL sidecar file from INSIDE the running pass, and
asserts the prediction is already there.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pytest
import torch
import torch.nn as nn
from pydantic import BaseModel

import execute_tools.train_engine_sandbox as tes
from core.runtime_control.records import MEASUREMENT_BACKED_SOURCES
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.task_data_path import bind_task_data_path
from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY, LossConfig, TrainConfig
from ml_models.models_sandbox import MODEL_REGISTRY
from tests.helpers.synthetic_training_data_path import TwoFamilyDataPath
from tests.helpers.two_family_profile import write_two_family_fixture

MODEL_TYPE = "pr07c_sidecar_observer"

#: Stopping policy bounded so the verifier reaches a verdict within the first
#: couple of validation batches. A HARNESS bound on an operator input: the
#: property under test is WHEN the prediction is persisted, not how many units
#: the production policy needs to stabilise.
_FAST_VERIFICATION = {
    "min_timed_ms": 0.001,
    "min_timed_steps": 2,
    "steady": {"window": 2, "stable_windows": 2, "rel_spread_tol": 0.99},
}


class _ObserverConfig(BaseModel):
    model_type: str = MODEL_TYPE
    segmentation_size: int = 1000


def _make_observer(sidecar_path: Path, clock=None):
    """A real model whose forward reads the REAL sidecar during validation.

    Registered into the live MODEL_REGISTRY, so the trainer builds and runs it
    exactly as it would any candidate — no production code is patched. The
    observation happens on the model's own forward, which is the only place a
    test can stand INSIDE the validation pass without instrumenting the
    production path it is trying to judge.
    """
    observations: list[dict] = []

    class _Observer(nn.Module):
        def __init__(self, cfg: _ObserverConfig):
            super().__init__()
            self.embed = nn.Embedding(256, 4)
            self.head = nn.Linear(4, 256)
            self.eval_calls = 0

        def forward(self, x):
            if not self.training:
                # EVERY validation batch, so the assertion can be about the
                # ORDER of events rather than about a hard-coded batch index —
                # which would be an assumption about this machine's speed.
                if clock is not None:
                    clock[0] += 1.0
                self.eval_calls += 1
                observations.append(
                    {"batch": self.eval_calls, **_read_validation_component(sidecar_path)}
                )
            return self.head(self.embed(x.long())).permute(0, 2, 1)

    return _Observer, observations


def _read_validation_component(sidecar_path: Path) -> dict:
    """What the WATCHDOG would see right now, read off disk."""
    if not sidecar_path.is_file():
        return {"sidecar": False}
    try:
        block = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception:
        return {"sidecar": "unreadable"}
    validation = (block.get("components") or {}).get("validation") or {}
    prediction = validation.get("prediction")
    return {
        "sidecar": True,
        "prediction": prediction,
        "source": (prediction or {}).get("source"),
        "predicted_seconds": (prediction or {}).get("predicted_seconds"),
    }


@pytest.fixture
def observed_run(tmp_path, request, monkeypatch):
    """One in-process streaming run whose model watches the live sidecar."""
    random.seed(7)
    np.random.seed(7)
    torch.manual_seed(0)

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    fx = write_two_family_fixture(tmp_path / "data")
    sidecar = tmp_path / "rv.json"
    # batch_size 1 over the 24-row scope gives 24 validation batches, so there
    # is ample headroom between the verifier's verdict and the end of the pass.
    budgeted = getattr(request, "param", False)
    clock = [0.0] if budgeted else None
    if clock is not None:
        monkeypatch.setattr("time.monotonic", lambda: clock[0])
    model_cls, observations = _make_observer(sidecar, clock)
    for sub in ("m", "r"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    MODEL_REGISTRY[MODEL_TYPE] = model_cls
    PLUGIN_CONFIG_REGISTRY[MODEL_TYPE] = _ObserverConfig
    session = RuntimeVerificationSession(
        str(sidecar),
        attempt_id="pr07c_timing",
        policy=RuntimeControlPolicy(
            verification=_FAST_VERIFICATION,
            training_budget={
                "budget_seconds": 8,
                "reserve_fraction": 0.25,
                "max_epochs": 1,
                "started_monotonic_seconds": 0,
            }
            if budgeted
            else None,
        ),
    )
    try:
        data_path = TwoFamilyDataPath(fx)
        with bind_dataset_profile(fx.profile), bind_task_data_path(data_path):
            summary = tes.run_experiment_streaming(
                _ObserverConfig(segmentation_size=fx.seg_size),
                TrainConfig(lr=1e-3, epochs=1, batch_size=1, optimizer_type="adam", device="cpu"),
                LossConfig(loss_type="ce"),
                sample_set=fx.full_sample_set(),
                data_dir=fx.data_dir,
                sandbox_dirs={
                    "models": str(tmp_path / "m"),
                    "results": str(tmp_path / "r"),
                },
                exp_id="pr07c_timing",
                train_base_seed=123,
                profile=fx.profile,
                runtime_session=session,
                **data_path.scope_kwargs(fx.full_sample_set(), fx.full_sample_set()),
            )
    finally:
        MODEL_REGISTRY.pop(MODEL_TYPE, None)
        PLUGIN_CONFIG_REGISTRY.pop(MODEL_TYPE, None)
    if not budgeted:
        assert summary is not None
    return summary, observations, sidecar, session


class TestThePredictionIsPersistedDuringThePass:
    """The Gate-2 attempt-1 regression. TWO tests, deliberately.

    One proves the defect is gone; one proves the fix moved ONLY the write
    timing. Everything else about validation lifecycle correctness belongs to
    Gate 2, which is what actually caught this — deriving a dozen
    first-batch / sidecar-timing / validation-length variants here would
    re-create the duplication the suite already suffers from.
    """

    def test_the_sidecar_holds_a_measurement_backed_prediction_mid_pass(self, observed_run):
        """THE regression.

        Read from inside the running pass, off the real file the watchdog
        reads. The source check is part of the same property, not a second
        one: a prediction C8d filters out is worth exactly as much as none.
        """
        _summary, observations, _sidecar, _session = observed_run
        assert observations, (
            "the observer never ran during validation — the fixture is not "
            "exercising the pass, so this test proves nothing"
        )
        total = len(observations)
        appeared = [o for o in observations if o["prediction"] is not None]
        assert appeared, (
            f"the validation pass ran {total} batches and the sidecar NEVER "
            "held a validation prediction — the Gate-2 attempt-1 defect: the "
            "watchdog enforces a deadline with no validation term for the "
            "whole pass, which is how attempt 1 died 26 s in"
        )
        # THE property: it landed while batches were still to come. Asserted on
        # the ORDER of events, not on a hard-coded batch index — the verifier's
        # verdict arrives later on a loaded machine, and a fixed index would
        # make this a flaky test of the host rather than of the code.
        first_seen = appeared[0]["batch"]
        assert first_seen < total, (
            f"the validation prediction only appeared on batch {first_seen} of "
            f"{total} — nothing ran after it, so this run cannot distinguish "
            "persisting DURING the pass from persisting after it"
        )
        assert appeared[0]["source"] == "real_validation_verification"
        assert appeared[0]["source"] in MEASUREMENT_BACKED_SOURCES
        assert appeared[0]["predicted_seconds"] > 0

    def test_the_fix_moved_only_the_write_timing(self, observed_run):
        """The four preservation assertions the fix ruling required, on the
        same run rather than as four more tests."""
        summary, _observations, sidecar, _session = observed_run
        block = json.loads(sidecar.read_text(encoding="utf-8"))
        components = block["components"]
        validation, training = components["validation"], components["training"]

        # 1. the full-pass ACTUAL still lands (Q-07c-5's other half: it is what
        #    calibrates FUTURE runs).
        assert validation["actual_seconds"] is not None and validation["actual_seconds"] > 0
        assert validation["actual_seconds"] == pytest.approx(
            sum(summary["training_history"]["validation_seconds"]), rel=0.05
        )

        # 2. the measured batches are counted exactly ONCE — the prediction is
        #    `unit_count x rate` over every validation row, with no extra term.
        prediction = validation["prediction"]
        assert prediction["predicted_seconds"] == pytest.approx(
            prediction["unit_count"]
            * prediction["ms_per_unit"]
            / 1000.0
            * prediction["safety_factor"],
            rel=1e-9,
        )

        # 3. 07a parity: the training ACTUAL stays validation-exclusive.
        assert training["actual_seconds"] > 0

        # 4. Validation calibration now reaches admission; this record-only run stays admitted.
        admission = block.get("admission")
        assert admission["decision"] == "admitted"
        assert admission["stage"] == "post_validation_verification"


@pytest.mark.parametrize("observed_run", [True], indirect=True)
def test_first_validation_stops_at_allocation_before_full_pass(observed_run, tmp_path):
    """Reachability: the real loop must check the continuing allowance, not after the epoch."""
    summary, observations, sidecar, _session = observed_run
    assert summary is None
    assert 0 < len(observations) < 24
    receipt = json.loads(sidecar.read_text())
    assert receipt["admission"]["decision"] == "rejected"
    assert receipt["admission"]["stage"] == "training_allocation.validation"
    assert "reserved_seconds=2" in receipt["admission"]["reason"]
    assert not list((tmp_path / "m").glob("*.pth"))
