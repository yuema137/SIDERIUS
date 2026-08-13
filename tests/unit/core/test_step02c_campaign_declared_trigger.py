"""Step 02c C3 — the campaign validator's trigger is the DECLARATION.

Design: ``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/
pr_02c_systematic_groups.md`` §6, §6.1, §11.3.

``validate_experiment_completeness`` runs a per-file completeness check
only for gates that peeked the task's health-peek selection. That
selection used to be a hardcoded ``[3, 10, 17]`` — a second copy of a
value the shipped health config already carried. It now reads the bound
task's declaration.

Two separable properties, and both need saying:

* **Authority moved.** Under a task declaring a DIFFERENT health-peek
  set, that set is what triggers enforcement, and TIDMAD's triplet stops
  triggering it. Nothing in the TIDMAD-only matrix
  (``test_campaign_artifacts.py``) can show this, because there the
  declaration and the old literal are the same three numbers.

* **Policy did NOT move.** The comparison is still exact ordered list
  equality against whatever is declared. A reordered copy of the
  DECLARED set must still take the silent else-branch, exactly as a
  reordered ``[10, 3, 17]`` does today. Comparing as a set — or sorting
  either side — would newly ENFORCE records that are skipped today,
  which is a policy change wearing an authority change's clothes.

The full TIDMAD policy matrix lives in ``test_campaign_artifacts.py``
and is deliberately not duplicated here; this file only covers what a
contrast declaration reveals.
"""

from __future__ import annotations

from core.campaign_artifacts import validate_experiment_completeness
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile

GATE_ID = "output_diversity_blocking"
_CONTRAST_PEEK = [2, 8, 14, 18]
_PER_FILE_ERROR_MARKER = "missing per-file entries"


def _contrast_profile():
    return TIDMAD_PROFILE.model_copy(update={"health_peek_files": _CONTRAST_PEEK})


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
    return validate_experiment_completeness(record, configured_gate_ids=[GATE_ID])


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

    def test_tidmad_s_triplet_stops_triggering_under_another_task(self):
        """The other half of the same claim. Without this, an
        implementation that enforced on the union of "declared OR
        [3,10,17]" would pass the test above."""
        with bind_dataset_profile(_contrast_profile()):
            errors = _errors(_record([3, 10, 17], per_file={}))
        assert not _enforced(errors), (
            "TIDMAD's triplet still triggers enforcement under a task that "
            "declares something else — a hardcoded copy survives"
        )


class TestPolicyDidNotMoveWithTheAuthority:
    def test_a_reordered_declared_set_still_skips(self):
        """The anti-normalization guard, restated against the DECLARATION.

        `test_campaign_artifacts.py` pins this for TIDMAD's order; this
        pins that the property is a property of the COMPARISON, not of
        the particular numbers — a `set()`/`sorted()` rewrite would red
        both, and a rewrite that special-cased TIDMAD would red only this.
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
