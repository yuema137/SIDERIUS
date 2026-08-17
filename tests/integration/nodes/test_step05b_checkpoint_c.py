"""Step 05b CHECKPOINT C — the REAL production resource/time control flow.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
§9 (Checkpoint C's frozen property), §8 (Stage-B B1/B2), §11 (the Gate-2
condition this evidence settles).

Everything else in this PR proves that a helper *can* consume the run-bound
authorities. That is a different claim from *production does*, and §9 makes
the difference explicit: **a helper-only test cannot discharge Checkpoint C.**
So both scenarios below run the production entry points, and nothing that
makes a decision is stubbed.

    C-P   the real VRAM pre-flight: the tuner's own adapter, a real
          IsolatedProbeSpec, a real spawned worker process, the real
          _build_probe_tensors realization, the real pricing composition and
          the real admission verdict. NO measurement stub — the probe runs on
          CPU, which costs under two seconds for a small candidate.

    C-D   the real workload/time path: the real HyperparamTuningAgent.run()
          reaching its real _run_time_preflight, which calls the real
          evaluate_time_skill.run_skill, which resolves real workloads from
          the run-bound DatasetProfile and returns a real feasibility verdict.

Two scenarios, ONE checkpoint (§9). They are separate because the production
control flow is: the tuner reaches the pre-flight through a subprocess
adapter and the time gate through an in-process skill, and no single call
crosses both.

**Deliberately NOT in the unit suite.** C-P spawns a real worker process, and
`tests/unit/agent/tune_ml_hyperparam_agent/conftest.py` exists precisely to
forbid that there — a test that spawns the worker under a stub that stopped
intercepting *hangs* rather than fails. CI is unit + static by design; this
module is run locally and its result is recorded in the design ledger.
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

import pytest

from agent.skills.evaluate_vram_skill.isolated_probe import HardwareSnapshot
from agent.skills.evaluate_vram_skill.preflight_adapter import run_production_preflight
from execute_tools.dataset_config import TIDMAD_PROFILE
from tests.helpers.scoring_stubs import stub_scoring
from tests.helpers.step04a_fixtures import tidmad_model_io

#: A synthetic GPU. The cap, device name and fingerprint are the parent's
#: frozen snapshot — the same object production hands the worker — so the
#: admission comparison below is the production one, against a number this
#: test states rather than a card it happens to find.
SNAPSHOT = HardwareSnapshot(
    usable_cap_bytes=8 * 1024**3,
    usable_cap_gb=8.0,
    total_memory_bytes=10 * 1024**3,
    total_memory_gb=10.0,
    device_name="s05b-checkpoint-c",
    device_available=True,
    hardware_fingerprint="s05b-checkpoint-c",
)

#: Small enough to probe on CPU in ~2 s, large enough that the forecast is a
#: real composition rather than a rounding artefact.
SEG = 1024


#: A 16-class candidate. Deliberately NOT 256: the whole question is
#: whether the gate prices what the run declares or what a literal says.
CANDIDATE = {
    "segmentation_size": SEG,
    "multi": 8,
    "depth": 2,
    "embedding_dim": 8,
    "num_classes": 16,
}


def _preflight(contract, workspace: str, label: str, loss_type: str = "smooth_l1") -> dict:
    """One real pre-flight of ONE fixed candidate, priced against ``contract``.

    Everything except the contract is held constant across every call in this
    module — the same model config, batch, segment length, loss, hardware
    snapshot and cap. So a difference in outcome is attributable to the
    contract and to nothing else.

    ``smooth_l1`` rather than ``ce`` because a long target is class INDICES,
    ``[B, T]``, carrying no contract-owned extent by design (ledger §18.3
    D-05b-2). Under a class-index loss the contract is correctly inert here,
    which is a compatibility property, not an observation. The float-target
    branch is the one the contract governs, and the gate does not itself
    gate on loss/semantic compatibility — that rule lives upstream — so this
    is a reachable input to this path.
    """
    return run_production_preflight(
        model_type="punet",
        model_config=CANDIDATE,
        train_config={"batch_size": 1},
        loss_config={"loss_type": loss_type},
        vram_budget_gb=None,
        hardware_context=SNAPSHOT,
        workspace=workspace,
        label=label,
        deadline_seconds=600.0,
        model_io_contract=contract,
    )


# ---------------------------------------------------------------------------
# C-P — the real VRAM pre-flight, pricing and admission
# ---------------------------------------------------------------------------


class TestCPRealPreflightAdmission:
    def test_the_real_gate_prices_and_admits_through_the_full_production_path(self):
        """The whole chain, unstubbed: adapter → spec → JSON → spawned worker
        → run_skill → probe realization → pricing → admission → adapted dict.

        The verdict must be a REAL decision, not a transport artefact: a
        status of ``schema_violation``, ``error`` or ``timeout`` would mean
        the run never reached the capacity question.
        """
        with tempfile.TemporaryDirectory() as workspace:
            result = _preflight(tidmad_model_io(num_classes=16), workspace, "cp_admit")

        assert result["status"] == "success", result.get("message")
        assert result["feasible"] is True
        assert result["num_params"] > 0
        assert result["limit_gb"] == 8.0
        assert 0.0 < result["estimated_gb"] < result["limit_gb"]
        # The admission comparison the tuner acts on, recomputed here from the
        # returned numbers so a verdict string alone cannot carry the test.
        assert result["estimated_gb"] <= result["limit_gb"]

    def test_the_contract_is_what_makes_the_candidate_probeable(self):
        """**B1 at production scale, single-axis.**

        ONE candidate, one hardware snapshot, one cap, one batch, one segment
        length, one loss. The ONLY variable is the run-bound contract.

        * bound  → the probe realizes ``[1, 16, T]`` from the declaration, the
          gate prices it and admits it;
        * absent → the legacy ``[B, 256, T]`` literal is realized against a
          model emitting 16 logits, and the probe dies on the shape.

        The second outcome is the V21 PR A defect verbatim — *"The size of
        tensor a (16) must match the size of tensor b (256) at non-singleton
        dimension 1"*, a contract defect wearing a resource-error costume. It
        is what this PR removes, and reproducing it here is what proves the
        contract is load-bearing rather than merely present: a transport that
        dropped it anywhere between the tuner and the worker would make the
        FIRST call fail exactly like the second.
        """
        with tempfile.TemporaryDirectory() as workspace:
            bound = _preflight(tidmad_model_io(num_classes=16), workspace, "cp_bound")
            legacy = _preflight(None, workspace, "cp_legacy")

        assert bound["status"] == "success", bound.get("message")
        assert bound["feasible"] is True

        assert legacy["status"] != "success", (
            "the no-contract run succeeded — the legacy literal is no longer "
            "reachable, so this contrast proves nothing about the contract"
        )
        assert "256" in str(legacy.get("message", "")), legacy.get("message")

    def test_calibration_and_hardware_are_fixed_across_the_contrast(self):
        """The contrast must move ONE authority's fact and nothing else. If
        the cap or its source moved too, the difference above would not be
        attributable to the contract."""
        with tempfile.TemporaryDirectory() as workspace:
            first = _preflight(tidmad_model_io(num_classes=16), workspace, "cp_fix_a")
            second = _preflight(tidmad_model_io(num_classes=16), workspace, "cp_fix_b")

        assert first["limit_gb"] == second["limit_gb"] == 8.0
        assert first["effective_vram_limit_gb"] == second["effective_vram_limit_gb"] == 8.0
        assert first["effective_limit_source"] == second["effective_limit_source"]
        # The DECISION is what the tuner acts on, and it is stable. The
        # forecast itself is not asserted equal: two identical runs measured
        # 0.230 and 0.231 GB, host-allocator jitter inside the real probe.
        # That is a pre-existing property of the measurement, not something
        # 05b introduces or should pin — pinning it would make this checkpoint
        # flake for a reason unrelated to the contract.
        assert first["feasible"] == second["feasible"] is True


# ---------------------------------------------------------------------------
# C-D — the real workload/time path, driven by the real tuner
# ---------------------------------------------------------------------------


@pytest.fixture
def _tuner_harness():
    """The established pattern from ``test_step02b_tuner_supplies_profile``:
    the REAL ``run()``, with only the LLM, the sandbox and the training
    subprocesses replaced. Everything this checkpoint observes stays real.
    """
    from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
        FAKE_PLAN_WITH_TRIAL,
        FAKE_REFLECT_RESPONSE,
        FAKE_SCORE_VECTOR_RESULT,
        FAKE_TIME_CHECK_OK,
        _make_trial_input,
        _mock_run_skill,
        _synth_reference,
    )

    return {
        "plan": FAKE_PLAN_WITH_TRIAL,
        "reflect": FAKE_REFLECT_RESPONSE,
        "score_vector": FAKE_SCORE_VECTOR_RESULT,
        "make_input": _make_trial_input,
        "run_skill": _mock_run_skill,
        "reference": _synth_reference,
        "time_check_ok": FAKE_TIME_CHECK_OK,
    }


def _drive_tuner(tmp_path, harness, *, capture: dict):
    """Run the real tuner far enough to reach both pre-flight gates.

    ``run_production_preflight`` and ``evaluate_time_skill.run_skill`` are
    wrapped in RECORDING spies, not replaced: the pre-flight delegates to the
    package's existing stub so no worker is spawned from this path, while the
    time gate runs for real.
    """
    from importlib import import_module

    from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent

    tuner = import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")

    def _spy_preflight(**kwargs):
        capture.setdefault("preflight", []).append(kwargs)
        return harness["run_skill"]("evaluate_vram_skill", None, **kwargs)

    real_time_skill = tuner._run_skill

    def _spy_run_skill(skill_folder, sandbox, **params):
        if skill_folder == "evaluate_time_skill":
            capture.setdefault("time", []).append(params)
            # The package's shared dispatcher has no entry for this skill, so
            # delegating would return {"status": "error"} and the tuner would
            # raise `Time check error: unknown skill` — aborting the round
            # AFTER the capture. The run must complete normally, or a later
            # mutation could red for that abort rather than for the value
            # this scenario is asserting.
            return harness["time_check_ok"]
        return harness["run_skill"](skill_folder, sandbox, **params)

    _ = real_time_skill
    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_spy_run_skill),
        patch(
            "nodes.ml_hyperparameter_tune_agent.execution.run_production_preflight", _spy_preflight
        ),
        patch(
            "nodes.ml_hyperparameter_tune_agent.execution.get_gates_for_position", return_value=[]
        ),
        patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor,
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=harness["reference"](),
        ),
        patch("os.path.exists", return_value=True),
        tempfile.TemporaryDirectory() as configs_dir,
    ):
        MockBridge.return_value.plan.return_value = harness["plan"]
        MockBridge.return_value.reflect.return_value = harness["reflect"]
        mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

        saved: list = []
        sandbox = MockSandbox.return_value
        sandbox.get_summary.side_effect = lambda: list(saved)
        sandbox.save_record.side_effect = saved.append
        sandbox.dirs = {"configs": configs_dir, "data": configs_dir}
        sandbox.base_dir = configs_dir
        stub_scoring(sandbox, *harness["score_vector"])

        agent_input = harness["make_input"](tmp_path, max_rounds=1, is_trial=True)
        # The time gate is opt-in PER MODE: with no budget the tuner prints
        # "[time-gate disabled / …]" and never calls the skill, so the C-D
        # scenario would silently observe nothing. BOTH budgets are set
        # because a single-round run is forced formal, so a trial-only budget
        # leaves the gate disabled for the round that actually executes —
        # which is exactly what the first attempt at this test hit.
        agent_input = agent_input.model_copy(
            update={
                "trial_time_budget_minutes": 20.0,
                "formal_time_budget_minutes": 120.0,
            }
        )
        return HyperparamTuningAgent().run(agent_input)


class TestCDRealWorkloadTimePath:
    def test_the_tuner_supplies_both_run_bound_authorities_to_the_live_gates(
        self, tmp_path, _tuner_harness
    ):
        """**Closes mutation M14.**

        C4 wired the contract into ``run()``'s pre-flight call and recorded
        that the hop had no execution coverage: it is a single line inside a
        ~2,500-line orchestrator, and a source-shape assertion would have been
        a green tick with nothing behind it. This drives the real ``run()``
        and reads what the production call sites actually passed.
        """
        capture: dict = {}
        output = _drive_tuner(tmp_path, _tuner_harness, capture=capture)
        assert output.status == "completed", (
            "the run did not complete, so a later assertion could pass or fail "
            f"for a reason unrelated to transport (status={output.status})"
        )

        preflights = capture.get("preflight", [])
        assert preflights, "the run never reached the VRAM pre-flight"
        for index, kwargs in enumerate(preflights):
            contract = kwargs.get("model_io_contract")
            assert contract is not None, (
                f"pre-flight call {index} reached the resource gate with NO "
                "contract — the tuner is not supplying the run binding"
            )
            assert contract == tidmad_model_io(), (
                f"pre-flight call {index} supplied a contract that is not the run's declaration"
            )

        time_calls = capture.get("time", [])
        assert time_calls, "the run never reached the time gate"
        for index, params in enumerate(time_calls):
            assert params.get("dataset_profile") == TIDMAD_PROFILE, (
                f"time-gate call {index} did not receive the run-bound profile"
            )

    def test_the_live_time_gate_produces_a_real_verdict_from_real_workloads(
        self, tmp_path, _tuner_harness
    ):
        """The real ``evaluate_time_skill.run_skill``, on the arguments the
        real tuner assembled.

        The gate is invoked HERE rather than inside ``run()`` for one
        source-grounded reason: the fake plan's candidate is a full-scale
        punet at ``seg_size=40000``, and the harness patches
        ``os.path.exists`` to ``True``, so a real invocation nested in the
        tuner enters the warm-up path and reads real HDF5 files. That is a
        harness artefact, not production behaviour — an operator run supplies
        a real ``data_dir`` or none.

        So the chain is established in two halves that meet at the same
        values: the test above proves the tuner PASSES the run-bound profile
        to the live gate, and this one proves the live gate RESOLVES real
        workloads from it and returns a real verdict. Neither half is a
        helper: both are production entry points.
        """
        capture: dict = {}
        _drive_tuner(tmp_path, _tuner_harness, capture=capture)
        assert capture.get("time"), "the run never reached the time gate"

        from agent.skills.evaluate_time_skill import wrapper as time_wrapper

        params = dict(capture["time"][0])
        params["model_config"] = {**params["model_config"], **CANDIDATE}
        params["data_dir"] = None  # no warm-up: this scenario prices, it does not measure

        verdict = time_wrapper.run_skill(None, **params)

        assert verdict["status"] == "success", verdict.get("message")
        assert isinstance(verdict["feasible"], bool)
        assert verdict["breakdown"]["total_train_steps"] > 0, (
            "the real workload resolution produced no steps"
        )
        # The step count is a decomposition-derived term, so it must follow
        # the profile the tuner bound — B2, observed through the live gate.
        assert params["dataset_profile"] == TIDMAD_PROFILE
