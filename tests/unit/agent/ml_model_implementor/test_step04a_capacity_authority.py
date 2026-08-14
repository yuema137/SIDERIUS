"""Step 04a / OD-S4-1 — the implementor's capacity prose derives from hardware.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §16 C6 and §14.1 OD-S4-1;
parent §12 (the ONE deliberate byte change in Step 04).

**The defect this closes.** The implementor's system prompt read

    - GPU budget: <10 GB VRAM, <100M parameters for initial exploration.

while the proposer — since Step 01 — has quoted the *live* cap from the same
machine (a real gpt-5.5 run cited 25.07 GB on an RTX 5090). So the two nodes
in one pipeline were told to build for machines differing by ~2.5x, and the
parameter ceiling had no authority behind it at all. A stale literal is worse
than no literal: it is confidently wrong, and it silently caps exploration.

**The defect only this module catches.** The `pb5_*` golden pins the rendered
bytes, but a golden cannot tell a derived string from a differently-worded
constant — regenerate it and both look identical. These tests assert that the
rendered text actually *tracks* the manifest, and that the template carries no
capacity magnitude for a future edit to re-bake.

**Scope discipline.** OD-S4-1 authorizes exactly one LLM-visible delta in
Step 04: this bullet, in `pb5_reasoning_system.txt`. Any other moved byte is a
defect, not a golden to update — which is why the attribution test below
enumerates the golden set rather than trusting review.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.schemas.implementor import ImplementorInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.hardware_context import HardwareContext
from nodes.ml_model_implementor.ml_model_implementor import (
    IMPLEMENTOR_CODE_PROMPT,
    IMPLEMENTOR_LOSS_CODE_PROMPT,
    IMPLEMENTOR_LOSS_REASONING_PROMPT,
    IMPLEMENTOR_LOSS_REPAIR_PROMPT,
    IMPLEMENTOR_REASONING_PROMPT,
    IMPLEMENTOR_REPAIR_PROMPT,
    _build_reasoning_system_prompt,
    _render_capacity_budget,
)

GOLDENS = Path(__file__).parent / "goldens"


def _ctx(total_gb: float, *, available: bool = True, name: str = "NVIDIA Test GPU"):
    return HardwareContext(
        device_name=name,
        total_memory_bytes=int(total_gb * (1024**3)),
        compute_capability=(9, 0),
        multiprocessor_count=64,
        torch_version="2.0.0",
        hostname="s04a-test-host",
        device_available=available,
        discovered_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def _input(**kw) -> ImplementorInput:
    return ImplementorInput(
        model_name="s04a_capacity",
        model_description="x",
        mathematical_definition="x",
        baseline_config={"model_config": {}, "train_config": {}},
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="/tmp/s04a_cap", run_name="r1"),
        ),
        **kw,
    )


# ---------------------------------------------------------------------------
# The rendered text TRACKS the manifest
# ---------------------------------------------------------------------------


def test_the_rendered_cap_follows_the_live_manifest_not_a_constant():
    """Two different machines must produce two different numbers.

    Fails when: the bullet is re-hardcoded, or wired to anything other than
    the live manifest. A single-machine assertion could not tell those apart
    — this one names the 80% safety fraction's consequence on two devices.
    """
    small = _render_capacity_budget(_ctx(10.0), None)
    large = _render_capacity_budget(_ctx(32.0), None)

    assert "8.00 GB" in small
    assert "25.60 GB" in large
    assert small != large


def test_an_operator_budget_below_the_physical_cap_binds():
    """BUDGET regime: the operator ceiling is what the implementor is told."""
    assert "12.00 GB" in _render_capacity_budget(_ctx(32.0), 12.0)


def test_an_operator_budget_above_the_physical_cap_does_not():
    """PHYSICAL VETO: a budget above the 80% floor cannot raise the cap.

    Fails when: the implementor quotes the operator's number while the VRAM
    engine enforces the physical one — the two would then disagree, and the
    LLM would be invited to build something guaranteed to be rejected.
    """
    rendered = _render_capacity_budget(_ctx(32.0), 999.0)
    assert "25.60 GB" in rendered
    assert "999" not in rendered


def test_the_implementor_and_the_proposer_quote_the_SAME_cap():
    """One rule, two consumers — asserted across the node boundary.

    ``HardwareContext.effective_cap_gb`` was extracted so these two cannot
    drift. Fails when: either node reimplements the regime arithmetic.
    """
    from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
        _render_hardware_context_block,
    )

    ctx, budget = _ctx(32.0), 12.0
    proposer_block = _render_hardware_context_block(ctx, budget)
    implementor_bullet = _render_capacity_budget(ctx, budget)

    cap = f"{ctx.effective_cap_gb(budget):.2f} GB"
    assert cap in proposer_block
    assert cap in implementor_bullet


# ---------------------------------------------------------------------------
# Degradation — a defined string, never a literal, never a crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "ctx"),
    [("no manifest", None), ("cpu-only host", _ctx(8.0, available=False))],
)
def test_capacity_degrades_to_a_magnitude_free_string(label, ctx):
    """C6 edge case: unavailable hardware must not crash or invent a number.

    Fails when: the fallback carries a magnitude — which would be exactly the
    stale ceiling OD-S4-1 removes, reintroduced through the back door.
    """
    rendered = _render_capacity_budget(ctx, None)

    assert rendered.startswith("- GPU budget:")
    assert not re.search(r"\d+(\.\d+)?\s*(GB|GiB|MB|M)\b", rendered), (
        f"{label}: the fallback names a magnitude it cannot know"
    )


def test_the_prompt_renders_end_to_end_with_and_without_hardware():
    """The placeholder never survives, on either path.

    Fails when: a caller that supplies no hardware leaves ``{CAPACITY_BUDGET}``
    literally in the prompt sent to the LLM.
    """
    for inp in (_input(), _input(hardware_context=_ctx(32.0), vram_budget_gb=12.0)):
        prompt = _build_reasoning_system_prompt(inp)
        assert "{CAPACITY_BUDGET}" not in prompt
        assert "{TASK_BACKGROUND}" not in prompt
        assert "- GPU budget:" in prompt

    live = _build_reasoning_system_prompt(_input(hardware_context=_ctx(32.0), vram_budget_gb=12.0))
    assert "12.00 GB" in live
    assert "NVIDIA Test GPU" in live


# ---------------------------------------------------------------------------
# The reused Step-01 concept detector, over the implementor scan set
# ---------------------------------------------------------------------------

_IMPLEMENTOR_TEMPLATES = {
    "IMPLEMENTOR_REASONING_PROMPT": IMPLEMENTOR_REASONING_PROMPT,
    "IMPLEMENTOR_CODE_PROMPT": IMPLEMENTOR_CODE_PROMPT,
    "IMPLEMENTOR_REPAIR_PROMPT": IMPLEMENTOR_REPAIR_PROMPT,
    "IMPLEMENTOR_LOSS_REASONING_PROMPT": IMPLEMENTOR_LOSS_REASONING_PROMPT,
    "IMPLEMENTOR_LOSS_CODE_PROMPT": IMPLEMENTOR_LOSS_CODE_PROMPT,
    "IMPLEMENTOR_LOSS_REPAIR_PROMPT": IMPLEMENTOR_LOSS_REPAIR_PROMPT,
}


def _numeric_capacity_literals(text: str) -> list[str]:
    """Step 01's S1-E detector, reused rather than reinvented (C6 plan).

    Imported by value rather than by reference because it lives in the
    proposer's test module; the regexes are identical and the concept is the
    one Step 01 froze — a MAGNITUDE appearing near CAPACITY language. Both
    halves are required: templates legitimately contain bare numerals
    (``[B, 256, T]``) and legitimately contain capacity prose with no numeral.
    """
    from tests.unit.agent.ml_model_proposal_agent.test_prompt_ceiling_policy import (
        _numeric_capacity_literals as detector,
    )

    return detector(text)


#: The ONE snippet the detector flags that is NOT a capacity claim.
#:
#: ``IMPLEMENTOR_REASONING_PROMPT`` teaches why a construction-time ``[T, T]``
#: buffer is fatal, with worked arithmetic: *"a [T, T] buffer at T=16000 costs
#: 1 GB of RAM; 4 layers × optimizer moments = >10 GB — the process will be
#: OOM-killed BEFORE training starts"*.
#:
#: That is a statement about an ALGORITHM's growth, not about this machine's
#: ceiling: the numbers stay true on any host, and they do not tell the LLM
#: how large a model it may build. The detector is a deliberate
#: over-approximation (a magnitude near capacity words), so it cannot make
#: that distinction and the exception is declared here instead.
#:
#: It is NOT reworded, because rewording it would be a second LLM-visible
#: prompt delta and OD-S4-1 authorizes exactly one.
_ALLOWED_NON_CAPACITY_ARITHMETIC = "OOM-killed BEFORE training starts"


def test_no_implementor_template_carries_a_numeric_capacity_literal():
    """OD-S4-1's standing guard.

    Fails when: any capacity magnitude is baked back into an implementor
    template — the defect this PR removes, and the one most likely to return,
    because ``<10 GB VRAM`` reads as helpful guidance rather than as a claim
    about a machine nobody checked.

    The single declared exception is allowlisted by CONTENT, not by count, so
    a new literal appearing beside it still fails.
    """
    offenders = {
        name: unexplained
        for name, text in _IMPLEMENTOR_TEMPLATES.items()
        if (
            unexplained := [
                snippet
                for snippet in _numeric_capacity_literals(text)
                if _ALLOWED_NON_CAPACITY_ARITHMETIC not in snippet
            ]
        )
    }
    assert not offenders, (
        "implementor templates reintroduced a hardcoded capacity budget; it "
        f"must come from the live [HARDWARE CONTEXT] instead: {offenders}"
    )


def test_the_allowlisted_snippet_is_still_present_and_still_singular():
    """The allowlist above must not silently grow into a blanket exemption.

    Fails when: the declared exception disappears (the allowlist is then dead
    and should be removed), or when MORE than one flagged snippet exists in
    the reasoning prompt — at which point the second one needs its own
    justification rather than inheriting this one's.
    """
    flagged = _numeric_capacity_literals(IMPLEMENTOR_REASONING_PROMPT)
    assert len(flagged) == 1, f"expected exactly the OOM example, got {flagged}"
    assert _ALLOWED_NON_CAPACITY_ARITHMETIC in flagged[0]


def test_the_detector_actually_fires_on_the_removed_literal():
    """Reachability for the guard above — otherwise it could be vacuous.

    A guard that passes because its detector never matches anything is
    indistinguishable from a guard that passes because the code is clean.
    This feeds it the exact string that was removed.
    """
    assert _numeric_capacity_literals(
        "- GPU budget: <10 GB VRAM, <100M parameters for initial exploration."
    )


# ---------------------------------------------------------------------------
# Attribution of the ONE authorized golden delta
# ---------------------------------------------------------------------------


def test_only_the_capacity_bullet_moved_in_the_pb5_golden_set():
    """Every changed `pb5_*` byte is attributable to OD-S4-1.

    Fails when: a second golden moves, or the capacity golden moves in a
    second place. Parent §19 makes an unattributable `pb5_*` delta a STOP
    condition, so this is the mechanical form of that check rather than a
    reviewer's promise.
    """
    capacity_line_owners = [
        path.name
        for path in sorted(GOLDENS.glob("pb5_*.txt"))
        if "GPU budget" in path.read_text(encoding="utf-8")
    ]
    assert capacity_line_owners == ["pb5_reasoning_system.txt"], (
        "the capacity bullet appears in more pb5 goldens than the declared "
        f"OD-S4-1 set: {capacity_line_owners}"
    )

    golden = (GOLDENS / "pb5_reasoning_system.txt").read_text(encoding="utf-8")
    assert "<10 GB VRAM" not in golden
    assert "<100M parameters" not in golden
    assert golden.count("- GPU budget:") == 1
