"""Runtime assets must reach renderers and the packaging directory census."""

from __future__ import annotations

import pytest

from tools.ci.selection import resolve_selection
from tools.ci_selection import manifest as mf
from tools.ci_selection.resolver import REPO_ROOT, select


@pytest.mark.parametrize(
    "relative",
    [
        "proposal/comparison_stage.md",
        "proposal/causal_reasoning_stage.md",
        "proposal/proposing_stage.md",
        "proposal/comparison_stage_explore.md",
        "proposal/comparison_stage_exploit.md",
        "proposal/causal_reasoning_stage_explore.md",
        "proposal/causal_reasoning_stage_exploit.md",
        "proposal/proposing_stage_explore.md",
        "proposal/proposing_stage_exploit.md",
        "literature_review/paper_extract_system.md",
        "literature_review/search_decision_system.md",
        "literature_review/synthesis_system.md",
    ],
)
def test_prompt_assets_include_rendering_and_packaging_consumers(relative: str) -> None:
    """Removing the tree trigger loses the conservative rendering guarantee."""
    changed = "src/agent/prompt_templates/" + relative
    assert (REPO_ROOT / changed).is_file()
    result = select([changed, "README.md"])
    assert result.full_suite, result.describe()
    expanded = resolve_selection(REPO_ROOT, [changed, "README.md"])
    assert expanded.full_suite, expanded.reason
    assert "tests/unit/agent/prompt_templates/test_proposal_prompts.py" in expanded.files
    assert "tests/unit/workflows/test_step10_p1_c2_consumption.py" in expanded.files
    assert "tests/unit/packaging/test_package_resources.py" in expanded.files


@pytest.mark.parametrize(
    "changed",
    [
        "src/agent/prompt_templates/proposal/proposing_stage_exploit.md",
        "src/agent/skills/training_skill/skill_config.json",
        "src/agent/data_analysis/reference_packs/time_series/manifest.json",
        "src/ml_models/wavenet/description.md",
        "src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.md",
        "src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md",
        "src/dashboard/static/app.js",
        "src/tools/ci/weights.json",
        "src/execute_tools/health_checks/resources/health_checks.yaml",
        "src/tools/claude_hooks/templates/before_end_memory.template.md",
        "src/agent/schemas/vocab_seed.json",
    ],
)
def test_packaging_census_selects_its_resource_families(
    changed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broad full-suite triggers must not mask an undeclared packaging reader.

    Disable triggers/hubs to isolate the declaration, including the prompt
    family. Reverting the census entry omits packaging for computed glob roots.
    """
    monkeypatch.setattr(mf, "FULL_SUITE_TRIGGERS", ())
    monkeypatch.setattr(mf, "HUBS", ())
    assert (REPO_ROOT / changed).is_file()
    result = select([changed])
    assert not result.full_suite, result.describe()
    assert "tests/unit/packaging/test_package_resources.py" in result.modules
