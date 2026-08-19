"""Step 08b C7 — the completion criterion, made executable.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08b_extension_architecture.md`` §4.7,
and the roadmap's forward external-extensibility invariant.

**The claim, stated correctly.** 08b necessarily edits ``execute_tools/`` to
CREATE the seam, so "zero diffs to execute_tools" would be the wrong
assertion. The real one is:

    After the generic seam exists, adding a synthetic external FOURTH task
    requires ZERO ADDITIONAL infrastructure-source registration, config or
    import edits.

Asserted by the fixture's identifiers being absent from production source
plus a remove/restore negative control — **never** by inspecting ``git
diff``, which would only describe this commit rather than the property.

The fixture task is deliberately unlike TIDMAD: a different capability key,
its own provider, its own check, its own thresholds, and no relationship to
any shipped check. If the seam only worked for something TIDMAD-shaped, that
would be a task registry wearing a plugin's clothes.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

from execute_tools.health_checks import _plugin_binding, registry, runner
from execute_tools.health_checks._plugin_binding import (
    HealthBindingError,
    HealthPluginError,
)
from execute_tools.health_checks.config import (
    load_composed_health_config,
    materialize_effective_config,
)
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    HealthCheckContext,
    TaskHealthFacts,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

PRODUCTION_PACKAGES = ("execute_tools", "nodes", "agent", "core", "scripts", "workflows", "configs")

# Every identifier the synthetic task invents. None may appear in production
# source — that absence IS the extension proof.
FIXTURE_IDENTIFIERS = (
    "acme_sensor_health",
    "acme.window_statistics",
    "acme_window_dispersion",
    "acme.window_provider",
)


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _plugin_binding.reset_run_scope()


_PLUGIN = textwrap.dedent('''
    """An out-of-tree task's Health plugin. Nothing in SIDERIUS knows it exists."""

    from typing import Any, ClassVar

    from execute_tools.health_checks import (
        HealthView,
        register,
        register_view_provider,
    )
    from execute_tools.health_checks.schemas import (
        CheckInputDeclaration,
        HealthCheckContext,
        HealthCheckResult,
    )

    CAPABILITY = "acme.window_statistics"


    class AcmeWindowProvider:
        """Knows how to read THIS task's outputs. SIDERIUS never learns how."""

        provider_id: ClassVar[str] = "acme.window_provider"
        capabilities: ClassVar[frozenset[str]] = frozenset({CAPABILITY})

        def materialize(self, capability_key, ctx, config=None):
            width = (config or {}).get("window", 4)
            return HealthView(
                capability_key=capability_key,
                provider_id=self.provider_id,
                payload={"windows": [[1.0] * width, [1.0, 9.0] * (width // 2)]},
            )


    class AcmeWindowDispersionCheck:
        """A task-specific check consuming a plugin-LOCAL capability."""

        name: ClassVar[str] = "acme_window_dispersion"
        declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
            consumes_view=CAPABILITY,
            requires_view=True,
            threshold_parameter_names=("min_window_spread",),
        )

        def run(
            self,
            ctx: HealthCheckContext,
            config: dict[str, Any] | None = None,
            *,
            view: HealthView | None = None,
        ) -> HealthCheckResult:
            assert view is not None, "the runner must supply the required view"
            floor = float((config or {}).get("min_window_spread", 1.0))
            spreads = [max(w) - min(w) for w in view.payload["windows"]]
            worst = min(spreads)
            return HealthCheckResult(
                check_name=self.name,
                passed=worst >= floor,
                reason=f"worst window spread {worst}",
                metrics={"worst_window_spread": worst, "threshold": floor},
            )


    register_view_provider(AcmeWindowProvider())
    register(AcmeWindowDispersionCheck())
''')


def _external_task(root: Path, *, plugin_body: str = _PLUGIN) -> Path:
    """A complete out-of-tree task package: config + plugin, nothing else."""
    (root / "plugins").mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "health.py").write_text(plugin_body)
    config = root / "acme_sensor_health.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "facts": {"encoding_family": "continuous_float"},
                "plugins": [{"kind": "file", "ref": "./plugins/health.py"}],
                "providers": [{"provider_id": "acme.window_provider", "config": {"window": 4}}],
                "roster": [
                    {
                        "gate_id": "acme_window_blocking",
                        "check": "acme_window_dispersion",
                        "disposition": "blocking",
                        "parameters": {"min_window_spread": 1.0},
                        "reason": "A collapsed window has no spread to speak of.",
                    }
                ],
            }
        )
    )
    return config


def _policy_only_framework(root: Path) -> str:
    path = root / "framework.yaml"
    path.write_text(yaml.safe_dump({"health_gates": []}))
    return str(path)


def _ctx() -> HealthCheckContext:
    return HealthCheckContext(model_name="acme_net", run_name="acme_run", round_index=1)


class TestTheFourthTaskRunsEndToEnd:
    """config → loader → registration → resolution → provider → check → result."""

    def test_the_whole_chain_produces_a_health_check_result(
        self, tmp_path, monkeypatch, preserved_registry
    ):
        config_path = _external_task(tmp_path / "acme")
        framework = _policy_only_framework(tmp_path)

        composed, task_config, plugins = load_composed_health_config(framework, str(config_path))

        # Loading and registration happened from the external file alone.
        assert [p.configured_ref for p in plugins] == ["plugins/health.py"]
        assert "acme_window_dispersion" in registry.all_registered()
        assert "acme.window_provider" in registry.all_registered_view_providers()

        # The roster composed, with framework policy derived from disposition.
        gate = composed.health_gates[0]
        assert gate.id == "acme_window_blocking"
        assert gate.gate_role == "blocking"
        assert gate.on_fail.action.value == "invalidate_round"
        assert gate.checks[0].config["min_window_spread"] == 1.0

        # And the gate actually runs, through the provider, to a verdict.
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: composed)
        monkeypatch.setattr(runner, "_resolve_task_facts", lambda: task_config.resolved_facts())
        result = runner.evaluate_gate("acme_window_blocking", _ctx())

        check_result = result.check_results[0]
        assert check_result.check_name == "acme_window_dispersion"
        # The metric could only have been computed from the provider's
        # payload, so its presence is the end-to-end evidence. WHAT it
        # decided is the next test's subject.
        assert "worst_window_spread" in check_result.metrics
        assert check_result.verdict in (CheckVerdict.PASSED, CheckVerdict.FAILED)

    def test_the_check_judges_the_providers_payload_rather_than_passing_blindly(
        self, tmp_path, monkeypatch, preserved_registry
    ):
        """The result must depend on what the provider supplied.

        A check that returned ``passed=True`` regardless would satisfy an
        end-to-end test that only asserts "a result came back" — which is why
        the payload contains one healthy window and one collapsed one, and
        the threshold decides between them.
        """
        config_path = _external_task(tmp_path / "acme")
        composed, task_config, _ = load_composed_health_config(
            _policy_only_framework(tmp_path), str(config_path)
        )
        monkeypatch.setattr(runner, "load_health_gates_config", lambda: composed)
        monkeypatch.setattr(runner, "_resolve_task_facts", lambda: task_config.resolved_facts())

        result = runner.evaluate_gate("acme_window_blocking", _ctx())

        # The collapsed window (spread 0.0) is the worst, and the floor is 1.0.
        assert result.check_results[0].metrics["worst_window_spread"] == 0.0
        assert result.check_results[0].verdict is CheckVerdict.FAILED
        assert result.action.value == "invalidate_round"

    def test_the_external_plugin_is_pinned_into_the_run_identity(
        self, tmp_path, preserved_registry
    ):
        """An out-of-tree task gets the same identity guarantees as a shipped one."""
        config_path = _external_task(tmp_path / "acme")
        path, _sha = materialize_effective_config(
            _policy_only_framework(tmp_path),
            None,
            str(tmp_path / "ws"),
            task_health_binding=str(config_path),
        )
        body = yaml.safe_load(Path(path).read_text())

        assert body["resolved_plugins"][0]["configured_ref"] == "plugins/health.py"
        assert len(body["resolved_plugins"][0]["content_sha256"]) == 64


class TestNoInfrastructureEditWasRequired:
    """The completion criterion itself."""

    @staticmethod
    def _git_grep(pattern: str) -> list[str]:
        proc = subprocess.run(
            ["git", "grep", "-nF", "--untracked", pattern, "--", *PRODUCTION_PACKAGES],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert proc.returncode in (0, 1), (
            f"git grep failed (rc={proc.returncode}) in {REPO_ROOT}: {proc.stderr.strip()}"
        )
        return proc.stdout.splitlines()

    def test_repo_root_resolves_to_this_checkout(self):
        """Guards the guard: a wrong root makes every census below vacuous."""
        assert (REPO_ROOT / ".git").exists()
        assert (REPO_ROOT / "execute_tools" / "health_checks" / "registry.py").is_file()

    def test_the_grep_probe_actually_finds_things(self):
        """Proves the search works, so its emptiness below is real evidence."""
        assert self._git_grep("register_view_provider"), "the probe found nothing at all"

    @pytest.mark.parametrize("identifier", FIXTURE_IDENTIFIERS)
    def test_no_fixture_identifier_appears_in_production_source(self, identifier):
        """The fourth task is unknown to SIDERIUS, by inspection.

        Covers the registry, every import list, every shipped YAML and every
        production package at once — if ANY of them had to learn this task's
        name, the seam would not be a seam.
        """
        assert self._git_grep(identifier) == []

    def test_the_shipped_configs_carry_no_task_identity(self):
        for name in ("health_checks.yaml", "health_checks_baseline_observe_mode.yaml"):
            body = yaml.safe_load((REPO_ROOT / "configs" / name).read_text())
            assert set(body) == {"health_policy"}, name

    def test_the_central_import_list_registers_only_built_ins(self):
        """``__init__`` keeps its bootstrap, but it is no longer the extension path."""
        source = (REPO_ROOT / "execute_tools" / "health_checks" / "__init__.py").read_text()

        for identifier in FIXTURE_IDENTIFIERS:
            assert identifier not in source

    def test_the_view_capability_vocabulary_is_open(self):
        """No closed enum of view kinds exists to be extended per task.

        ``consumes_view`` is a bare ``str`` and the engine never enumerates
        it; a plugin-local key like ``acme.window_statistics`` is exactly as
        legitimate as a shipped one.
        """
        from execute_tools.health_checks.schemas import CheckInputDeclaration

        field = CheckInputDeclaration.model_fields["consumes_view"]

        assert field.annotation is str


class TestTheNegativeControl:
    """A broken registration must fail CLOSED, and restoring must recover."""

    def test_removing_the_plugin_fails_the_run_closed(self, tmp_path, preserved_registry):
        config_path = _external_task(tmp_path / "acme")
        (tmp_path / "acme" / "plugins" / "health.py").unlink()

        with pytest.raises(HealthPluginError) as excinfo:
            load_composed_health_config(_policy_only_framework(tmp_path), str(config_path))

        assert "plugins/health.py" in str(excinfo.value)

    def test_a_plugin_that_registers_nothing_fails_at_RESOLUTION_not_silently(
        self, tmp_path, preserved_registry
    ):
        """Loading succeeded; the DECLARED binding is what fails closed.

        This is the distinction §3.2 freezes: a file that loads is not a
        binding that resolves, and the error names the check the config
        asked for rather than the file.
        """
        config_path = _external_task(tmp_path / "acme", plugin_body="VALUE = 1\n")

        with pytest.raises(HealthBindingError) as excinfo:
            load_composed_health_config(_policy_only_framework(tmp_path), str(config_path))

        assert "acme_window_dispersion" in str(excinfo.value)

    def test_restoring_the_plugin_makes_the_flow_succeed_again(self, tmp_path, preserved_registry):
        """The other direction, which is what makes the negative control a control.

        Without it, a seam that ALWAYS failed would satisfy every test above.
        """
        config_path = _external_task(tmp_path / "acme", plugin_body="VALUE = 1\n")
        with pytest.raises(HealthBindingError):
            load_composed_health_config(_policy_only_framework(tmp_path), str(config_path))

        _plugin_binding.reset_run_scope()
        (tmp_path / "acme" / "plugins" / "health.py").write_text(_PLUGIN)

        composed, _task, _plugins = load_composed_health_config(
            _policy_only_framework(tmp_path), str(config_path)
        )

        assert [g.id for g in composed.health_gates] == ["acme_window_blocking"]

    def test_the_fixture_imports_nothing_from_the_repo_but_the_public_api(self):
        """Guards against the proof passing for the wrong reason.

        If the fixture reached into an in-repo module for its provider or
        check, the chain would work without the seam working.
        """
        imported = [
            line.strip()
            for line in _PLUGIN.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        siderius = [line for line in imported if "execute_tools" in line]

        assert siderius and all(
            line.startswith("from execute_tools.health_checks import")
            or line.startswith("from execute_tools.health_checks.schemas import")
            for line in siderius
        ), imported


class TestTheProofIsNotSelfCongratulatory:
    """The census is only meaningful if it could fail."""

    def test_a_planted_identifier_would_be_detected(self, tmp_path):
        """Mutation-in-place: the same search finds a name that IS present.

        Without this, an over-narrow ``git grep`` invocation would make every
        absence assertion above pass vacuously.
        """
        census = TestNoInfrastructureEditWasRequired()

        assert census._git_grep("output_diversity") != []
        assert census._git_grep("acme_window_dispersion") == []
