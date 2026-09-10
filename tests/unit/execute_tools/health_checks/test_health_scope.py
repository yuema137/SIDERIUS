"""
DataScope-aware HealthGate config surface (DS4).

Covers:
  * apply_monitored_files — one shared run-level list applied uniformly to
    every declared check (blocking + recording-only); pure.
  * validate_health_scope — every check validated; a check without an
    explicit peek_file_indices counts as full-dataset access (violation
    under a partial scope). No intersection, no fallback.
  * materialize_effective_config — atomic write, body-sha reuse, mismatch
    diagnostics (operator inputs vs source drift).

See docs/design/enable_partial_file_list.md (Commit DS4).
"""

from __future__ import annotations

import pytest
import yaml

from execute_tools.health_checks.config import (
    EFFECTIVE_CONFIG_BASENAME,
    ActionConfig,
    CheckRef,
    GateConfig,
    HealthChecksConfig,
    apply_monitored_files,
    clear_health_gates_config_cache,
    load_health_gates_config,
    materialize_effective_config,
    validate_health_scope,
)
from execute_tools.health_checks.schemas import GateAction

SCOPE_4_9 = [4, 5, 6, 7, 8, 9]
FULL_SCOPE = list(range(20))
MONITORED = [4, 7, 9]

SYNTHETIC_GATE_IDS = {"synthetic_blocking", "synthetic_observational"}


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


def _synthetic_config() -> HealthChecksConfig:
    """A task-neutral roster that exercises both operational dispositions."""

    def gate(gate_id: str, role: str, checks: list[str]) -> GateConfig:
        return GateConfig(
            id=gate_id,
            gate_role=role,
            after_round="every",
            short_circuit=role == "blocking",
            on_pass=ActionConfig(action=GateAction.CONTINUE),
            on_fail=ActionConfig(
                action=(GateAction.INVALIDATE_ROUND if role == "blocking" else GateAction.CONTINUE)
            ),
            checks=[
                CheckRef(
                    name=name,
                    config={"peek_file_indices": [3, 10, 17]} if role == "blocking" else {},
                )
                for name in checks
            ],
        )

    return HealthChecksConfig(
        health_gates=[
            gate("synthetic_blocking", "blocking", ["check_a", "check_b"]),
            gate("synthetic_observational", "observational", ["check_c", "check_d"]),
        ]
    )


@pytest.fixture
def synthetic_config_path(tmp_path):
    path = tmp_path / "synthetic_health.yaml"
    path.write_text(yaml.safe_dump(_synthetic_config().model_dump(mode="json"), sort_keys=True))
    return str(path)


# ---------------------------------------------------------------------------
# apply_monitored_files
# ---------------------------------------------------------------------------


class TestApplyMonitoredFiles:
    def test_every_declared_check_receives_the_list(self):
        cfg = apply_monitored_files(_synthetic_config(), MONITORED)
        assert {g.id for g in cfg.health_gates} == SYNTHETIC_GATE_IDS
        for gate in cfg.health_gates:
            for check in gate.checks:
                assert check.config["peek_file_indices"] == MONITORED, (
                    f"{gate.id}/{check.name} missing shared monitored list"
                )

    def test_normalizes_sorted_deduped(self):
        cfg = apply_monitored_files(_synthetic_config(), [9, 4, 4, 7])
        for gate in cfg.health_gates:
            for check in gate.checks:
                assert check.config["peek_file_indices"] == [4, 7, 9]

    def test_pure_original_config_unmodified(self):
        original = _synthetic_config()
        snapshot = original.model_dump()
        apply_monitored_files(original, MONITORED)
        assert original.model_dump() == snapshot

    def test_empty_files_rejected(self):
        with pytest.raises(ValueError, match="must be non-empty"):
            apply_monitored_files(_synthetic_config(), [])


# ---------------------------------------------------------------------------
# validate_health_scope
# ---------------------------------------------------------------------------


class TestValidateHealthScope:
    def test_declared_roster_passes_full_scope(self):
        validate_health_scope(_synthetic_config(), FULL_SCOPE)

    def test_declared_roster_fails_partial_scope_naming_every_gate(self):
        with pytest.raises(ValueError) as exc_info:
            validate_health_scope(_synthetic_config(), SCOPE_4_9)
        msg = str(exc_info.value)
        for gate_id in SYNTHETIC_GATE_IDS:
            assert gate_id in msg, f"{gate_id} not named in the violation message"
        # Blocking gates: explicit [3,10,17] outside; recording: missing key.
        assert "outside the DataScope" in msg
        assert "defaults to full-dataset access" in msg
        assert "--health_gate_files" in msg

    def test_override_within_scope_passes(self):
        cfg = apply_monitored_files(_synthetic_config(), MONITORED)
        validate_health_scope(cfg, SCOPE_4_9)

    def test_override_outside_scope_fails(self):
        cfg = apply_monitored_files(_synthetic_config(), [3, 7, 10])
        with pytest.raises(ValueError, match=r"\[3, 10\] outside the DataScope"):
            validate_health_scope(cfg, SCOPE_4_9)

    def test_composed_full_scope_uses_its_explicit_partition_count(self):
        """Catch preflight comparing an external task against legacy topology.

        A 370-partition composed task is complete over ``range(370)`` even
        when the not-yet-bound process default describes a 20-partition task.
        Without the explicit count, recording checks are falsely classified
        as full-dataset access under a partial scope and startup is refused.
        """
        external_full_scope = list(range(370))

        with pytest.raises(ValueError, match="partial DataScope"):
            validate_health_scope(_synthetic_config(), external_full_scope)
        validate_health_scope(
            _synthetic_config(),
            external_full_scope,
            dataset_partition_count=370,
        )


# ---------------------------------------------------------------------------
# materialize_effective_config
# ---------------------------------------------------------------------------


class TestMaterializeEffectiveConfig:
    def test_written_file_loads_with_override_everywhere(self, tmp_path, synthetic_config_path):
        path, sha = materialize_effective_config(
            synthetic_config_path, MONITORED, str(tmp_path), resolved_scope=SCOPE_4_9
        )
        assert path.endswith(EFFECTIVE_CONFIG_BASENAME)
        loaded = load_health_gates_config(path)
        for gate in loaded.health_gates:
            for check in gate.checks:
                assert check.config["peek_file_indices"] == MONITORED
        assert len(sha) == 64

    def test_files_none_materializes_source_unchanged(self, tmp_path, synthetic_config_path):
        """The ROSTER survives materialization untouched.

        Compared gate-by-gate rather than model-to-model since Step 08b C5:
        the materialized artifact deliberately carries no `health_policy`
        (composition already consumed it and baked the result into each
        gate), so the two models differ in a field whose absence is the
        point.
        """
        path, _sha = materialize_effective_config(synthetic_config_path, None, str(tmp_path))
        loaded = load_health_gates_config(path)
        assert loaded.health_gates == _synthetic_config().health_gates

    def test_reuse_on_identical_inputs(self, tmp_path, synthetic_config_path):
        path1, sha1 = materialize_effective_config(synthetic_config_path, MONITORED, str(tmp_path))
        path2, sha2 = materialize_effective_config(synthetic_config_path, MONITORED, str(tmp_path))
        assert (path1, sha1) == (path2, sha2)

    def test_changed_operator_inputs_error(self, tmp_path, synthetic_config_path):
        materialize_effective_config(synthetic_config_path, MONITORED, str(tmp_path))
        with pytest.raises(ValueError, match="operator inputs changed"):
            materialize_effective_config(synthetic_config_path, [5, 8], str(tmp_path))

    def test_source_drift_error(self, tmp_path):
        # Copy the repo YAML to a mutable location, materialize, then edit
        # the source — re-materialization must diagnose drift.
        src = tmp_path / "source.yaml"
        src.write_text(yaml.safe_dump(_synthetic_config().model_dump(mode="json"), sort_keys=True))
        ws = tmp_path / "ws"
        materialize_effective_config(str(src), MONITORED, str(ws))
        # Drift a value the framework file actually owns. Since C5 the
        # thresholds live in the task config, and policy is what this file
        # carries — flipping a blocking gate's on_fail is exactly the kind
        # of silent change workspace-immutability exists to catch.
        src.write_text(src.read_text().replace("id: synthetic_blocking", "id: changed_blocking"))
        with pytest.raises(ValueError, match="source YAML content drifted"):
            materialize_effective_config(str(src), MONITORED, str(ws))

    def test_scope_validation_inside_materialize(self, tmp_path, synthetic_config_path):
        with pytest.raises(ValueError, match="violate the DataScope"):
            materialize_effective_config(
                synthetic_config_path, None, str(tmp_path), resolved_scope=SCOPE_4_9
            )
        assert not (tmp_path / EFFECTIVE_CONFIG_BASENAME).exists()


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
