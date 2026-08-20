"""Step 09b Gate 1 — the interpreter under a REAL LLM with re-owned prompts.

Dual-mode (design §13). PSEUDO mode is the default and CI-external: it pins
the exact, input-deterministic call manifest and REHEARSES the behavioural
probes against planted synthetic outputs, so the probes are proven to bite
before a single real call is spent. REAL mode (`--real-api-call`) is the
Gate itself.

What only a real LLM can answer (§13.1): given the recomposed prompts, does
the model still produce schema-valid structured interpretation, designate
the correct best model in BOTH direction/sign regimes, and refrain from
fabricating evidence the input does not contain? The prompt-CONSTRUCTION
half is deterministic and owned by the C2/C3/C5 unit suites; it is asserted
here too, but it is not the residual claim.

Case A — TIDMAD, from the preserved `step07b_gate1_postrefactor` artifact
(READ-ONLY; never written). Its outputs predate 09a and carry no
`metric_spec`, so the harness STAMPS the shipped TIDMAD spec as
test-fixture construction (Q-09b-2 / the Q-09a-7 precedent): production
outputs are untouched, no production derivation site is added, and the
records' own `metric_result` identity must still AGREE with the stamped
spec or the input contract refuses.

Case B — DAVIS-shaped, two fixture-authored models, STRICTLY dominance
ordered on both axes so any designation of the dominated model is an
unambiguous inversion.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks
from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import (
    InterpretationInput,
    MetricIdentity,
    ModelRunSummary,
    SecondaryMetricEvidence,
)
from execute_tools.evaluation_metric import metric_spec_from_declaration
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import (
    ResultInterpretationAgent,
    tuning_output_to_model_run_summary,
)
from tests.helpers.metric_fixtures import shipped_spec

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = Path("/home/klz/Data/SIDEREIS_DATA/step07b_gate1_postrefactor")
DAVIS_DECLARED = REPO_ROOT / "examples/davis_future_prediction/declared"

#: The frozen call manifest (design §13.3), input-deterministic per §2.3.
EXPECTED_LABELS_TIDMAD = ["interpretation.per_model", "interpretation.synthesis"]
EXPECTED_LABELS_DAVIS = [
    "interpretation.per_model",
    "interpretation.per_model",
    "interpretation.synthesis",
]
EXPECTED_TOTAL_CALLS = 5

#: DAVIS dominance fixture (§13.2-B): model 1 is better on EVERY round and
#: has fewer parameters, so no axis can justify designating model 2.
DAVIS_BETTER = "davis_temporal_unet_small"
DAVIS_WORSE = "davis_wide_convlstm"
DAVIS_BETTER_ROUNDS = [0.0172, 0.0170]
DAVIS_WORSE_ROUNDS = [0.0185, 0.0190]

TIDMAD_BETTER = "bidirectional_gated_tcn"
TIDMAD_WORSE = "wavenet24_fullspectrum_ce_coldstart"

#: Fields the designation matcher reads. All are LLM-authored synthesis
#: output; `take_home_message` is required non-empty by the prompt contract.
DESIGNATION_FIELDS = ("take_home_message", "key_findings", "efficiency_comparison")
#: Prose fields the fabrication/leak probes read.
PROSE_FIELDS = ("take_home_message", "key_findings", "bottlenecks")
SUPERLATIVES = (
    "best",
    "better",
    "strongest",
    "superior",
    "outperform",
    "leading",
    "leader",
    "top performer",
    "winner",
)
#: P-B2's leak set: tokens that may only appear when a task SUPPLIES the
#: guidance carrying them. (TIDMAD does; a block-less task must not.)
LEAK_TOKENS = ("impact_score", "linear_weight", "log-of-mean", "psd segment")
#: P-A2's fabrication test: a DESIGNATED file index.
_FILE_INDEX = re.compile(r"file[\s_\-]*(?:index)?[\s#]*\d+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Probes (shared by the pseudo rehearsal and the real Gate)
# ---------------------------------------------------------------------------


#: Sentence boundary: a period FOLLOWED BY whitespace/end, never one inside a
#: decimal. Scores in this domain are written `-2.3322708898096955`, so a
#: naive `.split(".")` orphans the model name from its verdict — which is
#: exactly how the first Gate run mis-read a CORRECT designation (F-09b-13).
_SENTENCE_SPLIT = re.compile(r"(?<!\d)\.(?:\s|$)|\n")


def _sentences(payload: Any) -> list[str]:
    """Flatten an LLM field into sentences (decimal-safe)."""
    items = payload if isinstance(payload, list) else [payload]
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        out += [chunk.strip() for chunk in _SENTENCE_SPLIT.split(item) if chunk and chunk.strip()]
    return out


def probe_designation(
    digest: dict, *, better: str, worse: str, better_score: str | None = None
) -> tuple[bool, str]:
    """P-A1 / P-B1: the structured output must designate `better`, never
    `worse`, and must designate SOMETHING.

    Evidence-grounded rather than a natural-language classifier (frozen
    §13.4): a sentence counts as designating when it carries a superlative
    AND a model NAME. A sentence is an INVERSION only when it names `worse`
    while referencing the winner in NO form — neither its name nor its score
    string. That last clause is not a loophole, it is the real output: the
    model wrote "even the better cross-model score of -2.3322708898096955 is
    still far from 0.0000", referencing the winner by its NUMBER (F-09b-15).
    Attributing that sentence to `worse` would be the classifier error, not
    the model's.
    """
    designating: list[str] = []
    for field in DESIGNATION_FIELDS:
        for sentence in _sentences(digest.get(field)):
            low = sentence.lower()
            if any(word in low for word in SUPERLATIVES) and (
                better.lower() in low or worse.lower() in low
            ):
                designating.append(sentence)
    if not designating:
        return False, "no sentence designates a best/better model by name"
    inverted = [
        s
        for s in designating
        if worse.lower() in s.lower()
        and better.lower() not in s.lower()
        and not (better_score and better_score in s)
    ]
    if inverted:
        return False, f"designated the WORSE model: {inverted[:2]}"
    return True, f"{len(designating)} designating sentence(s), none designating {worse}"


def probe_no_file_index_fabrication(digest: dict, fields: tuple[str, ...]) -> tuple[bool, str]:
    """P-A2 (frozen §13.4): no file-INDEX designation.

    The TIDMAD Gate artifact carries NO score table and NO file-index token in
    any of its prose (verified at design time, §2.8), so any *designated* file
    is invented. Naming the ABSENCE of per-file evidence — which is what the
    migrated guidance asks for when the table is missing — is the honest
    behaviour this probe must ACCEPT, not flag (F-09b-14).
    """
    offenders: list[str] = []
    for field in fields:
        for match in _FILE_INDEX.finditer(json.dumps(digest.get(field) or "")):
            offenders.append(match.group(0))
    if offenders:
        return False, f"designated file indices the input never contained: {offenders[:4]}"
    return True, "no fabricated file-index designation"


def probe_no_task_science_leak(digest: dict, fields: tuple[str, ...]) -> tuple[bool, str]:
    """P-B2 (frozen §13.4): a task supplying NO blocks must produce no
    TIDMAD-specific framing."""
    offenders: list[str] = []
    for field in fields:
        text = json.dumps(digest.get(field) or "").lower()
        offenders += [token for token in LEAK_TOKENS if token in text]
    if offenders:
        return False, f"TIDMAD science leaked into a block-less task: {sorted(set(offenders))}"
    return True, "no TIDMAD science leak"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _require_artifact() -> None:
    if not ARTIFACT.exists():
        pytest.skip(
            f"Gate-1 case A needs the preserved artifact at {ARTIFACT} "
            "(machine-local, read-only); it is not present on this host."
        )


def _tidmad_input(workspace: Path) -> InterpretationInput:
    _require_artifact()
    run_output = json.loads(
        (
            ARTIFACT / "iter_002/iteration_002/bidirectional_gated_tcn/run_output_iter_002.json"
        ).read_text()
    )
    digest = json.loads(
        (ARTIFACT / "iter_002/iteration_002/interpretation_iter_002.json").read_text()
    )
    proposal = json.loads(
        (
            ARTIFACT
            / "iter_002/iteration_002/attempt_001_bidirectional_gated_tcn/proposal_iter_002.json"
        ).read_text()
    )
    # Test-fixture stamping (Q-09b-2): the artifact predates 09a's transport.
    run_output["metric_spec"] = shipped_spec().model_dump()
    output = HyperparamTuningOutput.model_validate(run_output)
    summary = tuning_output_to_model_run_summary(output, order=MetricOrder(output.metric_spec))
    return InterpretationInput(
        summaries=[summary],
        model_knowledge_cache=digest["model_knowledge_cache"],
        metric_spec=output.metric_spec,
        task_blocks=load_interpretation_task_blocks(),
        task_description="full-spectrum 1-D time-series denoising of SQUID data.",
        runtime_vocab=digest["runtime_vocab"],
        previous_proposal=proposal,
        prediction_outcomes_history=digest["prediction_outcomes_history"],
        cumulative_information_gain=digest["cumulative_information_gain"],
        iteration=3,
        storage={"backend": "local", "local": {"workspace": str(workspace), "run_name": "gate1a"}},
    )


def _davis_summary(model_type: str, rounds: list[float], params: int) -> ModelRunSummary:
    spec = metric_spec_from_declaration(
        json.loads((DAVIS_DECLARED / "metric_mse.json").read_text())
    )
    psnr = metric_spec_from_declaration(
        json.loads((DAVIS_DECLARED / "metric_psnr.json").read_text())
    )
    mae = metric_spec_from_declaration(json.loads((DAVIS_DECLARED / "metric_mae.json").read_text()))
    from execute_tools.evaluation_metric import MetricResult

    return ModelRunSummary(
        model_type=model_type,
        run_name="gate1b",
        status="completed",
        completed_rounds=len(rounds),
        best_denoising_score=min(rounds),
        best_valid_denoising_score=min(rounds),
        worst_denoising_score=max(rounds),
        round_scores=list(rounds),
        round_conclusions=[f"round {i + 1} of {model_type}" for i in range(len(rounds))],
        best_model_params=params,
        metric_identity=MetricIdentity(metric_id=spec.id, direction=spec.direction),
        secondary_metrics=[
            SecondaryMetricEvidence(
                spec=psnr,
                result=MetricResult(
                    metric_id=psnr.id, direction=psnr.direction, scalar=round(1.0 / min(rounds), 2)
                ),
            ),
            SecondaryMetricEvidence(spec=mae),
        ],
        model_description=f"{model_type}: an 8->4 future-frame regression model.",
    )


def _davis_input(workspace: Path) -> InterpretationInput:
    spec = metric_spec_from_declaration(
        json.loads((DAVIS_DECLARED / "metric_mse.json").read_text())
    )
    return InterpretationInput(
        summaries=[
            _davis_summary(DAVIS_BETTER, DAVIS_BETTER_ROUNDS, params=1_200_000),
            _davis_summary(DAVIS_WORSE, DAVIS_WORSE_ROUNDS, params=4_800_000),
        ],
        metric_spec=spec,
        # No task blocks: a task that supplies no guidance must inherit none.
        task_description=(
            "DAVIS 2017 future-frame prediction: given 8 RGB frames, predict the next 4."
        ),
        iteration=1,
        enable_structured_health_feedback=True,
        storage={"backend": "local", "local": {"workspace": str(workspace), "run_name": "gate1b"}},
    )


# ---------------------------------------------------------------------------
# Recording bridges
# ---------------------------------------------------------------------------


class _RecordingBridge:
    """Wraps the real bridge (or canned responses) and records every call."""

    def __init__(self, inner=None, canned: dict[str, dict] | None = None):
        self._inner = inner
        self._canned = canned or {}
        self.calls: list[dict[str, Any]] = []

    def generate(self, system: str, user: str, label: str = "", **kwargs) -> dict:
        response = (
            self._inner.generate(system, user, label=label, **kwargs)
            if self._inner is not None
            else dict(self._canned[label])
        )
        self.calls.append({"label": label, "system": system, "user": user, "response": response})
        return response

    def emit_marker(self, **kwargs) -> None:
        self.calls.append({"label": "marker", "extra": kwargs})


def _bridge_factory(bridge: _RecordingBridge):
    """Bind the bridge EAGERLY (the repo's B023 default-arg locking rule, in
    the form a `**kwargs` factory signature allows)."""

    def factory(**_kwargs):
        return bridge

    return factory


def _canned(better: str) -> dict[str, dict]:
    """A CORRECT synthetic response set — the rehearsal's green control."""
    return {
        "interpretation.per_model": {
            "key_findings": ["scores improved across rounds"],
            "bottlenecks": ["capacity ceiling"],
            "best_config_analysis": "n/a",
            "score_trend": "improving",
            "per_file_analysis": "No per-sample evidence is available for this run.",
            "data_sensitivity": "n/a",
            "efficiency_assessment": "n/a",
            "strategy_assessment": "n/a",
        },
        "interpretation.synthesis": {
            "key_findings": [f"{better} is the better model on the bound metric"],
            "bottlenecks": ["shared capacity ceiling"],
            "per_file_comparison": "No per-sample evidence is available.",
            "efficiency_comparison": f"{better} achieves the best score per parameter",
            "take_home_message": f"{better} is the strongest candidate; iterate on it next.",
        },
    }


# ---------------------------------------------------------------------------
# PSEUDO mode — the manifest pin and the probe rehearsal
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
class TestPseudoManifestAndProbeRehearsal:
    def test_the_tidmad_call_manifest_is_the_frozen_two(self, tmp_path):
        bridge = _RecordingBridge(canned=_canned(TIDMAD_BETTER))
        agent = ResultInterpretationAgent(bridge_factory=lambda **_kw: bridge)
        agent.run(_tidmad_input(tmp_path))
        labels = [c["label"] for c in bridge.calls if c["label"] != "marker"]
        assert labels == EXPECTED_LABELS_TIDMAD, labels

    def test_the_davis_call_manifest_is_the_frozen_three(self, tmp_path):
        bridge = _RecordingBridge(canned=_canned(DAVIS_BETTER))
        agent = ResultInterpretationAgent(bridge_factory=lambda **_kw: bridge)
        agent.run(_davis_input(tmp_path))
        labels = [c["label"] for c in bridge.calls if c["label"] != "marker"]
        assert labels == EXPECTED_LABELS_DAVIS, labels

    def test_the_total_is_the_frozen_five(self, tmp_path):
        assert len(EXPECTED_LABELS_TIDMAD) + len(EXPECTED_LABELS_DAVIS) == EXPECTED_TOTAL_CALLS

    def test_the_designation_probe_accepts_a_correct_output(self):
        ok, why = probe_designation(
            _canned(DAVIS_BETTER)["interpretation.synthesis"],
            better=DAVIS_BETTER,
            worse=DAVIS_WORSE,
        )
        assert ok, why

    def test_the_designation_probe_rejects_an_inverted_output(self):
        """The rehearsal that makes the Gate meaningful."""
        inverted = dict(_canned(DAVIS_WORSE)["interpretation.synthesis"])
        ok, why = probe_designation(inverted, better=DAVIS_BETTER, worse=DAVIS_WORSE)
        assert not ok and "WORSE" in why, why

    def test_an_inversion_is_still_red_when_the_winner_score_is_supplied(self):
        """The score clause must not become a loophole: a sentence that
        designates the loser is RED even when the winner's score is known."""
        inverted = dict(_canned(DAVIS_WORSE)["interpretation.synthesis"])
        ok, why = probe_designation(
            inverted, better=DAVIS_BETTER, worse=DAVIS_WORSE, better_score="0.017"
        )
        assert not ok and "WORSE" in why, why

    def test_a_sentence_referencing_the_winner_by_score_is_not_an_inversion(self):
        """F-09b-15, from the real Gate output."""
        sentence = (
            "The established prior finding that davis_wide_convlstm remains far below the "
            "reference is confirmed: even the better cross-model score of 0.0170 is still short."
        )
        ok, _ = probe_designation(
            {"key_findings": [sentence]},
            better=DAVIS_BETTER,
            worse=DAVIS_WORSE,
            better_score="0.0170",
        )
        assert ok

    def test_the_designation_probe_rejects_silence(self):
        ok, why = probe_designation(
            {"take_home_message": "Results are inconclusive.", "key_findings": []},
            better=DAVIS_BETTER,
            worse=DAVIS_WORSE,
        )
        assert not ok and "no sentence" in why, why

    def test_the_file_index_probe_rejects_an_invented_designation(self):
        ok, why = probe_no_file_index_fabrication(
            {"per_file_comparison": "File 17 shows the largest remaining lever."},
            ("per_file_comparison",),
        )
        assert not ok, why

    def test_the_file_index_probe_accepts_naming_the_absence(self):
        """The behaviour the migrated guidance actually asks for when no
        table exists — and the case the first Gate run wrongly flagged."""
        ok, why = probe_no_file_index_fabrication(
            {
                "per_file_comparison": (
                    "There is no per-file Impact_Score evidence for either model, "
                    "so no lever can be named."
                )
            },
            ("per_file_comparison",),
        )
        assert ok, why

    def test_the_leak_probe_rejects_tidmad_science_in_a_blockless_task(self):
        ok, why = probe_no_task_science_leak(
            {"take_home_message": "Rank by Impact_Score descending."}, ("take_home_message",)
        )
        assert not ok, why

    def test_the_decimal_safe_splitter_keeps_a_score_sentence_whole(self):
        """F-09b-13: the defect that made a CORRECT designation read as an
        inversion."""
        sentence = (
            "The best observed score is from model_a at -2.3322708898096955, "
            "outperforming model_b at -2.4310203852971433."
        )
        # One sentence in, one out — the decimals no longer split it. (The
        # trailing period survives because it too follows a digit; harmless,
        # and asserted as-is rather than assumed away.)
        assert _sentences(sentence) == [sentence]
        ok, _ = probe_designation({"key_findings": [sentence]}, better="model_a", worse="model_b")
        assert ok


# ---------------------------------------------------------------------------
# REAL mode — Gate 1
# ---------------------------------------------------------------------------


@pytest.mark.real_run
class TestGate1RealLLM:
    def test_gate1(self, tmp_path):
        from agent.llm_bridge import LLMBridge

        config = json.loads((REPO_ROOT / "llm_configs/openai_tiered_pro.json").read_text())
        evidence_root = Path(
            os.environ.get(
                "STEP09B_GATE1_EVIDENCE",
                f"/home/klz/Data/SIDEREIS_DATA/step09b_gate1_evidence_{datetime.now(UTC):%Y%m%d}",
            )
        )
        evidence_root.mkdir(parents=True, exist_ok=True)
        results: dict[str, Any] = {"config": config["interpret"], "cases": {}}

        for case, build, labels, better, worse in (
            ("A_tidmad", _tidmad_input, EXPECTED_LABELS_TIDMAD, TIDMAD_BETTER, TIDMAD_WORSE),
            ("B_davis", _davis_input, EXPECTED_LABELS_DAVIS, DAVIS_BETTER, DAVIS_WORSE),
        ):
            workspace = tmp_path / case
            workspace.mkdir()
            bridge = _RecordingBridge(inner=LLMBridge(**config["interpret"]))
            # Default-arg binding: the loop variable must not be captured
            # late (the repo's B023 rule).
            agent = ResultInterpretationAgent(bridge_factory=_bridge_factory(bridge))
            output = agent.run(build(workspace))
            digest = json.loads(output.model_dump_json())
            observed = [c["label"] for c in bridge.calls if c["label"] != "marker"]

            synthesis = next(
                (c["response"] for c in bridge.calls if c["label"] == "interpretation.synthesis"),
                {},
            )
            checks = {
                "manifest": (observed == labels, f"observed {observed}"),
                "not_degraded": (digest["is_degraded"] is False, "is_degraded"),
                "designation": probe_designation(
                    {**synthesis, **{k: digest.get(k) for k in DESIGNATION_FIELDS}},
                    better=better,
                    worse=worse,
                    # The winner's score, read from the DIGEST's deterministic
                    # per-model map — never hand-written here.
                    better_score=str(digest.get("per_model_best", {}).get(better)),
                ),
                # Per the frozen §13.4 split: A owns non-fabrication of file
                # indices (its input has no table); B owns no-leak (it supplies
                # no blocks, so TIDMAD framing must not appear at all).
                "no_fabrication": (
                    probe_no_file_index_fabrication(digest, PROSE_FIELDS)
                    if case == "A_tidmad"
                    else probe_no_task_science_leak(digest, PROSE_FIELDS)
                ),
            }
            (evidence_root / f"{case}_digest.json").write_text(json.dumps(digest, indent=2))
            (evidence_root / f"{case}_transcript.json").write_text(
                json.dumps(bridge.calls, indent=2, default=str)
            )
            results["cases"][case] = {
                "labels": observed,
                "checks": {k: {"pass": v[0], "detail": v[1]} for k, v in checks.items()},
            }

        (evidence_root / "gate1_result.json").write_text(json.dumps(results, indent=2))
        failures = [
            f"{case}/{name}: {info['detail']}"
            for case, data in results["cases"].items()
            for name, info in data["checks"].items()
            if not info["pass"]
        ]
        assert not failures, f"Gate 1 FAIL — evidence at {evidence_root}:\n" + "\n".join(failures)
