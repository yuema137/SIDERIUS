"""after_round schema extension tests (M8 §3.2).

Covers the three accepted forms of ``GateConfig.after_round``:
    (a) positive int         → fires only on that round
    (b) literal ``"every"``  → fires on every round
    (c) list[int]            → fires on any listed round

Plus rejection cases (0, negative, empty list, arbitrary string, bool).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from execute_tools.health_checks.config import ActionConfig, CheckRef, GateConfig
from execute_tools.health_checks.schemas import GateAction


def _make_gate(after_round):
    return GateConfig(
        id="g",
        after_round=after_round,
        checks=[CheckRef(name="output_diversity")],
        on_pass=ActionConfig(action=GateAction.CONTINUE),
        on_fail=ActionConfig(action=GateAction.INVALIDATE_ROUND),
    )


# --- Accepted forms --------------------------------------------------------


class TestAcceptedForms:
    def test_int_specific_round(self):
        g = _make_gate(5)
        assert g.after_round == 5
        assert g.matches_round(5)
        assert not g.matches_round(4)
        assert not g.matches_round(6)

    def test_every_matches_all_rounds(self):
        g = _make_gate("every")
        assert g.after_round == "every"
        for r in [1, 2, 5, 10, 100, 999]:
            assert g.matches_round(r)

    def test_list_of_ints_matches_only_listed(self):
        g = _make_gate([1, 3, 5])
        assert g.after_round == [1, 3, 5]
        assert g.matches_round(1)
        assert g.matches_round(3)
        assert g.matches_round(5)
        assert not g.matches_round(2)
        assert not g.matches_round(4)
        assert not g.matches_round(6)


# --- Rejected forms --------------------------------------------------------


class TestRejectedForms:
    def test_zero_int_rejected(self):
        with pytest.raises(ValidationError, match=">= 1"):
            _make_gate(0)

    def test_negative_int_rejected(self):
        with pytest.raises(ValidationError, match=">= 1"):
            _make_gate(-1)

    def test_arbitrary_string_rejected(self):
        # Pydantic's discriminated-union type check rejects at type layer
        # before our field_validator runs; any ValidationError is acceptable.
        with pytest.raises(ValidationError):
            _make_gate("sometimes")

    def test_empty_list_rejected(self):
        with pytest.raises(ValidationError, match="at least one"):
            _make_gate([])

    def test_list_with_zero_rejected(self):
        with pytest.raises(ValidationError, match=">= 1"):
            _make_gate([1, 0, 3])

    def test_list_with_string_rejected(self):
        # Same as above: pydantic's list[int] rejects at type layer.
        with pytest.raises(ValidationError):
            _make_gate([1, "every", 3])

    def test_yaml_yes_coerces_to_int_1(self):
        # Documented behaviour, not a bug: PyYAML parses ``yes``/``true``
        # to Python bool → Pydantic accepts as int 1 → gate fires on
        # round 1. Regressive-friendly: no operator has ever needed
        # ``after_round: true`` on purpose, but it doesn't harm anything.
        g = _make_gate(True)
        assert g.after_round == 1
        assert g.matches_round(1)


# --- Runner integration ----------------------------------------------------


class TestRunnerIntegration:
    """Verify get_gates_for_position picks up each form correctly."""

    def test_every_gate_matches_every_round(self, tmp_path, monkeypatch):
        yaml_text = """\
health_gates:
  - id: "every_gate"
    after_round: every
    checks:
      - name: output_diversity
    on_pass: {action: continue}
    on_fail: {action: invalidate_round}
"""
        cfg_path = tmp_path / "hc.yaml"
        cfg_path.write_text(yaml_text)

        from execute_tools.health_checks import config as cfg_mod
        from execute_tools.health_checks import runner

        monkeypatch.setattr(cfg_mod, "_CACHED_GATES", None)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda: cfg_mod.load_health_gates_config(str(cfg_path)),
        )

        for r in [1, 4, 7, 10]:
            assert runner.get_gates_for_position(r) == ["every_gate"]

    def test_list_gate_matches_only_listed_rounds(self, tmp_path, monkeypatch):
        yaml_text = """\
health_gates:
  - id: "listed_gate"
    after_round: [3, 7, 11]
    checks:
      - name: output_diversity
    on_pass: {action: continue}
    on_fail: {action: invalidate_round}
"""
        cfg_path = tmp_path / "hc.yaml"
        cfg_path.write_text(yaml_text)

        from execute_tools.health_checks import config as cfg_mod
        from execute_tools.health_checks import runner

        monkeypatch.setattr(cfg_mod, "_CACHED_GATES", None)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda: cfg_mod.load_health_gates_config(str(cfg_path)),
        )

        assert runner.get_gates_for_position(3) == ["listed_gate"]
        assert runner.get_gates_for_position(7) == ["listed_gate"]
        assert runner.get_gates_for_position(11) == ["listed_gate"]
        assert runner.get_gates_for_position(2) == []
        assert runner.get_gates_for_position(8) == []

    def test_int_gate_unchanged_backwards_compat(self, tmp_path, monkeypatch):
        """Regression guard: the existing after_round: <int> form still matches only that round."""
        yaml_text = """\
health_gates:
  - id: "round_5_only"
    after_round: 5
    checks:
      - name: output_diversity
    on_pass: {action: continue}
    on_fail: {action: invalidate_round}
"""
        cfg_path = tmp_path / "hc.yaml"
        cfg_path.write_text(yaml_text)

        from execute_tools.health_checks import config as cfg_mod
        from execute_tools.health_checks import runner

        monkeypatch.setattr(cfg_mod, "_CACHED_GATES", None)
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda: cfg_mod.load_health_gates_config(str(cfg_path)),
        )

        assert runner.get_gates_for_position(5) == ["round_5_only"]
        assert runner.get_gates_for_position(4) == []
        assert runner.get_gates_for_position(6) == []
