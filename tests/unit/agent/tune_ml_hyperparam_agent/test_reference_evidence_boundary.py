"""Regression coverage for task-neutral reference-evidence behavior."""

from __future__ import annotations

from pathlib import Path

import nodes.ml_hyperparameter_tune_agent as tuner_module


def test_undeclared_reference_evidence_is_absent() -> None:
    """Catch any restored implicit task baseline or filesystem lookup."""

    assert tuner_module.load_reference_scores() is None


def test_tuner_does_not_bind_a_task_reference_loader() -> None:
    """Catch direct imports or checkout-relative task evidence in the tuner."""

    source = Path(tuner_module.__file__).read_text(encoding="utf-8")

    assert "nodes.scoring_reference" not in source
    assert "reference_data/" not in source
