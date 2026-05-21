"""Shared validation helper for the full 5-agent exploration workflow.

Extracted from ``tests/integration/workflows/test_full_exploration_loop.py``
so the pytest test and the standalone Slurm runner
(``sdsc_submission_scripts/run_exploration_test.py``) consume the same code
path without one importing from the other across the package boundary.
"""

from __future__ import annotations

import ast
import json
import math
import os

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

# Defaults mirror the chain-test configuration. Callers may override per-run.
_DEFAULT_SOURCE_MODELS: tuple[str, ...] = ("punet", "wavenet")
_DEFAULT_BUILTIN_MODELS: tuple[str, ...] = (
    "punet",
    "fcnet",
    "wavenet",
    "transformer",
    "rnn",
    "gated_fno",
)


def validate_workflow_outputs(
    run_dir: str,
    run_name: str,
    results: list,
    *,
    source_models: tuple[str, ...] = _DEFAULT_SOURCE_MODELS,
    builtin_models: tuple[str, ...] = _DEFAULT_BUILTIN_MODELS,
) -> str:
    """
    Validate all 5 stages by reading saved JSON files from the workflow output.

    Args:
        run_dir:         The workflow output directory ({workspace}/{run_name}/)
        run_name:        The run name used by all nodes
        results:         The list returned by run_workflow()
        source_models:   Models expected in the interpretation's model_types
        builtin_models:  Models the proposer's new model_name must NOT clash with

    Returns:
        The proposed model_name, for downstream cleanup hooks.
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
        d
        for d in os.listdir(iter_dir)
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

    assert set(source_models).issubset(set(interp["model_types"])), (
        f"Expected {list(source_models)} in model_types, got {interp['model_types']}"
    )
    assert len(interp["key_findings"]) > 0, "key_findings is empty"
    assert len(interp["take_home_message"]) > 0, "take_home_message is empty"
    assert interp["best_denoising_score"] is not None, "best_denoising_score is None"
    print(
        f"  [PASS] Interpretation: {len(interp['key_findings'])} findings, "
        f"best_score={interp['best_denoising_score']}"
    )

    # --- 2. Proposal ---
    proposal_path = os.path.join(attempt_dir, f"proposal_{run_name}.json")
    assert os.path.exists(proposal_path), f"Proposal output not found: {proposal_path}"
    with open(proposal_path) as f:
        proposal = json.load(f)

    model_name = proposal["model_name"]
    assert model_name not in builtin_models, (
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
        "plugin_registered",
        "tests_passed",
        "description_valid",
        "config_fields_valid",
        "instantiation_passed",
        "gradient_check_passed",
        "output_type_valid",
        "llm_review_passed",
    ]:
        assert validation[check] is True, f"Validation check '{check}' failed"
    print("  [PASS] Validation: all 8 checks passed")

    # --- 5. Tuning ---
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
        assert rec.file_vector is not None, f"Record {i} missing file_vector"
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

    print(
        f"  [PASS] Tuning: {tune_output.completed_rounds} rounds, "
        f"best_score={tune_output.best_denoising_score}"
    )

    return model_name
