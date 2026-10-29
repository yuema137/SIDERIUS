"""Real B1 captures and B3 HTTP/native CPU lifecycle; only provider replies are fake."""

import argparse
import json
import os
import time
from pathlib import Path
from uuid import UUID, uuid4

import uvicorn

from tests.browser.reusable_provider import provider
from tests.unit.tools.candidate_console.conftest import console_config
from tests.unit.tools.candidate_prepare.conftest import selection
from tests.unit.tools.candidate_prepare.test_reusable_preparation import reusable
from tools.candidate_console.app import create_app
from tools.candidate_console.models import ConsoleConfig
from tools.candidate_console.reusable_candidate import ReusableCandidate
from tools.candidate_console.reusable_models import ReusableCaptureChoice, ReusableCaptureLaunch
from tools.candidate_console.service import CandidateConsole
from tools.candidate_operations import read_operation
from tools.candidate_operations.read import releasable
from tools.candidate_prepare import prepare_reusable_candidate
from tools.workflow_authoring.models import Project


def setup(
    root: Path,
    origin: str,
    endpoint: str,
    captures_count: int = 3,
    training: bool = False,
    families: bool = False,
    literature: bool = False,
    host_ledger: bool = False,
) -> None:
    selected = selection.__wrapped__(root)
    config = console_config.__wrapped__(selected, root)
    # Fail closed both at effective SDK URL and proxy transport. This provider
    # neither forwards absolute URLs nor implements CONNECT.
    environment = {
        "OPENAI_API_KEY": "offline-not-a-secret",
        "OPENAI_BASE_URL": endpoint,
        "HTTP_PROXY": endpoint.removesuffix("/v1"),
        "HTTPS_PROXY": endpoint.removesuffix("/v1"),
        "ALL_PROXY": endpoint.removesuffix("/v1"),
        "NO_PROXY": "127.0.0.1,localhost",
    }
    os.environ.update(environment)
    from agent.llm_bridge import LLMBridge

    for model in ("offline-proposal", "offline-implement", "offline-review"):
        bridge = LLMBridge(provider="openai", model_id=model, max_retries=1)
        assert str(bridge.client.base_url) == endpoint + "/"
        bridge.client.close()
    Path(selected.llm_config_file).write_text(
        json.dumps(
            {
                "propose": {
                    stage: {"provider": "openai", "model_id": "offline-proposal", "max_retries": 1}
                    for stage in ("comparison", "reasoning", "proposing")
                },
                "implement": {
                    "provider": "openai",
                    "model_id": "offline-implement",
                    "max_retries": 1,
                },
                "validate": {"provider": "openai", "model_id": "offline-review", "max_retries": 1},
            }
        )
    )
    private = root / "credentials.json"
    private.write_text(json.dumps(environment))
    private.chmod(0o600)
    request = reusable.__wrapped__(selected).model_copy(
        update={
            "candidate_network": True,
            "candidate_environment_names": tuple(environment),
        }
    )
    if families:
        from tests.helpers.reusable_fanout import reusable_families

        request = reusable_families(request)
    if literature:
        from tests.helpers.reusable_literature import reusable_literature

        request = reusable_literature(
            request,
            {
                "dynamic_search": {"enabled": False},
                "findings_verbosity": 0,
                "synthesis": {"transfer_tolerance": "strict"},
            },
        )
        llm_path = Path(request.llm_config_file)
        llm_path.write_text(llm_path.read_text().replace("literature-test", "offline-literature"))
    if training:
        from tests.unit.tools.candidate_prepare.test_reusable_training import add_training

        request = add_training(request)
        (root / "training-fixture").touch()
    (root / "recovery").mkdir(mode=0o700)
    project = Project(
        project_id="capture",
        project_root=root,
        source_file=Path(request.source_path),
        recovery_directory=root / "recovery",
    )
    captures = []
    for _ in range(captures_count):
        current = request.model_copy(update={"run_id": uuid4()})
        prepared = prepare_reusable_candidate(current)
        assert prepared.status == "prepared", prepared.error
        captures.append(
            {
                "run_id": str(current.run_id),
                "envelope": prepared.envelope,
                "workspace": str(Path(prepared.envelope) / "workspace"),
            }
        )
    store = config.operation_store.model_copy(
        update={
            "preparation_roots": (*config.operation_store.preparation_roots, request.runs_root),
            "candidate_roots": (*config.operation_store.candidate_roots, request.runs_root),
        }
    )
    task = config.tasks[0].model_copy(
        update={
            "reusable_runs_root": request.runs_root,
            "candidate_network": True,
            "candidate_environment_names": tuple(environment),
            "allowed_output_types": None,
        }
    )
    config = config.model_copy(
        update={
            "operation_store": store,
            "tasks": (task,)
            if captures_count
            else (
                task,
                task.model_copy(
                    update={"task_id": "alternative", "label": "Alternative configured choice"}
                ),
            ),
            "credential_file": str(private),
            "editor_projects": (project, project.model_copy(update={"project_id": "disabled"})),
            "runnable_editor_projects": ("capture",),
            "browser_origin": origin,
            "port": int(origin.rsplit(":", 1)[1]),
        }
    )
    if host_ledger:
        config = config.model_copy(update={"host_ledger": _host_ledger(root)})
    CandidateConsole(config)
    (root / "console.json").write_text(config.model_dump_json(indent=2))
    metadata = {
        "origin": origin,
        "captures": captures,
        "source": request.source_path,
        "credential": str(private),
        "state": store.state_root,
    }
    (root / "metadata.json").write_text(json.dumps(metadata))
    # Token travels privately to the browser driver; never written to evidence logs.
    print(json.dumps({**metadata, "token": Path(config.auth_token_file).read_text()}), flush=True)


def headless(root: Path) -> None:
    config = ConsoleConfig.model_validate_json((root / "console.json").read_bytes())
    metadata = json.loads((root / "metadata.json").read_text())
    service = ReusableCandidate(CandidateConsole(config))
    selected = service.select(
        "capture",
        ReusableCaptureChoice(task_id="synthetic", run_id=UUID(metadata["captures"][2]["run_id"])),
    )
    reviewed = service.review("capture", selected)
    handle = service.launch(
        "capture",
        ReusableCaptureLaunch(
            selection=selected,
            expected_request_digest=reviewed.request_digest,
            candidate_operation_id=uuid4(),
        ),
    )
    deadline = time.monotonic() + 90
    while not releasable(config.operation_store, handle.operation_id):
        if time.monotonic() > deadline:
            raise TimeoutError("native operation did not finish")
        time.sleep(0.1)
    status = read_operation(config.operation_store, handle.operation_id)
    assert status.receipt is not None and status.receipt.status == "accepted", status
    print(status.model_dump_json(), flush=True)


def _host_ledger(root: Path):
    """A private ledger directory and a CPU-only budget file (B3-4c browser witness)."""
    from core.runtime_control.scheduling import HostBudget
    from tools.candidate_console.models import ConsoleHostLedger

    ledger = root / "host-ledger"
    ledger.mkdir(mode=0o700)
    budget = root / "host-budget.json"
    budget.write_text(
        HostBudget(
            gpus=(), host_memory_gib=64.0, cpu_slots=16, max_concurrent_units=4, source="file"
        ).model_dump_json(exclude={"source"})
    )
    return ConsoleHostLedger(ledger_root=str(ledger), budget_file=str(budget))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=("provider", "setup", "serve", "headless", "verify-training")
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--origin")
    parser.add_argument("--endpoint")
    parser.add_argument("--captures-count", type=int, default=3)
    parser.add_argument("--training", action="store_true")
    parser.add_argument("--families", action="store_true")
    parser.add_argument("--literature", action="store_true")
    parser.add_argument("--host-ledger", action="store_true")
    args = parser.parse_args()
    if args.mode == "provider":
        provider(args.root)
    elif args.mode == "setup":
        setup(
            args.root,
            args.origin,
            args.endpoint,
            args.captures_count,
            args.training,
            args.families,
            args.literature,
            args.host_ledger,
        )
    elif args.mode == "verify-training":
        from tests.browser.reusable_training_fixture import code_equivalent

        code_equivalent(args.root)
        from tools.candidate_worker.models import CandidateRunReceipt
        from tools.candidate_worker.training_evidence import verify_training_evidence

        receipts = list((args.root / "runs").glob("*/workspace/candidate_run/receipt.json"))
        assert receipts
        for path in receipts:
            receipt = CandidateRunReceipt.model_validate_json(path.read_bytes())
            assert receipt.status == "completed"
            verify_training_evidence(receipt)
        print("native training output verified after editor closure", flush=True)
    elif args.mode == "headless":
        headless(args.root)
    else:
        config = ConsoleConfig.model_validate_json((args.root / "console.json").read_bytes())
        if (args.root / "training-fixture").exists():
            from tests.browser.reusable_training_fixture import install_operation_fixture

            install_operation_fixture()
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
