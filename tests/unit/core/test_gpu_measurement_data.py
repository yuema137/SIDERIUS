"""The bounded loader must produce what the production loader produces.

V20 PR C2 / D-C2-12.

Gate 2 Lite-A case c1 was killed at 24.10 GiB host RSS **before the model
was built**, because `load_probe_batch` materializes the whole
2,010,000,000-sample channel before `max_segments` is applied. The bounded
replacement reads only the samples the batch needs — but a loader that is
merely *similar* would silently change what is measured, so the two are
compared directly.

The comparison runs against a small HDF5 fixture with the production
structure, so `load_probe_batch` itself is cheap here. That is the only way
to test this: the real dataset would cost ~13 GiB per invocation, which is
the defect.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from core.runtime_control.gpu_measurement_data import (
    CLASS_INDEX_OFFSET,
    INPUT_CHANNEL,
    TARGET_CHANNEL,
    load_bounded_probe_batch,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

SEG = 64
BATCH = 4


@pytest.fixture
def dataset_dir(tmp_path):
    """A miniature TIDMAD file: same paths, same dtypes, tiny.

    The two channels are given DIFFERENT values on purpose — a loader that
    read `channel0002` would pass a same-shape check and fail here.
    """
    h5py = pytest.importorskip("h5py")
    samples = SEG * (BATCH + 3)
    rng = np.random.default_rng(20260803)
    inputs = rng.integers(-128, 128, size=samples, dtype=np.int8)
    targets = rng.integers(-128, 128, size=samples, dtype=np.int8)
    path = tmp_path / "abra_training_0000.h5"
    with h5py.File(path, "w") as handle:
        group = handle.create_group("timeseries")
        group.create_group(INPUT_CHANNEL).create_dataset("timeseries", data=inputs)
        group.create_group(TARGET_CHANNEL).create_dataset("timeseries", data=targets)
    return str(tmp_path), inputs, targets


class TestItMatchesTheProductionLoaderExactly:
    def test_the_tensors_are_identical(self, dataset_dir):
        """The load-bearing assertion. Everything else here explains a way
        this could fail; this one is the claim."""
        from execute_tools.probe_data import load_probe_batch

        data_dir, _, _ = dataset_dir
        production = load_probe_batch(data_dir=data_dir, batch_size=BATCH, segment_length=SEG)
        bounded = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=BATCH, segment_length=SEG
        ).tensor
        assert torch.equal(bounded, production)

    def test_shape_and_dtype_match(self, dataset_dir):
        from execute_tools.probe_data import load_probe_batch

        data_dir, _, _ = dataset_dir
        production = load_probe_batch(data_dir=data_dir, batch_size=BATCH, segment_length=SEG)
        bounded = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=BATCH, segment_length=SEG
        ).tensor
        assert bounded.shape == production.shape == (BATCH, SEG)
        assert bounded.dtype == production.dtype == torch.long

    @pytest.mark.parametrize("batch,seg", [(1, 16), (2, 32), (5, 8)])
    def test_they_agree_across_shapes(self, dataset_dir, batch, seg):
        """One matching shape could be luck; a swapped offset or a
        transposed reshape shows up as soon as the geometry changes."""
        from execute_tools.probe_data import load_probe_batch

        data_dir, _, _ = dataset_dir
        assert torch.equal(
            load_bounded_probe_batch(
                data_dir=data_dir, batch_size=batch, segment_length=seg
            ).tensor,
            load_probe_batch(data_dir=data_dir, batch_size=batch, segment_length=seg),
        )


class TestTheSemanticsItReproduces:
    def test_segments_are_contiguous_and_in_order(self, dataset_dir):
        """With `sample_size=1` the production path reduces to
        `alltrain[i*seg : (i+1)*seg]`. Segment `i` must be exactly that."""
        data_dir, inputs, _ = dataset_dir
        tensor = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=BATCH, segment_length=SEG
        ).tensor
        for i in range(BATCH):
            expected = inputs[i * SEG : (i + 1) * SEG].astype(np.int16) + CLASS_INDEX_OFFSET
            assert torch.equal(tensor[i], torch.as_tensor(expected).long())

    def test_it_reads_the_input_channel_not_the_target(self, dataset_dir):
        """A swap would keep shape, dtype and range, and change every
        measured value."""
        data_dir, inputs, targets = dataset_dir
        tensor = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=1, segment_length=SEG
        ).tensor
        from_input = torch.as_tensor(inputs[:SEG].astype(np.int16) + CLASS_INDEX_OFFSET).long()
        from_target = torch.as_tensor(targets[:SEG].astype(np.int16) + CLASS_INDEX_OFFSET).long()
        assert torch.equal(tensor[0], from_input)
        assert not torch.equal(tensor[0], from_target), "fixture channels must differ"

    def test_values_land_in_the_class_index_range(self, dataset_dir):
        """The +128 offset turns an int8 sample into a class index; the
        model's embedding has 256 entries, so an off-by-one here is an
        index error at the first forward."""
        data_dir, _, _ = dataset_dir
        tensor = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=BATCH, segment_length=SEG
        ).tensor
        assert int(tensor.min()) >= 0
        assert int(tensor.max()) <= 255


class TestItStaysBounded:
    def test_it_reads_only_what_the_batch_needs(self, dataset_dir):
        data_dir, inputs, _ = dataset_dir
        result = load_bounded_probe_batch(data_dir=data_dir, batch_size=BATCH, segment_length=SEG)
        assert result.evidence.bytes_read == BATCH * SEG
        assert result.evidence.bytes_read < inputs.nbytes
        assert result.evidence.last_sample == BATCH * SEG

    def test_it_records_the_file_it_read_and_how_much_of_it(self, dataset_dir):
        data_dir, inputs, _ = dataset_dir
        evidence = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=BATCH, segment_length=SEG
        ).evidence
        assert evidence.source_file == "abra_training_0000.h5"
        assert evidence.channel == INPUT_CHANNEL
        assert evidence.file_sample_count == inputs.size
        assert evidence.fraction_of_file_read < 1.0

    def test_it_never_materializes_the_whole_channel(self):
        """The defect, as a source property: `np.array(channel)` on the full
        dataset is what cost 24.10 GiB.

        Checked over the AST rather than the text -- this module *documents*
        the forbidden call in a comment, and a substring scan cannot tell an
        explanation from an instruction. The repo root comes from this
        file's location, never a relative path.
        """
        import ast

        module = ast.parse(
            (REPO_ROOT / "core" / "runtime_control" / "gpu_measurement_data.py").read_text(
                encoding="utf-8"
            )
        )
        for node in ast.walk(module):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "array", (
                    "np.array() on an HDF5 dataset reads the whole channel"
                )
            # A bare `channel[:]` is the same materialisation wearing
            # slice syntax.
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
                assert not (
                    node.slice.lower is None
                    and node.slice.upper is None
                    and node.slice.step is None
                ), "a full-range slice reads the whole channel"


class TestItFailsClosedRatherThanFallingBack:
    def test_a_missing_dataset_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="no abra_training"):
            load_bounded_probe_batch(data_dir=str(tmp_path), batch_size=1, segment_length=SEG)

    def test_a_file_without_the_channel_raises_and_says_so(self, tmp_path):
        """It must never quietly reach for `load_probe_batch`: the unbounded
        path cannot run under the cap, so a silent fallback restores the
        failure this exists to remove."""
        h5py = pytest.importorskip("h5py")
        path = tmp_path / "abra_training_0000.h5"
        with h5py.File(path, "w") as handle:
            handle.create_group("timeseries").create_group("wrong_channel")
        with pytest.raises(RuntimeError, match="does not fall back"):
            load_bounded_probe_batch(data_dir=str(tmp_path), batch_size=1, segment_length=SEG)

    def test_a_batch_larger_than_the_file_raises_rather_than_truncating(self, dataset_dir):
        """Silently returning a short batch would measure a smaller
        candidate than the one requested."""
        data_dir, _, _ = dataset_dir
        with pytest.raises(RuntimeError, match="too small"):
            load_bounded_probe_batch(data_dir=data_dir, batch_size=10_000, segment_length=SEG)

    def test_it_never_pads(self, dataset_dir):
        data_dir, inputs, _ = dataset_dir
        exact = inputs.size // SEG
        result = load_bounded_probe_batch(data_dir=data_dir, batch_size=exact, segment_length=SEG)
        assert result.tensor.shape == (exact, SEG)
        assert result.evidence.bytes_read == exact * SEG
