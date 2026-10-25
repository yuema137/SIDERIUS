"""Native usage binds one cumulative ledger without opening scientific payloads."""

import hashlib
from pathlib import Path

import pytest

from core.native_writer.ownership import acquire
from tests.unit.tools.candidate_operations.test_native_chain import chain
from tests.unit.tools.candidate_operations.test_native_resume import history, reserve, terminal
from tests.unit.tools.candidate_worker.test_tokens import row
from tools.candidate_operations import read_operation_tokens
from tools.candidate_operations.models import OperationFailure
from tools.candidate_operations.native_chain import _fence
from tools.candidate_operations.native_chain_read import chain_evidence
from tools.native_chain.observation import NativeChainEvidence


def ledger(workspace, name):
    token = f"{name}-20261025T120000-123"
    (workspace / ".token_run_id").write_text(token)
    (workspace / "token_usage.jsonl").write_bytes(
        row(run_id=token, run_name=name)
        + row(run_id=token, run_name=name, tokens={"prompt": None, "completion": 5, "total": None})
        + row(run_id=token, run_name=name, model="other", tokens={"prompt": 3})
        + b"bad row\n{unfinished"
    )
    return token


@pytest.fixture
def native_usage(chain, monkeypatch):
    record, path = chain
    _fence(record)
    workspace = Path(record.native_chain_admission.workspace)
    lease = acquire(workspace, capture_sha256=record.submission.request.capture_sha256)
    lease.close(clean=True)
    workspace.mkdir()
    ledger(workspace, record.native_chain_admission.run_name)
    monkeypatch.setattr(
        "tools.candidate_operations.tokens.read_operation",
        lambda *a: pytest.fail("full scientific read"),
    )
    return record, path, workspace


def read(record):
    return read_operation_tokens(record.config, record.submission.request_id)


@pytest.mark.parametrize("fenced", [False, True])
def test_prelaunch_identity_not_ready_is_unavailable(chain, fenced):
    record, _ = chain
    if fenced:
        _fence(record)
    result = read(record)
    assert result.availability == "unavailable" and not result.groups
    assert result.scope == "chain_cumulative" and result.identity_basis is None


def test_active_native_usage_keeps_independent_counts_and_partial_flags(native_usage):
    record, _, _ = native_usage
    snapshot = read(record)
    first, second = snapshot.groups
    assert (
        first.reported_input_tokens,
        first.reported_output_tokens,
        first.reported_total_tokens,
    ) == (100, 25, 130)
    assert first.missing_input_rows == first.missing_total_rows == 1
    assert second.reported_input_tokens == 3 and second.reported_total_tokens is None
    assert (
        snapshot.quality.invalid_rows == 1
        and snapshot.quality.trailing_fragment
        and snapshot.quality.partial
    )
    assert snapshot.identity_basis == "observed_sidecar"
    assert "not reverified" in snapshot.coverage_note


@pytest.mark.parametrize("kind", ["limited", "anchored"])
def test_terminal_identity_basis_without_scientific_payload_reopen(native_usage, kind):
    record, path, workspace = native_usage
    evidence = (
        chain_evidence(record)
        if kind == "anchored"
        else NativeChainEvidence(availability="limit_exceeded")
    )
    terminal(record, path, record.submission.request, record.native_chain_admission, evidence)
    before = (path / "native-chain-terminal.json").read_bytes()
    result = read(record)
    assert result.identity_basis == (
        "retained_sidecar" if kind == "anchored" else "observed_sidecar"
    )
    assert (path / "native-chain-terminal.json").read_bytes() == before
    (workspace / ".token_run_id").unlink()
    if kind == "anchored":
        with pytest.raises(OperationFailure, match="verified"):
            read(record)
    else:
        assert read(record).availability == "unavailable"


@pytest.mark.parametrize("change", ["sidecar", "ledger", "fence", "terminal", "retained_failure"])
def test_native_identity_and_control_tamper_refuse(native_usage, change):
    record, path, workspace = native_usage
    evidence = chain_evidence(record)
    if change == "retained_failure":
        evidence = evidence.model_copy(update={"availability": "integrity_failure"})
    terminal(record, path, record.submission.request, record.native_chain_admission, evidence)
    if change in {"sidecar", "ledger"}:
        target = workspace / (".token_run_id" if change == "sidecar" else "token_usage.jsonl")
        saved = target.read_bytes()
        target.unlink()
        outside = workspace.parent / "foreign"
        outside.write_bytes(saved)
        target.symlink_to(outside)
    elif change == "fence":
        (workspace.parent / ".native-chain-operation/binding.json").write_text("{}")
    elif change == "terminal":
        with (path / "native-chain-terminal.json").open("ab") as handle:
            handle.write(b" ")
    with pytest.raises(OperationFailure, match="verified"):
        read(record)


def test_parent_and_successor_share_cumulative_ledger_without_double_sum(history, monkeypatch):
    root, _, successor, _, _ = history
    workspace = Path(root.native_chain_admission.workspace)
    ledger(workspace, "fixture")
    monkeypatch.setattr(
        "tools.candidate_operations.tokens.read_operation",
        lambda *a: pytest.fail("full scientific read"),
    )
    assert read(successor).availability == "unavailable"  # not yet linked
    reserve(successor, adopt=True)
    parent, child = read(root), read(successor)
    assert parent.model_dump(exclude={"observed_at"}) == child.model_dump(exclude={"observed_at"})
    assert parent.groups[0].reported_total_tokens == 130
    assert parent.identity_basis == "retained_sidecar"
    (workspace / ".token_run_id").write_text("fixture-20261025T120000-124")
    with pytest.raises(OperationFailure):
        read(successor)


@pytest.mark.parametrize("change", ["missing_writer", "identity_changed", "malformed_identity"])
def test_terminal_identity_cannot_fall_back_to_startup(native_usage, change):
    import shutil

    record, path, workspace = native_usage
    terminal(
        record,
        path,
        record.submission.request,
        record.native_chain_admission,
        chain_evidence(record),
    )
    if change == "missing_writer":
        shutil.rmtree(workspace.parent / f".{workspace.name}.siderius-writer")
        (workspace / ".token_run_id").unlink()
        (workspace / "token_usage.jsonl").unlink()
    else:
        (workspace / ".token_run_id").write_text(
            "native_test-20261025T120000-124" if change == "identity_changed" else "foreign"
        )
    with pytest.raises(OperationFailure):
        read(record)


def test_startup_fence_tamper_is_not_unavailable(chain):
    record, _ = chain
    _fence(record)
    (Path(record.submission.request.envelope) / ".native-chain-operation/binding.json").write_text(
        "{}"
    )
    with pytest.raises(OperationFailure):
        read(record)


def test_unlinked_successor_terminal_refuses(history):
    _, _, successor, path, current = history
    admission = successor.native_resume_admission
    terminal(successor, path, admission.root_request, admission.root_admission, current[0])
    with pytest.raises(OperationFailure):
        read(successor)
