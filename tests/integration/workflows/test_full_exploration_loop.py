"""
Tier 3 integration test: full 5-agent model exploration workflow.

See docs/running_chain_test.md for the full runbook (lilab + SDSC).


Exercises the complete loop end-to-end with real LLM API calls and GPU:
  1. Load existing tuning outputs for punet, fcnet, wavenet
  2. Interpret results across all models
  3. Propose a new architecture
  4. Implement the proposed model (LLM writes plugin code)
  5. Validate the plugin (7 automated checks)
  6. Tune the new model for 2 rounds (trial → forced formal)

Uses full data mode (is_trial=True, snapshot strategy) with minimal data
(trial_portion=0.02) to keep runtime manageable (~4-8 minutes).

Requires:
  - GEMINI_API_KEY set in the environment
  - TIDMAD data directory with training + validation HDF5 files
  - SIDERIUS run data with existing tuning outputs (v3_file6)
  - Segment anchor map (segment_anchors.json)
  - CUDA GPU

Run with:
  uv run pytest -m real_run tests/integration/workflows/test_full_exploration_loop.py -v -s

DO NOT run in CI.
"""

import ast
import json
import math
import os
import shutil
import pytest
from dotenv import load_dotenv

# Shared human-advice file used by both lilab and SDSC chain tests.
# Single source of truth — edit one file to retune both environments.
SHARED_ADVICE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "sdsc_submission_scripts", "human_advice.json",
)


def _load_shared_advice() -> dict:
    """Load the shared human-advice JSON; missing keys default to empty string."""
    with open(SHARED_ADVICE_FILE, "r", encoding="utf-8") as f:
        d = json.load(f)
    return {
        "interpret": d.get("interpret", "") or "",
        "propose":   d.get("propose",   "") or "",
        "implement": d.get("implement", "") or "",
        "validate":  d.get("validate",  "") or "",
        "tune":      d.get("tune",      "") or "",
    }

load_dotenv()

pytestmark = pytest.mark.real_run

# ---------------------------------------------------------------------------
# Resolve data paths
# ---------------------------------------------------------------------------

try:
    from execute_tools.data_paths import TIDMAD_DATA_DIR, SIDERIUS_DATA_DIR
except (FileNotFoundError, ImportError):
    TIDMAD_DATA_DIR = "/home/klz/Data/TIDMAD/"
    SIDERIUS_DATA_DIR = "/home/klz/Data/SIDEREIS_DATA/"

SOURCE_RUN_NAME = "small_sample_trial_v0"
SOURCE_MODELS = ["punet", "wavenet"]
EXISTING_BUILTIN_MODELS = ["punet", "fcnet", "wavenet", "transformer", "rnn", "gated_fno"]

ANCHOR_MAP_PATH = os.path.join(TIDMAD_DATA_DIR, "segment_anchors.json")


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

def _skip_if_no_key():
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set")


def _skip_if_no_data():
    if not os.path.isdir(TIDMAD_DATA_DIR):
        pytest.skip(f"TIDMAD data not found at {TIDMAD_DATA_DIR}")
    if not os.path.isdir(SIDERIUS_DATA_DIR):
        pytest.skip(f"SIDERIUS data not found at {SIDERIUS_DATA_DIR}")


def _skip_if_no_anchor_map():
    if not os.path.exists(ANCHOR_MAP_PATH):
        pytest.skip(f"segment_anchors.json not found at {ANCHOR_MAP_PATH}")


def _skip_if_no_tuning_outputs():
    for model in SOURCE_MODELS:
        path = os.path.join(
            SIDERIUS_DATA_DIR, model, SOURCE_RUN_NAME, "agent",
            f"run_output_{SOURCE_RUN_NAME}_agent.json",
        )
        if not os.path.exists(path):
            pytest.skip(f"Tuning output not found: {path}")


def _skip_if_no_cuda():
    import torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA GPU not available")


# ---------------------------------------------------------------------------
# Validation helpers (shared — reusable by Slurm mode)
# ---------------------------------------------------------------------------

def validate_workflow_outputs(
    run_dir: str,
    run_name: str,
    results: list,
):
    """
    Validate all 5 stages by reading saved JSON files from the workflow output.

    Args:
        run_dir:  The workflow output directory ({workspace}/{run_name}/)
        run_name: The run name used by all nodes
        results:  The list returned by run_workflow()
    """
    # --- Workflow returned a result ---
    assert len(results) == 1, (
        f"Expected 1 iteration result, got {len(results)}. "
        f"Check validation logs in {run_dir}/iteration_001/ for errors."
    )
    tune_output = results[0]

    # --- Find the iteration and attempt directories ---
    iter_dir = os.path.join(run_dir, "iteration_001")
    assert os.path.isdir(iter_dir), f"Iteration directory not found: {iter_dir}"

    # Find the attempt directory (named attempt_001_{model_name})
    attempt_dirs = [
        d for d in os.listdir(iter_dir)
        if d.startswith("attempt_") and os.path.isdir(os.path.join(iter_dir, d))
    ]
    assert len(attempt_dirs) >= 1, f"No attempt directories found in {iter_dir}"
    # Use the last attempt (the one that passed validation)
    attempt_dir = os.path.join(iter_dir, sorted(attempt_dirs)[-1])

    # --- 1. Interpretation ---
    interp_path = os.path.join(iter_dir, f"interpretation_{run_name}.json")
    assert os.path.exists(interp_path), f"Interpretation output not found: {interp_path}"
    with open(interp_path) as f:
        interp = json.load(f)

    assert set(SOURCE_MODELS).issubset(set(interp["model_types"])), (
        f"Expected {SOURCE_MODELS} in model_types, got {interp['model_types']}"
    )
    assert len(interp["key_findings"]) > 0, "key_findings is empty"
    assert len(interp["take_home_message"]) > 0, "take_home_message is empty"
    assert interp["best_denoising_score"] is not None, "best_denoising_score is None"
    print(f"  [PASS] Interpretation: {len(interp['key_findings'])} findings, "
          f"best_score={interp['best_denoising_score']}")

    # --- 2. Proposal ---
    proposal_path = os.path.join(attempt_dir, f"proposal_{run_name}.json")
    assert os.path.exists(proposal_path), f"Proposal output not found: {proposal_path}"
    with open(proposal_path) as f:
        proposal = json.load(f)

    model_name = proposal["model_name"]
    assert model_name not in EXISTING_BUILTIN_MODELS, (
        f"Proposed model_name '{model_name}' clashes with existing models"
    )
    assert "_" in model_name or model_name.islower(), (
        f"model_name '{model_name}' should be snake_case"
    )
    assert len(proposal["mathematical_definition"]) > 50, (
        f"mathematical_definition too short ({len(proposal['mathematical_definition'])} chars)"
    )
    assert "expert_advice" in proposal, "expert_advice missing from proposal"
    assert len(proposal["expert_advice"].get("constraints", [])) > 0, (
        "expert_advice.constraints is empty"
    )
    baseline = proposal["baseline_config"]
    for key in ["model_config", "train_config", "loss_config"]:
        assert key in baseline, f"baseline_config missing '{key}'"
    print(f"  [PASS] Proposal: model_name='{model_name}'")

    # --- 3. Implementation ---
    impl_path = os.path.join(attempt_dir, f"implementor_{run_name}.json")
    assert os.path.exists(impl_path), f"Implementor output not found: {impl_path}"
    with open(impl_path) as f:
        impl = json.load(f)

    model_file = impl["model_file_path"]
    test_file = impl["test_file_path"]
    assert os.path.exists(model_file), f"Plugin file not found: {model_file}"
    assert os.path.exists(test_file), f"Test file not found: {test_file}"

    # Verify plugin is valid Python
    with open(model_file) as f:
        source = f.read()
    ast.parse(source)  # raises SyntaxError if invalid
    print(f"  [PASS] Implementation: {model_file}")

    # --- 4. Validation ---
    valid_path = os.path.join(attempt_dir, f"validation_{run_name}.json")
    assert os.path.exists(valid_path), f"Validation output not found: {valid_path}"
    with open(valid_path) as f:
        validation = json.load(f)

    assert validation["passed"] is True, (
        f"Validation failed: {validation.get('error_message', 'unknown')}"
    )
    for check in [
        "plugin_registered", "tests_passed", "description_valid",
        "config_fields_valid", "instantiation_passed",
        "gradient_check_passed", "output_type_valid", "llm_review_passed",
    ]:
        assert validation[check] is True, f"Validation check '{check}' failed"
    print(f"  [PASS] Validation: all 8 checks passed")

    # --- 5. Tuning ---
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

    assert isinstance(tune_output, HyperparamTuningOutput)
    assert tune_output.status in ("completed", "partial"), (
        f"Unexpected tuning status: {tune_output.status}"
    )
    assert tune_output.completed_rounds >= 2, (
        f"Expected >= 2 completed rounds (trial + formal), got {tune_output.completed_rounds}"
    )
    assert tune_output.best_denoising_score is not None, "best_denoising_score is None"
    assert len(tune_output.all_records) >= 2, (
        f"Expected >= 2 records, got {len(tune_output.all_records)}"
    )

    # Both records should have file_vector (full data mode)
    # Note: all_records contains ExperimentRecord Pydantic objects, not dicts
    for i, rec in enumerate(tune_output.all_records):
        if rec.status != "success":
            continue
        assert rec.file_vector is not None, (
            f"Record {i} missing file_vector"
        )
        assert len(rec.file_vector) == 20, (
            f"Record {i} file_vector has {len(rec.file_vector)} entries, expected 20"
        )

    # Last record should be formal (forced on final round)
    last_record = tune_output.all_records[-1]
    assert last_record.is_trial is False, (
        f"Last record should be formal (is_trial=False), got is_trial={last_record.is_trial}"
    )

    # Formal record should have 20 non-NaN entries (all files evaluated)
    if last_record.file_vector is not None:
        non_nan = [v for v in last_record.file_vector if not math.isnan(v)]
        assert len(non_nan) == 20, (
            f"Formal record has {len(non_nan)}/20 non-NaN file_vector entries"
        )

    print(f"  [PASS] Tuning: {tune_output.completed_rounds} rounds, "
          f"best_score={tune_output.best_denoising_score}")

    return model_name


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestFullExplorationLoop:

    def setup_method(self):
        _skip_if_no_key()
        _skip_if_no_data()
        _skip_if_no_anchor_map()
        _skip_if_no_tuning_outputs()
        _skip_if_no_cuda()

    def test_full_loop(self, tmp_path):
        """
        Run the complete 5-agent workflow: interpret → propose → implement →
        validate → tune (2 rounds: trial + forced formal).
        """
        from workflows.model_exploration import run_workflow
        from workflows.llm_config import WorkflowLLMConfig

        workspace = str(tmp_path / "workflow_output")
        run_name = "test_full_loop"

        # Use the most powerful Gemini model for reliability on large prompts
        llm_config = WorkflowLLMConfig.uniform("gemini", "gemini-3.1-pro-preview")

        print(f"\n{'='*60}")
        print(f"  TIER 3 INTEGRATION TEST: Full 5-Agent Workflow")
        print(f"  Workspace: {workspace}")
        print(f"  LLM: gemini-3.1-pro-preview")
        print(f"{'='*60}\n")

        results = run_workflow(
            data_dir=SIDERIUS_DATA_DIR,
            model_types=SOURCE_MODELS,
            source_run_name=SOURCE_RUN_NAME,
            workspace=workspace,
            run_name=run_name,
            llm_config=llm_config,
            max_iterations=1,
            max_rounds=2,
            max_proposal_attempts=3,
            # Full data mode with minimal data
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.02,
            train_portion=1.0,
            eval_strategy="snapshot",
            eval_portion=0.02,
            cleanup_denoised=True,
            max_epochs=1,
            # Shared advice file (same one used by SDSC chain orchestrator)
            **{f"human_advice_{k}": v for k, v in _load_shared_advice().items()},
        )

        # --- Validate all 5 stages ---
        run_dir = os.path.join(workspace, run_name)
        model_name = validate_workflow_outputs(run_dir, run_name, results)

        # --- Cleanup registered plugin (side effect of _register_plugin) ---
        plugin_file = os.path.join("agent_generated", "models", f"{model_name}.py")
        plugin_desc_dir = os.path.join("agent_generated", "models", model_name)
        if os.path.exists(plugin_file):
            os.remove(plugin_file)
            print(f"  [CLEANUP] Removed {plugin_file}")
        if os.path.isdir(plugin_desc_dir):
            shutil.rmtree(plugin_desc_dir)
            print(f"  [CLEANUP] Removed {plugin_desc_dir}/")

        print(f"\n{'='*60}")
        print(f"  TIER 3 TEST PASSED — model '{model_name}' explored successfully")
        print(f"{'='*60}")

    def test_chained_iterations(self, tmp_path):
        """
        Tier 3: simulate the per-iteration Slurm job model on lilab.

        Runs two sequential workflow calls:
        - Iteration 1: source = original seeds (punet + wavenet)
        - Iteration 2: source = original seeds + iteration 1's output

        Verifies that the per-iteration chaining logic works end-to-end with
        real LLM and GPU. This is the on-lilab equivalent of submitting two
        chained Slurm jobs on SDSC.

        Uses very aggressive size constraints to keep total runtime under
        ~1 hour (vs ~2.5 hours for the default Tier 3 test).
        """
        from workflows.model_exploration import run_workflow
        from workflows.llm_config import WorkflowLLMConfig

        workspace = str(tmp_path / "workflow_output")
        llm_config = WorkflowLLMConfig.uniform("gemini", "gemini-3.1-pro-preview")

        # Shared advice file (same one used by SDSC chain orchestrator)
        shared_advice = _load_shared_advice()

        # --- Construct seed paths from the existing source data ---
        seed_paths = []
        for model in SOURCE_MODELS:
            path = os.path.join(
                SIDERIUS_DATA_DIR, model, SOURCE_RUN_NAME, "agent",
                f"run_output_{SOURCE_RUN_NAME}_agent.json",
            )
            seed_paths.append(path)

        registered_models: list[str] = []  # for cleanup

        try:
            # --- ITERATION 1 ---
            print(f"\n{'='*60}")
            print(f"  ITERATION 1: source = seeds only ({len(seed_paths)} files)")
            print(f"{'='*60}\n")

            results_1 = run_workflow(
                source_paths=seed_paths,
                workspace=workspace,
                run_name="iter_001",
                llm_config=llm_config,
                max_iterations=1,
                max_rounds=2,
                max_proposal_attempts=3,
                is_trial=True,
                trial_strategy="snapshot",
                trial_portion=0.02,
                train_portion=1.0,
                eval_strategy="snapshot",
                eval_portion=0.02,
                cleanup_denoised=True,
                max_epochs=1,
                **{f"human_advice_{k}": v for k, v in shared_advice.items()},
            )

            assert len(results_1) == 1, "Iteration 1 should produce one tuning output"
            iter1_model = results_1[0].model_type
            registered_models.append(iter1_model)
            # run_workflow wraps each iteration in {run_name}/iteration_001/...
            iter1_output_path = os.path.join(
                workspace, "iter_001", "iteration_001", iter1_model,
                "run_output_iter_001.json"
            )
            assert os.path.exists(iter1_output_path), (
                f"Iteration 1 output not found at expected path: {iter1_output_path}"
            )
            print(f"\n[ITER 1 DONE] Model: {iter1_model}, "
                  f"Output: {iter1_output_path}")

            # --- ITERATION 2: seed + iteration 1's output ---
            iter2_sources = seed_paths + [iter1_output_path]
            print(f"\n{'='*60}")
            print(f"  ITERATION 2: source = seeds + iter_001 ({len(iter2_sources)} files)")
            print(f"{'='*60}\n")

            results_2 = run_workflow(
                source_paths=iter2_sources,
                workspace=workspace,
                run_name="iter_002",
                llm_config=llm_config,
                max_iterations=1,
                max_rounds=2,
                max_proposal_attempts=3,
                is_trial=True,
                trial_strategy="snapshot",
                trial_portion=0.02,
                train_portion=1.0,
                eval_strategy="snapshot",
                eval_portion=0.02,
                cleanup_denoised=True,
                max_epochs=1,
                **{f"human_advice_{k}": v for k, v in shared_advice.items()},
            )

            assert len(results_2) == 1, "Iteration 2 should produce one tuning output"
            iter2_model = results_2[0].model_type
            registered_models.append(iter2_model)

            # --- Validate iteration 2 actually saw iteration 1's data ---
            iter2_interp_path = os.path.join(
                workspace, "iter_002", "iteration_001", "interpretation_iter_002.json"
            )
            assert os.path.exists(iter2_interp_path), (
                f"Iteration 2 interpretation output not found: {iter2_interp_path}"
            )
            with open(iter2_interp_path) as f:
                interp = json.load(f)
            iter2_seen_models = set(interp["model_types"])
            expected_in_iter2 = set(SOURCE_MODELS) | {iter1_model}
            assert expected_in_iter2.issubset(iter2_seen_models), (
                f"Iteration 2 should see {expected_in_iter2}, "
                f"but interpretation has {iter2_seen_models}"
            )
            print(f"\n[ITER 2 DONE] Model: {iter2_model}, "
                  f"Saw models: {iter2_seen_models}")

            print(f"\n{'='*60}")
            print(f"  CHAINED ITERATIONS TEST PASSED")
            print(f"  iter_001 → {iter1_model}")
            print(f"  iter_002 → {iter2_model} (saw {len(iter2_seen_models)} models)")
            print(f"{'='*60}")

        finally:
            # Clean up registered plugins from both iterations
            for model_name in registered_models:
                plugin_file = os.path.join("agent_generated", "models", f"{model_name}.py")
                plugin_desc_dir = os.path.join("agent_generated", "models", model_name)
                if os.path.exists(plugin_file):
                    os.remove(plugin_file)
                    print(f"  [CLEANUP] Removed {plugin_file}")
                if os.path.isdir(plugin_desc_dir):
                    shutil.rmtree(plugin_desc_dir)
                    print(f"  [CLEANUP] Removed {plugin_desc_dir}/")
