"""PR 01b / commit S1-E — the legacy reasoning SYSTEM baseline.

Design: `pr_01b_task_description_join.md` §4.3; parent §8.1 (the PB-0
row) and §13 rule 3 (regeneration event R3).

Why this golden exists at all. Step-00's PB-0 baseline pins the legacy
proposer USER prompt (`reasoning_prompt_structured_evidence.txt`, via
`test_health_prompt_parity.py`). The legacy **SYSTEM** prompt — the
`{TASK_BACKGROUND}` path through `PROPOSAL_REASONING_PROMPT` — has NO
full-string oracle anywhere in the repository. S1-E edits exactly that
surface, so without a capture taken FIRST the edit would change an
unpinned surface and its diff would be unreviewable.

**Ordering is an acceptance criterion, not a nicety** (§4.3 failure
cases): the golden was captured BEFORE the literal was touched, and the
regeneration diff in the same commit therefore shows only the literal's
removal.

Capture layer: the REAL legacy `run()` path through
`BoundaryRecorderBridge`, reusing the PB-4 harness. Capturing at the
boundary rather than by calling `_build_reasoning_system_prompt`
directly is what makes deleting the render call at the production call
site observable — the 2nd-review R2-4 lesson PB-4 already learned.
"""

from __future__ import annotations

from tests.helpers.golden import assert_golden
from tests.unit.agent.ml_model_proposal_agent.test_step00_prompt_goldens import (
    GOLDENS,
    _run_legacy_capture,
    _shipped_forward_contract,
    pinned_env,
)

GOLDEN = GOLDENS / "s1e_legacy_reasoning_system.txt"


def capture_legacy_reasoning_system(tmp_path, pinned_env: str) -> str:
    """Return the legacy reasoning SYSTEM prompt as the LLM receives it.

    Pinned to the SHIPPED ForwardContract, matching PB-4's precedent: the
    legacy surface renders the shipped declaration in production, and the
    test-owned PB-3 fixture profile (192 classes) would pin the wrong
    thing.
    """
    bridge = _run_legacy_capture(tmp_path, pinned_env, forward_contract=_shipped_forward_contract())
    reasoning = [c for c in bridge.captures if c[1] == "proposer.legacy_reasoning"]
    assert len(reasoning) == 1, (
        f"the legacy reasoning call must reach the boundary exactly once, got {len(reasoning)}"
    )
    _method, _label, system, _user = reasoning[0]
    return system


class TestS1ELegacyReasoningSystemGolden:
    def test_legacy_reasoning_system_matches_the_golden(self, tmp_path, pinned_env):
        assert_golden(
            capture_legacy_reasoning_system(tmp_path, pinned_env),
            GOLDEN,
            surface="S1-E legacy reasoning system prompt (rendered, at the boundary)",
        )

    def test_placeholder_is_actually_consumed(self, tmp_path, pinned_env):
        """Differential, mirroring PB-4's: the raw constant must NOT equal
        the golden while the RENDER does. Without this, a regression that
        stopped substituting `{TASK_BACKGROUND}` could ship a literal
        brace token and the golden alone would not say why."""
        from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
            PROPOSAL_REASONING_PROMPT,
        )

        golden = GOLDEN.read_text(encoding="utf-8")
        assert PROPOSAL_REASONING_PROMPT != golden
        assert "{TASK_BACKGROUND}" in PROPOSAL_REASONING_PROMPT
        assert "{TASK_BACKGROUND}" not in golden
