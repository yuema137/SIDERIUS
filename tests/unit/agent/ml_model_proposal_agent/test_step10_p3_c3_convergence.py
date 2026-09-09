"""Step 10 / P3 — C3: one reader, proven at the prompt boundary.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p3_proposer_typed_evidence.md`` §4.4 (the legacy adapter), §4.8 (the
convergence diagram), §7 C3; parent §11.2.

C1 proved the two entrypoints build EQUAL evidence values. That is necessary
and not sufficient: equal values could still be rendered by two different
readers that drift. This module closes the gap at the only place that matters
— the bytes the model receives.

The structural half of C3's claim (the raw dict and the dead mirror are gone,
the evidence is REQUIRED, and no proposer module reads a raw mapping) is owned
by ``tests/unit/nodes/test_step10_p3_proposer_evidence_census.py``. Byte parity
against the pre-migration goldens is owned by
``test_step10_p3_c0_baselines.py`` and the PB-4 / S1-E goldens. What is left,
and lives here, is the CONVERGENCE itself.
"""

from __future__ import annotations

import json

import pytest

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalInput, ReasoningPipelineConfig
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.dataset_config import bind_dataset_profile
from nodes.ml_model_proposal_agent.evidence_rendering import (
    render_legacy_interpretation_section,
)
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import _build_reasoning_prompt
from tests.helpers.two_family_profile import make_two_family_profile
from tests.unit.agent.ml_model_proposal_agent.test_step00_prompt_goldens import (
    fixture_proposal_input,
)
from tests.unit.agent.ml_model_proposal_agent.test_step10_p3_c0_baselines import (
    full_coverage_interpretation,
    legacy_absence_interpretation,
)

_INTERPRETATION_PROFILE = make_two_family_profile(num_files=20)


@pytest.fixture(autouse=True)
def _bind_interpretation_profile():
    """Validate nested score tables against an explicit synthetic topology."""
    with bind_dataset_profile(_INTERPRETATION_PROFILE):
        yield


def _legacy_input(tmp_path, evidence) -> ProposalInput:
    base = fixture_proposal_input(tmp_path, mode="explore")
    return base.model_copy(
        update={
            "interpretation_evidence": evidence,
            "reasoning_pipeline": ReasoningPipelineConfig(stages=[]),
        }
    )


class TestTheTwoEntrypointsRenderIdenticalBytes:
    """§4.8 — the protocol and the standalone CLI converge on ONE prompt."""

    @pytest.mark.parametrize(
        ("name", "dump"),
        [
            ("full coverage", full_coverage_interpretation()),
            ("legacy artifact", legacy_absence_interpretation()),
        ],
    )
    def test_protocol_and_cli_produce_the_same_legacy_prompt(
        self, tmp_path, name: str, dump: dict
    ) -> None:
        """Two SOURCES, one shape, one prompt.

        The protocol path builds evidence from an in-memory
        ``InterpretationOutput.model_dump()``; the CLI path builds it from the
        persisted ``interpretation_{run}.json``. Going through the filesystem
        rather than reusing a dict is what makes this a claim about the real
        standalone entrypoint. Before P3 these were two independent readers of
        one dict and had already drifted onto fields the other never saw
        (parent §3.6) — the whole point of the migration is that this
        comparison is now trivially true by construction, so a future divergence
        can only come from someone reintroducing a second reader.
        """
        if name == "full coverage":
            output = InterpretationOutput.model_validate(dump)
            in_memory = output.model_dump()
            artifact = tmp_path / "interpretation_p3c3.json"
            artifact.write_text(output.model_dump_json(), encoding="utf-8")
            from_disk = json.loads(artifact.read_text(encoding="utf-8"))
        else:
            # A legacy artifact never round-trips through the schema — that is
            # exactly what makes it legacy. Both sides load the same bytes.
            artifact = tmp_path / "interpretation_legacy.json"
            artifact.write_text(json.dumps(dump), encoding="utf-8")
            in_memory = dump
            from_disk = json.loads(artifact.read_text(encoding="utf-8"))

        via_protocol = _build_reasoning_prompt(
            _legacy_input(tmp_path, build_proposer_evidence(in_memory))
        )
        via_cli = _build_reasoning_prompt(
            _legacy_input(tmp_path, build_proposer_evidence(from_disk))
        )
        assert via_protocol == via_cli, f"{name}: the two entrypoints rendered different bytes"
        assert "## Interpretation Summary" in via_protocol

    def test_the_comparison_can_fail(self) -> None:
        """Anti-vacuity: two DIFFERENT dumps must render differently.

        Without this, a renderer that emitted a constant would satisfy every
        equality above.
        """
        full = render_legacy_interpretation_section(
            build_proposer_evidence(full_coverage_interpretation())
        )
        legacy = render_legacy_interpretation_section(
            build_proposer_evidence(legacy_absence_interpretation())
        )
        assert full != legacy


class TestTheLegacyAdapterIsTheOneRenderer:
    """The adapter renders the region; the node module only splices it."""

    def test_the_adapter_output_appears_verbatim_in_the_legacy_prompt(self, tmp_path) -> None:
        """Reachability: deleting the splice must be observable.

        A test that only checked the adapter in isolation would stay green if
        the node stopped calling it, which is the failure mode the P3-V1
        incident recorded on this very surface (a block wired into one branch
        and never reaching the other).
        """
        evidence = build_proposer_evidence(full_coverage_interpretation())
        section = "\n".join(render_legacy_interpretation_section(evidence))
        prompt = _build_reasoning_prompt(_legacy_input(tmp_path, evidence))
        assert section in prompt

    def test_the_dead_reads_render_nothing_because_they_cannot_be_carried(self) -> None:
        """The two deleted branches, closed at the type rather than the renderer.

        ``per_file_comparison`` / ``efficiency_comparison`` were readable only
        because the carrier was ``dict[str, Any]``. A dump containing them now
        projects to evidence that simply has no such fields, so the headings
        cannot appear no matter what an upstream artifact contains.
        """
        dump = dict(full_coverage_interpretation())
        dump["per_file_comparison"] = "SHOULD NOT RENDER"
        dump["efficiency_comparison"] = "SHOULD NOT RENDER EITHER"
        rendered = "\n".join(render_legacy_interpretation_section(build_proposer_evidence(dump)))
        assert "SHOULD NOT RENDER" not in rendered
        assert "Per-File Comparison" not in rendered
        assert "Efficiency Comparison" not in rendered


class TestTheLegacyAbsenceSemanticsSurvive:
    """A legacy artifact must still render, and render the same way."""

    def test_a_missing_total_experiments_still_reads_unknown(self) -> None:
        """The dict path defaulted a MISSING key to the string ``'unknown'``.

        A present ``None`` and an absent key rendered differently, and the
        typed field's default is ``None`` — so a naive migration would have
        printed "None" where an operator's legacy run used to print "unknown".
        Unreachable in production (the field is REQUIRED upstream) but reachable
        from the CLI's own artifacts, which is exactly who this path serves.
        """
        rendered = "\n".join(
            render_legacy_interpretation_section(build_proposer_evidence({"model_types": []}))
        )
        assert "Total experiments   : unknown" in rendered
        assert "Total experiments   : None" not in rendered

    def test_a_present_total_experiments_renders_its_value(self) -> None:
        """Anti-vacuity for the case above."""
        rendered = "\n".join(
            render_legacy_interpretation_section(
                build_proposer_evidence({"model_types": [], "total_experiments": 7})
            )
        )
        assert "Total experiments   : 7" in rendered

    def test_an_empty_legacy_artifact_does_not_crash(self, tmp_path) -> None:
        """The CLI's worst realistic input: an artifact carrying almost nothing."""
        prompt = _build_reasoning_prompt(_legacy_input(tmp_path, build_proposer_evidence({})))
        assert "## Interpretation Summary" in prompt


class TestNoProductionModuleReferencesTheRemovedFields:
    """The C3 sweep, executable rather than a one-time grep."""

    def test_the_schema_no_longer_declares_either_carrier(self) -> None:
        assert "interpretation" not in ProposalInput.model_fields
        assert "per_model_score_tables" not in ProposalInput.model_fields

    def test_the_protocol_populates_only_the_typed_evidence(self, tmp_path) -> None:
        from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
            local_full_context,
        )

        output = InterpretationOutput.model_validate(full_coverage_interpretation())
        result = local_full_context(
            output,
            StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="p3c3"),
            ),
        )
        assert result.interpretation_evidence == build_proposer_evidence(output.model_dump())
