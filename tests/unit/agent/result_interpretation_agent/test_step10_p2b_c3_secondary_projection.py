"""Step 10 / P2b — C3: persisted secondary evidence becomes interpreter evidence.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2b_secondary_metric_transport.md`` §4.4, §4.5, §6 C3.

The defects only this module catches
------------------------------------
1. **A silence reported as a measurement, or a measurement reported as
   silence.** The four projection states are the whole point: `scored`,
   `refused`, `unavailable` (a NAMED absence, which also covers a crash) and —
   for an output that declared nothing — no rows at all. Collapsing any pair
   would let the renderer print a confident silence where a named absence
   belongs, or invent absence rows for a task that has no secondaries.
2. **The B-6 carry asymmetry.** `failure_counts` is projected fresh AND
   restored from `_stats`; before P2b `secondary_metrics` had NEITHER half, so
   the Stability-Filter reuse path — a model that goes quiet for an iteration
   and gets no fresh LLM call — was exactly the path that lost the evidence.
   One fixture asserts BOTH keys survive it, in one assertion block, because
   the claim is that they ride the same mechanism.
3. **An inherited direction.** The fixture's `psnr` is higher-is-better while
   `mae` is lower-is-better. A carrier that inherited one direction would
   render one of them backwards and no numeric assertion would notice.
"""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import (
    ResultInterpretationAgent,
    tuning_output_to_model_run_summary,
)
from tests.helpers.metric_fixtures import shipped_spec

ORDER = MetricOrder(shipped_spec())

PSNR = {
    "id": "psnr",
    "direction": "higher",
    "aggregation": "global_mean_squared_error_over_clips_x_C_x_T_x_H_x_W",
    "references": [],
    "scoreability": {"contract_id": "deliverable_presence"},
    "transform": "psnr_db",
    "transform_params": {"data_range": 1.0},
}
MAE = {
    "id": "mae",
    "direction": "lower",
    "aggregation": "global_mean_absolute_error_over_clips_x_C_x_T_x_H_x_W",
    "references": [],
    "scoreability": {"contract_id": "deliverable_presence"},
    "transform": None,
    "transform_params": {},
}


def _refusal(metric_id: str, direction: str) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "direction": direction,
        "verdict": {
            "contract_id": "deliverable_presence",
            "failures": [{"requirement": "deliverable_exists", "detail": "absent"}],
        },
    }


def _record(exp_id: str = "r", **overrides) -> ExperimentRecord:
    return ExperimentRecord.model_validate(
        {
            "exp_id": exp_id,
            "status": "success",
            "model_type": "wavenet",
            "timestamp": "2026-08-21T00:00:00Z",
            "params": {},
            "denoising_score": -2.0,
            "health_gate_enabled": False,
            **overrides,
        }
    )


def _output(*records, stamp: list[dict] | None = None, **extra) -> HyperparamTuningOutput:
    payload: dict[str, Any] = {
        "run_name": "p2b",
        "model_type": "wavenet",
        "file_index": 6,
        "status": "completed",
        "completed_rounds": len(records),
        "total_attempts": len(records),
        "started_at": "2026-08-21T00:00:00Z",
        "finished_at": "2026-08-21T01:00:00Z",
        "all_records": list(records),
        **extra,
    }
    if stamp is not None:
        payload["secondary_metric_specs"] = stamp
    return HyperparamTuningOutput.model_validate(payload)


def _states(summary) -> list[tuple[str, str, str]]:
    """The projected STATE SEQUENCE: (id, its OWN direction, status)."""
    return [(e.spec.id, e.spec.direction, e.status) for e in summary.secondary_metrics]


# ---------------------------------------------------------------------------
# 1. The projection matrix — every state, as hand-written literals
# ---------------------------------------------------------------------------


class TestTheProjectionMatrix:
    def test_a_scored_pair_keeps_each_metric_s_OWN_direction(self):
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(
                    secondary_metric_results=[
                        {"metric_id": "psnr", "direction": "higher", "scalar": 31.5},
                        {"metric_id": "mae", "direction": "lower", "scalar": 0.017},
                    ]
                ),
                stamp=[PSNR, MAE],
            ),
            order=ORDER,
        )
        assert _states(summary) == [
            ("psnr", "higher", "scored"),
            ("mae", "lower", "scored"),
        ]
        assert [e.result.scalar for e in summary.secondary_metrics] == [31.5, 0.017]

    def test_a_refused_secondary_projects_refused_with_its_verdict(self):
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(secondary_metric_refusals=[_refusal("psnr", "higher")]),
                stamp=[PSNR, MAE],
            ),
            order=ORDER,
        )
        assert _states(summary) == [
            ("psnr", "higher", "refused"),
            ("mae", "lower", "unavailable"),
        ]
        assert summary.secondary_metrics[0].refusal.verdict.contract_id == "deliverable_presence"

    def test_a_declared_but_unevaluated_secondary_is_a_NAMED_absence(self):
        summary = tuning_output_to_model_run_summary(
            _output(_record(), stamp=[PSNR, MAE]), order=ORDER
        )
        assert _states(summary) == [
            ("psnr", "higher", "unavailable"),
            ("mae", "lower", "unavailable"),
        ]

    def test_a_CRASHED_secondary_projects_unavailable_and_never_a_fourth_state(self):
        """Q-P2b-2: the crash keeps its own diagnostic provenance on the record,
        but `SecondaryMetricEvidence` stays a THREE-state model. A crash
        promoted to a fourth scientific state would report an implementation
        failure as a finding about the science."""
        record = _record(secondary_metric_errors={"psnr": "ValueError: boom"})
        summary = tuning_output_to_model_run_summary(_output(record, stamp=[PSNR]), order=ORDER)
        assert _states(summary) == [("psnr", "higher", "unavailable")]
        assert record.secondary_metric_errors == {"psnr": "ValueError: boom"}

    @pytest.mark.parametrize("stamp", [None, []], ids=["no-stamp-legacy", "empty-stamp"])
    def test_an_output_that_declared_nothing_gets_NO_absence_rows(self, stamp):
        """Zero rows, not "unavailable" rows. A run of a task with no
        secondaries — TIDMAD — must render zero bytes, and a legacy output has
        no declared set to name an absence against."""
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(
                    secondary_metric_results=[
                        {"metric_id": "psnr", "direction": "higher", "scalar": 31.5}
                    ]
                ),
                stamp=stamp,
            ),
            order=ORDER,
        )
        assert summary.secondary_metrics == [], (
            "with no declared set there is nothing to report; reading the record "
            "anyway would resurrect the hidden contract Q-09-7 = B forbade"
        )
        # The record DOES carry evidence — that is the point. A projection that
        # fell back to the record's own carriers when the stamp is missing
        # would pass a test whose record was empty.
        assert summary.round_scores, "the fixture must contain a real record"

    def test_the_projection_follows_the_record_the_headline_score_came_FROM(self):
        """A secondary number must describe the same experiment as the score
        printed beside it — the per-role reasoning Step 09a applied to the
        training diagnosis. Under `higher`, the best record is the -1.0 one."""
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(
                    "worse",
                    denoising_score=-3.0,
                    secondary_metric_results=[
                        {"metric_id": "psnr", "direction": "higher", "scalar": 11.1}
                    ],
                ),
                _record(
                    "best",
                    denoising_score=-1.0,
                    secondary_metric_results=[
                        {"metric_id": "psnr", "direction": "higher", "scalar": 99.9}
                    ],
                ),
                stamp=[PSNR],
                best_denoising_score=-1.0,
            ),
            order=ORDER,
        )
        assert summary.best_denoising_score == -1.0
        assert [e.result.scalar for e in summary.secondary_metrics] == [99.9], (
            "the projection took a secondary from a record other than the one "
            "the headline score came from — the two would describe different "
            "experiments"
        )

    def test_the_declared_ORDER_is_preserved(self):
        summary = tuning_output_to_model_run_summary(
            _output(_record(), stamp=[MAE, PSNR]), order=ORDER
        )
        assert [e.spec.id for e in summary.secondary_metrics] == ["mae", "psnr"]

    def test_a_stamped_run_with_no_scored_record_still_names_its_declared_set(self):
        """Every record failed, so there is no `best_rec` — the declared family
        is still reported, as absence."""
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(status="error_scoring", denoising_score=None),
                stamp=[PSNR, MAE],
            ),
            order=ORDER,
        )
        assert _states(summary) == [
            ("psnr", "higher", "unavailable"),
            ("mae", "lower", "unavailable"),
        ]


# ---------------------------------------------------------------------------
# 2. The B-6 carry symmetry
# ---------------------------------------------------------------------------


class TestTheQuietIterationCarry:
    """`failure_counts` and `secondary_metrics` must survive equally long."""

    STAMPED: ClassVar[list[dict]] = [PSNR, MAE]

    def _run(self, tmp_path, summaries, cache):
        inp = InterpretationInput(
            summaries=summaries,
            metric_spec=shipped_spec(),
            model_knowledge_cache=cache,
            storage={
                "backend": "local",
                "local": {"workspace": str(tmp_path), "run_name": "p2b"},
            },
        )
        with patch("nodes.result_interpretation_agent.LLMBridge") as bridge:
            bridge.return_value.generate.side_effect = RuntimeError("forced LLM failure")
            agent = ResultInterpretationAgent(provider="openai", model_id="x")
            agent.bridge = bridge.return_value
            return agent.run(inp)

    def _summary(self):
        summary = tuning_output_to_model_run_summary(
            _output(
                _record(
                    secondary_metric_results=[
                        {"metric_id": "psnr", "direction": "higher", "scalar": 31.5}
                    ],
                    secondary_metric_refusals=[_refusal("mae", "lower")],
                ),
                stamp=self.STAMPED,
            ),
            order=ORDER,
        )
        summary.model_description = "d"
        return summary

    def test_a_fresh_summary_projects_both_keys(self, tmp_path):
        out = self._run(tmp_path, [self._summary()], {})
        assert "wavenet" in out.per_model_failure_counts
        assert [e.spec.id for e in out.per_model_secondary_metrics["wavenet"]] == ["psnr", "mae"]

    def test_a_QUIET_model_keeps_BOTH_keys_across_the_reuse_path(self, tmp_path):
        """The B-6 defect, in one assertion block.

        The model contributes NO summary this iteration — the Stability-Filter
        reuse path, no fresh LLM call — and both deterministic evidence keys
        must come back from `_stats`. Before P2b, `failure_counts` did and
        `secondary_metrics` did not.
        """
        summary = self._summary()
        cache = {
            "wavenet": {
                "insights": "x",
                "_stats": {
                    "failure_counts": summary.failure_counts.model_dump(),
                    "secondary_metrics": [e.model_dump() for e in summary.secondary_metrics],
                },
            }
        }
        out = self._run(tmp_path, [], cache)
        assert "wavenet" in out.per_model_failure_counts, "failure_counts lost on the quiet path"
        restored = out.per_model_secondary_metrics.get("wavenet")
        assert restored is not None, "secondary_metrics lost on the quiet path (audit B-6)"
        assert [(e.spec.id, e.spec.direction, e.status) for e in restored] == [
            ("psnr", "higher", "scored"),
            ("mae", "lower", "refused"),
        ]

    def test_the_write_and_the_read_back_are_ONE_round_trip(self, tmp_path):
        """The producer half, which a hand-built cache cannot reach.

        Mutation M11 — deleting the `_stats` WRITE — survived the test above,
        because that fixture supplies the cached payload itself. This runs a
        HEALTHY interpretation, takes the cache IT produced, and feeds that
        cache into a second run where the model goes quiet. Nothing here
        hand-writes the `_stats` payload, so both halves are load-bearing.
        """
        from tests.unit.agent.result_interpretation_agent import _step09a_fixture as fx

        summary = self._summary()
        first = ResultInterpretationAgent(
            bridge_factory=lambda **_kw: fx.RecordingStubBridge(str(tmp_path))
        ).run(
            InterpretationInput(
                summaries=[summary],
                metric_spec=shipped_spec(),
                storage={
                    "backend": "local",
                    "local": {"workspace": str(tmp_path), "run_name": "p2b"},
                },
            )
        )
        produced = (first.model_knowledge_cache["wavenet"].get("_stats") or {}).get(
            "secondary_metrics"
        )
        assert produced, "the healthy path never wrote the _stats secondary key"

        # Second iteration: the model contributes NO summary, so everything
        # must come back through the cache the FIRST run wrote.
        second = self._run(tmp_path / "iter2", [], first.model_knowledge_cache)
        assert [
            (e.spec.id, e.spec.direction, e.status)
            for e in second.per_model_secondary_metrics["wavenet"]
        ] == [("psnr", "higher", "scored"), ("mae", "lower", "refused")]

    def test_the_read_back_is_VALIDATED_not_a_raw_dict(self, tmp_path):
        cache = {
            "wavenet": {
                "insights": "x",
                "_stats": {"secondary_metrics": [{"spec": PSNR}]},
            }
        }
        out = self._run(tmp_path, [], cache)
        entry = out.per_model_secondary_metrics["wavenet"][0]
        assert entry.spec.direction == "higher" and entry.status == "unavailable"

    def test_a_cache_predating_the_key_contributes_ABSENCE_never_zero(self, tmp_path):
        cache = {"wavenet": {"insights": "x", "_stats": {"failure_counts": None}}}
        out = self._run(tmp_path, [], cache)
        assert "wavenet" not in out.per_model_secondary_metrics

    def test_a_corrupt_cached_payload_degrades_to_absence_without_crashing(self, tmp_path, capsys):
        cache = {
            "wavenet": {
                "insights": "x",
                "_stats": {"secondary_metrics": [{"spec": {"id": "psnr"}}]},
            }
        }
        out = self._run(tmp_path, [], cache)
        assert "wavenet" not in out.per_model_secondary_metrics
        assert "unreadable cached secondary" in capsys.readouterr().out

    def test_a_zero_secondary_run_writes_NO_stats_key(self, tmp_path):
        """§4.7: a run that declared no secondary leaves the cache entry
        byte-identical to its pre-P2b self — no empty list, no null.

        Driven through the HEALTHY path with the Step-09a stub bridge: the
        `_stats` block is written only when the per-model LLM call succeeds,
        so the degraded harness the rest of this class uses cannot see it.
        """
        from tests.unit.agent.result_interpretation_agent import _step09a_fixture as fx

        summary = tuning_output_to_model_run_summary(_output(_record(), stamp=None), order=ORDER)
        summary.model_description = "d"
        assert summary.secondary_metrics == []

        inp = InterpretationInput(
            summaries=[summary],
            metric_spec=shipped_spec(),
            storage={
                "backend": "local",
                "local": {"workspace": str(tmp_path), "run_name": "p2b"},
            },
        )
        recorder = fx.RecordingStubBridge(str(tmp_path))
        out = ResultInterpretationAgent(bridge_factory=lambda **_kw: recorder).run(inp)

        stats = (out.model_knowledge_cache.get("wavenet") or {}).get("_stats") or {}
        assert "failure_counts" in stats, (
            "the comparison key must be present, or 'the secondary key is "
            "absent' would pass on an empty _stats block"
        )
        assert "secondary_metrics" not in stats


# ---------------------------------------------------------------------------
# 3. Rendering — the EXISTING 09b renderer, reused unchanged
# ---------------------------------------------------------------------------


class TestTheRendering:
    def test_a_secondary_is_rendered_with_its_OWN_direction_words(self):
        """DAVIS's discriminating case, asserted textually.

        `psnr` is higher-is-better beside a lower-is-better primary. The
        renderer landed in 09b and is reused unchanged; what P2b must not
        break is that each line reads its own carrier.
        """
        from agent.prompt_templates.interpretation.rendering import render_secondary_metrics

        summary = tuning_output_to_model_run_summary(
            _output(
                _record(
                    secondary_metric_results=[
                        {"metric_id": "psnr", "direction": "higher", "scalar": 31.5}
                    ],
                    secondary_metric_refusals=[_refusal("mae", "lower")],
                ),
                stamp=[PSNR, MAE],
            ),
            order=ORDER,
        )
        # The 09b renderer returns one LINE per declared secondary, in
        # declaration order — reused here exactly as it shipped.
        rendered = render_secondary_metrics(summary.secondary_metrics)
        assert len(rendered) == 2
        psnr_line = next(line for line in rendered if "psnr" in line)
        mae_line = next(line for line in rendered if "mae" in line)
        assert "higher" in psnr_line and "lower" not in psnr_line, psnr_line
        assert "lower" in mae_line and "higher" not in mae_line, mae_line
        assert "31.5" in psnr_line
        assert "deliverable_presence" in mae_line, (
            "a refusal must render its contract id verbatim, not a paraphrase"
        )

    def test_no_declared_secondary_renders_ZERO_bytes(self):
        """TIDMAD's path. Not "an empty section" — no bytes at all."""
        from agent.prompt_templates.interpretation.rendering import render_secondary_metrics

        summary = tuning_output_to_model_run_summary(_output(_record()), order=ORDER)
        assert summary.secondary_metrics == []
        assert render_secondary_metrics(summary.secondary_metrics) == [], (
            "no declared secondary must produce no line at all — not an empty "
            "section header, which would still cost prompt bytes"
        )
