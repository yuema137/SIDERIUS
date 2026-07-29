# scripts/pr3_l2_calibration/runner.py
"""P3-L2p sample executor (protocol §4). REAL LLM CALLS — operator-gated.

Invocation (only after the operator's explicit launch decision):

    .venv/bin/python -m scripts.pr3_l2_calibration.runner \
        --run_id <id> --max_calls 60 --dollar_cap 80.0

Design:

* Every LLM attempt goes through a recording tee wrapped around the
  bridge client's ``chat.completions.create`` — it persists the request
  messages, the response-reported model/version, per-attempt usage
  (incl. cached tokens where reported), latency, and finish reason,
  and enforces the call + dollar hard caps BEFORE each attempt.
* The proposer runs the PRODUCTION pipeline (protocol invariant); the
  runner verifies per sample that the captured proposing-stage prompt
  exists and that pipeline mode was selected — otherwise the sample is
  recorded INVALID (its calls still count) and the run stops.
* First-response continuation gate per protocol §4.1; version drift is
  a hard stop.
* Retries: the bridge's own envelope handles the pre-registered
  technical conditions (transport/timeout via _call_with_retry;
  schema/content via its content-retry budget and the proposer's
  structural retries). Every attempt is recorded and counted. The
  first schema-valid response is the sample output — the runner never
  re-invokes a node because an output is unfavorable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

PRICE_INPUT_PER_M = 5.00  # USD, gpt-5.5, frozen 2026-07-29
PRICE_CACHED_PER_M = 0.50
PRICE_OUTPUT_PER_M = 30.00

PROVIDER = "openai"
MODEL_ID = "gpt-5.5"


class BudgetExceeded(RuntimeError):
    pass


class VersionDrift(RuntimeError):
    pass


class Ledger:
    """Attempt-level call + cost ledger with hard-cap enforcement."""

    def __init__(self, max_calls: int, dollar_cap: float, path: Path):
        self.max_calls = max_calls
        self.dollar_cap = dollar_cap
        self.path = path
        self.calls = 0
        self.input_tokens = 0
        self.cached_tokens = 0
        self.output_tokens = 0
        self.pinned_version: str | None = None

    @property
    def cost(self) -> float:
        uncached = self.input_tokens - self.cached_tokens
        return (
            uncached * PRICE_INPUT_PER_M
            + self.cached_tokens * PRICE_CACHED_PER_M
            + self.output_tokens * PRICE_OUTPUT_PER_M
        ) / 1_000_000

    def precheck(self):
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"call cap reached: {self.calls}/{self.max_calls}")
        if self.cost >= self.dollar_cap:
            raise BudgetExceeded(f"dollar cap reached: ${self.cost:.2f}/${self.dollar_cap:.2f}")

    def record(self, row: dict):
        self.calls += 1
        self.input_tokens += row.get("prompt_tokens") or 0
        self.cached_tokens += row.get("cached_tokens") or 0
        self.output_tokens += row.get("completion_tokens") or 0
        version = row.get("model")
        if version:
            if self.pinned_version is None:
                self.pinned_version = version
            elif version != self.pinned_version:
                raise VersionDrift(
                    f"model version drift: pinned={self.pinned_version!r} "
                    f"got={version!r} — stop before pooling (protocol §5)"
                )
        with open(self.path, "a") as f:
            f.write(json.dumps(row) + "\n")


def _wrap_client(bridge, ledger: Ledger, sample_dir: Path, node: str):
    """Tee around chat.completions.create — record + enforce caps."""
    real_create = bridge.client.chat.completions.create
    calls_path = sample_dir / "calls.jsonl"

    def create(*args, **kwargs):
        ledger.precheck()
        t0 = time.time()
        error = None
        response = None
        try:
            response = real_create(*args, **kwargs)
            return response
        except Exception as e:  # recorded, then re-raised for bridge retry
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            latency = round(time.time() - t0, 3)
            usage = getattr(response, "usage", None)
            details = getattr(usage, "prompt_tokens_details", None)
            row = {
                "node": node,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "latency_s": latency,
                "model": getattr(response, "model", None),
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "cached_tokens": getattr(details, "cached_tokens", None) if details else None,
                "finish_reason": (
                    response.choices[0].finish_reason
                    if response is not None and getattr(response, "choices", None)
                    else None
                ),
                "error": error,
                # rev 3 (§4.3 fix): EVERY attempt's raw response body is
                # persisted — including responses that later fail JSON
                # parsing or Pydantic validation downstream.
                "response_content": (
                    response.choices[0].message.content
                    if response is not None and getattr(response, "choices", None)
                    else None
                ),
                "request_messages": kwargs.get("messages"),
            }
            with open(calls_path, "a") as f:
                f.write(json.dumps(row) + "\n")
            if error is None:
                ledger.record(
                    {
                        k: v
                        for k, v in row.items()
                        if k not in ("request_messages", "response_content")
                    }
                )

    bridge.client.chat.completions.create = create


def _first_response_gate(ledger: Ledger, run_dir: Path):
    rows = [json.loads(line) for line in (ledger.path).read_text().splitlines() if line.strip()]
    assert rows, "no ledger rows after first call"
    first = rows[0]
    assert first["model"] and first["model"].startswith(MODEL_ID.split("-")[0]), first["model"]
    assert first["prompt_tokens"], "usage missing on first response"
    projected = ledger.cost / max(ledger.calls, 1) * ledger.max_calls
    gate = {
        "first_model": first["model"],
        "first_prompt_tokens": first["prompt_tokens"],
        "first_completion_tokens": first["completion_tokens"],
        "first_cached_tokens": first["cached_tokens"],
        "first_latency_s": first["latency_s"],
        "projected_worst_case_usd": round(projected, 2),
        "dollar_cap": ledger.dollar_cap,
        "continue": projected < ledger.dollar_cap,
    }
    (run_dir / "first_response_gate.json").write_text(json.dumps(gate, indent=2))
    if not gate["continue"]:
        raise BudgetExceeded(f"projected worst case ${projected:.2f} >= cap")
    return gate


def run_sample(entry: dict, run_dir: Path, ledger: Ledger, first_gate_done: list) -> dict:
    from agent.schemas.interpretation import InterpretationInput
    from agent.schemas.proposal import ReasoningPipelineConfig, ReasoningStage
    from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
        local_full_context,
    )
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from nodes.ml_model_proposal_agent import MLModelProposalAgent
    from nodes.result_interpretation_agent import (
        ResultInterpretationAgent,
        tuning_output_to_model_run_summary,
    )
    from scripts.pr3_l2_calibration.fixtures import (
        MODEL_DESCRIPTIONS,
        SCENARIOS,
        fixture_hash,
    )
    from scripts.pr3_l2_calibration.scorer import score_sample
    from workflows.task_config import get_task_description, load_task_config

    scenario, arm, rep = entry["scenario"], entry["arm"], entry["rep"]
    sid = f"{scenario}_{arm}_{rep}"
    sample_dir = run_dir / sid
    sample_dir.mkdir(parents=True, exist_ok=True)
    spec = SCENARIOS[scenario]
    interp_on = arm in ("T", "D")
    proposer_on = arm == "T"

    summaries = []
    for out in spec["tune_outputs"]():
        s = tuning_output_to_model_run_summary(out)
        s.model_description = MODEL_DESCRIPTIONS.get(s.model_type)
        summaries.append(s)

    from scripts.pr3_l2_calibration.fixtures import production_vocab_seed

    vocab_seed = production_vocab_seed()
    interp_input = InterpretationInput(
        summaries=summaries,
        storage={
            "backend": "local",
            "local": {"workspace": str(sample_dir / "interp_ws"), "run_name": sid},
        },
        iteration=spec["iteration"],
        enable_structured_health_feedback=interp_on,
        collapse_fingerprint_history=spec["carried_history"](),
        task_description=get_task_description(load_task_config()),
        # rev 3: production first-iteration vocabulary condition — the
        # workflow seeds runtime_vocab from the static seed on iter 1.
        runtime_vocab=vocab_seed,
    )
    os.makedirs(sample_dir / "interp_ws", exist_ok=True)
    (sample_dir / "interp_input.json").write_text(interp_input.model_dump_json(indent=2))

    meta = {
        "sample_id": sid,
        "execution_order_index": entry["idx"],
        "scenario": scenario,
        "arm": arm,
        "rep": rep,
        "fixture_hash": fixture_hash(scenario),
        "interp_flag": interp_on,
        "proposer_flag": proposer_on,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    interp_agent = ResultInterpretationAgent(provider=PROVIDER, model_id=MODEL_ID, max_retries=3)
    _wrap_client(interp_agent.bridge, ledger, sample_dir, node="interpreter")
    interp_out = interp_agent.run(interp_input)
    (sample_dir / "interp_output.json").write_text(interp_out.model_dump_json(indent=2))

    if not first_gate_done:
        _first_response_gate(ledger, run_dir)
        first_gate_done.append(True)

    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(sample_dir / "propose_ws"), run_name=sid),
    )
    os.makedirs(sample_dir / "propose_ws", exist_ok=True)
    propose_input = local_full_context(
        interp_out,
        storage,
        enable_structured_health_feedback=proposer_on,
        vocab_seed=vocab_seed,  # rev 3: production vocabulary for citations
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode="exploit",
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
        ),
    )
    _task_cfg = load_task_config()
    propose_input.task_description = get_task_description(_task_cfg)
    from agent.schemas.proposal import ForwardContract

    propose_input.forward_contract = ForwardContract(**_task_cfg["forward_contract"])
    (sample_dir / "propose_input_meta.json").write_text(
        json.dumps({"enable_structured_health_feedback": proposer_on}, indent=2)
    )

    proposer = MLModelProposalAgent(provider=PROVIDER, model_id=MODEL_ID, max_retries=3)
    _wrap_client(proposer.bridge, ledger, sample_dir, node="proposer")
    proposal = None
    terminal_error = None
    try:
        output = proposer.run(propose_input)
        proposal = output.model_dump(mode="json")
        (sample_dir / "proposal_output.json").write_text(json.dumps(proposal, indent=2))
    except (BudgetExceeded, VersionDrift):
        raise
    except Exception as e:
        terminal_error = f"{type(e).__name__}: {e}"
        (sample_dir / "terminal_failure.json").write_text(
            json.dumps({"error": terminal_error}, indent=2)
        )

    # --- production-path verification from the recorded calls ---
    proposing_prompt = ""
    mode_pipeline = False
    calls_file = sample_dir / "calls.jsonl"
    if calls_file.exists():
        for line in calls_file.read_text().splitlines():
            row = json.loads(line)
            if row.get("node") != "proposer" or not row.get("request_messages"):
                continue
            system = next(
                (m["content"] for m in row["request_messages"] if m["role"] == "system"), ""
            )
            if "custom_loss_spec" in system:  # proposing_stage.md marker
                proposing_prompt = system
                mode_pipeline = True
    (sample_dir / "proposing_stage_prompt.txt").write_text(proposing_prompt)
    meta["production_pipeline_mode"] = mode_pipeline
    meta["terminal_error"] = terminal_error
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    score = score_sample(scenario, arm, proposal, proposing_prompt)
    (sample_dir / "deterministic_score.json").write_text(json.dumps(score, indent=2))
    meta["ledger_after"] = {
        "calls": ledger.calls,
        "input_tokens": ledger.input_tokens,
        "cached_tokens": ledger.cached_tokens,
        "output_tokens": ledger.output_tokens,
        "cost_usd": round(ledger.cost, 4),
    }
    (sample_dir / "sample_meta.json").write_text(json.dumps(meta, indent=2))

    if proposal is not None and not mode_pipeline:
        raise RuntimeError(
            f"{sid}: production pipeline mode NOT verified — invalid sample, "
            f"protocol stop condition"
        )
    return meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--max_calls", type=int, required=True)
    parser.add_argument("--dollar_cap", type=float, required=True)
    parser.add_argument("--order_manifest", default=None)
    args = parser.parse_args()

    from dotenv import dotenv_values

    keys = dotenv_values(REPO / ".env")
    assert keys.get("OPENAI_API_KEY"), "OPENAI_API_KEY not present in .env"
    os.environ["OPENAI_API_KEY"] = keys["OPENAI_API_KEY"]

    run_dir = REPO / "reports" / "artifacts" / "pr3_l2p" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.max_calls, args.dollar_cap, run_dir / "ledger.jsonl")

    if args.order_manifest:
        order = json.loads(Path(args.order_manifest).read_text())["order"]
    else:
        from scripts.pr3_l2_calibration.fixtures import fixture_hash
        from scripts.pr3_l2_calibration.order import PILOT_ORDER, write_manifest

        write_manifest(
            str(run_dir / "launch_manifest.json"),
            {"S1": fixture_hash("S1"), "S2": fixture_hash("S2")},
        )
        order = PILOT_ORDER

    first_gate_done: list = []
    results = []
    for entry in order:
        print(f"[{entry['idx']}] {entry['scenario']}_{entry['arm']}_{entry['rep']} ...")
        meta = run_sample(entry, run_dir, ledger, first_gate_done)
        results.append(meta)
        print(
            f"    done: calls={ledger.calls} cost=${ledger.cost:.2f} "
            f"terminal_error={meta['terminal_error']}"
        )
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "samples": results,
                "calls": ledger.calls,
                "input_tokens": ledger.input_tokens,
                "cached_tokens": ledger.cached_tokens,
                "output_tokens": ledger.output_tokens,
                "cost_usd": round(ledger.cost, 4),
                "pinned_model_version": ledger.pinned_version,
            },
            indent=2,
        )
    )
    print(f"RUN COMPLETE: {ledger.calls} calls, ${ledger.cost:.2f}")


if __name__ == "__main__":
    main()
