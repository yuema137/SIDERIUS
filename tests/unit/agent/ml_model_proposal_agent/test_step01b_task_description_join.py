"""PR 01b / commit S1-C — the task-description JOIN.

Design: `docs/design/generic_framework_upgrade/
step_01_proposer_hypothesis_space/pr_01b_task_description_join.md` §4.1;
parent §8.3.

Before this commit the production pipeline transported
``inp.task_description`` into ``template_vars`` and NO proposal template
consumed it — an audited dead key. These tests pin the closure of that
seam at the surface that matters: the LLM boundary.

What each test here catches that nothing else does:

* the SHIPPED description (read through ``load_task_config``, never a
  literal copy) reaching EVERY stage in BOTH modes. The PB-3 goldens use
  a TEST-OWNED description, so they cannot distinguish "the config
  authority flows" from "some string was substituted".
* an UNSUBSTITUTED placeholder token shipping to the LLM. A golden
  regenerated alongside a broken placeholder would still be green;
  §3.1 documents exactly that trap (an UPPERCASE placeholder can never
  substitute, because ``load_stage_prompt`` builds its search token from
  the lowercase key verbatim).
* someone hardcoding the description or its label back INTO a template
  (the anti-re-inlining pin, design §10.B) — every golden would still
  pass.
* the whitespace-only collapse, which lives in
  ``_render_pipeline_task_background``'s own ``strip`` and is invisible
  to the legacy ``_render_task_background`` tests.

Deliberately NOT re-tested here (design §10.C): the empty-description
``""`` return and the description-only/contract-free block SHAPE, both
already pinned by ``test_proposer_task_config.py``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from agent.prompt_templates.proposal import load_stage_prompt
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    MLModelProposalAgent,
    _render_pipeline_task_background,
)
from tests.unit.agent.ml_model_proposal_agent.test_step00_prompt_goldens import (
    _CannedProposerBridge,
    fixture_proposal_input,
    pin_environment,
)
from workflows.task_config import get_task_description, load_task_config

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_DIR = REPO_ROOT / "agent" / "prompt_templates" / "proposal"

#: The three pipeline stage base templates the JOIN targets (OD-S1-3(a)).
STAGE_TEMPLATES = (
    "comparison_stage.md",
    "causal_reasoning_stage.md",
    "proposing_stage.md",
)

#: Capture keys, in the order the pipeline calls the stages.
STAGES = ("comparison", "causal_reasoning", "proposing")

#: The label authority. Defined once, in
#: ``_render_task_background``; repeated here as the EXPECTATION so the
#: test fails if the production label silently changes.
LABEL = "Background on the task:"

#: An unsubstituted ``{placeholder}`` token: an identifier in braces.
#: Deliberately identifier-only, so it does not match the legitimate
#: literal ``{loss_name, description, ...}`` JSON sketch in
#: ``proposing_stage.md`` or the ``{# EXPLORATION_MODE_BLOCK #}`` marker.
PLACEHOLDER_TOKEN = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def capture_stage_systems(
    tmp_path,
    monkeypatch,
    *,
    mode: str,
    task_description: str,
) -> dict[str, str]:
    """Run the REAL pipeline and return ``{stage: system_prompt}``.

    Uses the PB-3 machinery (real ``MLModelProposalAgent.run()``, canned
    boundary bridge, pinned environment) so the captured strings are the
    exact bytes the LLM would receive — not a test-side re-assembly.
    Only ``task_description`` is varied off the shared fixture.
    """
    index_path = pin_environment(tmp_path, monkeypatch)
    inp = fixture_proposal_input(tmp_path, mode=mode).model_copy(
        update={"task_description": task_description}
    )
    agent = MLModelProposalAgent(
        provider="openai",
        model_id="step01b-capture",
        bridge_factory=_CannedProposerBridge,
        capability_index_path=index_path,
    )
    agent.run(inp)
    captures = agent.bridge.captures
    labels = [label for _method, label, _system, _user in captures]
    assert labels == [
        "proposer.comparison",
        "proposer.causal_reasoning",
        "proposer.proposing",
    ], f"unexpected stage sequence {labels} — a retry/correction means the fixture drifted"
    return {
        stage: system
        for (_method, _label, system, _user), stage in zip(captures, STAGES, strict=True)
    }


def shipped_description() -> str:
    """The description as PRODUCTION reads it — through the single
    authority, never copied into this file."""
    return get_task_description(load_task_config())


# ---------------------------------------------------------------------------
# F1 — the shipped description reaches all three stages, in both modes
# ---------------------------------------------------------------------------


class TestJoinReachesEveryStageSystemPrompt:
    @pytest.mark.parametrize("mode", ["explore", "exploit"])
    def test_shipped_description_present_exactly_once_per_stage(self, tmp_path, monkeypatch, mode):
        """Six captures (3 stages x 2 modes), asserted PER STAGE.

        An aggregate "appears somewhere in the renders" assertion would
        stay green with one stage left task-blind — adversarial finding
        A7. Counting (rather than testing membership) additionally
        catches a placeholder accidentally added twice, or added to a
        MODE overlay as well as the base template.
        """
        description = shipped_description()
        assert description, "the shipped task_config carries no description"
        systems = capture_stage_systems(
            tmp_path, monkeypatch, mode=mode, task_description=description
        )
        assert set(systems) == set(STAGES)
        for stage in STAGES:
            system = systems[stage]
            assert system.count(description) == 1, (
                f"stage {stage!r} ({mode}): shipped description appears "
                f"{system.count(description)} times, expected exactly 1"
            )
            assert system.count(LABEL) == 1, (
                f"stage {stage!r} ({mode}): task-background label appears "
                f"{system.count(LABEL)} times, expected exactly 1"
            )

    @pytest.mark.parametrize("mode", ["explore", "exploit"])
    def test_no_unsubstituted_placeholder_reaches_the_boundary(self, tmp_path, monkeypatch, mode):
        """§3.1: a placeholder that never substitutes ships a literal
        brace token to the LLM, and a regenerated golden would not
        notice. Scan the real captured bytes instead."""
        systems = capture_stage_systems(
            tmp_path, monkeypatch, mode=mode, task_description=shipped_description()
        )
        for stage, system in systems.items():
            survivors = sorted(set(PLACEHOLDER_TOKEN.findall(system)))
            assert survivors == [], (
                f"stage {stage!r} ({mode}): unsubstituted placeholder token(s) "
                f"{survivors} reached the LLM boundary"
            )


# ---------------------------------------------------------------------------
# F3 — one label authority; the block is never re-inlined into a template
# ---------------------------------------------------------------------------


class TestTemplateLayerJoinPins:
    """The anti-re-inlining guard (design §10.B).

    This is the one deliberately shape-adjacent pin in the PR: it is the
    only check that fails when someone pastes the description or its
    label straight into a template. Every golden would still be green,
    because the rendered bytes would be identical.
    """

    @pytest.mark.parametrize("template", STAGE_TEMPLATES)
    def test_base_template_carries_the_placeholder_exactly_once(self, template):
        body = (TEMPLATE_DIR / template).read_text(encoding="utf-8")
        assert body.count("{task_background_block}") == 1

    @pytest.mark.parametrize("template", STAGE_TEMPLATES)
    def test_base_template_does_not_restate_the_label(self, template):
        body = (TEMPLATE_DIR / template).read_text(encoding="utf-8")
        assert LABEL not in body, (
            f"{template}: the task-background label must have exactly ONE "
            f"authority (the renderer), never a per-template copy"
        )

    @pytest.mark.parametrize("template", STAGE_TEMPLATES)
    def test_mode_overlays_do_not_carry_the_placeholder(self, template):
        """Placing it in a MODE file instead of the base template would
        leave the other mode task-blind (adversarial finding A7)."""
        stem = template[: -len(".md")]
        for mode in ("explore", "exploit"):
            overlay = TEMPLATE_DIR / f"{stem}_{mode}.md"
            if overlay.exists():
                assert "{task_background_block}" not in overlay.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# F2 — collapse, including the whitespace-only case
# ---------------------------------------------------------------------------


class TestEmptyAndWhitespaceCollapse:
    def test_absent_description_emits_no_label_or_stray_line(self):
        """Whitespace-only is the case the legacy helper gets WRONG:
        ``_render_task_background("   ", ForwardContract())`` renders a
        label over a blank bullet, because its guard is
        ``not task_description``. The pipeline renderer strips first, so
        deleting that strip reddens this test and nothing else."""
        for description in ("", "   ", "\n\t \n"):
            assert _render_pipeline_task_background(description) == ""

    def test_empty_description_leaves_the_stage_prompt_unchanged(self):
        """The block collapses with no orphan heading AND no stray blank
        line: the rendered prompt is byte-identical to the same template
        rendered with the placeholder removed entirely."""
        for template in STAGE_TEMPLATES:
            stem = template[: -len(".md")]
            collapsed = load_stage_prompt(
                stem,
                exploration_mode="explore",
                template_vars={"task_background_block": _render_pipeline_task_background("")},
            )
            assert LABEL not in collapsed
            assert "\n\n\n" not in collapsed.split("## Your task")[0], (
                f"{template}: the collapsed block left a stray blank line"
            )


# ---------------------------------------------------------------------------
# Negative input — a description carrying brace-like tokens
# ---------------------------------------------------------------------------


class TestBraceTokensInDescription:
    """``load_stage_prompt`` substitutes sequentially with ``str.replace``,
    so an injected VALUE containing another key's placeholder text is an
    ordering hazard worth pinning.

    Audited scope of that hazard (design §4.1's "must not corrupt other
    substitutions"): because ``str.replace`` acts on DISTINCT tokens at
    DISTINCT sites, no other placeholder's own site can ever receive the
    wrong value. The only order-dependent effect is confined to the
    injected block itself — a token inside the description either
    survives verbatim (its key was substituted earlier) or expands (its
    key is substituted later). This is a pre-existing property of every
    rendered ``*_block`` value, not something the JOIN introduces, so the
    §4.1 "STOP and report" branch is not triggered.

    What this test alone catches: a future refactor of the substitution
    mechanism to ``str.format`` / ``string.Template``, which would raise
    on brace-bearing content instead of passing it through; and any
    attempt to "fix" the hazard by sanitising the shipped description.
    """

    def test_brace_tokens_do_not_break_the_other_placeholder_sites(self):
        description = "task {minimum_boldness} and {available_losses_block} tokens"
        rendered = load_stage_prompt(
            "causal_reasoning_stage",
            exploration_mode="explore",
            template_vars={
                "task_background_block": _render_pipeline_task_background(description),
                "minimum_boldness": "0.05",
                "available_losses_block": "LOSS-REGISTRY-BLOCK",
            },
        )
        # Every one of the template's OWN placeholder sites rendered its
        # own value — the loop was neither derailed nor aborted.
        assert "0.05" in rendered
        assert "LOSS-REGISTRY-BLOCK" in rendered
        assert "{task_background_block}" not in rendered
        # The description's non-brace prose survives verbatim; the block
        # was rendered, not sanitised away.
        assert LABEL in rendered
        assert rendered.count("- task ") == 1
        assert " tokens\n" in rendered


# ---------------------------------------------------------------------------
# Render determinism
# ---------------------------------------------------------------------------


_DETERMINISM_SNIPPET = """
import hashlib, sys
sys.path.insert(0, {root!r})
from agent.prompt_templates.proposal import load_stage_prompt
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _render_pipeline_task_background,
)
from workflows.task_config import get_task_description, load_task_config

block = _render_pipeline_task_background(get_task_description(load_task_config()))
digest = hashlib.sha256()
for stem in ("comparison_stage", "causal_reasoning_stage", "proposing_stage"):
    for mode in ("explore", "exploit"):
        digest.update(
            load_stage_prompt(
                stem, exploration_mode=mode, template_vars={{"task_background_block": block}}
            ).encode("utf-8")
        )
print(digest.hexdigest())
"""


def test_join_render_is_byte_stable_across_fresh_processes():
    """Two fresh interpreters must produce byte-identical renders.

    Hash-randomisation and any dict/set iteration that leaked into the
    block would show up here and nowhere else in this module — the
    in-process tests all share one interpreter.
    """
    snippet = _DETERMINISM_SNIPPET.format(root=str(REPO_ROOT))
    digests = []
    for seed in ("0", "1"):
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed},
            check=True,
        )
        digests.append(proc.stdout.strip())
    assert digests[0] == digests[1], f"render is not byte-stable: {digests}"
