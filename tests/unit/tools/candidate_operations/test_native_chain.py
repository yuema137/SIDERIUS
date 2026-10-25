"""Chain recovery and release trust boundaries, independent of scientific outcomes."""

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from core.runtime_control.process_group import GroupCleanup, GroupObservation
from tools.candidate_operations import read_operation, submit_operation
from tools.candidate_operations.files import encode, publish
from tools.candidate_operations.models import Completion, OperationRecord, OperationStoreConfig
from tools.candidate_operations.native_chain import _fence
from tools.candidate_operations.native_chain_models import (
    NativeChainAdmission,
    NativeChainOperation,
    NativeChainOperationRequest,
    NativeChainTerminal,
)
from tools.candidate_operations.process import current_identity, runtime_identity
from tools.candidate_operations.read import releasable
from tools.candidate_operations.store import claim, digest, locked_store, now
from tools.workspace_sandbox.runner import ExecutionResult, ObservedExecutionResult


@pytest.fixture
def chain(tmp_path):
    envelope = tmp_path / "envelope"
    envelope.mkdir()
    source = tmp_path / "capture.json"
    source.write_text("original removed after admission")
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    submission = NativeChainOperation(
        request_id=uuid4(),
        request=NativeChainOperationRequest(
            capture_path=str(source),
            capture_sha256="a" * 64,
            envelope=str(envelope),
            read_only=(),
            network=False,
            devices=(),
            environment_names=("OPENAI_API_KEY",),
            timeout_seconds=10,
            input_max_bytes=16777216,
            max_iterations_observed=2,
            max_observation_bytes=1048576,
        ),
    )
    runtime = runtime_identity()
    admission = NativeChainAdmission(
        request_digest=digest(submission),
        capture_sha256="a" * 64,
        workspace=str(envelope / "workspace"),
        final_iteration=2,
        run_name="native_test",
        recipe="native-standard-chain/v1",
        checkout=runtime.source,
        git_directory=runtime.source + "/.git",
        git_common_directory=runtime.source + "/.git",
        required_environment_names=("OPENAI_API_KEY",),
        input_files=(),
    )
    record = OperationRecord(
        native_id=uuid4(),
        submission=submission,
        request_digest=digest(submission),
        config=config,
        runtime=runtime,
        inputs=(),
        admitted_at=now(),
        native_chain_admission=admission,
    )
    with locked_store(config) as root:
        path = claim(root, record)
    marker = current_identity(record)
    publish(
        path / "process.json", marker.model_copy(update={"start_ticks": marker.start_ticks + 1})
    )
    return record, path


def test_recovery_never_reopens_capture_or_requires_keys(chain, monkeypatch):
    """Deleting fresh inputs must not trigger a second launch or lose stored identity."""
    record, _ = chain
    Path(record.submission.request.capture_path).unlink()
    Path(record.native_chain_admission.workspace).mkdir()

    def forbidden(*args, **kwargs):
        pytest.fail("fresh admission/spawn during recovery")

    monkeypatch.setattr(
        "tools.candidate_operations.submit.review_native_chain_operation", forbidden
    )
    monkeypatch.setattr("tools.candidate_operations.submit.spawn", forbidden)
    assert (
        submit_operation(record.config, record.submission, launch_environment={}).observation
        == "existing"
    )
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.state == "unknown"
    assert snapshot.native_chain.admission.final_iteration == 2
    assert snapshot.native_chain.admission.run_name == "native_test"
    assert snapshot.native_chain.admission.recipe == "native-standard-chain/v1"


def test_cross_store_fence_is_exclusive_and_not_reused(chain):
    """Two persisted stores cannot both acquire a fresh envelope, even same content."""
    record, _ = chain
    _fence(record)
    other = record.model_copy(
        update={"submission": record.submission.model_copy(update={"request_id": uuid4()})}
    )
    with pytest.raises((OSError, ValueError)):
        _fence(other)
    assert not Path(record.native_chain_admission.workspace).exists()


@pytest.mark.parametrize("cleanup", ["absent", "present", "unknown"])
@pytest.mark.parametrize("status", ["completed", "failed", "timed_out"])
def test_release_requires_cleanup_not_shell_success(chain, cleanup, status):
    """Unknown/late-present cleanup must block even exit zero; known failure can release."""
    record, path = chain
    terminal = NativeChainTerminal(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        capture_sha256="a" * 64,
        envelope=record.submission.request.envelope,
        workspace=record.native_chain_admission.workspace,
        runtime_digest=hashlib.sha256(encode(record.runtime)).hexdigest(),
        supervision=ObservedExecutionResult(
            execution=ExecutionResult(
                status=status, returncode=0 if status == "completed" else 124, elapsed_seconds=1
            ),
            cleanup=GroupCleanup(required=False, final=GroupObservation(status=cleanup)),
            direct_child_reaped=True,
        ),
    )
    publish(path / "native-chain-terminal.json", terminal)
    publish(
        path / "completion.json",
        Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="native_chain",
            terminal_digest=hashlib.sha256(encode(terminal)).hexdigest(),
            reason="native_chain_terminal",
        ),
    )
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.state == ("completed" if cleanup == "absent" else "unknown")
    assert snapshot.native_chain.terminal.supervision.execution.status == status
    assert not snapshot.receipt_available
    assert releasable(record.config, record.submission.request_id) == (cleanup == "absent")
    (path / "native-chain-terminal.json").write_bytes(encode(terminal) + b" ")
    assert read_operation(record.config, record.submission.request_id).reason == "integrity_failure"
    assert not releasable(record.config, record.submission.request_id)


def test_predispatch_completion_cannot_override_terminal(chain):
    record, path = chain
    (path / "native-chain-terminal.json").write_text("terminal exists, even if malformed")
    publish(
        path / "completion.json",
        Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="pre_dispatch_failure",
            reason="refused",
        ),
    )
    assert read_operation(record.config, record.submission.request_id).reason == "integrity_failure"
    assert not releasable(record.config, record.submission.request_id)


@pytest.mark.parametrize("failure", ["pre_spawn", "post_spawn"])
def test_dispatch_classifies_only_proven_pre_spawn_failure(chain, monkeypatch, failure):
    from tools.candidate_operations.native_chain import execute_native_chain
    from tools.workspace_sandbox.runner import ObservedSpawnFailure

    record, path = chain
    monkeypatch.setattr(
        "tools.candidate_operations.native_chain.review_native_chain_operation",
        lambda *a, **k: record.native_chain_admission,
    )
    monkeypatch.setattr("tools.candidate_operations.native_chain.captured", lambda *a: None)
    monkeypatch.setattr("tools.candidate_operations.native_chain.sandbox_profile", lambda *a: None)
    monkeypatch.setattr("tools.candidate_operations.native_chain.shell_arguments", lambda *a: ())

    def failed(*args):
        raise (
            ObservedSpawnFailure("not created")
            if failure == "pre_spawn"
            else OSError("after spawn")
        )

    monkeypatch.setattr("tools.candidate_operations.native_chain.run_observed", failed)
    completion = execute_native_chain(record, path)
    assert completion.outcome == ("pre_dispatch_failure" if failure == "pre_spawn" else "unknown")


@pytest.mark.parametrize("timeout", [False, True])
def test_review_cli_bounds_subprocess_failures(chain, monkeypatch, capsys, timeout):
    import subprocess

    from tools.candidate_operations.__main__ import main

    record, path = chain
    config_path = path / "cli-config.json"
    request_path = path / "cli-request.json"
    config_path.write_text(record.config.model_dump_json())
    request_path.write_text(record.submission.model_dump_json())

    def failed(*args, **kwargs):
        if timeout:
            raise subprocess.TimeoutExpired(["private-scientific-argv"], 1)
        raise subprocess.CalledProcessError(78, ["private-scientific-argv"])

    monkeypatch.setattr(
        "tools.candidate_operations.native_chain._review_native_chain_operation", failed
    )
    monkeypatch.setattr(
        "sys.argv",
        ["operation", "review", "--store-config", str(config_path), "--request", str(request_path)],
    )
    assert main() == 2
    error = capsys.readouterr().err
    assert (
        "native_chain_admission" in error
        and "private-scientific-argv" not in error
        and "Traceback" not in error
    )


@pytest.mark.parametrize("route_name", ["interpret", "tune.reflector"])
def test_admission_forwards_full_native_routes(chain, monkeypatch, route_name):
    """A provider used only outside candidate stages must still block missing credentials."""
    from types import SimpleNamespace as NS

    from tools.candidate_operations.native_chain import review_native_chain_operation
    from tools.candidate_worker.preflight import require_credentials
    from tools.setup_review.route_models import LLMRoute, RouteTransport

    record, _ = chain
    route = LLMRoute(
        name=route_name,
        applicability="conditional",
        bridge_arguments={},
        transport=RouteTransport(
            provider="gemini",
            model_id="fixture",
            base_url=None,
            reasoning_effort=None,
            max_retries=None,
            request_timeout=1,
            timeout_retries=0,
        ),
    )
    routes = (
        route,
        LLMRoute(name="analysis", applicability="disabled", bridge_arguments={}, transport=None),
        LLMRoute(name="implement", applicability="pseudo", bridge_arguments={}, transport=None),
    )
    admission = record.native_chain_admission
    request = record.submission.request.model_copy(
        update={"environment_names": ("GEMINI_API_KEY",)}
    )
    submission = record.submission.model_copy(update={"request": request})
    capture = NS(
        declaration=NS(
            run=NS(workspace=Path(admission.workspace), final_iteration=2),
            working_directory=Path(record.runtime.source),
        ),
        environment=NS(
            launch_binding=NS(
                installation=NS(source_root=record.runtime.source), file_max_bytes=16777216
            ),
            saved_task_check=NS(result=NS(task_settings=NS(llm_routes=routes))),
        ),
    )
    monkeypatch.setattr("tools.candidate_operations.native_chain.captured", lambda *a: capture)
    observed = []

    def check(actual_routes, names, env):
        observed.append(actual_routes)
        require_credentials(actual_routes, names, env)

    monkeypatch.setattr("tools.candidate_operations.native_chain.require_credentials", check)
    with pytest.raises(ValueError, match="binding refused"):
        review_native_chain_operation(record.config, submission, launch_environment={})
    assert observed == [routes]


def test_concurrent_persisted_stores_claim_one_envelope(chain, tmp_path):
    """Actual concurrent exclusive mkdir prevents two store owners claiming one destination."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    record, _ = chain
    second_config = record.config.model_copy(update={"state_root": str(tmp_path / "second-state")})
    second = record.model_copy(
        update={
            "config": second_config,
            "submission": record.submission.model_copy(update={"request_id": uuid4()}),
        }
    )
    with locked_store(second_config) as root:
        claim(root, second)
    barrier = Barrier(2)

    def attempt(owner):
        barrier.wait(timeout=5)
        try:
            _fence(owner)
            return owner.submission.request_id
        except (OSError, ValueError):
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (record, second)))
    assert sum(value is not None for value in results) == 1
    binding = Path(record.submission.request.envelope) / ".native-chain-operation/binding.json"
    import json

    assert json.loads(binding.read_text())["operation_id"] == str(
        next(value for value in results if value is not None)
    )


def test_changed_scientific_evidence_does_not_reopen_process_lifecycle(chain):
    """Mutable checkpoint corruption is visible without pretending a cleaned child is live."""
    import json

    from core.iteration_manifest import manifest_self_digest
    from tools.candidate_operations.native_chain_read import chain_evidence

    record, path = chain
    workspace = Path(record.native_chain_admission.workspace)
    iteration = workspace / "iter_001"
    iteration.mkdir(parents=True)
    manifest = {"status": "no_records"}
    manifest["manifest_sha256"] = manifest_self_digest(manifest)
    artifact = iteration / "manifest.json"
    artifact.write_text(json.dumps(manifest))
    terminal = NativeChainTerminal(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        capture_sha256="a" * 64,
        envelope=record.submission.request.envelope,
        workspace=str(workspace),
        runtime_digest=hashlib.sha256(encode(record.runtime)).hexdigest(),
        supervision=ObservedExecutionResult(
            execution=ExecutionResult(status="failed", returncode=1, elapsed_seconds=1),
            cleanup=GroupCleanup(required=False, final=GroupObservation(status="absent")),
            direct_child_reaped=True,
        ),
        evidence=chain_evidence(record),
    )
    publish(path / "native-chain-terminal.json", terminal)
    publish(
        path / "completion.json",
        Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="native_chain",
            terminal_digest=hashlib.sha256(encode(terminal)).hexdigest(),
            reason="native_chain_terminal",
        ),
    )
    artifact.unlink()
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.state == "completed" and releasable(record.config, record.submission.request_id)
    assert snapshot.native_chain.evidence.availability == "integrity_failure"
    assert snapshot.native_chain.terminal.evidence.checkpoints[0].native_status == "no_records"
    assert snapshot.native_chain.terminal.evidence.checkpoints[1].integrity == "missing"


def _saved_observation_terminal(chain, policy, *, full_layout=False):
    """Persist pre-#847 evidence explicitly, independently of the observer under test."""
    import json

    from tools.candidate_operations.files import publish_encoded
    from tools.native_chain.observation import (
        NativeChainCheckpointObservation,
        NativeChainEvidence,
    )

    record, path = chain
    workspace = Path(record.native_chain_admission.workspace)
    iteration = workspace / "iter_001"
    iteration.mkdir(parents=True)
    # Legacy unverified manifest, exact bytes define the expected digest.
    payload = b'{"status":"no_records"}'
    (iteration / "manifest.json").write_bytes(payload)
    (workspace / "token_usage.jsonl").write_text("not interpreted by observation\n")
    terminal = NativeChainTerminal(
        operation_id=record.submission.request_id,
        request_digest=record.request_digest,
        capture_sha256="a" * 64,
        envelope=record.submission.request.envelope,
        workspace=str(workspace),
        runtime_digest=hashlib.sha256(encode(record.runtime)).hexdigest(),
        supervision=ObservedExecutionResult(
            execution=ExecutionResult(status="completed", returncode=0, elapsed_seconds=1),
            cleanup=GroupCleanup(required=False, final=GroupObservation(status="absent")),
            direct_child_reaped=True,
        ),
        evidence=NativeChainEvidence(
            availability="available",
            anomalies=("unexpected_entry",) if policy == 1 else (),
            checkpoints=(
                NativeChainCheckpointObservation(
                    iteration=1,
                    native_status="no_records",
                    integrity="unverified",
                    manifest_sha256=hashlib.sha256(payload).hexdigest(),
                ),
                NativeChainCheckpointObservation(iteration=2, integrity="missing"),
            ),
        ),
    )
    saved = terminal.model_dump(mode="json")
    if full_layout:
        # Exactly 19 entries: legacy v1 permits 18, current v2 permits 19.
        (workspace / "iter_002").mkdir()
        for name in (
            "iter_001_hardware.json",
            "iter_002_hardware.json",
            ".chain_halted",
            "chain_stopped.json",
            "run_invariants_lock.json",
            "effective_config.json",
            "health_checks_effective.yaml",
            "memory_trace.jsonl",
            "per_file_best.json",
            "evolution_log.jsonl",
            "plugins",
            "plugin_source_sentinel",
            "native_test_hardware.json",
            "generated_library",
            "STOP",
        ):
            (workspace / name).touch()
        (workspace / ".token_run_id").write_text("native_test-20261025T120000-123")
        saved["evidence"] = NativeChainEvidence(availability="limit_exceeded").model_dump(
            mode="json"
        )
    # Policy 1 is truly historical JSON: field absent, not an explicit new value.
    saved.pop("observation_policy", None)
    if type(policy) is not int or policy != 1:
        saved["observation_policy"] = policy
    terminal_bytes = json.dumps(saved).encode()
    publish_encoded(path / "native-chain-terminal.json", terminal_bytes)
    publish(
        path / "completion.json",
        Completion(
            operation_id=record.submission.request_id,
            request_digest=record.request_digest,
            outcome="native_chain",
            terminal_digest=hashlib.sha256(terminal_bytes).hexdigest(),
            reason="native_chain_terminal",
        ),
    )
    return workspace, terminal_bytes


@pytest.mark.parametrize("policy", [1, 2])
def test_saved_observer_policy_preserves_history_and_detects_mutation(chain, policy):
    """#847: old ledger diagnostics are history, but later file changes still refuse."""
    record, path = chain
    workspace, terminal_bytes = _saved_observation_terminal(chain, policy)
    completion_bytes = (path / "completion.json").read_bytes()
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.state == "completed"
    assert snapshot.native_chain.evidence.availability == "available"
    assert snapshot.native_chain.evidence.anomalies == ()
    assert snapshot.native_chain.terminal.evidence.anomalies == (
        ("unexpected_entry",) if policy == 1 else ()
    )
    assert snapshot.native_chain.terminal.observation_policy == policy
    assert (path / "native-chain-terminal.json").read_bytes() == terminal_bytes
    assert (path / "completion.json").read_bytes() == completion_bytes

    unknown = workspace / "foreign.jsonl"
    unknown.touch()
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.native_chain.evidence.anomalies == ("changed_after_terminal",)
    unknown.unlink()
    (workspace / "iter_001/manifest.json").write_text('{"status":"failed"}')
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.native_chain.evidence.availability == "integrity_failure"
    assert snapshot.native_chain.evidence.anomalies == ("changed_after_terminal",)
    assert (path / "native-chain-terminal.json").read_bytes() == terminal_bytes


@pytest.mark.parametrize("policy", [0, 3, "2", True])
def test_unsupported_saved_observer_policy_cannot_establish_terminal(chain, policy):
    """Stored unknown/coerced policy must fail closed through the public read boundary."""
    record, _ = chain
    _saved_observation_terminal(chain, policy)
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.reason == "integrity_failure"
    assert not releasable(record.config, record.submission.request_id)


def test_saved_legacy_discovery_limit_projects_current_evidence(chain):
    """The extra ledger slot must not turn a legacy limit result into a mutation."""
    record, path = chain
    _, terminal_bytes = _saved_observation_terminal(chain, 1, full_layout=True)
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.native_chain.terminal.evidence.availability == "limit_exceeded"
    assert snapshot.native_chain.evidence.availability == "available"
    assert snapshot.native_chain.evidence.anomalies == ()
    assert snapshot.native_chain.evidence.token_run_id == "native_test-20261025T120000-123"
    assert (path / "native-chain-terminal.json").read_bytes() == terminal_bytes


def test_new_terminal_writer_records_current_observer_policy(chain, monkeypatch):
    """Production terminal construction must not inherit the legacy read default."""
    import json

    from tools.candidate_operations.native_chain import execute_native_chain

    record, path = chain
    monkeypatch.setattr(
        "tools.candidate_operations.native_chain.review_native_chain_operation",
        lambda *a, **k: record.native_chain_admission,
    )
    monkeypatch.setattr("tools.candidate_operations.native_chain.captured", lambda *a: None)
    monkeypatch.setattr("tools.candidate_operations.native_chain.sandbox_profile", lambda *a: None)
    monkeypatch.setattr("tools.candidate_operations.native_chain.shell_arguments", lambda *a: ())

    def supervised(*args):
        workspace = Path(record.native_chain_admission.workspace)
        workspace.mkdir()
        (workspace / "token_usage.jsonl").touch()
        return ObservedExecutionResult(
            execution=ExecutionResult(status="completed", returncode=0, elapsed_seconds=1),
            cleanup=GroupCleanup(required=False, final=GroupObservation(status="absent")),
            direct_child_reaped=True,
        )

    monkeypatch.setattr("tools.candidate_operations.native_chain.run_observed", supervised)
    completion = execute_native_chain(record, path)
    assert completion.outcome == "native_chain"
    payload = (path / "native-chain-terminal.json").read_bytes()
    saved = json.loads(payload)
    assert saved["observation_policy"] == 2
    assert saved["evidence"]["anomalies"] == []
    assert completion.terminal_digest == hashlib.sha256(payload).hexdigest()
    publish(path / "completion.json", completion)
    snapshot = read_operation(record.config, record.submission.request_id)
    assert snapshot.native_chain.evidence.availability == "available"
    assert snapshot.native_chain.evidence == snapshot.native_chain.terminal.evidence
