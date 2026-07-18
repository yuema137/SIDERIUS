"""Contract tests for the two operator-reviewed V17 advice files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sdsc_submission_scripts.run_one_iteration import build_parser, normalize_args

ROOT = Path(__file__).resolve().parents[3]
ADVICE_PATHS = {
    "loss": ROOT / "advice/workflow/v17_loss_explorer.json",
    "architecture": ROOT / "advice/workflow/v17_arch_explorer.json",
}
REQUIRED_KEYS = {"mindset", "propose", "implement", "tune"}


@pytest.fixture(params=ADVICE_PATHS.items(), ids=ADVICE_PATHS.keys())
def advice(request):
    kind, path = request.param
    data = json.loads(path.read_text(encoding="utf-8"))
    return kind, data


def _render(data: dict[str, list[str]]) -> str:
    """Mirror the runner's list-to-text advice rendering contract."""
    return "\n".join(line for key in REQUIRED_KEYS for line in data[key])


def test_advice_has_supported_shape(advice):
    _, data = advice
    assert REQUIRED_KEYS <= data.keys()
    assert all(isinstance(data[key], list) and data[key] for key in REQUIRED_KEYS)
    assert all(isinstance(line, str) for key in REQUIRED_KEYS for line in data[key])


def test_advice_preserves_all_loss_branches(advice):
    _, data = advice
    rendered = _render(data)
    assert "Branch A" in rendered
    assert "Branch B" in rendered
    assert "Branch C / Option C" in rendered
    assert "custom_loss_spec" in rendered
    assert "built-in" in rendered
    assert "built-in only" not in rendered.lower()


def test_advice_requires_live_branch_b_and_preserves_task_semantics(advice):
    _, data = advice
    rendered = _render(data).lower()
    assert "live inventory" in rendered
    assert "stale" in rendered
    assert "output contract" in rendered
    assert "regression to classification" in rendered
    assert "stateful stop policies are deferred to v18" in rendered


def test_control_variable_intent_is_explicit(advice):
    kind, data = advice
    rendered = _render(data).lower()
    if kind == "loss":
        assert "primary variable: loss" in rendered
        assert "keep architecture" in rendered
    else:
        assert "primary variable: architecture" in rendered
        assert "keep the control loss" in rendered


@pytest.mark.parametrize("path", ADVICE_PATHS.values(), ids=ADVICE_PATHS.keys())
def test_existing_runner_advice_loader_accepts_file(path):
    args = build_parser().parse_args(
        [
            "--workspace",
            "/tmp/v17_advice_loader_test",
            "--run_name",
            "v17_advice_loader_test",
            "--start_iteration",
            "1",
            "--seed_paths",
            "/tmp/seed.json",
            "--advice",
            str(path),
        ]
    )
    normalized = normalize_args(args)
    assert normalized.human_advice_propose
    assert normalized.human_advice_implement
    assert normalized.human_advice_tune
    assert normalized.human_advice_mindset
