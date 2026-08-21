"""Step 10 / P3 — C0: the full-coverage proposer prompt baselines.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p3_proposer_typed_evidence.md`` §7 C0 (this commit), §4.3 (the 18-key
serializer whose bytes these pin), §4.4 (the legacy adapter's parity target),
§4.5 (the D1/D2/D3 surfaces C4 is allowed to move), §4.6 (the required
secondary NEGATIVE assertion).

Why these goldens exist when PB-3 already exists
------------------------------------------------
PB-3 (``test_step00_prompt_goldens.py``) is the production proposer's byte
baseline and stays exactly as it is. But its fixture populates **10 of the 18**
whitelist keys and NONE of the seven prediction keys, carries no
``metric_identity``, no health evidence and no secondary metrics. Every one of
those absent fields is a field P3 moves onto a typed carrier — so a parity
claim resting on PB-3 alone would be green for surfaces it never renders.

These baselines close that gap along two axes at once:

* **FULL** — a REAL ``InterpretationOutput.model_dump()`` with every one of the
  30 proposer-read fields populated, the health evidence live, and REAL
  secondary metrics present upstream. Built from the schema rather than
  hand-written as a dict, so it cannot drift from the producer's actual shape.
* **ABSENT** — a legacy persisted artifact whose keys are MISSING, not empty.
  The whitelist filters on ``is not None`` (``ml_model_proposal_agent.py:1698``)
  and the CLI feeds exactly this kind of file, so "absent" and "present-but-
  empty" are different bytes and both must survive the migration.

The secondary fixture is what gives §4.6's negative assertion teeth: the
upstream dump carries a scored ``psnr``, a scored ``mae`` and a REFUSED third
metric, so "the proposer prompt contains none of them" is a claim about
suppression, not about an empty input.

Capture provenance: goldens captured at ``c5f95ff0`` (P3 implementation base,
clean tree) by ``tools``-free explicit developer act, per the Step-00 §17
policy — tests never write goldens.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ReasoningPipelineConfig
from agent.schemas.proposer_evidence import build_proposer_evidence
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from tests.helpers.golden import assert_golden
from tests.helpers.metric_fixtures import accuracy_like_spec, error_like_spec
from tests.unit.agent.ml_model_proposal_agent.test_step00_prompt_goldens import (
    _CannedProposerBridge,
    _LegacyCommitRecorder,
    fixture_proposal_input,
    pin_environment,
)

GOLDENS = Path(__file__).parent / "goldens"

#: A DAVIS-shaped LOWER-is-better run. Chosen deliberately over a TIDMAD-shaped
#: one: under ``lower`` a direction mistake in the C2 clamp migration or the C4
#: authoring grammar produces visibly WRONG bytes, whereas under ``higher`` it
#: reproduces today's (accidentally correct) output. The values are the P2a C4
#: DAVIS fixture's, so the two modules describe the same imagined run.
LOWER_IDENTITY_ID = "fixture_mse"

_SCORE_TABLE_MD = "| file | score |\n|---|---|\n| 0 | **0.0174** |\n"


def _fixture_score_rows() -> list[dict]:
    """One row per file in the DECLARED topology, generated deterministically.

    ``ScoreComparisonTable`` validates the row count against
    ``resolve_dataset_profile().dataset.num_files`` (``score_table.py:239-251``),
    so a two-row stub is not a production-shaped table. Generating them keeps
    the fixture honest without 20 hand-written literals, and the values are a
    fixed arithmetic ramp so the dump is byte-stable across runs.
    """
    from execute_tools.dataset_config import resolve_dataset_profile

    num_files = resolve_dataset_profile().dataset.num_files
    # Sigma linear_weight must round-trip to 1.0 within 1e-9 (score_table.py:256-280).
    weight = 1.0 / num_files
    return [
        {
            "file_index": i,
            "raw_baseline": 0.04 + i * 0.001,
            "ground_truth": 0.0,
            "model": 0.017 + i * 0.0001,
            "gain_vs_raw": 0.023 - i * 0.0009,
            "headroom_vs_gt": 0.017 + i * 0.0001,
            "linear_weight": weight,
            "impact_score": 0.5 + i * 0.01,
        }
        for i in range(num_files)
    ]


def production_whitelist_keys() -> tuple[str, ...]:
    """The LIVE 18-key whitelist, read out of production source by AST.

    Deliberately not a copy of the tuple: a test-local list would let the
    fixture stay "complete" against a stale expectation while production
    dropped a key. C0 read it out of ``_run_pipeline``'s inline comprehension
    by AST; C2 gave the tuple a name in the rendering module, so this now
    imports that constant — the same live source, reached the obvious way once
    production has a name for it. The caller's length assertion still fails if
    the whitelist ever changes size.
    """
    from nodes.ml_model_proposal_agent.evidence_rendering import INTERPRETATION_SUMMARY_KEYS

    return INTERPRETATION_SUMMARY_KEYS


def full_coverage_interpretation() -> dict:
    """Every proposer-read field populated, dumped from the REAL schema.

    Populating all 18 whitelist keys is the point: the seven prediction keys
    and ``vocab_diversity_ratio`` are pinned by nothing today, so C2's
    serializer could drop them and every existing test would stay green.
    """
    psnr = accuracy_like_spec("fixture_psnr")
    mae = error_like_spec("fixture_mae")
    refused = error_like_spec("fixture_refused_secondary")
    output = InterpretationOutput(
        # --- identity / provenance (P2a) ---
        metric_identity={"metric_id": LOWER_IDENTITY_ID, "direction": "lower"},
        # --- required core ---
        model_types=["step00_alpha_net", "step00_beta_net", "step00_gamma_net"],
        model_descriptions={
            "step00_alpha_net": "Fixture alpha.",
            "step00_beta_net": "Fixture beta.",
            "step00_gamma_net": "Fixture gamma.",
        },
        total_experiments=7,
        key_findings=["beta recovers the low band best.", "gamma is the weakest of the three."],
        bottlenecks=["Low-frequency recovery is the binding limit."],
        take_home_message="Target low-frequency recovery next.",
        # --- per-model evidence (lower is better: beta best, gamma worst) ---
        per_model_best={
            "step00_alpha_net": 0.0174,
            "step00_beta_net": 0.0172,
            "step00_gamma_net": 0.0210,
        },
        per_model_best_valid={
            "step00_alpha_net": 0.0174,
            "step00_beta_net": 0.0172,
            "step00_gamma_net": 0.0210,
        },
        per_model_raw_best_health_validity={
            "step00_alpha_net": "valid",
            "step00_beta_net": "valid",
            "step00_gamma_net": "invalid",
        },
        per_model_worst={
            "step00_alpha_net": 0.0231,
            "step00_beta_net": 0.0198,
            "step00_gamma_net": 0.0402,
        },
        per_model_score_tables={
            "step00_alpha_net": {
                "rows": _fixture_score_rows(),
                "aggregate": {
                    "raw_baseline_scalar": 0.0402,
                    "ground_truth_scalar": 0.0,
                    "model_scalar": 0.0174,
                    "percent_of_ceiling_log": 56.7,
                    "num_sampled_files": 1,
                },
                "s_max_global": 0.0402,
                "reference_source": "p3c0_fixture",
                "linear_weight_total": 1.0,
                "rendered_markdown": _SCORE_TABLE_MD,
            }
        },
        per_model_params={
            "step00_alpha_net": 1_200_000,
            "step00_beta_net": 900_000,
            "step00_gamma_net": 2_400_000,
        },
        per_model_training_segments={
            "step00_alpha_net": 4000,
            "step00_beta_net": 4000,
            "step00_gamma_net": 2000,
        },
        model_knowledge_cache={
            "step00_gamma_net": {
                "key_findings": "gamma overfits the high band.",
                "bottlenecks": "capacity",
                "score_trend": "flat",
                "strategy_assessment": "retire",
            }
        },
        # --- run-level scalars (legacy reader also reads best_valid + best_config) ---
        best_denoising_score=0.0172,
        best_valid_denoising_score=0.0174,
        worst_denoising_score=0.0402,
        best_config={"lr": 0.0005, "epochs": 1},
        # --- the seven prediction keys + vocabulary health (pinned by NOTHING today) ---
        scientific_accuracy={"confirmed_rate": 0.5, "refuted_rate": 0.25},
        cumulative_information_gain=2.5,
        prediction_outcomes_history={"confirmed": 2, "refuted": 1},
        prediction_outcomes_by_semantics={
            "metric_order_signsafe_v2": {"confirmed": 1, "refuted": 1, "partial": 0}
        },
        cumulative_information_gain_by_semantics={"metric_order_signsafe_v2": 1.5},
        prediction_pool_sizes={"legacy_v1": 3, "metric_order_signsafe_v2": 2},
        prediction_evaluation_semantics="metric_order_signsafe_v2",
        vocab_diversity_ratio=0.42,
        # --- HealthGate evidence (flag-gated rendering) ---
        per_model_round_health_counts={
            "step00_gamma_net": {"valid": 0, "invalid": 2, "unknown": 1},
        },
        per_model_collapse_fingerprints={
            "step00_gamma_net": [
                {
                    "check_name": "sample_dispersion_floor",
                    "signature": "p3c0_sig_flat",
                    "metrics": {"output_std_mv": 0.0102},
                    "human_readable": "output std collapsed below 1 mV",
                }
            ]
        },
        collapse_fingerprint_history={
            "step00_gamma_net": [
                {
                    "signature": "p3c0_sig_flat",
                    "check_name": "sample_dispersion_floor",
                    "metrics": {"output_std_mv": 0.0102},
                    "human_readable": "output std collapsed below 1 mV",
                    "occurrences": [
                        {
                            "iteration": 4,
                            "count": 2,
                            "source_exp_ids": ["gamma_iter_004_001", "gamma_iter_004_002"],
                        },
                        {"iteration": 6, "count": 1, "source_exp_ids": ["gamma_iter_006_001"]},
                    ],
                }
            ]
        },
        # --- REAL secondaries upstream: Q-P3-3's negative assertion needs teeth ---
        per_model_secondary_metrics={
            "step00_alpha_net": [
                {
                    "spec": psnr.model_dump(),
                    "result": {"metric_id": psnr.id, "direction": "higher", "scalar": 31.7},
                },
                {
                    "spec": mae.model_dump(),
                    "result": {"metric_id": mae.id, "direction": "lower", "scalar": 0.0091},
                },
            ],
            "step00_beta_net": [
                {
                    "spec": refused.model_dump(),
                    "refusal": {
                        "metric_id": refused.id,
                        "direction": "lower",
                        "verdict": {
                            "contract_id": "presence",
                            "failures": [
                                {"requirement": "deliverable", "detail": "no reference channel"}
                            ],
                        },
                    },
                }
            ],
        },
    )
    return output.model_dump(mode="json")


def legacy_absence_interpretation() -> dict:
    """A pre-09a persisted artifact: the optional keys are ABSENT, not empty.

    This is the shape the standalone CLI loads from disk for an old workspace.
    The whitelist's ``is not None`` filter and the legacy reader's ``.get``
    defaults are the only things standing between it and a crash, so it is the
    fixture that proves the typed projection's per-field absence semantics
    reproduce today's bytes exactly.
    """
    return {
        "model_types": ["step00_alpha_net", "step00_beta_net"],
        "model_descriptions": {
            "step00_alpha_net": "Fixture alpha.",
            "step00_beta_net": "Fixture beta.",
        },
        "total_experiments": 2,
        "key_findings": [],
        "bottlenecks": [],
        "take_home_message": "",
        "per_model_best_valid": {"step00_alpha_net": 0.0174, "step00_beta_net": 0.0172},
    }


def make_input(tmp_path, *, mode: str, interpretation: dict, health: bool):
    """The PB-3 pinned input with only the interpretation + health flag varied.

    There is now exactly ONE carrier to update. During C2 there were two, and
    this helper updated only the raw dict — so the node kept reading the PB-3
    fixture's evidence and rendered PB-3's candidates and score table under
    this module's fixture, caught by these very goldens. That was a small,
    exact instance of the defect the whole PR removes: while two carriers of
    one fact exist they can disagree, and the disagreement is silent. C3
    deleted the raw field, so it can no longer be written wrongly.
    """
    base = fixture_proposal_input(tmp_path, mode=mode)
    return base.model_copy(
        update={
            "interpretation_evidence": build_proposer_evidence(interpretation),
            "enable_structured_health_feedback": health,
        }
    )


def capture_pipeline(tmp_path, index_path: str, *, mode: str, interpretation: dict, health: bool):
    """Drive the REAL pipeline and return the boundary captures."""
    agent = MLModelProposalAgent(
        provider="openai",
        model_id="p3c0-capture",
        bridge_factory=_CannedProposerBridge,
        capability_index_path=index_path,
    )
    agent.run(make_input(tmp_path, mode=mode, interpretation=interpretation, health=health))
    return agent.bridge.captures


def capture_legacy(tmp_path, index_path: str, *, interpretation: dict, health: bool):
    """Drive the REAL legacy path and return its reasoning user prompt."""
    inp = make_input(tmp_path, mode="explore", interpretation=interpretation, health=health)
    inp = inp.model_copy(update={"reasoning_pipeline": ReasoningPipelineConfig(stages=[])})
    agent = MLModelProposalAgent(
        provider="openai",
        model_id="p3c0-capture",
        bridge_factory=_LegacyCommitRecorder,
        capability_index_path=index_path,
    )
    agent.run(inp)
    reasoning = [c for c in agent.bridge.captures if c[1] == "proposer.legacy_reasoning"]
    assert len(reasoning) == 1, "the legacy reasoning call must reach the boundary exactly once"
    return reasoning[0][3]


@pytest.fixture
def pinned_env(tmp_path, monkeypatch) -> str:
    return pin_environment(tmp_path, monkeypatch)


class TestTheFixtureItselfIsHonest:
    """A baseline built on a fixture nobody checked is a baseline of nothing."""

    def test_the_full_fixture_populates_every_whitelist_key(self) -> None:
        """All 18, not the 10 PB-3 happens to carry."""
        keys = production_whitelist_keys()
        assert len(keys) == 18, f"the production whitelist moved: {len(keys)} keys, {keys}"
        dump = full_coverage_interpretation()
        missing = [k for k in keys if dump.get(k) is None]
        assert missing == [], (
            "the full-coverage fixture leaves whitelist keys unpopulated, so the "
            f"serializer's handling of them stays unpinned: {missing}"
        )

    def test_the_full_fixture_carries_real_secondary_evidence(self) -> None:
        """§4.6's negative assertion must be about SUPPRESSION, not absence."""
        secondaries = full_coverage_interpretation()["per_model_secondary_metrics"]
        ids = {e["spec"]["id"] for entries in secondaries.values() for e in entries}
        assert ids == {"fixture_psnr", "fixture_mae", "fixture_refused_secondary"}
        states = {
            ("scored" if e.get("result") else "refused")
            for entries in secondaries.values()
            for e in entries
        }
        assert states == {"scored", "refused"}

    def test_the_absence_fixture_omits_keys_rather_than_emptying_them(self) -> None:
        """Absent and present-but-empty are different bytes downstream."""
        legacy = legacy_absence_interpretation()
        for key in ("per_model_best", "per_model_score_tables", "metric_identity"):
            assert key not in legacy

    def test_the_two_fixtures_declare_opposite_identity_states(self) -> None:
        """Anti-vacuity: the pair covers both branches of the Q-10-2 rule."""
        assert full_coverage_interpretation()["metric_identity"] == {
            "metric_id": LOWER_IDENTITY_ID,
            "direction": "lower",
        }
        assert "metric_identity" not in legacy_absence_interpretation()


class TestP3C0PipelineBaselines:
    """Pipeline prompt bytes on the FULL fixture — both modes."""

    @pytest.mark.parametrize("mode", ["explore", "exploit"])
    def test_system_prompts(self, tmp_path, pinned_env, mode: str) -> None:
        caps = capture_pipeline(
            tmp_path,
            pinned_env,
            mode=mode,
            interpretation=full_coverage_interpretation(),
            health=True,
        )
        assert [c[1] for c in caps] == [
            "proposer.comparison",
            "proposer.causal_reasoning",
            "proposer.proposing",
        ], "exact label sequence — a retry/correction call means the canned fixture drifted"
        for (_m, label, system, _user), stem in zip(
            caps, ["comparison", "causal", "proposing"], strict=True
        ):
            assert_golden(
                system,
                GOLDENS / f"p3c0_full_{stem}_{mode}_system.txt",
                surface=f"P3-C0 {label} system prompt ({mode}, full coverage)",
            )

    def test_user_prompts_are_mode_invariant(self, tmp_path, pinned_env) -> None:
        for mode in ("explore", "exploit"):
            caps = capture_pipeline(
                tmp_path,
                pinned_env,
                mode=mode,
                interpretation=full_coverage_interpretation(),
                health=True,
            )
            for (_m, label, _system, user), stem in zip(
                caps, ["comparison", "causal", "proposing"], strict=True
            ):
                assert_golden(
                    user,
                    GOLDENS / f"p3c0_full_{stem}_user.txt",
                    surface=f"P3-C0 {label} user prompt ({mode}, full coverage)",
                )

    def test_absence_fixture_user_prompt(self, tmp_path, pinned_env) -> None:
        """The whitelist's ``is not None`` filter, pinned on a real legacy dump."""
        caps = capture_pipeline(
            tmp_path,
            pinned_env,
            mode="explore",
            interpretation=legacy_absence_interpretation(),
            health=False,
        )
        assert_golden(
            caps[0][3],
            GOLDENS / "p3c0_absent_comparison_user.txt",
            surface="P3-C0 comparison user prompt (legacy absence)",
        )


class TestP3C0LegacyBaselines:
    """The legacy reasoning USER prompt — the whole legacy interpretation reader.

    PB-4 pins the legacy COMMIT prompts and S1-E the legacy reasoning SYSTEM
    prompt; the reasoning USER prompt — 26 of the node module's 40 raw reads —
    was goldened only by ``test_health_prompt_parity.py`` on ONE fixture with
    the health flag OFF. C3 rewrites this renderer entirely, so it needs a
    baseline on both fixtures and with the flag ON.
    """

    def test_full_coverage(self, tmp_path, pinned_env) -> None:
        assert_golden(
            capture_legacy(
                tmp_path, pinned_env, interpretation=full_coverage_interpretation(), health=True
            ),
            GOLDENS / "p3c0_full_legacy_reasoning_user.txt",
            surface="P3-C0 legacy reasoning user prompt (full coverage)",
        )

    def test_legacy_absence(self, tmp_path, pinned_env) -> None:
        assert_golden(
            capture_legacy(
                tmp_path, pinned_env, interpretation=legacy_absence_interpretation(), health=False
            ),
            GOLDENS / "p3c0_absent_legacy_reasoning_user.txt",
            surface="P3-C0 legacy reasoning user prompt (legacy absence)",
        )


class TestQP3_3SecondariesAreAbsentFromEveryProposerPrompt:
    """§4.6, the FROZEN negative assertion — asserted where the temptation is real.

    The upstream dump carries a scored PSNR, a scored MAE and a refused third
    metric. None of their ids, values or refusal payloads may appear in any
    proposer prompt, on either entrypoint. This test is written in C0 — while
    the proposer still reads the raw dict — so it pins the CURRENT (correct)
    behaviour and would catch C1-C4 accidentally starting to project them.
    """

    FORBIDDEN = (
        "fixture_psnr",
        "fixture_mae",
        "fixture_refused_secondary",
        "31.7",
        "0.0091",
        "secondary_metric",
        "no reference channel",
    )

    def test_pipeline_prompts_carry_no_secondary_evidence(self, tmp_path, pinned_env) -> None:
        caps = capture_pipeline(
            tmp_path,
            pinned_env,
            mode="explore",
            interpretation=full_coverage_interpretation(),
            health=True,
        )
        for _m, label, system, user in caps:
            for token in self.FORBIDDEN:
                assert token not in system, f"{label} system prompt leaked {token!r}"
                assert token not in user, f"{label} user prompt leaked {token!r}"

    def test_legacy_prompt_carries_no_secondary_evidence(self, tmp_path, pinned_env) -> None:
        user = capture_legacy(
            tmp_path, pinned_env, interpretation=full_coverage_interpretation(), health=True
        )
        for token in self.FORBIDDEN:
            assert token not in user, f"legacy reasoning prompt leaked {token!r}"

    def test_the_probe_would_notice(self, tmp_path, pinned_env) -> None:
        """Anti-vacuity: the forbidden tokens ARE present in the input.

        Without this, deleting the secondaries from the fixture would leave
        the two assertions above passing for the wrong reason.
        """
        import json

        dump = json.dumps(full_coverage_interpretation())
        for token in self.FORBIDDEN:
            if token == "secondary_metric":
                # Skipped only because it is a KEY-name fragment rather than a
                # value: `per_model_secondary_metrics` puts it in the dump, so
                # probing it here would prove nothing about suppression. The
                # prompt assertions above still check it.
                continue
            assert token in dump, (
                f"{token!r} is not in the upstream fixture, so asserting its "
                "absence from the prompt proves nothing"
            )
