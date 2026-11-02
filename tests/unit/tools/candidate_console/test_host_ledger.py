"""Console launches under the shared host reservation ledger (B3-4c, backend).

The console loads the operator's ledger selection once and every submission goes
through ``CandidateConsole.submit``, which applies it by kind.
"""

import json
from uuid import uuid4

import pytest

from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.scheduling import GpuHardwareClass, GpuSlot, HostBudget
from tests.unit.tools.candidate_worker.conftest import prepared as worker_prepared
from tools.candidate_console.models import ConsoleHostLedger, RunResourcesSelection
from tools.candidate_console.service import CandidateConsole, with_run_resources
from tools.candidate_operations import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    CandidateOperation,
    PrepareOperation,
)
from tools.candidate_operations.models import OperationResources

SERVICE = "tools.candidate_console.service."
__all__ = ["worker_prepared"]


def _budget() -> HostBudget:
    return HostBudget(
        gpus=(
            GpuSlot(
                uuid="GPU-aaaa",
                hardware_class=GpuHardwareClass(
                    device_name="NVIDIA H100",
                    total_memory_bytes=80 * 1024**3,
                    compute_capability=(9, 0),
                ),
                ceiling=ResolvedGpuCeiling(
                    operator_ceiling_gib=4.0,
                    operator_source="caller",
                    host_quota_gib=None,
                    measured_capacity_gib=80.0,
                ),
            ),
        ),
        host_memory_gib=64.0,
        cpu_slots=16,
        max_concurrent_units=4,
        source="file",
    )


@pytest.fixture
def ledgered(console_config, tmp_path):
    root = tmp_path / "host-ledger"
    root.mkdir(mode=0o700)
    budget = tmp_path / "host-budget.json"
    budget.write_text(_budget().model_dump_json(exclude={"source"}))
    return console_config.model_copy(
        update={"host_ledger": ConsoleHostLedger(ledger_root=str(root), budget_file=str(budget))}
    )


def test_the_ledger_selection_reaches_exactly_the_kinds_it_governs(ledgered, monkeypatch):
    """Candidate runs and loop resumes reserve; preparations and native chains never do.

    A console that dropped ``host`` would launch GUI runs unbudgeted beside
    ledger-placed CLI runs (oversubscription); one that passed it for a
    preparation would refuse it ``resources_required``.
    """
    console = CandidateConsole(ledgered)
    assert console.host is not None and console.host.budget.digest == _budget().digest
    seen = {}

    def submit(store, submission, *, launch_environment, expected_reusable_inputs=None, host):
        seen[submission.kind] = host
        return None

    monkeypatch.setattr(SERVICE + "submit_operation", submit)
    candidate = CandidateOperation.model_construct(kind="candidate", request_id=uuid4())
    resume = CandidateLoopResumeOperation(
        request_id=uuid4(),
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=uuid4(), expected_receipt_digest="a" * 64
        ),
    )
    prepare = PrepareOperation.model_construct(kind="prepare", request_id=uuid4())
    chain = PrepareOperation.model_construct(kind="native_chain", request_id=uuid4())
    for submission in (candidate, resume, prepare, chain):
        console.submit(submission, launch_environment={})
    assert seen == {
        "candidate": console.host,
        "candidate_loop_resume": console.host,
        "prepare": None,
        "native_chain": None,
    }


def test_an_unusable_ledger_stops_the_console_instead_of_launching_unbudgeted(ledgered, tmp_path):
    """A typo in the budget file must not silently turn every launch serial."""
    broken = tmp_path / "broken-budget.json"
    broken.write_text(json.dumps({"gpus": []}))
    config = ledgered.model_copy(
        update={"host_ledger": ledgered.host_ledger.model_copy(update={"budget_file": str(broken)})}
    )
    with pytest.raises(ValueError, match="configured host ledger is unusable"):
        CandidateConsole(config)


def test_a_serial_launch_keeps_its_operation_bytes_and_resources_attach_after_review(
    worker_prepared,
):
    """Without operator inputs the reviewed operation is submitted byte for byte;
    with them, the reservation and parallel opt-in reach the operation the ledger reads."""
    from tests.helpers.candidate_fanout import fanout_request
    from tools.candidate_worker.parallel_models import CapabilityResources, ParallelDispatch

    operation = CandidateOperation(request_id=uuid4(), request=fanout_request(worker_prepared))
    serial = with_run_resources(operation, RunResourcesSelection())
    assert serial.model_dump_json() == operation.model_dump_json()
    resources = OperationResources(
        gpu_count=0, host_memory_gib=2.0, cpu_slots=1, time_budgeted=False
    )
    parallel = ParallelDispatch(
        capabilities={
            "implementation": CapabilityResources(gpu=False, host_memory_gib=1.0, cpu_slots=1)
        }
    )
    launched = with_run_resources(
        operation, RunResourcesSelection(resources=resources, parallel=parallel)
    )
    assert launched.resources == resources
    assert launched.request.parallel == parallel
    assert launched.request_id == operation.request_id


def test_review_refuses_what_the_launch_would_refuse_or_ignore(ledgered, console_config):
    """Without a ledger, declared resources were shown as reserved, then ignored at launch;
    with one, a resource-less review passed and only Launch refused. Both now refuse at review."""
    from tools.candidate_operations.models import OperationFailure

    resources = OperationResources(
        gpu_count=0, host_memory_gib=2.0, cpu_slots=1, time_budgeted=False
    )
    serial = CandidateConsole(console_config)
    assert "host_ledger" not in serial.choices_view().model_dump_json()
    serial.require_reviewable_resources(RunResourcesSelection())  # serial review as before
    with pytest.raises(OperationFailure) as refused:
        serial.require_reviewable_resources(RunResourcesSelection(resources=resources))
    assert refused.value.detail.code == "host_ledger_missing"
    shared = CandidateConsole(ledgered)
    assert shared.choices_view().host_ledger is True
    shared.require_reviewable_resources(RunResourcesSelection(resources=resources))
    with pytest.raises(OperationFailure) as missing:
        shared.require_reviewable_resources(RunResourcesSelection())
    assert missing.value.detail.code == "resources_required"


def test_queue_full_refusal_reaches_the_browser_with_recovery_action(console_config, monkeypatch):
    """The generic native-verification error hid the host admission refusal."""
    from tests.unit.tools.candidate_console.test_http import client
    from tools.candidate_operations.models import OperationFailure

    def refuse(self, selection):
        raise OperationFailure("host_queue_full", "private diagnostic")

    monkeypatch.setattr(CandidateConsole, "resume_loop", refuse)
    response = client(console_config).post(
        "/api/loop-resumes",
        json={
            "request_id": str(uuid4()),
            "predecessor_operation_id": str(uuid4()),
            "expected_receipt_digest": "a" * 64,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "host_queue_full",
        "message": "host waiting queue is full or disabled; retry when capacity is available",
    }


def test_run_resources_set_only_supplied_fields_and_never_override_a_reviewed_one(
    worker_prepared,
):
    """Supplying only ``resources`` silently cleared a reviewed request's ``parallel``,
    so the run launched serially inside a reservation sized for parallel (#1108)."""
    from tests.helpers.candidate_fanout import fanout_request
    from tools.candidate_operations.models import OperationFailure
    from tools.candidate_worker.parallel_models import CapabilityResources, ParallelDispatch

    def parallel(memory: float) -> ParallelDispatch:
        unit = CapabilityResources(gpu=False, host_memory_gib=memory, cpu_slots=1)
        return ParallelDispatch(capabilities={"implementation": unit})

    request = fanout_request(worker_prepared).model_copy(update={"parallel": parallel(1.0)})
    operation = CandidateOperation(request_id=uuid4(), request=request)
    resources = OperationResources(
        gpu_count=0, host_memory_gib=2.0, cpu_slots=1, time_budgeted=False
    )
    launched = with_run_resources(operation, RunResourcesSelection(resources=resources))
    assert launched.request.parallel == parallel(1.0) and launched.resources == resources
    same = with_run_resources(operation, RunResourcesSelection(parallel=parallel(1.0)))
    assert same.request.parallel == parallel(1.0)
    with pytest.raises(OperationFailure) as conflict:
        with_run_resources(operation, RunResourcesSelection(parallel=parallel(2.0)))
    assert conflict.value.detail.code == "run_resources_conflict"
    with pytest.raises(OperationFailure) as replaced:
        with_run_resources(
            launched,
            RunResourcesSelection(resources=resources.model_copy(update={"cpu_slots": 2})),
        )
    assert replaced.value.detail.code == "run_resources_conflict"


def test_a_relative_budget_file_stops_the_console(ledgered, tmp_path, monkeypatch):
    """A relative ``budget_file`` was resolved against the console's working directory,
    so the same configuration loaded a different budget per launch directory."""
    monkeypatch.chdir(tmp_path)
    config = ledgered.model_copy(
        update={
            "host_ledger": ledgered.host_ledger.model_copy(
                update={"budget_file": "host-budget.json"}
            )
        }
    )
    with pytest.raises(ValueError, match="configured host ledger is unusable"):
        CandidateConsole(config)


@pytest.mark.parametrize(
    ("code", "remedy"),
    [
        ("resource_refused", "lower them"),
        ("parallel_unit_exceeds_capacity", "parallel table"),
        ("run_resources_conflict", "without overriding"),
    ],
)
def test_resource_refusals_reach_the_browser_with_their_remedy(
    console_config, monkeypatch, code, remedy
):
    """These refusals reached the browser as "native operation could not be verified",
    so a parallel run refused for its own declaration gave the operator no remedy."""
    from tests.unit.tools.candidate_console.test_http import client
    from tools.candidate_operations.models import OperationFailure

    def refuse(self, selection):
        raise OperationFailure(code, "private diagnostic")

    monkeypatch.setattr(CandidateConsole, "resume_loop", refuse)
    response = client(console_config).post(
        "/api/loop-resumes",
        json={
            "request_id": str(uuid4()),
            "predecessor_operation_id": str(uuid4()),
            "expected_receipt_digest": "a" * 64,
        },
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == code and remedy in error["message"]
    assert "private diagnostic" not in error["message"]


def _resume_review_doubles(monkeypatch, root_resources, parallel=None):
    """The owners stubbed at the service call site; ``loop_resume_resources`` stays real."""
    from types import SimpleNamespace

    from tests.unit.tools.candidate_console.test_loop_pause_resume import (
        _paused,
        _readiness,
        _snapshot,
    )

    loop = SimpleNamespace(final_iteration=3)
    preview = SimpleNamespace(document=SimpleNamespace(definition=SimpleNamespace(loop=loop)))
    root = CandidateOperation.model_construct(
        request_id=uuid4(),
        request=SimpleNamespace(preview=preview, environment_names=(), parallel=parallel),
        resources=root_resources,
    )
    monkeypatch.setattr(
        SERVICE + "review_loop_resume",
        lambda config, value: _snapshot(value, receipt=_paused(attempted=1)),
    )
    monkeypatch.setattr(SERVICE + "loop_root_operation", lambda config, value: root)
    monkeypatch.setattr(SERVICE + "credential_readiness", lambda request, path: _readiness())


#: ``RunResourcesSelection(resources=RESOURCES).bound_digest("c" * 64)`` computed by the
#: pre-#1385 candidate code (master cc0dee852): the Resume binding reuses that formula,
#: and existing candidate review digests stay unchanged.
BOUND_C = "e6aa5dff20a98b02e11c79d0667e880cfd0a5696b7fdcfc64fe8c610eebdf35e"
RESOURCES = OperationResources(gpu_count=0, host_memory_gib=2.0, cpu_slots=1, time_budgeted=False)


def test_candidate_review_digests_are_unchanged_by_the_shared_reservation_binding():
    """``bound_digest`` moved to ``ReservationSelection`` (#1385). Literals from the
    pre-change code (master cc0dee852): a changed formula would turn every retained
    candidate launch into ``stale_review`` and break its idempotent replay."""
    from tools.candidate_worker.parallel_models import CapabilityResources, ParallelDispatch

    parallel = ParallelDispatch(
        capabilities={
            "implementation": CapabilityResources(gpu=False, host_memory_gib=1.0, cpu_slots=1)
        }
    )
    base = "a" * 64
    assert RunResourcesSelection().bound_digest(base) == base
    assert RunResourcesSelection(resources=RESOURCES).bound_digest(base) == (
        "d712be3808fb93c8f3a9415fdfbe9c8bccfdedc55fc56a11c138ed5b9856dd15"
    )
    assert RunResourcesSelection(parallel=parallel).bound_digest(base) == (
        "0a654f2b4d7ae29cbb3f8880bc0474b9e5e7b72fcf80c39c175ae91277576813"
    )
    assert RunResourcesSelection(resources=RESOURCES, parallel=parallel).bound_digest(base) == (
        "a9df2aaf4bd586d5751f10bcb61f3a1fd5e0c49e8fd2b18aa869bd0d99b85f1e"
    )


def test_resume_review_binds_the_segment_reservation_of_an_undeclared_root(ledgered, monkeypatch):
    """#1385: under a shared ledger a loop whose root declared no resources had no Resume
    path (the console always passed its ledger, and admission refused). The review now
    requires the segment's reservation, echoes it and binds it into ``review_digest``."""
    from tests.unit.tools.candidate_console.test_http import client

    _resume_review_doubles(monkeypatch, None)
    api = client(ledgered)
    path = f"/api/operations/{uuid4()}/loop-resume-review"
    plain = api.get(path)
    assert plain.status_code == 409
    assert plain.json()["error"]["code"] == "resources_required"
    assert "first run declared no host resources" in plain.json()["error"]["message"]
    reviewed = api.post(path, json={"resources": RESOURCES.model_dump(mode="json")})
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["expected_receipt_digest"] == "c" * 64
    assert OperationResources.model_validate(body["resources"]) == RESOURCES
    assert body["review_digest"] == BOUND_C


@pytest.mark.parametrize(
    ("ledger", "root_resources", "budgeted", "code"),
    [
        (True, RESOURCES, False, "run_resources_conflict"),
        (False, None, False, "host_ledger_missing"),
        (True, None, True, "parallel_budget"),
    ],
    ids=("root-declares-resources", "no-host-ledger", "root-parallel-budget"),
)
def test_resume_review_refuses_a_reservation_admission_would_refuse(
    ledgered, console_config, monkeypatch, ledger, root_resources, budgeted, code
):
    """A reservation beside the root's own (even an equal one), without a ledger, or for a
    root whose parallel run brings its own ``parallel.budget`` was accepted at review, then
    refused or ignored at Resume."""
    from types import SimpleNamespace

    from tests.unit.tools.candidate_console.test_http import client

    parallel = SimpleNamespace(budget=SimpleNamespace()) if budgeted else None
    _resume_review_doubles(monkeypatch, root_resources, parallel)
    api = client(ledgered if ledger else console_config)
    response = api.post(
        f"/api/operations/{uuid4()}/loop-resume-review",
        json={"resources": RESOURCES.model_dump(mode="json")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    if root_resources is not None:  # the root's own declaration still reviews without one
        assert api.get(f"/api/operations/{uuid4()}/loop-resume-review").status_code == 200


def test_resume_carries_only_the_reviewed_reservation(ledgered, monkeypatch):
    """A Resume whose reservation differs from the reviewed one (or lacks the binding)
    refuses ``stale_review`` before any submission; the reviewed one reaches the request."""
    from tests.unit.tools.candidate_console.test_http import client
    from tests.unit.tools.candidate_console.test_loop_pause_resume import _handle

    submitted = []

    def submit(store, submission, launch_environment, *, host, **_options):
        submitted.append((submission, host))
        return _handle(submission.request_id, "starting")

    _resume_review_doubles(monkeypatch, None)
    monkeypatch.setattr(SERVICE + "submit_operation", submit)
    api = client(ledgered)
    payload = {
        "request_id": str(uuid4()),
        "predecessor_operation_id": str(uuid4()),
        "expected_receipt_digest": "c" * 64,
    }
    resources = RESOURCES.model_dump(mode="json")
    for stale in (
        {"resources": {**resources, "cpu_slots": 2}, "expected_review_digest": BOUND_C},
        {"resources": resources},
        {"expected_review_digest": BOUND_C},
    ):
        response = api.post("/api/loop-resumes", json=payload | stale)
        assert response.status_code == 409, stale
        assert response.json()["error"]["code"] == "stale_review"
    assert submitted == []
    response = api.post(
        "/api/loop-resumes",
        json=payload | {"resources": resources, "expected_review_digest": BOUND_C},
    )
    assert response.status_code == 202, response.text
    [(submission, host)] = submitted
    assert submission.request.resources == RESOURCES
    assert host is not None
