"""Provider reachability, isolation, drift detection, and text-only results."""

import pytest
from pydantic import BaseModel, ValidationError

from agent.prompt_rendering import (
    PromptRenderingProfile,
    bind_prompt_profile,
    prompt_boundary,
)
from agent.prompt_templates.native_training import render_native_training_appendix


class Context(BaseModel):
    values: list[str]


@prompt_boundary("synthetic.message")
def _message(context: Context, suffix: str = "!") -> str:
    return ",".join(context.values) + suffix


def _profile(tmp_path, renderers=None, native=()):
    source = tmp_path / "provider.txt"
    source.write_text("first source")
    return PromptRenderingProfile(
        "test-v1", "1", renderers or {}, frozenset(native), {"provider": source}
    )


def test_copied_typed_inputs_defaults_and_nested_scope_restore(tmp_path):
    """A provider must receive defaults and must not mutate caller-owned evidence."""

    def render(context, suffix):
        context.values.append("changed")
        return suffix + context.values[-1]

    inp = Context(values=["original"])
    profile = _profile(tmp_path, {"synthetic.message": render})
    with bind_prompt_profile(profile):
        assert _message(inp) == "!changed"
        with bind_prompt_profile(None):
            assert _message(inp) == "original!"
        assert _message(inp) == "!changed"
    assert inp.values == ["original"]
    assert _message(inp) == "original!"


def test_explicit_native_and_unknown_boundary(tmp_path):
    profile = _profile(tmp_path, native={"synthetic.message"})
    with bind_prompt_profile(profile):
        assert _message(Context(values=["native"])) == "native!"
        with pytest.raises(ValueError, match="does not declare"):
            render_native_training_appendix()


def test_drift_rejected_before_rendering_and_scope_unwinds(tmp_path):
    profile = _profile(tmp_path, {"synthetic.message": lambda **_: "override"})
    identity = profile.identity()
    with bind_prompt_profile(profile, expected=identity):
        (tmp_path / "provider.txt").write_text("changed source")
        with pytest.raises(ValueError, match="source changed"):
            _message(Context(values=[]))
    with pytest.raises(ValueError, match="changed after composition"):
        with bind_prompt_profile(profile, expected=identity):
            pytest.fail("must reject before binding")
    assert _message(Context(values=[])) == "!"


def test_provider_result_cannot_bypass_text_boundary(tmp_path):
    profile = _profile(tmp_path, {"synthetic.message": lambda **_: {"execute": True}})
    with bind_prompt_profile(profile), pytest.raises(ValidationError):
        _message(Context(values=[]))


def test_implementor_consumes_scoped_appendix_provider(tmp_path):
    """Fails if the real node's system builders retain an inlined appendix."""
    from agent.schemas.implementor import ImplementorInput
    from nodes.ml_model_implementor.ml_model_implementor import (
        _build_code_system_prompt,
        _build_reasoning_system_prompt,
    )

    inp = ImplementorInput(
        model_name="example",
        model_description="Example",
        mathematical_definition="y=x",
        baseline_config={},
    )
    profile = _profile(tmp_path, {"native_training.appendix": lambda: "\nCUSTOM APPENDIX"})
    with bind_prompt_profile(profile):
        for render in (_build_reasoning_system_prompt, _build_code_system_prompt):
            assert render(inp).endswith("\nCUSTOM APPENDIX")
            assert "## Native training execution boundary" not in render(inp)
