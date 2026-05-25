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

import json
import os
import shutil
from pathlib import Path

import pytest
from dotenv import load_dotenv

from execute_tools.workflow_validation import validate_workflow_outputs

# Shared human-advice file used by both lilab and SDSC chain tests.
# Single source of truth — edit one file to retune both environments.
SHARED_ADVICE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "..",
    "sdsc_submission_scripts",
    "human_advice_chain_test.json",
)


def _load_shared_advice() -> dict:
    """Load the shared human-advice JSON; missing keys default to empty string."""
    with open(SHARED_ADVICE_FILE, encoding="utf-8") as f:
        d = json.load(f)
    return {
        "interpret": d.get("interpret", "") or "",
        "propose": d.get("propose", "") or "",
        "implement": d.get("implement", "") or "",
        "validate": d.get("validate", "") or "",
        "tune": d.get("tune", "") or "",
    }


load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")

pytestmark = pytest.mark.real_run

# ---------------------------------------------------------------------------
# Resolve data paths
# ---------------------------------------------------------------------------

try:
    from execute_tools.data_paths import SIDERIUS_DATA_DIR, TIDMAD_DATA_DIR
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
            SIDERIUS_DATA_DIR,
            model,
            SOURCE_RUN_NAME,
            "agent",
            f"run_output_{SOURCE_RUN_NAME}_agent.json",
        )
        if not os.path.exists(path):
            pytest.skip(f"Tuning output not found: {path}")


def _skip_if_no_cuda():
    import torch

    if not torch.cuda.is_available():
        pytest.skip("CUDA GPU not available")


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
        from workflows.llm_config import WorkflowLLMConfig
        from workflows.model_exploration import run_workflow

        workspace = str(tmp_path / "workflow_output")
        run_name = "test_full_loop"

        # E8 validates the planner/reflector model split end-to-end:
        # planner = pro, reflector = flash. Without the explicit
        # reflect_model_id override, uniform() falls back to the planner
        # model and the flash routing path is NOT exercised — which would
        # silently miss bugs like an invalid model ID. Always pass the
        # override here so E8 mirrors the SDSC E9 production config.
        llm_config = WorkflowLLMConfig.uniform(
            "gemini",
            "gemini-3.1-pro-preview",
            reflect_model_id="gemini-2.5-flash",
        )

        print(f"\n{'=' * 60}")
        print("  TIER 3 INTEGRATION TEST: Full 5-Agent Workflow")
        print(f"  Workspace: {workspace}")
        print("  LLM: gemini-3.1-pro-preview")
        print(f"{'=' * 60}\n")

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

        # No global-dir cleanup needed — since docs/run_scoped_plugins.md
        # Phase 4, _register_plugin writes into the tuner's workspace-rooted
        # plugin dir (which lives under ``tmp_path``) instead of the legacy
        # ``<repo>/agent_generated/models/``. tmp_path teardown handles it.

        print(f"\n{'=' * 60}")
        print(f"  TIER 3 TEST PASSED — model '{model_name}' explored successfully")
        print(f"{'=' * 60}")

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
        from workflows.llm_config import WorkflowLLMConfig
        from workflows.model_exploration import run_workflow

        workspace = str(tmp_path / "workflow_output")
        llm_config = WorkflowLLMConfig.uniform("gemini", "gemini-3.1-pro-preview")

        # Shared advice file (same one used by SDSC chain orchestrator)
        shared_advice = _load_shared_advice()

        # --- Construct seed paths from the existing source data ---
        seed_paths = []
        for model in SOURCE_MODELS:
            path = os.path.join(
                SIDERIUS_DATA_DIR,
                model,
                SOURCE_RUN_NAME,
                "agent",
                f"run_output_{SOURCE_RUN_NAME}_agent.json",
            )
            seed_paths.append(path)

        registered_models: list[str] = []  # for cleanup

        try:
            # --- ITERATION 1 ---
            print(f"\n{'=' * 60}")
            print(f"  ITERATION 1: source = seeds only ({len(seed_paths)} files)")
            print(f"{'=' * 60}\n")

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
                workspace, "iter_001", "iteration_001", iter1_model, "run_output_iter_001.json"
            )
            assert os.path.exists(iter1_output_path), (
                f"Iteration 1 output not found at expected path: {iter1_output_path}"
            )
            print(f"\n[ITER 1 DONE] Model: {iter1_model}, Output: {iter1_output_path}")

            # --- ITERATION 2: seed + iteration 1's output ---
            iter2_sources = [*seed_paths, iter1_output_path]
            print(f"\n{'=' * 60}")
            print(f"  ITERATION 2: source = seeds + iter_001 ({len(iter2_sources)} files)")
            print(f"{'=' * 60}\n")

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
            print(f"\n[ITER 2 DONE] Model: {iter2_model}, Saw models: {iter2_seen_models}")

            print(f"\n{'=' * 60}")
            print("  CHAINED ITERATIONS TEST PASSED")
            print(f"  iter_001 → {iter1_model}")
            print(f"  iter_002 → {iter2_model} (saw {len(iter2_seen_models)} models)")
            print(f"{'=' * 60}")

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
