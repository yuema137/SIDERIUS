#!/usr/bin/env python
"""Step 10 / P3 — Gate 1: does a REAL model obey lower-is-better semantics?

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p3_proposer_typed_evidence.md`` §8.2 (the frozen Gate contract, Q-P3-2)
and §7 C5. Gate standard: ``docs/gates/gate_testing_standard.md`` "Gate 1 — Real
LLM + pseudo training".

The failure class this owns, and nothing else can
--------------------------------------------------
C4's deterministic fixtures prove the PROMPT is direction-correct. They cannot
prove a real model READS it. Every worked example in this system's history was
higher-is-better, and a pattern-matching model under a ``lower`` metric may
still pick the largest number as SOTA and author an upward prediction. That is
LLM behaviour, so only a real call can observe it.

Two responsibilities, because P3 changed two stages (C-P3-1):

  A. COMPARISON / SOTA — given unambiguous candidate scores under a
     DAVIS-shaped LOWER-is-better metric, does the model name the LOWEST
     score as the SOTA?
  B. CAUSAL / PREDICTION AUTHORING — is the prediction schema-valid, does
     ``predicted_value`` move toward BETTER = LOWER, and does
     ``threshold_for_refutation`` sit on the REFUTED side (ABOVE current)?

Design of the fixture, so the verdict means something
-----------------------------------------------------
Model names are NEUTRAL (``alpha_net`` / ``beta_net`` / ``gamma_net``). A
fixture with a model called "best" would let the model score a pass off the
name instead of the numbers and the stated direction. The scores are
unambiguous and well separated, and the BEST one is deliberately NOT first in
declaration order, so "picked the first" and "picked the best" are
distinguishable.

Budget: the run is capped at 3 real calls (comparison, causal, proposing) and
the cap is enforced mechanically — the 4th call raises. Both acceptance
predicates are decided from the PERSISTED stage artifacts of calls 1 and 2, so
a capped run still yields a readable verdict.

Usage::

    ./.venv/bin/python scripts/step10_p3_gate1.py --out <evidence_dir>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llm_bridge import LLMBridge  # noqa: E402
from agent.schemas.proposal import (  # noqa: E402
    FalsifiablePrediction,
    ModelSelectionStrategy,
    ProposalInput,
    ReasoningPipelineConfig,
    ReasoningStage,
    ResearchPolicy,
)
from agent.schemas.proposer_evidence import build_proposer_evidence  # noqa: E402
from agent.schemas.storage import LocalStorageConfig, StorageConfig  # noqa: E402
from agent.schemas.task_config import ForwardContract  # noqa: E402
from execute_tools.evaluation_metric import metric_spec_from_declaration  # noqa: E402
from execute_tools.metric_order import MetricOrder  # noqa: E402
from nodes.ml_model_proposal_agent import MLModelProposalAgent  # noqa: E402

MAX_REAL_CALLS = 3

#: The Gate's metric identity comes from the REAL DAVIS pack declaration, never
#: from a direction literal typed here. Two reasons, and both matter:
#:
#: 1. Step 06's C5 boundary guard forbids any production surface — `scripts/`
#:    included — from executing a `"higher"`/`"lower"` literal. The declaration
#:    is DATA; reading it is not a second direction authority. This is the same
#:    route `scripts/run_davis_gate2.py` takes.
#: 2. It makes "DAVIS-shaped" literally true: the Gate exercises the identity
#:    DAVIS actually ships (`mse`, lower), not a hand-typed imitation of it.
_DAVIS_METRIC_DECLARATION = (
    REPO_ROOT / "examples" / "davis_future_prediction" / "declared" / "metric_mse.json"
)
DAVIS_SPEC = metric_spec_from_declaration(
    json.loads(_DAVIS_METRIC_DECLARATION.read_text(encoding="utf-8"))
)
DAVIS_IDENTITY: dict[str, str] = {
    "metric_id": DAVIS_SPEC.id,
    "direction": DAVIS_SPEC.direction,
}

#: DAVIS-shaped: global MSE, LOWER is better. beta_net (0.0172) is the SOTA.
#: Neutral names, and the best model is NOT first in declaration order.
DAVIS_SCORES: dict[str, float] = {
    "alpha_net": 0.0210,  # worst
    "beta_net": 0.0172,  # BEST under lower-is-better
    "gamma_net": 0.0186,
}
SOTA_MODEL = "beta_net"
SOTA_SCORE = 0.0172
WORST_MODEL = "alpha_net"
WORST_SCORE = 0.0210


_ORDER = MetricOrder(DAVIS_SPEC)


class CallCapExceeded(RuntimeError):
    """The Gate's mechanical budget, not an implementation failure."""


class RecordingBridge(LLMBridge):
    """The REAL bridge, with every boundary crossing recorded and counted."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.calls: list[dict[str, Any]] = []

    def _record(self, kind: str, label: str, system: str, user: str) -> None:
        if len(self.calls) >= MAX_REAL_CALLS:
            raise CallCapExceeded(
                f"the Gate's {MAX_REAL_CALLS}-call budget is exhausted; "
                f"refusing call {len(self.calls) + 1} ({label})"
            )
        self.calls.append(
            {
                "index": len(self.calls) + 1,
                "kind": kind,
                "label": label,
                "system_prompt": system,
                "user_prompt": user,
            }
        )

    def _chat_json(self, client, model_name, system_prompt, user_prompt, **kw) -> dict:
        self._record("json", kw.get("label", "unlabeled"), system_prompt, user_prompt)
        result = super()._chat_json(client, model_name, system_prompt, user_prompt, **kw)
        self.calls[-1]["response"] = result
        return result

    def generate_text(self, system_prompt, user_prompt, **kw) -> str:
        self._record("text", kw.get("label", "unlabeled"), system_prompt, user_prompt)
        result = super().generate_text(system_prompt, user_prompt, **kw)
        self.calls[-1]["response"] = result
        return result


def build_input(workspace: Path) -> ProposalInput:
    """A production-shaped ProposalInput on the DAVIS-shaped lower fixture."""
    dump: dict[str, Any] = {
        "metric_identity": dict(DAVIS_IDENTITY),
        "model_types": list(DAVIS_SCORES),
        "model_descriptions": {
            "alpha_net": "Encoder-decoder with strided downsampling and skip connections.",
            "beta_net": "Dilated temporal convolution stack with a residual head.",
            "gamma_net": "Gated recurrent encoder with a linear projection head.",
        },
        "total_experiments": 9,
        "per_model_best": dict(DAVIS_SCORES),
        "per_model_best_valid": dict(DAVIS_SCORES),
        "per_model_worst": {k: v * 1.4 for k, v in DAVIS_SCORES.items()},
        "per_model_raw_best_health_validity": dict.fromkeys(DAVIS_SCORES, "valid"),
        "per_model_params": {"alpha_net": 1_800_000, "beta_net": 900_000, "gamma_net": 2_400_000},
        "best_denoising_score": SOTA_SCORE,
        "worst_denoising_score": WORST_SCORE,
        "key_findings": [
            "All three architectures were trained under the same schedule and budget.",
            "The spread between the architectures is well outside run-to-run noise.",
        ],
        "bottlenecks": ["Reconstruction error on the fastest-moving regions dominates."],
        "take_home_message": "Pick the architecture the evidence supports and build on it.",
    }
    return ProposalInput(
        interpretation_evidence=build_proposer_evidence(dump),
        existing_model_types=list(DAVIS_SCORES),
        task_description=(
            "Predict the next frames of a video sequence from the preceding frames. "
            "Quality is measured as global mean squared error between the predicted "
            "frames and the ground-truth frames."
        ),
        forward_contract=ForwardContract(
            input_shape="[B, 8, 3, H, W] float32",
            input_description="eight consecutive RGB frames",
            output_shape="[B, 4, 3, H, W] float32",
            output_description="four predicted future RGB frames",
            task_type="regression",
        ),
        constraints=["VRAM < 8 GB"],
        reasoning_pipeline=ReasoningPipelineConfig(
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
            model_selection=ModelSelectionStrategy(),
            exploration_mode="exploit",
            policy=ResearchPolicy(minimum_boldness=0.05),
        ),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(workspace), run_name="p3_gate1"),
        ),
    )


def evaluate_comparison(response: dict[str, Any]) -> dict[str, Any]:
    """Acceptance A — the SOTA must be the BEST score under the declared order."""
    named = response.get("sota_model_type")
    score = response.get("sota_score")
    checks = {
        "sota_model_type_is_the_lowest_scoring_model": named == SOTA_MODEL,
        "sota_score_matches_the_lowest_score": (
            isinstance(score, int | float) and abs(float(score) - SOTA_SCORE) < 1e-9
        ),
        "the_worst_model_was_not_named_sota": named != WORST_MODEL,
    }
    return {
        "sota_model_type": named,
        "sota_score": score,
        "expected_sota_model_type": SOTA_MODEL,
        "expected_sota_score": SOTA_SCORE,
        "checks": checks,
        "verdict": "PASS" if all(checks.values()) else "FAIL",
    }


def evaluate_causal(response: dict[str, Any]) -> dict[str, Any]:
    """Acceptance B — schema-valid, moves toward LOWER, threshold ABOVE."""
    raw = response.get("falsifiable_prediction")
    result: dict[str, Any] = {"raw_prediction": raw}
    try:
        pred = FalsifiablePrediction.model_validate(raw)
    except Exception as exc:
        result["checks"] = {"schema_valid": False}
        result["schema_error"] = str(exc)
        result["verdict"] = "FAIL"
        return result

    checks = {
        "schema_valid": True,
        # "Better" and "refuted side" are asked of the ONE order authority, so
        # this checker cannot drift from the semantics it is verifying.
        "predicted_value_moves_toward_better": _ORDER.is_better(
            pred.predicted_value, pred.current_value
        ),
        "threshold_is_on_the_refuted_side": _ORDER.is_better(
            pred.current_value, pred.threshold_for_refutation
        ),
        "threshold_is_on_the_opposite_side_from_the_prediction": (
            (pred.predicted_value > pred.current_value)
            != (pred.threshold_for_refutation > pred.current_value)
        ),
    }
    result["current_value"] = pred.current_value
    result["predicted_value"] = pred.predicted_value
    result["threshold_for_refutation"] = pred.threshold_for_refutation
    result["metric"] = pred.metric
    result["checks"] = checks
    result["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 10 / P3 Gate 1")
    parser.add_argument("--out", required=True, help="evidence directory")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    workspace = out / "workspace"
    workspace.mkdir(exist_ok=True)

    started = datetime.now(UTC)
    bridge_holder: dict[str, RecordingBridge] = {}

    def factory(**kwargs: Any) -> RecordingBridge:
        bridge = RecordingBridge(**kwargs)
        bridge_holder["bridge"] = bridge
        return bridge

    agent = MLModelProposalAgent(provider="openai", model_id="gpt-5.5", bridge_factory=factory)
    run_error: str | None = None
    try:
        agent.run(build_input(workspace))
    except CallCapExceeded as exc:
        run_error = f"call cap reached (expected if a stage retried): {exc}"
    except Exception as exc:
        run_error = f"{type(exc).__name__}: {exc}"

    bridge = bridge_holder["bridge"]
    by_label = {c["label"]: c for c in bridge.calls}

    comparison = by_label.get("proposer.comparison")
    causal = next((c for k, c in by_label.items() if k.startswith("proposer.causal")), None)

    evidence: dict[str, Any] = {
        "gate": "Step 10 / P3 Gate 1",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "wall_seconds": (datetime.now(UTC) - started).total_seconds(),
        "provider": "openai",
        "model_id": "gpt-5.5",
        "max_real_calls": MAX_REAL_CALLS,
        "real_calls_used": len(bridge.calls),
        "call_labels": [c["label"] for c in bridge.calls],
        "fixture": {
            "metric_declaration": str(_DAVIS_METRIC_DECLARATION.relative_to(REPO_ROOT)),
            "metric_identity": dict(DAVIS_IDENTITY),
            "scores": DAVIS_SCORES,
            "expected_sota": SOTA_MODEL,
        },
        "run_error": run_error,
    }
    evidence["acceptance_A_comparison"] = (
        evaluate_comparison(comparison["response"])
        if comparison and isinstance(comparison.get("response"), dict)
        else {"verdict": "INCONCLUSIVE", "reason": "no comparison artifact was produced"}
    )
    evidence["acceptance_B_causal"] = (
        evaluate_causal(causal["response"])
        if causal and isinstance(causal.get("response"), dict)
        else {"verdict": "INCONCLUSIVE", "reason": "no causal artifact was produced"}
    )
    verdicts = {
        evidence["acceptance_A_comparison"]["verdict"],
        evidence["acceptance_B_causal"]["verdict"],
    }
    evidence["overall_verdict"] = (
        "PASS" if verdicts == {"PASS"} else ("FAIL" if "FAIL" in verdicts else "INCONCLUSIVE")
    )

    (out / "gate1_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    (out / "gate1_calls.json").write_text(json.dumps(bridge.calls, indent=2), encoding="utf-8")

    print(json.dumps({k: v for k, v in evidence.items() if k != "fixture"}, indent=2)[:4000])
    print(f"\nEvidence written to {out}")
    return 0 if evidence["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONWARNINGS", "ignore")
    raise SystemExit(main())
