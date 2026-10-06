"""Chain-runner wiring for the structured-health-feedback policy (CB5-c).

Covers: the ALL-THREE-SITES lock regression (tuner / workflow / chain —
the PR 2 lock-collision guard, extended per ``pr3_healthgate_feedback.md``
§11-CB5), CLI startup rejection of invalid retention values, the
run_workflow forwarding surface incl. the typed history carry, and the
manifest CONTROL-POLICY stamp.
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_spec = importlib.util.spec_from_file_location(
    "run_one_iteration_for_health_test",
    _REPO / "src" / "workflows" / "run_one_iteration.py",
)
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)

LOCK_SITES = {
    "tuner": _REPO / "src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
    "workflow": _REPO / "src/workflows/model_exploration.py",
    "chain": _REPO / "src/workflows/run_one_iteration.py",
}

POLICY_KWARGS = (
    "structured_health_feedback_enabled=",
    "health_feedback_history_window_iterations=",
    "health_feedback_history_max_entries_per_model=",
)


class TestAllThreeLockSites:
    """Final CB5 regression: every ``build_run_invariants(`` call site
    passes the SAME named policy fields — a site relying on builder
    defaults would write a contradictory lock and abort every flag-ON
    run (the PR 2 lock-collision failure mode)."""

    @pytest.mark.parametrize("site", sorted(LOCK_SITES))
    def test_site_passes_all_three_policy_fields(self, site):
        src = LOCK_SITES[site].read_text()
        # Window scan: a call's kwargs (incl. multi-line parenthesized
        # values) sit within a bounded span after the opening paren, so a
        # fixed window is robust to inner ')' lines that defeat a
        # non-greedy regex terminator.
        starts = [m.end() for m in re.finditer(r"build_run_invariants\(", src)]
        starts = [s for s in starts if "def build_run_invariants" not in src[s - 40 : s]]
        assert starts, f"{site}: no build_run_invariants call found"
        for s in starts:
            window = src[s : s + 1500]
            for kwarg in POLICY_KWARGS:
                assert kwarg in window, f"{site}: lock call missing {kwarg}"


class TestChainCli:
    def _args(self, extra=()):
        return roi.build_parser().parse_args(
            [
                "--workspace",
                "/tmp/ws",
                "--llm_config",
                str(_REPO / "configs/llm/certify_minimal.json"),
                "--start_iteration",
                "1",
                "--run_name",
                "t",
                "--task_composition",
                str(_REPO / "configs/task_composition/quickstart.yaml"),
                "--data_dir",
                str(_REPO),
                *extra,
            ]
        )

    def test_defaults_off_3_8(self):
        args = self._args()
        assert args.enable_structured_health_feedback is False
        assert args.health_feedback_history_window_iterations == 3
        assert args.health_feedback_history_max_entries_per_model == 8

    def test_flag_and_knobs_parse(self):
        args = self._args(
            [
                "--enable_structured_health_feedback",
                "--health_feedback_history_window_iterations",
                "5",
                "--health_feedback_history_max_entries_per_model",
                "4",
            ]
        )
        assert args.enable_structured_health_feedback is True
        assert args.health_feedback_history_window_iterations == 5
        assert args.health_feedback_history_max_entries_per_model == 4

    @pytest.mark.parametrize(
        "flag,value",
        [
            ("--health_feedback_history_window_iterations", "0"),
            ("--health_feedback_history_window_iterations", "-1"),
            ("--health_feedback_history_max_entries_per_model", "0"),
        ],
    )
    def test_invalid_retention_rejected_at_startup(self, flag, value):
        """normalize_args fails BEFORE any resume mutation or LLM work
        (parser.error → SystemExit != 0) — no partial run."""
        args = self._args([flag, value])
        with pytest.raises(SystemExit) as exc:
            roi.normalize_args(args)
        assert exc.value.code != 0

    def test_lock_built_from_cli_args(self, tmp_path):
        from workflows.task_composition import (
            bind_run_task_composition,
            compose_run_task_bindings,
        )

        args = self._args(["--enable_structured_health_feedback"])
        args.workspace = str(tmp_path)
        args.health_gate_enabled = False  # avoid materializing gate config
        args.health_gate_files = None
        composition = compose_run_task_bindings(args.task_composition)
        with bind_run_task_composition(composition, physical_data_root=args.data_dir):
            invariants = roi.compute_expected_invariants(args, run_composition=composition)
        assert invariants.structured_health_feedback_enabled is True
        assert invariants.health_feedback_history_window_iterations == 3
        assert invariants.health_feedback_history_max_entries_per_model == 8


class TestRunWorkflowForwarding:
    def test_policy_and_typed_history_forwarded(self):
        src = LOCK_SITES["chain"].read_text()
        # Step 10 / P1 C5 indented this call one level: it is now wrapped in
        # `with bind_run_task_composition(...)`, so the closing paren sits at
        # 12 spaces rather than 8.
        call = re.search(r"results = run_workflow\((.*?)\n            \)", src, re.DOTALL).group(1)
        assert "enable_structured_health_feedback=args.enable_structured_health_feedback" in call
        assert "health_feedback_history_window_iterations=" in call
        assert "health_feedback_history_max_entries_per_model=" in call
        # The restored fingerprint history now travels inside the ONE
        # `RestoredState` carrier (09.5a's C4b hand-off, closed by P1 C5)
        # rather than as its own kwarg. Same value, same source object.
        assert "restored_state=state" in call


class TestManifestPolicyStamp:
    def test_policy_stamped_as_control_policy_only(self, tmp_path):
        policy = {
            "enable_structured_health_feedback": True,
            "history_window_iterations": 3,
            "max_entries_per_model": 8,
        }
        manifest = roi.write_manifest(
            str(tmp_path), "iter_001", results=[], health_feedback_policy=policy
        )
        assert manifest["health_feedback_policy"] == policy
        # Policy ONLY: no per-round gate evidence keys in the manifest.
        assert "health_gate_results" not in manifest
        assert "collapse_fingerprint_history" not in manifest

    def test_legacy_call_without_policy_stamps_none(self, tmp_path):
        manifest = roi.write_manifest(str(tmp_path), "iter_001", results=[])
        assert manifest["health_feedback_policy"] is None
