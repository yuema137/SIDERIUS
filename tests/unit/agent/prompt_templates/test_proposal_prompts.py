"""Structural regression guards for the proposer prompt files (Commit P-c).

These tests are NOT design validation — that's Checkpoint P's job (offline
human review of rendered prompts). These tests catch *accidental* regressions:
- a deleted MANDATORY block,
- a re-added hardcoded trust hierarchy ("Literature agents:", "Physics agents:",
  "Human directives:"),
- a forgotten "Advice JSON" reference in a mode file,
- a Rule 1 rewrite that drops one of the two valid evidence sources.

Per ``feedback_dont_test_static_analysis``: do NOT add tests here that verify
declarative prose alone (e.g. "the prompt is well-written"). Only add a test
when it catches a *runtime-observable* regression — i.e. something the LLM
would read differently.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from agent.prompt_templates.proposal import (
    _LOSS_REGISTRY_EMPTY_FALLBACK,
    load_stage_prompt,
    render_available_losses,
)

PROPOSAL_PROMPT_DIR = (
    Path(__file__).resolve().parents[4] / "src/agent" / "prompt_templates" / "proposal"
)

BASE_FILES = (
    "comparison_stage.md",
    "causal_reasoning_stage.md",
    "proposing_stage.md",
)
MODE_FILES = (
    "comparison_stage_explore.md",
    "comparison_stage_exploit.md",
    "causal_reasoning_stage_explore.md",
    "causal_reasoning_stage_exploit.md",
    "proposing_stage_explore.md",
    "proposing_stage_exploit.md",
)
ALL_PROMPT_FILES = BASE_FILES + MODE_FILES


def _load(name: str) -> str:
    return (PROPOSAL_PROMPT_DIR / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Causal-reasoning stage — the MANDATORY synthesis block and Rule 1 rewrite
# are the core P-c design contract. If either disappears, the LLM reverts to
# experiment-only reasoning and the lit-review integration is dead.
# ---------------------------------------------------------------------------


class TestCausalReasoningStage:
    def test_mandatory_multi_source_synthesis_block_present(self):
        """The MANDATORY block telling the LLM how to weight hard_limit /
        strong_prior / soft_prior must exist. Deleting it reverts the
        proposer to its pre-P-c behavior (anchor on experiment history,
        ignore external findings)."""
        text = _load("causal_reasoning_stage.md")
        assert "## MANDATORY — Multi-source synthesis" in text
        # All three trust_level values must be referenced by name — the
        # synthesis rule is generic over trust_level, not over agent names.
        for level in ("hard_limit", "strong_prior", "soft_prior"):
            assert f"`{level}`" in text, f"trust_level {level!r} missing from synthesis block"

    def test_rule_1_is_evidence_backed_two_sources(self):
        """Rule 1 must accept BOTH a ModelComparison and a trust-level-gated
        ExpertContextItem as valid evidence. The pre-P-c form ("must
        reference a specific ModelComparison from Stage 1") is forbidden —
        it blocks literature findings by construction."""
        text = _load("causal_reasoning_stage.md")
        # Header form
        assert "1. **Evidence-backed**" in text
        # Both valid sources mentioned
        assert "ModelComparison" in text
        assert "ExpertContextItem" in text
        # Trust gate on the second source — strong_prior or hard_limit only
        # may motivate a claim; soft_prior is inspirational (see Rule 1 spec)
        assert "`strong_prior`" in text
        assert "`hard_limit`" in text
        # Cite source_ref clause — the citation discipline must survive
        assert "source_ref" in text
        # Pre-P-c regression guard: the old single-source form must be gone.
        assert "must reference\n   a specific ModelComparison from Stage 1." not in text

    def test_rule_5_generic_source_type(self):
        """Rule 5 must reference the generic source_type field (P-b) rather
        than 'past model' only. Otherwise InheritedComponent.source_type =
        external_agent / human becomes orphan vocabulary."""
        text = _load("causal_reasoning_stage.md")
        assert "`source_type`" in text
        # All three source_type values must appear so the LLM knows what's valid
        for st in ("experiment", "external_agent", "human"):
            assert f"`{st}`" in text, f"source_type {st!r} missing from Rule 5"


# ---------------------------------------------------------------------------
# Comparison stage — Rule 4 must allow literature signals as link suggestions
# while preserving "only experiment results confirm" semantics.
# ---------------------------------------------------------------------------


class TestComparisonStage:
    def test_rule_4_allows_external_with_provenance(self):
        """Rule 4 must accept external signals as link suggestions but
        require provenance and forbid promotion on external evidence
        alone. Pre-P-c form ("Do NOT guess from generic ML knowledge")
        is forbidden — it blocked lit-review from influencing
        vocab_links."""
        text = _load("comparison_stage.md")
        # The new form must mention provenance + the "no promotion" guard
        assert "provenance" in text or "Provenance" in text
        assert "Do not promote a link to confirmed status on external evidence alone." in text
        # Pre-P-c phrasing must be gone
        assert "Do NOT guess from generic ML knowledge" not in text


# ---------------------------------------------------------------------------
# Generic-over-trust_level invariant — the hardcoded trust hierarchy must
# NOT appear anywhere in agent/prompt_templates/proposal/. P-b introduced
# trust_level so the proposer reads structured calibration off the card;
# any re-introduction of prose like "Literature agents: ... Physics
# agents: ..." undoes that work.
# ---------------------------------------------------------------------------


class TestNoHardcodedAgentNamesInProposalPrompts:
    FORBIDDEN_PHRASES = (
        "Literature agents:",
        "Physics agents:",
        "Human directives: always take precedence",
    )

    def test_forbidden_phrase_absent(self):
        """One property: no prompt file names an agent to set trust.

        Was a stacked cross-product over phrases x files -- one failure
        class reported N x M ways, stopping at the first cell. Scanning the
        whole matrix reports every offending (file, phrase) pair, and the
        cell count no longer grows multiplicatively as either list grows.
        """
        violations = [
            f"{filename}: {forbidden!r}"
            for filename in ALL_PROMPT_FILES
            for forbidden in self.FORBIDDEN_PHRASES
            if forbidden in _load(filename)
        ]
        assert not violations, (
            "Pre-P-c hardcoded trust-hierarchy phrases found:\n  "
            + "\n  ".join(violations)
            + "\n\nCalibration must flow via AgentCard.trust_level (P-b) — "
            "not via agent-name pattern matching."
        )


# ---------------------------------------------------------------------------
# Mode files — Contract Hierarchy must redirect to the base prompt's
# synthesis rules and must NOT reference the dead "Advice JSON" concept.
# ---------------------------------------------------------------------------


class TestModeFilesRedirectSynthesis:
    def test_advice_json_phrase_absent(self):
        """'Advice JSON' as the strategic-direction authority was a
        pre-P-c dangling pointer — pipeline mode never rendered any such
        JSON. Replaced with a redirect to the base-prompt synthesis rules.
        The phrase must be gone from EVERY mode file, and this reports all
        the files that still carry it rather than only the first."""
        offenders = [f for f in MODE_FILES if "Advice JSON" in _load(f)]
        assert not offenders, f"mode files still naming the dead Advice JSON: {offenders}"

    def test_redirect_to_base_prompt_synthesis_present(self):
        """Every mode file's Contract Hierarchy must point at the base
        prompt's synthesis rules so a downstream reader knows where the
        authoritative calibration lives."""
        missing = [f for f in MODE_FILES if "base prompt" not in _load(f)]
        assert not missing, f"mode files with no redirect to the base prompt: {missing}"


# ---------------------------------------------------------------------------
# L5 — render_available_losses helper + {available_losses_block} placeholder
# in proposing_stage.md and causal_reasoning_stage.md.
# See docs/design/enable_loss_inventory.md § Commit L5.
# ---------------------------------------------------------------------------


@dataclass
class _StubMeta:
    """Duck-typed CapabilityMetadata-shaped stub for render_available_losses
    tests. Avoids standing up a tmp JSON index when we only want to inspect
    rendering behaviour.

    L6c — ``mathematical_definition`` added with default empty so existing
    test constructors that don't set it keep producing description-only
    rendering (back-compat path)."""

    name: str
    description: str
    created_at: str
    source_iteration: str | None = None
    mathematical_definition: str = ""


class _StubRegistry:
    """Minimal registry duck-type: only the methods render_available_losses
    actually calls. Tests pass this instead of a real CapabilityRegistry +
    tmp_path index file."""

    def __init__(self, metas: list[_StubMeta]):
        self._metas = metas

    def list(self, capability_type: str | None = None):
        # render_available_losses only ever passes capability_type="loss";
        # the stub doesn't bother filtering — that's the registry's job
        # and is tested separately in test_capability_registry.py.
        return list(self._metas)


class TestRenderAvailableLosses:
    def test_empty_registry_returns_fallback(self):
        out = render_available_losses(_StubRegistry([]))
        assert out == _LOSS_REGISTRY_EMPTY_FALLBACK
        # Sanity: the fallback mentions the 3 options the LLM has.
        assert "No custom losses registered" in out
        assert "built-in" in out

    def test_single_entry_renders_subsection(self):
        """L6c — output uses ``### name (source: iter_N)`` subsection format
        with a ``**Description**:`` line. Replaces the pre-L6c markdown table
        (broke on multi-line mathematical_definition formulas)."""
        registry = _StubRegistry(
            [
                _StubMeta(
                    name="snr_weighted_mse",
                    description="SNR-weighted MSE for noisy waveform regression.",
                    created_at="2026-06-22T10:00:00+00:00",
                    source_iteration="iter_005",
                )
            ]
        )
        out = render_available_losses(registry)
        assert "## Available custom losses" in out
        assert "### `snr_weighted_mse` (source: iter_005)" in out
        assert "**Description**: SNR-weighted MSE" in out

    def test_multi_entries_sorted_most_recent_first(self):
        """Order MUST be descending by created_at — the design doc says the
        most-recent loss is most likely to be relevant to the current
        bottleneck. Stable sort under identical inputs (same input →
        same output)."""
        metas = [
            _StubMeta(
                name="oldest",
                description="d_old",
                created_at="2026-01-01T00:00:00+00:00",
                source_iteration="iter_001",
            ),
            _StubMeta(
                name="newest",
                description="d_new",
                created_at="2026-06-22T00:00:00+00:00",
                source_iteration="iter_010",
            ),
            _StubMeta(
                name="middle",
                description="d_mid",
                created_at="2026-04-01T00:00:00+00:00",
                source_iteration="iter_005",
            ),
        ]
        out = render_available_losses(_StubRegistry(metas))
        # Newest first, oldest last.
        idx_newest = out.index("`newest`")
        idx_middle = out.index("`middle`")
        idx_oldest = out.index("`oldest`")
        assert idx_newest < idx_middle < idx_oldest

    def test_stable_across_calls(self):
        """Same input must produce the same output — Python's sorted is
        guaranteed stable, but pinning the contract here so a future
        refactor (e.g. switching to a hash-based collection) does not
        silently break determinism."""
        metas = [
            _StubMeta(
                name=f"loss_{i}",
                description="x",
                created_at=f"2026-06-2{i}T00:00:00+00:00",
                source_iteration=f"iter_{i:03}",
            )
            for i in range(3)
        ]
        out_1 = render_available_losses(_StubRegistry(metas))
        out_2 = render_available_losses(_StubRegistry(metas))
        assert out_1 == out_2

    def test_none_source_iteration_renders_as_dash(self):
        """Hand-curated losses seeded into the registry have
        source_iteration=None per CapabilityMetadata. The rendering must
        not show 'None' — use an em-dash placeholder in the subsection
        header instead."""
        registry = _StubRegistry(
            [
                _StubMeta(
                    name="hand_curated",
                    description="x",
                    created_at="2026-06-22T00:00:00+00:00",
                    source_iteration=None,
                )
            ]
        )
        out = render_available_losses(registry)
        assert "### `hand_curated` (source: —)" in out
        assert "None" not in out

    def test_newlines_in_description_collapsed(self):
        """A multi-line description in the registry must collapse to one
        line in the rendered output (defensive — L4b also collapses at
        register time, but a hand-edited index could slip multi-line
        content in)."""
        registry = _StubRegistry(
            [
                _StubMeta(
                    name="x",
                    description="line one\nline two\nline three",
                    created_at="2026-06-22T00:00:00+00:00",
                    source_iteration="iter_001",
                )
            ]
        )
        out = render_available_losses(registry)
        assert "line one line two line three" in out

    def test_render_available_losses_shows_formula(self):
        """L6c — when a registry entry has a non-empty
        mathematical_definition, render it inside a fenced code block under
        a **Formula**: heading so the proposer can judge semantic similarity."""
        registry = _StubRegistry(
            [
                _StubMeta(
                    name="expected_value_mse",
                    description="Soft-expected-value MSE for ordinal classes.",
                    created_at="2026-06-22T00:00:00+00:00",
                    source_iteration="iter_001",
                    mathematical_definition=(
                        "soft_pred = sum_c c * softmax(inputs)[:, c, :]; "
                        "loss = mean((soft_pred - y)^2)"
                    ),
                )
            ]
        )
        out = render_available_losses(registry)
        assert "**Formula**:" in out
        assert "soft_pred = sum_c c * softmax(inputs)" in out
        assert "loss = mean((soft_pred - y)^2)" in out
        # Formula is fenced as a code block so the LLM reads it as code, not prose.
        assert "```" in out

    def test_render_available_losses_skips_formula_when_empty(self):
        """L6c back-compat — pre-L6c registry entries have
        mathematical_definition="" and must render as description-only
        (no **Formula**: section, no empty code fence) so existing
        registries don't degrade."""
        registry = _StubRegistry(
            [
                _StubMeta(
                    name="legacy_loss",
                    description="Pre-L6c entry without a stored formula.",
                    created_at="2026-06-22T00:00:00+00:00",
                    source_iteration="iter_001",
                    mathematical_definition="",
                )
            ]
        )
        out = render_available_losses(registry)
        assert "### `legacy_loss`" in out
        assert "**Description**: Pre-L6c entry" in out
        assert "**Formula**:" not in out
        # No empty code-fence pair either.
        assert "```\n\n```" not in out


# ---------------------------------------------------------------------------
# {available_losses_block} placeholder substitution in proposing_stage.md
# and causal_reasoning_stage.md.
# ---------------------------------------------------------------------------


class TestAvailableLossesBlockSubstitution:
    def test_proposing_stage_contains_placeholder(self):
        text = _load("proposing_stage.md")
        assert "{available_losses_block}" in text

    def test_causal_reasoning_stage_contains_placeholder(self):
        text = _load("causal_reasoning_stage.md")
        assert "{available_losses_block}" in text

    @pytest.mark.parametrize("stage_name", ["proposing_stage", "causal_reasoning_stage"])
    def test_load_stage_prompt_substitutes_placeholder(self, stage_name: str):
        """load_stage_prompt must replace {available_losses_block} from
        template_vars, the same way it does {forward_contract} and
        {existing_model_types}."""
        rendered = load_stage_prompt(
            stage_name,
            template_vars={
                "available_losses_block": "## CUSTOM LOSS PROBE",
                # Other placeholders proposing_stage.md references — provide
                # empty strings so substitution doesn't leave braces.
                "existing_model_types": "",
                "forward_contract": "",
                "recent_gate_exhaustions_block": "",
                "known_constraints_block": "",
                "minimum_boldness": "0.05",
                "n_agent_proposed": "1",
                "n_confirmed_links": "0",
                "task_description": "",
            },
        )
        assert "## CUSTOM LOSS PROBE" in rendered
        # Placeholder fully consumed.
        assert "{available_losses_block}" not in rendered

    def test_proposing_stage_has_rule_9_3_branch_decision(self):
        """The 3-branch decision rule must be present as Rule 9 with all
        three branches named — the schema validator (L3) will reject any
        proposal that violates this, so the LLM needs to see it
        explicitly."""
        text = _load("proposing_stage.md")
        assert "9. **Loss selection" in text
        # All 3 branches must be named (A/B/C).
        assert "Branch A" in text
        assert "Branch B" in text
        assert "Branch C" in text
        # And the key constraint that makes the schema validator fire
        # (loss_name MUST match custom_loss_spec.loss_name).
        assert "MUST match" in text

    def test_proposing_stage_lists_five_loss_types(self):
        """The 'What you produce' section must mention all 5 valid
        loss_type values so the LLM can pick from the same set L3 / L2
        validates against."""
        text = _load("proposing_stage.md")
        # Anchor on the explicit listing line we added in L5a.
        for lt in ("focal", "focal_cw", "ce", "smooth_l1", "custom"):
            assert f"`{lt}`" in text
