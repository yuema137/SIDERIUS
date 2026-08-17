"""The one profile-derived bounded probe-batch builder (Step 07 / PR 07c C2).

Byte parity against the frozen pre-refactor golden lives in
`tests/unit/core/test_gpu_measurement_data.py`, which owns the Checkpoint-0
oracle. What this module owns is what byte parity CANNOT show: that the facts
now come from the profile, that the file the builder opens is a DECLARED one,
that the read is still exactly as wide as the batch, and that both production
paths actually reach the builder.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from execute_tools.dataset_config import TIDMAD_PROFILE
from execute_tools.probe_batch import build_bounded_probe_batch

REPO_ROOT = Path(__file__).resolve().parents[3]

SEG = 32
BATCH = 3


def _write_file(directory: Path, name: str, *, samples: int) -> np.ndarray:
    """One profile-shaped HDF5 file, deterministic per name."""
    import h5py

    rng = np.random.default_rng(abs(hash(name)) % (2**32))
    inputs = rng.integers(-128, 128, size=samples, dtype=np.int8)
    targets = rng.integers(-128, 128, size=samples, dtype=np.int8)
    with h5py.File(directory / name, "w") as handle:
        group = handle.create_group("timeseries")
        group.create_group(TIDMAD_PROFILE.channels.input_channel).create_dataset(
            "timeseries", data=inputs
        )
        group.create_group(TIDMAD_PROFILE.channels.target_channel).create_dataset(
            "timeseries", data=targets
        )
    return inputs


def _build(data_dir: Path, **over):
    kwargs = {
        "profile": TIDMAD_PROFILE,
        "data_dir": str(data_dir),
        "batch_size": BATCH,
        "segment_length": SEG,
    }
    kwargs.update(over)
    return build_bounded_probe_batch(**kwargs)


class TestItOpensADeclaredFile:
    """Q-07c-2: enumerate the DECLARED indices, take the first that exists."""

    def test_a_gap_at_index_zero_advances_to_the_next_declared_index(self, tmp_path):
        """The predecessor globbed and took `sorted(...)[0]`. Enumerating the
        declared indices must reach the same answer on a gappy directory —
        otherwise 07c would silently change which data is measured."""
        expected = _write_file(tmp_path, "abra_training_0003.h5", samples=SEG * (BATCH + 1))
        result = _build(tmp_path)
        assert result.evidence.source_file == "abra_training_0003.h5"
        first = expected[:SEG].astype(TIDMAD_PROFILE.encoding.compute_dtype)
        first = first + TIDMAD_PROFILE.encoding.value_offset
        assert result.tensor[0].tolist() == first.tolist()

    def test_the_lowest_declared_index_wins_over_a_higher_one(self, tmp_path):
        """Deterministic choice, not directory order."""
        _write_file(tmp_path, "abra_training_0007.h5", samples=SEG * (BATCH + 1))
        _write_file(tmp_path, "abra_training_0002.h5", samples=SEG * (BATCH + 1))
        assert _build(tmp_path).evidence.source_file == "abra_training_0002.h5"

    def test_an_undeclared_file_on_disk_is_never_substituted(self, tmp_path):
        """The real behaviour change. `abra_training_0099.h5` matches the old
        glob and would have been consumed; index 99 is outside the profile's
        declared `num_files`, so the task never claimed that data."""
        _write_file(tmp_path, "abra_training_0099.h5", samples=SEG * (BATCH + 1))
        with pytest.raises(RuntimeError, match="no declared training file exists"):
            _build(tmp_path)

    def test_the_refusal_names_the_declared_range(self, tmp_path):
        """A bare 'not found' cannot be acted on: the operator needs to know
        WHICH names were looked for before checking the directory."""
        with pytest.raises(RuntimeError) as excinfo:
            _build(tmp_path)
        message = str(excinfo.value)
        assert TIDMAD_PROFILE.dataset.training_file_name(0) in message
        assert TIDMAD_PROFILE.dataset.training_file_name(TIDMAD_PROFILE.dataset.num_files - 1) in (
            message
        )


class TestTheReadStaysExactlyAsWideAsTheBatch:
    def test_bytes_read_is_the_exact_slice_including_itemsize(self, tmp_path):
        """`bytes_read == batch x segment_length x itemsize`, EXACTLY.

        This is the bounded-READ property, and it is deliberately not a claim
        about peak host RSS — a real RSS measurement would need a subprocess
        and is not portable. What it does establish is that nothing wider than
        the batch was materialised from HDF5, which is the seam that failed at
        24.10 GiB.
        """
        _write_file(tmp_path, "abra_training_0000.h5", samples=SEG * 40)
        evidence = _build(tmp_path).evidence
        itemsize = np.dtype(TIDMAD_PROFILE.encoding.storage_dtype).itemsize
        assert evidence.bytes_read == BATCH * SEG * itemsize
        assert evidence.file_sample_count == SEG * 40
        assert evidence.fraction_of_file_read < 0.1


class TestTheMeasurementPathHoldsNoTaskLiterals:
    """Checkpoint A/D: the three facts are gone from live measurement code."""

    #: Every module 07c C2 routed through the profile.
    SCANNED = (
        "execute_tools/probe_batch.py",
        "core/runtime_control/gpu_measurement_data.py",
        "core/runtime_control/probe_production.py",
    )

    @pytest.mark.parametrize("relative_path", SCANNED)
    def test_no_channel_offset_or_filename_literal_survives(self, relative_path):
        """Asserted over string/number CONSTANTS in the AST, not over the file
        text: every one of these modules explains the removed literal in a
        docstring or comment, and a substring scan cannot tell an explanation
        from an instruction.
        """
        forbidden_strings = {
            TIDMAD_PROFILE.channels.input_channel,
            TIDMAD_PROFILE.channels.target_channel,
        }
        pattern_stem = TIDMAD_PROFILE.dataset.training_file_pattern.split("{")[0]
        module = ast.parse((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if not isinstance(node, ast.Constant):
                continue
            if isinstance(node.value, str) and not isinstance(node.value, bool):
                # A docstring is an `ast.Constant` too, but it is an
                # explanation; only short literals can be operative values.
                if "\n" not in node.value:
                    assert node.value not in forbidden_strings, (
                        f"{relative_path} still names a channel literally"
                    )
                    assert pattern_stem not in node.value, (
                        f"{relative_path} still names the training filename family"
                    )

    def test_the_value_offset_is_not_an_operative_literal(self):
        """`+128` specifically: it is the one fact whose reintroduction would
        keep every shape and dtype correct and change every measured value."""
        module = ast.parse(
            (REPO_ROOT / "execute_tools" / "probe_batch.py").read_text(encoding="utf-8")
        )
        offsets = [
            n
            for n in ast.walk(module)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, int)
            and not isinstance(n.value, bool)
            and n.value == TIDMAD_PROFILE.encoding.value_offset
        ]
        assert offsets == [], "the class-index offset must come from the profile"


class TestBothProductionPathsReachTheOneBuilder:
    """Checkpoint D reachability. Two paths used to build the batch two ways;
    a test that only exercised one would let the other drift back."""

    def test_the_worker_seam_calls_the_builder(self, tmp_path, monkeypatch):
        import execute_tools.probe_batch as probe_batch
        from core.runtime_control.gpu_measurement_data import load_bounded_probe_batch

        _write_file(tmp_path, "abra_training_0000.h5", samples=SEG * 20)
        calls: list[dict] = []
        real = probe_batch.build_bounded_probe_batch

        def spy(**kwargs):
            calls.append(kwargs)
            return real(**kwargs)

        monkeypatch.setattr(probe_batch, "build_bounded_probe_batch", spy)
        load_bounded_probe_batch(data_dir=str(tmp_path), batch_size=BATCH, segment_length=SEG)
        assert len(calls) == 1
        assert calls[0]["profile"] is not None, "the seam must resolve a profile, never omit one"

    def test_the_in_process_probe_path_calls_the_builder(self, tmp_path, monkeypatch):
        """`probe_production._setup` used the UNBOUNDED loader until C2. It is
        exercised for real here (CPU, tiny model) rather than asserted from
        source, because the whole failure mode was a path that looked right
        and ran something else."""
        import torch.nn as nn
        from pydantic import BaseModel

        import execute_tools.probe_batch as probe_batch
        from core.runtime_control.probe_production import production_probe_executors
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.models_sandbox import MODEL_REGISTRY

        model_type = "pr07c_c2_reachability_probe"

        class _Config(BaseModel):
            segmentation_size: int = SEG

        class _Model(nn.Module):
            def __init__(self, cfg: _Config):
                super().__init__()
                self.embed = nn.Embedding(256, 4)
                self.head = nn.Linear(4, 256)

            def forward(self, x):
                return self.head(self.embed(x.long())).permute(0, 2, 1)

        MODEL_REGISTRY[model_type] = _Model
        PLUGIN_CONFIG_REGISTRY[model_type] = _Config
        try:
            _write_file(tmp_path, "abra_training_0000.h5", samples=SEG * 20)
            calls: list[dict] = []
            real = probe_batch.build_bounded_probe_batch

            def spy(**kwargs):
                calls.append(kwargs)
                return real(**kwargs)

            monkeypatch.setattr(probe_batch, "build_bounded_probe_batch", spy)
            production_probe_executors(
                model_type=model_type,
                model_config={"segmentation_size": SEG},
                train_config={
                    "lr": 1e-3,
                    "batch_size": BATCH,
                    "epochs": 1,
                    "optimizer_type": "adamw",
                    "weight_decay": 0.0,
                    "device": "cpu",
                },
                loss_config={"loss_type": "ce"},
                data_dir=str(tmp_path),
                device="cpu",
            ).setup()
            assert len(calls) == 1
            assert calls[0]["batch_size"] == BATCH
            assert calls[0]["profile"] is not None
        finally:
            MODEL_REGISTRY.pop(model_type, None)
            PLUGIN_CONFIG_REGISTRY.pop(model_type, None)
