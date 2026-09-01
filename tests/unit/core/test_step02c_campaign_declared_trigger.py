"""Step 02c C3 — the campaign validator's trigger is the DECLARATION.

Design: ``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/
pr_02c_systematic_groups.md`` §6, §6.1, §11.3.

``validate_experiment_completeness`` runs a per-file completeness check
only for gates that peeked the task's declared health-peek selection.

Two separable properties, and both need saying:

* **Authority is declarative.** Under two tasks declaring different
  health-peek sets, only the active declaration triggers enforcement.

* **Policy did NOT move.** The comparison is still exact ordered-list
  equality against whatever is declared. Comparing as a set, or sorting
  either side, would newly enforce records that are skipped today.

The broader campaign-artifact policy matrix lives in
``test_campaign_artifacts.py`` and is deliberately not duplicated here.
"""

from __future__ import annotations

from core.campaign_artifacts import validate_experiment_completeness
from execute_tools.dataset_config import (
    bind_dataset_profile,
    resolve_dataset_profile,
)
from tests.helpers.two_family_profile import make_two_family_profile

GATE_ID = "output_diversity_blocking"
_CONTRAST_PEEK = [2, 8, 14, 18]
_OTHER_PEEK = [1, 5, 11]
_PER_FILE_ERROR_MARKER = "missing per-file entries"


def _contrast_profile():
    return make_two_family_profile(num_files=20).model_copy(
        update={"health_peek_files": _CONTRAST_PEEK}
    )


def _record(files_requested: list[int], per_file: dict) -> dict:
    return {
        "denoising_score": -1.0,
        "file_vector": [1.0] * 20,
        "checkpoint_path": "/checkpoint.pth",
        "params": {"model_config": {"channels": 8}},
        "health_gate_results": [
            {
                "gate_name": GATE_ID,
                "execution_status": "passed",
                "resolved_action": "continue",
                "aggregation": {"files_requested": files_requested},
                "metrics": {"aggregate_statistics": {"count": 3}, "per_file": per_file},
            }
        ],
    }


def _errors(record: dict) -> list[str]:
    # Step 10 / P1 (S7): the declared peek set is now the caller's explicit
    # argument rather than something the validator pulls from the ambient
    # profile. The value under test is unchanged — what changed is that this
    # fixture now STATES it instead of depending on which profile happened to
    # be resolvable in-process.
    return validate_experiment_completeness(
        record,
        configured_gate_ids=[GATE_ID],
        declared_health_peek=list(resolve_dataset_profile().health_peek_files),
    )


def _enforced(errors: list[str]) -> bool:
    return any(_PER_FILE_ERROR_MARKER in error for error in errors)


class TestTheTriggerFollowsTheDeclaration:
    def test_the_declared_set_triggers_enforcement(self):
        with bind_dataset_profile(_contrast_profile()):
            errors = _errors(_record(list(_CONTRAST_PEEK), per_file={}))
        assert _enforced(errors), (
            "a record requesting the bound task's declared health-peek set was "
            "not enforced — the validator is still keyed on a literal"
        )

    def test_another_declared_selection_does_not_trigger(self):
        """The other half of the same claim. Without this, an
        implementation that enforced on the union of multiple task
        declarations would pass the test above."""
        with bind_dataset_profile(_contrast_profile()):
            errors = _errors(_record(list(_OTHER_PEEK), per_file={}))
        assert not _enforced(errors), (
            "a different task's selection still triggers enforcement under "
            "the active declaration — a second authority survives"
        )


class TestPolicyDidNotMoveWithTheAuthority:
    def test_a_reordered_declared_set_still_skips(self):
        """The anti-normalization guard, restated against the DECLARATION.

        `test_campaign_artifacts.py` pins this for TIDMAD's order; this
        pins that the property is a property of the COMPARISON, not of
        the particular numbers — a `set()`/`sorted()` rewrite would red
        both declaration-driven controls.
        """
        reordered = [_CONTRAST_PEEK[1], _CONTRAST_PEEK[0], *_CONTRAST_PEEK[2:]]
        assert reordered != _CONTRAST_PEEK and sorted(reordered) == sorted(_CONTRAST_PEEK)
        with bind_dataset_profile(_contrast_profile()):
            errors = _errors(_record(reordered, per_file={}))
        assert not _enforced(errors), (
            "a reordered copy of the declared set was enforced. It skips "
            "today; enforcing it is a POLICY change, not an authority change"
        )

    def test_a_complete_per_file_under_the_declaration_is_accepted(self):
        with bind_dataset_profile(_contrast_profile()):
            errors = _errors(
                _record(
                    list(_CONTRAST_PEEK),
                    per_file={str(i): {"execution_status": "passed"} for i in _CONTRAST_PEEK},
                )
            )
        assert errors == []
