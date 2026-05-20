"""Unit tests for ``agent/utils/architectural_pattern_tagger.py``.

Covers:

* the three v1 tags against the actually-observed failure configs from
  ``explore_novel_v3_0420`` (iter 2 scan, iter 3 GRU, iter 4 TCN-success);
* the attention windowing negative case;
* unknown / empty inputs → ``[]``;
* determinism (sorted, unique tags);
* the completeness invariant: every tag emitted by ``tag_architecture``
  has an entry in ``ARCHITECTURAL_PATTERNS``.

See ``docs/reliable_resource_proposer.md`` §9 Commit 2 checklist.
"""

from __future__ import annotations

import pytest

from agent.utils.architectural_pattern_tagger import (
    ARCHITECTURAL_PATTERNS,
    TIME_FACTOR_THRESHOLD,
    VRAM_FACTOR_THRESHOLD,
    tag_architecture,
)

# ── the three v1 tags against the observed failure configs ──────────────────


def test_iter2_selective_scan_gets_scan_over_T():
    """iter 2's ``selective_bidirectional_scan_conv`` was 18,772× over
    budget — the tagger must flag it as ``scan_over_T``."""
    model_config = {
        "segmentation_size": 40000,
        "num_blocks": 12,
        "state_dim": 16,
        "ssm_dt_rank": 8,
        "hidden_channels": 128,
    }
    assert tag_architecture("selective_bidirectional_scan_conv", model_config) == ["scan_over_T"]


def test_iter3_gru_stack_gets_recurrent_over_T():
    """iter 3's ``dual_path_gated_gru_stack`` was 28× over budget — the
    tagger must flag it as ``recurrent_over_T``."""
    model_config = {
        "segmentation_size": 40000,
        "num_blocks": 6,
        "gru_hidden_size": 128,
        "hidden_channels": 128,
    }
    assert tag_architecture("dual_path_gated_gru_stack", model_config) == ["recurrent_over_T"]


def test_iter4_fourier_tcn_gets_no_tags():
    """iter 4's ``gated_fourier_tcn`` was the first architecturally-feasible
    proposal at seg_size=40000. The tagger MUST NOT flag it, or the next
    proposer would incorrectly ban a working class."""
    model_config = {
        "segmentation_size": 40000,
        "num_blocks": 6,
        "kernel_size": 3,
        "dilation_base": 2,
        "hidden_channels": 128,
        "fft_bins": 512,
    }
    assert tag_architecture("gated_fourier_tcn", model_config) == []


# ── attention + windowing split ─────────────────────────────────────────────


def test_transformer_without_window_gets_dense_attention_over_T():
    model_config = {
        "segmentation_size": 40000,
        "num_heads": 8,
        "hidden_channels": 128,
    }
    assert tag_architecture("transformer_base", model_config) == ["dense_attention_over_T"]


def test_transformer_with_window_is_not_flagged():
    """Windowed attention is feasible — the tagger must recognise
    ``window_size`` as a mitigation and NOT emit the tag."""
    model_config = {
        "segmentation_size": 40000,
        "num_heads": 8,
        "hidden_channels": 128,
        "window_size": 128,
    }
    assert tag_architecture("transformer_base", model_config) == []


@pytest.mark.parametrize(
    "window_key",
    ["window_size", "chunk_size", "attention_window", "local_window"],
)
def test_all_four_windowing_keys_suppress_dense_attention_tag(window_key):
    """All four recognised windowing keys must equally suppress the tag."""
    model_config = {window_key: 128}
    assert tag_architecture("attention_stack", model_config) == []


# ── unknown / empty inputs ──────────────────────────────────────────────────


def test_unknown_model_type_with_no_matching_keys_returns_empty():
    assert tag_architecture("some_novel_fft_variant", {"hidden_channels": 64}) == []


def test_empty_model_type_returns_empty():
    assert tag_architecture("", {}) == []


def test_none_model_type_is_handled_gracefully():
    """The tagger must not crash on ``None`` — the tuner may call it with
    edge-case data. Defensive against upstream bugs."""
    assert tag_architecture(None, {}) == []  # type: ignore[arg-type]


def test_none_model_config_is_handled_gracefully():
    assert tag_architecture("some_model", None) == []  # type: ignore[arg-type]


# ── config-key triggers independent of model_type name ──────────────────────


def test_recurrent_config_key_alone_triggers_tag_even_if_name_hides_it():
    """If the model_type name hides the recurrence (e.g., a custom
    wrapper), a ``*_hidden_size`` key in the config still catches it."""
    assert tag_architecture("custom_block_stack", {"lstm_hidden_size": 64}) == ["recurrent_over_T"]


def test_state_dim_plus_ssm_key_triggers_scan_tag():
    """Conjunctive trigger: both ``state_dim`` AND any ``ssm_*`` key must
    be present. Either alone should not fire."""
    assert tag_architecture("custom_block_stack", {"state_dim": 16, "ssm_dt_rank": 8}) == [
        "scan_over_T"
    ]


def test_state_dim_alone_does_not_trigger_scan_tag():
    """state_dim without any ssm_* key is ambiguous — could be a plain
    hidden-state buffer. Don't false-positive."""
    assert tag_architecture("custom_block_stack", {"state_dim": 16}) == []


def test_ssm_key_alone_does_not_trigger_scan_tag():
    """Similarly ``ssm_dt_rank`` alone (no state_dim) doesn't fire via
    the conjunctive path. It would fire only if the name had an SSM hint."""
    assert tag_architecture("custom_block_stack", {"ssm_dt_rank": 8}) == []


# ── multi-tag + determinism ─────────────────────────────────────────────────


def test_model_matching_multiple_patterns_gets_all_tags_sorted():
    """An ``attention_gru_hybrid`` with no windowing should fire BOTH
    ``recurrent_over_T`` (via ``gru``) AND ``dense_attention_over_T``
    (via ``attention`` without a window key). Tags must be sorted."""
    tags = tag_architecture("attention_gru_hybrid", {"gru_hidden_size": 64})
    assert tags == ["dense_attention_over_T", "recurrent_over_T"]


def test_output_is_deterministic_across_calls():
    """Same inputs → same output, same order. The downstream renderer
    relies on this for stable prompt text."""
    cfg = {"gru_hidden_size": 64}
    out1 = tag_architecture("attention_gru_hybrid", cfg)
    out2 = tag_architecture("attention_gru_hybrid", cfg)
    out3 = tag_architecture("attention_gru_hybrid", cfg)
    assert out1 == out2 == out3


# ── completeness invariant ──────────────────────────────────────────────────


def test_every_emitted_tag_has_an_english_description():
    """Completeness invariant: every tag any matcher can return must
    have a description in ``ARCHITECTURAL_PATTERNS`` so the proposer
    renderer can never emit an un-described tag."""
    # Trigger each pattern at least once through the public API.
    emitted: set[str] = set()
    emitted.update(tag_architecture("gru_stack", {}))
    emitted.update(tag_architecture("scan_net", {}))
    emitted.update(tag_architecture("transformer", {}))

    assert emitted == {
        "recurrent_over_T",
        "scan_over_T",
        "dense_attention_over_T",
    }, "test setup didn't cover all three v1 tags — update it if vocab grew"

    missing = emitted - ARCHITECTURAL_PATTERNS.keys()
    assert not missing, (
        f"tagger emits tags with no English description: {sorted(missing)}. "
        f"Add them to ARCHITECTURAL_PATTERNS so the proposer renderer "
        f"cannot silently drop them."
    )


def test_architectural_patterns_has_no_orphan_descriptions():
    """Reverse invariant: every description in ARCHITECTURAL_PATTERNS
    should be reachable from some input. Orphan entries are dead docs
    and should be cleaned up when a tag is retired."""
    reachable: set[str] = set()
    reachable.update(tag_architecture("gru_stack", {}))
    reachable.update(tag_architecture("scan_net", {}))
    reachable.update(tag_architecture("transformer", {}))

    orphans = ARCHITECTURAL_PATTERNS.keys() - reachable
    assert not orphans, (
        f"ARCHITECTURAL_PATTERNS has descriptions for tags the tagger "
        f"can no longer emit: {sorted(orphans)}. Retire the descriptions "
        f"or restore the matching heuristic."
    )


# ── thresholds are exported at module level ─────────────────────────────────


def test_thresholds_are_the_documented_v1_values():
    """The v1 thresholds from §7 Decision 2. If these change, the doc
    must change with them."""
    assert TIME_FACTOR_THRESHOLD == 5.0
    assert VRAM_FACTOR_THRESHOLD == 2.0
