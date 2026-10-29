"""Explicit synthetic task and prepared developer seed; no provider defaults."""

import json
from pathlib import Path

import pytest

from core.generated_library import bind_generated_library_to_workspace
from tools.candidate_worker.models import CandidateRunRequest
from tools.workflow_preview import WorkflowPreviewRequest, preview_workflow
from workflows.definition import WorkflowDocument

REPO = Path(__file__).resolve().parents[4]
QUICKSTART = REPO / "configs/task_composition/quickstart.yaml"


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    yield from _prepared(tmp_path, monkeypatch, QUICKSTART)


def _prepared(tmp_path, monkeypatch, manifest: Path):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)  # a test manifest may live here (a mounted read-only root)
    (project / "data").mkdir()
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(workspace / "generated_library"))
    monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(workspace))
    bind_generated_library_to_workspace(str(workspace))
    from agent.schemas.proposal import ProposalInput
    from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
    from ml_models import models_format_sandbox, models_sandbox, plugin_loader
    from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings

    for module, name in (
        (models_format_sandbox, "PLUGIN_CONFIG_REGISTRY"),
        (models_sandbox, "MODEL_REGISTRY"),
        (plugin_loader, "PLUGIN_OUTPUT_TYPE_REGISTRY"),
    ):
        monkeypatch.setattr(module, name, dict(getattr(module, name)))
    from execute_tools.task_registration_scope import run_registration_scope

    with run_registration_scope():
        yield _prepare_request(
            project,
            workspace,
            compose_run_task_bindings,
            build_task_composition_ref,
            ProposalInput,
            ProposerInterpretationEvidence,
            manifest=manifest,
        )


def _prepare_request(
    project,
    workspace,
    compose_run_task_bindings,
    build_task_composition_ref,
    ProposalInput,
    ProposerInterpretationEvidence,
    manifest: Path = QUICKSTART,
):
    composition = compose_run_task_bindings(str(manifest))
    seed = ProposalInput(
        interpretation_evidence=ProposerInterpretationEvidence(),
        cold_start=True,
        task_description=composition.task_description,
        forward_contract=composition.forward_contract,
        proposal_blocks=composition.proposal_blocks,
        task_composition_ref=build_task_composition_ref(composition),
        data_dir=str(project / "data"),
        allowed_output_types=["classifier"],
    ).model_dump(mode="json")
    seed.pop("storage")
    (project / "seed.json").write_text(json.dumps(seed))
    storage = {
        "backend": "local",
        "local": {
            "workspace": str(workspace / "candidate/iteration_001/attempt_001/impl_001"),
            "run_name": "candidate",
        },
    }
    (project / "storage.json").write_text(json.dumps(storage))
    config = {
        "propose": {
            "reasoning": {"provider": "openai", "model_id": "proposal-test", "max_retries": 0}
        },
        "implement": {"provider": "openai", "model_id": "implement-test", "max_retries": 0},
        "validate": {"provider": "openai", "model_id": "validate-test", "max_retries": 0},
    }
    # Native WorkflowLLMConfig alias for the validator is validate_model.
    config["validate_model"] = config.pop("validate")
    (project / "llm.json").write_text(json.dumps(config))
    document = WorkflowDocument.model_validate_json(
        json.dumps(
            {
                "definition": {
                    "task": {
                        "manifest": str(manifest),
                        "data_root": "data",
                        "workspace": str(workspace),
                    },
                    "externals": [
                        {"id": "seed", "contract": "proposal.input", "location": "seed.json"},
                        {"id": "storage", "contract": "storage", "location": "storage.json"},
                    ],
                    "nodes": [
                        {
                            "id": "propose",
                            "capability": "proposal",
                            "request": {"kind": "external", "binding": "seed"},
                        },
                        *[
                            {
                                "id": name,
                                "capability": capability,
                                "request": {
                                    "kind": "protocol",
                                    "protocol": protocol,
                                    "arguments": [
                                        {
                                            "name": "output",
                                            "source": {"kind": "result", "node": source},
                                        },
                                        {
                                            "name": "storage",
                                            "source": {"kind": "external", "binding": "storage"},
                                        },
                                    ],
                                },
                            }
                            for name, capability, source, protocol in (
                                (
                                    "implement",
                                    "implementation",
                                    "propose",
                                    "proposal-to-implementation",
                                ),
                                (
                                    "validate",
                                    "validation",
                                    "implement",
                                    "implementation-to-validation",
                                ),
                            )
                        ],
                    ],
                }
            }
        )
    )
    preview = WorkflowPreviewRequest(
        document=document, project_root=str(project), llm_config_file="llm.json"
    )
    observed = preview_workflow(preview)
    return CandidateRunRequest(
        preview=preview,
        declaration_digest=document.definition.declaration_digest(),
        files=observed.files,
        selected_constructor_routes=observed.selected_constructor_routes,
        storage_policy="managed_fresh",
        run_name="candidate",
        timeout_seconds=60.0,
        network=False,
        devices=(),
        read_only=(str(project), str(REPO)),
        environment_names=("OPENAI_API_KEY",),
    )


def refresh(request):
    observed = preview_workflow(request.preview)
    return request.model_copy(
        update={
            "files": observed.files,
            "selected_constructor_routes": observed.selected_constructor_routes,
            "declaration_digest": request.preview.document.definition.declaration_digest(),
        }
    )
