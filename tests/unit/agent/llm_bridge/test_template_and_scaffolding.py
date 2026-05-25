"""Unit tests for the Commit 4.2 ``template_and_scaffolding`` catch-all.

Closes the T1.2 audit gap measured on 2026-05-04 (Gate T1 RED): the
proposer's ``_audit_proposer_components`` hook reports the 9 named
content payloads injected into the user prompt, but not the template
wrapper text (section headers, key-value preludes, stage instructions)
that ``_build_*_prompt`` adds around them. ~22% of each user prompt was
unaccounted for, breaking the row-level invariant
``sum(components) == chars.total``.

The fix lives in ``LLMBridge._record_usage`` (not the audit hook): the
bridge has both the rendered prompt total and the components dict at
write time, so it injects a 10th key
``template_and_scaffolding = max(0, chars.total - sum(other 9))``
when components is non-empty. Non-proposer rows (empty components) are
untouched.

These tests pin the contract:
  - non-empty components → 10th key added; sum(all 10) == chars.total
  - empty components → row written with empty components, no 10th key
  - over-counting components → 10th key clamped to 0 (never negative)
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.llm_bridge import LLMBridge

# ---------------------------------------------------------------------------
# Helpers (mirror tests/unit/agent/llm_bridge/test_record_usage.py)
# ---------------------------------------------------------------------------


def _usage(prompt: int, completion: int, total: int) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


def _chat_response(content: str, usage=None) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _make_bridge(tmp_path: Path) -> LLMBridge:
    with patch("agent.llm_bridge.OpenAI"):
        bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini")
    bridge._token_usage_path = tmp_path / "token_usage.jsonl"
    bridge._run_id = "test-run-id"
    bridge._run_name = "test_run"
    bridge._iter = 1
    return bridge


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _record(
    bridge: LLMBridge,
    system: str,
    user: str,
    components: dict | None,
    label: str = "proposer.proposing",
) -> dict:
    """Drive the bridge through one generate() call and return the row."""
    bridge.client.chat.completions.create.return_value = _chat_response(
        '{"ok": 1}',
        usage=_usage(prompt=1, completion=1, total=2),
    )
    bridge.generate(system, user, label=label, components=components)
    rows = _read_rows(bridge._token_usage_path)
    assert len(rows) == 1
    return rows[0]


# ---------------------------------------------------------------------------
# (1) Non-empty components → 10th key added; sum(all 10) == chars.total
# ---------------------------------------------------------------------------


def test_non_empty_components_get_template_scaffolding_key(tmp_path):
    """The 9-key components dict is augmented with a 10th catch-all so
    the lossless invariant ``sum(components) == chars.total`` holds."""
    bridge = _make_bridge(tmp_path)
    system = "S" * 100
    user = "U" * 1000
    # 9 keys summing to 800 — leaves a 300-char gap (chars.total = 1100).
    components = {
        "system_prompt": 100,
        "candidates_markdown": 200,
        "interpretation_json": 100,
        "previous_failures": 0,
        "vocab_block": 50,
        "expert_context_block": 50,
        "agent_cards_block": 0,
        "prior_stage_outputs": 300,
        "recent_gate_block": 0,
    }

    row = _record(bridge, system, user, components)

    expected_total = len(system) + len(user)
    assert row["chars"]["total"] == expected_total

    out = row["components"]
    assert "template_and_scaffolding" in out
    assert len(out) == 10
    # The 9 original keys are preserved exactly.
    for k, v in components.items():
        assert out[k] == v
    # Catch-all = chars.total - sum(other 9).
    content_sum = sum(components.values())
    assert out["template_and_scaffolding"] == expected_total - content_sum
    # Lossless: sum of all 10 keys == chars.total.
    assert sum(out.values()) == expected_total


# ---------------------------------------------------------------------------
# (2) Empty components → no 10th key (non-proposer rows untouched)
# ---------------------------------------------------------------------------


def test_empty_components_stay_empty(tmp_path):
    """Non-proposer call sites pass no components; the row's components
    dict must remain empty — we do not invent a single-key dict."""
    bridge = _make_bridge(tmp_path)

    row = _record(bridge, "sys", "user", components=None, label="tuner.planner")

    assert row["components"] == {}
    assert "template_and_scaffolding" not in row["components"]


def test_explicit_empty_components_stay_empty(tmp_path):
    """Same contract when the caller passes ``components={}`` explicitly."""
    bridge = _make_bridge(tmp_path)

    row = _record(bridge, "sys", "user", components={}, label="implementor.code")

    assert row["components"] == {}


# ---------------------------------------------------------------------------
# (3) Over-counting components → 10th key clamped to 0 (defensive)
# ---------------------------------------------------------------------------


def test_overcount_clamps_to_zero(tmp_path):
    """If a future audit-hook bug double-counts a payload so that
    sum(components) > chars.total, the catch-all must clamp to 0
    rather than emit a negative — better to log under than lie."""
    bridge = _make_bridge(tmp_path)
    system = "S" * 10
    user = "U" * 10  # chars.total = 20
    # Deliberately over-large 9-key sum (1000 > 20).
    components = {
        "system_prompt": 1000,
        "candidates_markdown": 0,
        "interpretation_json": 0,
        "previous_failures": 0,
        "vocab_block": 0,
        "expert_context_block": 0,
        "agent_cards_block": 0,
        "prior_stage_outputs": 0,
        "recent_gate_block": 0,
    }

    row = _record(bridge, system, user, components)

    assert row["components"]["template_and_scaffolding"] == 0
    # The 9 keys are still preserved as reported (we don't rewrite them).
    assert row["components"]["system_prompt"] == 1000


# ---------------------------------------------------------------------------
# (4) Exact-match case → 10th key is 0, key still present (lossless invariant)
# ---------------------------------------------------------------------------


def test_exact_match_yields_zero_value(tmp_path):
    """When the 9 keys exactly cover chars.total (no template wrapper),
    the 10th key is 0 — present so downstream tooling can always rely on
    the key existing on proposer rows."""
    bridge = _make_bridge(tmp_path)
    system = "S" * 50
    user = "U" * 50  # chars.total = 100
    components = {
        "system_prompt": 50,
        "candidates_markdown": 50,
        "interpretation_json": 0,
        "previous_failures": 0,
        "vocab_block": 0,
        "expert_context_block": 0,
        "agent_cards_block": 0,
        "prior_stage_outputs": 0,
        "recent_gate_block": 0,
    }

    row = _record(bridge, system, user, components)

    assert row["components"]["template_and_scaffolding"] == 0
    assert sum(row["components"].values()) == 100
