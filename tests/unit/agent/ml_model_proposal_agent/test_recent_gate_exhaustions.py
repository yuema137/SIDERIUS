"""
Phase N (§14.N.3-N.4) — proposer prompt: [RECENT GATE EXHAUSTIONS] block.

Aggregate-window successor to the K.7.6 singular block. Covers the helper
that renders the §14.N.3 block from a (possibly empty) list of up to
``GateExhaustionInfo`` entries, plus the two injection points that splice
the rendered block into the proposer's user/system prompts:

  * Helper truth-table: [] → "" (no empty section). 1/2/3-entry lists →
    block with header-arithmetic, per-entry ``iter N-k`` labels, rules
    between entries, and the "switch family" closing guidance.
  * Legacy mode: ``_build_reasoning_prompt`` includes the block when
    ``inp.recent_gate_exhaustions`` is non-empty; omits it when empty.
  * Pipeline mode: ``template_vars`` carries the rendered block under
    ``recent_gate_exhaustions_block``; the proposing-stage template
    substitutes the placeholder so the LLM sees the block in its system
    prompt; placeholder is collapsed to "" when the list is empty.

Field numeric-to-string rendering (``n/a`` for disabled axes, factor
two-decimal ``×`` suffix, etc.) is inherited from the K.7.6 helper and
not re-tested here — see §14.N.4.
"""

from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest

from agent.prompt_templates.proposal import load_stage_prompt
from agent.schemas.hyperparam_tuning import GateExhaustionInfo
from agent.schemas.proposal import (
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
)
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.utils.architectural_pattern_tagger import ARCHITECTURAL_PATTERNS
from nodes.ml_model_proposal_agent import (
    MLModelProposalAgent,
    _build_reasoning_prompt,
    _format_recent_gate_exhaustions_block,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _gate_exhaustion(**overrides) -> GateExhaustionInfo:
    """Concise factory for a fully-populated GateExhaustionInfo."""
    base = dict(
        total_attempts=9,
        vram_gated_attempts=7,
        time_gated_attempts=2,
        other_failure_attempts=0,
        active_mode="trial",
        vram_budget_gb=4.0,
        time_budget_minutes=20.0,
        baseline_vram_estimate_gb=6.4,
        baseline_vram_factor=1.6,
        baseline_time_estimate_minutes=8.0,
        baseline_time_factor=0.4,
        worst_vram_factor=2.0,
        worst_time_factor=0.6,
        summary_message="All 9 attempts were rejected by the resource gate.",
    )
    base.update(overrides)
    return GateExhaustionInfo(**base)


def _minimal_interp() -> dict:
    return {
        "model_types": ["wavenet"],
        "total_experiments": 5,
        "best_denoising_score": 5.5,
        "worst_denoising_score": 1.0,
        "key_findings": [],
        "bottlenecks": [],
        "take_home_message": "wavenet dominates",
    }


def _proposal_input(tmp_path, gate_infos=None) -> ProposalInput:
    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(_minimal_interp()),
        existing_model_types=["wavenet"],
        recent_gate_exhaustions=list(gate_infos) if gate_infos else [],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


def _pipeline_input(tmp_path, gate_infos=None) -> ProposalInput:
    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(_minimal_interp()),
        existing_model_types=["wavenet"],
        recent_gate_exhaustions=list(gate_infos) if gate_infos else [],
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode="exploit",
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
        ),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="test"),
        ),
    )


# ---------------------------------------------------------------------------
# Helper truth-table — §14.N.4: 0 / 1 / 2 / 3 entries
# ---------------------------------------------------------------------------


class TestFormatRecentGateExhaustionsBlock:
    """Per-entry-count baselines. Each multi-assertion test pins every
    rendering invariant for that entry-count in one place (header
    singularity/pluralisation, ``iter N-k`` labelling, separator-rule
    count = N-1, oldest-first ordering, summary_message pass-through)."""

    def test_empty_list_returns_empty_string(self):
        """No gate-exhaustions → empty string so callers can splice
        unconditionally without producing a stray header."""
        assert _format_recent_gate_exhaustions_block([]) == ""

    def test_single_entry_block_shape(self):
        """1 entry → singular header, ``iter N-1 (most recent)`` label,
        no separator rule, summary_message reaches the rendered block.
        Replaces four flat tests (header_is_singular,
        labelled_most_recent, has_no_rule_separator, carries_summary_message)."""
        info = _gate_exhaustion(summary_message="VRAM gate exhausted.")
        block = _format_recent_gate_exhaustions_block([info])

        assert "[RECENT GATE EXHAUSTIONS (last 1 iteration)]" in block
        assert "iter N-1 (most recent):" in block
        assert "-" * 68 not in block
        assert "VRAM gate exhausted." in block

    def test_two_entry_block_shape(self):
        """2 entries → plural header, ``iter N-2`` then ``iter N-1`` in
        order, exactly one 68-dash separator, both summary_messages
        present oldest-first. Replaces four flat tests
        (header_is_plural, labels_oldest_first, separated_by_one_rule,
        preserve_distinct_summaries)."""
        older = _gate_exhaustion(summary_message="OLDER: VRAM gate hit.")
        newer = _gate_exhaustion(summary_message="NEWER: time gate hit.")
        block = _format_recent_gate_exhaustions_block([older, newer])

        assert "[RECENT GATE EXHAUSTIONS (last 2 iterations)]" in block
        assert "iter N-2:" in block
        assert "iter N-1 (most recent):" in block
        assert block.index("iter N-2:") < block.index("iter N-1 (most recent):")
        assert block.count("-" * 68) == 1
        assert "OLDER: VRAM gate hit." in block
        assert "NEWER: time gate hit." in block
        assert block.index("OLDER: VRAM gate hit.") < block.index("NEWER: time gate hit.")

    def test_three_entry_block_shape(self):
        """3 entries → header mentions ``3 iterations``, all three
        ``iter N-k`` labels present in oldest-first order, exactly two
        68-dash separators (N entries → N-1 rules). Replaces three flat
        tests (header_mentions_three, all_labels_present_in_order,
        separated_by_two_rules)."""
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()] * 3)

        assert "[RECENT GATE EXHAUSTIONS (last 3 iterations)]" in block
        assert "iter N-3:" in block
        assert "iter N-2:" in block
        assert "iter N-1 (most recent):" in block
        assert (
            block.index("iter N-3:")
            < block.index("iter N-2:")
            < block.index("iter N-1 (most recent):")
        )
        assert block.count("-" * 68) == 2

    def test_closing_guidance_present(self):
        """§14.N.3 load-bearing nudge: when the same family recurs, switch
        family rather than shrink. Spot-check the phrases that carry that."""
        block = _format_recent_gate_exhaustions_block([_gate_exhaustion()] * 2)
        assert "same architecture family or scale" in block
        assert "different family" in block


# ---------------------------------------------------------------------------
# Legacy mode — _build_reasoning_prompt
# ---------------------------------------------------------------------------


class TestLegacyReasoningPromptInjection:
    def test_block_absent_when_list_empty(self, tmp_path):
        """Default ProposalInput → empty list → header must not appear in
        the legacy reasoning prompt."""
        inp = _proposal_input(tmp_path, gate_infos=[])
        prompt = _build_reasoning_prompt(inp)
        assert "[RECENT GATE EXHAUSTIONS" not in prompt

    def test_populated_block_carries_header_summary_and_accounting(self, tmp_path):
        """Single populated entry → legacy prompt receives the §14.N.3
        header, the entry's ``summary_message`` verbatim, and every
        resource-accounting field the template references. Replaces two
        flat tests (block_present_when_list_populated +
        block_carries_resource_accounting) into one shared-setup
        baseline."""
        inp = _proposal_input(
            tmp_path,
            gate_infos=[
                _gate_exhaustion(
                    active_mode="trial",
                    vram_budget_gb=4.0,
                    time_budget_minutes=20.0,
                    baseline_vram_factor=1.6,
                    worst_vram_factor=2.0,
                    summary_message="All attempts blew the VRAM ceiling.",
                )
            ],
        )
        prompt = _build_reasoning_prompt(inp)

        # Header + summary pass-through
        assert "[RECENT GATE EXHAUSTIONS (last 1 iteration)]" in prompt
        assert "All attempts blew the VRAM ceiling." in prompt

        # Every field the §14.N.3 template references reaches the prompt
        assert "Mode active:       trial" in prompt
        assert "VRAM budget:       4.0 GB" in prompt
        assert "Time budget:       20.0 min" in prompt
        assert "VRAM 1.60×" in prompt
        assert "VRAM 2.00×" in prompt

    def test_multi_entry_ordering_preserved_in_legacy_prompt(self, tmp_path):
        """Two entries → both summary_messages reach the prompt, oldest
        first."""
        older = _gate_exhaustion(summary_message="OLD: VRAM gate hit.")
        newer = _gate_exhaustion(summary_message="NEW: time gate hit.")
        inp = _proposal_input(tmp_path, gate_infos=[older, newer])
        prompt = _build_reasoning_prompt(inp)
        assert "OLD: VRAM gate hit." in prompt
        assert "NEW: time gate hit." in prompt
        assert prompt.index("OLD:") < prompt.index("NEW:")


# ---------------------------------------------------------------------------
# Pipeline mode — proposing-stage template substitution
# ---------------------------------------------------------------------------


class TestPipelineProposingStageInjection:
    """The proposing-stage template (.md file) carries a
    ``{recent_gate_exhaustions_block}`` placeholder; the pipeline populates
    ``template_vars`` from the input list; ``load_stage_prompt`` substitutes
    the placeholder. This test loads the template directly via
    ``load_stage_prompt`` to verify the round-trip without standing up the
    whole 3-stage pipeline."""

    def test_template_carries_placeholder(self):
        """Sanity: the .md file must contain the placeholder, otherwise the
        template_vars substitution is a no-op."""
        prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode="exploit",
            template_vars=None,
        )
        assert "{recent_gate_exhaustions_block}" in prompt

    @pytest.mark.parametrize(
        "gate_infos, expects_header, expects_summary",
        [
            pytest.param(
                [_gate_exhaustion()],
                True,
                "All 9 attempts were rejected by the resource gate.",
                id="populated_substitutes_to_block",
            ),
            pytest.param(
                [],
                False,
                None,
                id="empty_collapses_to_empty_string",
            ),
        ],
    )
    def test_placeholder_substitution(
        self,
        gate_infos,
        expects_header,
        expects_summary,
    ):
        """Round-trip contract: helper output is spliced into the
        proposing-stage template via ``template_vars``. Populated list →
        block lands with header + summary; empty list → placeholder
        collapses to "" so neither the header nor a stray ``{...}``
        marker appears. Replaces two flat tests
        (placeholder_substitutes_to_block_when_populated +
        placeholder_collapses_to_empty_when_list_empty)."""
        block = _format_recent_gate_exhaustions_block(gate_infos)
        prompt = load_stage_prompt(
            "proposing_stage",
            exploration_mode="exploit",
            template_vars={
                "recent_gate_exhaustions_block": block,
                # Other proposing-stage placeholders need values too so the
                # final prompt has no stray ``{...}`` markers.
                "known_constraints_block": "",
                "existing_model_types": "wavenet",
            },
        )

        # Placeholder always substituted, regardless of populated/empty.
        assert "{recent_gate_exhaustions_block}" not in prompt

        if expects_header:
            assert "[RECENT GATE EXHAUSTIONS" in prompt
            assert expects_summary in prompt
        else:
            assert "[RECENT GATE EXHAUSTIONS" not in prompt


class TestPipelineTemplateVarsCarryBlock:
    """Belt-and-braces: hook into ``_run_pipeline`` via a fake bridge and
    assert the rendered system prompt actually reaches the LLM with the
    block when the input list is populated, and without it when empty.

    Inspecting ``self.bridge.generate.call_args_list`` is the cleanest way
    to see the substituted system prompt, since the proposing call sits
    behind the comparison + reasoning calls."""

    _FAKE_COMPARISON: ClassVar[dict[str, Any]] = {
        "comparisons": [],
        "proposed_vocab_links": [],
        "proposed_vocab_candidates": [],
        "sota_model_type": "wavenet",
        "sota_score": 5.5,
        "sota_mechanism": "x",
    }
    _FAKE_REASONING: ClassVar[dict[str, Any]] = {
        "proposed_change": "x",
        "causal_hypothesis": "x",
        "falsifiable_prediction": {
            "metric": "denoising_score",
            "current_value": 5.5,
            "predicted_value": 6.5,
            "threshold_for_refutation": 5.0,
            "rationale": "x",
        },
        "predicted_failure_modes": [],
        "inherited_components": [],
        "proposed_vocab_candidates": [],
    }
    _FAKE_PROPOSING: ClassVar[dict[str, Any]] = {
        "model_name": "spectral_wavenet",
        "model_description": "x",
        "mathematical_definition": "x",
        "motivation": "x",
        "expert_advice": {
            "focus_areas": [],
            "constraints": ["VRAM<10", "params<50M"],
            "known_failures": [],
            "suggested_directions": [],
            "rationale": "x",
        },
        "baseline_config": {
            "model_config": {},
            "train_config": {},
            "loss_config": {},
        },
        "memo_consistency_notes": [],
    }

    def _agent(self):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            self._FAKE_COMPARISON,
            self._FAKE_REASONING,
            self._FAKE_PROPOSING,
        ]
        agent = MLModelProposalAgent(
            provider="gemini",
            model_id="test",
            bridge_factory=lambda **kw: bridge,
        )
        return agent, bridge

    def _proposing_system_prompt(self, bridge) -> str:
        """The proposing call is the 3rd ``bridge.generate`` invocation;
        the system prompt is the first positional arg."""
        return bridge.generate.call_args_list[2][0][0]

    @pytest.mark.parametrize(
        "gate_infos_factory, expects_header, expects_summary",
        [
            pytest.param(
                lambda: [_gate_exhaustion(summary_message="All attempts hit the VRAM gate.")],
                True,
                "All attempts hit the VRAM gate.",
                id="populated_block_present_in_system_prompt",
            ),
            pytest.param(
                lambda: [],
                False,
                None,
                id="empty_list_omits_block_from_system_prompt",
            ),
        ],
    )
    def test_proposing_system_prompt_block_inclusion(
        self,
        tmp_path,
        gate_infos_factory,
        expects_header,
        expects_summary,
    ):
        """End-to-end via ``agent.run``: the proposing-stage system prompt
        the LLM actually sees carries the rendered block when the input
        list is populated, and is free of both the header and any stray
        placeholder when the list is empty. Replaces two flat tests
        (contains_block_when_populated + omits_block_when_list_empty)."""
        agent, bridge = self._agent()
        inp = _pipeline_input(tmp_path, gate_infos=gate_infos_factory())
        agent.run(inp)
        system_prompt = self._proposing_system_prompt(bridge)

        if expects_header:
            assert "[RECENT GATE EXHAUSTIONS" in system_prompt
            assert expects_summary in system_prompt
        else:
            assert "[RECENT GATE EXHAUSTIONS" not in system_prompt
            # No stray placeholder either
            assert "{recent_gate_exhaustions_block}" not in system_prompt

    def test_proposing_system_prompt_preserves_three_entry_order(self, tmp_path):
        """Three entries → all reach the system prompt oldest-first, with
        the pluralised header."""
        agent, bridge = self._agent()
        older = _gate_exhaustion(summary_message="OLD: VRAM hit.")
        middle = _gate_exhaustion(summary_message="MID: time hit.")
        newer = _gate_exhaustion(summary_message="NEW: both hit.")
        inp = _pipeline_input(tmp_path, gate_infos=[older, middle, newer])
        agent.run(inp)
        system_prompt = self._proposing_system_prompt(bridge)
        assert "[RECENT GATE EXHAUSTIONS (last 3 iterations)]" in system_prompt
        assert system_prompt.index("OLD:") < system_prompt.index("MID:")
        assert system_prompt.index("MID:") < system_prompt.index("NEW:")


class TestDebugDumpProposingPrompt:
    """Phase K.8 instrumentation: when
    ``ProposalInput.debug_dump_proposing_prompt_path`` is set, the
    pipeline's proposing-stage system prompt is written to that path
    so smoke runs can audit it. None (default) → no file written."""

    def _agent(self):
        bridge = MagicMock()
        bridge.generate.side_effect = [
            TestPipelineTemplateVarsCarryBlock._FAKE_COMPARISON,
            TestPipelineTemplateVarsCarryBlock._FAKE_REASONING,
            TestPipelineTemplateVarsCarryBlock._FAKE_PROPOSING,
        ]
        agent = MLModelProposalAgent(
            provider="gemini",
            model_id="test",
            bridge_factory=lambda **kw: bridge,
        )
        return agent, bridge

    def test_dump_path_set_writes_rendered_prompt(self, tmp_path):
        agent, _ = self._agent()
        dump_path = tmp_path / "debug" / "iter002_proposing.md"
        inp = _pipeline_input(
            tmp_path,
            gate_infos=[_gate_exhaustion(summary_message="All attempts hit the VRAM gate.")],
        )
        inp.debug_dump_proposing_prompt_path = str(dump_path)
        agent.run(inp)
        assert dump_path.exists(), "dump file should be created"
        contents = dump_path.read_text()
        assert "[RECENT GATE EXHAUSTIONS" in contents
        assert "All attempts hit the VRAM gate." in contents

    def test_dump_path_none_writes_nothing(self, tmp_path):
        agent, _ = self._agent()
        inp = _pipeline_input(tmp_path, gate_infos=[])
        agent.run(inp)
        debug_dir = tmp_path / "debug"
        assert not debug_dir.exists(), "no debug dir should be created when path is None"


# ---------------------------------------------------------------------------
# Fix 1 Commit 4 — [DISALLOWED PATTERNS] sub-block rendering
# ---------------------------------------------------------------------------
#
# 🛡️ SOVEREIGN CORE — DO NOT compress.
#
# This sub-block enforces research-strategy: a structural ban on
# architectural patterns the tuner has already proven infeasible on this
# hardware/data combination. Each tag→description pair, ordering
# invariant, placement invariant, and unknown-tag defensive drop is a
# distinct contract. Collapsing them would risk Silent Drift on the
# DO-NOT-PROPOSE banner that gates the LLM's proposal space.
#
# The tuner (Commit 3) populates
# ``GateExhaustionInfo.disallowed_architectural_patterns`` on attempts
# that exceeded the structural-overshoot thresholds. This block ensures
# the proposer renders each tag with its English description — imported
# from the tagger's ``ARCHITECTURAL_PATTERNS`` (single source of truth)
# — under a hard ``DO NOT PROPOSE`` banner inside the entry's rendering.
#
# See docs/reliable_resource_proposer.md §9 Commit 4.


class TestDisallowedPatternsSubBlock:
    def test_empty_patterns_produces_no_disallowed_block(self):
        """Zero-noise: default empty list must NOT render the banner — the
        aggregate-window block should look exactly as it did pre-Fix-1 for
        entries without structural bans."""
        info = _gate_exhaustion(disallowed_architectural_patterns=[])
        block = _format_recent_gate_exhaustions_block([info])
        assert "[DISALLOWED PATTERNS]" not in block
        assert "DO NOT PROPOSE" not in block

    def test_single_pattern_renders_banner_and_description(self):
        info = _gate_exhaustion(
            disallowed_architectural_patterns=["scan_over_T"],
        )
        block = _format_recent_gate_exhaustions_block([info])
        assert "[DISALLOWED PATTERNS] DO NOT PROPOSE:" in block
        # The English description must be the one from the tagger (single
        # source of truth) — not a copy in the proposer. This assertion
        # would fail silently if someone duplicated the text.
        assert ARCHITECTURAL_PATTERNS["scan_over_T"] in block
        assert "- scan_over_T:" in block

    def test_multi_pattern_renders_in_stored_order(self):
        """The tuner emits tags sorted; the renderer preserves that order
        verbatim so the LLM's prompt is deterministic across runs."""
        info = _gate_exhaustion(
            disallowed_architectural_patterns=[
                "dense_attention_over_T",
                "recurrent_over_T",
                "scan_over_T",
            ],
        )
        block = _format_recent_gate_exhaustions_block([info])
        # All three tag→description pairs present
        for tag, desc in [
            ("dense_attention_over_T", ARCHITECTURAL_PATTERNS["dense_attention_over_T"]),
            ("recurrent_over_T", ARCHITECTURAL_PATTERNS["recurrent_over_T"]),
            ("scan_over_T", ARCHITECTURAL_PATTERNS["scan_over_T"]),
        ]:
            assert f"- {tag}: {desc}" in block
        # Order preserved: dense_attention_over_T → recurrent_over_T → scan_over_T
        pos_dense = block.index("- dense_attention_over_T:")
        pos_rec = block.index("- recurrent_over_T:")
        pos_scan = block.index("- scan_over_T:")
        assert pos_dense < pos_rec < pos_scan

    def test_disallowed_block_appears_after_resource_accounting(self):
        """The sub-block sits inside its parent entry — after the Resource
        accounting numbers, so the LLM reads the structural ban after seeing
        why the iteration failed numerically."""
        info = _gate_exhaustion(
            disallowed_architectural_patterns=["scan_over_T"],
        )
        block = _format_recent_gate_exhaustions_block([info])
        pos_accounting = block.index("Resource accounting:")
        pos_disallowed = block.index("[DISALLOWED PATTERNS]")
        assert pos_accounting < pos_disallowed

    def test_disallowed_block_is_per_entry_not_global(self):
        """With 2 entries where only one has patterns, the banner appears
        once and sits inside that entry's section (between ``iter N-2:`` and
        the separator before ``iter N-1``)."""
        older_with_ban = _gate_exhaustion(
            summary_message="older: scan class banned",
            disallowed_architectural_patterns=["scan_over_T"],
        )
        newer_clean = _gate_exhaustion(
            summary_message="newer: marginal overshoot, no ban",
            disallowed_architectural_patterns=[],
        )
        block = _format_recent_gate_exhaustions_block([older_with_ban, newer_clean])
        # Exactly one banner
        assert block.count("[DISALLOWED PATTERNS] DO NOT PROPOSE:") == 1
        # Banner belongs to the older entry (appears between iter N-2 and iter N-1)
        pos_older = block.index("iter N-2:")
        pos_banner = block.index("[DISALLOWED PATTERNS]")
        pos_newer = block.index("iter N-1 (most recent):")
        assert pos_older < pos_banner < pos_newer

    def test_unknown_tag_is_dropped_defensively(self):
        """If a tag reaches the renderer without a description (e.g. the
        tagger vocabulary grew but the description map wasn't updated),
        the renderer drops it silently rather than emitting a bare tag
        the LLM cannot action. The tagger's own completeness-invariant
        tests prevent this in practice; this is belt-and-suspenders."""
        info = _gate_exhaustion(
            disallowed_architectural_patterns=["scan_over_T", "unknown_future_tag"],
        )
        block = _format_recent_gate_exhaustions_block([info])
        # The known tag renders fully
        assert "- scan_over_T:" in block
        assert ARCHITECTURAL_PATTERNS["scan_over_T"] in block
        # The unknown tag is silently dropped
        assert "unknown_future_tag" not in block

    def test_all_unknown_tags_produces_no_block(self):
        """If ALL tags on an entry are unknown, no banner is emitted —
        a bare ``DO NOT PROPOSE:`` with nothing under it would be worse
        than silence."""
        info = _gate_exhaustion(
            disallowed_architectural_patterns=["unknown_a", "unknown_b"],
        )
        block = _format_recent_gate_exhaustions_block([info])
        assert "[DISALLOWED PATTERNS]" not in block

    def test_every_tag_in_vocabulary_has_a_description(self):
        """Tagger-side completeness mirror: every v1 tag in the tagger's
        ``ARCHITECTURAL_PATTERNS`` is known to the renderer, because the
        renderer imports that same dict. Equality check guards against
        someone splitting the vocabulary across modules in the future."""
        # This is a tautology given the import, but the assertion documents
        # the intent: vocabulary and descriptions must live together.
        assert set(ARCHITECTURAL_PATTERNS) == {
            "recurrent_over_T",
            "scan_over_T",
            "dense_attention_over_T",
        }


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
