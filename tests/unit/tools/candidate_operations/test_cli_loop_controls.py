"""CLI routing for authored-loop Stop, Pause and Resume; owners are doubles here.

The owners' admission and lifecycle semantics are tested beside the owners. These tests
pin only what the CLI adds: which owner each subcommand reaches, the saved Resume file
and the bounded failure output.
"""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from tools.candidate_operations import __main__ as cli
from tools.candidate_operations.models import (
    CandidateLoopResumeOperation,
    OperationFailure,
    OperationStoreConfig,
)

DIGEST = "c" * 64
SECRET = "sk-cli-loop-secret-value"


@pytest.fixture
def store(tmp_path, monkeypatch):
    config = OperationStoreConfig(
        state_root=str(tmp_path / "state"),
        preparation_roots=(str(tmp_path),),
        candidate_roots=(str(tmp_path),),
    )
    path = tmp_path / "store.json"
    path.write_text(config.model_dump_json())
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    return config, path


def invoke(monkeypatch, capsys, *argv):
    monkeypatch.setattr("sys.argv", ["operation", *argv])
    status = cli.main()
    out, err = capsys.readouterr()
    assert SECRET not in out + err
    return status, out, err


def recorder(calls, name, result):
    def owner(config, operation_id):
        calls.append((name, config, operation_id))
        return result

    return owner


@pytest.mark.parametrize(
    ("command", "owner"),
    [
        ("stop-loop", "request_loop_stop"),
        ("pause-loop", "request_loop_pause"),
        ("review-loop-resume", "review_loop_resume"),
        ("cancel", "request_cancel"),
    ],
)
def test_loop_command_reaches_its_own_owner(store, monkeypatch, capsys, command, owner):
    """Fails if a subcommand is routed to another control (e.g. pause-loop writes Stop,
    which is run-wide and terminal; cancel reaching a boundary control would let a paid run
    continue) or to the native-chain review."""
    config, path = store
    calls = []
    for name in ("request_loop_stop", "request_loop_pause", "review_loop_resume", "request_cancel"):
        result = SimpleNamespace(model_dump_json=lambda name=name: json.dumps({"owner": name}))
        monkeypatch.setattr(cli, name, recorder(calls, name, result))
    monkeypatch.setattr(cli, "review_native_chain_resume", recorder(calls, "native", None))
    operation_id = uuid4()
    status, out, _ = invoke(
        monkeypatch,
        capsys,
        command,
        "--store-config",
        str(path),
        "--operation-id",
        str(operation_id),
    )
    assert status == 0
    assert calls == [(owner, config, operation_id)]
    assert json.loads(out) == {"owner": owner}


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (
            OperationFailure("not_running", "candidate is terminal or not confirmed running"),
            {"code": "not_running", "message": "candidate is terminal or not confirmed running"},
        ),
        (
            FileNotFoundError(f"/private/{SECRET}/record.json"),
            {
                "code": "invalid_input_or_record",
                "message": "cannot validate or read the selected operation input/record",
            },
        ),
    ],
)
def test_loop_refusal_is_one_json_error_without_diagnostics(
    store, monkeypatch, capsys, raised, expected
):
    """Fails if a typed refusal exits 0, prints a traceback, or leaks a raw OS diagnostic."""
    _, path = store

    def refuse(config, operation_id):
        raise raised

    monkeypatch.setattr(cli, "request_loop_pause", refuse)
    status, out, err = invoke(
        monkeypatch,
        capsys,
        "pause-loop",
        "--store-config",
        str(path),
        "--operation-id",
        str(uuid4()),
    )
    assert (status, out) == (2, "")
    assert json.loads(err) == expected


def test_saved_resume_is_written_once_and_submitted_unchanged(store, tmp_path, monkeypatch, capsys):
    """Fails if the request is not bound to the reviewed digest, if a rerun overwrites
    the saved request (a new request ID could no longer reconnect a lost response), or if
    `submit` does not pass the saved resume and the shell environment to the owner."""
    config, path = store
    predecessor = uuid4()
    reviews = []

    def review(config_arg, operation_id):
        reviews.append((config_arg, operation_id))
        return SimpleNamespace(receipt_digest=DIGEST)

    monkeypatch.setattr(cli, "review_loop_resume", review)
    output = tmp_path / "loop-resume.json"
    args = ("--store-config", str(path), "--operation-id", str(predecessor))
    status, out, _ = invoke(
        monkeypatch, capsys, "write-loop-resume", *args, "--output", str(output)
    )
    assert status == 0
    saved = CandidateLoopResumeOperation.model_validate_json(output.read_bytes())
    assert saved.request.predecessor_operation_id == predecessor
    assert saved.request.expected_receipt_digest == DIGEST
    assert CandidateLoopResumeOperation.model_validate_json(out) == saved
    assert reviews == [(config, predecessor)]

    original = output.read_bytes()
    status, out, err = invoke(
        monkeypatch, capsys, "write-loop-resume", *args, "--output", str(output)
    )
    assert (status, out, json.loads(err)["code"]) == (2, "", "output_exists")
    assert output.read_bytes() == original

    submitted = []

    def submit(config_arg, submission, *, launch_environment, host):
        # No --host-ledger: the CLI selects the serial default (no host ledger).
        assert host is None
        submitted.append((config_arg, submission, launch_environment.get("OPENAI_API_KEY")))
        return SimpleNamespace(model_dump_json=lambda: json.dumps({"submitted": True}))

    monkeypatch.setattr(cli, "submit_operation", submit)
    status, _, _ = invoke(
        monkeypatch, capsys, "submit", "--store-config", str(path), "--request", str(output)
    )
    assert status == 0
    assert submitted == [(config, saved, SECRET)]


def test_refused_review_writes_no_resume_request(store, tmp_path, monkeypatch, capsys):
    """Fails if a request file is saved for a segment the review refused (for example a
    stopped or condition-completed loop), which a later `submit` would then attempt."""
    _, path = store

    def refuse(config, operation_id):
        raise OperationFailure("loop_resume", "loop is terminal")

    monkeypatch.setattr(cli, "review_loop_resume", refuse)
    output = tmp_path / "loop-resume.json"
    status, _, err = invoke(
        monkeypatch,
        capsys,
        "write-loop-resume",
        "--store-config",
        str(path),
        "--operation-id",
        str(UUID(int=7)),
        "--output",
        str(output),
    )
    assert (status, json.loads(err)["code"]) == (2, "loop_resume")
    assert not output.exists()


def test_advice_file_is_saved_in_the_resume_request_and_invalid_advice_writes_nothing(
    store, tmp_path, monkeypatch, capsys
):
    """Fails if ``--advice-file`` text does not reach the saved request (trimmed, so a
    resubmission is byte-identical), or if invalid advice is echoed, reaches review, or
    leaves a request file behind."""
    _, path = store
    reviews = []

    def review(config_arg, operation_id):
        reviews.append(operation_id)
        return SimpleNamespace(receipt_digest=DIGEST)

    monkeypatch.setattr(cli, "review_loop_resume", review)
    args = ("--store-config", str(path), "--operation-id", str(UUID(int=7)))
    advice = tmp_path / "advice.txt"
    advice.write_text("  Try a smaller hidden width.\n")
    output = tmp_path / "advised.json"
    status, _, _ = invoke(
        monkeypatch,
        capsys,
        "write-loop-resume",
        *args,
        "--output",
        str(output),
        "--advice-file",
        str(advice),
    )
    assert status == 0
    saved = CandidateLoopResumeOperation.model_validate_json(output.read_bytes())
    assert saved.request.operator_advice == "Try a smaller hidden width."
    # A CRLF (Windows) file binds the same text as its LF form.
    advice.write_bytes(b"First line.\r\nSecond line.\r\n")
    crlf = tmp_path / "crlf.json"
    status, _, _ = invoke(
        monkeypatch,
        capsys,
        "write-loop-resume",
        *args,
        "--output",
        str(crlf),
        "--advice-file",
        str(advice),
    )
    assert status == 0
    saved = CandidateLoopResumeOperation.model_validate_json(crlf.read_bytes())
    assert saved.request.operator_advice == "First line.\nSecond line."
    marker = "secret\x1b[31m control"
    for invalid in (marker.encode(), b"   ", b"\xff\xfe", b"x" * 4001, b"secret\rcr"):
        advice.write_bytes(invalid)
        refused = tmp_path / "refused.json"
        status, out, err = invoke(
            monkeypatch,
            capsys,
            "write-loop-resume",
            *args,
            "--output",
            str(refused),
            "--advice-file",
            str(advice),
        )
        assert (status, out, json.loads(err)["code"]) == (2, "", "invalid_input_or_record")
        assert "secret" not in err and not refused.exists()
    assert len(reviews) == 2
