"""Security and certification regressions for untrusted generated analysis."""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
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

#: Seed a non-deterministic program executes under in these tests (issue #983).
PROGRAM_SEED = 13


def _persist_program(
    tmp_path: Path,
    source: str,
    *,
    keys: tuple[str, ...],
    determinism: str = "deterministic",
    seed: int = 7,
):
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
        determinism=determinism,
        seed=seed if determinism == "deterministic" else None,
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


def _execute(
    tmp_path: Path, source: str, *, keys: tuple[str, ...], determinism: str = "deterministic"
):
    sandbox = AnalysisCodeSandbox()
    capability = sandbox.probe()
    if not capability.available:
        if os.environ.get("REQUIRE_ANALYSIS_SANDBOX") == "1":
            pytest.fail(f"required sandbox qualification failed: {capability.reason}")
        pytest.skip(f"host cannot enforce sandbox: {capability.reason}")
    program, _identity, source_path = _persist_program(
        tmp_path, source, keys=keys, determinism=determinism
    )
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
        program_seed=PROGRAM_SEED,
    )


@pytest.mark.parametrize(
    "missing,expected",
    [
        ({"bwrap"}, "bwrap (bubblewrap)"),
        ({"unshare"}, "unshare (util-linux)"),
        ({"bwrap", "unshare"}, "bwrap (bubblewrap), unshare (util-linux)"),
    ],
)
def test_probe_names_only_missing_tools(monkeypatch, missing, expected):
    monkeypatch.setattr(
        "agent.data_analysis.analysis_code_sandbox.shutil.which",
        lambda name: None if name in missing else f"/usr/bin/{name}",
    )
    capability = AnalysisCodeSandbox().probe()
    assert not capability.available
    assert capability.reason == "Missing required generated-analysis executable(s): " + expected


def test_required_qualification_cannot_skip_unavailable_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIRE_ANALYSIS_SANDBOX", "1")
    monkeypatch.setattr("agent.data_analysis.analysis_code_sandbox.shutil.which", lambda _: None)
    with pytest.raises(pytest.fail.Exception, match="required sandbox qualification failed"):
        _execute(tmp_path, "", keys=())


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
        network_socket = socket.socket()
    except OSError:
        network_denied = True
    else:
        network_socket.settimeout(0.25)
        try:
            network_socket.connect(('198.51.100.1', 9))
        except OSError:
            network_denied = True
        else:
            network_denied = False
        finally:
            network_socket.close()
    values_readable = float(inputs['values']['arrays']['information__data'][1]) == 2.0
    results = []
    for key, value in (
        ('credential_hidden', credential_hidden),
        ('repo_hidden', repo_hidden),
        ('unauthorized_hidden', unauthorized_hidden),
        ('repo_write_denied', repo_write_denied),
        ('unauthorized_read_denied', unauthorized_read_denied),
        ('external_network_denied', network_denied),
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
        "external_network_denied",
        "authorized_input_readable",
    )

    receipt = _execute(tmp_path, source, keys=keys)

    assert receipt.status == "completed"
    assert receipt.payload is not None
    assert {item.result_key: item.value for item in receipt.payload.quantitative_results} == {
        key: True for key in keys
    }


@pytest.mark.allow_real_subprocess
def test_sandbox_output_directory_matches_declared_artifact_paths(tmp_path: Path) -> None:
    """Defect: the runner prepended artifacts twice and made valid outputs uncertifiable."""

    source = """from pathlib import Path

def analyze(inputs, parameters, output_directory):
    artifact = Path(output_directory) / 'artifacts' / 'measurement.txt'
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('measured', encoding='utf-8')
    return {
        'summary': 'Produced one bounded artifact.',
        'quantitative_results': [{
            'result_key': 'artifact_written', 'value': True, 'unit': None,
            'description': 'Artifact was written below the sandbox output root.',
        }],
        'produced_artifacts': [{
            'artifact_type': 'table', 'logical_name': 'measurement',
            'media_type': 'text/plain', 'relative_path': 'artifacts/measurement.txt',
            'description': 'Bounded generated measurement artifact.',
        }],
        'analysis_usage': {'effective_count': 2, 'dropped_count': 0, 'drop_reasons': []},
        'warnings': [],
    }
"""
    receipt = _execute(tmp_path, source, keys=("artifact_written",))

    assert receipt.status == "completed"
    assert receipt.payload is not None
    assert receipt.payload.produced_artifacts[0].relative_path == "artifacts/measurement.txt"
    assert (tmp_path / "output" / "artifacts" / "measurement.txt").read_text() == "measured"


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
        if os.environ.get("REQUIRE_ANALYSIS_SANDBOX") == "1":
            pytest.fail(f"required sandbox qualification failed: {capability.reason}")
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
        program_seed=PROGRAM_SEED,
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
        lambda **_: SandboxCapabilityReceipt(
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
            program_seed=PROGRAM_SEED,
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
        lambda **_: SandboxCapabilityReceipt(
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
            program_seed=PROGRAM_SEED,
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


#: random.random() and np.random.rand() right after seeding with 13 and 7.
SEEDED_DRAWS = {
    13: (0.2590084917154736, 0.7777024105738202),
    7: (0.32383276483316237, 0.07630828937395717),
}


@pytest.mark.allow_real_subprocess
@pytest.mark.parametrize(("determinism", "seed"), [("nondeterministic", 13), ("deterministic", 7)])
def test_generated_program_always_runs_seeded(tmp_path: Path, determinism, seed) -> None:
    """Issue #983: fails if a program declared nondeterministic runs on entropy
    instead of the run-derived program seed (13 here), or if a deterministic
    program's own declared seed (7) is overridden."""
    python_draw, numpy_draw = SEEDED_DRAWS[seed]
    source = f"""import random
import numpy as np

def analyze(inputs, parameters, output_directory):
    results = []
    for key, value in (
        ('python_seeded', random.random() == {python_draw!r}),
        ('numpy_seeded', float(np.random.rand()) == {numpy_draw!r}),
    ):
        results.append({{
            'result_key': key, 'value': value, 'unit': None,
            'description': key.replace('_', ' '),
        }})
    return {{
        'summary': 'Seeding checked.',
        'quantitative_results': results,
        'produced_artifacts': [],
        'analysis_usage': {{'effective_count': 2, 'dropped_count': 0, 'drop_reasons': []}},
        'warnings': [],
    }}
"""
    receipt = _execute(
        tmp_path, source, keys=("python_seeded", "numpy_seeded"), determinism=determinism
    )
    assert receipt.status == "completed", receipt.failure_message
    assert receipt.payload is not None
    assert {r.result_key: r.value for r in receipt.payload.quantitative_results} == {
        "python_seeded": True,
        "numpy_seeded": True,
    }


#: Stands in for unshare+bwrap where the host forbids user namespaces. It runs
#: the real ``probe()``/``execute()`` supervision: a capability probe (the
#: command carries ``-c``) sleeps, then writes the probe file through its
#: ``--bind <dir> /output`` mount; an execution becomes the controlled child.
_ISOLATION_STAND_IN = """import os, signal, sys, time
from pathlib import Path

args = sys.argv[1:]
cut = args.index("--")
options, payload = args[:cut], args[cut + 1:]
if "-c" in payload:
    time.sleep({probe_delay_s!r})
    Path(options[options.index("/output") - 1], "probe").write_text("ok")
    raise SystemExit(0)
if {ignores_sigterm!r}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
os.execv({sleep!r}, [{sleep!r}, "60"])
"""


def _stand_in_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    probe_delay_s: float,
    ignores_sigterm: bool = False,
) -> AnalysisCodeSandbox:
    import shutil
    import sys

    sleep = shutil.which("sleep")
    assert sleep is not None
    stand_in = tmp_path / "isolation_stand_in.py"
    stand_in.write_text(
        _ISOLATION_STAND_IN.format(
            probe_delay_s=probe_delay_s, ignores_sigterm=ignores_sigterm, sleep=sleep
        )
    )
    sandbox = AnalysisCodeSandbox()
    # probe() checks that both tools resolve before it launches the command.
    monkeypatch.setattr(sandbox, "_bubblewrap", "bwrap-stand-in")
    monkeypatch.setattr(sandbox, "_unshare", "unshare-stand-in")
    monkeypatch.setattr(sandbox, "_base_command", lambda: [sys.executable, str(stand_in)])
    return sandbox


def _execute_stand_in(sandbox: AnalysisCodeSandbox, tmp_path: Path, *, timeout_s: float):
    program, _identity, source_path = _persist_program(
        tmp_path, "def analyze(inputs, parameters, output_directory):\n    pass\n", keys=("x",)
    )
    output = tmp_path / "output"
    output.mkdir()
    return sandbox.execute(
        program=program,
        source_path=source_path,
        materialization_paths={},
        materialization_descriptors={},
        parameters={},
        output_directory=output,
        control_directory=tmp_path / "control",
        timeout_s=timeout_s,
        max_host_memory_gb=1.0,
        program_seed=PROGRAM_SEED,
    )


@pytest.mark.allow_real_subprocess
@pytest.mark.parametrize(("ignores_sigterm", "bound_s"), [(False, 0.75), (True, 1.75)])
def test_generated_program_stops_at_the_continuing_allocation_within_the_termination_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ignores_sigterm: bool,
    bound_s: float,
) -> None:
    """#1447: probe, request publication and SIGTERM reaping are charged to the allocation.

    The caller passes ``min(per_skill_timeout_s, remaining)`` before the
    probe. A 0.5 s probe plus a 0.5 s publication stall, followed by the full
    timeout from launch, or the 1 s grace waited out on a zombie leader,
    overrun expiry by about 1-2 s. Enforcement leaves only the poll interval,
    or the SIGTERM grace for a child that ignores SIGTERM.
    """
    from agent.data_analysis import analysis_code_sandbox as module
    from core.execution_deadline import execution_deadline

    sandbox = _stand_in_sandbox(
        tmp_path, monkeypatch, probe_delay_s=0.5, ignores_sigterm=ignores_sigterm
    )
    publish = module.publish_bytes_write_once
    published_at: list[float] = []

    def stalled_publish(path: str, payload: bytes) -> None:
        publish(path, payload)
        time.sleep(0.5)
        published_at.append(time.monotonic())

    monkeypatch.setattr(module, "publish_bytes_write_once", stalled_publish)
    with execution_deadline(1.5) as allocation:
        receipt = _execute_stand_in(sandbox, tmp_path, timeout_s=1.5)
        overrun_s = time.monotonic() - max(allocation.expires_at, *published_at)

    assert receipt.status == "timed_out"
    assert overrun_s < bound_s
    assert receipt.worker_pid is not None
    assert not process_group_alive(receipt.worker_pid)


@pytest.mark.allow_real_subprocess
def test_capability_probe_cannot_run_past_the_continuing_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#1447: a probe that outlives the allocation is cut at expiry, not at 10 s.

    The timeout is reported as ``timed_out`` without launching generated code;
    a probe cut by the allocation is not evidence that isolation is missing.
    """
    from core.execution_deadline import execution_deadline

    sandbox = _stand_in_sandbox(tmp_path, monkeypatch, probe_delay_s=5.0)
    with execution_deadline(1.0) as allocation:
        receipt = _execute_stand_in(sandbox, tmp_path, timeout_s=1.0)
        overrun_s = time.monotonic() - allocation.expires_at

    assert overrun_s < 0.5
    assert receipt.status == "timed_out"
    assert receipt.worker_pid is None
    assert not (tmp_path / "control" / "request.json").exists()
