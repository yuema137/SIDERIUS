"""Composed single-file attempts must not be labelled as legacy runs (#1183)."""

from dataclasses import replace

from nodes.ml_hyperparameter_tune_agent.contracts import AttemptIdentity, AttemptOrdering
from nodes.ml_hyperparameter_tune_agent.planning import prepare_attempt
from tests.unit.nodes.ml_hyperparameter_tune_agent.test_c12p_b11_composed_seg_size_authoring import (
    _bindings,
    _composed_input,
)


def test_composed_single_file_notice_does_not_claim_legacy_mode(tmp_path, capsys):
    """Exercise the caller: mode alone used to mislabel a composed attempt."""
    bindings = replace(_bindings(_composed_input(), tmp_path), trial_allowed=False)
    prepared = prepare_attempt(
        bindings,
        attempt_ordering=AttemptOrdering(),
        identity=AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=False),
        total_attempts=1,
        attempts_this_round=1,
        formal_trial_winner=None,
    )

    assert prepared.trial_config.mode == "single_file"
    notice = capsys.readouterr().out

    assert "Legacy mode" not in notice
    assert "file_index" not in notice
    assert "Task-owned scope" in notice
    assert "no legacy SampleSet" in notice
