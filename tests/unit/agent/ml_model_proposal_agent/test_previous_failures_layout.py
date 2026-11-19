"""Multi-line ``previous_failures`` entries stay inside their numbered item (#1555).

What only these tests catch:

* a continuation line of a multi-line entry starting at column 0, where the
  model reads it as the next list item, in the production reasoning prompt;
* a single-line entry or a whole single-line list changing bytes, or entering
  the ``proposal.failure_entry_layout`` boundary (a historical profile that
  does not declare it would then raise);
* the siderius-exp pin: a profile returning ``f"  {number}. {entry}"``
  reproduces the pre-#1555 block byte for byte.
"""

from __future__ import annotations

import pytest

from agent.prompt_rendering import PromptRenderingProfile, bind_prompt_profile
from agent.prompt_templates.proposal.previous_failures import previous_failure_items
from nodes.ml_model_proposal_agent import _build_reasoning_prompt

from . import test_proposal_agent as _proposal_agent_tests

pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")

_MULTI = "V2 forward ignores the gate\n\nEarlier attempts (oldest first):\n  Attempt 1: V1"


def _profile(tmp_path, renderers):
    source = tmp_path / "provider.txt"
    source.write_text("fixed paper-style provider")
    return PromptRenderingProfile("paper-style", "1", renderers, frozenset(), {"source": source})


def _block(prompt: str) -> str:
    start = prompt.index("## Previous Failed Proposals")
    return prompt[start : prompt.index("\n\n", start)]


def test_continuation_lines_are_indented_under_their_item():
    inp = _proposal_agent_tests.TestBuildReasoningPromptEnriched()._make_enriched_input()
    inp.previous_failures = ["single cause", _MULTI]
    assert _block(_build_reasoning_prompt(inp)) == (
        "## Previous Failed Proposals (DO NOT repeat these mistakes)\n"
        "  1. single cause\n"
        "  2. V2 forward ignores the gate"
    )
    full = _build_reasoning_prompt(inp)
    item = full[full.index("  2. V2") :]
    assert item.startswith(
        "  2. V2 forward ignores the gate\n\n"
        "     Earlier attempts (oldest first):\n"
        "       Attempt 1: V1\n"
    )


def test_item_width_follows_the_number_and_blank_lines_stay_empty():
    items = previous_failure_items([f"e{n}" for n in range(1, 10)] + ["first\n\nsecond"])
    assert items[-1] == "  10. first\n\n      second"
    assert items[0] == "  1. e1"


def test_single_line_lists_never_enter_the_boundary(tmp_path):
    """An undeclared historical profile raises when the boundary is entered;
    single-line entries must not reach it."""
    with bind_prompt_profile(_profile(tmp_path, {})):
        assert previous_failure_items(["a", "b"]) == ["  1. a", "  2. b"]


def test_profile_restores_the_pre_1555_layout(tmp_path):
    pinned = _profile(
        tmp_path,
        {"proposal.failure_entry_layout": lambda number, entry: f"  {number}. {entry}"},
    )
    with bind_prompt_profile(pinned):
        assert previous_failure_items(["a", _MULTI]) == ["  1. a", f"  2. {_MULTI}"]
