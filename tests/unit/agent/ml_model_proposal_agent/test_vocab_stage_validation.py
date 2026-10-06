"""Owner-stage correction and frozen successful-path prompt parity for #147."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from .test_causal_stage_validation import _agent, _pipeline_input
from .test_pipeline_runner import (
    FAKE_COMPARISON_OUTPUT,
    FAKE_PROPOSING_OUTPUT,
    FAKE_REASONING_OUTPUT,
)

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


def trace(tmp_path, variant):
    comparison = deepcopy(FAKE_COMPARISON_OUTPUT)
    reasoning = deepcopy(FAKE_REASONING_OUTPUT)
    inp = _pipeline_input(tmp_path)
    if variant == "omitted":
        comparison.pop("proposed_vocab_candidates")
        comparison.pop("proposed_vocab_links")
    elif variant == "vocabulary":
        comparison["proposed_vocab_links"] = [
            {
                "feature": "conv",
                "capability": "context",
                "evidence": "observed",
                "status": "uncertain",
            }
        ]
        comparison["proposed_vocab_candidates"] = [
            {"name": "conv", "kind": "feature", "description": "local mixing"}
        ]
        reasoning["proposed_vocab_candidates"] = [
            {"name": "finding", "kind": "discovery", "description": "observed gain"},
            {"name": "context", "kind": "capability", "description": "long context"},
        ]
    elif variant == "ignored":
        comparison["proposed_vocab_candidates"] = [None, "ignored", {"kind": "other", "value": [1]}]
    elif variant == "no-causal":
        inp.reasoning_pipeline.stages[1].enabled = False
    elif variant == "no-comparison":
        inp.reasoning_pipeline.stages[0].enabled = False
    bridge = MagicMock()
    responses = []
    if variant != "no-comparison":
        responses.append(comparison)
    if variant != "no-causal":
        responses.append(reasoning)
    responses.append(deepcopy(FAKE_PROPOSING_OUTPUT))
    bridge.generate.side_effect = responses
    output = _agent(bridge).run(inp).model_dump(mode="json")
    output.pop("candidate_id", None)  # Random runtime identity, not scientific output.
    calls = [
        {"system": call.args[0], "user": call.args[1], "label": call.kwargs["label"]}
        for call in bridge.generate.call_args_list
    ]
    serialized = json.dumps({"calls": calls, "output": output}, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


@pytest.mark.parametrize(
    "variant", ["empty", "omitted", "vocabulary", "ignored", "no-causal", "no-comparison"]
)
def test_successful_trace_matches_pre_147(tmp_path, variant):
    fixture = Path(__file__).with_name("fixtures") / "vocab_stage_pre147.json"
    assert trace(tmp_path, variant) == json.loads(fixture.read_text())["cases"][variant]


def run_responses(tmp_path, responses):
    bridge = MagicMock()
    bridge.generate.side_effect = deepcopy(responses)
    return _agent(bridge), bridge, _pipeline_input(tmp_path)


@pytest.mark.parametrize("owner", ["comparison", "causal_reasoning"])
@pytest.mark.parametrize("defect", ["candidate", "discovery", "container", "kind"])
def test_bad_vocabulary_returns_to_its_owner(tmp_path, owner, defect):
    comparison = deepcopy(FAKE_COMPARISON_OUTPUT)
    reasoning = deepcopy(FAKE_REASONING_OUTPUT)
    bad = deepcopy(comparison if owner == "comparison" else reasoning)
    malformed = {
        "candidate": [{"kind": "feature", "name": "conv", "description": []}],
        "discovery": [{"kind": "discovery", "description": "missing name"}],
        "container": None,
        "kind": [{"kind": []}],
    }
    bad["proposed_vocab_candidates"] = malformed[defect]
    corrected = deepcopy(comparison if owner == "comparison" else reasoning)
    corrected["proposed_vocab_candidates"] = [
        {"kind": "feature", "name": "corrected", "description": "valid"}
    ]
    responses = (
        [bad, corrected, reasoning, FAKE_PROPOSING_OUTPUT]
        if owner == "comparison"
        else [comparison, bad, corrected, FAKE_PROPOSING_OUTPUT]
    )
    agent, bridge, inp = run_responses(tmp_path, responses)
    output = agent.run(inp)
    assert output.proposed_vocab_candidates[0]["name"] == "corrected"
    labels = [call.kwargs["label"] for call in bridge.generate.call_args_list]
    expected = (
        [
            "proposer.comparison",
            "proposer.comparison.correction",
            "proposer.causal_reasoning",
            "proposer.proposing",
        ]
        if owner == "comparison"
        else [
            "proposer.comparison",
            "proposer.causal_reasoning",
            "proposer.causal_reasoning.correction",
            "proposer.proposing",
        ]
    )
    assert labels == expected
    correction = bridge.generate.call_args_list[1 if owner == "comparison" else 2]
    assert "proposed_vocab_candidates" in correction.args[1]
    original = bridge.generate.call_args_list[0 if owner == "comparison" else 1]
    assert correction.args[0] == original.args[0]


def test_bad_links_exhaust_at_comparison_before_other_calls(tmp_path):
    bad = deepcopy(FAKE_COMPARISON_OUTPUT)
    bad["proposed_vocab_links"] = [{"feature": "conv", "capability": "context", "evidence": []}]
    agent, bridge, inp = run_responses(tmp_path, [bad] * 3)
    with pytest.raises(RuntimeError, match=r"Comparison stage.*2 correction retries"):
        agent.run(inp)
    assert [call.kwargs["label"] for call in bridge.generate.call_args_list] == [
        "proposer.comparison",
        "proposer.comparison.correction",
        "proposer.comparison.correction",
    ]


def test_existing_causal_correction_cannot_introduce_invalid_vocabulary(tmp_path):
    from .test_causal_stage_validation import CORRECTED_REASONING, MALFORMED_REASONING

    repaired_citation = deepcopy(CORRECTED_REASONING)
    repaired_citation["proposed_vocab_candidates"] = [
        {"kind": "discovery", "description": "missing name"}
    ]
    agent, bridge, inp = run_responses(
        tmp_path,
        [
            FAKE_COMPARISON_OUTPUT,
            MALFORMED_REASONING,
            repaired_citation,
            CORRECTED_REASONING,
            FAKE_PROPOSING_OUTPUT,
        ],
    )
    output = agent.run(inp)
    assert output.inherited_components[0].source_id == "registry:ce_plus_hf_spectral_loss"
    assert (
        bridge.generate.call_args_list[3].kwargs["label"] == "proposer.causal_reasoning.correction"
    )
    assert "proposed_vocab_candidates" in bridge.generate.call_args_list[3].args[1]
    assert bridge.generate.call_count == 5


def test_causal_corrections_share_one_budget_and_show_latest_bad_response(tmp_path):
    bad = deepcopy(FAKE_REASONING_OUTPUT)
    bad["proposed_vocab_candidates"] = [{"kind": "feature", "description": []}]
    latest = deepcopy(bad)
    latest["proposed_vocab_candidates"][0]["name"] = "latest_bad_response"
    agent, bridge, inp = run_responses(tmp_path, [FAKE_COMPARISON_OUTPUT, bad, latest, latest])
    with pytest.raises(RuntimeError, match=r"Causal-reasoning stage.*2 correction retries"):
        agent.run(inp)
    assert bridge.generate.call_count == 4
    assert "latest_bad_response" in bridge.generate.call_args_list[3].args[1]
    assert all(
        call.kwargs["label"] != "proposer.proposing" for call in bridge.generate.call_args_list
    )
