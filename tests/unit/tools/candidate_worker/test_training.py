"""Fresh four-stage production dispatch with real proposal/implementation/validation.

Only provider, measurement/hardware and tuner execution effects are substituted;
request admission, context projection, native staging and tuner protocol stay real.
"""

import importlib
import json
from pathlib import Path

import pytest

from tools.candidate_worker import launch_candidate
from workflows.definition import WorkflowDocument

from .conftest import refresh
from .test_native import Provider
from .test_native import native_runner as native_runner


@pytest.fixture
def training_request(prepared):
    root = Path(prepared.preview.project_root)
    document = prepared.preview.document.model_dump(mode="json")
    definition = document["definition"]
    definition["externals"].append(
        {"id": "settings", "contract": "native-training.settings", "location": "training.json"}
    )
    definition["nodes"].append(
        {
            "id": "tune",
            "capability": "tuning",
            "request": {
                "kind": "protocol",
                "protocol": "validated-candidate-to-tuning",
                "arguments": [
                    {"name": "proposal", "source": {"kind": "result", "node": "propose"}},
                    {"name": "validation", "source": {"kind": "result", "node": "validate"}},
                    {"name": "settings", "source": {"kind": "external", "binding": "settings"}},
                ],
            },
        }
    )
    launch = {
        "healthgate_mode": "observe_only",
        "result_authority": "diagnostic",
        "allowed_output_types": ["classifier"],
        "trial_time_budget_minutes": 7.0,
        "formal_time_budget_minutes": 19.0,
        "max_rounds": 2,
        "trial_max_epochs": 3,
        "formal_max_epochs": 8,
        "trial_portion": 0.2,
        "train_portion": 0.3,
    }
    (root / "training.json").write_text(json.dumps({"launch": launch}))
    seed = json.loads((root / "seed.json").read_text())
    seed.update(
        {
            name: launch[name]
            for name in (
                "trial_time_budget_minutes",
                "formal_time_budget_minutes",
                "trial_portion",
                "train_portion",
            )
        }
    )
    (root / "seed.json").write_text(json.dumps(seed))
    config = json.loads((root / "llm.json").read_text())
    config["tune"] = {
        "provider": "openai",
        "model_id": "tuner-test",
        "planner_strategy": "native-timing-v1",
    }
    (root / "llm.json").write_text(json.dumps(config))
    return refresh(
        prepared.model_copy(
            update={
                "preview": prepared.preview.model_copy(
                    update={"document": WorkflowDocument.model_validate_json(json.dumps(document))}
                )
            }
        )
    )


@pytest.fixture
def training_runner(native_runner, monkeypatch):
    from core.hardware_context import HardwareContext
    from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
    from tests.unit.workflows.test_model_exploration import _make_tuning_output
    from tools.candidate_worker import training, training_admission

    seen = []
    monkeypatch.setattr(
        training_admission, "run_launch_self_test", lambda **kwargs: seen.append(("guard", kwargs))
    )
    monkeypatch.setattr(
        training_admission,
        "resolve_composed_measurement_capability",
        lambda *args, **kwargs: ResolvedMeasurementCapability(
            task_identity="fixture",
            dataset_adapter="fixture",
            data_shape_class="fixture",
            probe_available=False,
            unavailability_reason="offline fixture",
        ),
    )
    # HardwareContext fixture follows the same deterministic CPU owner used by native tests.
    monkeypatch.setattr(
        training_admission,
        "get_hardware_context",
        lambda *args: HardwareContext(
            device_name="cpu",
            total_memory_bytes=0,
            compute_capability=(0, 0),
            multiprocessor_count=0,
            torch_version="fixture",
            hostname="fixture",
            device_available=False,
            discovered_at="2026-01-01T00:00:00Z",
        ),
    )
    real_propose = importlib.import_module("tools.candidate_worker.native").MLModelProposalAgent.run

    def propose(self, value):
        seen.append(("proposal", value))
        return real_propose(self, value)

    monkeypatch.setattr(
        importlib.import_module("tools.candidate_worker.native").MLModelProposalAgent,
        "run",
        propose,
    )

    native = importlib.import_module("tools.candidate_worker.native")
    real_implement = native.MLModelImplementor.run

    def implement(self, value):
        seen.append(("implementation", value))
        return real_implement(self, value)

    monkeypatch.setattr(native.MLModelImplementor, "run", implement)
    real_text = Provider.generate_text

    def text(self, system, user, **kwargs):
        seen.append(("message", (kwargs.get("label"), user)))
        return real_text(self, system, user, **kwargs)

    monkeypatch.setattr(Provider, "generate_text", text)

    class Tuner:
        def set_run_context(self, **kwargs):
            pass

        def run(self, value):
            seen.append(("tuner", value))
            output = _make_tuning_output(
                model_type=value.model_type, run_name=value.storage.local.run_name
            )
            return output.model_copy(
                update={
                    "candidate_id": value.candidate_id,
                    "task_composition_fingerprint": value.task_composition_ref.semantic_fingerprint,
                }
            )

    monkeypatch.setattr(training, "HyperparamTuningAgent", Tuner)
    return seen


def test_four_stage_reaches_native_input_and_verifies_later_reads(
    training_request, training_runner
):
    """Fails on dropped budgets at actual node calls or missing terminal integrity checks."""
    receipt = launch_candidate(training_request)
    assert receipt.status == "completed", receipt.error
    proposed = next(value for name, value in training_runner if name == "proposal")
    tuned = next(value for name, value in training_runner if name == "tuner")
    assert (proposed.trial_time_budget_minutes, proposed.formal_time_budget_minutes) == (7, 19)
    assert (tuned.trial_time_budget_minutes, tuned.formal_time_budget_minutes) == (7, 19)
    assert (tuned.trial_max_epochs, tuned.formal_max_epochs) == (3, 8)
    assert proposed.constraint_context.execution.trial_max_epochs == 3
    implemented = next(value for name, value in training_runner if name == "implementation")
    assert (
        implemented.constraint_context.execution.trial_time_budget_minutes,
        implemented.constraint_context.execution.formal_time_budget_minutes,
    ) == (7, 19)
    messages = "\n".join(value[1] for name, value in training_runner if name == "message")
    assert "trial_time_budget_minutes" in messages and "formal_time_budget_minutes" in messages
    assert (
        training_runner[0][0] == "guard" and training_runner[0][1]["require_probe_runner"] is True
    )
    assert len(receipt.native_output_paths) == 4
    from tools.candidate_worker.training_evidence import verify_training_evidence

    verify_training_evidence(receipt)
    path = Path(receipt.native_output_paths[-1])
    path.write_text(path.read_text().replace('"candidate_id"', '"other_id"'))
    with pytest.raises(ValueError, match="integrity"):
        verify_training_evidence(receipt)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_rounds", -2),
        ("runtime_safety_factor", -1),
        ("vram_preflight_total_timeout_seconds", -2),
        ("validation_max_samples", -2),
        ("trial_time_budget_minutes", 0),
        ("formal_time_budget_minutes", float("nan")),
        ("plan_overrides", {}),
        ("require_probe_runner", False),
    ],
)
def test_bad_launch_refuses_before_provider(training_request, native_runner, field, value):
    """These owner constraints must be reached before even the proposer bridge exists."""
    path = Path(training_request.preview.project_root) / "training.json"
    settings = json.loads(path.read_text())
    settings["launch"][field] = value
    path.write_text(json.dumps(settings))
    receipt = launch_candidate(refresh(training_request))
    assert receipt.status == "failed"
    assert not Provider.calls


@pytest.mark.parametrize(
    "fault",
    ["explicit_none", "hardware", "ordering", "construction", "rejected", "abort", "timeout"],
)
def test_training_failure_boundaries(
    training_request, training_runner, native_runner, monkeypatch, fault
):
    """Conflicts precede bridges; rejection/admission refusal cannot reach tuning; parent timeout wins."""
    from core.hardware_models import HardwareContext
    from tools.candidate_worker import training

    root = Path(training_request.preview.project_root)
    if fault in {"explicit_none", "hardware"}:
        path = root / "seed.json"
        seed = json.loads(path.read_text())
        if fault == "explicit_none":
            seed["trial_time_budget_minutes"] = None
        else:
            seed["hardware_context"] = HardwareContext(
                device_name="stale",
                total_memory_bytes=0,
                compute_capability=(0, 0),
                multiprocessor_count=0,
                torch_version="fixture",
                hostname="old",
                device_available=False,
                discovered_at="2026-01-01T00:00:00Z",
            ).model_dump(mode="json")
        path.write_text(json.dumps(seed))
    if fault == "ordering":
        path = root / "training.json"
        settings = json.loads(path.read_text()) | {
            "order_strategy_override": "sequential",
            "file_order_override": [999],
        }
        path.write_text(json.dumps(settings))
    if fault == "construction":

        def refuse(*args):
            raise ValueError("construction refusal witness")

        monkeypatch.setattr(training, "admit_generated_model_construction", refuse)
    if fault == "rejected":
        native_runner.reject = True
    if fault == "abort":
        real_run = training.HyperparamTuningAgent.run

        def abort(self, value):
            output = real_run(self, value)
            return output.model_copy(
                update={
                    "status": "failed",
                    "termination_reason": "infrastructure_abort",
                    "all_records": [],
                    "completed_rounds": 0,
                    "best_denoising_score": None,
                    "best_formal_denoising_score": None,
                }
            )

        monkeypatch.setattr(training.HyperparamTuningAgent, "run", abort)
    if fault == "timeout":
        from tools.workspace_sandbox.runner import ExecutionResult

        def timeout(profile, argv):
            from tools.candidate_worker.child import execute

            execute(Path(argv[-1]))
            return ExecutionResult(status="timed_out", returncode=-9, elapsed_seconds=1.0)

        monkeypatch.setattr(
            importlib.import_module("tools.candidate_worker.launch"), "run", timeout
        )
    receipt = launch_candidate(refresh(training_request))
    assert receipt.status == {"rejected": "rejected", "timeout": "timed_out"}.get(
        fault, "failed"
    ), receipt.error
    if fault in {"explicit_none", "hardware", "ordering"}:
        assert not Provider.calls
    if fault in {"explicit_none", "hardware", "ordering", "construction", "rejected"}:
        assert not any(name == "tuner" for name, _ in training_runner)
    if fault == "abort":
        assert len(receipt.native_output_paths) == 4
        from tools.candidate_worker.training_evidence import verify_training_evidence

        verify_training_evidence(receipt)


@pytest.mark.parametrize("change", ["settings", "health", "snapshot"])
def test_captured_training_inputs_refuse_before_child_work(
    training_request, native_runner, monkeypatch, change
):
    """Nested operator Health and original/snapshot settings all belong to capture admission."""
    root = Path(training_request.preview.project_root)
    health = root / "operator-health.yaml"
    health.write_text("health_gates: []\n")
    path = root / "training.json"
    settings = json.loads(path.read_text()) | {"health_checks_config": "operator-health.yaml"}
    path.write_text(json.dumps(settings))
    request = refresh(training_request)
    assert next(
        item.path for item in request.files if item.reference == "training.health_checks_config"
    ) == str(health)

    def altered(profile, argv):
        if change == "health":
            health.write_text("changed")
        elif change == "settings":
            path.write_text("{}")
        else:
            index = next(
                i for i, item in enumerate(request.files) if item.reference == "external.settings"
            )
            (profile.workspace / f"candidate_run/input_{index:03}.snapshot").write_text("{}")
        from tools.candidate_worker.child import execute

        execute(Path(argv[-1]))
        raise AssertionError("changed input reached native execution")

    monkeypatch.setattr(importlib.import_module("tools.candidate_worker.launch"), "run", altered)
    receipt = launch_candidate(request)
    assert receipt.status == "failed" and "selected input changed" in receipt.error
    assert not Provider.calls


@pytest.mark.parametrize("tamper", ["missing", "coordinated"])
def test_after_process_operation_read_reaches_terminal_verifier(
    training_request, training_runner, tmp_path, tamper
):
    """The public read path must detect a removed native output without editor state."""
    from uuid import UUID, uuid4

    from tools.candidate_operations import CandidateOperation, OperationStoreConfig, read_operation
    from tools.candidate_operations.models import OperationRecord
    from tools.candidate_operations.process import runtime_identity
    from tools.candidate_operations.store import claim, digest, locked_store, now

    receipt = launch_candidate(training_request)
    assert receipt.status == "completed", receipt.error
    config = OperationStoreConfig(
        state_root=str(tmp_path / "operations"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    submission = CandidateOperation(request_id=uuid4(), request=training_request)
    record = OperationRecord(
        native_id=UUID(receipt.run_id),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=runtime_identity(),
        inputs=training_request.files,
        admitted_at=now(),
    )
    with locked_store(config) as root:
        claim(root, record)
    observed = read_operation(config, submission.request_id)
    assert observed.receipt.status == "completed"
    # Read through the public CLI in a new interpreter after the worker has exited.
    import subprocess
    import sys

    store_config = tmp_path / "store.json"
    store_config.write_text(config.model_dump_json())
    command = [
        sys.executable,
        "-m",
        "tools.candidate_operations",
        "status",
        "--store-config",
        str(store_config),
        "--operation-id",
        str(submission.request_id),
    ]
    fresh = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, timeout=60, check=True
    )
    assert json.loads(fresh.stdout)["receipt"]["status"] == "completed"
    if tamper == "missing":
        Path(receipt.native_output_paths[-1]).unlink()
    else:
        import hashlib

        from tools.candidate_operations.models import Completion
        from tools.candidate_operations.store import operation_path

        native_path = Path(receipt.workspace) / "candidate_run/receipt.json"
        completion = Completion(
            operation_id=submission.request_id,
            request_digest=record.request_digest,
            outcome="native",
            receipt_digest=hashlib.sha256(native_path.read_bytes()).hexdigest(),
            reason="native_terminal",
        )
        (operation_path(config, submission.request_id) / "completion.json").write_text(
            completion.model_dump_json()
        )
        (operation_path(config, submission.request_id) / "completion.json").chmod(0o600)
        output_path = Path(receipt.native_output_paths[-1])
        output_path.write_bytes(output_path.read_bytes() + b"\n")
        modified = json.loads(native_path.read_text())
        modified["training_output"]["output_sha256"] = hashlib.sha256(
            output_path.read_bytes()
        ).hexdigest()
        native_path.write_text(json.dumps(modified))
    assert read_operation(config, submission.request_id).reason == "integrity_failure"
    fresh = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, timeout=60, check=True
    )
    assert json.loads(fresh.stdout)["reason"] == "integrity_failure"


@pytest.mark.parametrize("missing", [False, True])
def test_generated_loss_reaches_only_native_tuner_destination(
    training_request, training_runner, monkeypatch, missing
):
    """A real generated loss must be staged beside the model without global publication."""
    import yaml

    from workflows.task_composition import build_task_composition_ref, compose_run_task_bindings

    project = Path(training_request.preview.project_root)
    manifest = Path(training_request.preview.document.definition.task.manifest)
    source = yaml.safe_load(
        manifest.read_text().replace("../../examples/", str(manifest.parents[2] / "examples") + "/")
    )
    task = yaml.safe_load(Path(source["task_config"]["config"]).read_text())
    forward = task["forward_contract"]
    target = {
        "axes": [{"role": "batch", "dimension": {"symbolic": "B"}}],
        "dtype": {"admissible": ["int64"]},
    }
    forward["supervision_target"] = target
    forward["custom_loss_applicability"] = {
        "mode": "explicit_pair",
        "prediction": forward["model_io"]["output"],
        "target": target,
    }
    task_file = project / "loss-task.yaml"
    task_file.write_text(yaml.safe_dump(task))
    source["task_config"]["config"] = str(task_file)
    source["objective"] = {"none": True}
    task_plugin = project / "loss_task_plugin.py"
    task_plugin.write_text(
        Path(source["task_data_path"]["file"])
        .read_text()
        .replace(
            "class QuickstartTaskDataPath:",
            "class QuickstartTaskDataPath:\n    @staticmethod\n    def custom_loss_validation_pair():\n        import torch\n        return torch.tensor([[0.2, 0.8], [0.7, 0.3]], requires_grad=True), torch.tensor([1, 0])\n",
        )
    )
    source["task_data_path"]["file"] = str(task_plugin)
    manifest_file = project / "loss-manifest.yaml"
    manifest_file.write_text(yaml.safe_dump(source))
    from execute_tools import task_data_path

    monkeypatch.setattr(task_data_path, "_REGISTRY", {})
    monkeypatch.setattr(task_data_path, "_CONTENT", {})
    composition = compose_run_task_bindings(str(manifest_file))
    seed_file = project / "seed.json"
    seed = json.loads(seed_file.read_text())
    seed.update(
        forward_contract=composition.forward_contract.model_dump(mode="json"),
        task_composition_ref=build_task_composition_ref(composition).model_dump(mode="json"),
    )
    seed_file.write_text(json.dumps(seed))
    document = training_request.preview.document.model_dump(mode="json")
    document["definition"]["task"]["manifest"] = str(manifest_file)
    training_request = refresh(
        training_request.model_copy(
            update={
                "preview": training_request.preview.model_copy(
                    update={"document": WorkflowDocument.model_validate_json(json.dumps(document))}
                )
            }
        )
    )
    original = Provider.generate

    def generate(self, system, user, **kwargs):
        if kwargs.get("label") == "implementor.loss.code":
            return {
                "extra_imports": "",
                "config_fields_code": "",
                "init_body": "pass",
                "forward_body": "return torch.nn.functional.cross_entropy(inputs, targets.long())",
            }
        result = original(self, system, user, **kwargs)
        if "model_name" in result:
            result["custom_loss_spec"] = {
                "loss_name": "worker_cross_entropy",
                "description": "Synthetic cross entropy propagation witness.",
                "mathematical_definition": "L = mean(-log softmax(logits)[label])",
            }
            result["baseline_config"]["loss_config"] = {
                "loss_type": "custom",
                "loss_name": "worker_cross_entropy",
            }
        return result

    monkeypatch.setattr(Provider, "generate", generate)
    if missing:
        from tools.candidate_worker import training

        real_execute = training.execute_training

        def remove_loss(phases, admitted):
            Path(phases.implementation.loss_provenance.loss_file_path).unlink()
            return real_execute(phases, admitted)

        monkeypatch.setattr(training, "execute_training", remove_loss)
    receipt = launch_candidate(training_request)
    if missing:
        assert receipt.status == "failed" and "source is missing" in receipt.error
        assert not any(name == "tuner" for name, _ in training_runner)
        return
    assert receipt.status == "completed", receipt.error
    tuned = next(value for name, value in training_runner if name == "tuner")
    from core.sandbox_executor import get_loss_dir

    directory = Path(tuned.storage.local.workspace)
    staged = Path(get_loss_dir(str(directory), receipt.run_name)) / "worker_cross_entropy.py"
    assert staged.is_file()
    assert "cross_entropy" in staged.read_text()
    assert not list((Path(receipt.workspace) / "generated_library").glob("losses/*.py"))


def test_public_example_writes_portable_matching_inputs(tmp_path):
    """A fresh interpreter must build request/seed/settings from this checkout, outside its source tree."""
    import subprocess
    import sys

    from tools.candidate_worker.models import CandidateRunRequest
    from workflows.candidate_training_settings import CandidateTrainingSettings

    repo = Path(__file__).resolve().parents[4]
    data = tmp_path / "data"
    data.mkdir()
    project = tmp_path / "inputs"
    result = subprocess.run(
        [
            sys.executable,
            str(repo / "examples/workflow_declarations/native_training.py"),
            "--project",
            str(project),
            "--data",
            str(data),
            "--workspace",
            str(tmp_path / "workspace"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    request = CandidateRunRequest.model_validate_json(
        (project / "candidate_request.json").read_bytes()
    )
    assert request.preview.document.definition.task.manifest == str(
        repo / "configs/task_composition/quickstart.yaml"
    )
    settings = CandidateTrainingSettings.model_validate_json(
        (project / "settings.json").read_bytes()
    )
    assert (
        settings.launch.trial_time_budget_minutes,
        settings.launch.formal_time_budget_minutes,
    ) == (2, 5)
    assert not (tmp_path / "workspace").exists()
    assert {node.capability for node in request.preview.document.definition.nodes} == {
        "proposal",
        "implementation",
        "validation",
        "tuning",
    }


def test_real_child_process_uses_captured_training_request(training_request, monkeypatch):
    """A fresh interpreter must dispatch the serialized request and preserve tuner budgets."""
    import subprocess
    import sys

    from tools.workspace_sandbox.runner import ExecutionResult

    program = """
import sys
from pathlib import Path
import pytest
from tests.unit.tools.candidate_worker.test_native import native_runner
from tests.unit.tools.candidate_worker.test_training import training_runner
from tools.candidate_worker.child import execute
patch = pytest.MonkeyPatch()
provider = native_runner.__wrapped__(patch)
seen = training_runner.__wrapped__(provider, patch)
receipt = execute(Path(sys.argv[1]))
assert receipt.status == "completed", receipt.error
request = next(value for name, value in seen if name == "tuner")
assert (request.trial_time_budget_minutes, request.formal_time_budget_minutes) == (7, 19)
"""

    def child(profile, argv):
        result = subprocess.run(
            [sys.executable, "-c", program, argv[-1]], capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)

    monkeypatch.setattr(importlib.import_module("tools.candidate_worker.launch"), "run", child)
    receipt = launch_candidate(training_request)
    assert receipt.status == "completed", receipt.error


def test_unavailable_measurement_refuses_before_provider(
    training_request, training_runner, monkeypatch
):
    """The managed true guard must reach the real owner, even when the caller omits it."""
    from core.runtime_control.launch_guard import run_launch_self_test
    from tools.candidate_worker import training_admission

    monkeypatch.setattr(training_admission, "run_launch_self_test", run_launch_self_test)
    receipt = launch_candidate(training_request)
    assert receipt.status == "failed"
    assert "offline fixture" in receipt.error
    assert not Provider.calls
    assert not any(name == "tuner" for name, _ in training_runner)


def test_public_tune_routes_match_actual_native_tuner_input(training_request, training_runner):
    """Preview's public route must describe the native input that reaches tuner.run."""
    from pydantic import TypeAdapter

    from nodes.tuner_llm_settings import tuner_bridge_arguments
    from tools.setup_review.routes import node_llm_routes
    from workflows.llm_config import WorkflowLLMConfig

    receipt = launch_candidate(training_request)
    assert receipt.status == "completed", receipt.error
    tuned = next(value for name, value in training_runner if name == "tuner")
    config = WorkflowLLMConfig.model_validate_json(
        (Path(training_request.preview.project_root) / "llm.json").read_bytes()
    )
    route = next(route for route in node_llm_routes(config, "tune") if route.name == "tune.planner")
    assert route.bridge_arguments == TypeAdapter(dict).dump_python(
        tuner_bridge_arguments(tuned), mode="json"
    )
    assert route in training_request.selected_constructor_routes


def test_four_stage_reusable_requires_source_owned_settings(training_request):
    """A v1 settings file cannot silently become a reusable source-owned input."""
    from workflows.definition import ReusableWorkflowDocument
    from workflows.definition.models import ReusableWorkflowDefinition

    payload = training_request.preview.document.definition.model_dump(mode="json")
    payload["schema_version"] = 2
    payload["task"].pop("workspace")
    reusable = ReusableWorkflowDefinition.model_validate_json(json.dumps(payload))
    with pytest.raises(ValueError, match="source-owned training_settings"):
        ReusableWorkflowDocument(definition=reusable)
