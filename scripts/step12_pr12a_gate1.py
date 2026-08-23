#!/usr/bin/env python
"""Step 12 / PR-12a — G-12a-1: does a REAL model read the COMPOSED task's science?

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C9 and §6.2. Gate standard:
``docs/gates/gate_testing_standard.md`` "Gate 1 — Real LLM + pseudo training".
Parent Gate row: ``step_12_external_extensibility_graduation.md`` §G-12a-1 —
"composed prompts carry the TASK's science (and legacy bytes unchanged) —
real-model reading, the 09b/P3 class; bounded probe set (~<=6 calls); no
training; probe harness re-reads persisted prompts".

The failure class this owns, and nothing else can
--------------------------------------------------
C7's deterministic evidence proves the composed prompts CONTAIN the task's
science and none of TIDMAD's, byte by byte. It cannot prove a real model READS
them. Every worked example this system has ever shown a model was 1-D signal
denoising, and a pattern-matching model handed an unfamiliar task can still
answer in the vocabulary it saw most — proposing a denoiser for a video task,
or treating a lower-is-better metric as something to maximize. That is LLM
behaviour, so only a real call can observe it.

It also owns the harder half, which no deterministic test can reach: when a
composed task declares NO science, the frozen semantic is that the model gets
NOTHING rather than TIDMAD's. A deterministic test proves the bytes are absent.
Only a real call shows whether the model then invents them.

The pre-chosen task facts (operator amendment, design §0.1 item 3)
------------------------------------------------------------------
Never a subjective "the model understands the task". The composed fixture is
DAVIS 2017 future-frame prediction, and three facts are chosen BEFORE the run:

  F1  INPUT TOPOLOGY     8 context RGB frames in, 4 predicted frames out
                         ([B, 3, 8, H, W] -> [B, 3, 4, H, W])
  F2  PREDICTION TARGET  future video frames — not a denoised waveform
  F3  METRIC + DIRECTION `mse`, and LOWER is better

DAVIS is chosen because it is maximally unlike TIDMAD on all three axes and
because its direction is the one the system has never had: a model that pattern-
matches instead of reading will get F3 wrong in a way that is impossible to
misread as a near miss.

Banned concepts are TIDMAD's own science, not merely its name. A response
mentioning "denoising" or "256 amplitude bins" for a video task has imported
science from somewhere other than the declaration.

Budget: 4 real calls, capped mechanically at 6. Every probe re-reads a prompt
rendered through the PRODUCTION assembly path — never a string this file
composed — so a pass means the shipped renderers produced something a real
model can act on.

Usage::

    ./.venv/bin/python scripts/step12_pr12a_gate1.py --out <evidence_dir>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from agent.llm_bridge import LLMBridge  # noqa: E402
from agent.schemas.proposal import ProposalInput  # noqa: E402
from agent.schemas.proposer_evidence import ProposerInterpretationEvidence  # noqa: E402
from workflows.task_composition import compose_run_task_bindings  # noqa: E402

DAVIS_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "davis"

# ---------------------------------------------------------------------------
# The pre-chosen facts, and the banned science. Declared BEFORE the run.
# ---------------------------------------------------------------------------

#: Each fact is a set of ALTERNATIVE spellings; the response must hit >= 1.
#: Alternatives, not a single string, because a model may legitimately write
#: "eight frames" or "8 frames" — the fact is the topology, not the wording.
FACTS: dict[str, dict[str, Any]] = {
    "F1_input_topology": {
        "statement": "8 context frames in, 4 future frames out",
        "any_of": ["8 context", "eight context", "8 input frames", "8 frames", "eight frames"],
        "and_any_of": ["4 future", "four future", "next 4", "next four", "4 frames", "four frames"],
    },
    "F2_prediction_target": {
        "statement": "the target is future VIDEO FRAMES",
        "any_of": ["future frame", "future-frame", "video", "frames of a clip", "clip"],
    },
    "F3_metric_direction": {
        "statement": "the metric is mse and LOWER is better",
        "any_of": ["mse", "mean squared error"],
        # A LITERAL "lower is better" is not how a model writes this. The first
        # run answered "Lower mean squared error is better." — correct, and
        # invisible to a substring matcher because the metric name sits between
        # the words. Corrected to a regex, and paired with a NEGATIVE clause so
        # the fix cannot be mistaken for a loosening: a response claiming the
        # opposite direction still FAILS.
        "and_regex_any_of": [
            r"lower[^.\n]{0,80}\bis better\b",
            r"lower[- ]is[- ]better",
            r"\bminimi[sz]",
            r"the lower[^.\n]{0,80}the better",
        ],
        "regex_none_of": [r"higher[^.\n]{0,80}\bis better\b", r"\bmaximi[sz]"],
    },
}

#: TIDMAD's science, not merely its name. A video task's answer must contain
#: none of it.
BANNED_TIDMAD_CONCEPTS = (
    "denois",
    "waveform",
    "squid",
    "dark matter",
    "256 amplitude",
    "256-class",
    "256 class",
    "amplitude bin",
    "impact_score",
    "linear_weight",
    "channel0001",
    "channel0002",
    "1-d time-series",
    "abracadabra",
)


class CallCap:
    """A mechanical budget. The 7th call raises rather than quietly spending."""

    def __init__(self, limit: int = 6) -> None:
        self.limit = limit
        self.used = 0

    def spend(self, label: str) -> None:
        self.used += 1
        if self.used > self.limit:
            raise RuntimeError(
                f"real-call budget exhausted at {self.limit} (attempted {label!r}). "
                "The Gate is bounded on purpose; raising the cap is an operator decision."
            )
        print(f"  [call {self.used}/{self.limit}] {label}")


# ---------------------------------------------------------------------------
# The composed fixture — a real manifest, composed by the production loader
# ---------------------------------------------------------------------------


def build_composed_manifest(work: Path, *, declare_science: bool) -> Path:
    """A DAVIS composition, with or without declared proposer/implementor science.

    Built from the COMMITTED DAVIS fixture with its refs absolutized, so the
    task facts come from the real declaration rather than from prose this file
    invented. ``declare_science=False`` is the absence probe.
    """
    work.mkdir(parents=True, exist_ok=True)
    raw = yaml.safe_load((DAVIS_FIXTURE / "composition.yaml").read_text(encoding="utf-8"))
    raw = _absolutize(raw, DAVIS_FIXTURE)

    if declare_science:
        blocks = work / "davis_proposal.yaml"
        blocks.write_text(
            yaml.safe_dump(
                {
                    "architect_role": "video future-frame prediction",
                    "output_contract_guidance": (
                        "A candidate predicts the next 4 RGB frames of a clip directly "
                        "from its 8 context frames. There is no class alphabet: the "
                        "output is dense per-pixel intensity."
                    ),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        impl = work / "davis_implementor.yaml"
        impl.write_text(
            yaml.safe_dump(
                {
                    "science_domain": "video future-frame prediction",
                    "continuous_output_phrase": "dense per-pixel frame regression",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        raw["proposal_blocks"] = {"config": str(blocks)}
        raw["implementor_blocks"] = {"config": str(impl)}

    target = work / "composition.yaml"
    target.write_text(yaml.safe_dump(raw, sort_keys=True), encoding="utf-8")
    return target


def _absolutize(node: Any, base: Path) -> Any:
    if isinstance(node, dict):
        return {
            key: (
                os.path.abspath(os.path.join(base, value))
                if key in ("config", "declaration", "file") and isinstance(value, str)
                else _absolutize(value, base)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_absolutize(item, base) for item in node]
    return node


# ---------------------------------------------------------------------------
# Prompt rendering — through PRODUCTION assembly, never composed here
# ---------------------------------------------------------------------------


def render_proposer_prompt(composition: Any) -> str:
    from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
        _build_reasoning_system_prompt,
    )

    task_config = _task_config(composition)
    return _build_reasoning_system_prompt(
        ProposalInput(
            task_description=task_config["task_description"],
            forward_contract=task_config["forward_contract"],
            proposal_blocks=composition.proposal_blocks,
            # An EMPTY evidence projection: this Gate probes the task-science
            # surface, and a populated one would let the model answer from
            # score tables instead of from the declaration.
            interpretation_evidence=ProposerInterpretationEvidence(),
        )
    )


def render_implementor_prompt(composition: Any) -> str:
    from nodes.ml_model_implementor.ml_model_implementor import (
        IMPLEMENTOR_REASONING_PROMPT,
        render_engineer_role,
    )

    return IMPLEMENTOR_REASONING_PROMPT.replace(
        "{ENGINEER_ROLE}", render_engineer_role(composition.implementor_blocks)
    )


def _task_config(composition: Any) -> dict[str, Any]:
    from agent.schemas.task_config import ForwardContract

    raw = yaml.safe_load((DAVIS_FIXTURE / "task_config.yaml").read_text(encoding="utf-8"))
    return {
        "task_description": raw["task_description"],
        "forward_contract": ForwardContract(**raw["forward_contract"]),
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def check_facts(text: str) -> dict[str, Any]:
    """Decide each pre-chosen fact from the response text.

    Substring alternatives for the facts a model states as nouns; REGEX for the
    one it states as a sentence, plus a negative clause so a corrected matcher
    cannot silently become a looser one.
    """
    lowered = text.lower()
    out: dict[str, Any] = {}
    for name, spec in FACTS.items():
        checks = [any(token in lowered for token in spec["any_of"])]
        if "and_any_of" in spec:
            checks.append(any(token in lowered for token in spec["and_any_of"]))
        if "and_regex_any_of" in spec:
            checks.append(any(re.search(r, lowered) for r in spec["and_regex_any_of"]))
        if "regex_none_of" in spec:
            checks.append(not any(re.search(r, lowered) for r in spec["regex_none_of"]))
        out[name] = {"statement": spec["statement"], "present": all(checks)}
    return out


def check_banned(text: str) -> list[str]:
    lowered = text.lower()
    return [concept for concept in BANNED_TIDMAD_CONCEPTS if concept in lowered]


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def probe(
    bridge: LLMBridge,
    cap: CallCap,
    *,
    label: str,
    system: str,
    user: str,
) -> dict[str, Any]:
    cap.spend(label)
    response = bridge.generate_text(system_prompt=system, user_prompt=user, label=label)
    return {
        "label": label,
        "prompt_sha_note": "system prompt rendered by the production assembly path",
        "system_prompt": system,
        "user_prompt": user,
        "response": response,
        "prompt_banned_hits": check_banned(system),
        "response_banned_hits": check_banned(response),
        "response_facts": check_facts(response),
    }


ASK_FACTS = (
    "Before proposing anything, state in plain prose, in at most six sentences: "
    "(a) the shape and meaning of the input this task gives a model and the shape "
    "and meaning of the output it must produce; (b) what the model is predicting; "
    "and (c) the name of the primary evaluation metric and whether a better model "
    "scores higher or lower on it. Answer only from the task information you were "
    "given. If some part was not given to you, say so explicitly instead of "
    "supplying a plausible answer."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="evidence directory")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model_id", default="gpt-5.5")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "work"
    work.mkdir(exist_ok=True)

    cap = CallCap(limit=6)
    bridge = LLMBridge(provider=args.provider, model_id=args.model_id)

    print("Composing the DAVIS fixture WITH declared science ...")
    declared = compose_run_task_bindings(
        str(build_composed_manifest(work / "declared", declare_science=True))
    )
    print("Composing the same fixture WITHOUT it (the absence probe) ...")
    bare = compose_run_task_bindings(
        str(build_composed_manifest(work / "bare", declare_science=False))
    )

    probes: list[dict[str, Any]] = []

    # P1/P2 — declared science reaches the model, at both authoring nodes.
    probes.append(
        probe(
            bridge,
            cap,
            label="proposer.declared",
            system=render_proposer_prompt(declared),
            user=ASK_FACTS,
        )
    )
    probes.append(
        probe(
            bridge,
            cap,
            label="implementor.declared",
            system=render_implementor_prompt(declared),
            user=(
                "State in at most three sentences what kind of model you have been "
                "asked to write code for, and what its output represents. Answer only "
                "from the instructions you were given; if the domain was not stated, "
                "say that it was not stated rather than assuming one."
            ),
        )
    )

    # P3/P4 — the absence probe. NOTHING, not TIDMAD's science.
    probes.append(
        probe(
            bridge,
            cap,
            label="proposer.undeclared",
            system=render_proposer_prompt(bare),
            user=ASK_FACTS,
        )
    )
    probes.append(
        probe(
            bridge,
            cap,
            label="implementor.undeclared",
            system=render_implementor_prompt(bare),
            user=(
                "State in at most three sentences what scientific or application "
                "domain you have been told you are working in. If no domain was "
                "stated, say exactly that — do not infer one."
            ),
        )
    )

    verdict = evaluate(probes)
    payload = {
        "gate": "G-12a-1",
        "utc": datetime.now(UTC).isoformat(),
        "provider": args.provider,
        "model_id": args.model_id,
        "real_calls": cap.used,
        "facts": {name: spec["statement"] for name, spec in FACTS.items()},
        "banned_concepts": list(BANNED_TIDMAD_CONCEPTS),
        "probes": probes,
        "verdict": verdict,
    }
    (out / "gate1_result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    for line in verdict["lines"]:
        print(line)
    print("=" * 70)
    print(f"  G-12a-1: {verdict['status']}   ({cap.used} real calls)")
    print("=" * 70)
    return 0 if verdict["status"] == "PASS" else 1


def evaluate(probes: list[dict[str, Any]]) -> dict[str, Any]:
    """Acceptance, decided from the persisted artifacts.

    Four checks, each naming what it would catch:

      1. every rendered COMPOSED prompt is free of TIDMAD science — the
         deterministic property, re-asserted on the exact bytes sent;
      2. with declared science, the model reflects ALL THREE pre-chosen facts;
      3. no response imports TIDMAD science, declared or not;
      4. with NO declared science, the model does not supply TIDMAD's — the
         frozen semantic that only a real call can observe.
    """
    lines: list[str] = []
    ok = True

    for p in probes:
        hits = p["prompt_banned_hits"]
        good = not hits
        ok &= good
        lines.append(
            f"  [{'PASS' if good else 'FAIL'}] {p['label']}: rendered prompt carries "
            f"no TIDMAD science" + (f" — found {hits}" if hits else "")
        )

    for p in probes:
        if not p["label"].endswith(".declared"):
            continue
        for name, result in p["response_facts"].items():
            # The implementor prompt is deliberately given only the science
            # domain, so it is scored on F2 alone; the proposer carries the
            # task description and forward contract and is scored on all three.
            if p["label"].startswith("implementor") and name != "F2_prediction_target":
                continue
            good = result["present"]
            ok &= good
            lines.append(
                f"  [{'PASS' if good else 'FAIL'}] {p['label']}: response reflects "
                f"{name} ({result['statement']})"
            )

    for p in probes:
        hits = p["response_banned_hits"]
        good = not hits
        ok &= good
        lines.append(
            f"  [{'PASS' if good else 'FAIL'}] {p['label']}: response imports no "
            f"TIDMAD science" + (f" — found {hits}" if hits else "")
        )

    return {"status": "PASS" if ok else "FAIL", "lines": lines}


if __name__ == "__main__":
    raise SystemExit(main())
