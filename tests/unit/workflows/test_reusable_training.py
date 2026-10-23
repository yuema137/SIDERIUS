"""Sparse transport and compatibility witnesses for reusable native training."""

import hashlib
import json

import pytest

from tests.unit.workflows.reusable_fixture import reusable
from workflows.definition import (
    ReusableWorkflowDocument,
    parse_workflow_source,
    render_workflow_source,
)


def training_document(settings=None):
    payload = reusable().model_dump(mode="json")
    payload["definition"]["externals"].append(
        {"id": "training", "contract": "native-training.settings", "kind": "managed_candidate"}
    )
    payload["definition"]["nodes"].append(
        {
            "id": "fit",
            "capability": "tuning",
            "request": {
                "kind": "protocol",
                "protocol": "validated-candidate-to-tuning",
                "arguments": [
                    {"name": "proposal", "source": {"kind": "result", "node": "hypothesis"}},
                    {"name": "validation", "source": {"kind": "result", "node": "check"}},
                    {"name": "settings", "source": {"kind": "external", "binding": "training"}},
                ],
            },
        }
    )
    payload["training_settings"] = {} if settings is None else settings
    return ReusableWorkflowDocument.model_validate_json(json.dumps(payload))


def test_legacy_v2_bytes_frozen_before_training_change():
    """Captured at 8ba14871: adding an absent field must not change canonical identities."""
    document = reusable()
    assert (
        hashlib.sha256(render_workflow_source(document).encode()).hexdigest()
        == "f0717cfc5640874bcefa38e8e88e1e490189a5099aebbb79b3a17bec42cde53e"
    )
    assert (
        hashlib.sha256(document.model_dump_json().encode()).hexdigest()
        == "f346ee7b5df47ca598590d8d5191d9f798f01879d858b35936afbac7a2638c7c"
    )
    assert (
        hashlib.sha256(document.declaration_digest().encode()).hexdigest()
        == "26588b4cd2f1845bbf9b9681b507ab516e2be8d07fdb3f316898dd24c233baf5"
    )


def test_training_sparse_roundtrip_and_alias_resolution():
    """Native expansion or dropped null/list values changes the authored transport."""
    from tests.unit.tools.candidate_prepare.test_reusable_resolution import locations
    from tools.candidate_prepare.resolution import (
        ResolvedExternalLocation,
        resolve_reusable_candidate,
    )

    supplied = {
        "launch": {
            "trial_time_budget_minutes": None,
            "formal_time_budget_minutes": 7.0,
            "sampling_seed": 17,
            "train_base_seed": 23,
        },
        "health_gate_files": [1, 3],
    }
    document = training_document(supplied)
    source = render_workflow_source(document)
    assert parse_workflow_source(source) == document
    assert document.training_settings == supplied
    mapped = locations("/run")
    mapped = mapped.model_copy(
        update={
            "externals": (
                *mapped.externals,
                ResolvedExternalLocation(binding="training", location="/run/training.json"),
            )
        }
    )
    resolved = resolve_reusable_candidate(document, mapped)
    assert resolved.document.definition.nodes[-1].id == "fit"
    assert resolved.document.definition.externals[-1].location == "/run/training.json"
    assert "require_probe_runner" not in source


@pytest.mark.parametrize(
    "settings",
    [
        {"launch": {"require_probe_runner": False}},
        {"launch": {"max_iterations": 2}},
        {"health_checks_config": "secret.yaml"},
    ],
)
def test_source_reaches_native_presence_and_supported_controls(settings):
    """A declaration must reject settings the real native ingress cannot accept."""
    with pytest.raises(ValueError):
        training_document(settings)


@pytest.mark.parametrize(
    "literal",
    [
        '{"launch": {}, "launch": {}}',
        "{**{}}",
        "{1: 2}",
        '{"launch": __import__("os")}',
        '{"launch": [x for x in ()]}',
        '{"launch": {"trial_time_budget_minutes": 1e999}}',
    ],
)
def test_json_grammar_rejects_before_construction(literal, monkeypatch):
    """Whole-tree checking prevents partial construction and duplicate-key erasure."""
    from workflows.definition import source as bridge

    source = render_workflow_source(training_document())
    source = source.replace("training_settings={}", "training_settings=" + literal)
    monkeypatch.setattr(bridge, "_construct", lambda *args: pytest.fail("constructed unsafe tree"))
    with pytest.raises(ValueError):
        parse_workflow_source(source)


def test_source_training_validation_does_not_resolve_runtime_effects(monkeypatch):
    """Schema validation must not read task content, bind verifier factories or probe hardware."""
    from importlib.metadata import EntryPoint
    from pathlib import Path

    import torch

    from core import hardware_context
    from core.runtime_control import verifier_provider
    from workflows import run_config, task_composition

    supplied = {"launch": {"sampling_seed": 19, "runtime_verifier": "selected-user-verifier"}}
    source = render_workflow_source(training_document(supplied))

    def forbidden(*args, **kwargs):
        pytest.fail("source validation executed a runtime effect")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(run_config, "bind_runtime_verifier_launch", forbidden)
    monkeypatch.setattr(task_composition, "compose_run_task_bindings", forbidden)
    monkeypatch.setattr(hardware_context, "get_or_create", forbidden)
    monkeypatch.setattr(hardware_context, "discover", forbidden)
    monkeypatch.setattr(torch.cuda, "is_available", forbidden)
    monkeypatch.setattr(verifier_provider, "entry_points", forbidden)
    monkeypatch.setattr(EntryPoint, "load", forbidden)
    assert parse_workflow_source(source).training_settings == supplied


def test_effective_ingress_inserts_only_output_restriction_and_refuses_conflicts():
    """R1 forbids materializing defaults or erasing explicit null output selection."""
    from workflows.candidate_training_settings import effective_training_settings

    assert json.loads(effective_training_settings({}, None)) == {
        "launch": {"allowed_output_types": None}
    }
    source = {"launch": {"sampling_seed": 0, "formal_time_budget_minutes": None}}
    assert json.loads(effective_training_settings(source, ("classifier",))) == {
        "launch": {
            "sampling_seed": 0,
            "formal_time_budget_minutes": None,
            "allowed_output_types": ["classifier"],
        }
    }
    assert source == {"launch": {"sampling_seed": 0, "formal_time_budget_minutes": None}}
    with pytest.raises(ValueError, match="allowed_output_types"):
        training_document({"launch": {"allowed_output_types": None}})
