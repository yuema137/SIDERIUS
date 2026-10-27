"""Two independently captured native bodies, not public append admission."""

import json
from pathlib import Path

import pytest

from tests.helpers.candidate_literature import literature_request
from tools.candidate_worker.graph import execute_fanout
from tools.candidate_worker.graph_evidence import admit_graph_control, verify_graph_trace
from tools.workflow_preview.files import observe_file
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

from .test_graph import initial
from .test_literature import literature_sdk
from .test_native import native_runner


def test_native_bodies_use_independent_captures_and_parent_iteration(
    prepared, native_runner, literature_sdk, monkeypatch
):
    """Crossed captures/receipts must not overwrite or certify another iteration."""
    from core.durable_io import publish_bytes_write_once

    request = literature_request(prepared)
    project = Path(request.preview.project_root)
    receipt = initial(request)
    workspace = Path(receipt.workspace)
    composition = compose_run_task_bindings(request.preview.document.definition.task.manifest)
    config = WorkflowLLMConfig.model_validate_json((project / "llm.json").read_bytes())
    seed_template = json.loads((project / "seed.json").read_bytes())
    review_template = json.loads((project / "review.json").read_bytes())
    generate = native_runner.generate

    def distinct_proposals(self, *args, **kwargs):
        output = generate(self, *args, **kwargs)
        if "model_name" in output:
            output["model_name"] = f"worker_linear_{self.context['iter']}"
        return output

    monkeypatch.setattr(native_runner, "generate", distinct_proposals)
    preserved = {}
    receipts = []
    with bind_run_task_composition(composition, physical_data_root=str(project / "data")):
        for iteration in (1, 2):
            control = workspace / "candidate_run"
            if iteration == 2:
                control /= "iteration_002"
            slots = workspace / request.run_name / "graph_instances"
            review_storage = {
                "backend": "local",
                "local": {
                    "workspace": str(slots / "review" / f"iteration_{iteration:03d}/attempt_001"),
                    "run_name": request.run_name,
                },
            }
            impl_storage = {
                "backend": "local",
                "local": {
                    "workspace": str(
                        slots / "build0" / f"iteration_{iteration:03d}/attempt_001/impl_001"
                    ),
                    "run_name": request.run_name,
                },
            }
            # The caller authors fresh inputs before capture. Prior snapshots are immutable.
            (project / "seed.json").write_text(
                json.dumps(
                    {
                        **seed_template,
                        "storage": {
                            "backend": "local",
                            "local": {
                                "workspace": str(
                                    slots / "propose" / f"iteration_{iteration:03d}/attempt_001"
                                ),
                                "run_name": request.run_name,
                            },
                        },
                        "debug_dump_proposing_prompt_path": str(
                            control / "debug/propose/prompt.md"
                        ),
                    }
                )
            )
            (project / "review.json").write_text(
                json.dumps({**review_template, "storage": review_storage})
            )
            (project / "slot0.json").write_text(json.dumps(impl_storage))
            captures = [observe_file(Path(item.path), item.reference) for item in request.files]
            selected = request.model_copy(update={"files": tuple(item for item, _ in captures)})
            control.mkdir(parents=True, exist_ok=True)
            for index, (_, payload) in enumerate(captures):
                publish_bytes_write_once(str(control / f"input_{index:03}.snapshot"), payload)
            admit_graph_control(selected, receipt, iteration=iteration)
            if iteration == 2:
                before = len(native_runner.calls), len(literature_sdk[0])
                # A caller captured iteration-two storage for slot three: reject before effects.
                crossed = workspace / "candidate_run/iteration_003"
                crossed.mkdir()
                for index, (_, payload) in enumerate(captures):
                    publish_bytes_write_once(str(crossed / f"input_{index:03}.snapshot"), payload)
                with pytest.raises(ValueError, match="storage"):
                    execute_fanout(selected, receipt, composition, config, iteration=3)
                assert before == (len(native_runner.calls), len(literature_sdk[0]))
            terminal = execute_fanout(selected, receipt, composition, config, iteration=iteration)
            assert terminal.status == "accepted", terminal
            verify_graph_trace(selected, receipt, terminal, iteration=iteration)
            assert {row.state for row in terminal.graph_trace.nodes} == {"succeeded"}
            for row in terminal.graph_trace.nodes:
                assert f"/iteration_{iteration:03d}/" in row.storage
            with pytest.raises(ValueError, match="graph trace binding"):
                verify_graph_trace(selected, receipt, terminal, iteration=3)
            assert all(path.read_bytes() == content for path, content in preserved.items())
            paths = [*control.glob("input_*.snapshot"), *control.glob("*inputs/*.json")]
            paths.extend(Path(path) for path in terminal.native_output_paths)
            preserved.update({path: path.read_bytes() for path in paths})
            receipts.append((selected, terminal))
    for iteration, (selected, terminal) in enumerate(receipts, 1):
        verify_graph_trace(selected, receipt, terminal, iteration=iteration)
    assert {context["iter"] for _, context in native_runner.calls} == {1, 2}
    rows = [json.loads(line) for line in Path(receipt.ledger_path).read_text().splitlines()]
    assert [row["iter"] for row in rows] == [1, 2]
    assert all(row["run_id"] == receipt.run_id for row in rows)
