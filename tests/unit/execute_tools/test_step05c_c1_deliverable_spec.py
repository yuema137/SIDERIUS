"""Step 05c — C1: the provisional ``DeliverableSpec``, still inert.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` §3.1, §3.2a, C1.

The type exists and is correct is a **different claim** from production uses
it, with different failure modes — so C1 proves only the first, and asserts
the second is not yet true (zero production importers). Every name and glob
expectation is compared against the **C0 capture**, never re-derived by
calling the spec twice.
"""

from __future__ import annotations

import glob
import os

import pytest
from pydantic import ValidationError

from execute_tools.dataset_config import (
    ChannelIdentity,
    DatasetProfile,
    ValueEncoding,
    resolve_dataset_profile,
)
from execute_tools.deliverable_spec import (
    DeliverableNaming,
    DeliverableStorage,
    default_deliverable_naming,
    derive_tidmad_deliverable_spec,
)
from tests.unit.core.test_step05c_c0_launch_cleanup_baseline import (
    EXP_ID as C0_EXP_ID,
)
from tests.unit.core.test_step05c_c0_launch_cleanup_baseline import (
    MODEL_TYPE as C0_MODEL_TYPE,
)
from tests.unit.core.test_step05c_c0_launch_cleanup_baseline import (
    RUN_NAME as C0_RUN_NAME,
)
from tests.unit.core.test_step05c_c0_launch_cleanup_baseline import (
    SEEDED_FILES,
)
from tests.unit.execute_tools.test_step05c_c0_deliverable_baseline import (
    GOLDEN_EXP_ID,
    GOLDEN_FILE_INDEX,
    GOLDEN_FIX_MODE_NAME,
    GOLDEN_MODEL_TYPE,
    GOLDEN_RUN_NAME,
    GOLDEN_SAMPLE_SET_NAME,
)

# ---------------------------------------------------------------------------
# Naming — resolved against the C0 goldens
# ---------------------------------------------------------------------------


def test_spec_resolves_the_c0_producer_names():
    """Both production name shapes, equal to what the inlined literals build.

    If this fails, C3 would migrate the producers onto a spec that writes
    files the readers and the scorer cannot find — failure class 1, shipped
    deliberately. This is the assertion that makes the whole migration safe to
    perform at all.
    """
    naming = default_deliverable_naming()

    assert (
        naming.name(
            model_type=GOLDEN_MODEL_TYPE,
            run_name=GOLDEN_RUN_NAME,
            exp_id=GOLDEN_EXP_ID,
            input_identity=GOLDEN_FILE_INDEX,
        )
        == GOLDEN_SAMPLE_SET_NAME
    )
    assert (
        naming.unqualified_name(model_type=GOLDEN_MODEL_TYPE, input_identity=GOLDEN_FILE_INDEX)
        == GOLDEN_FIX_MODE_NAME
    )


def test_globs_match_exactly_the_c0_cleanup_sets(tmp_path):
    """The two glob accessors reproduce the C0 deleted sets — and, just as
    load-bearing, leave the C0 survivors alone.

    The two shapes differ deliberately (exp-keyed vs fully qualified). A
    single accessor, or one accidentally "tidied" into the other's shape,
    either stops reclaiming disk or deletes a concurrent attempt's artifacts.
    Only comparing both match sets against the capture catches that.
    """
    for name in SEEDED_FILES:
        (tmp_path / name).write_bytes(b"x")
    naming = default_deliverable_naming()

    experiment_matched = sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(str(tmp_path), naming.experiment_glob(exp_id=C0_EXP_ID)))
    )
    attempt_matched = sorted(
        os.path.basename(p)
        for p in glob.glob(
            os.path.join(
                str(tmp_path),
                naming.attempt_glob(
                    model_type=C0_MODEL_TYPE, run_name=C0_RUN_NAME, exp_id=C0_EXP_ID
                ),
            )
        )
    )

    assert experiment_matched == [
        "abra_validation_denoised_fcnet_c0run_c0exp_0000.h5",
        "abra_validation_denoised_fcnet_c0run_c0exp_0007.h5",
        "abra_validation_denoised_wavenet_otherrun_c0exp_0003.h5",
    ]
    assert attempt_matched == [
        "abra_validation_denoised_fcnet_c0run_c0exp_0000.h5",
        "abra_validation_denoised_fcnet_c0run_c0exp_0007.h5",
    ]
    # Neither glob may reach the raw input, the checkpoint, the non-.h5
    # sidecar, or another experiment's artifact.
    untouchable = {
        "abra_validation_0000.h5",
        "abra_validation_denoised_fcnet_c0run_c0exp_0000.txt",
        "abra_validation_denoised_fcnet_c0run_otherexp_0000.h5",
        "model_fcnet_c0exp_agent.pth",
    }
    assert untouchable.isdisjoint(experiment_matched)
    assert untouchable.isdisjoint(attempt_matched)


def test_file_index_parse_is_the_inverse_of_name():
    """``file_index_of`` inverts ``name`` — and rejects a non-deliverable.

    ``v18_wave_summary.py:55`` carries its own regex for this today, which is
    a second restatement of the template: rename the deliverable and the
    auditor silently stops recognising any artifact, reporting a clean
    workspace. Round-tripping through one authority is what removes that.
    """
    naming = default_deliverable_naming()

    for index in (0, 7, 19, 9999):
        resolved = naming.name(model_type="wavenet", run_name="r", exp_id="e", input_identity=index)
        assert naming.input_identity_of(resolved) == index

    # The fix-mode shape parses too, and MUST: it is a deliverable of this
    # spec and it does carry a file index. The production regex it replaces
    # (``v18_wave_summary.py:55``) matches it for the same reason.
    assert (
        naming.input_identity_of(naming.unqualified_name(model_type="wavenet", input_identity=3))
        == 3
    )

    assert naming.input_identity_of("abra_validation_0000.h5") is None
    assert naming.input_identity_of("abra_validation_denoised_fcnet_run_exp_0000.txt") is None


def test_every_accessor_moves_with_one_renamed_prefix():
    """One field changes and ALL SIX accessors follow.

    This is the property the whole contract exists for, asserted at the type
    before any production site depends on it: five independent restatements of
    a template cannot be renamed together, and one declaration can.
    """
    renamed = DeliverableNaming(prefix="step05c_renamed")

    assert (
        renamed.name(model_type="wavenet", run_name="r", exp_id="e", input_identity=1)
        == "step05c_renamed_wavenet_r_e_0001.h5"
    )
    assert (
        renamed.unqualified_name(model_type="wavenet", input_identity=1)
        == "step05c_renamed_wavenet_0001.h5"
    )
    assert (
        renamed.attempt_glob(model_type="wavenet", run_name="r", exp_id="e")
        == "step05c_renamed_wavenet_r_e_*.h5"
    )
    assert renamed.experiment_glob(exp_id="e") == "step05c_renamed_*_e_*.h5"
    assert renamed.any_glob() == "step05c_renamed_*.h5"
    assert renamed.input_identity_of("step05c_renamed_wavenet_r_e_0001.h5") == 1
    # ...and the TIDMAD name is no longer recognised, which is what proves the
    # accessors read the field rather than a captured constant.
    assert renamed.input_identity_of(GOLDEN_SAMPLE_SET_NAME) is None


@pytest.mark.parametrize("bad_prefix", ["", "  ", " abra ", "abra_*_denoised"])
def test_degenerate_prefix_is_rejected_at_construction(bad_prefix):
    """A prefix that would resolve a destructive glob fails loudly.

    Not a declaration test: an empty prefix is a perfectly valid ``str``, and
    Pydantic accepts it. What it produces is a cleanup pattern of ``_*.h5``
    (or, with a wildcard, ``abra_*_denoised_*_e_*.h5``) that matches files
    this run never wrote — and the consumer of that pattern calls
    ``os.remove``. The only place the value is visible before it reaches a
    filesystem operation is here.
    """
    with pytest.raises(ValidationError):
        DeliverableNaming(prefix=bad_prefix)


def test_identical_channel_groups_are_rejected():
    """Writing the denoised and injected signals to one group is refused.

    It would not raise anywhere downstream: ``create_abra_file`` would create
    the group, write the denoised samples, then overwrite them with the
    injected truth — producing a readable file whose score is meaningless.
    """
    with pytest.raises(ValidationError):
        DeliverableStorage(
            input_channel_group="channel0001",
            target_channel_group="channel0001",
            storage_dtype="int8",
            value_offset=128,
        )


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def test_tidmad_derivation_reproduces_the_inlined_literals():
    """The shipped profile derives exactly the values the seven sites inline.

    ``channel0001`` / ``channel0002`` from ``array2h5.py:49,63``; ``int8``
    from the output buffers at ``inference_single.py:690-691``; ``128`` from
    the ``- 128`` at ``:318``. Asserted against hardcoded numbers, so a
    profile change that silently moved the persisted representation would red
    here rather than in a scientific result months later.
    """
    spec = derive_tidmad_deliverable_spec(resolve_dataset_profile())

    assert spec.storage.input_channel_group == "channel0001"
    assert spec.storage.target_channel_group == "channel0002"
    assert spec.storage.storage_dtype == "int8"
    assert spec.storage.value_offset == 128
    assert (
        spec.naming.name(
            model_type=GOLDEN_MODEL_TYPE,
            run_name=GOLDEN_RUN_NAME,
            exp_id=GOLDEN_EXP_ID,
            input_identity=GOLDEN_FILE_INDEX,
        )
        == GOLDEN_SAMPLE_SET_NAME
    )


def test_derivation_survives_the_persisted_execution_input_round_trip():
    """A profile that has crossed the transport derives the SAME spec.

    ``dataset_profile_{exp_id}.json`` is written by the parent and loaded by
    the child; §3.2a's whole equality argument is that both sides derive from
    it. Round-tripping through ``model_dump``/``model_validate`` is that
    transport's serialization step, and it is also §3.3's replay property in
    miniature: a stored run's existing values construct the identical spec,
    with no migration and no new field.
    """
    live = resolve_dataset_profile()
    restored = DatasetProfile.model_validate(live.model_dump())

    assert derive_tidmad_deliverable_spec(restored) == derive_tidmad_deliverable_spec(live)


def test_contrast_profile_moves_storage_and_leaves_naming_fixed():
    """A different channel identity and encoding move the STORAGE half only.

    The naming half must not follow, because a deliverable's name is a frozen
    compatibility literal and not a property of the input dataset. If naming
    tracked the profile, every task would silently rename artifacts that
    already exist on disk.
    """
    live = resolve_dataset_profile()
    contrast = live.model_copy(
        update={
            "channels": ChannelIdentity(input_channel="sensor_a", target_channel="sensor_b"),
            "encoding": ValueEncoding(
                storage_dtype="int16",
                compute_dtype="int32",
                value_offset=32768,
                num_classes=65536,
            ),
        }
    )

    spec = derive_tidmad_deliverable_spec(contrast)

    assert spec.storage.input_channel_group == "sensor_a"
    assert spec.storage.target_channel_group == "sensor_b"
    assert spec.storage.storage_dtype == "int16"
    assert spec.storage.value_offset == 32768
    assert spec.naming == default_deliverable_naming()


# ---------------------------------------------------------------------------
# Inertness
# ---------------------------------------------------------------------------
#
# C1's inertness assertion — "zero production importers" — lived here and did
# its job: it went red the moment C2 wired the first production consumer, which
# is exactly when it should. It was not deleted but INVERTED, into
# ``tests/unit/core/test_step05c_c2_reader_migration.py::
# test_only_the_censused_sites_consume_the_deliverable_spec`` — the same
# concept (which production sites hold this authority) asserted in the
# direction that stays meaningful for the rest of the PR, including the
# boundary sites that must NEVER import it.
