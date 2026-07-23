"""L.8 — Dual-mode regression test for the Phase L fail-round abort path.

Exercises the outer loop's abort branch: an iteration that anchors on one
successful round 1 and then collapses into 3 consecutive fail-rounds,
reaching `max_fail_rounds=3` and exiting with
`termination_reason="aborted_fail_rounds"` plus a Trigger B
`gate_exhaustion` summary for the next iteration's proposer.

The §11.8 spec originally called for an "all-9-OOM" choreography under
`max_rounds=3`, but that scenario hits Trigger A (no-successes branch)
of `_build_gate_exhaustion`, not Trigger B — the L.3 implementation
gates Trigger B behind `completed_rounds > 0`. To validate Trigger B's
"model too large after K successful rounds" framing (the load-bearing
claim of §11.4), this test inserts one successful round 1 before the
fail-round burst.

Choreography under Phase L (see the pseudo-data folder's README and
`docs/resource_estimator_implement.md` §11.4 for full rationale):

  Round 1 (1 attempt): planner picks `hidden_dim=128` → VRAM gate fits
           (~26 MB < 100 MB) → sandbox + reflector run → recorded as
           `success`. `completed_rounds` advances 0 → 1.
  Rounds 2, 3, 4 (3 attempts each, 9 total):
           planner returns oversized `hidden_dim=2048` for every attempt
           → VRAM gate verdicts over budget (~151 MB > 100 MB) → all 9
           records saved as `skipped_oom_risk`. Each round exhausts its
           per-round attempt budget without a success and increments
           `consecutive_fails`. After round 4, `consecutive_fails ==
           max_fail_rounds == 3` → outer loop aborts.

Per the success-counter-derived `round_index` convention (set at round
start as `completed_rounds + 1`), all 9 fail-records carry
`round_index = 2` because `completed_rounds` is stuck at 1.

Total: 10 records (1 success + 9 OOM-skip), 10 plan calls, 1 reflect call.

Run with:
  .venv/bin/pytest tests/integration/workflows/test_l_fail_round_abort_dual_mode.py -v -s
  .venv/bin/pytest tests/integration/workflows/test_l_fail_round_abort_dual_mode.py -v -s --real-llm
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

pytestmark = pytest.mark.dual_mode


_PLUGIN_DIR_REL = "tests/pseudo_data/plugins"
_PLUGIN_MODEL_TYPE = "pe_wavenet_delta"
_PSEUDO_AGENT_FOLDER = "ml_hyperparameter_tune_agent_l_fail_round_abort"


def _register_plugin(monkeypatch, request):
    """Set ``SIDERIUS_PLUGIN_DIRS`` and re-extend the live registries.

    Reused pattern from the K.9 fixture — see
    ``test_k9_invented_model_dual_mode.py::_register_k9_plugin`` for the
    full rationale.
    """
    plugin_dir_abs = os.path.abspath(_PLUGIN_DIR_REL)
    monkeypatch.setenv("SIDERIUS_PLUGIN_DIRS", plugin_dir_abs)

    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.plugin_loader import (
        PLUGIN_OUTPUT_TYPE_REGISTRY,
        extend_registries,
    )

    loaded = extend_registries(MODEL_REGISTRY, PLUGIN_CONFIG_REGISTRY)

    def _cleanup():
        for mt in loaded:
            MODEL_REGISTRY.pop(mt, None)
            PLUGIN_CONFIG_REGISTRY.pop(mt, None)
            PLUGIN_OUTPUT_TYPE_REGISTRY.pop(mt, None)

    request.addfinalizer(_cleanup)


def _disable_sleeps(monkeypatch):
    """Replace ``time.sleep`` with a no-op for the duration of the test.

    Under Phase L the canned bridge is sized exactly to the planned
    attempt sequence (10 plans + 1 reflect), so no spin-through padding
    is needed — but neutralising sleeps keeps wall-clock under a second.
    """
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *a, **kw: None)


def _mock_cuda(monkeypatch):
    """Make the VRAM gate believe it is on a 32 GB GPU with 20 GB free.

    Same setup as K.9: the 0.8 × 20 GB = 16 GB defensive cap never binds
    against the operator budget (0.1 GB), so the binding ceiling is the
    operator's value and verdicts are deterministic on machines without
    a real GPU.
    """
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        torch.cuda,
        "mem_get_info",
        lambda *a, **kw: (20 * 1024**3, 32 * 1024**3),
    )


@pytest.mark.dual_mode
def test_fail_round_abort_triggers_phase_l_termination(tmp_path, request, monkeypatch, capsys):
    """L.8 — agent runs the 4-round fail-burst loop end-to-end.

    Layered assertions:
      Layer 1 — termination contract: completed_rounds, consecutive_fail_
                rounds_at_exit, termination_reason, echoed budget knobs.
      Layer 2 — record counts (pseudo only): 10 records (1 success + 9
                OOM-skip); all 9 OOM records carry round_index=2 (Phase L
                success-counter-derived index).
      Layer 3 — gate_exhaustion summary (pseudo only): Trigger B framing
                ("Model too large", "3 consecutive rounds", "after 1
                successful round").
      Layer 4 — best score still populated from the canned round 1 success.
    """
    from agent.llm_bridge import LLMBridge
    from tests.conftest import _is_real_llm, _is_real_training
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.recording_sandbox import RecordingSandbox

    _register_plugin(monkeypatch, request)
    _mock_cuda(monkeypatch)
    _disable_sleeps(monkeypatch)

    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)
    run_name = "l_fail_round_abort"

    agent_input = HyperparamTuningInput(
        model_type=_PLUGIN_MODEL_TYPE,
        # Phase L choreography for L.8: round 1 success + 3 fail-rounds
        # → abort. max_rounds=4 because Trigger B requires
        # ``completed_rounds > 0`` (the success-anchor) AND we need 3
        # consecutive fail-rounds after the success to hit
        # ``max_fail_rounds=3``.
        max_rounds=4,
        attempts_per_round=3,
        # Explicit override of the default 5 (per §11.8) — defensive,
        # since formal-promotion (completed_rounds == max_rounds - 1 == 3)
        # is never reached in this test.
        attempts_per_formal_round=3,
        max_fail_rounds=3,
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.05,
        train_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=0.05,
        # Ceiling between the two fixture estimates: hidden_dim=128 must
        # fit, hidden_dim=2048 must bust. Estimates are environment-
        # dependent — on the H100 dev box (2026-07) they are ~0.2 /
        # ~0.4 GB, so 0.3 splits them; the original 0.1 was calibrated
        # for the lilab-era stack (~0.03 / ~0.15) and rejected everything
        # here. If this test fails on a new environment with all attempts
        # gate-rejected (or none), re-derive the two estimates and pick a
        # ceiling between them.
        trial_vram_budget_gb=0.3,
        # Time gate disabled — L.8 is about VRAM/abort, not time.
        trial_time_budget_minutes=None,
        # HealthGate subsystem OFF — this test exercises round/budget/abort
        # choreography, not gate behavior. The pseudo stack writes no
        # denoised HDF5s, so real gates would invalidate every round
        # (the M9 pseudo-gate gap). Explicit opt-out via the DS5 operator
        # switch is the correct test configuration, not a workaround.
        health_gate_enabled=False,
        llm_provider="openai",
        llm_model_id="gpt-5-mini",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name=run_name),
        ),
        progress_bar=False,
    )

    bridge = sandbox = None
    if _is_real_llm(request):
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("--real-llm requires OPENAI_API_KEY for L.8")
        bridge_factory = LLMBridge
    else:
        bridge = RecordingLLMBridge.for_agent(_PSEUDO_AGENT_FOLDER)

        def bridge_factory(**kw):
            return bridge

    if _is_real_training(request):
        pytest.skip(
            "--real-training is not supported for L.8: pe_wavenet_delta is a "
            "test-only plugin, not a registered training target."
        )
    else:
        sandbox = RecordingSandbox.for_model(
            _PLUGIN_MODEL_TYPE, base_dir=workspace, run_name=run_name
        )

        def sandbox_factory(**kw):
            return sandbox

    agent = HyperparamTuningAgent(bridge_factory=bridge_factory, sandbox_factory=sandbox_factory)

    output = agent.run(agent_input)

    # --- Smoke / wiring ---
    assert isinstance(output, HyperparamTuningOutput)
    HyperparamTuningOutput.model_validate(output.model_dump())
    assert output.run_name == run_name
    assert output.model_type == _PLUGIN_MODEL_TYPE

    # ------------------------------------------------------------------
    # Layer 1 — Phase L termination contract. Both modes.
    # ------------------------------------------------------------------
    # Echoed budget knobs — must reflect what we asked for, not the defaults.
    assert output.attempts_per_round == 3
    assert output.attempts_per_formal_round == 3
    assert output.max_fail_rounds == 3
    # Termination contract (§11.8 (4)): one success, then 3 fail-rounds → abort.
    assert output.completed_rounds == 1, (
        f"Only round 1 should succeed; got completed_rounds={output.completed_rounds}."
    )
    assert output.consecutive_fail_rounds_at_exit == 3, (
        f"Should hit max_fail_rounds=3; got "
        f"consecutive_fail_rounds_at_exit={output.consecutive_fail_rounds_at_exit}."
    )
    assert output.termination_reason == "aborted_fail_rounds", (
        f"Should abort on fail-round burst; got termination_reason={output.termination_reason!r}."
    )

    # ------------------------------------------------------------------
    # Layer 2 — record counts + Phase L round_index semantics. Pseudo only
    # (real-LLM may pick differently and never hit the abort).
    # ------------------------------------------------------------------
    if bridge is not None:
        assert len(output.all_records) == 10, (
            f"Expected 10 records (1 success + 9 OOM-skip); got {len(output.all_records)}."
        )
        success_records = [r for r in output.all_records if r.status == "success"]
        oom_records = [r for r in output.all_records if r.status == "skipped_oom_risk"]
        assert len(success_records) == 1, (
            f"Round 1 should be the only success; got {len(success_records)}."
        )
        assert len(oom_records) == 9, (
            f"Rounds 2-4 should produce 9 OOM-skips; got {len(oom_records)}."
        )

        # Phase L success-counter-derived round_index: completed_rounds is
        # stuck at 1 after round 1, so all 9 fail-records carry round_index=2
        # (not 2/3/4 as the outer loop iteration count). This mirrors the
        # L.6 sub-case (b) trap and the K.9 success record's round_index=1.
        assert success_records[0].memory.round_index == 1
        assert success_records[0].memory.attempt_in_round == 1
        for i, r in enumerate(oom_records):
            assert r.memory.round_index == 2, (
                f"OOM record [{i}] should have round_index=2 (success-counter-"
                f"derived under Phase L); got {r.memory.round_index}."
            )

    # ------------------------------------------------------------------
    # Layer 3 — Trigger B gate_exhaustion summary. Both modes (the
    # termination contract should produce a populated summary regardless
    # of who picked the plans).
    # ------------------------------------------------------------------
    assert output.gate_exhaustion is not None, (
        "Abort path should populate gate_exhaustion for the next proposer."
    )
    summary = output.gate_exhaustion.summary_message
    # Trigger B lead phrasing per §11.4 — verifies we hit the
    # "model too large after K successful rounds" branch, not Trigger A's
    # no-successes branch.
    assert "Model too large" in summary, (
        f"Expected Trigger B lead phrase in summary; got: {summary!r}"
    )
    assert "3 consecutive rounds" in summary, (
        f"Summary should cite consecutive_fail_rounds_at_exit=3; got: {summary!r}"
    )
    assert "after 1 successful round" in summary, (
        f"Summary should cite completed_rounds=1 in singular form; got: {summary!r}"
    )

    # ------------------------------------------------------------------
    # Layer 4 — best score populated from the round 1 success.
    # ------------------------------------------------------------------
    if bridge is not None:
        assert output.best_denoising_score == pytest.approx(0.65)
    else:
        assert output.best_denoising_score is not None
