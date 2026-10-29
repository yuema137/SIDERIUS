"""#779: native live calls guard consumed names before their first effects.

Removing an entry guard reaches the sentinel instead of the component error.
Archive round trips and unused-backend cases pin the live/read separation.
"""

from importlib import import_module
from unittest.mock import MagicMock

import pytest

import nodes.ml_code_validator_agent as validator
import nodes.ml_hyperparameter_tune_agent as tuner
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_literature_review import MLLiteratureReviewAgent
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.helpers.probe_seed import PROBE_SEED
from tests.unit.agent.ml_code_validator_agent.test_validator_agent import (
    make_input as validator_input,
)
from tests.unit.agent.ml_literature_review.test_node import _input as literature_input
from tests.unit.agent.ml_model_implementor.test_generated_name_safety import loss_spec, request
from tests.unit.agent.ml_model_proposal_agent.test_proposal_agent import (
    make_input as proposal_input,
)
from tests.unit.agent.result_interpretation_agent.test_analysis_brief_generation import _cold_input


class FirstEffect(Exception):
    """Deliberate stop before provider, probe or persistence work."""


def _entry(kind, tmp_path, monkeypatch):
    first = MagicMock(side_effect=FirstEffect)
    # __new__ deliberately proves run eligibility independently of constructors.
    if kind == "proposal":
        inp = proposal_input(tmp_path)
        agent = MLModelProposalAgent.__new__(MLModelProposalAgent)
        agent._custom_loss_inventory = first
    elif kind == "implementor":
        inp = request(tmp_path, custom_loss_spec=loss_spec("safe_loss"))
        inp.storage = StorageConfig(local=LocalStorageConfig(workspace=str(tmp_path)))
        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent._probe_seed = PROBE_SEED
        agent._generate_loss = first
        agent.bridge = MagicMock()
    elif kind == "validator":
        inp = validator_input(tmp_path)
        agent = validator.MLCodeValidatorAgent.__new__(validator.MLCodeValidatorAgent)
        agent._probe_seed = PROBE_SEED
        monkeypatch.setattr(validator, "_check_plugin", first)
    elif kind == "interpreter":
        inp = _cold_input(tmp_path, requested=True)
        agent = ResultInterpretationAgent.__new__(ResultInterpretationAgent)
        agent._attach_analysis_brief = first
    elif kind == "literature":
        inp = literature_input(tmp_path)
        agent = MLLiteratureReviewAgent(
            bridge_factory=first, root_cache_dir=str(tmp_path / "cache")
        )
    else:
        inp = HyperparamTuningInput(
            model_type="synthetic",
            storage=StorageConfig(local=LocalStorageConfig(workspace=str(tmp_path))),
        )
        agent = tuner.HyperparamTuningAgent.__new__(tuner.HyperparamTuningAgent)
        monkeypatch.setattr(tuner, "validate_watchdog_startup", first)
    return inp, agent, first


KINDS = ["proposal", "implementor", "validator", "interpreter", "literature", "tuner"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("name", ["../escape", "/absolute", "folder\\escape", "run\nname"])
def test_archived_unsafe_name_is_refused_before_first_effect(tmp_path, monkeypatch, kind, name):
    inp, agent, first = _entry(kind, tmp_path, monkeypatch)
    assert inp.storage.local is not None
    if kind == "literature":
        inp.run_name = name
    else:
        inp.storage.local.run_name = name
    restored = type(inp).model_validate_json(inp.model_dump_json())
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match="filesystem component"):
        agent.run(restored)
    first.assert_not_called()
    if kind == "implementor":
        assert agent.bridge.mock_calls == []
    assert sorted(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("name", ["研究-v2.1", "r" * 129])
def test_ordinary_components_reach_existing_behavior_unchanged(tmp_path, monkeypatch, kind, name):
    inp, agent, first = _entry(kind, tmp_path, monkeypatch)
    assert inp.storage.local is not None
    inp.storage.local.run_name = name
    if kind == "literature":
        inp.run_name = name
    with pytest.raises(FirstEffect):
        agent.run(inp)
    first.assert_called_once()
    assert inp.storage.local.run_name == name
    if kind == "literature":
        assert inp.run_name == name


@pytest.mark.parametrize("kind", KINDS)
def test_backend_predicate_matches_actual_writer(tmp_path, monkeypatch, kind):
    inp, agent, first = _entry(kind, tmp_path, monkeypatch)
    inp.storage.backend = "postgres"
    assert inp.storage.local is not None
    inp.storage.local.run_name = "../unused"
    if kind in {"validator", "tuner"}:
        with pytest.raises(ValueError, match="filesystem component"):
            agent.run(inp)
        first.assert_not_called()
    else:
        # Literature consumes its separate top-level name; the other three
        # entries do not select local persistence for the postgres backend.
        with pytest.raises(FirstEffect):
            agent.run(inp)
        first.assert_called_once()


@pytest.mark.parametrize("entry", ["literature", "primary", "brief"])
def test_independent_writers_refuse_before_directory_provider_or_publication(
    tmp_path, monkeypatch, entry
):
    from pathlib import Path

    brief = import_module("nodes.result_interpretation_agent.analysis_brief")
    from tests.unit.agent.ml_literature_review.test_node import _interp

    effect = MagicMock(side_effect=AssertionError("writer effect reached"))
    monkeypatch.setattr(Path, "mkdir", effect)
    monkeypatch.setattr(brief, "publish_bytes_write_once", effect)
    monkeypatch.setattr(brief, "_brief_route", effect)
    if entry == "literature":
        inp = literature_input(tmp_path)
        inp.run_name = "../escape"
        agent = MLLiteratureReviewAgent.__new__(MLLiteratureReviewAgent)
        with pytest.raises(ValueError, match="filesystem component"):
            agent._write_output(inp, MagicMock())
    else:
        inp = _cold_input(tmp_path, requested=True)
        assert inp.storage.local is not None
        inp.storage.local.run_name = "../escape"
        with pytest.raises(ValueError, match="filesystem component"):
            if entry == "primary":
                brief.persist_or_resume_primary_interpretation(inp, _interp())
            else:
                brief.generate_or_resume_analysis_brief(
                    bridge=MagicMock(),
                    inp=inp,
                    interpretation=_interp(),
                    provider="openai",
                    model_id="test",
                )
    effect.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_literature_writer_uses_top_level_name_and_skips_missing_local(tmp_path):
    from agent.schemas.literature_review import LiteratureReviewOutput

    inp = literature_input(tmp_path, run_name="研究-v2.1")
    assert inp.storage.local is not None
    inp.storage.local.run_name = "../unused"
    inp.storage.backend = "postgres"
    agent = MLLiteratureReviewAgent.__new__(MLLiteratureReviewAgent)
    output = LiteratureReviewOutput(
        agent_card=import_module("nodes.ml_literature_review")._AGENT_CARD,
        run_name=inp.run_name,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:00Z",
    )
    agent._write_output(inp, output)
    path = tmp_path / "ml_literature_review_研究-v2.1.json"
    assert path.read_text() == output.model_dump_json(indent=2)
    inp.storage.local = None
    inp.run_name = "../unused"
    agent._write_output(inp, output)
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("entry", ["primary", "brief"])
def test_brief_writers_do_not_restrict_unused_local_name(tmp_path, monkeypatch, entry):
    brief = import_module("nodes.result_interpretation_agent.analysis_brief")
    from tests.unit.agent.ml_literature_review.test_node import _interp

    inp = _cold_input(tmp_path, requested=True)
    inp.storage.backend = "postgres"
    assert inp.storage.local is not None
    inp.storage.local.run_name = "../unused"
    output = _interp()
    if entry == "primary":
        assert brief.persist_or_resume_primary_interpretation(inp, output) is output
    else:
        route = MagicMock(side_effect=FirstEffect)
        monkeypatch.setattr(brief, "_brief_route", route)
        with pytest.raises(FirstEffect):
            brief.generate_or_resume_analysis_brief(
                bridge=MagicMock(),
                inp=inp,
                interpretation=output,
                provider="openai",
                model_id="test",
            )
        route.assert_called_once()
    assert list(tmp_path.iterdir()) == []
