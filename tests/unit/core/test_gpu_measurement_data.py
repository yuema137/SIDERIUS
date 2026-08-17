"""The measurement probe batch must be the bytes it has always been.

V20 PR C2 / D-C2-12, then Step 07 / PR 07c C1 and C2.

Gate 2 Lite-A case c1 was killed at 24.10 GiB host RSS **before the model
was built**, because `load_probe_batch` materialized the whole
2,010,000,000-sample channel before `max_segments` was applied. The bounded
replacement reads only the samples the batch needs — but a loader that is
merely *similar* would silently change what is measured, so until 07c the two
were compared **to each other**.

07c removed the unbounded loader (Q-07c-1) and moved the remaining one onto
the resolved `DatasetProfile`, so the comparison target changed with it: this
module now owns the **Checkpoint-0 byte oracle**, a set of goldens captured by
executing the pre-refactor loader at `GOLDEN_CAPTURED_AT`. Comparing to a
frozen value is strictly stronger than comparing two implementations — two
implementations can drift together, a captured hash cannot.

Everything runs against a small deterministic HDF5 fixture with the production
structure. That is the only way to test this: the real dataset would cost
~13 GiB per invocation, which is the defect.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pytest
import torch

from core.runtime_control.gpu_measurement_data import load_bounded_probe_batch
from execute_tools.dataset_config import TIDMAD_PROFILE

REPO_ROOT = Path(__file__).resolve().parents[3]

SEG = 64
BATCH = 4

# 07c C2: the three facts the loader used to hardcode now come from the
# profile, so the test reads them from the same authority the production path
# does. A test that kept its own copies could agree with a builder that had
# stopped reading the profile at all.
INPUT_CHANNEL = TIDMAD_PROFILE.channels.input_channel
TARGET_CHANNEL = TIDMAD_PROFILE.channels.target_channel
CLASS_INDEX_OFFSET = TIDMAD_PROFILE.encoding.value_offset
COMPUTE_DTYPE = TIDMAD_PROFILE.encoding.compute_dtype

# --------------------------------------------------------------------------
# PR 07c Checkpoint 0 — the byte-identity oracle, captured BEFORE the refactor
# --------------------------------------------------------------------------
#
# 07c replaces the measurement path's three hardcoded TIDMAD facts (channel
# name, `+128` offset, `abra_training_*.h5` family) with values derived from
# the resolved `DatasetProfile`. "The bytes did not move" is the property the
# whole PR rests on, and a baseline captured AFTER the edit proves nothing —
# so the numbers below are frozen here, at the pre-edit base, and every later
# producer is measured against them rather than against another loader.

#: The commit these goldens were captured at (master, clean tree, 2026-08-17).
GOLDEN_CAPTURED_AT = "0b92fac90d5279e2292ffa6551f1e4b572d89c2b"

#: sha256 of the produced tensor's buffer per `(batch_size, segment_length)`,
#: byte order pinned little-endian so a golden means the same thing on any
#: host. FOUR geometries, not one: a single matching shape could be luck,
#: while a swapped offset or a transposed reshape shows up as soon as the
#: geometry changes. All four were captured by executing the loader as it
#: stood at `GOLDEN_CAPTURED_AT`, before any 07c production edit.
GOLDEN_BATCH_SHA256_BY_GEOMETRY: dict[tuple[int, int], str] = {
    (1, 16): "060ff4e773e0f261fabb365ce270d05f812fbdd2495cc4a278cd1327601742e7",
    (2, 32): "1c4fc07a1c507594f417d4f467fd3122fda87f5e74ae0dab464ffd6b726323c5",
    (5, 8): "cf032733b6a881658a1895c3d1d06b28c0f90e0a9245414d70674bf3940b939b",
    (4, 64): "dd96e8a1eb32c0ae9ba2c17235a5b98a9f5c1a6b11b79a43988912c5f512f1a7",
}
GOLDEN_BATCH_SHA256 = GOLDEN_BATCH_SHA256_BY_GEOMETRY[(BATCH, SEG)]
GOLDEN_BATCH_DTYPE = torch.int64
GOLDEN_BATCH_SHAPE = (BATCH, SEG)
#: The file the producer must actually OPEN — asserted from the producer's own
#: evidence, never from the configuration handed to it.
GOLDEN_SOURCE_FILE = "abra_training_0000.h5"

#: sha256 of the fixture's own input channel. Pinned separately so a change in
#: the fixture generator (a numpy RNG stream change, an edited geometry) fails
#: as ITSELF rather than being misread as a loader regression.
GOLDEN_FIXTURE_INPUT_SHA256 = "326c7bd699048c55cfe0ca6f273d56830b815ed89dcffa472956f21bccb10018"


def _tensor_sha256(tensor: torch.Tensor) -> str:
    """Hash the tensor's buffer with an explicit byte order."""
    return hashlib.sha256(tensor.numpy().astype("<i8").tobytes()).hexdigest()


def _fixture_samples() -> tuple[np.ndarray, np.ndarray]:
    """The fixture's two channels, generated deterministically.

    Provenance: `np.random.default_rng(20260803)`, 448 int8 samples per
    channel (`SEG * (BATCH + 3)`). The fixture is GENERATED rather than
    committed — numpy's PCG64 stream is stable across versions and platforms,
    so this is machine-independent without carrying a binary blob in git, and
    `GOLDEN_FIXTURE_INPUT_SHA256` pins the result either way.

    The two channels get DIFFERENT values on purpose — a loader that read
    `channel0002` would pass a same-shape check and fail here.
    """
    rng = np.random.default_rng(20260803)
    samples = SEG * (BATCH + 3)
    inputs = rng.integers(-128, 128, size=samples, dtype=np.int8)
    targets = rng.integers(-128, 128, size=samples, dtype=np.int8)
    return inputs, targets


def write_probe_fixture(
    directory: Path, inputs: np.ndarray, targets: np.ndarray, *, name: str = GOLDEN_SOURCE_FILE
) -> Path:
    """Write a miniature TIDMAD file: same paths, same dtypes, tiny.

    A missing `h5py` is a FAILURE, not a skip. `h5py` is a hard project
    dependency (`pyproject.toml`) and this is the Checkpoint-0 byte oracle: a
    skipped oracle would let every later 07c commit report green with the one
    measurement that matters missing. SKIP is reserved for genuinely external,
    non-portable resources — a GPU, the real dataset.
    """
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - h5py is a hard dependency
        pytest.fail(
            "h5py is unavailable, so the PR-07c Checkpoint-0 byte oracle cannot "
            f"run. It is a declared project dependency, so this is a broken "
            f"environment, not a skippable condition ({exc!r})."
        )
    path = directory / name
    with h5py.File(path, "w") as handle:
        group = handle.create_group("timeseries")
        group.create_group(INPUT_CHANNEL).create_dataset("timeseries", data=inputs)
        group.create_group(TARGET_CHANNEL).create_dataset("timeseries", data=targets)
    return path


class ProbeBatchObservation(NamedTuple):
    """What a probe-batch producer produced, and which file it opened.

    `source_file` is `None` only for a producer that does not report one; the
    oracle asserts non-vacuity so that cannot become the whole registry.
    """

    tensor: torch.Tensor
    source_file: str | None


ProbeBatchProducer = Callable[[str, int, int], ProbeBatchObservation]


def _observe_bounded_loader(data_dir: str, batch_size: int, segment_length: int):
    result = load_bounded_probe_batch(
        data_dir=data_dir, batch_size=batch_size, segment_length=segment_length
    )
    return ProbeBatchObservation(result.tensor, result.evidence.source_file)


def _observe_profile_builder(data_dir: str, batch_size: int, segment_length: int):
    """The 07c C2 builder, called directly with an explicit profile.

    Registered ALONGSIDE the worker seam rather than instead of it: the seam
    resolves the profile (Regime A) and the builder requires one, so the two
    entries prove the golden holds on both sides of that resolution.
    """
    from execute_tools.probe_batch import build_bounded_probe_batch

    result = build_bounded_probe_batch(
        profile=TIDMAD_PROFILE,
        data_dir=data_dir,
        batch_size=batch_size,
        segment_length=segment_length,
    )
    return ProbeBatchObservation(result.tensor, result.evidence.source_file)


#: Every production path that builds a measurement probe batch. C2 collapsed
#: the two loaders into one profile-derived builder, registered HERE, so it is
#: measured against the same frozen golden instead of growing a second,
#: independently-drifting comparison. The deleted `unbounded_loader` entry was
#: `execute_tools.probe_data.load_probe_batch` (Q-07c-1 = DELETE, no shim).
PROBE_BATCH_PRODUCERS: dict[str, ProbeBatchProducer] = {
    "bounded_loader": _observe_bounded_loader,
    "profile_builder": _observe_profile_builder,
}


@pytest.fixture
def dataset_dir(tmp_path):
    """A miniature TIDMAD file: same paths, same dtypes, tiny."""
    inputs, targets = _fixture_samples()
    write_probe_fixture(tmp_path, inputs, targets)
    return str(tmp_path), inputs, targets


class TestTheCheckpointZeroByteOracle:
    """The frozen pre-refactor capture every 07c commit is measured against."""

    @pytest.mark.parametrize("producer_name", sorted(PROBE_BATCH_PRODUCERS))
    def test_every_producer_matches_the_committed_golden(self, dataset_dir, producer_name):
        """The load-bearing 07c assertion: the BYTES, not the fact that a
        producer ran. A producer that derived the channel, offset or filename
        from somewhere else would still return a same-shaped int64 tensor."""
        data_dir, _, _ = dataset_dir
        observed = PROBE_BATCH_PRODUCERS[producer_name](data_dir, BATCH, SEG)
        assert _tensor_sha256(observed.tensor) == GOLDEN_BATCH_SHA256, (
            f"{producer_name} produced different bytes than the golden captured "
            f"at {GOLDEN_CAPTURED_AT}"
        )
        assert observed.tensor.dtype == GOLDEN_BATCH_DTYPE
        assert tuple(observed.tensor.shape) == GOLDEN_BATCH_SHAPE

    def test_the_file_actually_opened_is_the_golden_one(self, dataset_dir):
        """Asserted from the producer's own evidence, never from the config it
        was handed — the config is what a broken file resolver would echo back."""
        data_dir, _, _ = dataset_dir
        reported = 0
        for name, producer in PROBE_BATCH_PRODUCERS.items():
            observed = producer(data_dir, BATCH, SEG)
            if observed.source_file is None:
                continue
            reported += 1
            assert observed.source_file == GOLDEN_SOURCE_FILE, name
        assert reported >= 1, "no producer reports the file it opened; the oracle is vacuous"

    def test_the_fixture_itself_is_reproducible(self):
        """Pinned separately from the batch so an RNG-stream or geometry change
        fails as itself instead of masquerading as a loader regression."""
        inputs, _ = _fixture_samples()
        assert hashlib.sha256(inputs.tobytes()).hexdigest() == GOLDEN_FIXTURE_INPUT_SHA256
        assert inputs.dtype == np.int8
        assert inputs.size == SEG * (BATCH + 3)

    @pytest.mark.parametrize("geometry", sorted(GOLDEN_BATCH_SHA256_BY_GEOMETRY))
    def test_the_golden_holds_across_geometries(self, dataset_dir, geometry):
        """One matching shape could be luck; a swapped offset or a transposed
        reshape shows up as soon as the geometry changes.

        Inherited intent from the pre-07c `test_they_agree_across_shapes`,
        which compared the bounded loader to the now-deleted unbounded one.
        Comparing to a FROZEN value instead is strictly stronger: two
        implementations can drift together, a captured hash cannot.
        """
        batch, seg = geometry
        data_dir, _, _ = dataset_dir
        observed = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=batch, segment_length=seg
        ).tensor
        assert _tensor_sha256(observed) == GOLDEN_BATCH_SHA256_BY_GEOMETRY[geometry]
        assert tuple(observed.shape) == (batch, seg)
        assert observed.dtype == GOLDEN_BATCH_DTYPE

    def test_a_corrupted_fixture_turns_the_oracle_red(self, tmp_path):
        """Non-vacuity. If the golden matched regardless of the bytes on disk,
        every later 'byte-identical' claim in this PR would be worthless."""
        inputs, targets = _fixture_samples()
        corrupted = inputs.copy()
        corrupted[0] = np.int8(corrupted[0] + 1)
        write_probe_fixture(tmp_path, corrupted, targets)
        observed = _observe_bounded_loader(str(tmp_path), BATCH, SEG)
        assert _tensor_sha256(observed.tensor) != GOLDEN_BATCH_SHA256


class TestTheSemanticsItReproduces:
    def test_segments_are_contiguous_and_in_order(self, dataset_dir):
        """With `sample_size=1` the production path reduces to
        `alltrain[i*seg : (i+1)*seg]`. Segment `i` must be exactly that."""
        data_dir, inputs, _ = dataset_dir
        tensor = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=BATCH, segment_length=SEG
        ).tensor
        for i in range(BATCH):
            expected = inputs[i * SEG : (i + 1) * SEG].astype(COMPUTE_DTYPE) + CLASS_INDEX_OFFSET
            assert torch.equal(tensor[i], torch.as_tensor(expected).long())

    def test_it_reads_the_input_channel_not_the_target(self, dataset_dir):
        """A swap would keep shape, dtype and range, and change every
        measured value."""
        data_dir, inputs, targets = dataset_dir
        tensor = load_bounded_probe_batch(
            data_dir=data_dir, batch_size=1, segment_length=SEG
        ).tensor
        from_input = torch.as_tensor(inputs[:SEG].astype(COMPUTE_DTYPE) + CLASS_INDEX_OFFSET).long()
        from_target = torch.as_tensor(
            targets[:SEG].astype(COMPUTE_DTYPE) + CLASS_INDEX_OFFSET
        ).long()
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
        assert evidence.source_file == GOLDEN_SOURCE_FILE
        assert evidence.channel == INPUT_CHANNEL
        assert evidence.file_sample_count == inputs.size
        assert evidence.fraction_of_file_read < 1.0

    @pytest.mark.parametrize(
        "relative_path",
        [
            # Where the read LIVES after 07c C2 — the one builder.
            "execute_tools/probe_batch.py",
            # And where it used to live, so the module cannot grow one back.
            "core/runtime_control/gpu_measurement_data.py",
        ],
    )
    def test_it_never_materializes_the_whole_channel(self, relative_path):
        """The defect, as a source property: `np.array(channel)` on the full
        dataset is what cost 24.10 GiB.

        Checked over the AST rather than the text -- these modules *document*
        the forbidden call in a comment, and a substring scan cannot tell an
        explanation from an instruction. The repo root comes from this
        file's location, never a relative path.
        """
        import ast

        module = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
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
        with pytest.raises(RuntimeError, match="no declared training file exists"):
            load_bounded_probe_batch(data_dir=str(tmp_path), batch_size=1, segment_length=SEG)

    def test_a_file_without_the_channel_raises_and_says_so(self, tmp_path):
        """It must never quietly widen the read: the unbounded path cannot run
        under the cap, so a silent fallback restores the failure this exists
        to remove."""
        import h5py

        path = tmp_path / GOLDEN_SOURCE_FILE
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
