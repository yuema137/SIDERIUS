"""V21 PR E — E2: the candidate identity transport, end to end.

The id is SYSTEM-minted in the proposer's ``run()`` — after the LLM JSON
is parsed, before persistence — and travels **inside the objects** through
the three protocols, is explicitly echoed by the implementor (both
construction sites) and the validator (no generic echo exists, §0.J), and
is stamped onto every ``ExperimentRecord`` at the ``_emit_record``
validate-and-persist seam.

What this module proves that grep cannot:

1. the id that arrives at ``HyperparamTuningInput`` **is the minted
   string**, having crossed every hop through the REAL protocol functions
   and REAL node ``run()`` bodies — not a reimplementation (B1b's P2 and
   PR D's M-D3 both survived exactly that mistake);
2. the LLM cannot supply an id (mint overwrites; parser whitelists never
   accepted the key);
3. O-E-4: two proposer runs mint two different ids;
4. O-E-5: two different ids are behaviourally inert — identical outputs,
   only the label differs;
5. absence stays absence at every hop, and the fixed-plan seam REFUSES an
   operator-supplied id rather than accepting an identity nobody minted.

Design doc: ``docs/design/v21_priorities/pr_e_proposal_scale_funnel.md``
Commit E2.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord
from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import ProposalInput
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from tests.unit.agent.ml_code_validator_agent.test_validator_agent import (
    make_input as make_validator_input,
)
from tests.unit.agent.ml_model_implementor.test_implementor_agent import (
    FAKE_CODE_RESPONSE as IMPL_CODE_RESPONSE,
)
from tests.unit.agent.ml_model_implementor.test_implementor_agent import (
    FAKE_REASONING as IMPL_REASONING,
)
from tests.unit.agent.ml_model_proposal_agent.test_proposal_agent import (
    FAKE_COMMIT_RESPONSE,
    FAKE_INTERPRETATION,
    FAKE_REASONING,
)

_REPO = Path(__file__).resolve().parents[4]


def _storage(tmp_path, run_name="e2") -> StorageConfig:
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name=run_name),
    )


def _run_proposer(tmp_path, commit_response=None, run_name="e2"):
    with patch("nodes.ml_model_proposal_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate_text.return_value = FAKE_REASONING
        MockBridge.return_value.generate.return_value = commit_response or FAKE_COMMIT_RESPONSE
        agent = MLModelProposalAgent(provider="gemini", model_id="test-model")
        agent.bridge = MockBridge.return_value
        return agent.run(
            ProposalInput(
                interpretation=FAKE_INTERPRETATION,
                existing_model_types=[],
                constraints=[],
                storage={
                    "backend": "local",
                    "local": {"workspace": str(tmp_path), "run_name": run_name},
                },
            )
        )


class TestMint:
    def test_the_system_mints_and_persists_the_id(self, tmp_path):
        out = _run_proposer(tmp_path)
        assert out.candidate_id is not None
        assert out.candidate_id.startswith("cand_")
        # Minted BEFORE persistence: the proposal JSON carries it.
        persisted = json.loads((tmp_path / "proposal_e2.json").read_text())
        assert persisted["candidate_id"] == out.candidate_id

    def test_two_proposer_runs_mint_two_different_ids(self, tmp_path):
        """O-E-4: a new proposer-emitted proposal IS a new candidate."""
        a = _run_proposer(tmp_path / "a", run_name="r1")
        b = _run_proposer(tmp_path / "b", run_name="r2")
        assert a.candidate_id != b.candidate_id

    def test_the_llm_cannot_supply_the_id(self, tmp_path):
        """The id is never LLM-generated: a candidate_id in the raw LLM JSON
        neither survives the parser whitelist nor the unconditional mint."""
        evil = dict(FAKE_COMMIT_RESPONSE)
        evil["candidate_id"] = "llm_supplied_evil"
        out = _run_proposer(tmp_path, commit_response=evil)
        assert out.candidate_id != "llm_supplied_evil"
        assert out.candidate_id.startswith("cand_")

    def test_the_id_is_not_derived_from_model_name(self, tmp_path):
        out = _run_proposer(tmp_path)
        assert out.model_name not in out.candidate_id


class TestTransportThroughRealHops:
    """Mint → protocol → node echo → protocol → node echo → protocol → input.

    Every hop is the REAL production function. Each carries from its
    IMMEDIATE upstream, so severing any echo breaks the end-to-end value.
    """

    def _drive_chain(self, tmp_path, run_name="e2"):
        proposal = _run_proposer(tmp_path, run_name=run_name)

        impl_input = local_full_spec(proposal, _storage(tmp_path, run_name))
        assert impl_input.candidate_id == proposal.candidate_id
        impl_input.plugin_dir = str(tmp_path / "models")
        impl_input.test_dir = str(tmp_path / "tests")

        impl_agent = MLModelImplementor.__new__(MLModelImplementor)
        impl_agent.bridge = MagicMock()
        impl_agent._registry = MagicMock()
        impl_agent.bridge.generate_text.return_value = IMPL_REASONING
        impl_agent.bridge.generate.return_value = IMPL_CODE_RESPONSE
        impl_out = impl_agent.run(impl_input)
        assert impl_out.candidate_id == proposal.candidate_id

        valid_input = local_all_fields(impl_out, _storage(tmp_path, run_name))
        assert valid_input.candidate_id == proposal.candidate_id

        # The validator needs a real loadable plugin; reuse the canonical
        # valid-plugin fixture but keep OUR candidate_id.
        fixture_input = make_validator_input(tmp_path, run_name=run_name)
        fixture_input.candidate_id = valid_input.candidate_id
        valid_agent = MLCodeValidatorAgent.__new__(MLCodeValidatorAgent)
        valid_agent.bridge = MagicMock()
        valid_agent.bridge.generate.return_value = {
            "passed": True,
            "spec_alignment": True,
            "implementation_issues": [],
            "trainability_concerns": [],
            "notes": "pseudo",
        }
        valid_out = valid_agent.run(fixture_input)
        assert valid_out.candidate_id == proposal.candidate_id

        tune_input = local_validated_model(valid_out, proposal, _storage(tmp_path, run_name))
        return proposal, impl_out, valid_out, tune_input

    def test_minted_id_reaches_the_tuner_input_and_every_artifact(self, tmp_path):
        proposal, _impl_out, _valid_out, tune_input = self._drive_chain(tmp_path)
        minted = proposal.candidate_id

        assert tune_input.candidate_id == minted
        # ...and every persisted native artifact carries it (§0.J: the
        # transport test ends ON DISK, not at schema construction).
        for stem in ("proposal", "implementor", "validation"):
            payload = json.loads((tmp_path / f"{stem}_e2.json").read_text())
            assert payload["candidate_id"] == minted, stem

    def test_absence_propagates_as_none_at_every_hop(self, tmp_path):
        """Legacy / non-proposer candidates: None in, None at every hop,
        nothing synthesised anywhere."""
        from agent.schemas.proposal import ExpertAdvice, ProposalOutput

        proposal = ProposalOutput(
            model_name="legacy_net",
            model_description="pre-PR-E proposal shape",
            mathematical_definition="—",
            motivation="—",
            expert_advice=ExpertAdvice(
                focus_areas=["—"],
                constraints=["—"],
                known_failures=["—"],
                suggested_directions=["—"],
                rationale="legacy fixture",
            ),
            baseline_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        )
        assert proposal.candidate_id is None
        impl_input = local_full_spec(proposal, _storage(tmp_path))
        assert impl_input.candidate_id is None

        fixture_input = make_validator_input(tmp_path, run_name="legacy")
        assert fixture_input.candidate_id is None
        valid_agent = MLCodeValidatorAgent.__new__(MLCodeValidatorAgent)
        valid_agent.bridge = MagicMock()
        valid_agent.bridge.generate.return_value = {
            "passed": True,
            "spec_alignment": True,
            "implementation_issues": [],
            "trainability_concerns": [],
            "notes": "pseudo",
        }
        valid_out = valid_agent.run(fixture_input)
        assert valid_out.candidate_id is None
        tune_input = local_validated_model(valid_out, proposal, _storage(tmp_path))
        assert tune_input.candidate_id is None

    def test_a_pre_pr_e_record_still_loads(self):
        rec = ExperimentRecord.model_validate(
            {
                "exp_id": "legacy_001",
                "status": "success",
                "model_type": "punet",
                "timestamp": "2026-01-01 00:00:00",
                "params": {},
            }
        )
        assert rec.candidate_id is None


class TestBranchBReuseEcho:
    """The implementor's SECOND output-construction site (§0.J): Branch B
    reuses an existing registered plugin without any LLM call — and the
    reused artifact still belongs to the CURRENT candidate. M-E2-7 survived
    the first mutation round precisely because no test drove this path."""

    def test_branch_b_reuse_keeps_the_current_candidates_id(self, tmp_path):
        from agent_generated._registry import CapabilityMetadata, CapabilityRegistry

        existing_path = tmp_path / "global_models" / "reused_net.py"
        existing_path.parent.mkdir(parents=True)
        existing_path.write_text("# stub plugin\n")
        registry = CapabilityRegistry(index_path=str(tmp_path / "_capability_index.json"))
        registry.register(
            CapabilityMetadata(
                name="reused_net",
                capability_type="model",
                file_path=str(existing_path),
                created_at="2026-08-08T00:00:00+00:00",
                source_iteration="iter_001",
                description="Reused stub.",
                mathematical_definition="y = x",
            )
        )
        agent = MLModelImplementor.__new__(MLModelImplementor)
        agent.bridge = MagicMock()
        agent._registry = registry
        out = agent.run(
            ImplementorInput(
                candidate_id="cand_branch_b",
                model_name="reused_net",
                model_description="x",
                mathematical_definition="x",
                baseline_config={
                    "model_config": {"model_name": "reused_net"},
                    "train_config": {},
                    "loss_config": {},
                },
                plugin_dir=str(tmp_path / "models"),
                test_dir=str(tmp_path / "tests"),
                storage=_storage(tmp_path, "bb"),
            )
        )
        agent.bridge.generate.assert_not_called()  # really Branch B
        assert out.candidate_id == "cand_branch_b"


class TestBehaviouralInertness:
    """O-E-5: identical operations under two different ids produce identical
    behavioural outputs — only the recorded label differs."""

    def test_validator_verdict_is_identical_under_two_ids(self, tmp_path):
        outs = []
        for sub, cid in (("a", "cand_one"), ("b", "cand_two")):
            d = tmp_path / sub
            d.mkdir()
            inp = make_validator_input(d, run_name="inert")
            inp.candidate_id = cid
            agent = MLCodeValidatorAgent.__new__(MLCodeValidatorAgent)
            agent.bridge = MagicMock()
            agent.bridge.generate.return_value = {
                "passed": True,
                "spec_alignment": True,
                "implementation_issues": [],
                "trainability_concerns": [],
                "notes": "pseudo",
            }
            outs.append(agent.run(inp))
        a, b = (o.model_dump() for o in outs)
        assert a.pop("candidate_id") == "cand_one"
        assert b.pop("candidate_id") == "cand_two"
        # test_output embeds the pytest-captured stdout, which contains the
        # two different tmp_path fixtures — environmental noise, not
        # behaviour. Assert both runs PASSED their tests, then exclude it.
        assert "1 passed" in a.pop("test_output")
        assert "1 passed" in b.pop("test_output")
        assert a == b, "a candidate_id changed validator behaviour (O-E-5 violation)"

    def test_tuner_input_construction_is_identical_under_two_ids(self, tmp_path):
        proposal_kwargs = dict(FAKE_COMMIT_RESPONSE)
        from agent.schemas.validator import ValidatorOutput

        def build(cid):
            v = ValidatorOutput(
                passed=True,
                candidate_id=cid,
                model_type="punet",
                plugin_registered=True,
                tests_passed=True,
                description_valid=True,
                config_fields_valid=True,
                instantiation_passed=True,
                gradient_check_passed=True,
                llm_review_passed=True,
            )
            from agent.schemas.proposal import ExpertAdvice, ProposalOutput

            p = ProposalOutput(
                candidate_id=cid,
                model_name="punet",
                model_description="x",
                mathematical_definition="—",
                motivation="—",
                expert_advice=ExpertAdvice(
                    focus_areas=["—"],
                    constraints=["—"],
                    known_failures=["—"],
                    suggested_directions=["—"],
                    rationale="—",
                ),
                baseline_config=proposal_kwargs.get(
                    "baseline_config",
                    {"model_config": {}, "train_config": {}, "loss_config": {}},
                ),
            )
            return local_validated_model(v, p, _storage(tmp_path)).model_dump()

        a, b = build("cand_one"), build("cand_two")
        assert a.pop("candidate_id") == "cand_one"
        assert b.pop("candidate_id") == "cand_two"
        assert a == b


class TestRecordStamp:
    def test_emit_record_stamps_the_id_before_validate_and_persist(self):
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _emit_record,
        )

        saved = []
        sandbox = MagicMock()
        sandbox.save_record.side_effect = saved.append
        record = {
            "exp_id": "e",
            "status": "success",
            "model_type": "m",
            "timestamp": "2026-01-01 00:00:00",
            "params": {},
        }
        _emit_record(sandbox, record, candidate_id="cand_stamp")
        assert saved[0]["candidate_id"] == "cand_stamp"

        record2 = dict(record)
        _emit_record(sandbox, record2)  # legacy path: absence stays absence
        assert saved[1]["candidate_id"] is None

    def test_every_emit_record_call_site_passes_the_id(self):
        """AST, not substring (§E.3d.9): each of the 12 production call sites
        must pass candidate_id explicitly. A new site that forgets it fails
        here rather than silently producing unjoinable records."""
        src = (
            _REPO / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
        ).read_text()
        tree = ast.parse(src)
        sites = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_emit_record"
            ):
                kw = {k.arg for k in node.keywords}
                sites.append((node.lineno, "candidate_id" in kw))
        assert len(sites) == 12, f"expected 12 call sites, found {len(sites)}"
        missing = [ln for ln, ok in sites if not ok]
        assert not missing, f"_emit_record call sites missing candidate_id=: {missing}"

    def test_output_dicts_echo_the_id_on_healthy_and_degraded_paths(self):
        """The run-level label survives BOTH exit paths, like the
        healthgate_mode echo it sits beside."""
        src = (
            _REPO / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
        ).read_text()
        assert src.count('"candidate_id": agent_input.candidate_id,') == 3, (
            "expected the echo in the provenance stamp, the healthy output "
            "dict and the degraded/partial output dict"
        )


class TestFixedPlanSeam:
    """The plan seam refuses an operator-supplied identity (O-E-4: only the
    system mints; a fixed-plan candidate deliberately runs id-less)."""

    def _write_plan(self, tmp_path, extra=None):
        plan = {
            "model_name": "fixed_net",
            "model_description": "fixed validation candidate",
            "mathematical_definition": "—",
            "motivation": "—",
            "expert_advice": {
                "focus_areas": ["—"],
                "constraints": ["—"],
                "known_failures": ["—"],
                "suggested_directions": ["—"],
                "rationale": "—",
            },
            "baseline_config": {
                "model_config": {},
                "train_config": {},
                "loss_config": {},
            },
        }
        plan.update(extra or {})
        path = tmp_path / "plan.json"
        path.write_text(json.dumps(plan))
        return str(path)

    def test_a_plan_carrying_candidate_id_refuses_the_launch(self, tmp_path):
        from sdsc_submission_scripts.run_one_iteration import (
            load_validation_fixed_candidate_plan,
        )

        path = self._write_plan(tmp_path, {"candidate_id": "cand_smuggled"})
        with pytest.raises(SystemExit, match="candidate_id"):
            load_validation_fixed_candidate_plan(path)

    def test_a_clean_plan_loads_with_no_identity(self, tmp_path):
        from sdsc_submission_scripts.run_one_iteration import (
            load_validation_fixed_candidate_plan,
        )

        path = self._write_plan(tmp_path)
        loaded = load_validation_fixed_candidate_plan(path)
        assert loaded is not None
        # The loader returns plan.model_dump(mode="json") under "plan"
        # (run_one_iteration.py:201), so the schema-defaulted key IS present
        # — with None, the deliberate id-less state of a fixed-plan candidate.
        assert loaded["plan"]["candidate_id"] is None


class TestNoBehaviouralKeyUsage:
    """Supporting grep-level check (O-E-5) — the behavioural proof is above;
    this catches the textual smell early."""

    def test_no_registry_dispatch_or_path_reads_the_id(self):
        forbidden_files = [
            "ml_models/plugin_loader.py",
            "core/sandbox_executor.py",
            "execute_tools/scoring_utils.py",
            "core/resume.py",
            "core/scientific_authority.py",
        ]
        for rel in forbidden_files:
            src = (_REPO / rel).read_text()
            assert "candidate_id" not in src, (
                f"{rel} references candidate_id — it must never key "
                "registration, dispatch, scoring or decisions (O-E-5)"
            )
