"""The formal-LAUNCH decision: is there evidence worth spending a round on?

V20 PR D, checkpoint D-C3. This module owns the launch question end to
end. The *authority* question — may a formal result inform science — is
D-C2a/b's and is deliberately absent here (§16.D).

**The defect.** `_should_skip_formal` used to read

    winner is not None and winner.score < threshold

so `winner is None` returned `False` and the formal round RAN. Absence of
evidence was indistinguishable from sufficient evidence. `force_formal_round`
does not rescue this and is not an override: it defaults to `True` and means
*the last round of every iteration runs in formal mode regardless of what the
planner picked* (§16.A). Formal on the final round is therefore the DEFAULT
path and the skip gate is the ONLY thing that can prevent it — so an inert
skip gate let every zero-evidence iteration spend a full formal round.

**The second defect, from the other direction.** With no restored incumbent
the reference was `None` and BOTH gates fell silent, so an excellent first
trial was still blocked by the formal time budget — the v15 failure
`8f1cf528` was written to fix, reappearing because the reference was absent
rather than because the gate was wrong. §16.C bootstraps the reference to
`-inf` instead, which arms both gates on a fresh chain.

The frozen policy (§16.D):

    winner = _best_trial_winner(...)      # the single source
    winner is None                -> skip formal
    winner.score <  ref + skip Δ  -> skip formal
    winner.score >= ref + bypassΔ -> bypass the formal time budget
    otherwise                     -> ordinary time-budget decision
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _apply_mode_override_chain,
    _best_trial_winner,
    _json_safe_reference,
    _resolve_formal_comparison_thresholds,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
)

BLOCKING_IDS = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)

# The production posture measured in §16.B: switch ON, skip Δ 0.0,
# bypass Δ 0.5, restored incumbent 10.0 → thresholds 10.0 / 10.5.
INCUMBENT = 10.0
SKIP_DELTA = 0.0
BYPASS_DELTA = 0.5
SKIP_T = 10.0
BYPASS_T = 10.5


def _trial(exp_id: str, score: float, *, valid: bool = True) -> dict:
    """A completed trial record. ``valid=False`` fails every blocking-role
    gate, which is what makes it ineligible to be the winner."""
    return {
        "exp_id": exp_id,
        "status": "success",
        "denoising_score": score,
        "is_trial": True,
        "health_gate_results": [
            {
                "gate_name": gate_id,
                "execution_status": "passed" if valid else "failed",
                "check_passed": valid,
                "would_invalidate_under_production_policy": not valid,
                "resolved_action": "continue",
            }
            for gate_id in BLOCKING_IDS
        ],
        "params": {
            "model_config": {"depth": 2},
            "train_config": {"lr": 0.001, "epochs": 1, "batch_size": 2},
            "loss_config": {"loss_type": "focal"},
        },
        "memory": {"time_mode": "trial", "round_index": 1},
    }


class Launch(dict):
    """The full launch verdict, so every row can assert every output."""

    __getattr__ = dict.__getitem__  # type: ignore[assignment]


def _launch(
    records: list[dict],
    *,
    incumbent: float | None = INCUMBENT,
    gates_enabled: bool = True,
    skip_delta: float = SKIP_DELTA,
    bypass_delta: float = BYPASS_DELTA,
) -> Launch:
    """Run the REAL production helpers in the REAL production order.

    Mirrors the tuner exactly: the incumbent is gated on the feature switch
    into ``_consumed_reference`` first (a flag-OFF run must not consume a
    reconstructed incumbent), the resolver runs once, the winner is
    resolved once, and both gates judge that same winner.
    """
    consumed_reference = incumbent if gates_enabled else None
    reference, skip_t, bypass_t, source = _resolve_formal_comparison_thresholds(
        reference_score=consumed_reference,
        skip_min_delta=skip_delta,
        bypass_min_delta=bypass_delta,
        gates_enabled=gates_enabled,
    )
    winner = _best_trial_winner(records)
    skip = _should_skip_formal(winner, threshold=skip_t, gates_enabled=gates_enabled)
    bypass = _should_bypass_formal_time_budget(winner, threshold=bypass_t)
    return Launch(
        winner=winner,
        winner_id=None if winner is None else winner["exp_id"],
        skip=skip,
        bypass=bypass,
        # §16.D's fourth branch: neither gate fired, so the round is
        # subject to the ordinary time-budget decision.
        ordinary_budget=not skip and not bypass,
        reference=reference,
        source=source,
        skip_threshold=skip_t,
        bypass_threshold=bypass_t,
        persisted={
            "formal_reference_score": _json_safe_reference(reference),
            "formal_comparison_reference_source": source,
            "resolved_skip_formal_threshold": _json_safe_reference(skip_t),
            "resolved_bypass_formal_threshold": _json_safe_reference(bypass_t),
        },
    )


NEG_INF = float("-inf")

# (id, records, kwargs, winner_id, skip, bypass, ordinary, ref, source, skip_t, bypass_t)
MATRIX = [
    # ---- no evidence at all: the three shapes of "no winner" ----------
    (
        "1_no_trial_records",
        [],
        {},
        None,
        True,
        False,
        False,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
    (
        "2_all_trials_invalid",
        [_trial("bad_a", 99.0, valid=False), _trial("bad_b", 50.0, valid=False)],
        {},
        None,
        True,
        False,
        False,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
    (
        # The adversarial case: a single invalid trial scoring far above
        # BOTH thresholds. It must open neither gate, and the skip must
        # fire for lack of a winner rather than be suppressed by the 99.0.
        "3_invalid_trial_with_an_enormous_score",
        [_trial("collapsed", 99.0, valid=False)],
        {},
        None,
        True,
        False,
        False,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
    # ---- the bootstrap: a fresh chain with no restored incumbent ------
    (
        "4_valid_winner_with_no_incumbent",
        [_trial("first", 0.001)],
        {"incumbent": None},
        "first",
        False,
        True,
        False,
        NEG_INF,
        "negative_infinity_bootstrap",
        NEG_INF,
        NEG_INF,
    ),
    # ---- the numeric band, boundaries included ------------------------
    (
        "5_valid_winner_below_the_skip_threshold",
        [_trial("weak", 9.0)],
        {},
        "weak",
        True,
        False,
        False,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
    (
        # `<` not `<=`: exactly at the threshold the round RUNS.
        "6_valid_winner_exactly_at_the_skip_threshold",
        [_trial("at_skip", SKIP_T)],
        {},
        "at_skip",
        False,
        False,
        True,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
    (
        "7_valid_winner_between_the_thresholds",
        [_trial("middle", 10.2)],
        {},
        "middle",
        False,
        False,
        True,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
    (
        # `>=` not `>`: exactly at the threshold the budget IS bypassed.
        "8_valid_winner_exactly_at_the_bypass_threshold",
        [_trial("at_bypass", BYPASS_T)],
        {},
        "at_bypass",
        False,
        True,
        False,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
    (
        "9_valid_winner_above_the_bypass_threshold",
        [_trial("strong", 11.0)],
        {},
        "strong",
        False,
        True,
        False,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
    # ---- the feature switch: pre-V20 behaviour, still reachable -------
    (
        # THE BACKWARD-COMPATIBILITY ROW. Gates off, no valid winner, and
        # the formal round still runs exactly as it did before D-C3.
        "10_gates_disabled_with_no_valid_winner",
        [_trial("collapsed", 99.0, valid=False)],
        {"gates_enabled": False},
        None,
        False,
        False,
        True,
        None,
        "gates_disabled",
        None,
        None,
    ),
    (
        "10b_gates_disabled_with_a_valid_winner",
        [_trial("ignored", 99.0)],
        {"gates_enabled": False},
        "ignored",
        False,
        False,
        True,
        None,
        "gates_disabled",
        None,
        None,
    ),
    # ---- provenance: a real incumbent is never the bootstrap ----------
    (
        "11_restored_valid_formal_incumbent",
        [_trial("normal", 10.25)],
        {"incumbent": 10.0},
        "normal",
        False,
        False,
        True,
        INCUMBENT,
        "restored_valid_formal_incumbent",
        SKIP_T,
        BYPASS_T,
    ),
]


@pytest.mark.parametrize(
    (
        "records",
        "kwargs",
        "winner_id",
        "skip",
        "bypass",
        "ordinary",
        "reference",
        "source",
        "skip_t",
        "bypass_t",
    ),
    [pytest.param(*row[1:], id=row[0]) for row in MATRIX],
)
def test_the_launch_matrix(
    records, kwargs, winner_id, skip, bypass, ordinary, reference, source, skip_t, bypass_t
):
    """Every row asserts every output — winner identity, both gate
    decisions, ordinary-budget applicability, the effective reference and
    its provenance, both thresholds, and the JSON-safe persisted form."""
    result = _launch(records, **kwargs)

    assert result.winner_id == winner_id
    assert result.skip is skip
    assert result.bypass is bypass
    assert result.ordinary_budget is ordinary
    assert result.reference == reference
    assert result.source == source
    assert result.skip_threshold == skip_t
    assert result.bypass_threshold == bypass_t

    # Whatever the row, the persisted form must survive strict JSON.
    encoded = json.dumps(result.persisted, allow_nan=False)
    assert "Infinity" not in encoded and "NaN" not in encoded
    assert json.loads(encoded)["formal_comparison_reference_source"] == source


def test_the_two_gates_are_never_both_open():
    """§16.E's invariant, asserted as an outcome rather than a config
    check: with a legal delta ordering no score can both skip the round
    and bypass its budget. Inverted deltas make both fire, which is why
    D-C1b refuses them at launch."""
    for score in [round(9.0 + i * 0.1, 4) for i in range(30)]:
        result = _launch([_trial("sweep", score)])
        assert not (result.skip and result.bypass), score


class TestTheWinnerIsResolvedOnce:
    """Row 12 — the same winner snapshot reaches skip, bypass, the log
    line and formal-plan inheritance.

    Originally three independent `_best_trial_winner` calls agreed only
    because the trial history cannot change between them. FU-D-6 closed
    that seam: inheritance now RECEIVES the winner instead of deriving
    one, so agreement is structural rather than coincidental.
    """

    RECORDS: ClassVar[list[dict]] = [
        _trial("collapsed_high", 99.0, valid=False),
        _trial("real_winner", 10.6),
        _trial("weaker", 10.1),
    ]

    def test_skip_bypass_and_inheritance_all_judge_the_same_record(self):
        winner = _best_trial_winner(self.RECORDS)
        assert winner is not None and winner["exp_id"] == "real_winner"

        from agent.schemas.hyperparam_tuning import ExperimentPlan

        plan = _apply_mode_override_chain(
            ExperimentPlan.with_defaults(
                {
                    "model_cfg": {"depth": 4},
                    "train_cfg": {"lr": 0.002, "epochs": 1, "batch_size": 4},
                    "loss_cfg": {"loss_type": "ce"},
                    "is_trial": True,
                }
            ),
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="inherit_best_trial",
            memory_history=self.RECORDS,
            trial_winner=winner,
        )
        assert plan.model_cfg == winner["params"]["model_config"]
        assert plan.train_cfg["lr"] == winner["params"]["train_config"]["lr"]

    def test_inheritance_obeys_the_supplied_winner_over_the_history(self):
        """FU-D-6's actual guarantee, and the only test that can show it.

        Hand inheritance a history whose OWN best is `real_winner` while
        supplying `weaker` as the resolved winner. If the function still
        re-derived from the history it would inherit `real_winner`'s
        config; because it uses the snapshot it must inherit `weaker`'s.

        The two are deliberately given different `lr` values so the
        assertion cannot pass by coincidence. This configuration cannot
        arise in production — that is the point: it isolates *which*
        source is consulted.
        """
        from agent.schemas.hyperparam_tuning import ExperimentPlan

        weaker = _trial("weaker", 10.1)
        # Only the lr differs; the rest of `params` stays intact because
        # `hybrid_params` also reads `loss_config`.
        weaker["params"] = {**weaker["params"], "train_config": {"lr": 0.00042}}
        history = [_trial("real_winner", 10.6), weaker]
        supplied = weaker

        plan = _apply_mode_override_chain(
            ExperimentPlan.with_defaults(
                {
                    "model_cfg": {"depth": 4},
                    "train_cfg": {"lr": 0.002, "epochs": 1, "batch_size": 4},
                    "loss_cfg": {"loss_type": "ce"},
                    "is_trial": True,
                }
            ),
            trial_allowed=True,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy="hybrid_params",
            memory_history=history,
            trial_winner=supplied,
        )

        assert plan.train_cfg["lr"] == 0.00042, (
            "inheritance re-derived the winner from memory_history instead "
            "of using the supplied snapshot"
        )

    def test_the_helper_cannot_silently_fall_back_to_the_history(self):
        """MUTATION TARGET: giving `trial_winner` a `None` default.

        A default would make a forgetful caller silently mean "no winner",
        which for `full_clone`/`hybrid_params` means "inherit nothing" —
        a behaviour change with no error. Keeping it required turns that
        into a `TypeError` at the call site.
        """
        import inspect

        parameter = inspect.signature(_apply_mode_override_chain).parameters["trial_winner"]
        assert parameter.default is inspect.Parameter.empty
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    def test_a_formal_round_cannot_add_a_trial_record_beneath_the_snapshot(self):
        """WHY the round-boundary snapshot is safe to reuse inside the
        attempt loop.

        The tuner resolves the winner once at the formal-round boundary
        and the bypass gate consults it later, after attempts may have
        appended records. That is only sound because a formal round
        forces `plan.is_trial = False`, so nothing it appends can satisfy
        `_best_trial_winner`'s filter. Appending formal records must
        therefore leave the winner identical.
        """
        before = _best_trial_winner(self.RECORDS)
        formal_attempt = {
            "exp_id": "formal_attempt_1",
            "status": "success",
            "denoising_score": 999.0,
            "is_trial": False,
            "health_gate_results": [],
            "memory": {"time_mode": "formal", "round_index": 2},
        }
        after = _best_trial_winner([*self.RECORDS, formal_attempt])
        assert after is before

    def test_the_production_site_resolves_the_winner_exactly_once(self):
        """MUTATION TARGET: re-deriving the winner at either gate.

        Structural, because the divergence it guards against is invisible
        to a behavioural test while the history happens to be stable.
        """
        src = (
            Path(__file__).resolve().parents[4]
            / "nodes"
            / "ml_hyperparameter_tune_agent"
            / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")

        assert "formal_trial_winner = _best_trial_winner(" in src
        assert src.count("formal_trial_winner = _best_trial_winner(") == 1
        # Both gates receive the resolved winner, not a fresh list.
        assert "_should_skip_formal(\n                    formal_trial_winner," in src
        assert (
            "_should_bypass_formal_time_budget(\n                                formal_trial_winner,"
            in src
        )
        # And the feature switch really is threaded into the skip gate.
        assert "gates_enabled=agent_input.enable_chain_incumbent_formal_gates," in src


class TestPersistenceIsJsonSafe:
    """`-inf` is a RESOLVER value, never a stored one (§16.C)."""

    def test_nan_is_sanitised_too_not_only_the_infinities(self):
        """MUTATION TARGET: testing membership instead of finiteness.

        `value in (float("-inf"), float("inf"))` compares by EQUALITY, and
        NaN is not equal to itself — so that form lets NaN through, and
        `json.dump` (whose `allow_nan` defaults to True) writes a bare
        `NaN` into the artifact. Reachable: the deltas are operator CLI
        floats, and `reference + nan` is `nan`.

        The gates are separately blind to it — every comparison against
        NaN is False, so a NaN threshold silently disables both rather
        than failing loudly. That refusal belongs to D-C1b's launch
        validation and is filed as FU-D-8; what this test pins is that it
        can never reach an artifact.
        """
        assert _json_safe_reference(float("nan")) is None
        assert (
            json.dumps({"t": _json_safe_reference(float("nan"))}, allow_nan=False) == '{"t": null}'
        )

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (float("-inf"), None),
            (float("inf"), None),
            (float("nan"), None),
            (None, None),
            (0.0, 0.0),
            (-3.5, -3.5),
            (10.0, 10.0),
        ],
    )
    def test_infinite_bounds_persist_as_null(self, value, expected):
        assert _json_safe_reference(value) is expected or _json_safe_reference(value) == expected

    def test_an_operator_disabling_a_gate_cannot_write_infinity(self):
        """The PRE-EXISTING case, not the bootstrap: `skip_delta=-inf` and
        `bypass_delta=+inf` are the documented way to switch a gate off,
        and with a real incumbent they already produced infinite
        thresholds that would have serialised as non-standard JSON."""
        _, skip_t, bypass_t, _ = _resolve_formal_comparison_thresholds(
            reference_score=10.0,
            skip_min_delta=float("-inf"),
            bypass_min_delta=float("inf"),
            gates_enabled=True,
        )
        assert (skip_t, bypass_t) == (float("-inf"), float("inf"))
        persisted = {
            "resolved_skip_formal_threshold": _json_safe_reference(skip_t),
            "resolved_bypass_formal_threshold": _json_safe_reference(bypass_t),
        }
        assert json.dumps(persisted, allow_nan=False) == (
            '{"resolved_skip_formal_threshold": null, "resolved_bypass_formal_threshold": null}'
        )

    def test_the_provenance_survives_the_typed_output_and_the_manifest(self):
        """MUTATION TARGET: emitting the source into a dict but never
        DECLARING it on `HyperparamTuningOutput`.

        This is a real gap D-C3 shipped with and closed. The tuner builds
        `agent_output_dict` and hands it to `model_validate`; Pydantic's
        default `extra="ignore"` silently DROPS an undeclared key, so the
        source reached the run_config dict and vanished before
        `run_output_*.json` and the iteration manifest — the two artifacts
        an operator actually reads. Nothing failed, because a dropped
        field looks exactly like a field that was never set.

        Without the provenance, `formal_reference_score: null` is
        ambiguous across three genuinely different runs (§16.C).
        """
        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

        assert "formal_comparison_reference_source" in HyperparamTuningOutput.model_fields

        output = HyperparamTuningOutput.model_validate(
            {
                "run_name": "prov",
                "model_type": "punet",
                "file_index": 0,
                "status": "completed",
                "completed_rounds": 1,
                "total_attempts": 1,
                "all_records": [],
                "started_at": "2026-08-05 00:00:00",
                "finished_at": "2026-08-05 00:00:01",
                "formal_reference_score": None,
                "formal_comparison_reference_source": "negative_infinity_bootstrap",
                "resolved_skip_formal_threshold": None,
                "resolved_bypass_formal_threshold": None,
            }
        )
        assert output.formal_comparison_reference_source == "negative_infinity_bootstrap"

        # ...and it reaches the manifest the chain reads, still paired with
        # the null reference rather than replacing it.
        restored = json.loads(output.model_dump_json())
        assert restored["formal_reference_score"] is None
        assert restored["formal_comparison_reference_source"] == "negative_infinity_bootstrap"

    def test_the_manifest_carries_the_source_beside_the_reference(self, tmp_path):
        """Reachability for the OTHER artifact: `write_manifest` must copy
        the source across, not just the reference and thresholds."""
        from sdsc_submission_scripts.run_one_iteration import write_manifest

        class _Output:
            model_type = "punet"
            completed_rounds = 1
            best_denoising_score = 1.0
            best_exp_id = "e1"
            formal_reference_score = None
            formal_comparison_reference_source = "negative_infinity_bootstrap"
            resolved_skip_formal_threshold = None
            resolved_bypass_formal_threshold = None

        # `write_manifest` takes the tuner output as `results[0]`.
        manifest = write_manifest(iter_dir=str(tmp_path), run_name="prov", results=[_Output()])
        assert manifest["formal_comparison_reference_source"] == "negative_infinity_bootstrap"
        assert manifest["formal_reference_score"] is None
        assert "Infinity" not in json.dumps(manifest, allow_nan=False)

    def test_every_tuner_persistence_site_sanitises_all_three_values(self):
        """MUTATION TARGET: sanitising the reference but not the
        thresholds, or covering two of the three artifact sites.

        Under the bootstrap all three are `-inf` simultaneously, so a
        partial fix still emits `Infinity`.
        """
        src = (
            Path(__file__).resolve().parents[4]
            / "nodes"
            / "ml_hyperparameter_tune_agent"
            / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")

        for field in (
            "formal_reference_score",
            "resolved_skip_formal_threshold",
            "resolved_bypass_formal_threshold",
        ):
            # The unsanitised form — `"field": field,` — must appear nowhere.
            assert f'"{field}": {field},' not in src, f"{field} is persisted unsanitised somewhere"
            assert src.count(f'"{field}": _json_safe_reference(') == 3, (
                f"{field} must be sanitised at all three persistence sites"
            )


# ---------------------------------------------------------------------------
# Production reachability — the decision through the real tuner loop
# ---------------------------------------------------------------------------


def _run_one_formal_round(tmp_path, *, seeded_trial: dict, gates_enabled: bool) -> list[dict]:
    """Drive the real tuner to its formal round and return every record.

    Reaches the formal round the production way, via RESUME: a completed
    trial round is already on the sandbox summary, `max_rounds=2` makes the
    next round the final one, and `force_formal_round` (default `True`)
    turns it formal. Only the skill EXECUTION is mocked — the round loop,
    the resolver, the winner resolution and both gates all run for real.

    ``health_gate_enabled=True`` throughout, and the seed is deliberately
    left UNSTAMPED (DS6b reads that as "legacy = gates active", which is
    compatible with an enabled run). Both details are load-bearing: DS5
    waives the gate requirement entirely for a record stamped
    ``health_gate_enabled=False``, so a seed carrying that stamp would be
    classified VALID whatever its gate results say — a combination that
    cannot occur in production and would silently defeat this harness.
    The only variable across these tests is the chain-incumbent switch.
    """
    from .test_tuning_agent import FAKE_REFLECT_RESPONSE, _mock_run_skill, _synth_reference

    saved_records: list[dict] = [seeded_trial]

    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch("nodes.ml_hyperparameter_tune_agent._run_skill", side_effect=_mock_run_skill),
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        tempfile.TemporaryDirectory() as configs_dir,
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = {
            "model_type": "punet",
            "hypothesis": "Formal round.",
            "reasoning": "Exercise the launch decision.",
            "model_config": {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
            "train_config": {"epochs": 1, "lr": 1e-4},
            "loss_config": {"loss_type": "focal", "gamma": 2.0},
            "is_trial": False,
        }
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = saved_records.append
        data_dir = Path(tmp_path) / "anchor_data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "segment_anchors.json").write_text(
            json.dumps({"s_max": 1.0, "anchors": {str(i): [1.0] for i in range(20)}})
        )
        mock_sandbox.dirs = {"configs": configs_dir, "data": str(data_dir)}
        mock_sandbox.score_vector.return_value = ([1.75] * 20, 1.75)

        HyperparamTuningAgent = __import__(
            "nodes.ml_hyperparameter_tune_agent", fromlist=["HyperparamTuningAgent"]
        ).HyperparamTuningAgent

        HyperparamTuningAgent().run(
            HyperparamTuningInput(
                model_type="punet",
                run_name="dc3_launch",
                max_rounds=2,
                attempts_per_round=1,
                attempts_per_formal_round=1,
                max_fail_rounds=1,
                is_trial=True,
                health_gate_enabled=True,
                enable_chain_incumbent_formal_gates=gates_enabled,
                current_run_best_formal_score=None,
                skip_formal_min_delta=SKIP_DELTA,
                bypass_formal_time_budget_min_delta=BYPASS_DELTA,
                llm_provider="gemini",
                llm_model_id="test-model",
                storage=StorageConfig(
                    backend="local",
                    local=LocalStorageConfig(workspace=str(tmp_path), run_name="dc3_launch"),
                ),
                progress_bar=False,
            )
        )
    return saved_records


def _formal_records(records: list[dict]) -> list[dict]:
    return [r for r in records[1:] if r.get("is_trial") is not True]


def test_production_no_valid_trial_skips_the_formal_round(tmp_path, capsys):
    """THE HEADLINE BEHAVIOUR, through the real loop.

    A collapsed trial scoring 99.0 is the only evidence. Pre-D-C3 the
    formal round ran anyway; now the iteration ends without spending it.
    """
    records = _run_one_formal_round(
        tmp_path, seeded_trial=_trial("collapsed", 99.0, valid=False), gates_enabled=True
    )

    assert _formal_records(records) == [], "a formal round was spent on no valid evidence"
    assert "no_valid_trial_winner" in capsys.readouterr().out


def test_production_a_valid_trial_still_runs_the_formal_round(tmp_path):
    """The control. Same harness, one valid trial — the round must still
    run, so the test above is measuring the winner and not the harness."""
    records = _run_one_formal_round(
        tmp_path, seeded_trial=_trial("healthy", 5.0), gates_enabled=True
    )

    assert _formal_records(records), "a valid trial winner must still open the formal round"


def test_production_with_the_gates_disabled_the_round_still_runs(tmp_path):
    """BACKWARD COMPATIBILITY, through the real loop: with the feature
    switch off, no valid winner, the formal round runs exactly as it did
    before D-C3."""
    records = _run_one_formal_round(
        tmp_path, seeded_trial=_trial("collapsed", 99.0, valid=False), gates_enabled=False
    )

    assert _formal_records(records), "the gates-disabled path must be unchanged by D-C3"
