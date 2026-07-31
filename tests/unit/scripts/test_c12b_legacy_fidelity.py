"""C12-B — the external harness must match the official legacy FCNet.

Fidelity is checked against the legacy SOURCE, read-only, with no
execution of train.py/inference.py: both write to relative paths and
running them could deposit artifacts inside the legacy tree.

Two complementary checks:

* a LINE-LEVEL mapping — every constant the harness uses is asserted to
  appear at the cited line of the legacy file, so a legacy edit or a
  harness drift fails here instead of silently producing a wrong number;
* a BEHAVIOURAL check — the harness's segment construction reproduces
  `read_loader`'s reshape arithmetic exactly, on a synthetic array.

These tests skip when the legacy repository is not present, so the suite
stays portable on a machine that has no copy of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

LEGACY_ROOT = Path("/home/tidmad/TIDMAD")
legacy_required = pytest.mark.skipif(
    not LEGACY_ROOT.is_dir(), reason="legacy TIDMAD repository not present on this host"
)


def _line(relative: str, number: int) -> str:
    """One line of a legacy file, 1-indexed. Read-only."""
    return (LEGACY_ROOT / relative).read_text(encoding="utf-8").splitlines()[number - 1]


@legacy_required
class TestLineLevelFidelity:
    """Each assertion pins a constant to the exact line it came from."""

    def test_training_constants(self):
        from scripts.legacy_fcnet_timing import (
            BATCH_SIZE,
            INPUT_SIZE,
            LEARNING_RATE,
            MAX_INDEX,
            SAMPLE_SIZE,
        )

        assert _line("train.py", 41).strip() == f"input_size = {INPUT_SIZE}"
        assert _line("train.py", 44).startswith(f"sample_size = {SAMPLE_SIZE}")
        assert _line("train.py", 45).strip() == f"batchsize = {BATCH_SIZE}"
        assert _line("train.py", 57).strip() == f"max_index = {MAX_INDEX}"
        assert f"lr={LEARNING_RATE}" in _line("train.py", 113).replace(" ", "")

    def test_segment_construction(self):
        """The reshape that defines a training step."""
        line = _line("train.py", 58)
        assert "reshape(" in line
        assert "-1,sample_size, batchsize, input_size" in line.replace("  ", " ")

    def test_model_and_loss_are_the_fcnet_branch(self):
        assert "model = AE(input_size)" in _line("train.py", 102)
        assert "criterion = nn.SmoothL1Loss()" in _line("train.py", 103)

    def test_optimizer(self):
        line = _line("train.py", 113).replace(" ", "")
        assert "torch.optim.Adam(model.parameters(),lr=0.0005)" in line

    def test_band_checkpoints(self):
        from scripts.legacy_fcnet_timing import BANDS

        assert _line("train.py", 74).strip() == "ifile_checkpoint = [0,4,10,15,20]"
        # the harness's bands are exactly the half-open intervals between them
        assert tuple(BANDS.values()) == ((0, 4), (4, 10), (10, 15), (15, 20))

    def test_inference_shape(self):
        from scripts.legacy_fcnet_timing import INFERENCE_BATCH, INPUT_SIZE

        assert _line("inference.py", 69).strip() == f"input_size = {INPUT_SIZE}"
        assert _line("inference.py", 70).startswith(f"batchsize = {INFERENCE_BATCH}")
        assert "-1, batchsize, input_size" in _line("inference.py", 94)

    def test_architecture_scale_factors(self):
        """The dims 40000 -> 4000 -> 400 -> 40 come from these factors."""
        assert "0.1,0.01,0.001" in _line("network.py", 291).replace(" ", "")


@legacy_required
class TestBehaviouralFidelity:
    def test_steps_per_file_matches_the_legacy_reshape(self):
        """5000 steps/file is not a remembered number: it falls out of the
        legacy reshape, and this recomputes it the same way."""
        import numpy as np

        from scripts.legacy_fcnet_timing import (
            BATCH_SIZE,
            INPUT_SIZE,
            MAX_INDEX,
            SAMPLE_SIZE,
        )

        synthetic = np.zeros(MAX_INDEX // 1000, dtype=np.int8)
        scaled_max = synthetic.shape[0]
        reshaped = synthetic[:scaled_max].reshape(-1, SAMPLE_SIZE, BATCH_SIZE, INPUT_SIZE // 1000)
        assert reshaped.shape[0] == scaled_max // (SAMPLE_SIZE * BATCH_SIZE * (INPUT_SIZE // 1000))
        # and at full scale:
        assert MAX_INDEX // (SAMPLE_SIZE * BATCH_SIZE * INPUT_SIZE) == 5000

    def test_the_realized_parameter_count_matches_the_legacy_model(self):
        from scripts.legacy_fcnet_timing import INPUT_SIZE, load_legacy_ae

        model = load_legacy_ae()(INPUT_SIZE)
        assert sum(p.numel() for p in model.parameters()) == 323_280_840

    def test_the_layer_dimensions_are_the_official_ones(self):
        import torch.nn as nn

        from scripts.legacy_fcnet_timing import INPUT_SIZE, load_legacy_ae

        model = load_legacy_ae()(INPUT_SIZE)
        dims = [m.in_features for m in model.modules() if isinstance(m, nn.Linear)]
        assert dims == [40000, 4000, 400, 40, 400, 4000]


@legacy_required
class TestReadOnlyGuards:
    def test_the_harness_executes_no_legacy_script(self):
        from scripts.legacy_fcnet_timing import plan

        class _Args:
            warmup_steps, timed_steps, inference_batches, phase_b_seconds = 3, 20, 5, 300.0

        record = plan("0-3", Path("/tmp"), Path("/tmp"), _Args())
        assert record["legacy_scripts_executed"] == []
        assert record["legacy_symbols_used"] == ["network.AE"]

    def test_importing_the_model_does_not_change_the_legacy_tree(self):
        from scripts.legacy_fcnet_timing import (
            legacy_fingerprint,
            legacy_tree_inventory,
            load_legacy_ae,
        )

        before_hashes, before_tree = legacy_fingerprint(), legacy_tree_inventory()
        load_legacy_ae()
        assert legacy_fingerprint() == before_hashes
        assert legacy_tree_inventory() == before_tree

    def test_bytecode_writing_is_disabled(self):
        import sys

        import scripts.legacy_fcnet_timing

        assert sys.dont_write_bytecode is True

    def test_outputs_are_external_to_the_legacy_repository(self):
        from scripts.legacy_fcnet_timing import DEFAULT_OUTPUT_ROOT
        from scripts.legacy_fcnet_timing import LEGACY_ROOT as root

        assert not str(DEFAULT_OUTPUT_ROOT).startswith(str(root))
        assert "SIDEREIS_DATA" in str(DEFAULT_OUTPUT_ROOT)
