"""YAML config loader semantics.

Covers the rev-6 HealthGate config classes and their loader plus the
legacy rev-3 classes still kept until commit-6. See
``docs/design/pluggable_health_checks.md`` §3 for the schema and §15.2
for the per-commit test scope rule of thumb.

Config parsing only — this file does NOT exercise any check's ``run``
method. amplitude_collapse in the shipped YAML uses ``collapse_threshold:
0.95`` for the distribution-based predicate landing in commit-4; that
predicate is not tested here, only that the YAML parses.
"""

from __future__ import annotations

import textwrap

import pytest
from pydantic import ValidationError

from execute_tools.health_checks.config import (
    ActionConfig,
    CheckRef,
    GateConfig,
    HealthChecksConfig,
    clear_health_gates_config_cache,
    load_health_gates_config,
)
from execute_tools.health_checks.schemas import GateAction


@pytest.fixture(autouse=True)
def _clear_caches():
    """Process-wide gate-config cache is cleared before and after every
    test in this file."""
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


# ---------------------------------------------------------------------------
# rev-6 schemas — CheckRef
# ---------------------------------------------------------------------------


class TestCheckRef:
    def test_defaults(self):
        r = CheckRef(name="output_diversity")
        assert r.config == {}

    def test_config_dict_propagates(self):
        r = CheckRef(
            name="output_diversity",
            config={"min_unique_int8_values": 5, "peek_samples": 100_000},
        )
        assert r.config["min_unique_int8_values"] == 5
        assert r.config["peek_samples"] == 100_000


# ---------------------------------------------------------------------------
# rev-6 schemas — ActionConfig
# ---------------------------------------------------------------------------


class TestActionConfig:
    def test_valid_action(self):
        ac = ActionConfig(action=GateAction.CONTINUE)
        assert ac.action is GateAction.CONTINUE

    def test_action_accepts_string_value(self):
        """The YAML loader receives raw strings — Pydantic coerces to
        the GateAction StrEnum via its ``__init__``."""
        ac = ActionConfig.model_validate({"action": "skip_iter"})
        assert ac.action is GateAction.SKIP_ITER

    def test_unknown_action_string_raises(self):
        with pytest.raises(ValidationError):
            ActionConfig.model_validate({"action": "not_a_real_action"})


# ---------------------------------------------------------------------------
# rev-6 schemas — GateConfig
# ---------------------------------------------------------------------------


def _minimal_gate_kwargs(**overrides):
    """Build a minimal-valid GateConfig kwargs dict; overrides win."""
    base = {
        "id": "test_gate",
        "after_round": 1,
        "checks": [CheckRef(name="output_diversity")],
        "on_pass": ActionConfig(action=GateAction.CONTINUE),
        "on_fail": ActionConfig(action=GateAction.SKIP_ITER),
    }
    base.update(overrides)
    return base


class TestGateConfig:
    def test_minimal_valid(self):
        g = GateConfig(**_minimal_gate_kwargs())
        assert g.id == "test_gate"
        assert g.after_round == 1
        assert g.short_circuit is True  # D4: default True
        assert g.reason == ""

    def test_short_circuit_default_is_true(self):
        """D4: per-gate ``short_circuit`` moves to gate level, default True."""
        g = GateConfig(**_minimal_gate_kwargs())
        assert g.short_circuit is True

    def test_short_circuit_can_be_disabled(self):
        g = GateConfig(**_minimal_gate_kwargs(short_circuit=False))
        assert g.short_circuit is False

    def test_empty_checks_list_rejected(self):
        """D2: min_length=1 — a gate with no checks is a config error."""
        with pytest.raises(ValidationError):
            GateConfig(**_minimal_gate_kwargs(checks=[]))

    def test_on_pass_required(self):
        """D1: on_pass is required, no default."""
        kwargs = _minimal_gate_kwargs()
        del kwargs["on_pass"]
        with pytest.raises(ValidationError):
            GateConfig(**kwargs)  # type: ignore[arg-type]

    def test_on_fail_required(self):
        """D1: on_fail is required, no default."""
        kwargs = _minimal_gate_kwargs()
        del kwargs["on_fail"]
        with pytest.raises(ValidationError):
            GateConfig(**kwargs)  # type: ignore[arg-type]

    def test_reason_default_empty(self):
        g = GateConfig(**_minimal_gate_kwargs())
        assert g.reason == ""

    def test_missing_id_raises(self):
        kwargs = _minimal_gate_kwargs()
        del kwargs["id"]
        with pytest.raises(ValidationError):
            GateConfig(**kwargs)  # type: ignore[arg-type]

    def test_missing_after_round_raises(self):
        kwargs = _minimal_gate_kwargs()
        del kwargs["after_round"]
        with pytest.raises(ValidationError):
            GateConfig(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# rev-6 schemas — HealthChecksConfig
# ---------------------------------------------------------------------------


class TestHealthChecksConfig:
    def test_empty_health_gates_list_is_valid(self):
        """Empty list = no gates fire, but the config itself is valid.
        Operators may temporarily disable all gates by clearing the list."""
        cfg = HealthChecksConfig(health_gates=[])
        assert cfg.health_gates == []

    def test_single_gate_is_valid(self):
        g = GateConfig(**_minimal_gate_kwargs())
        cfg = HealthChecksConfig(health_gates=[g])
        assert len(cfg.health_gates) == 1
        assert cfg.health_gates[0].id == "test_gate"

    def test_duplicate_ids_rejected(self):
        """D3: unique gate ids required, else ValueError with dupe list."""
        g1 = GateConfig(**_minimal_gate_kwargs(id="duplicate_id"))
        g2 = GateConfig(**_minimal_gate_kwargs(id="duplicate_id"))
        with pytest.raises(ValidationError) as exc_info:
            HealthChecksConfig(health_gates=[g1, g2])
        # The Pydantic ValidationError wraps the ValueError; the dupe list
        # must appear in the message.
        assert "duplicate_id" in str(exc_info.value).lower()

    def test_duplicate_ids_message_lists_all_dupes(self):
        """The ValueError message lists every duplicated id, not just one."""
        gates = [
            GateConfig(**_minimal_gate_kwargs(id="dup_a")),
            GateConfig(**_minimal_gate_kwargs(id="dup_a")),
            GateConfig(**_minimal_gate_kwargs(id="dup_b")),
            GateConfig(**_minimal_gate_kwargs(id="dup_b")),
        ]
        with pytest.raises(ValidationError) as exc_info:
            HealthChecksConfig(health_gates=gates)
        msg = str(exc_info.value).lower()
        assert "dup_a" in msg
        assert "dup_b" in msg


# ---------------------------------------------------------------------------
# load_health_gates_config
# ---------------------------------------------------------------------------


class TestLoadHealthGatesConfig:
    def test_missing_explicit_path_raises_file_not_found(self, tmp_path):
        missing = tmp_path / "missing_health_checks.yaml"
        with pytest.raises(FileNotFoundError):
            load_health_gates_config(path=str(missing))

    def test_loads_valid_yaml(self, tmp_path):
        p = tmp_path / "hc.yaml"
        p.write_text(
            textwrap.dedent(
                """
                health_gates:
                  - id: "g1"
                    after_round: 1
                    checks:
                      - name: output_diversity
                        config:
                          min_unique_int8_values: 5
                    on_pass:
                      action: continue
                    on_fail:
                      action: skip_iter
                """
            ).lstrip()
        )
        cfg = load_health_gates_config(path=str(p))
        assert len(cfg.health_gates) == 1
        g = cfg.health_gates[0]
        assert g.id == "g1"
        assert g.after_round == 1
        assert g.checks[0].config["min_unique_int8_values"] == 5
        assert g.on_pass.action is GateAction.CONTINUE
        assert g.on_fail.action is GateAction.SKIP_ITER

    def test_empty_yaml_produces_empty_config(self, tmp_path):
        """Empty file → HealthChecksConfig(health_gates=[])."""
        p = tmp_path / "empty.yaml"
        p.write_text("")
        cfg = load_health_gates_config(path=str(p))
        assert cfg.health_gates == []

    def test_path_override_bypasses_cache(self, tmp_path):
        """Passing ``path=`` should always re-read from disk."""
        p = tmp_path / "hc.yaml"
        p.write_text("health_gates: []\n")
        cfg1 = load_health_gates_config(path=str(p))
        p.write_text(
            textwrap.dedent(
                """
                health_gates:
                  - id: "g1"
                    after_round: 1
                    checks:
                      - name: output_diversity
                    on_pass: {action: continue}
                    on_fail: {action: skip_iter}
                """
            ).lstrip()
        )
        cfg2 = load_health_gates_config(path=str(p))
        assert cfg1.health_gates == []
        assert len(cfg2.health_gates) == 1

    def test_default_path_loads_shipped_config(self):
        """The shipped configs/health_checks.yaml must load cleanly and
        contain the M8 rev-7 gate set: 3 blocking + 3 recording, all
        firing on every round. See M8 execution plan §3.5."""
        cfg = load_health_gates_config()
        ids = [g.id for g in cfg.health_gates]
        assert "output_diversity_blocking" in ids
        assert "output_std_blocking" in ids
        assert "amplitude_collapse_blocking" in ids
        assert "pearson_dispersion_recording" in ids
        assert "spectral_peak_ratio_recording" in ids
        assert "per_file_output_std_recording" in ids
        # All gates fire on every round.
        for g in cfg.health_gates:
            assert g.after_round == "every", f"{g.id} should be after_round=every"
        # Blocking gates route to invalidate_round on failure.
        blocking = {
            "output_diversity_blocking",
            "output_std_blocking",
            "amplitude_collapse_blocking",
        }
        for g in cfg.health_gates:
            if g.id in blocking:
                assert g.on_fail.action.value == "invalidate_round"
            else:
                assert g.on_fail.action.value == "continue"

    def test_shipped_config_all_actions_valid(self):
        """Every on_pass/on_fail action string in the shipped YAML must
        resolve to a real GateAction enum member."""
        cfg = load_health_gates_config()
        for g in cfg.health_gates:
            # Type check: if the string was invalid, ValidationError would
            # have raised during load.
            assert isinstance(g.on_pass.action, GateAction)
            assert isinstance(g.on_fail.action, GateAction)


# Note (commit-6): TestLegacyClasses + TestLegacyLoader used to live here
# (4 tests exercising CheckConfig, HealthCheckConfig, load_health_check_config,
# clear_config_cache). The legacy config classes and their loader were
# removed in commit-6; see docs/design/pluggable_health_checks.md §14.
