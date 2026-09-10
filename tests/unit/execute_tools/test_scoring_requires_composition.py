"""Fail-closed intake for the generic scoring child."""

from __future__ import annotations

import pytest

from execute_tools.denoising_score_single import (
    _require_composed_scoring_args,
    build_parser,
    main,
)


def test_scoring_refuses_every_missing_composition_transport() -> None:
    args = build_parser().parse_args([])

    with pytest.raises(ValueError) as excinfo:
        _require_composed_scoring_args(args)

    message = str(excinfo.value)
    for flag in (
        "--task_manifest",
        "--task_data_path_id",
        "--dataset_profile_json",
        "--task_eval_scope_ref",
        "--task_eval_scope_digest",
    ):
        assert flag in message


def test_scoring_accepts_a_complete_composition_transport() -> None:
    args = build_parser().parse_args(
        [
            "--task_manifest",
            "task.yaml",
            "--task_data_path_id",
            "synthetic_task",
            "--dataset_profile_json",
            "profile.json",
            "--task_eval_scope_ref",
            "scope.json",
            "--task_eval_scope_digest",
            "0" * 64,
        ]
    )

    _require_composed_scoring_args(args)


def test_production_entry_refuses_before_any_scientific_default_is_resolved() -> None:
    with pytest.raises(ValueError, match="explicit task composition"):
        main([])
