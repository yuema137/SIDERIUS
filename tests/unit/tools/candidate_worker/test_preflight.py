"""Credential policy and native reachability own distinct preclaim failure classes."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from tools.candidate_worker import launch_candidate
from tools.candidate_worker.preflight import credential_requirements, require_credentials


def test_route_policy_deduplicates_stages_excludes_inactive_and_marks_unknown(prepared):
    """Fails if a provider map copy drifts, inactive routes add keys, or unknown looks ready."""
    base = prepared.selected_constructor_routes[0]
    gemini = base.model_copy(
        update={"transport": base.transport.model_copy(update={"provider": "gemini"})}
    )
    deepseek = base.model_copy(
        update={"transport": base.transport.model_copy(update={"provider": "deepseek"})}
    )
    routes = (
        base,
        base.model_copy(update={"name": "propose.comparison"}),
        gemini,
        deepseek.model_copy(update={"applicability": "disabled"}),
        deepseek.model_copy(update={"applicability": "pseudo"}),
    )
    result = credential_requirements(routes, ("GEMINI_API_KEY",))
    assert result.required_names == ("GEMINI_API_KEY", "OPENAI_API_KEY")
    assert result.omitted_names == ("OPENAI_API_KEY",)
    assert result.unresolved_routes == ()
    for transport in (None, base.transport.model_copy(update={"provider": "custom"})):
        unknown = base.model_copy(update={"name": "unresolved", "transport": transport})
        assert credential_requirements((unknown,), ()).unresolved_routes == ("unresolved",)
        with pytest.raises(ValueError, match="unresolved"):
            require_credentials((unknown,), (), {})


@pytest.mark.parametrize("case", ["omitted", "missing", "empty", "extra"])
def test_native_bindings_refused_before_workspace_or_dispatch(prepared, monkeypatch, case):
    """Removing native credential admission would reach run and create the workspace."""
    run = Mock()
    monkeypatch.setattr("tools.candidate_worker.launch.run", run)
    if case == "omitted":
        prepared = prepared.model_copy(update={"environment_names": ()})
    elif case == "missing":
        monkeypatch.delenv("OPENAI_API_KEY")
    elif case == "empty":
        monkeypatch.setenv("OPENAI_API_KEY", "")
    elif case == "extra":
        prepared = prepared.model_copy(
            update={"environment_names": ("OPENAI_API_KEY", "EXTRA_RUNTIME")}
        )
        monkeypatch.delenv("EXTRA_RUNTIME", raising=False)
    with pytest.raises(ValueError, match=r"OPENAI_API_KEY|EXTRA_RUNTIME"):
        launch_candidate(prepared)
    assert not Path(prepared.preview.document.definition.task.workspace).exists()
    run.assert_not_called()
