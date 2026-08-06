"""A composite config value must not crash the planner.

V20 launch attempt 1 (2026-08-06, SHA `d8e21d1a`) died on its first
iteration. A proposal legitimately produced a LIST-valued `train_config`
entry; `build_exploration_checklist` added it to a `set`:

    TypeError: unhashable type: 'list'
      agent/prompts.py:361  train_cfg_tried[key].add(val)

Every subsequent planning attempt hit the same line. Three attempts were
consumed, the round failed, and the iteration recorded `no_records` — an
infrastructure crash spent as scientific search budget, before the
candidate reached implementation, training or HealthGate.

The guard already existed for `model_config` and for neither of the other
two, which is the defect: one of three call sites knew values could be
composite.

These tests drive the real `build_exploration_checklist`, not the
canonicaliser alone — the crash was in the production path, and a helper
test would have passed while the campaign still died.
"""

from __future__ import annotations

import pytest

from agent.prompts import _canonical_config_value, build_exploration_checklist

SCHEMA = {
    "properties": {
        "hidden_channels": {"type": "integer", "default": 32, "description": "width"},
        "dilations": {"type": "array", "default": [1, 2, 4], "description": "dilation schedule"},
    }
}


def _record(model_config=None, loss_config=None, train_config=None):
    return {
        "params": {
            "model_config": model_config or {},
            "loss_config": loss_config or {},
            "train_config": train_config or {},
        }
    }


class TestTheProductionPathSurvivesCompositeValues:
    def test_a_list_valued_train_config_does_not_crash(self):
        # THE regression. Before the fix this raised TypeError and the
        # attempt was consumed.
        out = build_exploration_checklist(
            SCHEMA, [_record(train_config={"lr": 5e-4, "lr_schedule": [1e-3, 5e-4, 1e-4]})]
        )
        assert isinstance(out, str) and out

    def test_a_list_valued_loss_config_does_not_crash(self):
        out = build_exploration_checklist(
            SCHEMA, [_record(loss_config={"loss_type": "focal", "class_weights": [1.0, 2.0]})]
        )
        assert "class_weights" in out

    def test_a_nested_dict_and_list_does_not_crash(self):
        out = build_exploration_checklist(
            SCHEMA,
            [
                _record(
                    model_config={"blocks": [{"width": 32, "dilations": [1, 2]}]},
                    train_config={"optimizer_type": {"name": "adamw", "betas": [0.9, 0.999]}},
                )
            ],
        )
        assert isinstance(out, str) and out

    @pytest.mark.parametrize(
        "value",
        [
            [1, 2, 4],
            {"a": 1},
            [{"a": [1, 2]}],
            [],
            {},
            [[1], [2]],
        ],
    )
    def test_no_json_shaped_value_can_crash_any_of_the_three_sections(self, value):
        out = build_exploration_checklist(
            SCHEMA,
            [
                _record(
                    model_config={"hidden_channels": value},
                    loss_config={"weights": value},
                    train_config={"lr": value},
                )
            ],
        )
        assert isinstance(out, str)

    def test_the_original_value_is_what_gets_rendered(self):
        # The canonical form is bookkeeping. If it leaked into the prompt
        # the planner would read `('seq', (1, 2, 4))` instead of `[1, 2, 4]`.
        out = build_exploration_checklist(
            SCHEMA, [_record(train_config={"lr_schedule": [1, 2, 4]})]
        )
        assert "('seq'" not in out
        if "lr_schedule" in out:
            assert "[1, 2, 4]" in out


class TestDistinctCountingIsStillCorrect:
    """The set existed to count distinct values; that must survive."""

    def test_the_same_list_twice_counts_once(self):
        out = build_exploration_checklist(
            SCHEMA,
            [
                _record(model_config={"dilations": [1, 2, 4]}),
                _record(model_config={"dilations": [1, 2, 4]}),
            ],
        )
        assert "only 1 value tried" in out

    def test_two_different_lists_count_twice(self):
        out = build_exploration_checklist(
            SCHEMA,
            [
                _record(model_config={"dilations": [1, 2, 4]}),
                _record(model_config={"dilations": [1, 2, 8]}),
            ],
        )
        assert "2 values tried" in out

    def test_scalar_behaviour_is_unchanged(self):
        out = build_exploration_checklist(
            SCHEMA,
            [
                _record(model_config={"hidden_channels": 32}),
                _record(model_config={"hidden_channels": 64}),
            ],
        )
        assert "2 values tried" in out


class TestTheCanonicalForm:
    def test_every_json_shape_is_hashable(self):
        for value in ([1, 2], {"a": 1}, [{"b": [1]}], (1, 2), {1, 2}, "s", 1, 1.5, True, None):
            hash(_canonical_config_value(value))

    def test_dict_key_order_does_not_create_a_false_distinct(self):
        # `str(val)` — the previous model_config-only guard — counted these
        # as two different values.
        assert _canonical_config_value({"a": 1, "b": 2}) == _canonical_config_value(
            {"b": 2, "a": 1}
        )

    def test_a_list_never_collides_with_its_string_form(self):
        # The other `str(val)` failure: `[1, 2]` and "[1, 2]" were one value.
        assert _canonical_config_value([1, 2]) != _canonical_config_value("[1, 2]")

    def test_a_sequence_never_collides_with_a_mapping(self):
        assert _canonical_config_value([("a", 1)]) != _canonical_config_value({"a": 1})

    def test_a_list_and_tuple_of_the_same_values_agree(self):
        # A tuple that survives a JSON round trip comes back a list;
        # counting them separately would double-count one value.
        assert _canonical_config_value([1, 2]) == _canonical_config_value((1, 2))

    def test_different_values_stay_different(self):
        assert _canonical_config_value([1, 2]) != _canonical_config_value([2, 1])
        assert _canonical_config_value({"a": 1}) != _canonical_config_value({"a": 2})

    def test_it_is_deterministic_across_calls(self):
        v = {"b": [3, {"z": 1, "a": 2}], "a": 1}
        assert _canonical_config_value(v) == _canonical_config_value(
            dict(reversed(list(v.items())))
        )
