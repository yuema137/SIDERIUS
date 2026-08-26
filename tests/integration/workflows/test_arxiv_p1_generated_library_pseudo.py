"""arXiv P1 — checkout-pollution migration: the workflow-level witness.

Anti-vacuity matrix rows A, B and C in ONE real ``run_workflow`` pass
(mocked agents, REAL startup preloads, REAL post-validation index register,
REAL ``_promote_loss_to_global`` + ``_promote_model_to_global``, REAL
run-invariants lock):

  A. a fresh normal run writes the generated artifacts (promoted model .py,
     promoted loss .py, capability index rows) under the RESOLVED
     non-checkout library root;
  B. provenance records the resolved location — the startup log line and
     the lock's ``generated_library`` field;
  C. the repository checkout's ``agent_generated/`` tree is byte-identical
     before and after the run — a DIRECTORY-STATE assertion (recursive
     relpath+sha256 snapshot), not an absence-of-crash.

Row C is also the plant detector (matrix row E): re-rooting ANY of the four
family writers back at the repository checkout turns the snapshot
comparison RED.

Harness modeled on ``test_chain_incumbent_pseudo.py``: agents mocked at the
class boundary so ``run_workflow``'s OWN body — the production wiring P1
repointed — executes for real. ``_register_plugin`` alone stays patched: it
is the workspace-scoped half (already tmp-rooted, out of P1 scope) and
needs a full sandbox layout this bounded probe does not build.

Wrong-tree guard (S5 finding E1): the editable-install finder can map
``core``/``workflows`` to the canonical checkout for subprocess children.
This probe runs in-process, and it still asserts module provenance against
its own checkout so a wrong-tree import turns the rows RED rather than
vacuously green.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import textwrap
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.implementor import ImplementorOutput, LossProvenance
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ExpertAdvice, ProposalOutput
from agent.schemas.validator import ValidatorOutput
from agent_generated._registry import CapabilityMetadata
from core.resume import restore_prior_state
from core.run_invariants import RUN_INVARIANTS_BASENAME
from core.scientific_authority import ScientificAuthority
from sdsc_submission_scripts.run_one_iteration import write_manifest
from tests.helpers.metric_fixtures import shipped_spec
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig

pytestmark = pytest.mark.dual_mode

_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

_GEN_MODEL_TYPE = "gen_probe_model"
_GEN_LOSS_NAME = "gen_probe_loss"

_GEN_MODEL_SRC = textwrap.dedent(f"""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "{_GEN_MODEL_TYPE}"

    class _Cfg(BaseModel):
        model_type: str = "{_GEN_MODEL_TYPE}"
        segmentation_size: int = Field(default=1000, ge=100)
        batch_size: int = 1

    class _Mdl(nn.Module):
        def __init__(self, config):
            super().__init__()
        def forward(self, x):
            return x.float().unsqueeze(1).expand(-1, 256, -1)

    PLUGIN_CONFIG_CLASS = _Cfg
    PLUGIN_MODEL_CLASS  = _Mdl
""")

_GEN_LOSS_SRC = textwrap.dedent(f"""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_LOSS_TYPE = "{_GEN_LOSS_NAME}"

    class _LossCfg(BaseModel):
        pass

    class _Loss(nn.Module):
        def __init__(self, config):
            super().__init__()
        def forward(self, inputs, targets):
            return inputs.mean()

    PLUGIN_LOSS_CONFIG_CLASS = _LossCfg
    PLUGIN_LOSS_CLASS = _Loss
""")


def _checkout_agent_generated_snapshot() -> list[tuple[str, str]]:
    """Recursive (relpath, sha256) snapshot of the checkout's
    ``agent_generated/`` tree — the row-C directory-state evidence."""
    root = os.path.join(_REPO_ROOT, "agent_generated")
    snapshot: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fname in sorted(filenames):
            path = os.path.join(dirpath, fname)
            digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
            snapshot.append((os.path.relpath(path, root), digest))
    return sorted(snapshot)


def _passing_verdicts() -> list[dict]:
    return [
        {
            "gate_name": gate_id,
            "execution_status": "passed",
            "check_passed": True,
            "would_invalidate_under_production_policy": False,
            "resolved_action": "continue",
        }
        for gate_id in (
            "output_diversity_blocking",
            "output_std_blocking",
            "amplitude_collapse_blocking",
        )
    ]


def _formal_record(exp_id: str, score: float, model_type: str) -> dict:
    return {
        "exp_id": exp_id,
        "status": "success",
        "model_type": model_type,
        "timestamp": "2026-07-27 00:00:00",
        "params": {},
        "logical_round": 3,
        "denoising_score": score,
        "file_vector": [score] + [None] * 19,
        "health_gate_results": _passing_verdicts(),
        "health_gate_enabled": False,
        "scientific_authority": ScientificAuthority(
            healthgate_mode="blocking",
            declared_result_authority="scientific",
            formal_validity="valid",
        ).model_dump(mode="json"),
    }


def _tune_output(run_name: str, model_type: str, score: float) -> HyperparamTuningOutput:
    records = [_formal_record("f1", score, model_type)]
    return HyperparamTuningOutput(
        run_name=run_name,
        model_type=model_type,
        file_index=6,
        status="completed",
        completed_rounds=1,
        total_attempts=1,
        best_denoising_score=score,
        best_formal_denoising_score=score,
        best_valid_formal_denoising_score=score,
        best_valid_formal_exp_id="f1",
        all_records=records,
        started_at="2026-07-27 00:00:00",
        finished_at="2026-07-27 00:00:01",
        # Step 09a: a score-bearing output must carry its MetricSpec or the
        # summary projection refuses (a direction is never assumed).
        metric_spec=shipped_spec(),
    )


def _write_iter_disk(workspace: str, iter_idx: int, tune_output: HyperparamTuningOutput) -> None:
    run_name = f"iter_{iter_idx:03d}"
    iter_dir = os.path.join(workspace, run_name)
    model_dir = os.path.join(iter_dir, "iteration_001", tune_output.model_type)
    os.makedirs(model_dir, exist_ok=True)
    with open(os.path.join(model_dir, f"run_output_{run_name}.json"), "w") as f:
        f.write(tune_output.model_dump_json())
    with open(os.path.join(model_dir, f"run_config_{run_name}.json"), "w") as f:
        json.dump({"formal_strategy": "snapshot", "formal_eval_portion": 1.0}, f)
    write_manifest(iter_dir, run_name, [tune_output])


_INTERP_OUT = InterpretationOutput(
    model_types=["punet"],
    model_descriptions={"punet": "punet"},
    total_experiments=1,
    per_model_best={"punet": 1.0},
    per_model_worst={"punet": 0.5},
    best_denoising_score=1.0,
    worst_denoising_score=0.5,
    best_config={"model_config": {}},
    key_findings=[],
    bottlenecks=[],
    take_home_message="proceed",
    model_knowledge_cache={},
    runtime_vocab=[],
)


def _proposal_out() -> ProposalOutput:
    return ProposalOutput(
        model_name=_GEN_MODEL_TYPE,
        model_description="generated probe model",
        mathematical_definition="y = model(x)",
        motivation="witness the library write path",
        expert_advice=ExpertAdvice(
            focus_areas=["-"],
            constraints=["-"],
            known_failures=["-"],
            suggested_directions=["-"],
            rationale="pseudo probe - no real advice",
        ),
        baseline_config={
            "model_config": {},
            "train_config": {},
            "loss_config": {"loss_type": "focal"},
        },
    )


def _impl_out(gen_dir: str) -> ImplementorOutput:
    """A generated-model implementor output whose artifacts REALLY exist
    (in tmp), carrying the capability metadata the workflow registers
    post-validation and the loss provenance the promotion consumes."""
    model_file = os.path.join(gen_dir, f"{_GEN_MODEL_TYPE}.py")
    with open(model_file, "w") as f:
        f.write(_GEN_MODEL_SRC)
    loss_file = os.path.join(gen_dir, f"{_GEN_LOSS_NAME}.py")
    with open(loss_file, "w") as f:
        f.write(_GEN_LOSS_SRC)
    desc_file = os.path.join(gen_dir, "description.md")
    with open(desc_file, "w") as f:
        f.write("# generated probe model\n")
    test_file = os.path.join(gen_dir, f"test_{_GEN_MODEL_TYPE}.py")
    with open(test_file, "w") as f:
        f.write("def test_noop():\n    pass\n")
    return ImplementorOutput(
        model_type=_GEN_MODEL_TYPE,
        description_file_path=desc_file,
        model_file_path=model_file,
        test_file_path=test_file,
        config_fields={"segmentation_size": 1000},
        model_description="generated probe model",
        mathematical_definition="y = model(x)",
        capability_metadata=CapabilityMetadata(
            name=_GEN_MODEL_TYPE,
            capability_type="model",
            file_path=model_file,
            created_at="2026-08-24T00:00:00+00:00",
            source_iteration="iter_002",
            description="generated probe model",
        ),
        loss_provenance=LossProvenance(
            loss_name=_GEN_LOSS_NAME,
            action="generated",
            source_iteration="iter_002",
            loss_file_path=loss_file,
            dummy_tensor_validated=True,
        ),
    )


_VALID_OUT = ValidatorOutput(
    passed=True,
    model_type=_GEN_MODEL_TYPE,
    plugin_registered=True,
    tests_passed=True,
    description_valid=True,
    config_fields_valid=True,
    instantiation_passed=True,
    gradient_check_passed=True,
    llm_review_passed=True,
)


def test_fresh_run_writes_the_library_not_the_checkout(tmp_path, monkeypatch, capsys):
    """Matrix rows A + B + C — see module docstring for the row mapping."""
    # Wrong-tree guard (E1): the modules under test must come from THIS
    # checkout, or every assertion below certifies the wrong tree.
    import core.generated_library as _cgl
    import workflows.model_exploration as _wme

    assert os.path.realpath(_cgl.__file__).startswith(os.path.realpath(_REPO_ROOT) + os.sep)
    assert os.path.realpath(_wme.__file__).startswith(os.path.realpath(_REPO_ROOT) + os.sep)

    lib = tmp_path / "lib"
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(lib))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    gen_dir = tmp_path / "impl_out"
    gen_dir.mkdir()

    before = _checkout_agent_generated_snapshot()

    _write_iter_disk(str(workspace), 1, _tune_output("iter_001", "punet", 1.0))
    state = restore_prior_state(str(workspace), current_iter=2, seed_paths=[])

    with contextlib.ExitStack() as stack:
        MockInterp = stack.enter_context(
            patch("workflows.model_exploration.ResultInterpretationAgent")
        )
        MockPropose = stack.enter_context(patch("workflows.model_exploration.MLModelProposalAgent"))
        MockImpl = stack.enter_context(patch("workflows.model_exploration.MLModelImplementor"))
        MockValid = stack.enter_context(patch("workflows.model_exploration.MLCodeValidatorAgent"))
        MockTune = stack.enter_context(patch("workflows.model_exploration.HyperparamTuningAgent"))
        # The workspace-scoped mirror half (out of P1 scope; needs a full
        # sandbox layout). The FOUR P1 families all stay REAL.
        stack.enter_context(
            patch("workflows.model_exploration._register_plugin", return_value=None)
        )
        MockInterp.return_value.run.return_value = _INTERP_OUT
        MockPropose.return_value.run.return_value = _proposal_out()
        MockImpl.return_value.run.return_value = _impl_out(str(gen_dir))
        MockValid.return_value.run.return_value = _VALID_OUT
        MockTune.return_value.run.return_value = _tune_output("iter_002", _GEN_MODEL_TYPE, 1.2)

        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=str(tmp_path / "data"),
                model_types=["punet"],
                source_run_name="v1",
                start_iteration=2,
                max_iterations=1,
                source_paths=state.resolved_source_paths,
            ),
            workspace=str(workspace),
            run_name="iter_002",
            restored_state=state,
        )

    out = capsys.readouterr().out

    # --- Row B: startup log provenance names the resolved root. ---
    assert f"Generated library: {lib} (source: env)" in out

    # --- Row A: all four artifact families landed under the resolved root. ---
    promoted_model = lib / "models" / f"{_GEN_MODEL_TYPE}.py"
    assert promoted_model.is_file()
    assert promoted_model.read_text() == _GEN_MODEL_SRC
    assert (lib / "models" / _GEN_MODEL_TYPE / "description.md").is_file()
    promoted_loss = lib / "losses" / f"{_GEN_LOSS_NAME}.py"
    assert promoted_loss.is_file()
    assert promoted_loss.read_text() == _GEN_LOSS_SRC
    index_path = lib / "_capability_index.json"
    assert index_path.is_file()
    rows = {row["name"]: row for row in json.loads(index_path.read_text())}
    assert _GEN_MODEL_TYPE in rows
    # The promotion's registry leg re-pointed file_path at the library copy.
    assert rows[_GEN_MODEL_TYPE]["file_path"] == str(promoted_model)

    # --- Row B: the lock records {root, source} as _PROVENANCE. ---
    lock = json.loads((workspace / RUN_INVARIANTS_BASENAME).read_text())
    assert lock["generated_library"] == {"root": str(lib), "source": "env"}

    # --- Row C: the checkout is byte-identical — the plant detector. ---
    assert _checkout_agent_generated_snapshot() == before
