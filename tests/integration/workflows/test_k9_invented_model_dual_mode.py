"""K.9 — Dual-mode regression test for the K.2.5-8 soft-fallback path.

Exercises the full tuner-gate → record → memory pipeline when the planner
proposes an unregistered ``model_type`` (an invented plugin not present
in ``core/inference_defaults._INFERENCE_BATCH_SIZES``). Pairs with the
canned pseudo-data folder
``tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent_k9_invented/``
and the plugin file ``tests/pseudo_data/plugins/pe_wavenet_delta.py``.

Choreography under Phase L (see the pseudo-data folder's README and
``docs/resource_estimator_implement.md`` §11.8 for full rationale):
  Round 1, attempt 1: planner picks ``hidden_dim=2048`` → VRAM gate
           emits the K.2.5-8 warning AND verdicts over budget
           (over the 0.3 GB ceiling) → record saved as ``skipped_oom_risk``;
           sandbox never reached. Round 1 is NOT yet a success — the
           inner attempt budget continues.
  Round 1, attempt 2: planner reacts by collapsing to ``hidden_dim=128``
           → gate emits the K.2.5-8 warning again but verdicts under
           budget → time gate passes → ``RecordingSandbox`` returns the
           canned training/inference/scoring trio → reflector returns
           the first canned reflection → record saved with
           ``status="success"``. Round 1 succeeds; ``completed_rounds``
           advances 0 → 1; inner loop breaks.
  Round 2, attempt 1: ``completed_rounds == max_rounds - 1`` so the
           agent forces ``plan.is_trial=False`` for formal promotion.
           Planner returns ``hidden_dim=128`` again; gate fits;
           sandbox + reflector run; second canned reflection consumed.
           ``completed_rounds`` 1 → 2; outer loop exits with
           ``termination_reason="completed"``.

Total: 3 records (1 OOM-skip + 2 success), 3 plan calls, 2 reflect calls.

Run with:
  .venv/bin/pytest tests/integration/workflows/test_k9_invented_model_dual_mode.py -v -s
  .venv/bin/pytest tests/integration/workflows/test_k9_invented_model_dual_mode.py -v -s --real-llm
"""

from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.tuner_composed_effects import (
    recording_sandbox_for_attempts,
    synthetic_cuda_context,
)

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

pytestmark = pytest.mark.dual_mode


# Repo-relative path to the K.9 plugin folder. Resolved to absolute at
# fixture time so the env var the subprocess loader reads is unambiguous.
_PLUGIN_DIR_REL = "tests/pseudo_data/plugins"
_PLUGIN_MODEL_TYPE = "pe_wavenet_delta"
_PSEUDO_AGENT_FOLDER = "ml_hyperparameter_tune_agent_k9_invented"


def _register_k9_plugin(monkeypatch, request):
    """Set ``SIDERIUS_PLUGIN_DIRS`` and re-extend the live registries.

    ``ml_models/models_sandbox.py`` auto-runs ``extend_registries`` once at
    import time, but that ran before our env var was set, so the K.9
    plugin would not be in the registry. Re-running with the env var set
    registers it for the duration of the test; the finaliser pops it back
    out so the registry doesn't leak into other tests.
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

    The tuner's main loop sleeps 2 s after a successful round and 5 s
    after a caught exception. Under Phase L the canned bridge is sized
    exactly to the planned attempt sequence (3 plans + 2 reflects), so
    no spin-through padding is needed — but neutralising sleeps still
    keeps wall-clock under a second.
    """
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *a, **kw: None)


@pytest.mark.dual_mode
def test_invented_model_type_triggers_k2_5_8_fallback_path(tmp_path, request, monkeypatch, capsys):
    """K.9 — agent runs the 2-round invented-model_type loop end-to-end.

    Layered assertions (mirrors the K.8.1 evidence layout):
      Layer 1 — gate stdout: K.2.5-8 warning + verdict line are present.
      Layer 2 — per-record memory: 3 records (1 OOM-skip + 2 success);
                ``inference_batch_uncalibrated``, ``vram_budget_gb``,
                ``vram_estimate_gb`` all populated; round 1 attempt 1
                over budget, both successes fit.
      Layer 3 — planner reaction (pseudo only): plan() call #2 (the
                attempt 2 retry of round 1) receives the K.6 budget
                kwargs (``trial_vram_budget_gb``, ``last_vram_estimate_gb``);
                canned planner output lowers ``hidden_dim`` from
                attempt 1's value. plan() call #3 (the formal-promotion
                round) also carries the kwargs.
      Layer 4 — ``gate_exhaustion is None`` (success path);
                ``termination_reason == 'completed'`` and
                ``consecutive_fail_rounds_at_exit == 0`` (Phase L);
                best score populated from the canned sandbox.
    """
    from agent.llm_bridge import LLMBridge
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.recording_sandbox import RecordingSandbox

    _register_k9_plugin(monkeypatch, request)
    hardware_context = synthetic_cuda_context(monkeypatch)
    _disable_sleeps(monkeypatch)

    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)
    run_name = "k9_invented"

    agent_input = HyperparamTuningInput(
        model_type=_PLUGIN_MODEL_TYPE,
        # ``max_rounds`` must be >= 2 so the agent does NOT promote round 1
        # to formal mode. The agent forces ``plan.is_trial = False`` on the
        # formal round (``completed_rounds == max_rounds - 1``) so the final
        # round always produces a formal-mode result. K.9 needs round 1 in
        # trial mode so the trial VRAM budget binds — hence max_rounds=2.
        #
        # Phase L (§11): outer loop counts only successes. With the default
        # ``attempts_per_round=3``, ``attempts_per_formal_round=5``,
        # ``max_fail_rounds=3``, the planned attempt sequence is exactly:
        #   round 1 attempt 1 (OOM) + round 1 attempt 2 (success)
        #   + round 2 attempt 1 (formal success) = 3 attempts total.
        # The bridge is sized to match (3 plans + 2 reflects) — no
        # spin-through padding needed.
        max_rounds=2,
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.05,
        train_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=0.05,
        # Ceiling between the two fixture estimates: round 1's
        # hidden_dim=2048 must bust the budget, round 2's hidden_dim=128
        # must fit. Estimates are environment-dependent — on the H100 dev
        # box (2026-07) they are ~0.24 / ~0.4+ GB, so 0.3 splits them;
        # the original 0.1 was calibrated for the lilab-era stack and
        # rejected everything here. If this test fails on a new
        # environment with the wrong verdict split, re-derive the two
        # estimates and pick a ceiling between them. See the K.9.0 README
        # for the param-count math.
        trial_vram_budget_gb=0.3,
        # Time gate kept disabled — K.9 is about VRAM/K.2.5-8, not time.
        trial_time_budget_minutes=None,
        # HealthGate subsystem OFF — K.9 exercises the VRAM-gate fallback
        # path and planner-reaction choreography, not gate behavior. The
        # pseudo stack writes no denoised HDF5s, so real gates would
        # invalidate every round (the M9 pseudo-gate gap). Explicit
        # opt-out via the DS5 operator switch is the correct test
        # configuration, not a workaround.
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
            pytest.skip("--real-llm requires OPENAI_API_KEY for K.9")
        bridge_factory = LLMBridge
    else:
        bridge = RecordingLLMBridge.for_agent(_PSEUDO_AGENT_FOLDER)

        def bridge_factory(**kw):
            return bridge

    sandbox = recording_sandbox_for_attempts(
        _PLUGIN_MODEL_TYPE,
        base_dir=workspace,
        run_name=run_name,
        completed_attempts=2,
    )

    def sandbox_factory(**kw):
        return sandbox

    agent = HyperparamTuningAgent(bridge_factory=bridge_factory, sandbox_factory=sandbox_factory)

    from tests.helpers.tuner_composed_effects import composed_tuner_effects
    from tests.helpers.tuner_composed_fixture import composed_run

    effect_boundary = (
        nullcontext()
        if _is_real_llm(request)
        else composed_tuner_effects(
            monkeypatch,
            sandbox=sandbox,
            bridge=bridge,
            expected_attempts=3,
            hardware_context=hardware_context,
            preflight_results=[
                ("MEASURED_PEAK_ABOVE_VRAM_CAP", 0.4),
                ("COMPLETED_MEASUREMENT", 0.1),
                ("COMPLETED_MEASUREMENT", 0.1),
            ],
        )
    )
    with effect_boundary:
        with composed_run(tmp_path, agent_input, health=False):
            output = agent.run(agent_input)

    # --- Smoke / wiring assertions ---
    # NOTE: ``len(output.all_records) == 2`` is intentionally NOT here; it
    # belongs to Layer 2. Putting it before Layer 1 would mask K.2.5-8
    # regressions (a hard-fail in the inference estimator returns
    # ``status="error"`` and saves zero records, so this assertion would
    # fire first with ``0 == 2`` instead of the more diagnostic Layer 1
    # message ``"K.2.5-8 warning line missing"``. Verified in the K.9.3
    # regression-revert check.
    assert isinstance(output, HyperparamTuningOutput)
    HyperparamTuningOutput.model_validate(output.model_dump())
    assert output.run_name == run_name
    assert output.model_type == _PLUGIN_MODEL_TYPE

    # ------------------------------------------------------------------
    # Layer 1 — gate stdout (capsys). Both modes.
    # ------------------------------------------------------------------
    # A.8 (8b6c4ba, 2026-04-23) intentionally removed the K.2.5-8
    # fallback-warning/uncalibrated surface: the deterministic wrapper
    # rewrite structurally probes every batch, so unregistered model types
    # no longer take an "uncalibrated" table-fallback path and the
    # ``!!! [evaluate_vram_skill]`` warning no longer exists. The invented-
    # model choreography below (gate verdicts, OOM-skip taxonomy, planner
    # reaction, Phase-K budget fields, formal promotion) remains the value
    # of this test.
    capsys.readouterr()  # drain; stdout is no longer an assertion surface
    # Step-00 OD-5 (operator-approved 2026-08-12; design
    # docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md
    # §22.3): the former ``assert "Feasible" in stdout`` went stale when
    # the verdict print stopped reaching the parent stdout on this path
    # (pre-existing red, proven at base 844a329f). TEST-ONLY assertion
    # migration: the same property — the VRAM gate ran and produced a
    # verdict for every attempt — is asserted on production-owned
    # STRUCTURED evidence instead: each persisted record carries the
    # gate's measured verdict fields. No production print was restored
    # or moved (that disposition belongs to step 05a). Both modes.
    # The stdout property was "at least one verdict line was printed";
    # the equivalent-strength structured property is "at least one record
    # carries the gate's measured verdict evidence" (production stamps
    # ``memory.vram_estimate_gb`` on gated trial attempts; the formal
    # round's record does not carry it by existing production behavior —
    # verified during this migration). Layer 2 below keeps the strong
    # per-record taxonomy in pseudo mode.
    assert output.all_records, "gate choreography must persist at least one record"
    gate_evidence = [
        rec
        for rec in output.all_records
        if rec.status == "skipped_oom_risk"
        or (rec.memory is not None and rec.memory.vram_estimate_gb is not None)
    ]
    assert gate_evidence, (
        "no record carries any VRAM-gate verdict evidence — the pre-flight "
        "gate did not run (OD-5 escalation guard: STOP for operator review, "
        "do not weaken this assertion)"
    )

    # ------------------------------------------------------------------
    # Layer 2 — per-record memory. Pseudo mode only (real-LLM may diverge).
    # ------------------------------------------------------------------
    if bridge is not None:
        # Pseudo mode under Phase L: round 1 attempt 1 OOM-skips, round 1
        # attempt 2 succeeds (resets consecutive_fails), round 2 attempt 1
        # (formal) succeeds → exactly 3 records. Real-LLM mode is exempt
        # because the LLM may pick differently.
        assert len(output.all_records) == 3
        oom_records = [r for r in output.all_records if r.status == "skipped_oom_risk"]
        success_records = [r for r in output.all_records if r.status == "success"]
        assert len(oom_records) == 1, "Round 1 attempt 1 should be the only OOM-skipped record."
        assert len(success_records) == 2, (
            "Round 1 attempt 2 (trial) and round 2 attempt 1 (formal) should both succeed."
        )
        oom_record = oom_records[0]
        # success_records[0] = round 1 attempt 2 (trial); [1] = round 2 (formal).
        # Both have hidden_dim=128 (the formal-promotion plan reuses the trial
        # arch), so we use the trial-mode one for the per-record VRAM/budget
        # assertions to keep the apples-to-apples comparison against round 1
        # attempt 1 (same is_trial=True, same trial_portion).
        success_record = success_records[0]

        # K.2.5-8 flag — set on every gate-touched record for an unregistered model_type.
        # (inference_batch_uncalibrated assertions removed — the flag was
        # retired by the A.8 wrapper rewrite; see the Layer-1 comment.)

        # vram_budget_gb is the binding ceiling = min(operator_budget, 0.8×free).
        # Mocked free=20 GB so the cap=16 GB never binds; operator's 0.3 GB wins.
        assert oom_record.memory.vram_budget_gb == pytest.approx(0.3)
        assert success_record.memory.vram_budget_gb == pytest.approx(0.3)

        # vram_estimate_gb populated on both records; round 1 over, round 2
        # under the 0.3 GB ceiling (thresholds match trial_vram_budget_gb —
        # see the budget comment on the input for the per-GPU estimates).
        assert oom_record.memory.vram_estimate_gb is not None
        assert success_record.memory.vram_estimate_gb is not None
        assert oom_record.memory.vram_estimate_gb > 0.3, (
            f"Round 1 should be over budget; got {oom_record.memory.vram_estimate_gb} GB."
        )
        assert success_record.memory.vram_estimate_gb < 0.3, (
            f"Round 2 should fit; got {success_record.memory.vram_estimate_gb} GB."
        )

    # ------------------------------------------------------------------
    # Layer 3 — planner reaction. Pseudo mode only (bridge.calls is the
    # whole point; the real LLMBridge has no recorded-calls surface and
    # the real LLM is free to pick its own plan).
    # ------------------------------------------------------------------
    if bridge is not None:
        plan_calls = [c for c in bridge.calls if c[0] == "plan"]
        assert len(plan_calls) >= 2, (
            f"Expected ≥2 plan() calls (one per round); got {len(plan_calls)}."
        )

        # plan() call #2 = round 1 attempt 2 (the retry-after-OOM, still
        # within round 1). Its kwargs carry the K.6 [ACTIVE RESOURCE BUDGETS]
        # inputs the agent forwards, and its memory_history includes the
        # attempt 1 OOM-skip record so the planner can lower hidden_dim.
        # Mirrors the prompt-block contract end-to-end.
        # Note: ``last_mode`` is sourced from the prior record's ``time_mode``
        # (agent ml_hyperparameter_tune_agent.py:543), and K.9 disables the time
        # gate (trial_time_budget_minutes=None) so ``time_mode`` is never set
        # and ``last_mode`` is legitimately None here. We don't assert on it.
        attempt_2_kwargs = plan_calls[1][4]
        assert attempt_2_kwargs["trial_vram_budget_gb"] == pytest.approx(0.3)
        assert attempt_2_kwargs["last_vram_estimate_gb"] is not None
        assert attempt_2_kwargs["last_vram_estimate_gb"] == pytest.approx(
            oom_record.memory.vram_estimate_gb
        ), "Attempt 2 should see attempt 1's vram_estimate_gb in last_vram_estimate_gb."

        # plan() call #2's memory_history (positional arg) carries the attempt
        # 1 OOM-skip record, including the same vram_estimate_gb — proves K.6
        # history-block plumbing across attempts within a round.
        attempt_2_history = plan_calls[1][1]
        assert len(attempt_2_history) >= 1, (
            "Attempt 2's memory_history should include attempt 1's record."
        )
        assert attempt_2_history[-1]["memory"]["vram_estimate_gb"] == pytest.approx(
            oom_record.memory.vram_estimate_gb
        )

        # plan() call #3 = round 2 attempt 1 (formal promotion). Sanity check
        # the K.6 budget kwargs are still threaded through on the formal round
        # (formal_vram_budget_gb defaults to trial when unset, so the budget
        # block is non-empty here too).
        assert len(plan_calls) >= 3, (
            f"Expected 3 plan() calls (round 1 attempts 1+2 + round 2 formal); "
            f"got {len(plan_calls)}."
        )
        formal_kwargs = plan_calls[2][4]
        assert formal_kwargs["trial_vram_budget_gb"] == pytest.approx(0.3)

        # Canned planner reaction: attempt 2 lowers hidden_dim from 2048 → 128
        # in response to attempt 1's over-budget verdict (within round 1).
        h_attempt1 = oom_record.params["model_config"]["hidden_dim"]
        h_attempt2 = success_record.params["model_config"]["hidden_dim"]
        assert h_attempt2 < h_attempt1, (
            f"Attempt 2 should react by lowering hidden_dim; got {h_attempt1} → {h_attempt2}."
        )

    # ------------------------------------------------------------------
    # Layer 4 — Phase L termination + gate_exhaustion + best score.
    # ------------------------------------------------------------------
    # Success path zeroes gate_exhaustion (§10.13.1) — any success in the run
    # means "the gate didn't exhaust the budget; the next iteration doesn't
    # need a budget-shrink hint."
    assert output.gate_exhaustion is None, (
        f"Success path should zero gate_exhaustion; got {output.gate_exhaustion!r}."
    )
    # Phase L termination contract (§11.8 (4)): the run completes both rounds
    # successfully (consecutive_fails was reset on the round 1 attempt 2 success
    # and never re-incremented), so the loop exits via the success path.
    assert output.termination_reason == "completed", (
        f"Successful 2-round run should terminate with 'completed'; "
        f"got {output.termination_reason!r}."
    )
    assert output.consecutive_fail_rounds_at_exit == 0, (
        f"consecutive_fail_rounds_at_exit should be 0 after a clean run; "
        f"got {output.consecutive_fail_rounds_at_exit}."
    )

    # Best score: pseudo mode gets the canned 0.65 verbatim; real-LLM mode
    # only checks population (the real LLM's plan may produce any score).
    if bridge is not None:
        assert output.best_denoising_score == pytest.approx(0.65)
    else:
        assert output.best_denoising_score is not None
