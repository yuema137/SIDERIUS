"""Subprocess harness — exercises §1.4.2 fail-fast contract end-to-end.

Used by ``test_runner_aborts_on_runid_mismatch`` (Q4 confirmed: real
subprocess, no monkey-patching). Mirrors the chain runner's top-level
handler: build a real ``LLMBridge``, bind a deliberately-fresh
``run_id`` against a workspace
whose ``token_usage.jsonl`` is already owned by a *different* run_id,
then call ``_record_usage``. The bridge's first-row check (§1.4.1)
should raise :class:`LLMBridgeContextError`; the handler below
translates that into ``[FATAL]`` on stderr + ``sys.exit(2)`` — exactly
what production must do.

Argv:
    1. ``workspace`` — directory containing the pre-seeded
       ``token_usage.jsonl`` whose first row carries the *prior*
       run_id.
    2. ``run_id`` — the *new* run_id this harness will bind. Must
       differ from the workspace's first-row ``run_id`` or the test
       collapses into a no-op success.

Exit codes:
    ``2`` — :class:`LLMBridgeContextError` propagated to the handler
            (the documented success path).
    ``0`` — bridge silently wrote a row (test failure: the check
            didn't fire).
    Any other — unexpected exception (bug; surfaced in test stderr).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

# Repo root must be on sys.path before importing agent.* so this harness
# is runnable as a bare ``python harness.py`` subprocess (no PYTHONPATH
# inheritance assumed). parents[3] = tests/integration/runner → tests →
# repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.llm_bridge import LLMBridge
from agent.schemas.telemetry import LLMBridgeContextError


def main() -> None:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <workspace> <run_id>", file=sys.stderr)
        sys.exit(255)

    workspace = Path(sys.argv[1])
    run_id = sys.argv[2]

    # OPENAI_API_KEY may not be set in CI — feed a placeholder so the
    # SDK constructor doesn't complain. No real API call happens here.
    os.environ.setdefault("OPENAI_API_KEY", "harness-placeholder")

    try:
        bridge = LLMBridge(provider="openai")
        bridge.set_run_context(
            workspace=workspace,
            iter=1,
            run_name="runid_mismatch_harness",
            run_id=run_id,
        )
        # Construct a minimal SDK-shape response so ``response.usage``
        # parses (we only need to reach the pre-write validation step).
        fake_usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15,
        )
        fake_response = SimpleNamespace(usage=fake_usage)
        bridge._record_usage(
            response=fake_response,
            label="harness.canary",
            system_prompt="sys",
            user_prompt="usr",
            model_name="gpt-test",
            provider="openai",
        )
        # If we reach this line, the first-row check failed silently.
        print("HARNESS: bridge wrote without raising — test should fail.",
              file=sys.stderr)
        sys.exit(0)
    except LLMBridgeContextError as e:
        # The exact wording mirrors the chain runner's top-level handler
        # in sdsc_submission_scripts/run_one_iteration.py so a single
        # grep catches drift.
        print(
            f"[FATAL] LLMBridgeContextError: {e} — aborting run to "
            f"prevent telemetry corruption.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
