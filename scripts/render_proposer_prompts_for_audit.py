"""Checkpoint P driver — render proposer prompts for human audit.

Builds a synthetic ``ProposalInput`` that triggers BOTH the lit-review
card path AND the ``human_advice`` wrap path simultaneously, runs the
``MLModelProposalAgent._run_pipeline`` prompt-assembly path with mocked
LLM responses, and writes the rendered prompts to
``docs/proposer_prompt_audit.md`` as an embedded-inline artifact for
human review against the 9 Checkpoint P sub-criteria.

Why this is a script, not a pytest test:

Checkpoint P is fundamentally a *visual* human review — the goal is to
let a human read the prompts the LLM would actually see and confirm
each of the 9 sub-criteria pass. ``tests/unit/agent/prompt_templates/
test_proposal_prompts.py`` already covers the structural assertions that
can be checked programmatically (P-c gate); Checkpoint P also includes
a small programmatic pre-check section (sub-criteria 6, 7, 8, 9 are
substring-level) so the human only has to focus their eye on the
non-programmable parts (1-5 — block presence, order, content quality).

Usage:
    .venv/bin/python scripts/render_proposer_prompts_for_audit.py

Output:
    docs/proposer_prompt_audit.md — self-contained artifact, embeds every
    rendered prompt inline. Pre-check verdicts are PASS/FAIL machine-
    readable; the final human-verdict block at the bottom of the artifact
    is left blank for the reviewer to fill in and commit.

Zero LLM calls. Zero GPU. Runs in ~1 second.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent.schemas.interpretation import InterpretationOutput  # noqa: E402
from agent.schemas.proposal import (  # noqa: E402
    AgentCard,
    ExpertContextItem,
    ModelSelectionStrategy,
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
    ResearchPolicy,
)
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (  # noqa: E402
    local_full_context,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig  # noqa: E402
from core.hardware_context import HardwareContext  # noqa: E402
from nodes.ml_model_proposal_agent import MLModelProposalAgent  # noqa: E402

ARTIFACT_PATH = REPO_ROOT / "docs" / "proposer_prompt_audit.md"
PROPOSAL_PROMPT_DIR = REPO_ROOT / "agent" / "prompt_templates" / "proposal"

# Source commits backing the rendered prompts — kept in sync with the Commit P
# ladder so the artifact records the exact state at audit time.
SOURCE_COMMITS = {
    "P-a (cite_id → source_ref)": "0c280ba",
    "P-b (trust_level + source_type/source_id)": "a629e4a",
    "P-c (multi-source synthesis prompt)": "69e7234",
    "P-d (pipeline-mode fixes + position bias)": "aeb4d9f",
    "P-e (doc closure + status board)": "6348ece",
}


# ---------------------------------------------------------------------------
# Synthetic input — designed to exercise every block under audit
# ---------------------------------------------------------------------------


def _make_interpretation() -> InterpretationOutput:
    return InterpretationOutput(
        model_types=["punet", "wavenet"],
        model_descriptions={
            "punet": "U-Net baseline for 1-D signal denoising.",
            "wavenet": "Dilated causal convolutional network — current SOTA.",
        },
        total_experiments=2,
        per_model_best={"punet": 1.2, "wavenet": 5.57},
        per_model_worst={"punet": 0.4, "wavenet": 2.1},
        best_denoising_score=5.57,
        worst_denoising_score=0.4,
        best_config={
            "model_config": {"depth": 6},
            "train_config": {"lr": 1e-4, "epochs": 10},
            "loss_config": {"loss_type": "focal"},
        },
        key_findings=[
            "wavenet's dilated_causal_conv stack drives high-freq performance.",
            "punet plateaus at depth=6; deeper variants saw no lift.",
        ],
        bottlenecks=[
            "Low-frequency files (0-3) remain weak across all models.",
            "Wavenet's receptive field saturates before low-freq capture.",
        ],
        take_home_message=(
            "Next iteration: target low-freq recovery via a richer "
            "frequency-aware mechanism while inheriting wavenet's high-freq strength."
        ),
    )


def _lit_review_card() -> AgentCard:
    """Lit-review's emitted card (mirrors the static _AGENT_CARD in
    nodes/ml_literature_review.py:65 — trust_level='soft_prior')."""
    return AgentCard(
        agent_name="ml_literature_review",
        role="Surface ML denoising literature relevant to the current iteration.",
        expertise_domain="ML denoising architectures; Semantic Scholar corpus.",
        coverage="ArXiv/S2 results any year; local PDFs in reference_data/.",
        limitations=(
            "Cannot run experiments; cannot judge SQUID-specific applicability "
            "without empirical confirmation."
        ),
        trust_level="soft_prior",
        trust_guidance=(
            "Treat findings as inspirational priors — experiment runs are required "
            "to confirm applicability before adoption."
        ),
    )


def _lit_review_finding() -> ExpertContextItem:
    return ExpertContextItem(
        source="ml_literature_review",
        kind="literature",
        content=(
            "**Implication:** A frequency-aware composite loss may widen wavenet's "
            "effective spectral coverage on low-freq files (bottleneck 1).\n\n"
            "**Mechanism:** Composite loss $\\min_\\theta \\delta L^f + (1-\\delta) L^t$ "
            "(FreLE), where $L^f$ is the Fourier-magnitude loss and $L^t$ is the "
            "time-domain reconstruction loss; $\\delta \\in [0, 1]$ trades off the two. "
            "Lifted verbatim from the source paper's Eq. 4.\n\n"
            "**Adaptation:** Apply the composite loss directly to the wavenet decoder "
            "with the clean signal's Fourier magnitudes as the spectral target. "
            "Keep wavenet's dilated_causal_conv backbone unchanged."
        ),
        source_ref="arxiv:2312.00752",
        confidence=0.85,
    )


def _hardware_context() -> HardwareContext:
    return HardwareContext(
        device_name="NVIDIA RTX 3090",
        total_memory_bytes=24 * 1024**3,
        compute_capability=(8, 6),
        multiprocessor_count=82,
        cuda_runtime_version="12.1",
        torch_version="2.1.0",
        hostname="checkpoint-p-audit-host",
        device_available=True,
        discovered_at=datetime.now(UTC),
    )


HUMAN_ADVICE = (
    "Prioritize low-frequency recovery; tolerate up to 12 GB VRAM if the "
    "extra capacity directly improves files 0-3. Avoid frequency-split "
    "training — keep the full-spectrum setting locked."
)


# ---------------------------------------------------------------------------
# Canned LLM responses — enable the pipeline to traverse all 3 stages
# without a real bridge call.
# ---------------------------------------------------------------------------


def _canned_response_for(label: str) -> dict:
    if "comparison" in label:
        return {
            "comparisons": [
                {
                    "model_type": "wavenet",
                    "source": "seed",
                    "best_score": 5.57,
                    "key_mechanism": "dilated_causal_conv stack — exponential receptive field growth.",
                    "strengths": ["scores 8.2 on files 15-19 (high-freq)"],
                    "weaknesses": ["near-zero on files 0-3 (low-freq)"],
                    "lesson_for_next_proposal": "Inherit dilated_causal_conv; augment for low-freq.",
                },
                {
                    "model_type": "punet",
                    "source": "seed",
                    "best_score": 1.2,
                    "key_mechanism": "U-Net encoder/decoder with skip connections.",
                    "strengths": ["compact"],
                    "weaknesses": ["plateaus at depth=6"],
                    "lesson_for_next_proposal": "Skip if wavenet inheritance is preferred.",
                },
            ],
            "proposed_vocab_links": [],
            "proposed_vocab_candidates": [],
            "sota_model_type": "wavenet",
            "sota_score": 5.57,
            "sota_mechanism": "dilated_causal_conv provides exponential receptive field growth.",
        }
    if "causal_reasoning" in label:
        return {
            "proposed_change": (
                "Augment wavenet with a frequency-aware composite loss "
                "($\\delta L^f + (1-\\delta) L^t$) to widen spectral coverage."
            ),
            "causal_hypothesis": (
                "wavenet's dilated_causal_conv (Stage 1 ModelComparison) saturates "
                "high-freq but leaves low-freq files weak. A composite frequency loss "
                "(source_ref arxiv:2312.00752, trust_level=soft_prior) directly "
                "targets the low-freq bottleneck without altering the proven backbone."
            ),
            "falsifiable_prediction": {
                "metric": "mean(file_vector[0:3])",
                "current_value": 0.5,
                "predicted_value": 1.5,
                "threshold_for_refutation": 0.7,
                "rationale": "FreLE's spectral loss is on-domain for 1-D denoising.",
            },
            "predicted_failure_modes": ["Composite loss may destabilise training in early epochs."],
            "inherited_components": [
                {
                    "component": "dilated_causal_conv",
                    "source_type": "experiment",
                    "source_id": "wavenet",
                    "contribution_evidence": "Core mechanism of wavenet's 5.57 SOTA score.",
                }
            ],
        }
    # proposing stage
    return {
        "model_name": "frele_wavenet",
        "model_description": "wavenet + composite frequency loss (FreLE).",
        "mathematical_definition": (
            "wavenet backbone unchanged; output head trained against "
            "$\\delta L^f + (1-\\delta) L^t$ with $\\delta=0.3$."
        ),
        "motivation": (
            "Addresses the low-freq bottleneck per the causal_hypothesis while "
            "preserving wavenet's confirmed high-freq strength."
        ),
        "expert_advice": {
            "focus_areas": ["low-freq recovery", "loss balance hyperparam delta"],
            "constraints": ["VRAM < 10 GB", "params < 50M"],
            "known_failures": ["Training instability if delta > 0.6 early."],
            "suggested_directions": ["Start delta=0.3, anneal up if stable."],
            "rationale": "Composite loss is the entire delta vs SOTA.",
        },
        "baseline_config": {
            "model_config": {"depth": 8, "dilation_max": 256},
            "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 1},
            "loss_config": {"loss_type": "frele_composite", "delta": 0.3},
        },
        "parameter_count_estimate": 5_000_000,
    }


# ---------------------------------------------------------------------------
# Programmatic pre-checks — substring-level checks on rendered prompts +
# static prompt files.  Pass/fail recorded in the artifact alongside each
# sub-criterion.
# ---------------------------------------------------------------------------


def _precheck(criterion: str, ok: bool, evidence: str) -> str:
    badge = "✅ PASS" if ok else "❌ FAIL"
    return f"- **{criterion}** — {badge}\n  - {evidence}"


def _run_prechecks(captures: list[tuple[str, str, str]]) -> str:
    """Return a Markdown section with automated pre-check verdicts."""
    lines: list[str] = ["## Pre-check verdicts (automated)\n"]

    # Sub-criterion 6 — causal_reasoning_stage.md system prompt content
    causal = (PROPOSAL_PROMPT_DIR / "causal_reasoning_stage.md").read_text(encoding="utf-8")
    lines.append(
        _precheck(
            "S6 — causal_reasoning_stage.md has the new MANDATORY Multi-source synthesis block",
            "## MANDATORY — Multi-source synthesis" in causal,
            "Header literal `## MANDATORY — Multi-source synthesis` present.",
        )
    )
    lines.append(
        _precheck(
            "S6 — causal_reasoning_stage.md Rule 1 is Evidence-backed (two sources)",
            (
                "**Evidence-backed**" in causal
                and "ModelComparison" in causal
                and "ExpertContextItem" in causal
                and "`strong_prior`" in causal
                and "`hard_limit`" in causal
            ),
            "Rule 1 header `**Evidence-backed**` + both ModelComparison and ExpertContextItem mentions + trust_level gate.",
        )
    )
    lines.append(
        _precheck(
            "S6 — no hardcoded `Literature agents:` / `Physics agents:` / `Human directives: always take precedence` "
            "phrases in any base proposal prompt",
            all(
                forbidden not in (PROPOSAL_PROMPT_DIR / fname).read_text(encoding="utf-8")
                for fname in (
                    "causal_reasoning_stage.md",
                    "comparison_stage.md",
                    "proposing_stage.md",
                )
                for forbidden in (
                    "Literature agents:",
                    "Physics agents:",
                    "Human directives: always take precedence",
                )
            ),
            "Hardcoded trust-hierarchy strings absent from the 3 base prompts.",
        )
    )

    # Sub-criterion 7 — no expert_advice / no cite_id in the rendered prompts
    rendered_blob = "\n".join(s + "\n" + u for _, s, u in captures)
    lines.append(
        _precheck(
            "S7 — no `expert_advice` field-name reference in rendered USER prompts "
            "(system prompts retain it as the ProposalOutput field for the LLM to emit)",
            not any("expert_advice" in u for _, _s, u in captures),
            evidence="User-prompt assembly carries no inp.expert_advice (it was hard-removed in P-d).",
        )
    )
    lines.append(
        _precheck(
            "S7 — no `cite_id` literal in rendered prompts",
            "cite_id" not in rendered_blob,
            evidence="Pure rename — every `cite_id` became `source_ref` in P-a.",
        )
    )

    # Sub-criterion 8 — comparison_stage.md weakened Rule 4 + 6 mode files
    comp = (PROPOSAL_PROMPT_DIR / "comparison_stage.md").read_text(encoding="utf-8")
    lines.append(
        _precheck(
            "S8 — comparison_stage.md Rule 4 allows external signals with provenance",
            (
                "Do not promote a link to confirmed status on external evidence alone." in comp
                and "provenance" in comp.lower()
                and "arxiv:" in comp.lower()
            ),
            evidence=(
                "Rule 4 contains the no-promotion-on-external-evidence guard "
                "+ explicit provenance language + arxiv: example."
            ),
        )
    )
    mode_files = [
        "comparison_stage_explore.md",
        "comparison_stage_exploit.md",
        "causal_reasoning_stage_explore.md",
        "causal_reasoning_stage_exploit.md",
        "proposing_stage_explore.md",
        "proposing_stage_exploit.md",
    ]
    all_mode_text = {m: (PROPOSAL_PROMPT_DIR / m).read_text(encoding="utf-8") for m in mode_files}
    lines.append(
        _precheck(
            "S8 — no hardcoded trust-hierarchy phrases in any of the 6 *_explore.md/*_exploit.md files",
            all(
                forbidden not in text
                for text in all_mode_text.values()
                for forbidden in (
                    "Literature agents:",
                    "Physics agents:",
                    "Human directives: always take precedence",
                )
            ),
            evidence=f"Checked {len(mode_files)} files.",
        )
    )
    lines.append(
        _precheck(
            "S8 — every mode file's Operating Mode block references "
            "`trust_level`-weighted findings (not 'Advice JSON')",
            all(
                "trust_level" in text and "Advice JSON" not in text
                for text in all_mode_text.values()
            ),
            evidence=(
                f"All {len(mode_files)} files mention `trust_level` and contain no "
                "`Advice JSON` reference (P-c rewrite + P-c extra sweep)."
            ),
        )
    )

    # Sub-criterion 9 — rendered Contributors block has both Trust Level values
    expected_soft = "Trust Level: soft_prior"
    expected_strong = "Trust Level: strong_prior"
    user_blob = "\n".join(u for _, _s, u in captures)
    lines.append(
        _precheck(
            f"S9 — rendered user prompts contain literal `{expected_soft}` (lit-review card)",
            expected_soft in user_blob,
            evidence="Substring search across every captured user prompt.",
        )
    )
    lines.append(
        _precheck(
            f"S9 — rendered user prompts contain literal `{expected_strong}` "
            "(synthesized human card)",
            expected_strong in user_blob,
            evidence="Substring search across every captured user prompt.",
        )
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Capture + render
# ---------------------------------------------------------------------------


def _build_proposal_input() -> ProposalInput:
    """Build the ProposalInput by going through the production protocol so the
    human_advice wrap path AND synthesized human AgentCard injection both fire.
    """
    interp = _make_interpretation()
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="/tmp/checkpoint_p_audit", run_name="audit"),
    )
    pipeline = ReasoningPipelineConfig(
        stages=[
            ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
            ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
        ],
        model_selection=ModelSelectionStrategy(),
        exploration_mode="explore",
        policy=ResearchPolicy(minimum_boldness=0.05),
    )
    inp = local_full_context(
        interp,
        storage,
        expert_context=[_lit_review_finding()],
        agent_cards=[_lit_review_card()],
        reasoning_pipeline=pipeline,
        human_advice=HUMAN_ADVICE,  # protocol wraps + synth human AgentCard injection
    )
    # The protocol returns the constructed ProposalInput as a Pydantic object —
    # patch in the post-protocol fields the protocol does NOT populate
    # (constraints, hardware_context) since those come from the workflow layer
    # in production. Checkpoint P verifies they reach the user prompt.
    inp = inp.model_copy(
        update={
            "constraints": ["VRAM < 10 GB", "params < 50M"],
            "hardware_context": _hardware_context(),
            "vram_budget_gb": None,  # PHYSICAL regime
        }
    )
    return inp


def _capture_prompts(inp: ProposalInput) -> list[tuple[str, str, str]]:
    """Run _run_pipeline with a mocked bridge that captures every prompt pair."""
    captured: list[tuple[str, str, str]] = []

    def _fake_generate(system_prompt: str, user_prompt: str, **kwargs):
        label = kwargs.get("label", "")
        captured.append((label, system_prompt, user_prompt))
        return _canned_response_for(label)

    def _fake_generate_text(system_prompt: str, user_prompt: str, **kwargs):
        label = kwargs.get("label", "")
        captured.append((label, system_prompt, user_prompt))
        return ""

    with (
        patch("agent.llm_bridge.LLMBridge.generate", side_effect=_fake_generate),
        patch("agent.llm_bridge.LLMBridge.generate_text", side_effect=_fake_generate_text),
    ):
        agent = MLModelProposalAgent(provider="openai", model_id="gpt-4o-mini")
        agent.run(inp)
    return captured


# ---------------------------------------------------------------------------
# Artifact write
# ---------------------------------------------------------------------------


def _write_artifact(captures: list[tuple[str, str, str]]) -> None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    parts: list[str] = []
    parts.append(f"# Checkpoint P — Proposer pipeline-mode prompt audit ({today})\n")
    parts.append(
        "Self-contained artifact produced by "
        "`scripts/render_proposer_prompts_for_audit.py`. The rendered prompts "
        "below are the exact strings the proposer's LLM would see in a "
        "production pipeline-mode run, captured with the LLM bridge mocked "
        "(zero LLM calls). See `docs/commit_plan_ml_literature_review.md` § "
        '"Behavioral Checkpoint P" for the 9 sub-criteria.\n'
    )
    parts.append("## Source commits\n")
    for label, sha in SOURCE_COMMITS.items():
        parts.append(f"- {label} — `{sha}`")
    parts.append("")

    parts.append("## Synthetic input shape\n")
    parts.append(
        "- `inp.agent_cards`: 1 lit-review card (`trust_level=soft_prior`) "
        "supplied by caller; 1 `human` card "
        "(`trust_level=strong_prior`) appended by the protocol's "
        "`human_advice` wrap path.\n"
        "- `inp.expert_context`: 1 lit-review finding "
        "(`source_ref=arxiv:2312.00752`) supplied by caller; 1 wrapped human "
        "directive (`source_ref=human:human_advice`) appended by the same "
        "protocol path.\n"
        "- `inp.constraints`: `['VRAM < 10 GB', 'params < 50M']`.\n"
        "- `inp.hardware_context`: synthetic RTX 3090 manifest, "
        "`device_available=True`, PHYSICAL regime (no operator budget).\n"
        "- `inp.human_advice`: realistic operator directive about low-freq "
        "targeting.\n"
        "- `reasoning_pipeline`: standard 2-stage (`comparison` + "
        "`causal_reasoning`) + the implicit proposing stage, `exploration_mode=explore`.\n"
    )

    parts.append(_run_prechecks(captures))
    parts.append("")

    parts.append("## Rendered prompts (1 entry per LLM call)\n")
    for i, (label, system_prompt, user_prompt) in enumerate(captures, start=1):
        parts.append(f"### Call {i} — `{label}`\n")
        parts.append(f"**System prompt** ({len(system_prompt)} chars):\n")
        parts.append("```")
        parts.append(system_prompt.rstrip())
        parts.append("```\n")
        parts.append(f"**User prompt** ({len(user_prompt)} chars):\n")
        parts.append("```")
        parts.append(user_prompt.rstrip())
        parts.append("```\n")
        parts.append("---\n")

    parts.append("## Human verdict (Checkpoint P sign-off)\n")
    parts.append(
        "Reviewer reads the rendered prompts above and confirms each of the 9 "
        "sub-criteria. The automated pre-checks at the top of this artifact "
        "cover sub-criteria 6/7/8/9 mechanically; sub-criteria 1-5 (block "
        "presence and content quality) require human judgment.\n"
    )
    parts.append("| # | Criterion (short) | Verdict | Notes |")
    parts.append("|---|---|---|---|")
    criteria_short = [
        ("S1", "`[HARDWARE CONTEXT]` block at the top of every stage's user prompt"),
        ("S2", "`## Constraints` block right below"),
        ("S3", "`## External Contributors` block next, both Trust Level values visible"),
        ("S4", "`## Expert Context` block next, lit-review + wrapped-human items present"),
        ("S5", "Candidate markdown + accumulated JSON renders below all of the above"),
        (
            "S6",
            "causal_reasoning_stage.md system prompt is post-P-c (rule 1 + MANDATORY synthesis; no hardcoded hierarchy)",
        ),
        ("S7", "no `expert_advice` field-name in user prompts; no `cite_id` anywhere"),
        (
            "S8",
            "comparison_stage.md weakened Rule 4 + 6 mode files clean of hardcoded hierarchy / Advice JSON",
        ),
        (
            "S9",
            "rendered Contributors block contains literal `Trust Level: soft_prior` AND `Trust Level: strong_prior`",
        ),
    ]
    for sid, short in criteria_short:
        parts.append(f"| {sid} | {short} | _ | _ |")
    parts.append("")
    parts.append(
        "**Sign-off**: a human reviewer fills the Verdict column above "
        "(`PASS`/`FAIL`/`N/A`) and commits the artifact alongside ticking "
        "Checkpoint P + closing P-e in "
        "`docs/commit_plan_ml_literature_review.md`."
    )

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> int:
    inp = _build_proposal_input()
    captures = _capture_prompts(inp)
    _write_artifact(captures)
    print(f"Wrote {len(captures)} captured prompt pairs → {ARTIFACT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
