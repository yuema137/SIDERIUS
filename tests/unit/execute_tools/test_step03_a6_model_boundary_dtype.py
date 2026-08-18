"""Step 03 Checkpoint 0 — baseline **A6**: the model-boundary input dtype.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§5 (A6 — "MISSING, capture first"), §15 (Checkpoint 0), §24.2 finding F-1,
§24.3 (Checkpoint-0 oracle audit).

**Why capture-first.** Step 03 Phase B replaces model-NAME-keyed input
dtype routing with contract-keyed routing. A6 is the only oracle that can
see whether that migration changed what actually reaches a model, so it
must exist BEFORE the production diff — a baseline written afterwards
pins the already-changed behaviour and proves nothing. This module has
**zero production diff** by construction.

**What A6 asserts, and why it is not decoration.** No existing test
observes the dtype of the tensor handed to ``model.forward``. Every
nearby oracle is blind to it:

===============================  =========================================
oracle                           why it cannot see the dtype
===============================  =========================================
Step-00 numeric baselines (A4)   ``nn.Embedding`` accepts int32 and int64
                                 alike, so forward OUTPUTS are numerically
                                 identical under either
Step-02a C1 baselines            assert what the DATASET serves, which is
                                 upstream of the engine's cast
pyright / Pydantic               ``Tensor`` is one static type; the cast
                                 is a runtime method call
===============================  =========================================

Delete this module and a Phase-B change that silently fed int64 where
int32 flows today — or that quietly unified the two boundaries — would
pass the entire suite.

**The finding this baseline exists to pin (F-1).** The concrete dtype is
NOT one value today. On the embedding arm training feeds **int32** and
inference feeds **int64**; ``configs/task_config.yaml`` declares int64,
agreeing with inference only. That divergence is captured here exactly as
it is — **not normalized, reinterpreted or repaired**. Whether the
Model-I/O contract should own a dtype REQUIREMENT that both concrete
casts satisfy is an open operator decision recorded in §24.2; this module
is the evidence that decision is made against, and it deliberately takes
no position on it.

Every expectation below is HARDCODED. Nothing is read back from the
object under test, so the assertions cannot drift with the production
value the way ``observed == cfg.some_field`` would.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import h5py
import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader, Dataset

import execute_tools.inference_single as inf
import execute_tools.train_engine_sandbox as tes
from execute_tools.dataset_config import TIDMAD_PROFILE, bind_dataset_profile
from ml_models.models_format_sandbox import LossConfig, TrainConfig, get_config_class
from ml_models.models_sandbox import BUILTIN_OUTPUT_TYPES, MODEL_REGISTRY

# Segment length: >= the ``segmentation_size`` floor of 1000, and a power of
# two so PUNet's downsampling depth divides it. Small enough that six
# builtins x three boundaries stay a CPU unit test.
SEG = 1024

#: Minimal-but-valid architecture parameters. Only SIZE is reduced — no
#: field that could influence the input dtype is touched, because that is
#: the property under observation.
_TINY: dict[str, dict] = {
    "punet": {"multi": 8, "depth": 2, "embedding_dim": 8, "kernel_size": 3},
    "fcnet": {"latent_dims": [64, 16]},
    "transformer": {
        "embedding_dim": 8,
        "nhead": 2,
        "num_layers": 1,
        "dim_feedforward": 64,
    },
    "wavenet": {
        "input_channels": 4,
        "residual_channels": 8,
        "gate_channels": 8,
        "skip_channels": 8,
        "kernel_size": 2,
        "num_blocks": 1,
    },
    "rnn": {},
    "gated_fno": {},
}

BUILTINS = tuple(BUILTIN_OUTPUT_TYPES)

# ---------------------------------------------------------------------------
# THE BASELINE — hardcoded, one cell per (boundary, model).
#
# `fcnet` is listed separately from the embedding arm at every boundary
# rather than folded into a default, because a shared expectation is
# exactly what would hide a regression on one arm only.
# ---------------------------------------------------------------------------

#: ``train_engine_sandbox.run_experiment`` — the epoch path, cast at :660,
#: model called at :671.
EPOCH_TRAINING_DTYPE: dict[str, torch.dtype] = {
    "punet": torch.int32,
    "fcnet": torch.float32,
    "transformer": torch.int32,
    "wavenet": torch.int32,
    "rnn": torch.int32,
    "gated_fno": torch.int32,
}

#: ``train_engine_sandbox.run_experiment_streaming`` — THE production
#: training path, cast at :1029, model called at :1036.
STREAMING_TRAINING_DTYPE: dict[str, torch.dtype] = dict(EPOCH_TRAINING_DTYPE)

#: ``inference_single.process_batch`` — cast at :213, model called at :228.
#: NOTE the embedding arm differs from both training paths. That is F-1.
INFERENCE_DTYPE: dict[str, torch.dtype] = {
    "punet": torch.int64,
    "fcnet": torch.float32,
    "transformer": torch.int64,
    "wavenet": torch.int64,
    "rnn": torch.int64,
    "gated_fno": torch.int64,
}


def _cfg(model_type: str):
    """A minimal valid config for one builtin."""
    return get_config_class(model_type)(segmentation_size=SEG, **_TINY[model_type])


def _record_forward_dtype(monkeypatch, model_type: str, sink: list[torch.dtype]) -> None:
    """Register a subclass that records the dtype its forward receives.

    A subclass — not a wrapper object and not a patched cast — so the model
    the engine constructs, and the argument it is handed, are the production
    ones. ``forward`` delegates unchanged, so nothing about the run differs
    except that the dtype is observable.
    """
    real = MODEL_REGISTRY[model_type]

    class _Recorder(real):  # type: ignore[misc, valid-type]
        def forward(self, x, *args, **kwargs):
            sink.append(x.dtype)
            return super().forward(x, *args, **kwargs)

    _Recorder.__name__ = real.__name__
    _Recorder.__qualname__ = real.__qualname__
    monkeypatch.setitem(tes.MODEL_REGISTRY, model_type, _Recorder)


def _sandbox_dirs(tmp_path) -> dict[str, str]:
    dirs = {
        "models": str(tmp_path / "cached_models"),
        "results": str(tmp_path / "records"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


class _Int16Pairs(Dataset):
    """Serves the int16 the real loaders serve (Step-02a C1 pinned that).

    The served dtype is the INPUT to the engine's cast, so getting it right
    is what makes the observed output meaningful.
    """

    def __init__(self, n: int = 2):
        self.n = n

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, idx: int):
        x = torch.full((SEG,), 100 + idx, dtype=torch.int16)
        return x, x.clone()


@pytest.fixture
def one_file_scope(tmp_path):
    """One tiny training file, two segments — enough for one streaming step."""
    rng = np.random.default_rng(0)
    path = tmp_path / TIDMAD_PROFILE.dataset.training_file_name(4)
    n = 2 * SEG
    with h5py.File(path, "w") as f:
        ts = f.create_group("timeseries")
        ts.create_group("channel0001").create_dataset(
            "timeseries", data=rng.integers(-128, 127, size=n, dtype=np.int8)
        )
        ts.create_group("channel0002").create_dataset(
            "timeseries", data=rng.integers(-128, 127, size=n, dtype=np.int8)
        )
    tiny = TIDMAD_PROFILE.model_copy(
        update={"dataset": TIDMAD_PROFILE.dataset.model_copy(update={"psd_segment_length": SEG})}
    )
    with bind_dataset_profile(tiny):
        yield str(tmp_path), {"4": [0, 1]}


# ---------------------------------------------------------------------------
# Boundary 1 — epoch training
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_type", BUILTINS)
def test_epoch_training_model_boundary_dtype(model_type, tmp_path, monkeypatch):
    """The dtype ``run_experiment`` hands each builtin, observed at forward."""
    seen: list[torch.dtype] = []
    _record_forward_dtype(monkeypatch, model_type, seen)

    tes.run_experiment(
        _cfg(model_type),
        TrainConfig(lr=1e-4, epochs=1, batch_size=1, optimizer_type="adam", device="cpu"),
        LossConfig(),
        DataLoader(_Int16Pairs(), batch_size=1),
        _sandbox_dirs(tmp_path),
        "a6_epoch",
    )

    assert seen, "the model was never called — the boundary was not exercised"
    assert set(seen) == {EPOCH_TRAINING_DTYPE[model_type]}


# ---------------------------------------------------------------------------
# Boundary 2 — streaming training (THE production path)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_type", BUILTINS)
def test_streaming_training_model_boundary_dtype(model_type, tmp_path, one_file_scope, monkeypatch):
    """The dtype ``run_experiment_streaming`` hands each builtin."""
    data_dir, sample_set = one_file_scope
    seen: list[torch.dtype] = []
    _record_forward_dtype(monkeypatch, model_type, seen)

    tes.run_experiment_streaming(
        _cfg(model_type),
        TrainConfig(lr=1e-4, epochs=1, batch_size=1, optimizer_type="adam", device="cpu"),
        LossConfig(),
        sample_set=sample_set,
        data_dir=data_dir,
        sandbox_dirs=_sandbox_dirs(tmp_path),
        exp_id="a6_streaming",
        train_base_seed=42,
    )

    assert seen, "the model was never called — the boundary was not exercised"
    assert set(seen) == {STREAMING_TRAINING_DTYPE[model_type]}


# ---------------------------------------------------------------------------
# Boundary 3 — inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_type", BUILTINS)
def test_inference_model_boundary_dtype(model_type, monkeypatch):
    """The dtype ``process_batch`` hands each builtin."""
    monkeypatch.setattr(inf, "DEVICE", torch.device("cpu"))

    cfg = _cfg(model_type)
    real = MODEL_REGISTRY[model_type]
    model = real(cfg, loss_type="focal") if model_type == "fcnet" else real(cfg)
    model.eval()

    seen: list[torch.dtype] = []
    real_forward = model.forward

    def recording(x, *args, **kwargs):
        seen.append(x.dtype)
        return real_forward(x, *args, **kwargs)

    monkeypatch.setattr(model, "forward", recording)

    arr = np.zeros((1, 1, SEG), dtype=np.int8)
    inf.process_batch(
        0,
        arr,
        arr.copy(),
        model,
        SimpleNamespace(denoising_model=model_type),
        "focal",
    )

    assert seen, "the model was never called — the boundary was not exercised"
    assert set(seen) == {INFERENCE_DTYPE[model_type]}


# ---------------------------------------------------------------------------
# The cross-boundary fact (§24.2 F-1)
# ---------------------------------------------------------------------------


class TestConcreteDtypeDivergesAcrossBoundaries:
    """The same builtin is fed two different concrete integer dtypes today.

    Recorded as its own claim rather than left implicit in the three tables
    above, because it is the fact the Step-03 dtype decision turns on: a
    single ``input.dtype`` on the contract cannot reproduce both concrete
    casts. Asserted from the hardcoded baselines, so it reds if a future
    change quietly unifies them — which is precisely the outcome that needs
    an operator decision first.
    """

    EMBEDDING_ARM = tuple(m for m in BUILTINS if m != "fcnet")

    @pytest.mark.parametrize("model_type", EMBEDDING_ARM)
    def test_the_same_builtin_accepts_both_concrete_integer_dtypes(self, model_type):
        """Executed, not asserted from a table: each embedding-arm builtin
        really does run under both int32 and int64.

        This is why the divergence has survived unnoticed — nothing fails
        today. It is also what makes a dtype REQUIREMENT (rather than a
        boundary-specific concrete cast) representable at all.
        """
        model = MODEL_REGISTRY[model_type](_cfg(model_type))
        model.eval()
        shapes = []
        for dtype in (torch.int32, torch.int64):
            with torch.no_grad():
                shapes.append(tuple(model(torch.zeros(1, SEG, dtype=dtype)).shape))
        assert shapes[0] == shapes[1] == (1, 256, SEG)

    def test_the_declared_contract_matches_inference_only(self):
        """``configs/task_config.yaml`` declares int64 — true of inference,
        false of both training paths. Pinned so the mismatch is evidence in
        the suite, not only prose in the design ledger."""
        from agent.schemas.task_config import ForwardContract
        from workflows.task_config import load_task_config

        # The established idiom for reading the shipped contract in tests
        # (test_step00_prompt_goldens.py:63, test_contract_reassertion.py:29):
        # ``load_task_config`` returns a validated dict, not a model.
        declared = ForwardContract(**load_task_config()["forward_contract"])
        assert declared.input_shape == "[B, T] int64"
        assert INFERENCE_DTYPE["punet"] is torch.int64
        assert EPOCH_TRAINING_DTYPE["punet"] is not torch.int64
