"""T6 — schema + determinism tests for ``core.sandbox_executor.StubSandbox``.

StubSandbox is the 0-cost smoke-run replacement for ``TidmadSandbox``: it
returns synthetic, pydantic-valid results without launching subprocesses,
touching the real data dir, or producing GPU artefacts. These tests pin
five guarantees that the chain orchestration layer relies on:

  * ``execute_training`` / ``execute_inference`` / ``execute_scoring`` all
    return ``status == "success"`` plus a results dict shaped like the
    production trainer / inference / scorer output.
  * The merged training-plus-scoring dict round-trips through
    ``ExperimentRecord`` validation (the same gate
    ``ml_hyperparameter_tune_agent`` runs upstream of every save).
  * ``denoising_score`` synthesises in [-3.0, -2.0] (the contract from the
    Roadmap §B3 / Commit 4.4 spec).
  * ``save_record`` stamps a ``_pseudo_origin = "stub_sandbox"`` audit
    marker, mirrors the record into ``self.saved_records`` for tests, AND
    persists the marker to disk in ``records/<run_name>/<exp_id>.json``.
  * ``random.Random(self._run_id)`` is the seed source — same ``run_id``
    yields identical streams across instances and across processes.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord
from core.sandbox_executor import StubSandbox

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RUN_NAME = "stub_smoke_run"
_RUN_ID = "stub_smoke_run-2026-05-07T00:00:00-12345"
_EXP_ID = "stub_exp_001"
_MODEL_TYPE = "stub_arch"

# Minimal config dicts. StubSandbox doesn't validate them (the override
# bypasses ``_validate_configs``), so any non-empty mapping is accepted.
_M_CFG: dict[str, Any] = {"hidden_dim": 8}
_T_CFG: dict[str, Any] = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
_L_CFG: dict[str, Any] = {"loss_type": "ce"}


@pytest.fixture
def stub(tmp_path) -> StubSandbox:
    return StubSandbox(
        run_name=_RUN_NAME,
        workspace=str(tmp_path),
        progress_bar=False,
        run_id=_RUN_ID,
    )


def _build_record(
    train_results: dict[str, Any],
    score_results: dict[str, Any],
) -> dict[str, Any]:
    """Mirror the record-assembly step in ``ml_hyperparameter_tune_agent``.

    The agent merges training + scoring results into a single dict and
    validates the assembled record against ``ExperimentRecord`` immediately
    before calling ``sandbox.save_record``. This helper builds the same
    shape so the schema-validity tests stay close to production behaviour.
    """
    return {
        "exp_id": _EXP_ID,
        "status": "success",
        "model_type": _MODEL_TYPE,
        "timestamp": "2026-05-07T00:00:00",
        "file_index": 6,
        "params": {
            "model_config": _M_CFG,
            "train_config": _T_CFG,
            "loss_config": _L_CFG,
        },
        "final_loss": train_results.get("final_loss"),
        "loss_history": train_results.get("loss_history"),
        "model_params": train_results.get("model_params"),
        "denoising_score": score_results.get("denoising_score"),
        "file_vector": score_results.get("file_vector"),
    }


# ---------------------------------------------------------------------------
# 1. execute_training shape
# ---------------------------------------------------------------------------


def test_execute_training_returns_schema_valid_success(stub: StubSandbox) -> None:
    """``status: success`` plus a results dict carrying the three keys
    ``ml_hyperparameter_tune_agent`` reads from training output."""
    out = stub.execute_training(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    assert out["status"] == "success"
    results = out["results"]
    assert isinstance(results["final_loss"], float)
    assert isinstance(results["loss_history"], list) and results["loss_history"]
    assert isinstance(results["model_params"], int)
    assert results["model_params"] > 0


# ---------------------------------------------------------------------------
# 2. execute_inference shape
# ---------------------------------------------------------------------------


def test_execute_inference_returns_schema_valid_success(stub: StubSandbox) -> None:
    """Stub inference returns the four keys the chain consumes:
    ``per_file_timings_ms``, ``process_startup_ms``, ``subprocess_wall_ms``,
    plus the success status."""
    out = stub.execute_inference(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        l_cfg=_L_CFG,
    )
    assert out["status"] == "success"
    assert out["per_file_timings_ms"] == []
    assert out["process_startup_ms"] == pytest.approx(10.0)
    assert out["subprocess_wall_ms"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 3. execute_scoring + ExperimentRecord round-trip
# ---------------------------------------------------------------------------


def test_execute_scoring_records_validate_against_experiment_record(
    stub: StubSandbox,
) -> None:
    """The merged train+score dict must satisfy ``ExperimentRecord`` —
    that is the exact gate the agent runs before ``save_record``. If
    this drifts, every chain crashes on the first round's
    ``model_validate`` call."""
    train_out = stub.execute_training(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    score_out = stub.execute_scoring(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    assert score_out["status"] == "success"
    # Cached training results must be merged into scoring output (mirrors
    # the prod ``execute_scoring`` merge order).
    assert score_out["results"]["final_loss"] == train_out["results"]["final_loss"]

    record = _build_record(train_out["results"], score_out["results"])
    # No exception → schema-valid. The record is a Pydantic v2 default
    # model with extra='ignore', so unknown keys (like the future
    # ``_pseudo_origin`` marker) are silently dropped during validation
    # but preserved on the raw dict for json-dump on disk.
    ExperimentRecord.model_validate(record)


# ---------------------------------------------------------------------------
# 4. denoising_score bounds
# ---------------------------------------------------------------------------


def test_denoising_score_within_bounds(stub: StubSandbox) -> None:
    """Roadmap contract: synthetic ``denoising_score`` ∈ [-3.0, -2.0]."""
    score_out = stub.execute_scoring(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    s = score_out["results"]["denoising_score"]
    assert -3.0 <= s <= -2.0, f"denoising_score {s} outside [-3.0, -2.0]"
    fv = score_out["results"]["file_vector"]
    assert isinstance(fv, list) and len(fv) == 9
    for v in fv:
        assert -3.0 <= v <= -2.0


# ---------------------------------------------------------------------------
# 5. save_record — in-memory mirror + audit marker
# ---------------------------------------------------------------------------


def test_save_record_stamps_pseudo_origin_and_mirrors_in_memory(
    stub: StubSandbox,
) -> None:
    """The audit marker ``_pseudo_origin = "stub_sandbox"`` must be
    injected on the record dict before persistence, and the same record
    must appear in ``self.saved_records`` for unit-test inspection."""
    train_out = stub.execute_training(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    score_out = stub.execute_scoring(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    record = _build_record(train_out["results"], score_out["results"])
    stub.save_record(record)

    # In-memory mirror.
    assert len(stub.saved_records) == 1
    assert stub.saved_records[0]["_pseudo_origin"] == "stub_sandbox"
    # Same dict object (or at least carries the marker).
    assert record["_pseudo_origin"] == "stub_sandbox"


# ---------------------------------------------------------------------------
# 6. save_record — on-disk persistence with marker
# ---------------------------------------------------------------------------


def test_save_record_persists_pseudo_origin_marker_to_disk(
    stub: StubSandbox,
    tmp_path,
) -> None:
    """Operators must be able to ``grep _pseudo_origin records/`` to
    distinguish synthetic smoke-run records from real measurements."""
    train_out = stub.execute_training(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    score_out = stub.execute_scoring(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    record = _build_record(train_out["results"], score_out["results"])
    stub.save_record(record)

    # Path layout matches ``LocalRecorder.save_record``:
    #   <workspace>/records/<run_name>/<exp_id>.json
    detail_path = os.path.join(
        str(tmp_path),
        "records",
        _RUN_NAME,
        f"{_EXP_ID}.json",
    )
    assert os.path.isfile(detail_path), f"missing on-disk record: {detail_path}"
    with open(detail_path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["_pseudo_origin"] == "stub_sandbox"
    # And the summary file must also carry the marker.
    summary_path = os.path.join(str(tmp_path), f"summary_{_RUN_NAME}.json")
    assert os.path.isfile(summary_path)
    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)
    assert any(r.get("_pseudo_origin") == "stub_sandbox" for r in summary)


# ---------------------------------------------------------------------------
# 7. Determinism — same run_id → identical streams
# ---------------------------------------------------------------------------


def test_determinism_same_run_id_yields_same_stream(tmp_path) -> None:
    """Two fresh StubSandbox instances with the same ``run_id`` must
    produce byte-identical synthetic outputs. This is the foundation of
    cross-process smoke-run reproducibility."""
    a = StubSandbox(
        run_name=_RUN_NAME,
        workspace=str(tmp_path / "a"),
        run_id=_RUN_ID,
    )
    b = StubSandbox(
        run_name=_RUN_NAME,
        workspace=str(tmp_path / "b"),
        run_id=_RUN_ID,
    )
    out_a = a.execute_training(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    out_b = b.execute_training(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )
    assert out_a["results"]["final_loss"] == out_b["results"]["final_loss"]
    assert out_a["results"]["loss_history"] == out_b["results"]["loss_history"]
    assert out_a["results"]["model_params"] == out_b["results"]["model_params"]


# ---------------------------------------------------------------------------
# 9. score_vector — anchor-normalised path (no h5 read)
# ---------------------------------------------------------------------------


def test_score_vector_returns_synthetic_two_tuple(stub: StubSandbox) -> None:
    """``ml_hyperparameter_tune_agent`` calls ``sandbox.score_vector`` (not
    ``execute_scoring``) when ``anchor_map_data is not None`` — the default
    modern chain path. The inherited prod implementation opens the
    ``abra_validation_denoised_*.h5`` artefacts produced by inference;
    under ``--is_pseudo_training`` those files don't exist (inference is
    stubbed), so the stub must override the method to return a synthetic
    2-tuple matching the tuner's unpacking at the call site:

        file_vector, final_scalar

    Pins both contract fields: ``file_vector`` length 9 and bounded in
    [-3.0, -2.0]; ``final_scalar`` in the same band.

    Health-check separation (commit-5a): the trailing
    ``(is_degenerate, failure_reason)`` pair was removed when
    ``score_vector`` shed its embedded health-check logic. See
    ``docs/design/pluggable_health_checks.md`` §14 Option A. Extra
    kwargs like ``reference_file_vector`` are silently swallowed by
    ``**kwargs`` — verified below."""
    fv, fs = stub.score_vector(
        sample_set={6: [0, 1, 2]},
        anchor_map={6: 1.0},
        s_max=1.0,
        denoised_filename_fn=lambda i: f"fake_{i:04d}.h5",
        # Swallowed by **kwargs — exercises the kwargs-tolerance contract.
        reference_file_vector=None,
    )
    assert isinstance(fv, list) and len(fv) == 9
    for v in fv:
        assert -3.0 <= v <= -2.0
    assert isinstance(fs, float)
    assert -3.0 <= fs <= -2.0


# ---------------------------------------------------------------------------
# 8. set_run_context — late re-seeding for distinct run_ids
# ---------------------------------------------------------------------------


def test_set_run_context_reseeds_for_distinct_run_ids(tmp_path) -> None:
    """``set_run_context`` mirrors the StubLLMBridge API: re-seeding with a
    new ``run_id`` switches the synthetic stream so two distinct chain
    runs don't collide. Also pins that distinct run_ids → distinct
    streams (no accidental degeneracy)."""
    sandbox = StubSandbox(
        run_name=_RUN_NAME,
        workspace=str(tmp_path),
        run_id="run_id_alpha",
    )
    s_alpha = sandbox.execute_scoring(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )["results"]["denoising_score"]

    sandbox.set_run_context("run_id_beta")
    s_beta = sandbox.execute_scoring(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )["results"]["denoising_score"]

    # Distinct run_ids → distinct streams. (Probability of accidental
    # equality across two SHA-512-seeded uniform draws is vanishingly
    # small; if this ever fires, a re-seed bug is the more likely cause.)
    assert s_alpha != s_beta

    # And re-seeding back to "run_id_alpha" reproduces the original draw.
    sandbox.set_run_context("run_id_alpha")
    s_alpha_again = sandbox.execute_scoring(
        exp_id=_EXP_ID,
        run_name=_RUN_NAME,
        model_type=_MODEL_TYPE,
        m_cfg=_M_CFG,
        t_cfg=_T_CFG,
        l_cfg=_L_CFG,
    )["results"]["denoising_score"]
    assert s_alpha == s_alpha_again
