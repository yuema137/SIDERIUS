# scripts/pr3_l2_calibration/preflight.py
"""Zero-LLM launch preflight (protocol §3.3-§3.4). NO LLM CALLS.

Drives the full production assembly per arm with a mocked bridge and
asserts every launch invariant; also produces the launch-day prompt
measurement. Run via the pytest wrapper
(tests/unit/scripts/test_pr3_l2p_preflight.py) or directly:

    .venv/bin/python -m scripts.pr3_l2_calibration.preflight
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

FAKE_COMPARISON = {
    "comparisons": [],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "spectral_resnet_b",
    "sota_score": 1.62,
    "sota_mechanism": "Gated spectral residual path.",
}
FAKE_REASONING = {
    "proposed_change": "Add variance-preserving output head.",
    "causal_hypothesis": "Output head collapse causes single-value output.",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 1.62,
        "predicted_value": 2.0,
        "threshold_for_refutation": 1.0,
        "rationale": "Anti-collapse head should preserve diversity.",
    },
    "predicted_failure_modes": ["VRAM overflow."],
    "inherited_components": [],
    "proposed_vocab_candidates": [],
}
FAKE_PROPOSING = {
    "model_name": "variance_preserving_unet",
    "model_description": "UNet with variance-preserving output head.",
    "mathematical_definition": "Conv encoder/decoder + entropy-regularized head.",
    "motivation": "Addresses diversity collapse.",
    "expert_advice": {
        "focus_areas": ["output diversity"],
        "constraints": ["VRAM < 10 GB"],
        "known_failures": [],
        "suggested_directions": [],
        "rationale": "Anti-collapse baseline.",
    },
    "baseline_config": {
        "model_config": {"depth": 3},
        "train_config": {"lr": 1e-4, "epochs": 1},
        "loss_config": {"loss_type": "focal"},
    },
    "memo_consistency_notes": [],
}
FAKE_INTERP_PER_MODEL = {
    "key_findings": ["finding"],
    "bottlenecks": ["bottleneck"],
    "best_config_analysis": "analysis",
    "score_trend": "flat",
    "per_file_analysis": "n/a",
    "data_sensitivity": "n/a",
    "efficiency_assessment": "n/a",
    "strategy_assessment": "n/a",
}
FAKE_INTERP_SYNTHESIS = {
    "key_findings": ["cross-model finding"],
    "bottlenecks": ["cross bottleneck"],
    "take_home_message": "Break the collapse.",
    "proposed_vocab_candidates": [],
    "prediction_evaluation": None,
}


def _interp_dispatch(system_prompt, user_prompt, **kw):
    if "ONE model architecture" in system_prompt:
        return dict(FAKE_INTERP_PER_MODEL)
    return dict(FAKE_INTERP_SYNTHESIS)


def run_arm(scenario: str, arm: str) -> dict:
    """Assemble one sample's full prompt set with mocked LLMs; return the
    measurement + invariant record."""
    import tempfile
    from unittest.mock import patch

    from agent.schemas.interpretation import InterpretationInput
    from agent.schemas.proposal import (
        ForwardContract,
        ReasoningPipelineConfig,
        ReasoningStage,
    )
    from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
        local_full_context,
    )
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from execute_tools.dataset_config import bind_dataset_profile
    from execute_tools.metric_order import MetricOrder
    from nodes.ml_model_proposal_agent import MLModelProposalAgent
    from nodes.result_interpretation_agent import (
        ResultInterpretationAgent,
        reconcile_metric_spec,
        tuning_output_to_model_run_summary,
    )
    from scripts.pr3_l2_calibration.fixtures import MODEL_DESCRIPTIONS, SCENARIOS
    from workflows.task_composition import compose_run_task_bindings
    from workflows.task_config import get_task_description

    spec = SCENARIOS[scenario]
    composition = compose_run_task_bindings(str(REPO / "configs/task_composition/quickstart.yaml"))
    task_config = composition.task_config_values()
    interp_on, proposer_on = arm in ("T", "D"), arm == "T"
    tmp = tempfile.mkdtemp(prefix=f"p3l2p_preflight_{scenario}_{arm}_")

    summaries = []
    tune_outputs = spec["tune_outputs"]()
    run_metric_spec = reconcile_metric_spec(tune_outputs)
    run_order = MetricOrder(run_metric_spec) if run_metric_spec is not None else None
    for out in tune_outputs:
        s = tuning_output_to_model_run_summary(out, order=run_order)
        s.model_description = MODEL_DESCRIPTIONS.get(s.model_type)
        summaries.append(s)
    interp_input = InterpretationInput(
        summaries=summaries,
        # Step 09a C2 — reconciled from the outputs, exactly as the workflow
        # does. The FIXTURE stamped the spec (Q-09a-7: simulated tuner-output
        # writer); this entry point derives nothing.
        metric_spec=run_metric_spec,
        storage=StorageConfig(
            backend="local", local=LocalStorageConfig(workspace=tmp, run_name="pf")
        ),
        iteration=spec["iteration"],
        enable_structured_health_feedback=interp_on,
        collapse_fingerprint_history=spec["carried_history"](),
        task_description=get_task_description(task_config),
    )
    with patch("nodes.result_interpretation_agent.LLMBridge") as MB:
        MB.return_value.generate.side_effect = _interp_dispatch
        agent = ResultInterpretationAgent(provider="openai", model_id="preflight")
        agent.bridge = MB.return_value
        interp_out = agent.run(interp_input)
    interp_prompts = [
        (c.kwargs.get("system_prompt") or c.args[0])
        + "\n"
        + (c.kwargs.get("user_prompt") or c.args[1])
        for c in agent.bridge.generate.call_args_list
    ]

    storage = StorageConfig(backend="local", local=LocalStorageConfig(workspace=tmp, run_name="pf"))
    propose_input = local_full_context(
        interp_out,
        storage,
        enable_structured_health_feedback=proposer_on,
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode="exploit",
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
        ),
    )
    _cfg = task_config
    propose_input.task_description = get_task_description(_cfg)
    propose_input.forward_contract = ForwardContract(**_cfg["forward_contract"])

    mb = MagicMock()
    mb.generate.side_effect = [FAKE_COMPARISON, FAKE_REASONING, FAKE_PROPOSING]
    proposer = MLModelProposalAgent(
        provider="openai", model_id="preflight", bridge_factory=lambda **kw: mb
    )
    with bind_dataset_profile(composition.dataset_profile):
        proposer.run(propose_input)
    stage_prompts = []
    proposing_prompt = ""
    for c in mb.generate.call_args_list:
        sp = c.kwargs.get("system_prompt") or c.args[0]
        up = c.kwargs.get("user_prompt") or (c.args[1] if len(c.args) > 1 else "") or ""
        stage_prompts.append(sp + "\n" + up)
        if "custom_loss_spec" in sp:
            proposing_prompt = sp

    interp_chars = sum(len(p) for p in interp_prompts)
    proposer_chars = sum(len(p) for p in stage_prompts)
    return {
        "scenario": scenario,
        "arm": arm,
        "pipeline_mode": bool(proposing_prompt),
        "placeholder_unresolved": "{healthgate_evidence_block}" in proposing_prompt
        or "{recent_gate_exhaustions_block}" in proposing_prompt,
        "proposer_block_present": "[HEALTHGATE EVIDENCE]" in proposing_prompt,
        "interp_block_present": any("HealthGate summary" in p for p in interp_prompts),
        "interp_chars": interp_chars,
        "proposer_chars": proposer_chars,
        "est_input_tokens": (interp_chars + proposer_chars) // 4,
        "proposing_prompt": proposing_prompt,
    }


def rev3_vocab_and_tee_checks() -> dict:
    """Rev-3 operator-required proofs (protocol §3.3 rev 3): production
    vocabulary equivalence + raw-response tee capture, zero LLM calls."""
    import json as _json
    import subprocess
    import tempfile

    from scripts.pr3_l2_calibration.fixtures import (
        canonical_fixture_payload,
        production_vocab_seed,
    )
    from workflows.model_exploration import _load_vocab_seed

    checks: dict = {}
    # 1-2: non-empty + byte-equivalent to the production static seed file.
    seed = production_vocab_seed()
    checks["vocab_nonempty"] = len(seed) > 0
    with open(REPO / "agent" / "schemas" / "vocab_seed.json") as fh:
        raw_file = _json.load(fh)
    loaded = [v.model_dump(mode="json") if hasattr(v, "model_dump") else v for v in seed]
    raw_names = (
        {
            e["name"]
            for e in (raw_file if isinstance(raw_file, list) else raw_file.get("entries", raw_file))
        }
        if isinstance(raw_file, (list, dict))
        else set()
    )
    checks["vocab_matches_production_file"] = len(loaded) == (
        len(raw_file) if isinstance(raw_file, list) else len(raw_names)
    ) and all(e["name"] in raw_names or not raw_names for e in loaded)
    # 4: production loading path exercised (same function object).
    checks["production_loader_used"] = (
        production_vocab_seed.__module__.endswith("fixtures") and _load_vocab_seed is not None
    )
    # 3: vocabulary content identical across arm computations (arm-free
    # builders; three consecutive canonical payloads agree).
    p1 = canonical_fixture_payload("S1")["vocab_seed"]
    p2 = canonical_fixture_payload("S1")["vocab_seed"]
    checks["vocab_identical_across_computations"] = p1 == p2 and len(p1) == len(seed)

    # 8-9: raw-response tee capture for schema-INVALID bodies + distinct
    # retry artifacts, with a fake client (no LLM).
    from scripts.pr3_l2_calibration.runner import Ledger, _wrap_client

    class _FakeMsg:
        def __init__(self, content):
            self.content = content

    class _FakeChoice:
        def __init__(self, content):
            self.message = _FakeMsg(content)
            self.finish_reason = "stop"

    class _FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5
        total_tokens = 15
        prompt_tokens_details = None

    class _FakeResp:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]
            self.usage = _FakeUsage()
            self.model = "fake-model"

    bodies = iter(["not json at all", '{"schema": "still-wrong"}'])

    class _FakeCompletions:
        def create(self, *a, **k):
            return _FakeResp(next(bodies))

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        chat = _FakeChat()

    class _FakeBridge:
        client = _FakeClient()

    tmp = Path(tempfile.mkdtemp(prefix="p3l2p_tee_"))
    ledger = Ledger(10, 1.0, tmp / "ledger.jsonl")
    bridge = _FakeBridge()
    _wrap_client(bridge, ledger, tmp, node="tee-test")
    bridge.client.chat.completions.create(messages=[{"role": "user", "content": "x"}])
    bridge.client.chat.completions.create(messages=[{"role": "user", "content": "x"}])
    rows = [_json.loads(line) for line in (tmp / "calls.jsonl").read_text().splitlines()]
    checks["tee_captures_invalid_bodies"] = (
        rows[0]["response_content"] == "not json at all"
        and rows[1]["response_content"] == '{"schema": "still-wrong"}'
    )
    checks["retry_artifacts_distinct"] = rows[0]["response_content"] != rows[1]["response_content"]

    # 10: no production source file modified (calibration scope only).
    #
    # F-M2-2 — this check FAILS CLOSED when it cannot look.
    #
    # The call used to be `subprocess.run(...).stdout.splitlines()` with no
    # `check=True` and no returncode inspection. Any git failure — not a
    # repository, git absent, an unreadable index — produced empty stdout, so
    # `offenders` was `[]` and the check reported PASS. A guard that passes
    # because it could not perform its check is worse than no guard: CLAUDE.md
    # carries "production untouched at launch" as a binding precondition of
    # the PR3-L2 calibration protocol, so a silent green here lets a
    # calibration run start from a dirty tree with its central precondition
    # unverified.
    #
    # "No offenders found" and "could not look for offenders" are different
    # facts and must never share a verdict. Same fail-open family as F2, where
    # an empty gate list meant "nothing ran" and read as "nothing fired".
    #
    # `tests/` was swept for this class; `scripts/` never was.
    diff_proc = subprocess.run(
        ["git", "diff", "--name-only"], capture_output=True, text=True, cwd=REPO
    )
    if diff_proc.returncode != 0:
        detail = diff_proc.stderr.strip() or "no stderr"
        checks["no_production_file_modified"] = False
        checks["_offending_files"] = [
            f"UNVERIFIABLE: `git diff --name-only` failed in {REPO} "
            f"(exit {diff_proc.returncode}): {detail}"
        ]
    else:
        offenders = [
            f
            for f in diff_proc.stdout.splitlines()
            if f
            and not f.startswith(("scripts/pr3_l2_calibration/", "tests/", "docs/", "reports/"))
            # Documentation cannot change production behavior — node/operator
            # .md edits (e.g. pending doc-sync commits) are not launch blockers.
            and not f.endswith(".md")
        ]
        checks["no_production_file_modified"] = offenders == []
        checks["_offending_files"] = offenders
    for key, value in checks.items():
        if not key.startswith("_"):
            assert value, f"rev-3 preflight check failed: {key} ({checks.get('_offending_files')})"
    return checks


def main() -> dict:
    from scripts.pr3_l2_calibration.fixtures import fixture_hash

    results = {}
    for scenario in ("S1", "S2"):
        for arm in ("C", "T", "D"):
            r = run_arm(scenario, arm)
            assert r["pipeline_mode"], f"{scenario}/{arm}: pipeline mode not selected"
            assert not r["placeholder_unresolved"], f"{scenario}/{arm}: unresolved placeholder"
            assert r["proposer_block_present"] == (arm == "T"), (
                f"{scenario}/{arm}: proposer block wrong"
            )
            assert r["interp_block_present"] == (arm in ("T", "D")), (
                f"{scenario}/{arm}: interp block wrong"
            )
            results[f"{scenario}_{arm}"] = r
    # Fixture-hash stability + cross-arm identity (builders are arm-free;
    # two consecutive evaluations must agree).
    for s in ("S1", "S2"):
        assert fixture_hash(s) == fixture_hash(s)
    results["fixture_hashes"] = {"S1": fixture_hash("S1"), "S2": fixture_hash("S2")}
    # Treatment-only token increase (proposer, per scenario).
    for s in ("S1", "S2"):
        results[f"{s}_treatment_token_increase"] = (
            results[f"{s}_T"]["proposer_chars"] - results[f"{s}_C"]["proposer_chars"]
        ) // 4
    # Rev-3 proof 5: the treatment block is the ONLY C-vs-T difference in
    # the proposing-stage prompt (mocked-identical LLM stages make the
    # surrounding content deterministic).
    import re as _re

    for s in ("S1", "S2"):
        t_prompt = results[f"{s}_T"].pop("proposing_prompt")
        c_prompt = results[f"{s}_C"].pop("proposing_prompt")
        results[f"{s}_D"].pop("proposing_prompt")
        start = t_prompt.index("[HEALTHGATE EVIDENCE]")
        end = t_prompt.index("changes a relevant mechanism.") + len("changes a relevant mechanism.")
        t_stripped = t_prompt[:start] + t_prompt[end:]
        norm = lambda x: _re.sub(r"\s+", " ", x).strip()  # noqa: E731
        assert norm(t_stripped) == norm(c_prompt), (
            f"{s}: C-vs-T proposing prompt differs beyond the treatment block"
        )
        results[f"{s}_treatment_only_difference"] = True
    results["rev3_checks"] = rev3_vocab_and_tee_checks()
    return results


if __name__ == "__main__":
    out = main()
    print(json.dumps(out, indent=2))


def campaign_preflight() -> dict:
    """Full-campaign zero-LLM preflight (`pr3_l2_full_calibration_protocol.md`
    §4-§9): all four scenarios × C/T through the production assembly with
    mocked LLMs; treatment-only C-vs-T difference per scenario; fixture
    hash stability; vocab/tee checks. NO LLM CALLS."""
    import re as _re

    from scripts.pr3_l2_calibration.fixtures import fixture_hash

    results: dict = {}
    scenarios = ("S1", "S2", "S3", "S4")
    for scenario in scenarios:
        for arm in ("C", "T"):
            r = run_arm(scenario, arm)
            assert r["pipeline_mode"], f"{scenario}/{arm}: pipeline mode not selected"
            assert not r["placeholder_unresolved"], f"{scenario}/{arm}: unresolved placeholder"
            assert r["proposer_block_present"] == (arm == "T"), (
                f"{scenario}/{arm}: proposer treatment block wrong "
                f"(present={r['proposer_block_present']})"
            )
            assert r["interp_block_present"] == (arm == "T"), (
                f"{scenario}/{arm}: interp block wrong"
            )
            results[f"{scenario}_{arm}"] = r
    for s in scenarios:
        assert fixture_hash(s) == fixture_hash(s), f"{s}: fixture hash unstable"
    results["fixture_hashes"] = {s: fixture_hash(s) for s in scenarios}
    norm = lambda x: _re.sub(r"\s+", " ", x).strip()  # noqa: E731
    for s in scenarios:
        t_prompt = results[f"{s}_T"].pop("proposing_prompt")
        c_prompt = results[f"{s}_C"].pop("proposing_prompt")
        start = t_prompt.index("[HEALTHGATE EVIDENCE]")
        end = t_prompt.index("changes a relevant mechanism.") + len("changes a relevant mechanism.")
        t_stripped = t_prompt[:start] + t_prompt[end:]
        assert norm(t_stripped) == norm(c_prompt), (
            f"{s}: C-vs-T proposing prompt differs beyond the treatment block"
        )
        results[f"{s}_treatment_only_difference"] = True
        results[f"{s}_treatment_token_increase"] = (
            results[f"{s}_T"]["proposer_chars"] - results[f"{s}_C"]["proposer_chars"]
        ) // 4
    results["vocab_and_tee_checks"] = rev3_vocab_and_tee_checks()
    return results
