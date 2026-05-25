"""
Tier 3 integration test — verifies the Phase A + B.2a baseline-validation fix.

Replays the two 2026-04-16 iter-1 failures (`exploit_cnn_v1`,
`explore_novel_v1`) through the propose → implement → validate slice of the
workflow, using real OpenAI LLM calls but **no GPU training**. The tuner is
deliberately skipped — the original failures fired in the implementor's
schema check and tuner's resource gate, both of which are now covered by
upstream gates:

  - Phase A: ``ProposalOutput.baseline_config['model_config']['segmentation_size']``
    validator rejects values that don't divide ``psd_segment_length``.
  - Phase B.2a: ``_check_baseline_schema_compatibility`` in the implementor
    rejects schemas whose constraints don't accept the proposer's baseline.

Either fix, if triggered, resolves via the existing retry loop. A passing
test does NOT prove the fix fired on THIS run (LLM may produce valid values
on the first try and never exercise the retry path). It proves only that
the pipeline still works end-to-end. To see whether a gate actually fired,
inspect the stdout log for retry messages.

Requires:
  - OPENAI_API_KEY set in the environment (or .env)
  - SIDERIUS seed data at /home/klz/Data/SIDEREIS_DATA/{wavenet,punet}/small_sample_trial_v0/

Run with:
  uv run pytest -m real_run \\
      tests/integration/workflows/test_baseline_validation_fix.py -v -s

DO NOT run in CI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

SIDERIUS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

try:
    from execute_tools.data_paths import SIDERIUS_DATA_DIR
except (FileNotFoundError, ImportError):
    SIDERIUS_DATA_DIR = "/home/klz/Data/SIDEREIS_DATA/"

SEED_RUN_NAME = "small_sample_trial_v0"
SEED_MODELS = ["wavenet", "punet"]

SEED_PATHS = [
    os.path.join(
        SIDERIUS_DATA_DIR,
        m,
        SEED_RUN_NAME,
        "agent",
        f"run_output_{SEED_RUN_NAME}_agent.json",
    )
    for m in SEED_MODELS
]

LLM_CONFIG_PATH = os.path.join(SIDERIUS_ROOT, "llm_configs", "openai_tiered_v1.json")
ADVICE_EXPLOIT = os.path.join(SIDERIUS_ROOT, "tuner_advice", "exploit_cnn_v1.json")
ADVICE_EXPLORE = os.path.join(SIDERIUS_ROOT, "tuner_advice", "explore_novel_v1.json")


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------


def _skip_if_no_key():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set")


def _skip_if_no_seeds():
    for p in SEED_PATHS:
        if not os.path.exists(p):
            pytest.skip(f"Seed tuning output not found: {p}")


# ---------------------------------------------------------------------------
# Helpers — load advice + LLM config the same way the chain runner does
# ---------------------------------------------------------------------------


def _load_advice(path: str) -> dict:
    """Load an advice JSON; list values get joined into one string (matches
    the chain runner's handling)."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: ("\n".join(v) if isinstance(v, list) else v) for k, v in raw.items()}


def _valid_seg_divisors() -> list[int]:
    """Valid segmentation_size divisors of psd_segment_length. Used to assert
    the proposer's emitted value passes the Phase A gate."""
    from execute_tools.dataset_config import TIDMAD

    return list(TIDMAD.valid_segmentation_sizes())


# ---------------------------------------------------------------------------
# Core runner — propose → implement → validate, no tuner
# ---------------------------------------------------------------------------


def _run_propose_implement_validate(
    *,
    tmp_path,
    run_name: str,
    advice_path: str,
    exploration_mode: str,
):
    """Drive interpret → propose → implement → validate with real OpenAI calls.

    Mirrors the inner loop of ``workflows.model_exploration.run_workflow`` but
    stops after validation — no plugin registration, no tuner. Writes all
    artifacts under ``tmp_path`` so nothing leaks into the live
    ``agent_generated/`` directory.

    Returns:
        tuple ``(proposal, impl_output, validation)`` for the test to inspect.
    """
    from agent.schemas.interpretation import InterpretationInput
    from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import (
        local_all_fields,
    )
    from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import (
        local_full_spec,
    )
    from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
        local_full_context,
    )
    from nodes.ml_code_validator_agent import MLCodeValidatorAgent
    from nodes.ml_model_implementor import MLModelImplementor
    from nodes.ml_model_proposal_agent import MLModelProposalAgent
    from nodes.result_interpretation_agent import ResultInterpretationAgent
    from workflows.llm_config import WorkflowLLMConfig
    from workflows.model_exploration import (
        _get_reasoning_pipeline,
        _load_vocab_seed,
        _make_storage,
        load_tuning_outputs_from_paths,
        tuning_outputs_to_summaries,
    )

    # --- Setup ---
    run_dir = tmp_path / run_name
    iter_dir = run_dir / "iteration_001"
    attempt_dir = iter_dir / "attempt_001"
    for d in (run_dir, iter_dir, attempt_dir):
        d.mkdir(parents=True, exist_ok=True)

    llm_config = WorkflowLLMConfig.from_json(LLM_CONFIG_PATH)
    advice = _load_advice(advice_path)
    vocab_seed = _load_vocab_seed()
    reasoning_pipeline = _get_reasoning_pipeline(
        llm_config,
        exploration_mode=exploration_mode,
        minimum_boldness=0.05,
    )

    # --- Step 1: Interpret ---
    print(f"\n[{run_name}] Loading seed tuning outputs...")
    tuning_outputs = load_tuning_outputs_from_paths(SEED_PATHS)
    summaries = tuning_outputs_to_summaries(tuning_outputs)
    existing_model_types = list({o.model_type for o in tuning_outputs})

    interp_storage = _make_storage(str(iter_dir), run_name)
    interp_input = InterpretationInput(
        summaries=summaries,
        model_knowledge_cache={},
        human_advice=advice.get("interpret"),
        runtime_vocab=vocab_seed,
        previous_proposal=None,
        storage=interp_storage,
    )

    print(f"[{run_name}] Interpreting...")
    interpretation = ResultInterpretationAgent(
        **llm_config.get("interpret"),
    ).run(interp_input)
    print(f"  Take-home: {interpretation.take_home_message[:120]}...")
    print(f"  Best score: {interpretation.best_denoising_score}")

    # --- Step 2: Propose ---
    attempt_storage = _make_storage(str(attempt_dir), run_name)
    propose_input = local_full_context(
        interpretation,
        attempt_storage,
        vocab_seed=vocab_seed,
        reasoning_pipeline=reasoning_pipeline,
        human_advice=advice.get("propose"),
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.1,
        target_files=None,
        train_portion=1.0,
        sampling_seed=None,
        trial_time_budget_minutes=None,  # time-gate disabled — keeps the
        formal_time_budget_minutes=None,  # slice purely LLM-driven
        data_dir=None,
    )
    propose_input.existing_model_types = existing_model_types
    if advice.get("mindset"):
        propose_input.mindset = advice["mindset"]

    print(f"[{run_name}] Proposing...")
    proposal = MLModelProposalAgent(
        **llm_config.get("propose"),
    ).run(propose_input)
    print(f"  Proposed model: {proposal.model_name}")
    print(
        f"  baseline_config.model_config: "
        f"{json.dumps(proposal.baseline_config.get('model_config', {}), indent=2)}"
    )

    # --- Step 3: Implement ---
    impl_input = local_full_spec(proposal, attempt_storage)
    # Redirect plugin + test writes under tmp_path — never touch the
    # live agent_generated/ directory.
    impl_input.plugin_dir = str(attempt_dir / "models")
    impl_input.test_dir = str(attempt_dir / "tests")
    if advice.get("implement"):
        impl_input.human_advice = advice["implement"]

    print(f"[{run_name}] Implementing...")
    impl_output = MLModelImplementor(
        **llm_config.get("implement"),
    ).run(impl_input)
    print(f"  Plugin: {impl_output.model_file_path}")

    # --- Step 4: Validate ---
    valid_llm = llm_config.get("validate")
    valid_input = local_all_fields(
        impl_output,
        attempt_storage,
        llm_provider=valid_llm.get("provider", "openai"),
        llm_model_id=valid_llm.get("model_id", "gpt-5.4-mini"),
    )
    if advice.get("validate"):
        valid_input.human_advice = advice["validate"]
    if proposal.inherited_components:
        valid_input.inherited_components = proposal.inherited_components

    print(f"[{run_name}] Validating...")
    validation = MLCodeValidatorAgent(**valid_llm).run(valid_input)
    print(f"  Validation passed: {validation.passed}")
    if not validation.passed:
        print(f"  Error: {validation.error_message}")

    return proposal, impl_output, validation


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaselineValidationFix:
    """Replays the two iter-1 failure modes from 2026-04-16.

    These are replay tests — the LLM may not reproduce the exact bad-baseline
    pattern on every run. What we assert is that the pipeline produces a
    valid, schema-compatible baseline by the time it reaches the (skipped)
    tuner step. Whether the fix fired on this particular run is visible in
    the stdout log (retry counts).
    """

    def setup_method(self):
        _skip_if_no_key()
        _skip_if_no_seeds()

    def test_exploit_cnn_v1_recovery(self, tmp_path):
        """Replay exploit_cnn_v1 — Phase A gate on segmentation_size.

        Original failure: proposer emitted ``segmentation_size=16384`` which
        does not divide ``psd_segment_length=10_000_000``. With Phase A, this
        is caught at ``ProposalOutput`` validation time and retried.
        """
        proposal, _impl_output, validation = _run_propose_implement_validate(
            tmp_path=tmp_path,
            run_name="exploit_cnn_v1_test",
            advice_path=ADVICE_EXPLOIT,
            exploration_mode="exploit",
        )

        # Phase A gate contract: emitted segmentation_size must divide psd_segment_length.
        model_cfg = proposal.baseline_config.get("model_config", {})
        seg = model_cfg.get("segmentation_size")
        if seg is not None:
            valid = _valid_seg_divisors()
            assert seg in valid, (
                f"Phase A gate regression: proposer emitted segmentation_size={seg} "
                f"which is not in the valid-divisor list. This should have been "
                f"caught by the ProposalOutput validator and retried."
            )
            print(f"  [PASS] segmentation_size={seg} is a valid divisor")
        else:
            print("  [INFO] proposal did not include segmentation_size (nothing to check)")

        # B.2a gate contract: whatever schema the implementor wrote must accept
        # whatever baseline the proposer emitted. Validation reaching passed=True
        # means both gates (plus everything else) held.
        assert validation.passed, (
            f"Validation failed after the fix should have resolved any "
            f"baseline-vs-schema conflict: {validation.error_message}"
        )
        print(f"  [PASS] Validation succeeded for model '{proposal.model_name}'")

    def test_explore_novel_v1_recovery(self, tmp_path):
        """Replay explore_novel_v1 — Phase B.2a baseline self-check.

        Original failure: implementor wrote a plugin with ``multiple_of=2`` on
        ``refiner_kernel_size`` while the proposer's baseline had
        ``refiner_kernel_size=5``. With B.2a the implementor's post-write
        check instantiates ``PLUGIN_CONFIG_CLASS(**model_config)`` and
        surfaces the rejection; the existing retry loop asks the LLM to
        relax the schema.
        """
        proposal, impl_output, validation = _run_propose_implement_validate(
            tmp_path=tmp_path,
            run_name="explore_novel_v1_test",
            advice_path=ADVICE_EXPLORE,
            exploration_mode="explore",
        )

        # Same Phase A check — a proposer running in explore mode is just as
        # capable of emitting a bad segmentation_size.
        model_cfg = proposal.baseline_config.get("model_config", {})
        seg = model_cfg.get("segmentation_size")
        if seg is not None:
            valid = _valid_seg_divisors()
            assert seg in valid, (
                f"Phase A gate regression: proposer emitted segmentation_size={seg} "
                f"which is not in the valid-divisor list."
            )
            print(f"  [PASS] segmentation_size={seg} is a valid divisor")

        # The critical contract for this scenario: the implementor's schema
        # accepts the proposer's baseline. The B.2a gate ensures this — if it
        # didn't hold, _validate_code would have failed and the run would
        # have raised ValueError before we got here.
        assert validation.passed, (
            f"Validation failed after the fix should have resolved any "
            f"baseline-vs-schema conflict: {validation.error_message}"
        )

        # Belt-and-suspenders: re-instantiate the plugin's config with the
        # baseline values ourselves, mimicking what the tuner will do. This
        # is a direct test of the B.2a contract.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            proposal.model_name,
            impl_output.model_file_path,
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # This is the exact call the tuner's evaluate_vram_skill makes
        # and that used to raise ValidationError.
        mod.PLUGIN_CONFIG_CLASS(**model_cfg)
        print(
            f"  [PASS] PLUGIN_CONFIG_CLASS accepted the proposer's "
            f"baseline values for '{proposal.model_name}'"
        )
