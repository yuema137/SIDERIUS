"""Phase R resilience tests for run_exploration_adaptive.

Three behavioural guarantees:

1. ``_append_evolution_failure`` writes a JSONL line with the expected
   schema (``kind`` = "iteration_failure", ``architecture_name``,
   ``termination_reason``).

2. The main loop continues past a failed iteration, calls the failure
   logger, and resets the consecutive-failure counter on the next
   success.

3. The consecutive-failure brake fires after exactly
   ``--max_failed_iterations`` failures in a row.

The runner is loaded by file path so we can monkeypatch ``_run_one_iter``
without dragging in heavy workflow imports.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "run_exploration_adaptive.py"


def _load_runner_module():
    """Import run_exploration_adaptive.py without executing main()."""
    spec = importlib.util.spec_from_file_location(
        "run_exploration_adaptive_under_test", RUNNER_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner():
    return _load_runner_module()


# ---------------------------------------------------------------------------
# (1) failure-logger schema
# ---------------------------------------------------------------------------

def test_append_evolution_failure_writes_expected_schema(tmp_path, runner):
    workspace = str(tmp_path)
    manifest = {
        "status": "no_records",
        "model_name": "spectral_u_operator_lite",
        "iteration_dir": str(tmp_path / "iter_002"),
        "completed_rounds": 0,
    }
    runner._append_evolution_failure(workspace, iteration=2, manifest=manifest)

    log_path = os.path.join(workspace, "evolution_log.jsonl")
    assert os.path.exists(log_path)
    lines = [json.loads(ln) for ln in open(log_path)]
    assert len(lines) == 1
    entry = lines[0]
    assert entry["kind"] == "iteration_failure"
    assert entry["iteration"] == 2
    assert entry["architecture_name"] == "spectral_u_operator_lite"
    assert entry["manifest_status"] == "no_records"
    assert entry["completed_rounds"] == 0
    # Default termination_reason falls back to manifest['status'] when
    # run_output_iter_NNN.json is absent
    assert entry["termination_reason"] == "no_records"
    assert "timestamp" in entry


def test_append_evolution_failure_pulls_termination_reason_from_run_output(tmp_path, runner):
    workspace = str(tmp_path)
    arch = "spectral_u_operator_lite"
    iter_dir = tmp_path / "iter_002"
    inner_dir = iter_dir / "iteration_002" / arch
    inner_dir.mkdir(parents=True)
    (inner_dir / "run_output_iter_002.json").write_text(json.dumps({
        "termination_reason": "aborted_fail_rounds",
        "total_attempts": 9,
    }))

    manifest = {
        "status": "no_records",
        "model_name": arch,
        "iteration_dir": str(iter_dir),
        "completed_rounds": 0,
    }
    runner._append_evolution_failure(workspace, iteration=2, manifest=manifest)

    entry = json.loads(open(os.path.join(workspace, "evolution_log.jsonl")).read())
    assert entry["termination_reason"] == "aborted_fail_rounds"


# ---------------------------------------------------------------------------
# (2) and (3) main-loop behaviour
# ---------------------------------------------------------------------------

def _stub_args(workspace: str, max_iterations: int, max_failed_iterations: int):
    """Minimal argparse.Namespace surface needed by main() before the loop.

    main() prints a banner that touches many args; we provide a permissive
    namespace and patch parse_args() to return it.
    """
    import argparse
    return argparse.Namespace(
        run_name="resilience_test",
        workspace=workspace,
        advice="tuner_advice/explore_novel_v4.json",  # not actually read because we stub the file
        llm_config=None,
        max_iterations=max_iterations,
        start_iteration=1,
        max_rounds=1,
        max_proposal_attempts=1,
        max_impl_attempts=1,
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.05,
        target_files=[],
        train_portion=0.1,
        eval_portion=0.1,
        sampling_seed=None,
        max_epochs=1,
        trial_time_budget_minutes=20,
        formal_time_budget_minutes=180,
        data_dir=None,
        trial_vram_budget_gb=8,
        formal_vram_budget_gb=12,
        formal_strategy="snapshot",
        formal_portion=0.1,
        formal_train_portion=0.1,
        formal_eval_portion=0.1,
        force_formal_round=False,
        formal_round_strategy="inherit_best_trial",
        degenerate_penalty_score=None,
        attempts_per_round=3,
        attempts_per_formal_round=5,
        max_fail_rounds=3,
        max_failed_iterations=max_failed_iterations,
        seed_paths=None,
        source_paths_legacy=None,
        exploration_mode="explore",
        minimum_boldness=0.05,
        debug_dump_prompts=False,
    )


def _make_advice_file(tmp_path: Path) -> str:
    advice_path = tmp_path / "advice.json"
    advice_path.write_text(json.dumps({
        "propose": "x", "implement": "y", "tune": "z", "mindset": "w",
    }))
    return str(advice_path)


def _stub_seed_path(tmp_path: Path) -> str:
    p = tmp_path / "seed.json"
    p.write_text(json.dumps({"all_records": []}))
    return str(p)


def test_loop_continues_past_failure_and_resets_counter(tmp_path, runner, capsys):
    workspace = str(tmp_path / "ws")
    args = _stub_args(workspace, max_iterations=3, max_failed_iterations=3)
    args.advice = _make_advice_file(tmp_path)
    args.seed_paths = [_stub_seed_path(tmp_path)]

    iter_dir = lambda i: os.path.join(workspace, f"iter_{i:03d}")

    def _fake_run_one_iter(args, ws, llm_cfg, advice, source_paths, iteration):
        if iteration == 2:  # middle iter fails
            return {
                "status": "no_records", "output_path": None,
                "iteration_dir": iter_dir(iteration),
                "model_name": "bad_arch", "best_score": None,
                "completed_rounds": 0,
            }
        return {
            "status": "completed",
            "output_path": iter_dir(iteration) + "/out.json",
            "iteration_dir": iter_dir(iteration),
            "model_name": f"good_arch_{iteration}", "best_score": 5.5,
            "completed_rounds": 1,
        }

    with patch.object(runner, "parse_args", return_value=args), \
         patch.object(runner, "_run_one_iter", side_effect=_fake_run_one_iter), \
         patch.object(runner, "validate_workspace_layout", return_value=None), \
         patch.object(runner, "WorkflowLLMConfig"):
        runner.main()

    # Assertions
    log_path = os.path.join(workspace, "evolution_log.jsonl")
    assert os.path.exists(log_path), "evolution_log.jsonl must be written"
    lines = [json.loads(ln) for ln in open(log_path)]
    failure_lines = [ln for ln in lines if ln.get("kind") == "iteration_failure"]
    assert len(failure_lines) == 1
    assert failure_lines[0]["iteration"] == 2
    assert failure_lines[0]["architecture_name"] == "bad_arch"

    # chain_log.txt must be tee'd
    chain_log = os.path.join(workspace, "chain_log.txt")
    assert os.path.exists(chain_log)
    log_text = open(chain_log).read()
    assert "[WARNING] Iteration 2 failed" in log_text
    assert "Iteration 3 completed" in log_text


def test_consecutive_failure_brake_fires(tmp_path, runner):
    workspace = str(tmp_path / "ws")
    args = _stub_args(workspace, max_iterations=10, max_failed_iterations=3)
    args.advice = _make_advice_file(tmp_path)
    args.seed_paths = [_stub_seed_path(tmp_path)]

    call_count = {"n": 0}

    def _always_fail(args, ws, llm_cfg, advice, source_paths, iteration):
        call_count["n"] += 1
        return {
            "status": "no_records", "output_path": None,
            "iteration_dir": os.path.join(workspace, f"iter_{iteration:03d}"),
            "model_name": f"bad_{iteration}", "best_score": None,
            "completed_rounds": 0,
        }

    with patch.object(runner, "parse_args", return_value=args), \
         patch.object(runner, "_run_one_iter", side_effect=_always_fail), \
         patch.object(runner, "validate_workspace_layout", return_value=None), \
         patch.object(runner, "WorkflowLLMConfig"), \
         pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 1
    # Brake fires after max_failed_iterations=3 consecutive failures
    assert call_count["n"] == 3

    log_path = os.path.join(workspace, "evolution_log.jsonl")
    failure_lines = [json.loads(ln) for ln in open(log_path)
                     if json.loads(ln).get("kind") == "iteration_failure"]
    assert len(failure_lines) == 3
    assert [ln["iteration"] for ln in failure_lines] == [1, 2, 3]
