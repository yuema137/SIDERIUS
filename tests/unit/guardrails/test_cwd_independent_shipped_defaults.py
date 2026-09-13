"""Framework defaults and explicit task declarations are cwd-independent."""

from pathlib import Path

from agent.prompt_templates.implementor.task_blocks import load_implementor_task_blocks
from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks
from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks
from execute_tools.health_checks.config import _DEFAULT_CONFIG_PATH, load_health_gates_config


def test_framework_health_policy_is_anchored_to_its_package(tmp_path, monkeypatch) -> None:
    expected = (
        Path(__file__).resolve().parents[3]
        / "src/execute_tools/health_checks/resources/health_checks.yaml"
    )
    monkeypatch.chdir(tmp_path)
    assert Path(_DEFAULT_CONFIG_PATH) == expected
    assert load_health_gates_config().health_gates == []


def test_omitted_task_guidance_is_empty_from_any_working_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_proposal_task_blocks().model_dump(exclude_none=True) == {}
    assert load_implementor_task_blocks().model_dump(exclude_none=True) == {}
    assert load_interpretation_task_blocks().model_dump(exclude_none=True) == {}


def test_explicit_task_guidance_uses_the_supplied_absolute_path(tmp_path, monkeypatch) -> None:
    declaration = tmp_path / "declarations" / "proposal.yaml"
    declaration.parent.mkdir()
    declaration.write_text("output_contract_guidance: Keep the declared semantics.\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert load_proposal_task_blocks(str(declaration)).output_contract_guidance.startswith("Keep")
