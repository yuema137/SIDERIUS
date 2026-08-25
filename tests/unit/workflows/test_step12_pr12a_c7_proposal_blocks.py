"""Step 12 / PR-12a — C7-3: ProposalTaskBlocks (D-12a-6).

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C7 / D-12a-6, blocks Pr1/Pr2/Pr3 of the
§8.9 classification table.

The proposer's prompts hardcoded that the architect specialises in "signal
denoising", that classification emits a distribution over "256 amplitude bins",
and how to rank a per-file ``Impact_Score`` table — TIDMAD science presented to
whatever task happened to be running. D-12a-6 mirrors 09b's interpretation
mechanism one node over: FRAMEWORK owns the keys and placement, TASK owns the
prose, absent ⇒ ZERO added bytes.

WHAT MAKES THIS A RELOCATION AND NOT A REWRITE: all three TIDMAD values in
``configs/task_proposal/tidmad.yaml`` are asserted byte-VERBATIM against the
live prompts below. That is what lets the un-composed rendering be unchanged.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

import pytest

from agent.prompt_templates.proposal.task_blocks import (
    LEGACY_DEFAULT_TASK_PROPOSAL_CONFIG,
    load_proposal_task_blocks,
)
from agent.schemas.proposal import ProposalTaskBlocks
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    PROPOSAL_REASONING_PROMPT,
    render_architect_role,
    render_output_contract_guidance,
    render_proposal_evidence_reading,
)
from tests.helpers.composed_manifest import write_complete_manifest
from workflows.model_exploration import resolve_run_proposal_blocks
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
PROPOSER = REPO_ROOT / "nodes" / "ml_model_proposal_agent" / "ml_model_proposal_agent.py"
PROPOSING_STAGE = REPO_ROOT / "agent" / "prompt_templates" / "proposal" / "proposing_stage.md"
ADAPTER = REPO_ROOT / "agent" / "prompt_templates" / "proposal" / "task_blocks.py"


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


class TestTidmadsProseWasRELOCATEDNotRewritten:
    """The property the whole legacy-parity claim rests on."""

    def test_all_three_values_are_byte_verbatim_against_the_live_prompts(self):
        blocks = load_proposal_task_blocks()

        # Pr1 — the role clause, as the prompt renders it.
        assert (
            render_architect_role(blocks) == " specialising in deep learning for signal denoising"
        )

        # Pr2 — the sentence pair, exactly as `proposing_stage.md` carried it.
        assert blocks.output_contract_guidance == (
            "Regression predicts the denoised waveform directly;\n"
            "classification predicts a distribution over 256 amplitude bins per timestep."
        )

        # Pr3 — the per-file protocol, still recognisable line for line.
        assert blocks.evidence_reading is not None
        assert blocks.evidence_reading.startswith(
            "   - Read each model's per-file score table by `Impact_Score` descending"
        )
        assert blocks.evidence_reading.rstrip().endswith("or from a fixed file-index label.")

    def test_the_prose_no_longer_lives_in_the_prompts(self):
        """The other half: a relocation that left a copy behind would render
        TIDMAD's science on a composed run anyway."""
        proposer = PROPOSER.read_text(encoding="utf-8")
        stage = PROPOSING_STAGE.read_text(encoding="utf-8")

        assert "specialising in deep learning for signal denoising" not in proposer
        assert "{ARCHITECT_ROLE}" in proposer
        assert "Impact_Score` descending" not in proposer
        assert "{EVIDENCE_READING}" in proposer
        assert "256 amplitude bins" not in stage
        assert "{OUTPUT_CONTRACT_GUIDANCE}" in stage


class TestTheRelocationIsBYTE_EXACT:
    """The strongest form of the legacy-parity claim available here.

    C7-2 could only show that the tuner's RENDERED manifest did not move.
    For the proposer there is a stricter proof: substituting TIDMAD's declared
    blocks back into the tokenized templates reproduces the PRE-C7 bytes
    exactly — the C0 fixture's original sha256, hardcoded below rather than
    recomputed, so this compares against the recorded past and not against
    itself.

    If anyone ever "tidies" a value in `configs/task_proposal/tidmad.yaml`,
    this turns RED and names the surface. That is the whole safety argument
    for calling D-12a-6 a relocation.
    """

    #: The C0 baseline shas, captured at `eeb073dc` BEFORE any block moved.
    PRE_C7_SHA: ClassVar[dict[str, str]] = {
        "PROPOSAL_REASONING_PROMPT": (
            "7c69ce7bae2509b830ad2cdfd8c239390554215e9feed259e83488845f1b9071"
        ),
        "proposing_stage.md": ("8d52e15675dcd6f5b96710dcc33809470123517e3d6b2734fd57300040d21ff1"),
    }

    def test_substituting_tidmads_blocks_reproduces_the_original_bytes(self):
        import hashlib

        blocks = load_proposal_task_blocks()

        reasoning = (
            PROPOSAL_REASONING_PROMPT.replace("{ARCHITECT_ROLE}", render_architect_role(blocks))
            .replace("{EVIDENCE_READING}", render_proposal_evidence_reading(blocks))
            # C7-5's two additional Pr3 clauses in the same constant. The
            # digest is UNCHANGED — which is the point: closing the residue
            # relocated more prose out of the template and the legacy bytes
            # still reproduce exactly.
            .replace("{TARGET_SELECTOR_CLAUSE}", blocks.target_strategy_selector_clause or "")
            .replace("{EVIDENCE_CITATION_CLAUSE}", blocks.evidence_citation_clause or "")
        )
        assert (
            hashlib.sha256(reasoning.encode("utf-8")).hexdigest()
            == self.PRE_C7_SHA["PROPOSAL_REASONING_PROMPT"]
        )

        stage = PROPOSING_STAGE.read_text(encoding="utf-8").replace(
            "{OUTPUT_CONTRACT_GUIDANCE}", render_output_contract_guidance(blocks)
        )
        assert (
            hashlib.sha256(stage.encode("utf-8")).hexdigest()
            == self.PRE_C7_SHA["proposing_stage.md"]
        )


class TestAbsentBlocksRenderZEROBytes:
    """D-12a-6's headline contract, and the reason this is safe to ship for a
    task that declares nothing."""

    @pytest.mark.parametrize("blocks", [None, ProposalTaskBlocks()])
    def test_every_renderer_returns_the_empty_string(self, blocks):
        assert render_architect_role(blocks) == ""
        assert render_proposal_evidence_reading(blocks) == ""
        assert render_output_contract_guidance(blocks) == ""

    def test_the_role_line_degrades_to_a_role_with_no_specialism(self):
        """Not a named absence, and deliberately not TIDMAD's: the clause
        simply disappears, leaving a grammatical sentence."""
        rendered = PROPOSAL_REASONING_PROMPT.replace(
            "{ARCHITECT_ROLE}", render_architect_role(None)
        )
        assert "You are a senior ML architect." in rendered
        assert "denoising" not in rendered.split("\n")[0]


class TestTheAdapterIsBOUNDEDAndNotAMechanism:
    """The 09b census shape, one node over. The single task-identity
    occurrence must be a default-path CONSTANT — never a branch, a table or
    an inference."""

    def test_exactly_one_task_identity_constant_and_no_conditional_reads_it(self):
        tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))

        constants = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign | ast.Assign)
            for target in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
            if isinstance(target, ast.Name) and "TIDMAD" in target.id.upper()
        ]
        assert len(constants) <= 1

        # No test/branch anywhere may name a task.
        for node in ast.walk(tree):
            if isinstance(node, ast.If | ast.IfExp | ast.Match):
                rendered = ast.dump(node.test if not isinstance(node, ast.Match) else node.subject)
                for forbidden in ("tidmad", "pets", "davis"):
                    assert forbidden not in rendered.lower(), (
                        "a task name entered a CONDITIONAL in the bounded adapter — "
                        "it is packaging, not a dispatch mechanism"
                    )

    def test_the_default_path_names_exactly_one_task(self):
        assert LEGACY_DEFAULT_TASK_PROPOSAL_CONFIG.endswith("tidmad.yaml")
        source = ADAPTER.read_text(encoding="utf-8")
        assert source.lower().count('"tidmad.yaml"') == 1

    def test_the_load_is_FAIL_CLOSED(self, tmp_path):
        missing = tmp_path / "nope.yaml"
        with pytest.raises(FileNotFoundError):
            load_proposal_task_blocks(str(missing))

        not_a_mapping = tmp_path / "list.yaml"
        not_a_mapping.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_proposal_task_blocks(str(not_a_mapping))

        unknown_key = tmp_path / "typo.yaml"
        unknown_key.write_text("architekt_role: oops\n", encoding="utf-8")
        with pytest.raises(ValueError, match="failed the ProposalTaskBlocks contract"):
            load_proposal_task_blocks(str(unknown_key))


class TestTheManifestSection:
    """``proposal_blocks:`` composes exactly like its ``interpretation_blocks``
    sibling — two families that behaved differently would be two things to
    learn instead of one."""

    def test_an_absent_section_composes_to_None(self, tmp_path):
        # `None` REMOVES the section — the shipped base manifest now declares
        # it (C8), so a bare copy would be testing the declared case.
        composition = compose_run_task_bindings(
            str(write_complete_manifest(tmp_path, proposal_blocks=None))
        )
        assert composition.proposal_blocks is None

    def test_an_explicit_none_composes_to_None(self, tmp_path):
        manifest = write_complete_manifest(tmp_path, proposal_blocks={"none": True})
        assert compose_run_task_bindings(str(manifest)).proposal_blocks is None

    def test_a_declared_section_composes_the_typed_value(self, tmp_path):
        declaration = tmp_path / "mine.yaml"
        declaration.write_text("architect_role: variable-length tabular regression\n", "utf-8")
        manifest = write_complete_manifest(tmp_path, proposal_blocks={"config": str(declaration)})
        blocks = compose_run_task_bindings(str(manifest)).proposal_blocks
        assert blocks is not None
        assert blocks.architect_role == "variable-length tabular regression"
        assert blocks.evidence_reading is None

    def test_a_declared_but_unloadable_section_FAILS_CLOSED(self, tmp_path):
        manifest = write_complete_manifest(
            tmp_path, proposal_blocks={"config": str(tmp_path / "absent.yaml")}
        )
        with pytest.raises(TaskCompositionError, match="proposal_blocks declaration"):
            compose_run_task_bindings(str(manifest))

    def test_a_malformed_section_FAILS_CLOSED(self, tmp_path):
        manifest = write_complete_manifest(tmp_path, proposal_blocks="not a mapping")
        with pytest.raises(TaskCompositionError, match="must be a mapping"):
            compose_run_task_bindings(str(manifest))


class TestFingerprintParticipation:
    """Declared proposer science is SEMANTIC — it changes what the model is
    asked — so it moves the run's identity. Undeclared must not."""

    #: Measured AT `eeb073dc` — before the section existed — in a detached
    #: worktree, so these compare against the recorded past rather than
    #: against the code under test.
    #:
    #: MOVED at Step 12 / PR-12d D4c, with the reason. The Pets/DAVIS
    #: fixtures' secondary metrics were bound to implementations computing
    #: something else — `psnr` and `mae` both to `GlobalMseMetric`, `macro_f1`
    #: to `AccuracyMetric` (F-12d-3). Rebinding to the packs' own
    #: implementations turns `implementation:` from a `module:` ref into a
    #: `file:` ref, which contributes its CONTENT DIGEST. The composition
    #: genuinely changed; the fingerprint rule did not.
    #:
    #: TIDMAD's shipped fingerprint is UNTOUCHED at `9125bf58…`.
    #:
    #: MOVED AGAIN at Step 12 / PR-12d, once per pack and each for its own
    #: reason — D6 for DAVIS, D5 for Pets. Both fixtures stopped carrying the
    #: fabricated TIDMAD-shaped `dataset_profile` F-12d-4 condemned
    #: (`psd_segment_length`, `segments_per_file`, `.h5` shard patterns for
    #: tasks that have clips and images): DAVIS' was re-authored into the
    #: Q-12-4 shape, and Pets' was DELETED so the fixture resolves the pack's
    #: SHIPPED `declared/dataset_profile.json` — exactly one Pets profile now
    #: exists. The profile's wire form enters the semantic fingerprint, so
    #: both values move because the DECLARATIONS genuinely changed; the
    #: fingerprint rule did not.
    #:
    #: TIDMAD's shipped fingerprint remains `9125bf58…` and is asserted
    #: separately — no TIDMAD declaration was touched by either commit.
    #: MOVED a THIRD time, and NOT because this fixture's own YAML changed —
    #: it did not. Both fixtures bind their SECONDARY metric through a `file:`
    #: ref into `_pets_metrics.py` / `_davis_metrics.py`, and a `file:` ref's
    #: CONTENT DIGEST enters the fingerprint. F-12d-19 added
    #: `PetsAccuracyMetric` / `DavisMseMetric` to those same files (to give the
    #: SHIPPED manifest's primary a binding that accepts the composed call),
    #: which moved the digest — and with it, every fixture referencing the
    #: file, whether or not the fixture's own content moved.
    #:
    #: The generalisable point: a `file:` ref's identity is the FILE's content,
    #: not the symbol composed. Two manifests binding different symbols out of
    #: the same file share one identity, and editing the file for one manifest
    #: silently reopens every other manifest's pinned fingerprint.
    PRE_SECTION_FINGERPRINT: ClassVar[dict[str, str]] = {
        "davis": "48b5e53e389f349396b83446e398a9ad02b6b3c36146e83ab4e5e668584d3b94",
        "pets": "600d7c2eea82fb03e56c41640d9837336259918293861eacdcc0c7d78a95bdfb",
    }

    @pytest.mark.parametrize("task", ["davis", "pets"])
    def test_an_undeclared_manifest_fingerprints_UNCHANGED(self, task):
        """If the key were unconditional, every existing composed run's resume
        would fail for a reason with no scientific content.

        Step 12 / PR-12a C8 re-pointed this at DAVIS and Pets. It used to read
        the TIDMAD fixture, which now DECLARES both new sections — so it would
        have been asserting the opposite property against a moved value. These
        two declare nothing and their pre-section fingerprints are unchanged.
        """
        composition = compose_run_task_bindings(
            str(REPO_ROOT / "tests" / "fixtures" / "step10_p1" / task / "composition.yaml")
        )
        assert composition.proposal_blocks is None
        assert composition.implementor_blocks is None
        assert composition.semantic_fingerprint == self.PRE_SECTION_FINGERPRINT[task]

    def test_the_SHIPPED_tidmad_manifest_DID_move_and_that_is_correct(self):
        """The declared consequence, stated rather than discovered.

        `configs/task_composition/tidmad.yaml` now declares `proposal_blocks:`
        and `implementor_blocks:`, so its identity moved
        `d6628a93…` -> `5836cb0a…`. A composed TIDMAD run started before this
        PR therefore FAILS ITS RESUME CLOSED — which is the designed behaviour
        for a composition that gained two real declared sources, even though
        the rendered prompt bytes happen to be identical. The alternative,
        declaring nothing, would mean a composed TIDMAD run silently proposes
        and implements with no science at all.
        """
        shipped = compose_run_task_bindings(
            str(REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml")
        )
        assert shipped.proposal_blocks is not None
        assert shipped.implementor_blocks is not None
        assert shipped.semantic_fingerprint != (
            "d6628a93fcb3578ca32812f39246f2b51abeecbd24d21df56856ea0ef9c56d3a"
        )

    def test_declaring_blocks_MOVES_the_fingerprint(self, tmp_path):
        bare = compose_run_task_bindings(
            str(write_complete_manifest(tmp_path / "bare", proposal_blocks=None))
        )

        declaration = tmp_path / "blocks.yaml"
        declaration.write_text("architect_role: something else entirely\n", encoding="utf-8")
        declared = compose_run_task_bindings(
            str(
                write_complete_manifest(
                    tmp_path / "declared", proposal_blocks={"config": str(declaration)}
                )
            )
        )
        assert declared.semantic_fingerprint != bare.semantic_fingerprint

    def test_changing_the_PROSE_moves_it_too(self, tmp_path):
        """Anti-vacuity: a fingerprint that keyed on the section's PRESENCE
        rather than its CONTENT would pass the row above and still let an
        edited declaration resume against a stale lock."""
        first = tmp_path / "a.yaml"
        first.write_text("architect_role: one\n", encoding="utf-8")
        second = tmp_path / "b.yaml"
        second.write_text("architect_role: two\n", encoding="utf-8")

        a = compose_run_task_bindings(
            str(write_complete_manifest(tmp_path / "wa", proposal_blocks={"config": str(first)}))
        )
        b = compose_run_task_bindings(
            str(write_complete_manifest(tmp_path / "wb", proposal_blocks={"config": str(second)}))
        )
        assert a.semantic_fingerprint != b.semantic_fingerprint


class TestTheWorkflowResolver:
    def test_un_composed_resolves_the_bounded_adapter(self):
        blocks = resolve_run_proposal_blocks(None)
        assert blocks is not None
        assert blocks.architect_role == "deep learning for signal denoising"

    def test_composed_supplies_its_OWN_declaration(self):
        composition = compose_run_task_bindings(
            str(REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "pets" / "composition.yaml")
        )
        assert resolve_run_proposal_blocks(composition) is None

    def test_a_composed_run_declaring_NONE_gets_None_not_TIDMADs(self):
        """The composed half of the contract, and the one that matters: a task
        that declares no proposer science must NOT inherit TIDMAD's."""
        composition = compose_run_task_bindings(
            str(REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "davis" / "composition.yaml")
        )
        resolved = resolve_run_proposal_blocks(composition)
        assert resolved is None
        assert render_architect_role(resolved) == ""
        assert render_proposal_evidence_reading(resolved) == ""
