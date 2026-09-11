"""V20 FU-D-11 — a fixed candidate PLAN may be injected; results may not.

Gate 2 established that whether an acceptance run reaches the formal path at
all depends on which architecture the planner happens to invent. Three runs
failed for three unrelated reasons — a pre-flight budget overrun, an
immediate output collapse, and before those a probe-attribution defect — none
of them a defect in the behaviour under test.

This seam removes that dependency by supplying the typed `ProposalOutput`
directly. It bypasses **only** the proposer: implement, validate, trial,
HealthGate, winner selection, formal launch, authority, resume and
aggregation all still run on the real path.

The dangerous failure mode is not that it fails — it is that it could quietly
become a way to inject a RESULT. `ProposalOutput` has no field for a score,
record, gate verdict, authority verdict or incumbent, so Pydantic's default
`extra="ignore"` would silently discard one. Silent discarding is exactly the
defect class this PR family hit three times, so the loader refuses unknown
keys instead.
"""

from __future__ import annotations

import json

import pytest

from workflows.run_one_iteration import (
    load_validation_fixed_candidate_plan,
)

PLAN = {
    "model_name": "fixed_validation_candidate",
    "model_description": "A small, previously-passing candidate.",
    "mathematical_definition": "Conv1d stack; [B,T] int64 -> [B,256,T] float32.",
    "motivation": "Removes planner variance from the acceptance harness.",
    "expert_advice": {
        "focus_areas": ["stability"],
        "constraints": [],
        "known_failures": [],
        "suggested_directions": [],
        "rationale": "fixed validation plan",
    },
    "baseline_config": {"model_config": {}, "train_config": {}, "loss_config": {}},
}


def _write(tmp_path, payload, name="plan.json"):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


class TestTheSeamAcceptsAPlan:
    def test_no_path_means_the_proposer_decides(self):
        """The ordinary campaign case must be untouched."""
        assert load_validation_fixed_candidate_plan(None) is None

    def test_a_valid_plan_round_trips(self, tmp_path):
        loaded = load_validation_fixed_candidate_plan(_write(tmp_path, PLAN))
        assert loaded is not None
        assert loaded["plan"]["model_name"] == "fixed_validation_candidate"
        assert loaded["plan"]["baseline_config"] == PLAN["baseline_config"]


class TestProvenanceIsRecorded:
    """An acceptance run that bypassed the proposer must be able to prove
    WHICH plan it used. Provenance that exists only as a local variable and a
    log line proves nothing — that was the state of a first version of this
    seam, and it is the fourth instance in this PR family of a value produced
    and never delivered."""

    def test_the_loader_returns_source_hash_and_identity(self, tmp_path):
        """MUTATION TARGET: dropping the provenance half of the return."""
        loaded = load_validation_fixed_candidate_plan(_write(tmp_path, PLAN))
        prov = loaded["provenance"]
        assert prov["candidate_source"] == "fixed_validation_plan"
        assert len(prov["plan_sha256"]) == 64
        assert prov["resolved_model_name"] == "fixed_validation_candidate"
        assert prov["plan_path"].endswith("plan.json")

    def test_the_hash_is_over_the_bytes_actually_read(self, tmp_path):
        """A different plan must hash differently, and an identical plan
        written twice must hash the same — otherwise the recorded hash cannot
        identify what ran."""
        a = load_validation_fixed_candidate_plan(_write(tmp_path, PLAN, "a.json"))
        b = load_validation_fixed_candidate_plan(_write(tmp_path, PLAN, "b.json"))
        changed = {**PLAN, "model_name": "other_candidate"}
        c = load_validation_fixed_candidate_plan(_write(tmp_path, changed, "c.json"))

        assert a["provenance"]["plan_sha256"] == b["provenance"]["plan_sha256"]
        assert a["provenance"]["plan_sha256"] != c["provenance"]["plan_sha256"]

    def test_every_manifest_branch_stamps_the_provenance(self):
        """MUTATION TARGET: stamping it on the healthy path only.

        Checked per AST call node. A failed iteration is exactly when you
        need to know which candidate ran — the §19.1 lesson, applied to a
        different field.
        """
        import ast
        from pathlib import Path

        launcher = (
            Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "run_one_iteration.py"
        )
        tree = ast.parse(launcher.read_text(encoding="utf-8"))
        calls, undeclared = 0, []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "write_manifest":
                continue
            calls += 1
            if "fixed_candidate_provenance" not in {kw.arg for kw in node.keywords}:
                undeclared.append(node.lineno)

        assert calls >= 5, f"expected every manifest branch; found {calls}"
        assert undeclared == [], (
            f"write_manifest called without fixed_candidate_provenance at lines "
            f"{undeclared}; those branches cannot say which candidate ran"
        )

    def test_the_manifest_carries_the_key_even_when_absent(self, tmp_path):
        """`None` must be recorded explicitly, so a reader can tell
        "the proposer chose" from "nobody wrote the field"."""
        from workflows.run_one_iteration import write_manifest

        manifest = write_manifest(iter_dir=str(tmp_path), run_name="prov", results=[], crashed=True)
        assert "fixed_candidate_provenance" in manifest
        assert manifest["fixed_candidate_provenance"] is None


class TestResultsCanNeverEnterThroughTheSeam:
    """The property the whole seam is judged on."""

    @pytest.mark.parametrize(
        "contraband",
        [
            {"denoising_score": 1.234},
            {"best_denoising_score": 9.9},
            {"all_records": [{"exp_id": "e1", "denoising_score": 5.0}]},
            {"health_gate_results": [{"gate_id": "g", "passed": True}]},
            {"scientific_authority": {"authoritative": True}},
            {"best_valid_formal_exp_id": "f1"},
        ],
        ids=[
            "score",
            "best-score",
            "records",
            "gate-verdicts",
            "authority-verdict",
            "incumbent-pointer",
        ],
    )
    def test_a_results_bearing_key_refuses_the_launch(self, tmp_path, contraband):
        """MUTATION TARGET: dropping the unknown-key check.

        Without it Pydantic silently ignores every one of these and the run
        proceeds, reporting a deterministic acceptance while a result was
        smuggled past the boundary. The failure would be invisible.
        """
        payload = {**PLAN, **contraband}
        with pytest.raises(SystemExit) as exc:
            load_validation_fixed_candidate_plan(_write(tmp_path, payload))
        message = str(exc.value)
        assert next(iter(contraband)) in message
        assert "never enter" in message or "not part of a candidate plan" in message

    def test_the_schema_itself_carries_no_result_field(self):
        """The structural guarantee behind the check: even if the loader were
        bypassed, the type cannot express a result."""
        from agent.schemas.proposal import ProposalOutput

        forbidden = {
            "denoising_score",
            "best_denoising_score",
            "all_records",
            "health_gate_results",
            "scientific_authority",
            "best_valid_formal_exp_id",
        }
        assert forbidden & set(ProposalOutput.model_fields) == set()


class TestItFailsClosed:
    """A run that asked for a fixed candidate must never silently get an
    invented one — that would report a determinism it did not have."""

    def test_a_missing_file_refuses_rather_than_falling_back(self, tmp_path):
        with pytest.raises(SystemExit, match="cannot read"):
            load_validation_fixed_candidate_plan(str(tmp_path / "absent.json"))

    def test_malformed_json_refuses(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit, match="not valid JSON"):
            load_validation_fixed_candidate_plan(str(p))

    def test_a_non_object_payload_refuses(self, tmp_path):
        with pytest.raises(SystemExit, match="must hold a JSON object"):
            load_validation_fixed_candidate_plan(_write(tmp_path, ["a", "list"]))

    def test_an_incomplete_plan_refuses(self, tmp_path):
        incomplete = {k: v for k, v in PLAN.items() if k != "mathematical_definition"}
        with pytest.raises(SystemExit, match="not a valid"):
            load_validation_fixed_candidate_plan(_write(tmp_path, incomplete))


class TestOnlyTheProposerIsBypassed:
    """Reachability: the seam must skip the proposer and nothing else.

    Structural, because reaching the branch needs a full real iteration —
    which is the very cost this seam exists to make deterministic.
    """

    @staticmethod
    def _workflow_source() -> str:
        import inspect

        from workflows import model_exploration

        return inspect.getsource(model_exploration)

    def test_the_proposer_call_is_inside_the_else_branch(self):
        """MUTATION TARGET: running the proposer anyway, or skipping more.

        The fixed plan must replace `_propose_agent.run(...)` — if that call
        were left unconditional the seam would do nothing, and if the bypass
        wrapped more than the proposer it would skip real work.
        """
        src = self._workflow_source()
        assert "if launch.validation_fixed_candidate_plan is not None:" in src
        block = src[src.index("if launch.validation_fixed_candidate_plan is not None:") :][:1400]
        assert "ProposalOutput.model_validate(" in block
        assert 'candidate_source = "fixed_validation_plan"' in block
        # The proposer still exists, on the other branch.
        assert "_propose_agent.run(propose_input)" in block

    @pytest.mark.parametrize(
        "stage",
        [
            "_impl_agent.run(",
            "_valid_agent.run(",
            "_tune_agent.run(",
        ],
    )
    def test_downstream_stages_are_not_conditional_on_the_plan(self, stage):
        """MUTATION TARGET: widening the bypass to skip real execution.

        Implement, validate and tune must run whether or not the candidate
        was fixed — otherwise the acceptance run would prove nothing about
        the path it claims to validate.
        """
        src = self._workflow_source()
        assert stage in src, f"{stage} disappeared from the workflow"
        before = src[: src.index(stage)]
        # The nearest enclosing guard must not be the fixed-plan branch.
        assert "if validation_fixed_candidate_plan is not None:" not in before[-600:], (
            f"{stage} sits inside the fixed-plan bypass; the seam must skip ONLY the proposer"
        )

    def test_the_launcher_forwards_the_plan_to_the_workflow(self):
        """MUTATION TARGET: parsing the flag and never passing it on."""
        import ast
        from pathlib import Path

        launcher = (
            Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "run_one_iteration.py"
        )
        # Step 09.5a C3: the launcher binds it one level deeper, inside the
        # WorkflowLaunchConfig it constructs. Same forwarding invariant.
        from tests.helpers.launcher_bindings import workflow_call_bindings

        forwarded = "validation_fixed_candidate_plan" in workflow_call_bindings(launcher)
        assert forwarded, (
            "run_workflow is called without validation_fixed_candidate_plan, so "
            "the flag would be accepted and silently ignored"
        )
