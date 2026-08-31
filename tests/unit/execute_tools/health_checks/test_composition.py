"""Step 08b C4 — composition, plugin pinning, and the three binding states.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08b_extension_architecture.md`` §3.6,
§3.7, §3.10, §4.4.

Defect classes owned here:

* **An artifact pin that does not describe the written file.** The effective
  config's body sha is workspace-immutable and fail-closed on mismatch.
* **A plugin edited in place under an unchanged config.** If plugin bytes
  were recorded only in the unhashed header, the same config with different
  code would resume happily and evaluate different gates.
* **Host paths leaking into semantic identity.** The same task package at two
  absolute paths must pin ONE identity, or relocating a checkout would break
  every resume.
* **"No binding" collapsing into "nothing was said".** These are different
  claims, and conflating them means a task that deliberately declares no
  health silently inherits another task's family.
* **Two roster authorities.** The framework file and a task config both
  declaring gates must be refused, not merged.
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

import pytest
import yaml

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks._composition import (
    HealthBindingState,
    HealthCompositionError,
    body_markers,
    compose_gate,
    resolve_composed_gates,
)
from execute_tools.health_checks._plugin_binding import ResolvedHealthPlugin
from execute_tools.health_checks._task_health_config import (
    HealthDisposition,
    HealthRosterEntry,
    TaskHealthConfig,
)
from execute_tools.health_checks.config import (
    load_health_gates_config,
    materialize_effective_config,
    read_effective_config_body_sha,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _plugin_binding.reset_run_scope()


_PLUGIN_SOURCE = textwrap.dedent("""
    from typing import Any, ClassVar

    from execute_tools.health_checks import register
    from execute_tools.health_checks.schemas import (
        CheckInputDeclaration,
        HealthCheckContext,
        HealthCheckResult,
    )


    class _PackagedCheck:
        name: ClassVar[str] = "packaged_check"
        declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
            consumes_view="vendor.view",
        )

        def run(self, ctx, config=None):
            return HealthCheckResult(check_name=self.name, passed=True, reason="")


    register(_PackagedCheck())
""")


def _task_package(root: Path, *, plugin_body: str = _PLUGIN_SOURCE) -> Path:
    """An external task package: a health config plus its plugin."""
    (root / "plugins").mkdir(parents=True, exist_ok=True)
    (root / "plugins" / "health.py").write_text(plugin_body)
    config_path = root / "task_health.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "facts": {"encoding_family": "int8_symbol_stream"},
                "plugins": [{"kind": "file", "ref": "./plugins/health.py"}],
                "roster": [
                    {
                        "gate_id": "packaged_blocking",
                        "check": "packaged_check",
                        "disposition": "blocking",
                        "parameters": {"threshold": 3},
                    }
                ],
            }
        )
    )
    return config_path


def _empty_framework_yaml(tmp_path: Path) -> str:
    """A policy-only framework config — the shape C5 makes the shipped one."""
    path = tmp_path / "framework.yaml"
    path.write_text(yaml.safe_dump({"health_gates": []}))
    return str(path)


class TestUndeclaredTaskHealthIsEmpty:
    """The framework must not select scientific Health checks for a caller."""

    def test_omitted_binding_materializes_no_gates(self, tmp_path):
        path, sha = materialize_effective_config(None, None, str(tmp_path))
        body = yaml.safe_load(Path(path).read_text())

        assert body["health_gates"] == []
        assert read_effective_config_body_sha(path) == sha

    def test_the_framework_config_carries_no_task_identity(self):
        """The forbidden failure mode, asserted on the shipped files.

        `configs/health_checks.yaml` must never become
        `tidmad: … / pets: … / <user task>: …` (parent §6a.4).
        """
        for name in ("health_checks.yaml", "health_checks_baseline_observe_mode.yaml"):
            body = yaml.safe_load((REPO_ROOT / "configs" / name).read_text())
            assert set(body) == {"health_policy"}, name
            text = (REPO_ROOT / "configs" / name).read_text().lower()
            for threshold in ("min_unique_int8_values", "min_std_mv", "collapse_threshold"):
                assert threshold not in text, f"{name} still carries {threshold}"

    def test_no_mv_per_lsb_literal_remains_in_the_health_package(self):
        """Exactly ONE numerical scale exists, and it is in the task config.

        AST-based, so the historical mentions these modules keep in their
        docstrings — which explain WHY the constant left — do not trip it.
        What must not come back is an executable one.
        """
        import ast

        package = REPO_ROOT / "execute_tools" / "health_checks"
        offenders: list[str] = []
        for source in package.glob("*.py"):
            tree = ast.parse(source.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "_MV_PER_LSB":
                    offenders.append(f"{source.name}: _MV_PER_LSB")
                if (
                    isinstance(node, ast.BinOp)
                    and isinstance(node.op, ast.Div)
                    and isinstance(node.left, ast.Constant)
                    and node.left.value == 40.0
                    and isinstance(node.right, ast.Constant)
                    and node.right.value == 128.0
                ):
                    offenders.append(f"{source.name}: 40.0 / 128.0")

        assert offenders == [], offenders

    def test_the_pinned_sha_describes_the_file_the_run_reads(self, tmp_path):
        """Re-read and re-hash the artifact rather than trusting the return.

        A sha computed over something other than what was written would be a
        pin that describes nothing — and the mismatch would only ever surface
        as an inexplicable fail-closed resume.
        """
        path, sha = materialize_effective_config(None, None, str(tmp_path), resolved_scope=None)

        assert read_effective_config_body_sha(path) == sha


class TestCompositionIsDeterministic:
    def test_repeated_composition_of_the_same_input_is_identical(self, tmp_path):
        first, _ = materialize_effective_config(None, None, str(tmp_path / "a"))
        second, _ = materialize_effective_config(None, None, str(tmp_path / "b"))

        assert Path(first).read_text() == Path(second).read_text()

    def test_parameter_key_order_does_not_change_the_artifact(self):
        """Author-side dict ordering is not semantic; gate ORDER is."""
        forward = compose_gate(
            HealthRosterEntry(
                gate_id="g",
                check="c",
                disposition=HealthDisposition.BLOCKING,
                parameters={"alpha": 1, "beta": 2},
            ),
            (),
        )
        reverse = compose_gate(
            HealthRosterEntry(
                gate_id="g",
                check="c",
                disposition=HealthDisposition.BLOCKING,
                parameters={"beta": 2, "alpha": 1},
            ),
            (),
        )

        assert yaml.safe_dump(forward, sort_keys=True) == yaml.safe_dump(reverse, sort_keys=True)

    def test_roster_order_IS_preserved(self):
        """The executed sequence is the parity criterion, so order is semantic."""
        config = TaskHealthConfig.model_validate(
            {
                "roster": [
                    {"gate_id": "second", "check": "c", "disposition": "recording"},
                    {"gate_id": "first", "check": "c", "disposition": "recording"},
                ]
            }
        )

        gates = resolve_composed_gates([], config)

        assert [g["id"] for g in gates] == ["second", "first"]


class TestDispositionDerivesFrameworkPolicy:
    """§3.7 — and the two shapes reproduce the six shipped gates exactly."""

    def test_blocking_yields_the_shipped_blocking_policy(self):
        gate = compose_gate(
            HealthRosterEntry(
                gate_id="output_diversity_blocking",
                check="output_diversity",
                disposition=HealthDisposition.BLOCKING,
                parameters={"min_unique_int8_values": 25, "peek_samples": 100000},
                uses_health_peek_files=True,
                reason="task science",
            ),
            (3, 10, 17),
        )

        assert gate["gate_role"] == "blocking"
        assert gate["after_round"] == "every"
        assert gate["short_circuit"] is True
        assert gate["on_pass"] == {"action": "continue"}
        assert gate["on_fail"] == {"action": "invalidate_round"}
        assert gate["checks"] == [
            {
                "name": "output_diversity",
                "config": {
                    "min_unique_int8_values": 25,
                    "peek_samples": 100000,
                    # C2 flip (operator-frozen, 2026-08-26): the blocking
                    # policy injects all_pass; any_pass before.
                    "aggregation": "all_pass",
                    "peek_file_indices": [3, 10, 17],
                },
            }
        ]
        assert gate["reason"] == "task science"

    def test_recording_yields_the_shipped_recording_policy(self):
        gate = compose_gate(
            HealthRosterEntry(
                gate_id="per_file_output_std_recording",
                check="per_file_output_std",
                disposition=HealthDisposition.RECORDING,
                parameters={"peek_samples": 100000},
            ),
            (3, 10, 17),
        )

        assert gate["gate_role"] == "observational"
        assert gate["short_circuit"] is False
        assert gate["on_pass"] == {"action": "continue"}
        assert gate["on_fail"] == {"action": "continue"}
        # No aggregation, and NO peek set: the recording gates read every
        # file today, and injecting the triplet would be a policy change.
        assert gate["checks"][0]["config"] == {"peek_samples": 100000}

    def test_two_roster_authorities_are_refused(self):
        """Refused, not merged and not resolved by precedence."""
        config = TaskHealthConfig.model_validate(
            {"roster": [{"gate_id": "g", "check": "c", "disposition": "blocking"}]}
        )

        with pytest.raises(HealthCompositionError) as excinfo:
            resolve_composed_gates([{"id": "framework_gate"}], config)

        assert "Exactly one authority owns the roster" in str(excinfo.value)


class TestThreeBindingStatesAreDistinct:
    """§3.10 — "nothing was said" and "there is none" are different claims."""

    def test_legacy_omitted_explicit_none_and_explicit_binding_differ(
        self, tmp_path, preserved_registry
    ):
        framework = _empty_framework_yaml(tmp_path)
        config_path = _task_package(tmp_path / "pkg")

        # Three states are three RUNS, which in production are three
        # processes. The run-scope ledger fails closed on a second, different
        # plugin set in one process — correctly — so each is given its own
        # scope here rather than the guard being weakened.
        _, legacy = materialize_effective_config(framework, None, str(tmp_path / "ws_a"))
        _plugin_binding.reset_run_scope()
        _, none_bound = materialize_effective_config(
            framework,
            None,
            str(tmp_path / "ws_b"),
            task_health_binding=HealthBindingState.EXPLICIT_NONE,
        )
        _plugin_binding.reset_run_scope()
        _, explicit = materialize_effective_config(
            framework, None, str(tmp_path / "ws_c"), task_health_binding=str(config_path)
        )

        assert len({legacy, none_bound, explicit}) == 3

    def test_explicit_none_records_a_named_absence_and_no_gates(self, tmp_path):
        """The pin itself says no family was bound.

        "No gates ran" and "gates ran and passed" must not look alike, which
        is the whole reason the marker is in the HASHED body.
        """
        path, _ = materialize_effective_config(
            _empty_framework_yaml(tmp_path),
            None,
            str(tmp_path / "ws"),
            task_health_binding=HealthBindingState.EXPLICIT_NONE,
        )
        body = yaml.safe_load(Path(path).read_text())

        assert body["task_health_binding"] == "explicit_none"
        assert body["health_gates"] == []

    def test_explicit_none_never_falls_back_to_a_shipped_family(self, tmp_path):
        """The synthesized-evidence failure the parent §6a.5 forbids.

        Pointed at the REAL shipped framework config, which still carries
        TIDMAD's six gates at C4: explicit-none must not acquire a task
        roster from anywhere, and must stay distinguishable from state A.
        """
        _, explicit_none = materialize_effective_config(
            None, None, str(tmp_path / "b"), task_health_binding=HealthBindingState.EXPLICIT_NONE
        )
        _, legacy = materialize_effective_config(None, None, str(tmp_path / "a"))

        assert explicit_none != legacy

    def test_explicit_none_survives_being_READ_BACK(self, tmp_path):
        """F-6 — the named absence must survive the round trip, not just the write.

        The two tests above prove the ARTIFACT records the decision. Nothing
        proved the LOADER still honoured it, and it did not: every path-based
        consumer reads the materialized file back through
        ``load_health_gates_config``, whose composition guard asked
        ``if cfg.health_gates:`` — FALSY for a roster that is empty BY
        DECISION. So an ``explicit_none`` effective config was treated as "no
        roster supplied" and acquired the LEGACY task's family, which is the
        one outcome this binding state exists to make impossible.

        Fails as: a non-empty roster coming back out of a config that declares
        none, or the marker not surviving the load (it is the only thing that
        distinguishes explicitly-empty from absent, and it was being dropped
        as an undeclared extra).
        """
        path, _ = materialize_effective_config(
            None,
            None,
            str(tmp_path / "ws"),
            task_health_binding=HealthBindingState.EXPLICIT_NONE,
        )

        reloaded = load_health_gates_config(path)

        assert [g.id for g in reloaded.health_gates] == []
        assert reloaded.task_health_binding == "explicit_none"

    def test_a_composed_roster_that_is_read_back_is_not_composed_again(self, tmp_path):
        """The same guard from the other side, so the fix is not a special case.

        A LEGACY_OMITTED effective config carries a real roster AND the
        marker. Reading it back must return exactly what was written — not a
        second composition pass over it.
        """
        path, _ = materialize_effective_config(None, None, str(tmp_path / "ws"))
        written = yaml.safe_load(Path(path).read_text())

        reloaded = load_health_gates_config(path)

        assert [g.id for g in reloaded.health_gates] == [g["id"] for g in written["health_gates"]]
        assert reloaded.task_health_binding == "legacy_default"

    def test_an_explicit_binding_composes_the_task_roster(self, tmp_path, clean_registry):
        config_path = _task_package(tmp_path / "pkg")

        path, _ = materialize_effective_config(
            _empty_framework_yaml(tmp_path),
            None,
            str(tmp_path / "ws"),
            task_health_binding=str(config_path),
        )
        body = yaml.safe_load(Path(path).read_text())

        assert [g["id"] for g in body["health_gates"]] == ["packaged_blocking"]
        assert body["health_gates"][0]["checks"][0]["config"]["threshold"] == 3
        assert body["task_health_binding"] == "explicit"


class TestPluginBytesAreInThePinnedIdentity:
    """§3.6 — the property that makes an in-place plugin edit fail closed."""

    def test_the_resolved_plugin_set_is_in_the_hashed_body(self, tmp_path, clean_registry):
        config_path = _task_package(tmp_path / "pkg")

        path, sha = materialize_effective_config(
            _empty_framework_yaml(tmp_path),
            None,
            str(tmp_path / "ws"),
            task_health_binding=str(config_path),
        )
        body = yaml.safe_load(Path(path).read_text())

        assert body["resolved_plugins"] == [
            {
                "configured_ref": "plugins/health.py",
                "member": "",
                "content_sha256": hashlib.sha256(_PLUGIN_SOURCE.encode()).hexdigest(),
            }
        ]
        # And it is genuinely HASHED, not merely written: the reader that
        # verifies a resume recomputes the same sha from these bytes.
        assert read_effective_config_body_sha(path) == sha

    def test_no_absolute_path_appears_in_the_hashed_body(self, tmp_path, clean_registry):
        config_path = _task_package(tmp_path / "pkg")

        path, _ = materialize_effective_config(
            _empty_framework_yaml(tmp_path),
            None,
            str(tmp_path / "ws"),
            task_health_binding=str(config_path),
        )
        lines = Path(path).read_text().splitlines()
        body = "\n".join(line for line in lines if not line.startswith("#"))

        assert str(tmp_path) not in body

    def test_rematerializing_an_effective_config_preserves_the_plugin_pin(
        self, tmp_path, clean_registry
    ):
        """A child workspace must retain the chain's resolved plugin identity."""
        config_path = _task_package(tmp_path / "pkg")
        first_path, first_sha = materialize_effective_config(
            _empty_framework_yaml(tmp_path),
            None,
            str(tmp_path / "chain"),
            task_health_binding=str(config_path),
        )

        _plugin_binding.reset_run_scope()
        second_path, second_sha = materialize_effective_config(
            first_path,
            None,
            str(tmp_path / "child"),
            task_health_binding=str(config_path),
        )

        assert second_sha == first_sha
        assert (
            yaml.safe_load(Path(second_path).read_text())["resolved_plugins"]
            == (yaml.safe_load(Path(first_path).read_text())["resolved_plugins"])
        )

        none_path, _ = materialize_effective_config(
            first_path,
            None,
            str(tmp_path / "explicit_none"),
            task_health_binding=HealthBindingState.EXPLICIT_NONE,
        )
        none_body = yaml.safe_load(Path(none_path).read_text())
        assert none_body["task_health_binding"] == "explicit_none"
        assert "resolved_plugins" not in none_body

    def test_mutated_plugin_bytes_change_the_pin_and_fail_a_resume_closed(
        self, tmp_path, clean_registry
    ):
        """Same config, same path, different code → refusal.

        Recording the plugin only in the unhashed header would leave exactly
        this case silently accepted, which is why §3.6 requires the digest in
        the hashed body.
        """
        pkg = tmp_path / "pkg"
        config_path = _task_package(pkg)
        workspace = str(tmp_path / "ws")
        framework = _empty_framework_yaml(tmp_path)

        _, first = materialize_effective_config(
            framework, None, workspace, task_health_binding=str(config_path)
        )

        # Simulate the RESUME, which happens in a fresh process: neither the
        # run-scope ledger nor the registration from the first load exists.
        (pkg / "plugins" / "health.py").write_text(_PLUGIN_SOURCE + "\n# behaviour changed\n")
        _plugin_binding.reset_run_scope()
        clean_registry.pop("packaged_check", None)

        with pytest.raises(ValueError) as excinfo:
            materialize_effective_config(
                framework, None, workspace, task_health_binding=str(config_path)
            )

        assert "workspace-immutable" in str(excinfo.value)
        assert "source YAML content drifted" in str(excinfo.value)
        # The FIRST pin is what the workspace still holds.
        assert (
            read_effective_config_body_sha(str(Path(workspace) / "health_checks_effective.yaml"))
            == first
        )

    def test_the_changed_digest_reaches_the_run_identity_by_its_own_name(
        self, tmp_path, clean_registry
    ):
        """Closes the chain: plugin bytes → body sha → the LOCKED field.

        The workspace-level refusal above proves the artifact is immutable.
        This proves the same sha is the one the run-invariants lock pins, so
        a mutated plugin fails a resume with ``health_config_sha256`` named —
        rather than the digest ending up somewhere nothing compares.
        """
        from core.run_invariants import (
            RunInvariants,
            RunInvariantsViolation,
            ensure_run_invariants,
            validate_run_invariants,
        )

        assert "health_config_sha256" in RunInvariants._CANONICAL

        workspace = str(tmp_path / "ws")
        pkg = tmp_path / "pkg"
        config_path = _task_package(pkg)
        _, first = materialize_effective_config(
            _empty_framework_yaml(tmp_path),
            None,
            workspace,
            task_health_binding=str(config_path),
        )
        locked = RunInvariants(
            resolved_data_scope=[],
            health_gate_enabled=True,
            health_config_sha256=first,
        )
        ensure_run_invariants(workspace, locked)

        drifted = locked.model_copy(update={"health_config_sha256": first[::-1]})
        with pytest.raises(RunInvariantsViolation) as excinfo:
            validate_run_invariants(workspace, drifted)

        assert "health_config_sha256" in str(excinfo.value)

    def test_the_same_package_at_two_absolute_paths_pins_one_identity(
        self, tmp_path, clean_registry
    ):
        """Host paths are not load-bearing (§3.6 operator amendment)."""
        first_config = _task_package(tmp_path / "checkout_one")
        second_config = _task_package(tmp_path / "checkout_two")
        framework = _empty_framework_yaml(tmp_path)

        _, first = materialize_effective_config(
            framework, None, str(tmp_path / "ws_a"), task_health_binding=str(first_config)
        )
        # Deliberately NO reset: the run-scope ledger must recognise the
        # relocated package as the SAME set and skip re-execution. A reset
        # here would hide that, and re-running the module would raise on
        # duplicate registration.
        _, second = materialize_effective_config(
            framework, None, str(tmp_path / "ws_b"), task_health_binding=str(second_config)
        )

        assert first == second

    def test_canonical_identity_is_what_gets_hashed(self):
        """Pins the CONCEPT: three fields, and the host path is not one."""
        plugin = ResolvedHealthPlugin(
            configured_ref="plugins/a.py",
            member="",
            content_sha256="deadbeef",
            absolute_path="/host/specific/plugins/a.py",
        )

        markers = body_markers(HealthBindingState.LEGACY_OMITTED, (plugin,))
        assert markers["task_health_binding"] == "legacy_default"

        markers = body_markers("some/task.yaml", (plugin,))
        assert markers["resolved_plugins"] == [
            {"configured_ref": "plugins/a.py", "member": "", "content_sha256": "deadbeef"}
        ]


class TestExistingReadersStillWork:
    """The composed artifact must not break its downstream consumers."""

    def test_the_wave_summary_reader_shape_survives(self, tmp_path, clean_registry):
        """``scripts/v18_wave_summary.py`` walks health_gates → checks → config."""
        config_path = _task_package(tmp_path / "pkg")
        path, _ = materialize_effective_config(
            _empty_framework_yaml(tmp_path),
            None,
            str(tmp_path / "ws"),
            task_health_binding=str(config_path),
        )

        raw = yaml.safe_load(Path(path).read_text())
        seen = [
            check.get("config")
            for gate in (raw or {}).get("health_gates", [])
            for check in gate.get("checks", [])
        ]

        assert seen and all(isinstance(c, dict) for c in seen)

    def test_the_body_sha_reader_tolerates_a_missing_or_corrupt_file(self, tmp_path):
        missing = str(tmp_path / "absent.yaml")
        corrupt = tmp_path / "corrupt.yaml"
        corrupt.write_text("# header\nhealth_gates: [oops\n")

        assert read_effective_config_body_sha(missing) is None
        assert read_effective_config_body_sha(str(corrupt)) is None
