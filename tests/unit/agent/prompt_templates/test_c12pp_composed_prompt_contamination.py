"""C12-P-P — a foreign composed task must not be taught TIDMAD's dataset rules.

THE CLAIM UNDER TEST (operator-ruled 2026-08-24)
------------------------------------------------
A foreign composed task must not receive TIDMAD-specific scientific constraints
merely because it traverses the shared proposer prompt path; and existing
TIDMAD / Regime-A prompt semantics must stay BYTE-EQUIVALENT.

Those are two opposite failure directions, so they are two different tests. A
single test cannot express both: one asserts ABSENCE in one regime, the other
asserts EXACT PRESENCE in the other, and a fix that satisfies only one of them
is precisely the regression the pair exists to catch.

STATE AT LANDED MASTER
----------------------
``test_foreign_composed_prompt_has_no_tidmad_dataset_constraints`` is expected
to FAIL until the bounded fix lands. That RED is the finding, not a broken
test: it is the executable form of the contamination C12-P-P was asked to
establish. Every other test here passes today and guards what must not move.

WHY THE LITERALS ARE HARDCODED
------------------------------
Every marker below is written out as a literal string. None is read back from
``execute_tools.dataset_config.TIDMAD``, from ``_format_known_constraints_block``
or from any baseline file. A marker derived from the thing under test would
follow that thing when it changes and could never fail -- the project's
"never assert a value read back from the thing under test" rule, which is
exactly the shape that let F-12bc-7 through.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.helpers import c12pp_prompt_capture as capture


@pytest.fixture(autouse=True)
def _offline_client_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the live-render guards runnable in a key-less environment.

    WHY THIS EXISTS (C12-P parent review, 2026-08-24). These tests originally
    called ``pytest.skip()`` when ``OPENAI_API_KEY`` was unset. That silently
    disabled the SIX Regime-A byte-parity cases — and by this module's own
    reasoning those are *the only* assertions that fail when a fix strips the
    dataset-constraint block from **both** regimes instead of just the foreign
    one. CI runs unit + static with no API keys by design, so the single most
    important guard in this unit would have been absent exactly where it is
    relied upon: green, and vacuous.

    Setting the variable is sound rather than a workaround: the key is read
    only for the OpenAI *client object*'s eager construction. Both
    ``LLMBridge.generate`` and ``LLMBridge.generate_text`` are patched with a
    ``side_effect`` in :mod:`tests.helpers.c12pp_prompt_capture`, so no request
    can be issued — zero LLM calls, zero network. The value is deliberately
    non-credential-shaped so it can never be mistaken for a real secret, and
    ``monkeypatch`` scopes it to the test.

    A real key already present in the environment is left untouched.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        monkeypatch.setenv("OPENAI_API_KEY", "offline-render-only-not-a-credential")


# --------------------------------------------------------------------------
# TIDMAD-ONLY MARKERS. Hardcoded, never derived.
#
# Each is a fact true of TIDMAD's SQUID/ADC dataset and of nothing else: the
# 1-second PSD segment at 10 MS/s, the divisor rule that follows from it, and
# the 256-level int8 ADC amplitude axis. A task with 224x224 RGB images or
# 480p video frames has no psd_segment_length and no amplitude bins.
# --------------------------------------------------------------------------
TIDMAD_ONLY_MARKERS: tuple[str, ...] = (
    # --- the computed dataset-constraint block (agent/prompts.py:720) ---
    "SYSTEM-ENFORCED DATASET CONSTRAINTS",
    "psd_segment_length",
    "10,000,000",
    "16384",
    "16000 is the nearest valid neighbor",
    # --- the prose the PR-12a proposal_blocks channel already removes.
    # Kept as a REGRESSION guard: it is the one marker whose absence from the
    # foreign prompt is already correct today, so it pins a working fix.
    "256 amplitude bins",
    # NOTE — "[B, 256, T]" is deliberately NOT in THIS module's set any more.
    # P1-B removed it from the stage template, and this harness renders with an
    # EMPTY forward_contract, so it legitimately no longer appears here.
    #
    # It is NOT dropped from the unit's evidence: the full union, including
    # both P1-B shape literals, lives in
    # test_c12pp_aggregate_composed_prompt.py::ALL_MARKERS, asserted against a
    # REAL composed binding with the forward contract populated. That module
    # owns the contamination claim; this set is scoped to what a
    # TIDMAD-profile, empty-contract render can actually show.
)

#: The regimes whose baselines were captured, and the stage whose prompt the
#: dataset-constraint block reaches (the proposing stage's SYSTEM prompt).
_PROPOSING_SYSTEM = "03_proposer_proposing__system"


def _baseline(regime: str, stem: str) -> Path:
    path = capture.BASELINE_DIR / f"{regime}__{stem}.txt"
    if not path.is_file():  # pragma: no cover - fixture integrity
        raise AssertionError(
            f"missing captured baseline {path}. Regenerate with "
            f"`python -m tests.helpers.c12pp_prompt_capture` (see its docstring)."
        )
    return path


def _markers_present(text: str) -> list[str]:
    """Which TIDMAD-only markers appear in ``text``. The one matcher all tests share."""
    return [marker for marker in TIDMAD_ONLY_MARKERS if marker in text]


# ==========================================================================
# 1. WHAT THIS HARNESS ACTUALLY MODELS  (superseded scope — see the aggregate)
# ==========================================================================


def test_proposal_blocks_alone_does_not_make_a_run_foreign() -> None:
    """Varying ``proposal_blocks`` does NOT produce a foreign task's prompt.

    SUPERSESSION NOTICE
        This slot used to hold
        ``test_foreign_composed_prompt_has_no_tidmad_dataset_constraints``. Its
        premise was wrong, and W1 disproved it: this harness varies only
        ``proposal_blocks``, leaving the run's DATASET PROFILE bound to TIDMAD.
        After P1-A the constraint block follows the profile — correctly — so
        the "foreign" regime here still receives TIDMAD's block, because it is
        still a TIDMAD run that merely declares no proposer prose.

        The real foreign case needs a real composed binding and now lives in
        ``test_c12pp_aggregate_composed_prompt.py``, which renders Pets and
        DAVIS through ``bind_run_task_composition``. That module owns the
        contamination claim; this one is narrowed to Regime-A byte parity.

    DEFECT THIS TEST ALONE CATCHES
        Someone re-reading ``proposal_blocks`` as the composed/un-composed
        discriminator for DATASET science and rebuilding a "foreign" fixture on
        it — which would silently weaken the contamination evidence back to
        what it was before W1, while looking green.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        If suppressing ``proposal_blocks`` ever also suppressed the dataset
        constraint block, the two renders would stop agreeing and the equality
        below fails.
    """
    with_blocks = capture.capture_prompts(capture.tidmad_regime_a_blocks())
    without_blocks = capture.capture_prompts(capture.foreign_composed_blocks())

    def _proposing(captures):
        for label, system_prompt, _user in captures:
            if "proposing" in label:
                return system_prompt
        raise AssertionError("no proposing stage rendered")

    a, b = _proposing(with_blocks), _proposing(without_blocks)
    header = "## SYSTEM-ENFORCED DATASET CONSTRAINTS"
    assert header in a and header in b, (
        "both renders are TIDMAD-profile runs, so BOTH must carry the dataset "
        "constraint block; proposal_blocks governs prose, not dataset science"
    )


# ==========================================================================
# 2. NON-VACUITY  (must pass today AND after the fix)
# ==========================================================================


def test_marker_matcher_actually_sees_contamination_in_the_tidmad_baseline() -> None:
    """The matcher is live: it finds the markers where they legitimately are.

    DEFECT THIS TEST ALONE CATCHES
        A vacuous contamination test. If a marker literal were misspelled, or
        the baseline pointed at the wrong stage, or the capture wrote an empty
        file, test 1 would pass for the wrong reason -- green because it can
        see nothing, not because nothing is there. This test asserts the SAME
        matcher over the SAME stage of the OTHER regime and requires a
        non-trivial hit, so a blind matcher cannot stay green here.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        If a future change strips these constraints from TIDMAD's own prompt
        too, this goes red -- which is the correct alarm, because the operator
        ruling forbids deleting useful guidance from genuine TIDMAD runs.
    """
    text = _baseline(capture.REGIME_TIDMAD, _PROPOSING_SYSTEM).read_text(encoding="utf-8")
    found = _markers_present(text)
    assert set(found) == set(TIDMAD_ONLY_MARKERS), (
        "The TIDMAD baseline should contain every TIDMAD-only marker; missing "
        f"{sorted(set(TIDMAD_ONLY_MARKERS) - set(found))}. Either the matcher is "
        "blind (making the contamination test vacuous) or TIDMAD lost guidance "
        "it is entitled to keep."
    )


def test_planted_contamination_is_detected() -> None:
    """A plant proves detection end-to-end, independent of any captured file.

    DEFECT THIS TEST ALONE CATCHES
        A matcher that is correct only against the current fixtures. This
        builds a clean synthetic foreign prompt, asserts it is clean, splices
        the real contaminating block in, and requires the matcher to flag it.
        It fails if ``_markers_present`` is ever weakened -- e.g. to a
        case-sensitive whole-line match, or to a check on one marker only.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        The post-plant assertion goes empty and names the plant that was not
        seen.
    """
    clean = (
        "You are an ML architect.\n\n## SYSTEM-ENFORCED DATASET CONSTRAINTS\n"
        # deliberately the HEADER only, with a foreign task's real rule under
        # it -- so the plant tests the RULE text, not merely the heading.
    ).replace("## SYSTEM-ENFORCED DATASET CONSTRAINTS\n", "")
    assert _markers_present(clean) == [], "the synthetic clean prompt is not clean"

    planted = clean + (
        "## SYSTEM-ENFORCED DATASET CONSTRAINTS\n\n"
        "  segmentation_size — must EXACTLY divide psd_segment_length (10,000,000).\n"
        "                      Powers of 2 such as 16384, 8192, 4096 are INVALID\n"
        "                      (16000 is the nearest valid neighbor of 16384).\n"
    )
    found = _markers_present(planted)
    for expected in (
        "SYSTEM-ENFORCED DATASET CONSTRAINTS",
        "psd_segment_length",
        "10,000,000",
        "16384",
        "16000 is the nearest valid neighbor",
    ):
        assert expected in found, f"planted marker {expected!r} was not detected"


# ==========================================================================
# 3. REGIME-A BYTE PARITY  (must pass today AND after the fix)
# ==========================================================================


@pytest.mark.parametrize(
    "stem",
    [
        "01_proposer_comparison__system",
        "01_proposer_comparison__user",
        "02_proposer_causal_reasoning__system",
        "02_proposer_causal_reasoning__user",
        "03_proposer_proposing__system",
        "03_proposer_proposing__user",
    ],
)
def test_tidmad_regime_a_prompt_is_byte_identical_to_baseline(stem: str) -> None:
    """Re-rendering TIDMAD's prompts today reproduces the captured bytes exactly.

    DEFECT THIS TEST ALONE CATCHES
        A fix for the foreign regime that silently moves TIDMAD's own prompt
        bytes. The operator ruling makes Regime-A byte-equivalence a hard
        constraint, and "the contamination test went green" is not evidence of
        it -- a fix that removed the block for BOTH regimes would satisfy test
        1 and be wrong. This is the only assertion that would fail in that
        case.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        Byte comparison against the committed baseline; the message names the
        stage and the first differing offset.

    NOTE ON COST: this re-runs the production prompt assembly (no LLM, no
    network, no GPU) once per parametrisation. It is the only way to assert
    that TODAY's code still produces the captured bytes; comparing the file to
    itself would assert nothing.
    """
    # No skip: `_offline_client_credential` guarantees a client-construction
    # credential in every environment. This case must NEVER be conditionally
    # absent — see that fixture's docstring for why a skip here was the
    # vacuity hazard rather than a courtesy.
    captures = capture.capture_prompts(capture.tidmad_regime_a_blocks())
    rendered: dict[str, str] = {}
    for index, (label, system_prompt, user_prompt) in enumerate(captures, start=1):
        safe = "".join(c if c.isalnum() else "_" for c in label) or "unlabelled"
        rendered[f"{index:02d}_{safe}__system"] = system_prompt
        rendered[f"{index:02d}_{safe}__user"] = user_prompt

    assert stem in rendered, (
        f"the production path no longer produces stage {stem!r}; it produced "
        f"{sorted(rendered)}. A changed stage set is itself a Regime-A change."
    )

    expected = _baseline(capture.REGIME_TIDMAD, stem).read_text(encoding="utf-8")
    actual = rendered[stem]
    if actual != expected:
        offset = next(
            (i for i, (a, b) in enumerate(zip(actual, expected, strict=False)) if a != b),
            min(len(actual), len(expected)),
        )
        raise AssertionError(
            f"Regime-A prompt {stem!r} moved. First difference at offset {offset}.\n"
            f"  baseline: {expected[offset : offset + 120]!r}\n"
            f"  rendered: {actual[offset : offset + 120]!r}"
        )
