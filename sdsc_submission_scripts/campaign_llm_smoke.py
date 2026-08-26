#!/usr/bin/env python
"""LLM reachability + concurrency smoke for the campaign preflight.

Eight co-resident band chains (two fleets of four) hit the provider
concurrently at launch. This smoke fires a BOUNDED burst of N (default 8)
parallel trivial completions through the repository's own config loading
(``workflows.llm_config.WorkflowLLMConfig``) and bridge
(``agent.llm_bridge.LLMBridge``) against the TUNER PLANNER slot — the
campaign's highest-rate consumer — and reports the success count and p95
latency.

WHAT THIS IS NOT: a quota guarantee. Real rate/quota limits are enforced
provider-side over the whole campaign's sustained call pattern; a green
burst proves the key, endpoint, model id and N-way concurrency are LIVE
right now, nothing more. Cost is trivial by construction: each call asks
for one word.

Exit 0 iff every call in the burst succeeded; 1 otherwise (per-call
errors printed); 2 for a config that cannot be loaded.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SYSTEM_PROMPT = "You are a reachability probe. Follow the instruction exactly."
USER_PROMPT = "Reply with the single word OK."


def _one_call(provider: str, model_id: str, timeout_s: float, results: list, idx: int) -> None:
    from agent.llm_bridge import LLMBridge

    t0 = time.time()
    try:
        bridge = LLMBridge(
            provider=provider,
            model_id=model_id,
            max_retries=2,  # bounded: a smoke must not inherit the infinite quota retry
            request_timeout=timeout_s,
        )
        text = bridge.generate_text(
            SYSTEM_PROMPT,
            USER_PROMPT,
            label="campaign_preflight_llm_smoke",
        )
        results[idx] = {"ok": True, "latency_s": round(time.time() - t0, 3), "reply": text[:40]}
    except Exception as exc:  # a smoke reports every failure shape, it never raises
        results[idx] = {
            "ok": False,
            "latency_s": round(time.time() - t0, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--llm-config",
        default=str(REPO_ROOT / "llm_configs" / "openai_tiered_pro.json"),
        help="WorkflowLLMConfig JSON (default: the campaign-standard openai_tiered_pro.json)",
    )
    parser.add_argument("--n", type=int, default=8, help="burst size (default 8 = 2 fleets x 4)")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--out", default=None, help="optional JSON report path")
    args = parser.parse_args()

    from workflows.llm_config import WorkflowLLMConfig

    try:
        config = WorkflowLLMConfig.from_json(args.llm_config)
        tuner_kwargs = config.get("tune")
    except Exception as exc:
        print(f"[llm-smoke] cannot load {args.llm_config!r}: {exc}", file=sys.stderr)
        return 2
    provider = tuner_kwargs.get("provider", "gemini")
    model_id = tuner_kwargs.get("model_id")
    print(f"[llm-smoke] provider={provider} model_id={model_id} burst_n={args.n}")

    results: list = [None] * args.n
    threads = [
        threading.Thread(
            target=_one_call,
            args=(provider, model_id, args.timeout_seconds, results, i),
            daemon=True,
        )
        for i in range(args.n)
    ]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=args.timeout_seconds * 3)
    burst_wall = round(time.time() - t0, 3)

    rows = [
        r if r is not None else {"ok": False, "error": "thread did not finish"} for r in results
    ]
    successes = [r for r in rows if r.get("ok")]
    latencies = sorted(r["latency_s"] for r in rows if "latency_s" in r)
    p95 = latencies[max(0, math.ceil(0.95 * len(latencies)) - 1)] if latencies else None

    report = {
        "llm_config": args.llm_config,
        "provider": provider,
        "model_id": model_id,
        "burst_n": args.n,
        "success_count": len(successes),
        "p95_latency_s": p95,
        "burst_wall_s": burst_wall,
        "calls": rows,
        "caveat": (
            "reachability/concurrency smoke only — provider-side quota over the "
            "campaign's sustained pattern is NOT guaranteed by a green burst"
        ),
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")

    print(f"[llm-smoke] success {len(successes)}/{args.n}  p95={p95}s  burst_wall={burst_wall}s")
    for i, r in enumerate(rows):
        if not r.get("ok"):
            print(f"[llm-smoke]   call {i}: FAILED — {r.get('error')}", file=sys.stderr)
    return 0 if len(successes) == args.n else 1


if __name__ == "__main__":
    sys.exit(main())
