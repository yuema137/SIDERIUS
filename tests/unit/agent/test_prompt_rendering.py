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


def test_loader_refuses_missing_duplicate_and_misnamed_providers(tmp_path, monkeypatch):
    """Entry-point discovery must never choose an arbitrary matching distribution."""
    from types import SimpleNamespace

    from agent import prompt_rendering as module

    profile = _profile(tmp_path)
    entry = SimpleNamespace(name="test-v1", load=lambda: lambda: profile)
    for entries in ([], [entry, entry]):
        monkeypatch.setattr(module, "entry_points", lambda entries=entries, **_: entries)
        with pytest.raises(ValueError, match="Expected one installed"):
            module.resolve_prompt_profile("test-v1")
    wrong = SimpleNamespace(name="requested-v1", load=lambda: lambda: profile)
    monkeypatch.setattr(module, "entry_points", lambda **_: [wrong])
    with pytest.raises(TypeError, match="selected PromptRenderingProfile"):
        module.resolve_prompt_profile("requested-v1")


def test_boundary_declaration_changes_identity(tmp_path):
    """Identical source files must not hide a different native/override selection."""
    profile = _profile(tmp_path, native={"synthetic.message"})
    other = PromptRenderingProfile(
        profile.name,
        profile.version,
        {"synthetic.message": lambda **_: "x"},
        frozenset(),
        profile.sources,
    )
    assert profile.identity().content_sha256 != other.identity().content_sha256


def test_validator_consumes_scoped_appendix_provider(tmp_path):
    """The review node must share the appendix seam without changing its validator."""
    from nodes.ml_code_validator_agent.ml_code_validator_agent import _build_review_system_prompt

    native = _build_review_system_prompt(None)
    profile = _profile(tmp_path, {"native_training.appendix": lambda: "\nCUSTOM APPENDIX"})
    with bind_prompt_profile(profile):
        overridden = _build_review_system_prompt(None)
    assert overridden.endswith("\nCUSTOM APPENDIX")
    assert overridden.removesuffix("\nCUSTOM APPENDIX") == native.removesuffix(
        render_native_training_appendix()
    )


@pytest.mark.parametrize("producer", ["planning.py", "provenance.py"])
def test_tuner_producer_changes_invalidate_rendering_qualification(monkeypatch, producer):
    """Input meaning can change without changing a template; bind both producers."""
    from pathlib import Path

    from agent.prompt_rendering import rendering_assembly_digest

    original = Path.read_bytes
    expected = rendering_assembly_digest()

    def changed(path):
        data = original(path)
        if path.name == producer and path.parent.name == "ml_hyperparameter_tune_agent":
            return data + b"\n# Changed input semantics\n"
        return data

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert rendering_assembly_digest() != expected
