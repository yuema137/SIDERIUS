"""Step 05c — C5: the persisted-output encoding derives from the contract.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` C5, §2.1, §2.2.

**The only commit that can move a written byte.** Failure class 2 says a byte
change is not a refactor — the deliverable is scientific evidence, and one
moved sample moves every downstream score. So the mandatory assertion here is
not "the dtype is still int8"; it is that **every persisted sample value** is
identical to the C0 golden.

**Three authorities, kept separate** (§2.1). The migration is decided by the
per-literal classification, never by the token:

===========================  ======================  ===================
site                         class                   disposition
===========================  ======================  ===================
``:216-218`` int16 + 128     input decode            NOT migrated
``argmax(dim=1)``            model-output decode     NOT migrated
``- value_offset`` on return persisted-output        DeliverableSpec
output buffers, writer casts persisted-output        DeliverableSpec
reuse-check dtype + channels persisted-output        DeliverableSpec
===========================  ======================  ===================

That the TIDMAD offset is ``128`` on *both* the input-decode and the
output-encode side is a coincidence of one task, made safe: the spec DERIVES
its offset from ``DatasetProfile.encoding``, so the two now agree by
derivation instead of by two literals that happen to match.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from execute_tools.dataset_config import ValueEncoding, resolve_dataset_profile
from execute_tools.deliverable_spec import (
    DeliverableStorage,
    derive_tidmad_deliverable_spec,
)
from execute_tools.inference_single import _is_complete_trial_output, _persisted_storage
from tests.unit.execute_tools.test_step05c_c0_deliverable_baseline import (
    INPUT_SAMPLES,
    TARGET_SAMPLES,
    canonical_h5_inspection,
)

_INFERENCE_SOURCE = Path(__file__).resolve().parents[3] / "execute_tools" / "inference_single.py"

TIDMAD_STORAGE = derive_tidmad_deliverable_spec(resolve_dataset_profile()).storage


# ---------------------------------------------------------------------------
# The mandatory assertion: no sample value moved
# ---------------------------------------------------------------------------


def test_the_derived_offset_and_dtype_equal_their_former_literals():
    """``128`` and ``int8`` — asserted against hardcoded numbers.

    Not a round-trip through the spec: hardcoded, so a profile edit that
    silently moved the persisted representation reds here rather than
    surfacing months later as a shifted score.
    """
    assert TIDMAD_STORAGE.value_offset == 128
    assert TIDMAD_STORAGE.storage_dtype == "int8"


def test_the_full_encode_decode_round_trip_is_value_exact():
    """Encode-then-decode returns the original samples, at the int8 extremes.

    The production arithmetic in one line: the input side widens and adds the
    offset (``:217-218``), the output side subtracts it and casts back at the
    writer boundary. If the derived offset differed from the input-side
    literal by even one, ``-128`` would wrap to ``127`` here and every
    downstream score would move — which is exactly failure class 2 and exactly
    what a dtype-only assertion would miss.
    """
    stored = np.asarray(INPUT_SAMPLES, dtype=np.int8)

    decoded = stored.astype(np.int16) + resolve_dataset_profile().encoding.value_offset
    re_encoded = (decoded - TIDMAD_STORAGE.value_offset).astype(TIDMAD_STORAGE.storage_dtype)

    assert re_encoded.tolist() == stored.tolist()
    assert re_encoded.dtype == np.dtype("int8")


def test_the_offset_derives_from_the_profile_rather_than_matching_it():
    """The output offset IS the profile's, by derivation — not a second copy.

    §2.1's rule: it must not be the case that some output-storage sites read
    the spec while others independently re-read ``DatasetProfile.encoding``.
    Under a contrast encoding the two must still be one value; two literals
    that merely agree under TIDMAD would diverge here.
    """
    live = resolve_dataset_profile()
    contrast = live.model_copy(
        update={
            "encoding": ValueEncoding(
                storage_dtype="int16",
                compute_dtype="int32",
                value_offset=32768,
                num_classes=65536,
            )
        }
    )

    derived = derive_tidmad_deliverable_spec(contrast).storage

    assert derived.value_offset == contrast.encoding.value_offset
    assert derived.storage_dtype == contrast.encoding.storage_dtype


# ---------------------------------------------------------------------------
# Reachability — process_batch reads the contract, not a literal
# ---------------------------------------------------------------------------


def test_process_batch_subtracts_the_contract_offset():
    """The real ``process_batch`` return applies the spec's offset.

    Driven through the actual function with a stub model, so this is
    behavioural rather than structural: a contrast offset must change the
    returned values. If ``- 128`` had survived, the contrast run would return
    the same numbers as the TIDMAD run.
    """
    torch = pytest.importorskip("torch")

    import execute_tools.inference_single as inference_single

    class _Tiny(torch.nn.Module):
        def forward(self, x):
            batch, time_steps = x.shape
            out = torch.zeros(batch, 256, time_steps)
            out[:, 200, :] = 1.0
            return out

    model = _Tiny().eval()
    inputarr = np.zeros((1, 1, 4), dtype=np.int8)
    targetarr = np.zeros((1, 1, 4), dtype=np.int8)

    tidmad_args = SimpleNamespace(
        denoising_model="punet",
        _deliverable_spec=derive_tidmad_deliverable_spec(resolve_dataset_profile()),
    )
    contrast_args = SimpleNamespace(
        denoising_model="punet",
        _deliverable_spec=derive_tidmad_deliverable_spec(resolve_dataset_profile()).model_copy(
            update={
                "storage": DeliverableStorage(
                    input_channel_group="channel0001",
                    target_channel_group="channel0002",
                    storage_dtype="int16",
                    value_offset=0,
                )
            }
        ),
    )

    _, tidmad_denoised, _ = inference_single.process_batch(
        0, inputarr, targetarr, model, tidmad_args, "ce"
    )
    _, contrast_denoised, _ = inference_single.process_batch(
        0, inputarr, targetarr, model, contrast_args, "ce"
    )

    # argmax picks class 200; TIDMAD returns it shifted back by 128.
    assert tidmad_denoised.tolist() == [72, 72, 72, 72]
    assert contrast_denoised.tolist() == [200, 200, 200, 200]


def test_persisted_storage_defaults_when_no_spec_was_carried():
    """A caller that never set ``args._deliverable_spec`` gets the shipped value.

    Mirrors the ``_model_io`` two-case rule on this same boundary: absent keeps
    Regime A. Without it, ``test_gpu_milestone_trace``'s direct
    ``process_batch`` call — which builds its own ``SimpleNamespace`` — would
    raise, and every legacy caller would too.
    """
    assert _persisted_storage(SimpleNamespace(denoising_model="punet")) == TIDMAD_STORAGE


def test_the_reuse_check_reads_the_contract_channels_and_dtype(tmp_path):
    """``_is_complete_trial_output`` validates against the SPEC, not literals.

    A site the §0 census missed, and the miss mattered: it reads the
    attempt's OWN deliverable, so under a contrast channel identity the
    inlined ``channel0001`` lookup raised ``KeyError`` -> ``return False``,
    declaring every completed output incomplete and silently re-running
    inference over data that was already correct.
    """
    from execute_tools.array2h5 import create_abra_file

    contrast = DeliverableStorage(
        input_channel_group="sensor_a",
        target_channel_group="sensor_b",
        storage_dtype="int8",
        value_offset=128,
    )
    out = str(tmp_path / "deliverable.h5")
    create_abra_file(
        out,
        np.asarray(INPUT_SAMPLES, dtype=np.int8),
        np.asarray(TARGET_SAMPLES, dtype=np.int8),
        indexed=False,
        storage=contrast,
    )

    assert _is_complete_trial_output(out, len(INPUT_SAMPLES), contrast) is True
    # The TIDMAD storage cannot find those groups — the pre-05c behaviour, and
    # the reason the site had to migrate.
    assert _is_complete_trial_output(out, len(INPUT_SAMPLES), TIDMAD_STORAGE) is False


def test_a_written_artifact_follows_a_contrast_storage_dtype(tmp_path):
    """The persisted dtype follows the contract end to end.

    Buffer allocation, the writer-boundary cast and the file on disk must all
    agree with ``storage_dtype``; asserting the dtype on the artifact is the
    only place all three are visible together.
    """
    from execute_tools.array2h5 import create_abra_file

    contrast = DeliverableStorage(
        input_channel_group="channel0001",
        target_channel_group="channel0002",
        storage_dtype="int16",
        value_offset=32768,
    )
    out = str(tmp_path / "wide.h5")
    create_abra_file(
        out,
        np.asarray(INPUT_SAMPLES, dtype=contrast.storage_dtype),
        np.asarray(TARGET_SAMPLES, dtype=contrast.storage_dtype),
        indexed=False,
        storage=contrast,
    )

    inspection = canonical_h5_inspection(out)
    assert {d["dtype"] for d in inspection["datasets"].values()} == {"int16"}
    assert inspection["datasets"]["timeseries/channel0001/timeseries"]["values"] == list(
        INPUT_SAMPLES
    )


# ---------------------------------------------------------------------------
# What must NOT have moved
# ---------------------------------------------------------------------------


def test_the_input_decode_sites_are_untouched():
    """``astype(np.int16) + 128`` at the input stays exactly as it was.

    An Input-Dataset-Contract fact. Migrating it into a producer contract is
    the specific mistake §2.2's per-literal audit exists to prevent, and it
    would not fail any deliverable-side assertion — the file would still be
    written correctly, from wrongly decoded input.
    """
    source = _INFERENCE_SOURCE.read_text()

    assert "inputarr = inputarr.astype(np.int16) + 128" in source
    assert "targetarr = targetarr.astype(np.int16) + 128" in source


def test_the_output_decode_branch_is_still_keyed_on_the_output_contract():
    """``argmax`` stays inside the ``is_regression`` branch, keyed on I15.

    Model-output decoding belongs to the Model-I/O contract. Re-keying it on
    the loss, a model name, or the deliverable spec is a §7 failure class 3
    boundary breach.
    """
    source = _INFERENCE_SOURCE.read_text()

    assert "output_type = get_output_type(args.denoising_model)" in source
    assert "output_seq = output.argmax(dim=1).detach().cpu().numpy()" in source


def test_no_persisted_output_site_restates_the_storage_dtype():
    """The semantic form of C5's acceptance, not a token ban.

    §C5 replaces revision 2's *"no `128`, `int8` or `256` literal remains"* —
    which was vacuous, since both ``256`` occurrences are comments and
    ``128``/``int16`` legitimately remain on the input-decode path. What must
    hold is that no **executed** ``np.int8`` survives: every output buffer
    allocation and writer-boundary cast reads the contract.
    """
    tree = ast.parse(_INFERENCE_SOURCE.read_text())

    int8_attribute_uses = [
        node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "int8"
    ]

    assert int8_attribute_uses == [], "an executed np.int8 survived on the persisted-output path"


@pytest.mark.parametrize("bad_dtype", ["float32", "int64", "not_a_dtype", ""])
def test_an_unwritable_storage_dtype_is_rejected_at_construction(bad_dtype):
    """A dtype the buffers could not be allocated as fails at run start.

    Any ``str`` satisfies the annotation, and an unknown name does not raise
    until ``np.zeros(..., dtype=…)`` runs — after an attempt's training and
    inference cost is already spent. This moves the failure to construction.
    """
    with pytest.raises(ValidationError):
        DeliverableStorage(
            input_channel_group="channel0001",
            target_channel_group="channel0002",
            storage_dtype=bad_dtype,
            value_offset=128,
        )
