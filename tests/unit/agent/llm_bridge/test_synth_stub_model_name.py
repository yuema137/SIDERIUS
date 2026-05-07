"""Determinism + format tests for ``_synth_stub_model_name``.

The slug returned by ``_synth_stub_model_name(iter_idx, slot)`` is the
single source of truth for cross-stub model naming in StubLLMBridge:
proposer.proposing / implementor.code / tuner.planner all derive their
``model_name`` from it. If any of those labels disagrees on the slug,
training crashes on ``ImportError`` mid-chain.

We pin:
  - exact format string (``stub_arch_{iter:03d}_{slot}``)
  - zero-padded iter (so iter 7 sorts next to iter 70 lexically)
  - determinism across calls
  - identifier-safe output (so ``importlib`` accepts it)
"""
from __future__ import annotations

import re

from agent.llm_bridge import _synth_stub_model_name


_SLUG_PATTERN = re.compile(r"^stub_arch_\d{3}_[a-zA-Z0-9_]+$")


def test_basic_format():
    assert _synth_stub_model_name(1, "a") == "stub_arch_001_a"


def test_iter_zero_pads_to_three_digits():
    """iter 7 and iter 70 must sort lexically by iter — pads to 3 digits."""
    assert _synth_stub_model_name(7, "a")  == "stub_arch_007_a"
    assert _synth_stub_model_name(70, "a") == "stub_arch_070_a"
    assert _synth_stub_model_name(0, "a")  == "stub_arch_000_a"


def test_high_iter_does_not_truncate():
    """≥1000 iters: padding is a floor, not a cap."""
    assert _synth_stub_model_name(1234, "x") == "stub_arch_1234_x"


def test_determinism_across_calls():
    a = _synth_stub_model_name(5, "b")
    b = _synth_stub_model_name(5, "b")
    assert a == b


def test_distinct_slot_yields_distinct_slug():
    assert _synth_stub_model_name(3, "a") != _synth_stub_model_name(3, "b")


def test_slug_is_python_identifier_safe():
    """The slug becomes a plugin filename + module name. Must match
    ``[A-Za-z_][A-Za-z0-9_]*`` so importlib can load it."""
    slug = _synth_stub_model_name(42, "trial_a")
    assert _SLUG_PATTERN.match(slug), f"unsafe slug: {slug!r}"
