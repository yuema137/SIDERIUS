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

#: Validation-posture fields `_build_runtime_policy` reads. These stubs
#: hand-list what the helper happens to read, so every new field it reads
#: breaks all three at once — which is how CI went red on 2026-08-14.
#: `None` is the production value for both.
_VALIDATION_POSTURE_OFF = {
    "validation_max_train_samples": None,
    "validation_max_samples": None,
    "validation_max_phase_seconds": None,
}


def _patch_sidecar(monkeypatch, predicted_seconds: float) -> str:
    """Make the deadline provider see one predicted component (the sidecar
    reader validates a full RuntimeObservation, so unit tests patch the
    reader with the minimal component block it returns)."""
    import core.sandbox_executor as se

    # C8d: the deadline provider requires the production prediction shape —
    # a component prediction declares its measurement-backed `source`.
    block = {
        "components": {
            "training": {
                "prediction": {
                    "predicted_seconds": predicted_seconds,
                    "source": "real_training_verification",
                }
            }
        }
    }
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
            **_VALIDATION_POSTURE_OFF,
        )
        d = _build_runtime_policy(
            agent_input, is_trial=False, chosen_time_budget=120.0, base_dir="/tmp/x"
        )
        assert d["safety_factor"] == V18_FORMAL_FACTOR
        assert d["watchdog"]["safety_factor"] == V19_WATCHDOG_FACTOR
        assert d["operator_budget_seconds"] == 7200.0
        d_trial = _build_runtime_policy(
            agent_input,
            is_trial=True,
            chosen_time_budget=20.0,
            admission_source="forecast",
            base_dir="/tmp/x",
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
            **_VALIDATION_POSTURE_OFF,
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
        lib = REPO_ROOT / "scripts" / "launch" / "_chain_common.sh"
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


RUNTIME_SURFACE_KWARGS = frozenset(
    {
        "runtime_watchdog_enabled",
        "runtime_safety_factor",
        "runtime_trial_safety_factor",
        "runtime_formal_safety_factor",
        "runtime_watchdog_safety_factor",
        "runtime_watchdog_floor_seconds",
    }
)


def _run_workflow_call_kwargs() -> set[str]:
    """Keyword names passed at the run_workflow(...) call site(s) in
    run_one_iteration.py, extracted from the AST (no import of the
    script — it is not a package)."""
    import ast

    # Step 09.5a C3: transit configuration is bound one level deeper, inside
    # the WorkflowLaunchConfig the launcher constructs. The shared extractor
    # flattens both levels so this parity guard keeps testing the binding.
    from tests.helpers.launcher_bindings import workflow_call_bindings

    source_path = REPO_ROOT / "src" / "workflows" / "run_one_iteration.py"
    flattened = set(workflow_call_bindings(source_path))
    tree = ast.parse(source_path.read_text())
    kwargs: set[str] = set(flattened)
    found_call = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_workflow"
        ):
            found_call = True
            for kw in node.keywords:
                assert kw.arg is not None, (
                    "run_workflow is called with a **dict expansion; the "
                    "kwarg-parity guard cannot see through it — pass "
                    "explicit keywords instead"
                )
                kwargs.add(kw.arg)
    assert found_call, "no run_workflow(...) call found in run_one_iteration.py"
    return kwargs


class TestWorkflowKwargParity:
    """Gate 0 attempt-1 regression (2026-07-29): run_one_iteration.py passed
    runtime_watchdog_safety_factor but run_workflow() did not accept it —
    an immediate pre-LLM TypeError that no test caught because nothing
    asserted CLI↔workflow kwarg parity. These tests close that class of gap
    for EVERY kwarg, not just the runtime surface."""

    def test_every_run_one_iteration_kwarg_accepted_by_run_workflow(self):
        import inspect

        from workflows.model_exploration import run_workflow

        sig = inspect.signature(run_workflow)
        assert not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()), (
            "run_workflow grew **kwargs; this parity guard is now vacuous"
        )
        # Step 09.5a C3: the launcher binds transit configuration inside the
        # WorkflowLaunchConfig it constructs, so the accepted surface is the
        # signature PLUS the carrier's fields. The Gate-0 failure this guards
        # — the launcher passing something the workflow layer cannot accept —
        # is unchanged.
        from workflows.run_config import launch_config_field_names

        accepted = set(sig.parameters) | launch_config_field_names()
        unknown = _run_workflow_call_kwargs() - accepted
        assert not unknown, (
            f"run_one_iteration.py passes kwargs run_workflow() does not "
            f"accept (this is the exact Gate 0 attempt-1 failure): {sorted(unknown)}"
        )

    def test_runtime_surface_present_at_every_layer(self):
        """The six runtime-control kwargs exist at the call site, the
        workflow signature, the protocol signature, and the schema."""
        import inspect

        from agent.schemas.hyperparam_tuning import HyperparamTuningInput
        from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
            local_validated_model,
        )
        from workflows.model_exploration import run_workflow

        call_kwargs = _run_workflow_call_kwargs()
        from workflows.run_config import launch_config_field_names

        workflow_params = set(inspect.signature(run_workflow).parameters) | (
            launch_config_field_names()
        )
        protocol_params = set(inspect.signature(local_validated_model).parameters)
        schema_fields = set(HyperparamTuningInput.model_fields)
        for name in sorted(RUNTIME_SURFACE_KWARGS):
            assert name in call_kwargs, f"{name} not passed by run_one_iteration"
            assert name in workflow_params, f"{name} missing from run_workflow()"
            assert name in protocol_params, f"{name} missing from local_validated_model()"
            assert name in schema_fields, f"{name} missing from HyperparamTuningInput"

    def test_workflow_forwards_watchdog_factor_into_protocol_call(self):
        """run_workflow forwards its runtime_watchdog_safety_factor parameter
        (same-named variable) into the local_validated_model(...) call."""
        import ast

        source_path = REPO_ROOT / "src/workflows" / "model_exploration.py"
        tree = ast.parse(source_path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "local_validated_model"
            ):
                for kw in node.keywords:
                    if kw.arg == "runtime_watchdog_safety_factor":
                        # Step 09.5a C3: forwarded as `launch.<name>` now. The
                        # invariant — the workflow passes ITS value straight
                        # through, unrenamed and unmodified — is unchanged.
                        forwarded = ast.unparse(kw.value)
                        assert forwarded in (
                            "runtime_watchdog_safety_factor",
                            "launch.runtime_watchdog_safety_factor",
                        ), forwarded
                        return
        raise AssertionError(
            "local_validated_model(...) call does not forward runtime_watchdog_safety_factor"
        )

    def test_cli_value_reaches_watchdog_config(self):
        """Propagation end: agent input carrying 3.5 produces a validated
        RuntimeControlPolicy whose WatchdogConfig.safety_factor is 3.5 while
        formal admission keeps factor 2.0 (both phases)."""
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
            **_VALIDATION_POSTURE_OFF,
        )
        for is_trial, budget in ((False, 120.0), (True, 5.0)):
            d = _build_runtime_policy(
                agent_input, is_trial=is_trial, chosen_time_budget=budget, base_dir="/t"
            )
            policy = RuntimeControlPolicy.model_validate(
                {k: v for k, v in d.items() if k != "observation_store_root"}
            )
            assert policy.watchdog.safety_factor == V19_WATCHDOG_FACTOR
        formal = _build_runtime_policy(
            agent_input, is_trial=False, chosen_time_budget=120.0, base_dir="/t"
        )
        assert formal["safety_factor"] == V18_FORMAL_FACTOR
