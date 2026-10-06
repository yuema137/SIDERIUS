"""Task-neutral reachability tests for tuner prompt rendering authorities."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent.prompt_templates.tuner.rendering import (
    EFFICIENCY_BAND_FRACTION,
    EFFICIENCY_BAND_PCT,
    build_tuner_task_render,
    render_builtin_model_roster,
    render_focal_defaults,
    render_full_scope_segments,
    render_gate_name_tokens,
    render_output_contract_shape,
)
from agent.prompts import PLANNER_PROMPT, REFLECTOR_PROMPT, _truncate_memory_history
from agent.schemas.model_io_contract import ModelIOContract
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.helpers.tuner_prompt_fixtures import planner_kwargs

REPO_ROOT = Path(__file__).resolve().parents[4]


class _Dataset:
    def __init__(self, num_files: int, segments_per_file: int):
        self.num_files = num_files
        self.segments_per_file = segments_per_file


class _Check:
    def __init__(self, name: str):
        self.name = name


class _Gate:
    def __init__(self, checks: list[str]):
        self.checks = [_Check(name) for name in checks]


class _HealthConfig:
    def __init__(self, checks: list[str]):
        self.health_gates = [_Gate(checks)]


def _contract():
    tensor = {
        "axes": [
            {"dimension": {"symbolic": "B"}, "role": "batch"},
            {"dimension": {"symbolic": "T"}, "role": "temporal"},
        ],
        "dtype": {"admissible": ["float32"]},
    }
    return ModelIOContract.model_validate({"input": tensor, "output": tensor})


def _task_render():
    return build_tuner_task_render(
        dataset=_Dataset(num_files=3, segments_per_file=50),
        model_io_contract=_contract(),
        health_config=_HealthConfig(["range_check", "finite_check"]),
        efficiency_band_fraction=EFFICIENCY_BAND_FRACTION,
        registry={},
        composed=True,
    )


class TestRenderedAuthorities:
    def test_the_efficiency_prompt_and_policy_share_one_constant(self):
        assert EFFICIENCY_BAND_PCT == f"{EFFICIENCY_BAND_FRACTION * 100:g}" == "5"
        assert "{EFFICIENCY_BAND_PCT}" in REFLECTOR_PROMPT
        assert "within 5% of the best score" not in REFLECTOR_PROMPT

    def test_the_task_render_reads_each_supplied_authority(self):
        render = _task_render()
        assert render.full_scope_segments == 150
        assert render.output_contract_shape == "[B, T]"
        assert render.gate_check_names == ("range_check", "finite_check")
        assert render.builtin_model_roster == ""

    def test_the_bridge_uses_the_rendered_task_facts(self):
        bridge = BoundaryRecorderBridge()
        bridge.plan(**{**planner_kwargs(), "task_render": _task_render()})
        _method, _label, system, _user = bridge.captures[0]
        # Native guidance must not turn full-scope geometry into a baseline
        # training prescription. The loss offer still reads the task contract.
        assert "trains on 150 segments" not in system
        assert "Compatible builtin loss types: **smooth_l1**" in system
        assert "alpha=0.5" not in system

    def test_a_missing_model_io_contract_stays_absent(self):
        assert render_output_contract_shape(None) is None
        render = build_tuner_task_render(
            dataset=_Dataset(4, 10),
            model_io_contract=None,
            health_config=_HealthConfig([]),
            efficiency_band_fraction=EFFICIENCY_BAND_FRACTION,
            registry={},
            composed=False,
        )
        assert render.output_contract_shape is None

    def test_plan_without_a_task_render_refuses_before_generation(self):
        bridge = BoundaryRecorderBridge()
        kwargs = {key: value for key, value in planner_kwargs().items() if key != "task_render"}
        with pytest.raises(ValueError, match="task_render"):
            bridge.plan(**kwargs)
        assert bridge.captures == []

    def test_templates_keep_authority_owned_values_as_tokens(self):
        for token in (
            "{TASK_DESCRIPTION}",
            "{LOSS_INVENTORY_RULE}",
        ):
            assert token in PLANNER_PROMPT


def test_renderers_read_their_declared_authority(monkeypatch):
    from ml_models import models_sandbox

    monkeypatch.setattr(models_sandbox, "BUILTIN_OUTPUT_TYPES", {"alpha": "regression"})
    assert render_full_scope_segments(_Dataset(7, 11)) == 77
    assert render_builtin_model_roster({"alpha": object(), "external": object()}) == "alpha"
    assert render_gate_name_tokens(_HealthConfig(["a", "b"])) == {"a": "a", "b": "b"}


def test_the_focal_defaults_follow_loss_config(monkeypatch):
    from ml_models.models_format_sandbox import LossConfig

    monkeypatch.setattr(LossConfig.model_fields["alpha"], "default", 0.25)
    monkeypatch.setattr(LossConfig.model_fields["gamma"], "default", 3.5)
    assert render_focal_defaults() == ("0.25", "3.5")


_HISTORY = [
    {
        "exp_id": f"fixture_{index:03d}",
        "status": "success",
        "model_type": "fixture_model",
        "denoising_score": index / 10,
        "is_trial": index < 3,
        "failure_reason": None,
        "params": {"width": index * 8},
        "memory": {
            "hypothesis": f"Hypothesis {index}.",
            "conclusion": f"Conclusion {index}.",
            "round_index": index,
            "memory_update": f"Update {index}.",
        },
    }
    for index in range(1, 5)
]

_RENDER_SNIPPET = """
import json, sys
sys.path.insert(0, sys.argv[1])
from agent.prompts import _truncate_memory_history
history = json.loads(sys.argv[2])
print(json.dumps(_truncate_memory_history(history), indent=2))
"""


def _render_in_subprocess(seed: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", _RENDER_SNIPPET, str(REPO_ROOT), json.dumps(_HISTORY)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
        cwd=REPO_ROOT,
        check=True,
    )
    return result.stdout


class TestCondensedHistoryStability:
    def test_four_records_reach_the_condensed_branch(self):
        condensed = _truncate_memory_history(_HISTORY)
        assert "params" not in condensed[0]
        assert "params" in condensed[-1]

    def test_render_is_byte_identical_across_hash_seeds(self):
        assert len({_render_in_subprocess(seed) for seed in ("0", "1", "12345")}) == 1

    def test_condensed_entry_keeps_the_records_key_order(self):
        condensed = _truncate_memory_history(_HISTORY)[0]
        assert list(condensed) == [
            "exp_id",
            "status",
            "model_type",
            "denoising_score",
            "is_trial",
            "failure_reason",
            "memory",
        ]
        assert list(condensed["memory"]) == ["hypothesis", "conclusion", "round_index"]
