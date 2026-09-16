"""Security and certification regressions for untrusted generated analysis."""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import pytest

from agent.data_analysis.analysis_code_sandbox import (
    AnalysisCodeSandbox,
    AnalysisCodeSandboxError,
    AnalysisCodeSandboxUnavailable,
    SandboxCapabilityReceipt,
)
from agent.data_analysis.generated_programs import (
    GeneratedProgramDraft,
    persist_generated_program,
)
from agent.schemas.data_analysis.action_identity import (
    GeneratedProgramGenerationProvenance,
)
from core.runtime_control.process_group import process_group_alive


def _persist_program(tmp_path: Path, source: str, *, keys: tuple[str, ...]):
    measurements = [
        {
            "result_key": key,
            "description": key.replace("_", " "),
            "value_type": "boolean",
        }
        for key in keys
    ]
    draft = GeneratedProgramDraft(
        program_id="sandbox-probe",
        question_ids=("q1",),
        source_code=source,
        input_slots=(
            {
                "slot_id": "values",
                "description": "Authorized values",
                "accepted_asset_types": ("dataset",),
                "accepted_view_formats": ("siderius.numeric-array.v1",),
                "required_information": ({"information_class": "data"},),
            },
        ),
        expected_measurements=measurements,
        resource_request={
            "wall_time_s": 2.0,
            "max_host_memory_gb": 1.0,
            "max_artifact_count": 0,
            "max_artifact_bytes": 0,
        },
        determinism="deterministic",
        seed=7,
        rationale="Exercise the sandbox boundary.",
    )
    provenance = GeneratedProgramGenerationProvenance(
        provider="test",
        model_id="fake",
        llm_config_sha256="1" * 64,
        generation_prompt_sha256="2" * 64,
        originating_request_id="request",
        question_ids=("q1",),
    )
    program, identity = persist_generated_program(
        root=tmp_path,
        draft=draft,
        generation_provenance=provenance,
    )
    source_path = tmp_path / program.source_ref.logical_ref
    return program, identity, source_path


def _materialization(tmp_path: Path) -> Path:
    buffer = io.BytesIO()
    np.savez(
        buffer,
        example_ids=np.asarray(["a", "b"]),
        information__data=np.asarray([1.0, 2.0]),
    )
    path = tmp_path / "authorized.npz"
    path.write_bytes(buffer.getvalue())
    return path


def _execute(tmp_path: Path, source: str, *, keys: tuple[str, ...]):
    sandbox = AnalysisCodeSandbox()
    capability = sandbox.probe()
    if not capability.available:
        pytest.skip(f"host cannot enforce sandbox: {capability.reason}")
    program, _identity, source_path = _persist_program(tmp_path, source, keys=keys)
    materialization = _materialization(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    return sandbox.execute(
        program=program,
        source_path=source_path,
        materialization_paths={"values": str(materialization)},
        materialization_descriptors={
            "values": {
                "binding_id": "values",
                "format_id": "siderius.numeric-array.v1",
            }
        },
        parameters={},
        output_directory=output,
        control_directory=tmp_path / "control",
        timeout_s=2.0,
        max_host_memory_gb=1.0,
    )


@pytest.mark.allow_real_subprocess
def test_sandbox_withholds_credentials_host_paths_and_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches credential, workspace, unauthorized-file, or network leakage."""

    secret_path = tmp_path / "not-authorized"
    secret_path.write_text("private", encoding="utf-8")
    monkeypatch.setenv("SIDERIUS_GENERATED_CODE_SECRET", "must-not-leak")
    checkout = Path(__file__).resolve().parents[4]
    source = f"""import os
import socket

def analyze(inputs, parameters, output_directory):
    credential_hidden = os.environ.get('SIDERIUS_GENERATED_CODE_SECRET') is None
    repo_hidden = not os.path.exists({str(checkout)!r})
    unauthorized_hidden = not os.path.exists({str(secret_path)!r})
    try:
        open({str(checkout / "generated-code-write")!r}, 'w').write('bad')
    except OSError:
        repo_write_denied = True
    else:
        repo_write_denied = False
    try:
        open({str(secret_path)!r}).read()
    except OSError:
        unauthorized_read_denied = True
    else:
        unauthorized_read_denied = False
    try:
        socket.socket()
    except PermissionError:
        network_denied = True
    else:
        network_denied = False
    values_readable = float(inputs['values']['arrays']['information__data'][1]) == 2.0
    results = []
    for key, value in (
        ('credential_hidden', credential_hidden),
        ('repo_hidden', repo_hidden),
        ('unauthorized_hidden', unauthorized_hidden),
        ('repo_write_denied', repo_write_denied),
        ('unauthorized_read_denied', unauthorized_read_denied),
        ('network_denied', network_denied),
        ('authorized_input_readable', values_readable),
    ):
        results.append({{
            'result_key': key, 'value': value, 'unit': None,
            'description': key.replace('_', ' '),
        }})
    return {{
        'summary': 'Sandbox isolation checked.',
        'quantitative_results': results,
        'produced_artifacts': [],
        'analysis_usage': {{'effective_count': 2, 'dropped_count': 0, 'drop_reasons': []}},
        'warnings': [],
    }}
"""
    keys = (
        "credential_hidden",
        "repo_hidden",
        "unauthorized_hidden",
        "repo_write_denied",
        "unauthorized_read_denied",
        "network_denied",
        "authorized_input_readable",
    )

    receipt = _execute(tmp_path, source, keys=keys)

    assert receipt.status == "completed"
    assert receipt.payload is not None
    assert {item.result_key: item.value for item in receipt.payload.quantitative_results} == {
        key: True for key in keys
    }


@pytest.mark.allow_real_subprocess
def test_timeout_kills_generated_process_group(tmp_path: Path) -> None:
    """Catches a generated child process surviving the invocation deadline."""

    source = """import subprocess
import sys
import time

def analyze(inputs, parameters, output_directory):
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    time.sleep(60)
    return {'summary': 'unreachable'}
"""
    sandbox = AnalysisCodeSandbox()
    capability = sandbox.probe()
    if not capability.available:
        pytest.skip(f"host cannot enforce sandbox: {capability.reason}")
    program, _identity, source_path = _persist_program(tmp_path, source, keys=("unused",))
    materialization = _materialization(tmp_path)
    output = tmp_path / "output"
    output.mkdir()

    receipt = sandbox.execute(
        program=program,
        source_path=source_path,
        materialization_paths={"values": str(materialization)},
        materialization_descriptors={"values": {"binding_id": "values"}},
        parameters={},
        output_directory=output,
        control_directory=tmp_path / "control",
        timeout_s=0.3,
        max_host_memory_gb=1.0,
    )

    assert receipt.status == "timed_out"
    with pytest.raises(ProcessLookupError):
        os.kill(receipt.worker_pid, 0)


@pytest.mark.allow_real_subprocess
def test_successful_parent_cannot_leave_a_generated_child_running(tmp_path: Path) -> None:
    """Catches a quick-returning generated parent orphaning its process-tree child."""

    source = """import subprocess
import sys

def analyze(inputs, parameters, output_directory):
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    return {
        'summary': 'Parent returned.',
        'quantitative_results': [{
            'result_key': 'parent_returned', 'value': True, 'unit': None,
            'description': 'parent returned',
        }],
        'produced_artifacts': [],
        'analysis_usage': {'effective_count': 2, 'dropped_count': 0, 'drop_reasons': []},
        'warnings': [],
    }
"""

    receipt = _execute(tmp_path, source, keys=("parent_returned",))

    assert receipt.status == "completed"
    assert not process_group_alive(receipt.worker_pid)


@pytest.mark.allow_real_subprocess
def test_generated_output_tree_is_bounded_before_artifact_certification(tmp_path: Path) -> None:
    """Catches untrusted code filling host storage with undeclared output files."""

    source = """from pathlib import Path
import time

def analyze(inputs, parameters, output_directory):
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=True)
    for index in range(40):
        (root / f'junk-{index}').write_bytes(b'x')
    time.sleep(60)
    return {'summary': 'unreachable'}
"""

    receipt = _execute(tmp_path, source, keys=("unused",))

    assert receipt.status == "output_limit_exceeded"
    assert receipt.payload is None


def test_sandbox_unavailable_fails_closed_without_subprocess_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches missing isolation silently falling back to an ordinary subprocess."""

    source = "def analyze(inputs, parameters, output_directory):\n    return {'summary': 'x'}\n"
    program, _identity, source_path = _persist_program(tmp_path, source, keys=("unused",))
    sandbox = AnalysisCodeSandbox()
    monkeypatch.setattr(
        sandbox,
        "probe",
        lambda: SandboxCapabilityReceipt(
            available=False,
            protocol_id="siderius.generated-analysis-sandbox.v1",
            bubblewrap_path=None,
            unshare_path=None,
            reason="test isolation unavailable",
        ),
    )
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(AnalysisCodeSandboxUnavailable, match="test isolation unavailable"):
        sandbox.execute(
            program=program,
            source_path=source_path,
            materialization_paths={},
            materialization_descriptors={},
            parameters={},
            output_directory=output,
            control_directory=tmp_path / "control",
            timeout_s=1.0,
            max_host_memory_gb=1.0,
        )


def test_source_mutation_after_planning_is_refused_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches final plans executing bytes different from their persisted identity."""

    source = "def analyze(inputs, parameters, output_directory):\n    return {'summary': 'x'}\n"
    program, _identity, source_path = _persist_program(tmp_path, source, keys=("unused",))
    source_path.write_text(source + "# mutation\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()

    sandbox = AnalysisCodeSandbox()
    monkeypatch.setattr(
        sandbox,
        "probe",
        lambda: SandboxCapabilityReceipt(
            available=True,
            protocol_id="siderius.generated-analysis-sandbox.v1",
            bubblewrap_path="/not-executed/bwrap",
            unshare_path="/not-executed/unshare",
        ),
    )
    with pytest.raises(AnalysisCodeSandboxError, match=r"byte size|digest"):
        sandbox.execute(
            program=program,
            source_path=source_path,
            materialization_paths={},
            materialization_descriptors={},
            parameters={},
            output_directory=output,
            control_directory=tmp_path / "control",
            timeout_s=1.0,
            max_host_memory_gb=1.0,
        )


def test_malformed_payload_cannot_be_mistaken_for_certified_evidence(tmp_path: Path) -> None:
    """Catches arbitrary generated return values entering report synthesis."""

    source = """def analyze(inputs, parameters, output_directory):
    return {'summary': {'not': 'a string'}}
"""
    receipt = _execute(tmp_path, source, keys=("unused",))

    assert receipt.status == "failed"
    assert receipt.failure_type == "invalid_generated_payload"
    assert receipt.payload is None
