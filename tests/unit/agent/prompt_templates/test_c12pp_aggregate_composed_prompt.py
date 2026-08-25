"""C12-P-P — THE AGGREGATE INVARIANT. Both mechanisms, one union, real binding.

WHAT THIS IS
------------
P1-A (the computed constraint block) and P1-B (the hardcoded template shapes)
are separate mechanisms with separate falsifiers. **Closing one is not closing
the unit.** This module holds the single assertion that spans both:

    the COMPLETE proposing prompt of a foreign composed task contains
    NONE of the known TIDMAD-specific contamination markers

The marker set below is a **union** and must never be split, narrowed or
parameterised per mechanism. Making this file green by deleting a needle is the
F-12bc-9 shape — a census whose own scope excluded the thing it was written to
find — and is explicitly forbidden.

WHY IT RENDERS UNDER A REAL COMPOSED BINDING
--------------------------------------------
Two ways to get this wrong, both of which produce a green test that proves
nothing:

1. Reading a committed baseline. That is a snapshot of the PRE-fix state; no
   production change can move it, so only re-capturing could turn it green —
   certifying a ceremony (the F-12bc-7 lesson).
2. Loading a pack's ``task_config.yaml`` directly. That raises
   ``DatasetContradictionError`` against the ambient TIDMAD ``ValueEncoding``,
   so the test fails for the wrong reason — or, if the error were caught, would
   render a prompt with no forward contract at all, and P1-B's safety argument
   rests on that block being present.

So the prompt is rendered through ``compose_run_task_bindings`` +
``bind_run_task_composition`` with an EMPTY data root, then through the
production ``_run_pipeline``. Measured: ~1.5 s for all three tasks, no real
data, no training, no GPU, no network.
"""

from __future__ import annotations

import pytest

from tests.helpers.c12pp_composed_render import proposing_system_prompt

# --------------------------------------------------------------------------
# THE UNION. Hardcoded literals, never derived from the code under test.
# --------------------------------------------------------------------------
P1A_MARKERS: tuple[str, ...] = (
    "SYSTEM-ENFORCED DATASET CONSTRAINTS",
    "psd_segment_length",
    "10,000,000",
    "16384",
    "16000 is the nearest valid neighbor",
)
P1B_MARKERS: tuple[str, ...] = (
    "[B, 256, T]",
    "[B, T]",
)
#: PR-12a's prose, already suppressed by the proposal_blocks channel. Kept in
#: the union so a regression in that channel is caught here too.
PRIOR_MARKERS: tuple[str, ...] = ("256 amplitude bins",)

ALL_MARKERS: tuple[str, ...] = P1A_MARKERS + P1B_MARKERS + PRIOR_MARKERS

FOREIGN_TASKS = ("pets", "davis")


@pytest.fixture(scope="module")
def data_root(tmp_path_factory: pytest.TempPathFactory) -> str:
    """An EMPTY physical data root.

    The binding requires one declared (Step 11 R-11-8) so no child silently
    falls back to ``TIDMAD_DATA_DIR``. Nothing in prompt assembly reads it, so
    an empty directory is not a shortcut — it is proof the prompt path needs no
    data.
    """
    return str(tmp_path_factory.mktemp("c12pp_empty_data_root"))


# ==========================================================================
# THE AGGREGATE ASSERTION
# ==========================================================================


@pytest.mark.parametrize("task", FOREIGN_TASKS)
def test_foreign_composed_prompt_carries_no_tidmad_contamination_aggregate(
    task: str, data_root: str
) -> None:
    """A foreign composed task's full proposing prompt is free of TIDMAD science.

    DEFECT THIS ALONE CATCHES
        Contamination arriving from EITHER mechanism, or from a future third
        one. The per-mechanism suites each see only their own surface: P1-A's
        A1 checks the computed block, P1-B's B1 checks the template file. Only
        this test reads the ASSEMBLED prompt a real model would receive, so
        only this test can catch a marker that reaches it by some other route.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        Every marker found is named, with the task. Because the prompt is
        rendered live under a real binding, reverting either production change
        turns this red immediately — no fixture regeneration involved.
    """
    prompt = proposing_system_prompt(task, data_root)
    found = [marker for marker in ALL_MARKERS if marker in prompt]
    assert found == [], (
        f"the composed {task} proposing prompt carries TIDMAD-only science: "
        f"{found}. This task has no PSD segment length and no 256-level "
        "amplitude axis."
    )


# ==========================================================================
# NON-VACUITY — the union must still be findable where it belongs
# ==========================================================================


def test_aggregate_matcher_is_not_blind_and_tidmad_keeps_its_science(
    data_root: str,
) -> None:
    """TIDMAD's own prompt still contains EVERY marker in the union.

    DEFECT THIS ALONE CATCHES
        Two at once, which is why it is one test:

        1. **A vacuous union.** A misspelled needle, a renamed stage, or an
           empty render would make the aggregate pass while seeing nothing.
           Requiring the same matcher to find all nine markers somewhere makes
           that impossible.
        2. **Over-deletion.** The operator ruling forbids removing useful
           guidance from genuine TIDMAD runs. If a future "fix" strips these
           from TIDMAD too, the aggregate would go green and this goes red.

    NOTE ON P1-B's MARKERS
        ``[B, 256, T]`` and ``[B, T]`` must still be here — but they now come
        from ``{forward_contract}``, TIDMAD's own declaration, not from the
        shared template. That is exactly P1-B's safety argument, asserted
        rather than assumed.
    """
    prompt = proposing_system_prompt("tidmad", data_root)
    missing = [marker for marker in ALL_MARKERS if marker not in prompt]
    assert missing == [], (
        f"TIDMAD's proposing prompt is missing {missing}. Either the matcher is "
        "blind — making the aggregate assertion vacuous — or TIDMAD has lost "
        "scientific instruction it is entitled to keep."
    )


def test_forward_contract_is_actually_present_in_every_rendered_prompt(
    data_root: str,
) -> None:
    """Every task's prompt carries its own forward contract.

    DEFECT THIS ALONE CATCHES
        The fixture defect this unit found in its own earlier evidence: a
        prompt rendered with ``forward_contract`` left default-EMPTY renders
        that block as "". The aggregate assertion would still pass — markers
        are absent when the block is absent — but it would be certifying a
        prompt production never emits, and P1-B's justification for deleting
        the template's shapes would be unsupported.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        The task whose contract block vanished is named.
    """
    for task in ("tidmad", *FOREIGN_TASKS):
        prompt = proposing_system_prompt(task, data_root)
        assert "forward contract (non-negotiable)" in prompt, (
            f"{task}'s rendered prompt carries no forward-contract block, so "
            "this render cannot support any claim about shape guidance"
        )
