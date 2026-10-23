"""Native observational reads: independent sums, bounded evidence and fixed identity."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.candidate_worker import CandidateTokenReadRequest, read_candidate_tokens
from tools.candidate_worker.models import CandidateRunReceipt
from tools.candidate_worker.token_models import CandidateTokenQuality

tokens = importlib.import_module("tools.candidate_worker.tokens")


def native_fixture(prepared, tmp_path):
    workspace = Path(prepared.preview.document.definition.task.workspace)
    control = workspace / "candidate_run"
    control.mkdir(parents=True)
    initial = CandidateRunReceipt(
        run_id="native-id",
        run_name=prepared.run_name,
        workspace=str(workspace),
        declaration_digest=prepared.declaration_digest,
        status="launched",
        node_ids=tuple(n.id for n in prepared.preview.document.definition.nodes),
        selected_constructor_routes=prepared.selected_constructor_routes,
        ledger_path=str(workspace / "token_usage.jsonl"),
        log_path=str(control / "worker.log"),
    )
    (control / "request.json").write_text(prepared.model_dump_json())
    (control / "launch.json").write_text(initial.model_dump_json())
    query = CandidateTokenReadRequest(
        allowed_workspace_root=str(tmp_path),
        workspace=str(workspace),
        expected_run_id=initial.run_id,
    )
    return query, initial, control, workspace / "token_usage.jsonl"


def row(**changes):
    value = dict(
        ts="2026-10-22T10:00:00Z",
        run_id="native-id",
        run_name="candidate",
        label="response",
        provider="openai",
        model="requested",
        served_model="served",
        tokens=dict(prompt=100, completion=20, total=130),
        chars=dict(system=0, user=0, total=0),
    )
    value.update(changes)
    return (json.dumps(value) + "\n").encode()


def test_independent_field_oracle_retry_and_exact_identity_buckets():
    """Collapsing served/provider identity, deriving totals or deduping retries fails."""
    payload = row() + row(tokens=dict(prompt=None, completion=5, total=None)) + row()
    payload += row(
        provider=None, model=None, served_model=None, label="arbitrary-marker", tokens={}
    )
    payload += row(served_model=None, tokens={}) + row(provider="other", tokens=dict(prompt=0))
    payload += row(model="", served_model="", tokens={})
    groups, quality, last = tokens.aggregate(
        payload, run_id="native-id", run_name="candidate", quality=CandidateTokenQuality()
    )
    first = groups[0]
    assert (
        first.response_rows,
        first.reported_input_tokens,
        first.reported_output_tokens,
        first.reported_total_tokens,
    ) == (3, 200, 45, 260)
    assert (first.missing_input_rows, first.missing_output_rows, first.missing_total_rows) == (
        1,
        0,
        1,
    )
    assert len(groups) == 4 and groups[1].served_model is None
    assert groups[1].reported_total_tokens is None and groups[1].response_rows == 1
    assert groups[2].reported_input_tokens == 0
    assert groups[3].requested_model == "" and groups[3].served_model == ""
    assert quality.marker_rows == 1 and not quality.partial
    assert last == "2026-10-22T10:00:00Z"


def test_missing_empty_partial_and_untrusted_evidence(prepared, tmp_path):
    """Unknown evidence cannot become zero; bad rows/timestamps cannot look complete."""
    query, _, _, ledger = native_fixture(prepared, tmp_path)
    assert read_candidate_tokens(query).reason == "usage_unavailable"
    ledger.write_bytes(b"")
    empty = read_candidate_tokens(query)
    assert (
        empty.availability == "available"
        and empty.reason == "no_reported_responses"
        and not empty.groups
    )
    ledger.write_bytes(row(provider=None, model=None, served_model=None, tokens={}))
    marker = read_candidate_tokens(query)
    assert marker.quality.marker_rows == 1 and not marker.groups and not marker.quality.partial
    ledger.write_bytes(
        row()
        + row(run_id="foreign")
        + b"{broken}\n"
        + row(tokens=dict(prompt=-1))
        + row(provider=None)
        + row(ts="naive bad timestamp")
        + row()[:-1]
    )
    result = read_candidate_tokens(query)
    assert result.quality.partial and result.quality.invalid_rows == 4
    assert result.quality.invalid_timestamp_rows == 1 and result.quality.trailing_fragment
    assert result.groups[0].response_rows == 2 and result.groups[0].reported_total_tokens == 260
    assert result.last_valid_usage_at == "2026-10-22T10:00:00Z"
    assert "missing or unrecorded" in result.coverage_note


@pytest.mark.parametrize(
    "target",
    [
        "expected",
        "launch",
        "request",
        "final",
        "symlink_file",
        "symlink_directory",
        "root",
        "mutated_request",
    ],
)
def test_identity_and_fixed_files_refuse(prepared, tmp_path, target):
    """Foreign/corrupt fixed records and symlink paths must refuse before counting."""
    query, initial, control, ledger = native_fixture(prepared, tmp_path)
    ledger.write_bytes(row())
    if target == "expected":
        query = query.model_copy(update={"expected_run_id": "foreign"})
    elif target == "launch":
        (control / "launch.json").write_text(
            initial.model_copy(update={"ledger_path": str(tmp_path / "secret")}).model_dump_json()
        )
    elif target == "request":
        (control / "request.json").write_text(
            prepared.model_copy(update={"run_name": "foreign"}).model_dump_json()
        )
    elif target == "final":
        (control / "receipt.json").write_text(
            initial.model_copy(update={"status": "accepted", "run_id": "foreign"}).model_dump_json()
        )
    elif target == "symlink_file":
        ledger.rename(ledger.with_suffix(".saved"))
        ledger.symlink_to(ledger.with_suffix(".saved"))
    elif target == "symlink_directory":
        control.rename(control.with_name("moved"))
        control.symlink_to(control.with_name("moved"), target_is_directory=True)
    elif target == "root":
        query = query.model_copy(update={"allowed_workspace_root": query.workspace})
    else:
        query = query.model_copy(update={"expected_run_id": 123})
    with pytest.raises((ValueError, OSError)):
        read_candidate_tokens(query)


def test_missing_native_publication_and_read_has_no_effects(prepared, tmp_path):
    """Direct native records need no operation/editor; snapshot does not mutate bytes."""
    query, _, control, ledger = native_fixture(prepared, tmp_path)
    ledger.write_bytes(row())
    before = {p: p.read_bytes() for p in control.parent.rglob("*") if p.is_file()}
    assert read_candidate_tokens(query).groups[0].reported_total_tokens == 130
    assert before == {p: p.read_bytes() for p in control.parent.rglob("*") if p.is_file()}
    (control / "launch.json").unlink()
    assert read_candidate_tokens(query).reason == "native_evidence_unavailable"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from tools.candidate_worker import read_candidate_tokens; assert not any(k.startswith(('openai', 'google.genai', 'nodes.ml_', 'ml_models.', 'workflows.task_composition', 'tools.candidate_operations')) for k in sys.modules)",
        ],
        check=True,
        timeout=20,
    )


def test_caps_exclude_rows_and_preserve_known_sums(tmp_path):
    """Caps must label incomplete evidence and never truncate identities into collisions."""
    payload = row() + row(model="é" * 129) + row(extra={"huge": "x" * 65536})
    payload += b"".join(row(model=str(i)) for i in range(256))
    groups, quality, _ = tokens.aggregate(
        payload, run_id="native-id", run_name="candidate", quality=CandidateTokenQuality()
    )
    assert len(groups) == 256 and quality.partial
    assert (
        quality.excluded_identity_rows == 1
        and quality.oversized_rows == 1
        and quality.excluded_group_rows == 1
    )
    marker = row(provider=None, model=None, served_model=None, tokens={})
    groups, quality, _ = tokens.aggregate(
        marker * 10000 + row(),
        run_id="native-id",
        run_name="candidate",
        quality=CandidateTokenQuality(),
    )
    assert not groups and quality.truncated_rows and quality.marker_rows == 10000
    ledger = tmp_path / "ledger"
    ledger.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    payload, quality = tokens.ledger_prefix(ledger)
    assert len(payload) == 4 * 1024 * 1024 and quality.truncated_bytes


@pytest.mark.parametrize("change", ["append", "shrink"])
def test_prefix_capture_ignores_later_append_and_detects_shrink(tmp_path, monkeypatch, change):
    """Actual append after fstat belongs to next read; observed shrink is partial."""
    path = tmp_path / "ledger"
    first = row()
    path.write_bytes(first)
    original = os.fstat
    calls = 0

    def mutate(fd):
        nonlocal calls
        metadata = original(fd)
        calls += 1
        if calls == 2:  # open_fixed regular-file check precedes size capture
            with path.open("ab" if change == "append" else "wb") as stream:
                stream.write(first if change == "append" else b"")
        return metadata

    monkeypatch.setattr(tokens.os, "fstat", mutate)
    payload, quality = tokens.ledger_prefix(path)
    assert payload == (first if change == "append" else b"")
    assert quality.short_read == (change == "shrink")
    if change == "append":
        assert tokens.ledger_prefix(path)[0] == first + first


def test_extreme_timestamp_and_invalid_unicode_are_partial_evidence():
    """Extreme UTC conversion cannot crash arithmetic; invalid UTF-8 identity is excluded."""
    groups, quality, last = tokens.aggregate(
        row(ts="0001-01-01T00:00:00+23:00") + row(model="\ud800"),
        run_id="native-id",
        run_name="candidate",
        quality=CandidateTokenQuality(),
    )
    assert groups[0].reported_total_tokens == 130 and last is None
    assert quality.partial and quality.invalid_timestamp_rows == 1 and quality.invalid_rows == 1
