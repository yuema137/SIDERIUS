"""S2 / U6 (#256) — every implement→validate retry survives on disk, distinct.

INVERTS the PR-E pin (``pr_e_proposal_scale_funnel.md`` §0.C, "the inner
implement→validate retry loop overwrites within one attempt dir — a known
limitation"). ``run_workflow`` now hands each retry its own nested
``impl_KKK/`` storage, so the implementor record, the validation record and
the generated-source directories of retry K never overwrite retry K-1, and
the funnel consumes the terminal attempt with no ``DuplicateIdConflict``.

The agents are mocked at the class boundary (the layout is ``run_workflow``'s
own behaviour); the mocked ``run`` side effects persist a marker into the
storage they are handed — the node contract the PR-E node-level pins prove
(``tests/integration/workflows/test_pr_e_persistence_layout_pseudo.py::
TestNodePersistence``: each node writes ``{stage}_{run}.json`` into the
workspace it is given).
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from unittest.mock import patch

from execute_tools.funnel_assembly import assemble_iteration_funnel
from execute_tools.impl_attempts import list_impl_attempt_dirs, stage_artifact_dir
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tune_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

RUN = "u6_layout"
REPO_ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"


def _run_with_forced_retries(tmp_path, verdicts: tuple[bool, ...]):
    """Drive one iteration whose implement→validate loop needs ``len(verdicts)`` tries."""
    composition = compose_run_task_bindings(str(QUICKSTART))
    _write_tuning_output(
        tmp_path,
        "punet",
        fingerprint=composition.semantic_fingerprint,
        metric_spec=composition.metric.spec,
    )
    workspace = str(tmp_path / "workflow_output")
    impl_inputs: list = []
    valid_inputs: list = []
    impl_outputs: list = []
    # The proposer mints the candidate id at run time; a class-boundary mock
    # must supply one, or nothing downstream can join (O-E-4).
    proposal = _make_proposal_output().model_copy(update={"candidate_id": "cand_u6_layout"})

    def _propose(inp):
        # The proposer's own persistence contract (node-level pin), so the
        # funnel sees the proposal stage at the attempt level.
        ws = inp.storage.local.workspace
        os.makedirs(ws, exist_ok=True)
        Path(ws, f"proposal_{inp.storage.local.run_name}.json").write_text(
            json.dumps({"candidate_id": proposal.candidate_id, "model_name": proposal.model_name})
        )
        return proposal

    def _implement(inp):
        impl_inputs.append(inp)
        k = len(impl_inputs)
        ws = inp.storage.local.workspace
        os.makedirs(ws, exist_ok=True)
        Path(ws, f"implementor_{inp.storage.local.run_name}.json").write_text(
            json.dumps({"candidate_id": inp.candidate_id, "impl_attempt": k})
        )
        out = _make_implementor_output().model_copy(
            update={
                "candidate_id": inp.candidate_id,
                "model_file_path": os.path.join(inp.plugin_dir, f"gated_tcn_{k}.py"),
            }
        )
        impl_outputs.append(out)
        return out

    def _validate(inp):
        valid_inputs.append(inp)
        k = len(valid_inputs)
        ws = inp.storage.local.workspace
        os.makedirs(ws, exist_ok=True)
        passed = verdicts[k - 1]
        Path(ws, f"validation_{inp.storage.local.run_name}.json").write_text(
            json.dumps({"candidate_id": inp.candidate_id, "passed": passed, "impl_attempt": k})
        )
        return _make_validator_output(passed=passed)

    with contextlib.ExitStack() as stack:
        interp = stack.enter_context(patch("workflows.model_exploration.ResultInterpretationAgent"))
        propose = stack.enter_context(patch("workflows.model_exploration.MLModelProposalAgent"))
        impl = stack.enter_context(patch("workflows.model_exploration.MLModelImplementor"))
        valid = stack.enter_context(patch("workflows.model_exploration.MLCodeValidatorAgent"))
        tune = stack.enter_context(patch("workflows.model_exploration.HyperparamTuningAgent"))
        register = stack.enter_context(patch("workflows.model_exploration._register_plugin"))
        stack.enter_context(patch("workflows.model_exploration._promote_model_to_global"))
        stack.enter_context(patch("workflows.model_exploration._promote_loss_to_global"))
        interp.return_value.run.return_value = _make_interpretation_output()
        propose.return_value.run.side_effect = _propose
        impl.return_value.run.side_effect = _implement
        valid.return_value.run.side_effect = _validate
        tune.return_value.run.return_value = _make_tune_output(
            fingerprint=composition.semantic_fingerprint,
            metric_spec=composition.metric.spec,
        )

        with bind_run_task_composition(composition, physical_data_root=str(tmp_path / "data")):
            run_workflow(
                llm_config=WorkflowLLMConfig(
                    tune=TunerLLMConfig(planner_strategy="native-timing-v1")
                ),
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=1,
                    max_proposal_attempts=1,
                    max_impl_attempts=len(verdicts),
                ),
                workspace=workspace,
                run_name=RUN,
                task_composition=composition,
            )
        register_calls = register.call_args_list

    iter_dir = os.path.join(workspace, RUN, "iteration_001")
    attempt_dir = os.path.join(iter_dir, "attempt_001_gated_tcn")
    return iter_dir, attempt_dir, impl_inputs, valid_inputs, impl_outputs, register_calls


def test_two_forced_retries_leave_three_distinct_attempts_on_disk(tmp_path):
    """THE #256 DEFECT: with one storage per proposal attempt, retry 3
    overwrote retries 1 and 2 (records, plugin, test, description, loss).
    Fails if fewer than three ``impl_KKK/`` exist, if two share a path, or
    if their contents are not the attempt that wrote them."""
    _iter_dir, attempt_dir, impl_inputs, valid_inputs, _outputs, _reg = _run_with_forced_retries(
        tmp_path, (False, False, True)
    )
    impl_dirs = list_impl_attempt_dirs(attempt_dir)
    assert [os.path.basename(d) for d in impl_dirs] == ["impl_001", "impl_002", "impl_003"]
    assert len({inp.storage.local.workspace for inp in impl_inputs}) == 3
    for k, (impl_dir, impl_inp, valid_inp) in enumerate(
        zip(impl_dirs, impl_inputs, valid_inputs, strict=True), start=1
    ):
        assert impl_inp.storage.local.workspace == impl_dir
        assert valid_inp.storage.local.workspace == impl_dir
        assert impl_inp.plugin_dir == os.path.join(impl_dir, "models")
        assert impl_inp.test_dir == os.path.join(impl_dir, "tests")
        assert impl_inp.loss_dir == os.path.join(impl_dir, "losses")
        impl_rec = json.loads(Path(impl_dir, f"implementor_{RUN}.json").read_text())
        valid_rec = json.loads(Path(impl_dir, f"validation_{RUN}.json").read_text())
        assert impl_rec["impl_attempt"] == k
        assert valid_rec["impl_attempt"] == k
        assert valid_rec["passed"] is (k == 3)
    # The proposal record stays at the attempt level, unchanged.
    assert os.path.isfile(os.path.join(attempt_dir, f"proposal_{RUN}.json"))
    assert not os.path.exists(os.path.join(attempt_dir, f"implementor_{RUN}.json"))


def test_the_funnel_and_the_registration_consume_the_terminal_attempt(tmp_path):
    """DEFECT: sibling attempt directories would trip DuplicateIdConflict
    (tuner evidence withheld); registering a non-terminal ``impl_output``
    would ship the plugin that FAILED validation. Fails on either."""
    iter_dir, attempt_dir, _inputs, _valid, impl_outputs, register_calls = _run_with_forced_retries(
        tmp_path, (False, True)
    )
    assert stage_artifact_dir(attempt_dir) == os.path.join(attempt_dir, "impl_002")

    funnel = assemble_iteration_funnel(iter_dir)
    assert funnel.duplicate_id_conflicts == []
    assert len(funnel.rows) == 1 and not funnel.unjoinable
    row = funnel.rows[0]
    assert row.candidate_id == impl_outputs[-1].candidate_id
    assert row.stages["validation"].native is not None
    assert row.stages["validation"].native["impl_attempt"] == 2
    assert row.stages["implementation"].native is not None
    assert row.stages["implementation"].native["impl_attempt"] == 2

    assert len(register_calls) == 1
    registered_output = register_calls[0].args[0]
    assert registered_output is impl_outputs[-1]
    assert registered_output.model_file_path.endswith(
        os.path.join("impl_002", "models", "gated_tcn_2.py")
    )
