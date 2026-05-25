"""
F.9 — Tier 2 dual-mode test: tune_ml_hyperparam_agent → result_interpretation_agent.

Exercises the full edge:
  1. Construct a HyperparamTuningOutput with known wavenet data
  2. Apply protocol local_all_records(output, storage) → InterpretationInput
  3. Run ResultInterpretationAgent with RecordingLLMBridge
  4. Validate InterpretationOutput has expected values

No GPU or real training required — this test validates the protocol mapping
and the interpretation agent's orchestration, not the training pipeline.

Run with:
  uv run pytest -m dual_mode tests/integration/protocols/test_tune_to_interp.py -v

DO NOT remove the dual_mode marker — this test runs in CI in pseudo mode.
"""

from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.schemas.hyperparam_tuning import (
    ExperimentRecord,
    HyperparamTuningOutput,
)
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import local_all_records
from agent.schemas.score_table import (
    AggregateScalars,
    PerFileRow,
    ScoreComparisonTable,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.scoring_helpers import render_comparison_table
from nodes.result_interpretation_agent import ResultInterpretationAgent

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")


# ---------------------------------------------------------------------------
# Synthetic HyperparamTuningOutput (wavenet, 2 rounds)
# ---------------------------------------------------------------------------

_WAVENET_BEST_FV = [
    0.1,
    0.1,
    0.1,
    0.1,
    0.1,  # files 0-4:  low-freq, near zero
    4.2,
    4.5,
    5.1,
    5.8,
    6.2,
    6.7,  # files 5-10: mid-freq, rising
    7.1,
    7.5,
    7.9,
    8.2,
    8.5,
    8.7,
    8.9,
    9.0,
    9.1,  # files 11-19: high-freq
]


def _make_score_table(model_fv: list[float], model_scalar: float) -> ScoreComparisonTable:
    """Build a realistic ScoreComparisonTable from a length-20 file vector.

    Produces `rendered_markdown` via the real renderer so downstream
    signature assertions (Phase 6 B) match production output.
    """
    raw_baseline_per_file = [0.2] * 20
    ground_truth_per_file = [9.5] * 20
    rows = [
        PerFileRow(
            file_index=i,
            raw_baseline=raw_baseline_per_file[i],
            ground_truth=ground_truth_per_file[i],
            model=v,
            gain_vs_raw=v - raw_baseline_per_file[i],
            headroom_vs_gt=ground_truth_per_file[i] - v,
        )
        for i, v in enumerate(model_fv)
    ]
    aggregate = AggregateScalars(
        raw_baseline_scalar=0.2,
        ground_truth_scalar=9.5,
        model_scalar=model_scalar,
        percent_of_ceiling_log=model_scalar / 9.5,
        num_sampled_files=20,
    )
    table = ScoreComparisonTable(
        rows=rows,
        aggregate=aggregate,
        s_max_global=5.27,
        reference_source="test_fixture",
        rendered_markdown="",
    )
    return table.model_copy(update={"rendered_markdown": render_comparison_table(table)})


_WAVENET_BEST_SCORE_TABLE = _make_score_table(_WAVENET_BEST_FV, model_scalar=5.576)
_WAVENET_FORMAL_SCORE_TABLE = _make_score_table(_WAVENET_BEST_FV, model_scalar=5.612)

_WAVENET_TUNING_OUTPUT = HyperparamTuningOutput(
    run_name="dual_tune_to_interp",
    model_type="wavenet",
    file_index=6,
    status="completed",
    completed_rounds=2,
    total_attempts=2,
    best_exp_id="wavenet_001_002",
    best_denoising_score=5.576,
    best_file_vector=_WAVENET_BEST_FV,
    best_score_table=_WAVENET_BEST_SCORE_TABLE,
    formal_score_table=_WAVENET_FORMAL_SCORE_TABLE,
    best_config={
        "model_config": {
            "model_type": "wavenet",
            "segmentation_size": 10000,
            "residual_channels": 16,
            "num_blocks": 3,
        },
        "train_config": {"lr": 1e-4, "epochs": 5},
        "loss_config": {"loss_type": "focal"},
    },
    all_records=[
        ExperimentRecord(
            exp_id="wavenet_001_001",
            status="success",
            model_type="wavenet",
            timestamp="2026-04-14 00:00:00",
            file_index=6,
            params={
                "model_config": {
                    "model_type": "wavenet",
                    "segmentation_size": 10000,
                    "residual_channels": 8,
                    "num_blocks": 2,
                },
                "train_config": {"lr": 1e-4, "epochs": 5},
                "loss_config": {"loss_type": "ce"},
            },
            denoising_score=5.21,
            file_vector=_WAVENET_BEST_FV,
            final_loss=0.41,
            model_params=2_100_000,
            memory={
                "expert_advice_followed": "n/a",
                "hypothesis": "CE loss will provide a reasonable baseline.",
                "conclusion": "CE baseline is reasonable but focal should improve.",
                "key_factor": "Low-freq blind spot already visible.",
                "discovery": "Files 0-4 near zero regardless of loss.",
                "memory_update": "Switch to focal loss next.",
            },
        ),
        ExperimentRecord(
            exp_id="wavenet_001_002",
            status="success",
            model_type="wavenet",
            timestamp="2026-04-14 01:00:00",
            file_index=6,
            params={
                "model_config": {
                    "model_type": "wavenet",
                    "segmentation_size": 10000,
                    "residual_channels": 16,
                    "num_blocks": 3,
                },
                "train_config": {"lr": 1e-4, "epochs": 5},
                "loss_config": {"loss_type": "focal"},
            },
            denoising_score=5.576,
            file_vector=_WAVENET_BEST_FV,
            final_loss=0.289,
            model_params=4_123_456,
            memory={
                "expert_advice_followed": "Switch to focal loss.",
                "hypothesis": "Focal loss will improve score by reducing easy-example dominance.",
                "conclusion": "Focal loss improved score to 5.576. High-freq strong, low-freq blind.",
                "key_factor": "Focal loss and deeper residual stack.",
                "discovery": "Low-freq blindness is structural — not fixable by loss tuning alone.",
                "memory_update": "Next: spectral processing to address low-freq gap.",
            },
        ),
    ],
    started_at="2026-04-14 00:00:00",
    finished_at="2026-04-14 02:00:00",
)


# ---------------------------------------------------------------------------
# F.9 — Dual-mode Tier 2 test
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_tune_to_interp_protocol_and_node(tmp_path, request):
    """F.9 — Tier 2 dual-mode: HyperparamTuningOutput → local_all_records → InterpretationAgent.

    Validates:
    1. Protocol correctly maps tuning output to InterpretationInput
       (model_type, best_score, completed_rounds, file_vector propagated).
    2. InterpretationAgent produces a valid InterpretationOutput from the
       condensed summary — no raw records needed.
    3. Key assertions on scores, model types, and output file persistence.

    Pseudo mode (default): RecordingLLMBridge with canned responses.
    Real mode (--real-api-call): real Gemini API. Skips if key not set.
    """
    from tests.conftest import make_bridge_factory

    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="tune_to_interp"),
    )

    # --- Step 1: apply protocol ---
    interp_input = local_all_records(_WAVENET_TUNING_OUTPUT, storage)

    # Protocol assertions (deterministic — same in both modes)
    assert len(interp_input.summaries) == 1
    summary = interp_input.summaries[0]
    assert summary.model_type == "wavenet"
    assert summary.completed_rounds == 2
    assert summary.best_denoising_score == pytest.approx(5.576, abs=0.001)
    assert summary.worst_denoising_score == pytest.approx(5.21, abs=0.001)
    assert summary.best_file_vector is not None
    assert len(summary.best_file_vector) == 20
    assert summary.best_file_vector[0] < 1.0, "low-freq file 0 should be weak"
    assert summary.best_file_vector[19] > 7.0, "high-freq file 19 should be strong"
    assert len(summary.round_scores) == 2
    assert len(summary.round_conclusions) == 2

    # Phase 6 A — hard assertion that score tables flow through the protocol.
    # These fields were added in Phase 3 but only verified in isolation until now.
    assert summary.best_score_table is not None, (
        "local_all_records must propagate best_score_table from HyperparamTuningOutput "
        "to ModelRunSummary — Phase 4 data contract."
    )
    assert summary.best_score_table.rendered_markdown, (
        "summary.best_score_table.rendered_markdown must be non-empty so the "
        "interpreter / proposer can drop it into prompts verbatim."
    )
    assert "| file | raw_baseline | ground_truth |" in summary.best_score_table.rendered_markdown, (
        "best_score_table.rendered_markdown must carry the canonical three-column "
        "header emitted by render_comparison_table."
    )
    assert summary.best_score_table.aggregate.model_scalar == pytest.approx(5.576, abs=0.001)

    assert summary.formal_score_table is not None, (
        "local_all_records must propagate formal_score_table (Phase 3 field) "
        "through to ModelRunSummary."
    )
    assert summary.formal_score_table.rendered_markdown, (
        "summary.formal_score_table.rendered_markdown must be non-empty."
    )
    assert "| file | raw_baseline | ground_truth |" in summary.formal_score_table.rendered_markdown

    # --- Step 2: run interpretation agent ---
    bridge_factory = make_bridge_factory(request, "result_interpretation_agent")
    agent = ResultInterpretationAgent(bridge_factory=bridge_factory)

    output = agent.run(interp_input)

    # --- Step 3: validate output ---
    assert isinstance(output, InterpretationOutput)
    assert "wavenet" in output.model_types
    assert output.best_denoising_score == pytest.approx(5.576, abs=0.001)
    assert output.total_experiments == 2
    assert len(output.key_findings) > 0
    assert len(output.bottlenecks) > 0
    assert len(output.take_home_message) > 10

    # Phase 6 A — required (no soft guards). The score_table contract is the
    # communication channel for Phases 3→5; if the interpreter stops emitting
    # per_model_score_tables, the proposer's prompt render breaks silently.
    assert output.per_model_score_tables is not None, (
        "InterpretationOutput must carry per_model_score_tables — Phase 4 "
        "hard-swap removed per_model_file_vectors in favor of this field."
    )
    assert "wavenet" in output.per_model_score_tables, (
        "per_model_score_tables must include the model_type seen in input summaries."
    )
    table = output.per_model_score_tables["wavenet"]
    assert table is not None
    assert table.rendered_markdown, (
        "per_model_score_tables['wavenet'].rendered_markdown must be non-empty "
        "so the proposer's stage prompts can embed it verbatim."
    )
    assert "| file | raw_baseline | ground_truth |" in table.rendered_markdown, (
        "Rendered markdown must match the render_comparison_table canonical header."
    )

    # Low/high-frequency sanity — synthesized from rows[i].model. Now
    # unconditional because the table itself is required above.
    fv = [r.model for r in table.rows]
    assert fv[0] is not None and fv[0] < 1.0, "low-freq file 0 should be weak in output score table"
    assert fv[19] is not None and fv[19] > 7.0, (
        "high-freq file 19 should be strong in output score table"
    )

    # Storage: output file written
    assert (tmp_path / "interpretation_tune_to_interp.json").exists()

    print(
        f"\n  [tune→interp] wavenet best={output.best_denoising_score:.4f} "
        f"rounds={output.total_experiments} "
        f"findings={len(output.key_findings)}"
    )
