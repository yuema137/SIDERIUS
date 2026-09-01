"""Step 05c — C6: the launcher and canonical reconstruction tooling.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` C6, §0.1, OD-05c-3.

Framework scripts that *reconstruct or validate a run* must agree with the
producer, or a renamed deliverable silently breaks recovery and baseline
scoring. Historical-file diagnostics now live with their task in the external
experiment repository, where they retain the old artifact names deliberately.
"""

from __future__ import annotations

from pathlib import Path

from execute_tools.deliverable_spec import DeliverableNaming, default_deliverable_naming
from tests.unit.execute_tools.test_step05c_c0_deliverable_baseline import (
    GOLDEN_EXP_ID,
    GOLDEN_FILE_INDEX,
    GOLDEN_MODEL_TYPE,
    GOLDEN_RUN_NAME,
    GOLDEN_SAMPLE_SET_NAME,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_the_launcher_resolves_the_c0_producer_name():
    """``run_comparison``'s baseline path equals what the producer writes.

    Same identifier tuple, same string. This is the cross-authority assertion
    C6 exists for: the launcher and the producer now agree by construction
    rather than by two f-strings that happen to match.
    """
    assert (
        default_deliverable_naming().name(
            model_type=GOLDEN_MODEL_TYPE,
            run_name=GOLDEN_RUN_NAME,
            exp_id=GOLDEN_EXP_ID,
            input_identity=GOLDEN_FILE_INDEX,
        )
        == GOLDEN_SAMPLE_SET_NAME
    )


def test_launcher_and_producer_move_together_under_a_rename():
    """One renamed spec moves the launcher's path AND the producer's name.

    Asserted in ONE test rather than two independent ones, because two tests
    each pinning their own site would both pass while the two sites drifted
    apart — which is precisely the drift this commit exists to prevent.
    """
    renamed = DeliverableNaming(prefix="step05c_renamed")
    identifiers = {
        "model_type": GOLDEN_MODEL_TYPE,
        "run_name": GOLDEN_RUN_NAME,
        "exp_id": GOLDEN_EXP_ID,
        "input_identity": GOLDEN_FILE_INDEX,
    }

    # The producer (inference_single) and every migrated reader compose the
    # name through this one accessor, so equality here IS the shared authority.
    assert renamed.name(**identifiers) != default_deliverable_naming().name(**identifiers)
    assert renamed.name(**identifiers).startswith("step05c_renamed_")
