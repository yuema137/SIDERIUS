"""Step 06 — C1: the metric handle, inert, with the TIDMAD instance.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§4, §5, §6, §7, §19 C1.

Two claims, kept apart: (1) the typed value is CORRECT — the TIDMAD instance
derives with no declaration and matches the identity ``per_file_best`` already
emits; a scalar-only instance is constructible; the loss boundary and the
scoreability contract are executable, not prose; scoreability runs BEFORE
arithmetic in the handle; (2) it is INERT — zero production importers. Claim
(2) goes red the moment C2 wires the first consumer, which is when it should
(05c C1 precedent); C2 inverts it into a census.

Every test names the defect only it catches. Not tested here: that a
``Literal`` rejects an unknown direction, that ``frozen=True`` blocks
assignment, that a required field is required — those are declarations
(CLAUDE.md test rule).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pytest
from pydantic import ValidationError

from execute_tools import evaluation_metric as em
from execute_tools.array2h5 import create_abra_file
from execute_tools.dataset_config import TIDMAD_PROFILE
from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec
from execute_tools.evaluation_metric import (
    TIDMAD_METRIC_ID,
    EvaluationMetric,
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    PresenceScoreabilityContract,
    ScoreabilityVerdict,
    TidmadDenoisingMetric,
    TidmadScoreabilityContract,
    derive_tidmad_metric,
    derive_tidmad_metric_spec,
)

# ---------------------------------------------------------------------------
# 1. The TIDMAD instance derives with NO declaration and matches the precedent
# ---------------------------------------------------------------------------


def test_tidmad_instance_derives_with_no_declaration_and_matches_per_file_best():
    """Regime A: a caller holding only the shipped profile obtains the instance,
    and its identity/transform equal what ``per_file_best`` has emitted since
    before Step 06 (``per_file_best.py`` ``metric_id`` / ``score_transform`` /
    ``log_base``; NUM-8 key set). Values are hardcoded, never read back from
    the module under test."""
    from execute_tools.per_file_best import LOG_BASE
    from execute_tools.scoring_helpers import _LOG_BASE

    spec = derive_tidmad_metric_spec(TIDMAD_PROFILE)
    assert spec.id == "tidmad_denoising_score" == TIDMAD_METRIC_ID
    assert spec.direction == "higher"
    assert spec.aggregation == "tidmad_anchor_normalised_linear_grand_mean"
    assert spec.transform == "log"
    assert spec.transform_params == {"log_base": 5.27}
    # One contract, four expressions (NUM-5 extended): the metric carries the
    # SAME log base the scorer's helper and per_file_best hold.
    assert spec.transform_params["log_base"] == LOG_BASE == _LOG_BASE
    assert spec.references == ("anchor_map", "raw_baseline", "ground_truth")


def test_tidmad_scoreability_is_declared_against_the_deliverable_spec():
    """The contract's input channel group and dtype are READ from 05c's
    ``DeliverableSpec`` (design §4 split), and under TIDMAD resolve to the
    channel the live scorer reads from the deliverable
    (``scoring_utils.py:477``, ``ch=1``) and the attrs it reads
    (``:159-164``). The target group is NOT a requirement: the live scorer
    reads ``ch=2`` from the RAW file (``:470``), never from the deliverable
    (ledger §20.4 correction)."""
    deliverable = derive_tidmad_deliverable_spec(TIDMAD_PROFILE)
    contract = derive_tidmad_metric_spec(TIDMAD_PROFILE, deliverable).scoreability
    assert isinstance(contract, TidmadScoreabilityContract)
    assert contract.input_channel_group == deliverable.storage.input_channel_group == "channel0001"
    assert "target_channel_group" not in TidmadScoreabilityContract.model_fields
    assert contract.required_storage_dtype == deliverable.storage.storage_dtype == "int8"
    assert contract.required_attrs == ("voltage_range_mV", "sampling_frequency")


def test_a_renamed_deliverable_spec_moves_the_contract_with_it():
    """REFERENCE, not restatement: a profile whose channel identity differs
    yields a contract requiring THAT group. (Whether the frozen scorer could
    then read them is the scorer's positional literal — out of Step 06's
    scope and recorded in the ledger — this pins only that the contract does
    not hold a second copy of the TIDMAD names.)"""
    profile = TIDMAD_PROFILE.model_copy(
        update={
            "channels": TIDMAD_PROFILE.channels.model_copy(
                update={"input_channel": "s6_in", "target_channel": "s6_target"}
            )
        }
    )
    contract = derive_tidmad_metric_spec(profile).scoreability
    assert isinstance(contract, TidmadScoreabilityContract)
    assert contract.input_channel_group == "s6_in"


# ---------------------------------------------------------------------------
# 2. A scalar-only metric is a first-class instance (§4, revision 2)
# ---------------------------------------------------------------------------


def test_a_scalar_only_metric_is_constructible_and_lower_is_a_legal_direction():
    """No per-sample evidence, no transform, no references — and it is not
    TIDMAD-shaped. The result carries ``per_sample=None`` honestly."""
    spec = MetricSpec(
        id="global_mse",
        direction="lower",
        aggregation="single_value",
        scoreability=PresenceScoreabilityContract(),
    )
    result = MetricResult(metric_id=spec.id, direction=spec.direction, scalar=0.031)
    assert result.per_sample is None
    assert result.references_used == ()
    assert spec.transform is None and spec.transform_params == {}


# ---------------------------------------------------------------------------
# 3. The evaluation-vs-training-diagnostics boundary is EXECUTABLE (§7)
# ---------------------------------------------------------------------------

_LOSS_IDENTITIES = (
    "train_loss",
    "validation_loss",
    "val_loss",
    "loss_history",
    "final_loss",
    "Focal Loss",
)


@pytest.mark.parametrize("identity", _LOSS_IDENTITIES)
def test_a_loss_shaped_identity_is_rejected_by_every_metric_type(identity):
    """Constructing a 'metric' whose identity is a loss is refused at
    construction — spec, result and not-scoreable result alike."""
    with pytest.raises(ValidationError, match="names a training loss"):
        MetricSpec(
            id=identity,
            direction="lower",
            aggregation="mean",
            scoreability=PresenceScoreabilityContract(),
        )
    with pytest.raises(ValidationError, match="names a training loss"):
        MetricResult(metric_id=identity, direction="lower", scalar=0.1)
    with pytest.raises(ValidationError, match="names a training loss"):
        NotScoreableResult(
            metric_id=identity,
            direction="lower",
            verdict=ScoreabilityVerdict(
                contract_id="c", failures=(em.ScoreabilityFailure(requirement="r", detail="d"),)
            ),
        )


def test_loss_history_cannot_populate_a_metric_result_under_any_key():
    """``extra='forbid'`` on the record-facing types: ``loss_history`` /
    ``final_loss`` / ``train_loss`` have no home on a MetricResult, and the
    types declare no field whose name says loss."""
    for key in ("loss_history", "final_loss", "train_loss"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            MetricResult(metric_id="m", direction="higher", scalar=1.0, **{key: [0.5, 0.4]})
    for model in (MetricSpec, MetricResult, NotScoreableResult, TidmadScoreabilityContract):
        assert not [f for f in model.model_fields if "loss" in f.lower()], model.__name__


def test_the_boundary_is_by_identity_not_by_formula():
    """A regression contrast task may score its deliverable by MSE; ``mse``
    is a metric identity, not a training loss. Guards the rejection rule
    against over-reach — a registry lookup would refuse this."""
    MetricSpec(
        id="mse", direction="lower", aggregation="mean", scoreability=PresenceScoreabilityContract()
    )


def test_a_not_scoreable_result_must_name_a_failure():
    """A NotScoreableResult with a clean verdict is a contradiction and is
    refused; the two outcome types cannot blur."""
    with pytest.raises(ValidationError, match="at least one failure"):
        NotScoreableResult(
            metric_id="m", direction="higher", verdict=ScoreabilityVerdict(contract_id="c")
        )


# ---------------------------------------------------------------------------
# 4. Scoreability is EXECUTABLE and structured (§5, §16-Q3)
# ---------------------------------------------------------------------------

_SAMPLES = np.arange(64, dtype=np.int8)


def _write_valid_deliverable(path: Path) -> str:
    """A tiny deliverable through the REAL writer and the derived TIDMAD
    storage — layout, attrs and dtype exactly as production writes them.
    Small on purpose: the contract is file-level, not segment-level."""
    storage = derive_tidmad_deliverable_spec(TIDMAD_PROFILE).storage
    create_abra_file(str(path), _SAMPLES, _SAMPLES, indexed=False, storage=storage)
    return str(path)


@pytest.fixture
def tidmad_contract() -> TidmadScoreabilityContract:
    contract = derive_tidmad_metric_spec(TIDMAD_PROFILE).scoreability
    assert isinstance(contract, TidmadScoreabilityContract)
    return contract


def test_the_contract_accepts_what_the_production_writer_writes(tmp_path, tidmad_contract):
    verdict = tidmad_contract.check({0: _write_valid_deliverable(tmp_path / "d0.h5")})
    assert verdict.scoreable and verdict.failures == ()
    assert verdict.contract_id == "tidmad_denoised_h5"


def _requirements(verdict: ScoreabilityVerdict) -> set[str]:
    return {f.requirement for f in verdict.failures}


def test_a_missing_deliverable_is_a_completeness_failure_not_a_file_error(
    tmp_path, tidmad_contract
):
    verdict = tidmad_contract.check({3: str(tmp_path / "never_written.h5")})
    assert not verdict.scoreable
    assert _requirements(verdict) == {"completeness"}
    assert verdict.failures[0].input_identity == 3


def test_an_empty_scope_is_not_scoreable(tidmad_contract):
    verdict = tidmad_contract.check({})
    assert not verdict.scoreable and _requirements(verdict) == {"completeness"}


def test_a_non_hdf5_file_is_a_structured_failure_not_an_oserror(tmp_path, tidmad_contract):
    """The whole point of the contract: what used to be an incidental
    exception inside the scorer worker is a named verdict."""
    bad = tmp_path / "bad.h5"
    bad.write_bytes(b"not an hdf5 file")
    verdict = tidmad_contract.check({0: str(bad)})
    assert not verdict.scoreable and _requirements(verdict) == {"completeness"}


def test_a_missing_input_channel_is_named(tmp_path, tidmad_contract):
    """The group the live scorer reads (``ch=1``) is absent → named failure."""
    path = tmp_path / "wrong_group.h5"
    with h5py.File(path, "w") as handle:
        grp = handle.create_group("timeseries/channel0009")
        grp.create_dataset("timeseries", data=_SAMPLES)
    verdict = tidmad_contract.check({0: str(path)})
    assert not verdict.scoreable and _requirements(verdict) == {"required_channels"}
    assert "channel0001" in verdict.failures[0].detail


def test_an_input_only_deliverable_is_scoreable(tmp_path, tidmad_contract):
    """What the live scorer reads is what the contract requires — no more.
    A deliverable carrying only the input group (``create_abra_file`` with
    ``array2=None``, its documented science-data form) is scoreable: the
    scorer takes ``ch=2`` from the RAW file. Guards the contract against
    becoming stricter than the frozen instance."""
    path = tmp_path / "input_only.h5"
    storage = derive_tidmad_deliverable_spec(TIDMAD_PROFILE).storage
    create_abra_file(str(path), _SAMPLES, None, indexed=False, storage=storage)
    assert tidmad_contract.check({0: str(path)}).scoreable


def test_a_wrong_storage_dtype_is_named(tmp_path, tidmad_contract):
    """int16 samples would not crash the scorer — they would silently score on
    the wrong scale. Only the contract catches this."""
    path = tmp_path / "int16.h5"
    storage = derive_tidmad_deliverable_spec(TIDMAD_PROFILE).storage
    wide = _SAMPLES.astype(np.int16)
    create_abra_file(str(path), wide, wide, indexed=False, storage=storage)
    verdict = tidmad_contract.check({0: str(path)})
    assert not verdict.scoreable and _requirements(verdict) == {"required_dtype"}
    assert all("int16" in f.detail and "int8" in f.detail for f in verdict.failures)


def test_a_missing_required_attr_is_named(tmp_path, tidmad_contract):
    path = _write_valid_deliverable(tmp_path / "no_attr.h5")
    with h5py.File(path, "a") as handle:
        del handle["timeseries/channel0001"].attrs["voltage_range_mV"]
    verdict = tidmad_contract.check({0: path})
    assert not verdict.scoreable and _requirements(verdict) == {"required_attrs"}
    assert "voltage_range_mV" in verdict.failures[0].detail


def test_every_violation_is_reported_not_just_the_first(tmp_path, tidmad_contract):
    """Two deliverables, two different defects → two failures, each keyed by
    its input identity. A first-failure-only contract hides the second."""
    good = _write_valid_deliverable(tmp_path / "d0.h5")
    verdict = tidmad_contract.check({0: good, 1: str(tmp_path / "absent.h5")})
    assert [f.input_identity for f in verdict.failures] == [1]


# ---------------------------------------------------------------------------
# 5. The handle: scoreability BEFORE arithmetic, and the TIDMAD instance
#    forwards to score_vector unchanged
# ---------------------------------------------------------------------------


class _Spy(EvaluationMetric):
    def __init__(self, spec: MetricSpec) -> None:
        super().__init__(spec)
        self.calls: list[dict[str, Any]] = []

    def _compute(self, deliverables: Mapping[int, str], /, **kw: Any):
        self.calls.append(dict(kw))
        return 0.5, None, ()


def test_evaluate_refuses_before_reaching_arithmetic(tmp_path):
    """On an invalid deliverable ``_compute`` is NEVER called and the outcome
    is a NotScoreableResult carrying the metric's identity/direction and the
    verdict; on a valid one, ``_compute`` runs and a MetricResult returns."""
    spec = MetricSpec(
        id="spy", direction="lower", aggregation="a", scoreability=PresenceScoreabilityContract()
    )
    metric = _Spy(spec)
    outcome = metric.evaluate({0: str(tmp_path / "absent.h5")}, k=1)
    assert isinstance(outcome, NotScoreableResult)
    assert (outcome.metric_id, outcome.direction) == ("spy", "lower")
    assert outcome.verdict.failures[0].requirement == "completeness"
    assert metric.calls == []

    present = tmp_path / "present.bin"
    present.write_bytes(b"x")
    outcome = metric.evaluate({0: str(present)}, k=1)
    assert isinstance(outcome, MetricResult)
    assert (outcome.metric_id, outcome.direction, outcome.scalar) == ("spy", "lower", 0.5)
    assert metric.calls == [{"k": 1}]


def test_tidmad_handle_forwards_kwargs_to_score_vector_verbatim(monkeypatch, tmp_path):
    """The aggregation is a REFERENCE to the frozen ``score_vector``: the
    handle passes its keyword arguments through untouched and maps the
    2-tuple to ``(scalar, per_sample)`` with ``references_used=('anchor_map',)``.
    A reshaped call — a renamed or dropped kwarg — would show up here."""
    import execute_tools.scoring_utils as su

    seen: dict[str, Any] = {}

    def fake_score_vector(**kwargs):
        seen.update(kwargs)
        return [None, 2.0, None], -0.25

    monkeypatch.setattr(su, "score_vector", fake_score_vector)
    metric = derive_tidmad_metric(TIDMAD_PROFILE)
    good = _write_valid_deliverable(tmp_path / "d1.h5")
    kwargs = {"data_dir": "D", "sample_set": {1: [0]}, "s_max": 3.0, "parallel": False}
    outcome = metric.evaluate({1: good}, **kwargs)
    assert isinstance(outcome, MetricResult)
    assert seen == kwargs
    assert outcome.scalar == -0.25 and outcome.per_sample == [None, 2.0, None]
    assert outcome.references_used == ("anchor_map",)
    assert (outcome.metric_id, outcome.direction) == (TIDMAD_METRIC_ID, "higher")


def test_the_tidmad_handle_is_the_derived_spec_bound_to_the_tidmad_instance():
    metric = derive_tidmad_metric(TIDMAD_PROFILE)
    assert isinstance(metric, TidmadDenoisingMetric)
    assert metric.spec == derive_tidmad_metric_spec(TIDMAD_PROFILE)


# ---------------------------------------------------------------------------
# 6. Inert — zero production importers
# ---------------------------------------------------------------------------
#
# C1's inertness assertion lived here and did its job: it went red the moment
# C2 wired the first production consumer, which is when it should. It was not
# deleted but INVERTED, into ``tests/unit/core/test_step06_c2_live_route.py::
# test_only_the_censused_sites_consume_the_metric_interface`` — the same
# concept (which production sites hold this authority) asserted in the
# direction that stays meaningful for the rest of the PR, including the
# boundary sites that must NEVER import it (the frozen scorer arithmetic, the
# reuse guard, the D1 consumers Step 06 does not reach).
