"""Actual captured native shell fixture; pseudo science, API0 and read-only GPU facts.

Run with the selected checkout's frozen Python and an external evidence directory.
No private server controls are added to the production HTTP adapter.
"""

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn

from tests.integration.workflows.test_captured_native_chain import _task_manifest
from tests.unit.tools.test_workflow_authoring import SOURCE
from tools.candidate_console import CandidateConsole, ConsoleConfig
from tools.candidate_console.app import create_app
from tools.candidate_console.native_chain import NativeChainConsole
from tools.candidate_console.native_chain_models import (
    NativeChainChoice,
    NativeChainLaunchSelection,
)
from tools.candidate_operations import NativeChainOperationRequest, OperationStoreConfig
from tools.native_chain.models import NativeChainDeclaration, NativeChainRunBinding
from tools.workflow_authoring.models import Project


def prepare(directory: Path) -> ConsoleConfig:
    root = Path(__file__).resolve().parents[2]
    inputs, data, runs = (directory / name for name in ("inputs", "data", "runs"))
    for path in (inputs, data, runs):
        path.mkdir()
    envelope = runs / "envelope"
    envelope.mkdir()
    manifest = _task_manifest(root, inputs)
    declaration = NativeChainDeclaration(
        working_directory=root,
        run=NativeChainRunBinding(
            workspace=envelope / "workspace", run_name="browser_pseudo", final_iteration=2
        ),
        chain_args=(
            "--task_composition",
            str(manifest),
            "--data_dir",
            str(data),
            "--llm_config",
            "configs/llm/openai_tiered_pro.json",
            "--is_pseudo_llm",
            "--is_pseudo_training",
            "--max_rounds",
            "1",
            "--max_epochs",
            "1",
            "--attempts_per_round",
            "1",
            "--attempts_per_formal_round",
            "1",
            "--max_proposal_attempts",
            "1",
            "--max_impl_attempts",
            "1",
            "--healthgate_mode",
            "observe_only",
            "--result_authority",
            "diagnostic",
            "--no-runtime_watchdog",
        ),
    )
    source = inputs / "declaration.json"
    source.write_text(declaration.model_dump_json())
    request = directory / "review-request.json"
    request.write_text(
        json.dumps(
            dict(
                source=str(source),
                output=str(directory / "review"),
                read_only=[str(inputs)],
                task_check=dict(timeout_seconds=60),
                input_max_bytes=16777216,
            )
        )
    )
    result = subprocess.run(
        [sys.executable, "-m", "tools.native_chain", "review", "--request", str(request)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    (directory / "capture-review.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("Capture review refused; inspect capture-review.log")
    capture = directory / "review/capture.json"
    devices = tuple(str(p) for p in Path("/dev").glob("nvidia*") if p.is_char_device())
    devices += tuple(str(p) for p in Path("/dev/nvidia-caps").glob("*") if p.is_char_device())
    native = NativeChainOperationRequest(
        capture_path=str(capture),
        capture_sha256=hashlib.sha256(capture.read_bytes()).hexdigest(),
        envelope=str(envelope),
        read_only=(str(inputs), str(data), "/sys"),
        network=False,
        devices=devices,
        environment_names=(),
        timeout_seconds=240,
        input_max_bytes=16777216,
        max_iterations_observed=2,
        max_observation_bytes=1048576,
    )
    token = directory / "token"
    token.write_text(secrets.token_urlsafe(32))
    token.chmod(0o600)
    editor = directory / "editor"
    editor.mkdir()
    editable = editor / "workflow.py"
    editable.write_text(SOURCE)
    recovery = editor / "recovery"
    recovery.mkdir(mode=0o700)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = ConsoleConfig(
        operation_store=OperationStoreConfig(
            state_root=str(directory / "state"),
            preparation_roots=(str(runs),),
            candidate_roots=(str(runs),),
        ),
        port=port,
        browser_origin=f"http://127.0.0.1:{port}",
        auth_token_file=str(token),
        native_chain_choices=(
            NativeChainChoice(
                choice_id="native", label="Offline two-iteration chain", request=native
            ),
        ),
        editor_projects=(
            Project(
                project_id="unrelated",
                project_root=editor,
                source_file=editable,
                recovery_directory=recovery,
            ),
        ),
    )
    (directory / "console.json").write_text(config.model_dump_json())
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--recover", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.monitor or args.recover:
        config = ConsoleConfig.model_validate_json((directory / "console.json").read_bytes())
        config = config.model_copy(
            update={
                "tasks": (),
                "native_chain_choices": (),
                "editor_projects": (),
                "credential_file": None,
            }
        )
    else:
        config = prepare(directory)
    if args.recover:
        selection = NativeChainLaunchSelection.model_validate_json(args.recover.read_bytes())
        handle = NativeChainConsole(CandidateConsole(config)).launch(selection)
        print(handle.model_dump_json(), flush=True)
        return
    print(
        json.dumps(
            dict(origin=config.browser_origin, token=Path(config.auth_token_file).read_text())
        ),
        flush=True,
    )
    uvicorn.run(
        create_app(config),
        host="127.0.0.1",
        port=config.port,
        proxy_headers=False,
        access_log=False,
        log_level="error",
    )


if __name__ == "__main__":
    main()
