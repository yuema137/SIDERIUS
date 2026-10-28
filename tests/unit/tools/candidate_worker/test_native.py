"""Real native node bodies and CPU probes, with only provider construction replaced."""

import importlib
import json
from pathlib import Path
from typing import ClassVar

import pytest

from tools.candidate_worker import launch_candidate
from tools.workspace_sandbox.runner import ExecutionResult

from .conftest import refresh


class Provider:
    calls: ClassVar[list] = []
    reject = False

    def __init__(self, **kwargs):
        self.context = None

    def set_run_context(self, **kwargs):
        self.context = kwargs

    def generate_text(self, system, user, **kwargs):
        self.calls.append((kwargs.get("label"), self.context))
        return "Use a small linear map from four floating features to two class logits."

    def generate(self, system, user, **kwargs):
        label = kwargs.get("label", "")
        self.calls.append((label, self.context))
        if label == "implementor.code":
            return {
                "extra_imports": "",
                "config_fields_code": "    width: int = Field(default=4, ge=1)",
                "config_fields": {"width": 4},
                "init_body": "        self.projection = nn.Linear(4, 2)",
                "forward_body": "        return self.projection(x.float())",
            }
        if "review" in label:
            return {
                "spec_alignment": True,
                "trainability_concerns": [],
                "implementation_issues": ["rejected fixture"] if self.reject else [],
                "passed": not self.reject,
                "notes": "Deterministic CPU test review.",
            }
        return {
            "model_name": "worker_linear",
            "model_description": "A tiny linear classifier mapping four floating point input features to two output logits.",
            "mathematical_definition": "y = x W^T + b with W in R^(2 x 4).",
            "motivation": "Test the declared synthetic interface.",
            "baseline_config": {
                "model_config": {"width": 4},
                "train_config": {"device": "cpu", "batch_size": 2, "epochs": 1},
                "loss_config": {"loss_type": "ce", "reduction": "mean"},
            },
        }


@pytest.fixture
def native_runner(monkeypatch):
    Provider.calls = []
    Provider.reject = False
    for name in ("ml_model_proposal_agent", "ml_model_implementor", "ml_code_validator_agent"):
        module = importlib.import_module(f"nodes.{name}.{name}")
        monkeypatch.setattr(module, "LLMBridge", Provider)

    def run(profile, argv):
        from tools.candidate_worker.child import execute

        execute(Path(argv[-1]))
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)

    monkeypatch.setattr(importlib.import_module("tools.candidate_worker.launch"), "run", run)

    def observed(profile, argv):
        from core.runtime_control.process_group import GroupCleanup, GroupObservation
        from tools.workspace_sandbox.runner import ObservedExecutionResult

        return ObservedExecutionResult(
            execution=run(profile, argv),
            direct_child_reaped=True,
            cleanup=GroupCleanup(required=False, final=GroupObservation(status="absent")),
        )

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_worker.launch"), "run_observed", observed
    )

    def unit_in_process(invocation_path):
        """Graph units execute their file-transported invocation in this process."""
        from tools.candidate_worker.unit_child import run_invocation_file

        run_invocation_file(Path(invocation_path))

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_worker.unit_runner"),
        "spawn_unit",
        unit_in_process,
    )
    return Provider


@pytest.mark.parametrize("reject", [False, True])
def test_native_chain_preserves_outputs_and_accounting(prepared, native_runner, reject):
    """Fails if protocol transport, native probing, output capture or accounting is bypassed."""
    native_runner.reject = reject
    seed_path = Path(prepared.preview.project_root) / "seed.json"
    raw = json.loads(seed_path.read_text())
    debug = (
        Path(prepared.preview.document.definition.task.workspace) / "candidate_run/debug/prompt.md"
    )
    raw["debug_dump_proposing_prompt_path"] = str(debug)
    seed_path.write_text(json.dumps(raw))
    receipt = launch_candidate(refresh(prepared))
    assert json.loads((debug.parent.parent / "proposal_input.json").read_text())[
        "debug_dump_proposing_prompt_path"
    ] == str(debug)
    assert receipt.status == ("rejected" if reject else "accepted"), receipt.error
    assert receipt.validation_passed is not reject
    assert receipt.candidate_id
    records = [json.loads(Path(path).read_text()) for path in receipt.native_output_paths]
    assert [record["candidate_id"] for record in records] == [receipt.candidate_id] * 3
    assert records[-1]["tests_passed"] is True
    assert records[-1]["instantiation_passed"] is True
    assert records[-1]["gradient_check_passed"] is True
    assert "Linear(4, 2)" in Path(records[1]["model_file_path"]).read_text()
    assert all(
        context["run_id"] == receipt.run_id
        and context["iter"] == 1
        and str(context["workspace"]) == receipt.workspace
        for _, context in native_runner.calls
    )
    assert not (Path(receipt.workspace) / "generated_library/_capability_index.json").exists()
    assert not list((Path(receipt.workspace) / "generated_library").glob("models/*.py"))


@pytest.mark.parametrize(
    "change",
    [
        "task",
        "data",
        "storage",
        "debug",
        "missing_evidence",
        "missing_task",
        "constraints",
        "debug_snapshot",
    ],
)
def test_native_input_refuses_before_provider(prepared, native_runner, change):
    """Each case exercises reconciliation absent from native single-field schemas."""
    path = Path(prepared.preview.project_root) / "seed.json"
    raw = json.loads(path.read_text())
    if change == "task":
        raw["task_description"] = "different task"
    elif change == "data":
        raw["data_dir"] = str(path.parent)
    elif change == "storage":
        raw["storage"] = {
            "backend": "local",
            "local": {"workspace": str(path.parent), "run_name": "candidate"},
        }
    elif change == "debug":
        raw["debug_dump_proposing_prompt_path"] = str(path.parent / "escape.md")
    elif change == "debug_snapshot":
        raw["debug_dump_proposing_prompt_path"] = str(
            Path(prepared.preview.document.definition.task.workspace)
            / "candidate_run/input_000.snapshot"
        )
    elif change == "missing_evidence":
        raw.pop("interpretation_evidence")
    elif change == "missing_task":
        raw.pop("proposal_blocks")
    else:
        raw["constraint_context"] = {
            "known_sections": ["objective"],
            "objective": {"loss_type": "smooth_l1"},
        }
    path.write_text(json.dumps(raw))
    receipt = launch_candidate(refresh(prepared))
    assert receipt.status == "failed"
    assert not native_runner.calls


def test_native_record_capture_preserves_bytes_and_refuses_mismatch(prepared):
    """Existing record disagreement must never be hidden by a worker overwrite."""
    from agent.schemas.proposal import ProposalOutput
    from tools.candidate_worker.artifacts import capture_record

    output = ProposalOutput.model_validate({**Provider().generate("", ""), "expert_advice": {}})
    path = Path(prepared.preview.project_root) / "native.json"
    capture_record(path, output)
    original = path.read_bytes()
    capture_record(path, output)
    assert path.read_bytes() == original
    changed = output.model_copy(update={"motivation": "different"})
    with pytest.raises(ValueError, match="disagrees"):
        capture_record(path, changed)
    assert path.read_bytes() == original


def test_child_rechecks_captured_bytes_before_native_calls(prepared, native_runner, monkeypatch):
    """Parent observation alone cannot protect a snapshot changed before child startup."""

    def altered(profile, argv):
        (profile.workspace / "candidate_run/input_001.snapshot").write_text("{}")
        from tools.candidate_worker.child import execute

        execute(Path(argv[-1]))
        raise AssertionError("changed snapshot reached native execution")

    monkeypatch.setattr(importlib.import_module("tools.candidate_worker.launch"), "run", altered)
    receipt = launch_candidate(prepared)
    assert receipt.status == "failed"
    assert "selected input changed" in receipt.error
    assert not native_runner.calls


def test_actual_reuse_output_capture_keeps_missing_description_and_test(prepared, tmp_path):
    """Native Branch B omits persistence; capture must not invent description/tests.

    This tests a returned native branch with an explicitly seeded index fixture.
    Fresh task-declared reuse inventory is a separate unresolved native-owner gap.
    """
    from agent.schemas.hyperparam_tuning import TaskCompositionRef
    from agent.schemas.implementor import ImplementorInput
    from core.capability_registry import CapabilityMetadata, CapabilityRegistry
    from core.local_code import LocalCodeError, bind_code_package
    from ml_models.plugin_binding import bind_run_model_plugins
    from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor
    from tests.helpers.local_code_model import MODEL_TYPE, make_package
    from tools.candidate_worker.artifacts import capture_record, verify_artifacts
    from workflows.attempt_storage import impl_attempt_storage

    package, binding = make_package(tmp_path / "declared")
    registry = CapabilityRegistry(index_path=str(tmp_path / "fixture_index.json"))
    registry.register(
        CapabilityMetadata(
            name=MODEL_TYPE,
            capability_type="model",
            file_path=str(package.root / "model.py"),
            created_at="fixture",
            description="Explicit declared package fixture",
        )
    )
    attempt = impl_attempt_storage(str(tmp_path / "attempt"), "reuse", 1)
    agent = MLModelImplementor(
        bridge_factory=lambda **kwargs: object(), capability_index_path=registry.index_path
    )
    request = ImplementorInput(
        model_name=MODEL_TYPE,
        model_description="Declared reusable model",
        mathematical_definition="y=x*w",
        storage=attempt.storage,
        baseline_config={
            "model_config": {"model_name": MODEL_TYPE},
            "train_config": {},
            "loss_config": {"loss_type": "ce"},
        },
    )
    seed = json.loads((Path(prepared.preview.project_root) / "seed.json").read_text())
    ref = TaskCompositionRef.model_validate(seed["task_composition_ref"])
    path = Path(attempt.impl_dir) / "implementor_reuse.json"
    with bind_code_package(package), bind_run_model_plugins(binding):
        output = agent.run(request)
        assert not path.exists()
        verify_artifacts(output, attempt, (str(package.root),), ref)
        capture_record(path, output)
        assert output.test_file_path == ""
        assert not Path(output.description_file_path).exists()
        escaped = output.model_copy(update={"model_file_path": str(tmp_path / "other.py")})
        with pytest.raises(LocalCodeError, match="captured member identity"):
            verify_artifacts(escaped, attempt, (str(tmp_path),), ref)
    assert json.loads(path.read_text())["test_file_path"] == ""
    assert not Path(output.description_file_path).exists()


@pytest.mark.parametrize(
    "argument,contract,value",
    [
        ("llm_provider", "llm-provider", "gemini"),
        ("llm_model_id", "optional.model-id", "different-model"),
        (
            "constraint_context",
            "optional.constraint-context",
            {"known_sections": ["objective"], "objective": {"loss_type": "ce"}},
        ),
    ],
)
def test_protocol_external_disagreement_precedes_provider(
    prepared, native_runner, argument, contract, value
):
    """Preview validates graph types; execution must still compare selected authorities."""
    from workflows.definition import ArgumentBinding, ExternalBinding, ExternalSource

    project = Path(prepared.preview.project_root)
    (project / "argument.json").write_text(json.dumps(value))
    definition = prepared.preview.document.definition
    validation = definition.nodes[-1]
    protocol = validation.request.model_copy(
        update={
            "arguments": (
                *validation.request.arguments,
                ArgumentBinding(name=argument, source=ExternalSource(binding="argument")),
            )
        }
    )
    definition = definition.model_copy(
        update={
            "externals": (
                *definition.externals,
                ExternalBinding(id="argument", contract=contract, location="argument.json"),
            ),
            "nodes": (*definition.nodes[:-1], validation.model_copy(update={"request": protocol})),
        }
    )
    updated = prepared.model_copy(
        update={
            "preview": prepared.preview.model_copy(
                update={
                    "document": prepared.preview.document.model_copy(
                        update={"definition": definition}
                    )
                }
            )
        }
    )
    receipt = launch_candidate(refresh(updated))
    assert receipt.status == "failed"
    assert f"protocol {argument} disagrees" in receipt.error
    assert not native_runner.calls


def test_explicit_protocol_storage_escape_precedes_provider(prepared, native_runner):
    """Matching proposal storage cannot excuse a conflicting downstream storage external."""
    path = Path(prepared.preview.project_root) / "storage.json"
    raw = json.loads(path.read_text())
    raw["local"]["workspace"] = str(path.parent)
    path.write_text(json.dumps(raw))
    receipt = launch_candidate(refresh(prepared))
    assert receipt.status == "failed"
    assert "storage disagrees" in receipt.error
    assert not native_runner.calls


@pytest.mark.parametrize("claim", ["time_null", "vram_null", "overrides", "timing", "epochs"])
def test_unowned_or_conflicting_constraint_claim_refused(prepared, native_runner, claim):
    """Claimed known nulls and unavailable controls must fail before provider work."""
    path = Path(prepared.preview.project_root) / "seed.json"
    raw = json.loads(path.read_text())
    context = {"known_sections": ["execution"], "execution": {}}
    if claim == "time_null":
        raw["trial_time_budget_minutes"] = 5
    elif claim == "vram_null":
        raw["vram_budget_gb"] = 8
    elif claim == "overrides":
        context = {"overrides": {"max_epochs": 100}}
    elif claim == "timing":
        context = {
            "timing": {
                "plan_overrides": {},
                "task_rules": None,
                "workflow_rules": None,
                "roles": [],
                "formal_training_scope_source": "operator",
                "formal_eval_portion": 1.0,
                "trial_allowed": True,
                "forced_formal": False,
                "inheritance_strategy": "none",
                "inheritance_values": {},
                "inheritance_unless_authored": [],
                "inheritance_winner": None,
                "inheritance_recovery": None,
                "partial_scope_strategy_overrides": {},
                "validation_max_portion": None,
                "validation_max_train_samples": None,
                "validation_max_samples": None,
                "training_validation_portion": None,
                "training_budget_reserve_fraction": None,
            }
        }
    else:
        context["execution"] = {"max_epochs": 100}
    raw["constraint_context"] = context
    path.write_text(json.dumps(raw))
    receipt = launch_candidate(refresh(prepared))
    assert receipt.status == "failed"
    expected = (
        "disagrees" if claim in {"time_null", "vram_null"} else "no candidate worker authority"
    )
    assert expected in receipt.error
    assert not native_runner.calls


@pytest.mark.parametrize("reject", [False, True])
def test_fanout_runs_native_branches_with_separate_same_name_artifacts(
    prepared, native_runner, monkeypatch, reject
):
    from tests.helpers.candidate_fanout import fanout_request
    from tools.candidate_worker.graph_evidence import verify_graph_trace
    from tools.candidate_worker.models import CandidateRunReceipt

    original = native_runner.generate
    implementations = []

    def generate(self, system, user, **kwargs):
        result = original(self, system, user, **kwargs)
        if kwargs.get("label") == "implementor.code":
            implementations.append(result)
            result["forward_body"] += f"  # branch {len(implementations)}"
        return result

    monkeypatch.setattr(native_runner, "generate", generate)
    native_runner.reject = reject
    request = fanout_request(prepared)
    receipt = launch_candidate(request)
    assert receipt.status == ("rejected" if reject else "accepted"), receipt.error
    assert receipt.graph_trace is not None
    assert len(receipt.graph_trace.nodes) == 5
    records = [json.loads(Path(item.record_path).read_text()) for item in receipt.graph_trace.nodes]
    assert records[1]["model_type"] == records[3]["model_type"] == "worker_linear"
    assert records[1]["model_file_path"] != records[3]["model_file_path"]
    assert (
        Path(records[1]["model_file_path"]).read_bytes()
        != Path(records[3]["model_file_path"]).read_bytes()
    )
    assert records[2]["tests_passed"] and records[4]["tests_passed"]
    initial = CandidateRunReceipt.model_validate_json(
        (Path(receipt.workspace) / "candidate_run/launch.json").read_bytes()
    )
    verify_graph_trace(request, initial, receipt)
    Path(receipt.graph_trace.nodes[1].record_path).write_text("{}")
    with pytest.raises(ValueError, match="record mismatch"):
        verify_graph_trace(request, initial, receipt)


def test_fanout_validation_refuses_same_identity_sibling_artifact(
    prepared, native_runner, monkeypatch
):
    from tests.helpers.candidate_fanout import fanout_request
    from tools.candidate_worker import phases

    original = phases.run_implementation
    outputs = []

    def swapped(*args, **kwargs):
        output, path = original(*args, **kwargs)
        outputs.append(output)
        return outputs[0], path

    monkeypatch.setattr(phases, "run_implementation", swapped)
    receipt = launch_candidate(fanout_request(prepared))
    assert receipt.status == "failed"
    assert receipt.graph_trace.nodes[2].state == "succeeded"
    assert receipt.graph_trace.nodes[4].state == "failed"


def test_join_protocol_optional_arguments_preserve_existing_defaults(prepared, native_runner):
    from agent.schemas.implementor import ImplementorOutput
    from agent.schemas.proposal import ProposalOutput
    from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from tests.helpers.candidate_fanout import fanout_request
    from workflows.candidate_validation_join import proposed_implementation_to_validation

    receipt = launch_candidate(fanout_request(prepared, 1))
    assert receipt.status == "accepted"
    proposal = ProposalOutput.model_validate_json(Path(receipt.native_output_paths[0]).read_bytes())
    implemented = ImplementorOutput.model_validate_json(
        Path(receipt.native_output_paths[1]).read_bytes()
    )
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=receipt.graph_trace.nodes[1].storage, run_name=receipt.run_name
        ),
    )
    mapped = proposed_implementation_to_validation(proposal, implemented, storage)
    baseline = local_all_fields(implemented, storage)
    assert mapped == baseline
    assert mapped.model_io_contract == implemented.model_io_contract
    assert mapped.segmentation_applicability == implemented.segmentation_applicability
    with pytest.raises(ValueError, match="identity"):
        proposed_implementation_to_validation(
            proposal, implemented.model_copy(update={"candidate_id": None}), storage
        )
