"""Task probe requirements reach generation and repair without losing errors."""

from nodes.ml_model_implementor.ml_model_implementor import (
    _build_code_prompt,
    _build_reasoning_prompt,
    _build_repair_prompt,
)
from tests.unit.agent.ml_model_implementor.test_step00_prompt_goldens import fixture_input
from tests.unit.agent.test_task_model_probe import declared_task
from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings


def test_declared_probe_reaches_all_generation_stages(tmp_path):
    declaration = {
        "description": "Synthetic normalized feature rows; no dataset access.",
        "max_input_elements": 100,
    }
    _, context, _ = declared_task(
        tmp_path,
        body="return torch.full(request.input_shape, 0.25, dtype=torch.float32)"
        + f"\n\nQuickstartTaskDataPath.model_validation_contract = {declaration!r}\n",
    )
    composition = compose_run_task_bindings(context.manifest_path)
    inp = fixture_input(
        task_composition_ref=build_task_composition_ref(composition),
        forward_contract=composition.forward_contract,
    )
    prompts = [
        _build_reasoning_prompt(inp),
        _build_code_prompt("Reasoned implementation", inp),
        _build_repair_prompt(
            {"forward_body": "return x"}, "Wrong output shape", inp,
            [(1, "Missing parameter")],
        ),
    ]
    for prompt in prompts:
        assert "Synthetic normalized feature rows; no dataset access." in prompt
        assert "100" in prompt
    assert "Wrong output shape" in prompts[-1]
    assert "Missing parameter" in prompts[-1]


def test_undeclared_probe_preserves_all_user_prompts(tmp_path):
    _, context, _ = declared_task(tmp_path)
    composition = compose_run_task_bindings(context.manifest_path)
    base = fixture_input(forward_contract=composition.forward_contract)
    composed = base.model_copy(update={
        "task_composition_ref": build_task_composition_ref(composition),
    })
    for render in (
        _build_reasoning_prompt,
        lambda inp: _build_code_prompt("reasoning", inp),
        lambda inp: _build_repair_prompt({}, "error", inp, [(1, "previous")]),
    ):
        assert render(base) == render(composed)
