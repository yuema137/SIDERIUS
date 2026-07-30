"""V19 admission/watchdog split (2026-07-29).

Proves the contract of `WatchdogConfig.safety_factor`:

- omitted → admission AND watchdog behave exactly as V18 (shared
  phase-effective factor);
- set to 3.5 → ONLY the watchdog deadline changes; formal admission
  keeps factor 2.0 (predicted ≤ 60 min admitted; above rejected
  exactly as before); trial admission stays record-only;
- floor and budget clamping unchanged; legacy policies load; shell/CLI
  passthrough exact; provenance carries both factors.

Design: docs/design/v19_priorities/v19_launch_protocol.md §4.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.runtime_control.session import (
    RuntimeControlPolicy,
    RuntimeVerificationSession,
    WatchdogConfig,
)
from core.sandbox_executor import _watchdog_deadline_provider

REPO_ROOT = Path(__file__).resolve().parents[3]

V18_FORMAL_BUDGET_S = 7200.0  # --formal_time_budget_minutes 120
V18_FORMAL_FACTOR = 2.0
V18_TRIAL_FACTOR = 3.0
V19_WATCHDOG_FACTOR = 3.5
V18_FLOOR_S = 120.0


def _patch_sidecar(monkeypatch, predicted_seconds: float) -> str:
    """Make the deadline provider see one predicted component (the sidecar
    reader validates a full RuntimeObservation, so unit tests patch the
    reader with the minimal component block it returns)."""
    import core.sandbox_executor as se

    block = {"components": {"training": {"prediction": {"predicted_seconds": predicted_seconds}}}}
    monkeypatch.setattr(se, "_read_runtime_observation_sidecar", lambda path: block)
    return "unused-sidecar-path"


def _formal_policy(watchdog_factor: float | None) -> RuntimeControlPolicy:
    return RuntimeControlPolicy(
        operator_budget_seconds=V18_FORMAL_BUDGET_S,
        safety_factor=V18_FORMAL_FACTOR,
        trial_safety_factor=V18_TRIAL_FACTOR,
        formal_safety_factor=V18_FORMAL_FACTOR,
        watchdog=WatchdogConfig(
            enabled=True, floor_seconds=V18_FLOOR_S, safety_factor=watchdog_factor
        ),
    )


def _trial_policy(watchdog_factor: float | None) -> RuntimeControlPolicy:
    return RuntimeControlPolicy(
        operator_budget_seconds=None,  # V18: trials are record-only
        safety_factor=V18_TRIAL_FACTOR,
        watchdog=WatchdogConfig(
            enabled=True, floor_seconds=V18_FLOOR_S, safety_factor=watchdog_factor
        ),
    )


def _admission(tmp_path: Path, policy: RuntimeControlPolicy, predicted_seconds: float):
    session = RuntimeVerificationSession(str(tmp_path / "obs.json"), policy=policy)
    session.complete_setup(storage_provenance={})
    # Overwrite the setup component's prediction with the scenario value so
    # the known-cost sum is exactly `predicted_seconds`.
    (setup_record,) = session._components.values()
    object.__setattr__(setup_record.prediction, "predicted_seconds", predicted_seconds)
    return session.decide_admission()


class TestAdmissionUnchanged:
    def test_formal_60min_still_admitted_with_watchdog_override(self, tmp_path):
        """Predicted exactly 3600 s × 2.0 = 7200 s == budget → admitted,
        with and without the 3.5 watchdog override."""
        for wf in (None, V19_WATCHDOG_FACTOR):
            rec = _admission(tmp_path, _formal_policy(wf), 3600.0)
            assert rec.decision == "admitted", f"watchdog_factor={wf}"

    def test_formal_above_boundary_rejected_identically(self, tmp_path):
        """3601 s × 2.0 > 7200 s → rejected — identically with the
        override present (admission never reads the watchdog factor)."""
        for wf in (None, V19_WATCHDOG_FACTOR):
            rec = _admission(tmp_path, _formal_policy(wf), 3601.0)
            assert rec.decision == "rejected", f"watchdog_factor={wf}"
            assert "x2" in rec.reason  # factor 2.0 quoted in the reason

    def test_admission_boundary_not_tightened_to_3_5(self, tmp_path):
        """The V19 conflict case: 2500 s predicted would be REJECTED under a
        3.5 admission factor (8750 > 7200) but must remain ADMITTED
        (2500 × 2.0 = 5000 ≤ 7200)."""
        rec = _admission(tmp_path, _formal_policy(V19_WATCHDOG_FACTOR), 2500.0)
        assert rec.decision == "admitted"

    def test_trial_admission_remains_record_only(self, tmp_path):
        """No budget → always admitted, regardless of the override and of
        an enormous prediction."""
        rec = _admission(tmp_path, _trial_policy(V19_WATCHDOG_FACTOR), 10_000_000.0)
        assert rec.decision == "admitted"
        assert "record-only" in rec.reason


class TestWatchdogDeadline:
    def test_omitted_override_reproduces_v18_deadline(self, monkeypatch):
        """Fallback: deadline uses the shared factor exactly as V18."""
        provider = _watchdog_deadline_provider(
            _formal_policy(None), _patch_sidecar(monkeypatch, 1000.0)
        )
        deadline, source = provider()
        assert source == "verified_components"
        assert deadline == 1000.0 * V18_FORMAL_FACTOR

    def test_formal_watchdog_uses_3_5(self, monkeypatch):
        provider = _watchdog_deadline_provider(
            _formal_policy(V19_WATCHDOG_FACTOR), _patch_sidecar(monkeypatch, 1000.0)
        )
        deadline, source = provider()
        assert deadline == 1000.0 * V19_WATCHDOG_FACTOR
        assert source == "verified_components"

    def test_trial_watchdog_uses_3_5(self, monkeypatch):
        provider = _watchdog_deadline_provider(
            _trial_policy(V19_WATCHDOG_FACTOR), _patch_sidecar(monkeypatch, 100.0)
        )
        deadline, _ = provider()
        assert deadline == 100.0 * V19_WATCHDOG_FACTOR

    def test_floor_remains_active(self, monkeypatch):
        """Tiny estimate → deadline clamps up to the 120 s floor."""
        provider = _watchdog_deadline_provider(
            _trial_policy(V19_WATCHDOG_FACTOR), _patch_sidecar(monkeypatch, 10.0)
        )
        deadline, _ = provider()
        assert deadline == V18_FLOOR_S

    def test_formal_budget_clamp_remains_active(self, monkeypatch):
        """Estimate × 3.5 above the 7200 s budget → budget wins the min()."""
        provider = _watchdog_deadline_provider(
            _formal_policy(V19_WATCHDOG_FACTOR), _patch_sidecar(monkeypatch, 3000.0)
        )
        deadline, source = provider()
        assert deadline == V18_FORMAL_BUDGET_S  # min(7200, 10500)
        assert source == "operator_budget"


class TestCompatibilityAndWiring:
    def test_legacy_policy_without_field_loads(self):
        """Pre-split policy payloads (no watchdog.safety_factor) validate,
        and the field defaults to None (fallback behavior)."""
        legacy = {
            "operator_budget_seconds": 7200.0,
            "safety_factor": 2.0,
            "watchdog": {"enabled": True, "floor_seconds": 120.0},
        }
        policy = RuntimeControlPolicy.model_validate(legacy)
        assert policy.watchdog.safety_factor is None

    def test_policy_provenance_records_both_factors(self):
        policy = _formal_policy(V19_WATCHDOG_FACTOR)
        dump = policy.model_dump(mode="json")
        assert dump["safety_factor"] == V18_FORMAL_FACTOR  # admission
        assert dump["watchdog"]["safety_factor"] == V19_WATCHDOG_FACTOR  # watchdog

    def test_tuner_policy_dict_wires_watchdog_factor(self):
        """The tuner helper forwards runtime_watchdog_safety_factor into the
        watchdog sub-dict and leaves the phase-effective factor alone."""
        from types import SimpleNamespace

        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _build_runtime_policy,
        )

        agent_input = SimpleNamespace(
            runtime_safety_factor=1.5,
            runtime_trial_safety_factor=V18_TRIAL_FACTOR,
            runtime_formal_safety_factor=V18_FORMAL_FACTOR,
            runtime_watchdog_enabled=True,
            runtime_watchdog_safety_factor=V19_WATCHDOG_FACTOR,
            runtime_watchdog_floor_seconds=V18_FLOOR_S,
        )
        d = _build_runtime_policy(
            agent_input, is_trial=False, chosen_time_budget=120.0, base_dir="/tmp/x"
        )
        assert d["safety_factor"] == V18_FORMAL_FACTOR
        assert d["watchdog"]["safety_factor"] == V19_WATCHDOG_FACTOR
        assert d["operator_budget_seconds"] == 7200.0
        d_trial = _build_runtime_policy(
            agent_input, is_trial=True, chosen_time_budget=20.0, base_dir="/tmp/x"
        )
        assert d_trial["safety_factor"] == V18_TRIAL_FACTOR
        assert d_trial["operator_budget_seconds"] is None
        assert d_trial["watchdog"]["safety_factor"] == V19_WATCHDOG_FACTOR

    def test_omitted_flag_gives_value_equivalent_prior_policy_dict(self):
        from types import SimpleNamespace

        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _build_runtime_policy,
        )

        agent_input = SimpleNamespace(
            runtime_safety_factor=1.5,
            runtime_trial_safety_factor=V18_TRIAL_FACTOR,
            runtime_formal_safety_factor=V18_FORMAL_FACTOR,
            runtime_watchdog_enabled=True,
            runtime_watchdog_safety_factor=None,
            runtime_watchdog_floor_seconds=V18_FLOOR_S,
        )
        d = _build_runtime_policy(
            agent_input, is_trial=False, chosen_time_budget=120.0, base_dir="/t"
        )
        assert d["watchdog"]["safety_factor"] is None  # → fallback to shared
        policy = RuntimeControlPolicy.model_validate(
            {k: v for k, v in d.items() if k != "observation_store_root"}
        )
        provider_input = policy.watchdog.safety_factor
        assert provider_input is None

    def test_shell_passthrough_exact(self):
        """--runtime_watchdog_safety_factor 3.5 reaches APP_ARGS verbatim;
        omitting it emits NO such flag (V18 command parity)."""
        lib = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"
        script = f"""
source '{lib}'
parse_chain_args --workspace /tmp/w --run_name t --mode lilab \
  --runtime_watchdog --runtime_watchdog_safety_factor 3.5
build_app_args 1
for a in "${{APP_ARGS[@]}}"; do echo "$a"; done
"""
        r = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, cwd=str(REPO_ROOT)
        )
        assert r.returncode == 0, r.stderr
        lines = r.stdout.splitlines()
        assert "--runtime_watchdog_safety_factor" in lines
        assert lines[lines.index("--runtime_watchdog_safety_factor") + 1] == "3.5"

        script_omit = f"""
source '{lib}'
parse_chain_args --workspace /tmp/w --run_name t --mode lilab --runtime_watchdog
build_app_args 1
for a in "${{APP_ARGS[@]}}"; do echo "$a"; done
"""
        r2 = subprocess.run(
            ["bash", "-c", script_omit], capture_output=True, text=True, cwd=str(REPO_ROOT)
        )
        assert r2.returncode == 0, r2.stderr
        assert "--runtime_watchdog_safety_factor" not in r2.stdout.splitlines()
