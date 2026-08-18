"""DAVIS future-frame prediction's executable data path (D14-3; Track C).

OWNERSHIP. How DAVIS RGB frames become `[3,8,128,224]` context /
`[3,4,128,224]` target windows, and how predicted future tensors become the
persisted deliverable — the task-owned side of the D14-1 ``TaskDataPath``
seam. The TRANSFORM here is the ONE authority the execution-manifest
generator and the runtime reader share; the committed ``execution.json``
probe hashes keep that single authority honest.

FROZEN TRANSFORM (child design §2.3; task table §22.9a):

    decode: PIL.Image.open -> .convert("RGB")     (NO EXIF transpose)
    resize: DIRECT to (W=224, H=128), PIL BILINEAR — a declared small
            aspect distortion (854x480 = 1.779 -> 1.75), chosen over a crop
            so every pixel of the scene stays in frame
    values: float32 / 255.0, CHW; a window stacks 12 consecutive frames as
            context [3,8,128,224] (start..start+7) + target [3,4,128,224]
            (start+8..start+11)

Manifest parsing lives HERE, not in the pack tooling: production must never
import `tools.example_packs` (§22.23.9 separability — the D14-2 C7 lesson,
applied from the start).

BOUNDARIES (parent Amendment 2): codec only — the global-MSE metric and its
scoreability belong to the Step-06 authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import torch
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field
from torch.utils.data import Dataset

from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    ValidationScopeError,
    register_task_data_path,
)

#: Frozen geometry (§22.9a; resize rule frozen by D14-3).
FRAME_WIDTH = 224
FRAME_HEIGHT = 128
CONTEXT_FRAMES = 8
FUTURE_FRAMES = 4
WINDOW_FRAMES = CONTEXT_FRAMES + FUTURE_FRAMES

#: Official extracted layout: <data_dir>/DAVIS/JPEGImages/480p/<seq>/%05d.jpg
FRAMES_RELDIR = Path("DAVIS") / "JPEGImages" / "480p"

DAVIS_TASK_DATA_PATH_ID = "davis_future_prediction"

SEQUENCES_MANIFEST_HEADER = "sequence_name,scope"
CLIPS_MANIFEST_HEADER = "sequence_name,start_frame,scope"


# ---------------------------------------------------------------------------
# Manifest rows and parsers (production-owned)
# ---------------------------------------------------------------------------


class SequenceRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence_name: str = Field(min_length=1)
    scope: str = Field(min_length=1)


class DavisClip(BaseModel):
    """One clip identity: which sequence, which window start."""

    model_config = ConfigDict(frozen=True)

    sequence_name: str = Field(min_length=1)
    start_frame: int = Field(ge=0)


class DavisScope(BaseModel):
    """DAVIS' opaque ``scope``: the clips in play. WHERE the frames live
    travels as the seam's ``params.data_dir`` (the D14-2 §2.1 pattern)."""

    model_config = ConfigDict(frozen=True)

    rows: tuple[DavisClip, ...] = Field(min_length=1)


def load_davis_sequences(path: str | Path) -> tuple[SequenceRow, ...]:
    """Parse the PR0-frozen ``sequences.csv`` (header-checked, fail closed)."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != SEQUENCES_MANIFEST_HEADER:
        raise ValueError(
            f"{path} is not a DAVIS sequence manifest "
            f"(header must be {SEQUENCES_MANIFEST_HEADER!r})"
        )
    rows: list[SequenceRow] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        sequence_name, scope = line.split(",")
        rows.append(SequenceRow(sequence_name=sequence_name, scope=scope))
    return tuple(rows)


def load_davis_clips(path: str | Path, *, scope: str | None = None) -> tuple[DavisClip, ...]:
    """Parse the committed ``clips.csv``, optionally filtered to one scope.

    The scope filter is the LEAKAGE guard's reader half: a caller asks for
    one scope's clips and can never receive another's, because the scope
    travels on every row and is compared here.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != CLIPS_MANIFEST_HEADER:
        raise ValueError(
            f"{path} is not a DAVIS clip manifest (header must be {CLIPS_MANIFEST_HEADER!r})"
        )
    rows: list[DavisClip] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        sequence_name, start_frame, row_scope = line.split(",")
        if scope is not None and row_scope != scope:
            continue
        rows.append(DavisClip(sequence_name=sequence_name, start_frame=int(start_frame)))
    return tuple(rows)


# ---------------------------------------------------------------------------
# The FROZEN clip rule (child design §2.2) — a pure function
# ---------------------------------------------------------------------------

#: Per-sequence clip caps by scope (parent §4.3 indicative caps).
CLIP_CAPS: dict[str, int] = {"train": 8, "validation": 4, "final": 4}


def clip_starts(frame_count: int, cap: int) -> tuple[int, ...]:
    """Deterministic, even, per-sequence window starts — no RNG, ever.

    ``L = frame_count - WINDOW_FRAMES`` is the last legal start; a sequence
    shorter than one window contributes ZERO clips (never a padded or
    truncated window). ``n = min(cap, L + 1)`` starts are spaced evenly
    over ``[0, L]`` with ``round`` (banker's rounding, Python's built-in),
    so the first window is always 0 and the last is always ``L``; for
    ``n == 1`` the single start is 0.

    Args:
        frame_count: frames on disk for this sequence.
        cap: this scope's per-sequence maximum.

    Returns:
        Ascending, duplicate-free starts (spacing >= 1 whenever
        ``n <= L + 1``, which the ``min`` guarantees).
    """
    if cap < 1:
        raise ValueError(f"cap must be >= 1, got {cap}")
    last_start = frame_count - WINDOW_FRAMES
    if last_start < 0:
        return ()
    n = min(cap, last_start + 1)
    if n == 1:
        return (0,)
    return tuple(round(i * last_start / (n - 1)) for i in range(n))


def count_sequence_frames(data_dir: str | Path, sequence_name: str) -> int:
    """Frames on disk for one sequence (the official ``%05d.jpg`` layout)."""
    return len(list((frames_root(data_dir) / sequence_name).glob("*.jpg")))


# ---------------------------------------------------------------------------
# The frozen transform
# ---------------------------------------------------------------------------


def frames_root(data_dir: str | Path) -> Path:
    return Path(data_dir) / FRAMES_RELDIR


def frame_path(data_dir: str | Path, sequence_name: str, index: int) -> Path:
    return frames_root(data_dir) / sequence_name / f"{index:05d}.jpg"


def decode_frame(path: str | Path) -> torch.Tensor:
    """One frame → ``float32 [3, 128, 224]`` in [0, 1] (the frozen rule)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"manifest names frame {p} but it does not exist — the declared "
            "scope must materialize exactly."
        )
    with Image.open(p) as img:
        rgb = img.convert("RGB").resize(
            (FRAME_WIDTH, FRAME_HEIGHT), resample=Image.Resampling.BILINEAR
        )
    hwc = torch.frombuffer(bytearray(rgb.tobytes()), dtype=torch.uint8).reshape(
        FRAME_HEIGHT, FRAME_WIDTH, 3
    )
    return hwc.permute(2, 0, 1).contiguous().to(torch.float32).div_(255.0)


def load_window(data_dir: str | Path, clip: DavisClip) -> tuple[torch.Tensor, torch.Tensor]:
    """``(context [3,8,128,224], target [3,4,128,224])`` for one clip."""
    frames = [
        decode_frame(frame_path(data_dir, clip.sequence_name, clip.start_frame + offset))
        for offset in range(WINDOW_FRAMES)
    ]
    context = torch.stack(frames[:CONTEXT_FRAMES], dim=1)
    target = torch.stack(frames[CONTEXT_FRAMES:], dim=1)
    return context, target


def window_probe_sha256(data_dir: str | Path, clip: DavisClip) -> str:
    """sha256 over ``context.bytes + target.bytes`` — one byte definition
    shared by the committed execution manifest and the parity tests."""
    import hashlib

    context, target = load_window(data_dir, clip)
    digest = hashlib.sha256()
    digest.update(context.numpy().tobytes())
    digest.update(target.numpy().tobytes())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# The TaskDataPath implementation
# ---------------------------------------------------------------------------


class _DavisWindowDataset(Dataset):
    """``(context, target)`` per clip; Amendment 1 live — the supervision
    target is a dense `[3,4,…]` tensor, a DIFFERENT shape from the context
    input, and the model output matches the target here (unlike Pets), which
    is exactly why the seam must not assume any relation between the three.

    Existence of every frame of every clip is verified at construction (fail
    closed naming the first missing one — the exact-materialization
    obligation in clip vocabulary); decoding stays lazy per item.
    """

    def __init__(self, rows: tuple[DavisClip, ...], data_dir: Path):
        missing: list[str] = []
        for clip in rows:
            for offset in range(WINDOW_FRAMES):
                p = frame_path(data_dir, clip.sequence_name, clip.start_frame + offset)
                if not p.exists():
                    missing.append(str(p))
                    break
        if missing:
            raise ValidationScopeError(
                f"declared scope names {len(missing)} clip(s) whose frames are "
                f"absent under {data_dir} (first: {missing[0]!r}) — the declared "
                "scope must materialize exactly."
            )
        self._rows = rows
        self._data_dir = data_dir

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(self, idx: int):
        return load_window(self._data_dir, self._rows[idx])


def deliverable_name(request: DeliverableWriteRequest | EvaluationReadRequest) -> str:
    """ONE naming rule, both directions."""
    return f"predictions_{request.model_type}_{request.run_name}_{request.exp_id}.npz"


def clip_key(clip: DavisClip) -> str:
    """The deliverable's stable per-clip key."""
    return f"{clip.sequence_name}:{clip.start_frame}"


class DavisTaskDataPath:
    """The registered DAVIS implementation of the four-method seam."""

    task_data_path_id: ClassVar[str] = DAVIS_TASK_DATA_PATH_ID

    @staticmethod
    def _scope(scope: object) -> DavisScope:
        if not isinstance(scope, DavisScope):
            raise TypeError(
                f"DAVIS data path requires a DavisScope, got {type(scope).__name__} "
                "— the binding and the scope object must come from the same task."
            )
        return scope

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset[Any]:
        s = self._scope(scope)
        if params.train_portion is not None and params.train_portion < 1.0:
            raise ValueError(
                "the DAVIS task defines no fractional-epoch subsampling rule "
                f"(frozen task, no augmentation); train_portion={params.train_portion} "
                "is refused rather than invented."
            )
        rows = s.rows if params.max_samples is None else s.rows[: params.max_samples]
        return _DavisWindowDataset(rows, Path(params.data_dir))

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset[Any]:
        s = self._scope(scope)
        return _DavisWindowDataset(s.rows, Path(params.data_dir))

    def write_deliverable(
        self,
        outputs: Iterable[tuple[DavisClip, np.ndarray | torch.Tensor]],
        request: DeliverableWriteRequest,
    ) -> None:
        """Persist ``{clip_key: float32 [3,4,128,224]}`` as one compressed npz."""
        arrays: dict[str, np.ndarray] = {}
        for clip, prediction in outputs:
            value = (
                prediction.detach().cpu().numpy()
                if isinstance(prediction, torch.Tensor)
                else np.asarray(prediction)
            )
            arrays[clip_key(clip)] = value.astype(np.float32, copy=False)
        path = Path(request.output_dir) / deliverable_name(request)
        # Type-only shim: numpy's stub declares `allow_pickle` as a keyword,
        # so unpacking a `dict[str, ndarray]` makes the checker bind an array
        # to it. Runtime semantics are unchanged (same call, same bytes) —
        # the same boundary pattern the h5py shims use.
        savez_compressed: Any = np.savez_compressed
        savez_compressed(path, **arrays)

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        """Decode to ``{clip_key: float32 ndarray}``; a missing file yields
        ``{}`` — absence is DATA for the Step-06 scoreability contract."""
        path = Path(request.deliverable_dir) / deliverable_name(request)
        if not path.exists():
            return {}
        with np.load(path) as handle:
            return {key: handle[key] for key in handle.files}


def truth_windows(data_dir: str | Path, clips: Sequence[DavisClip]) -> dict[str, np.ndarray]:
    """``{clip_key: target [3,4,128,224]}`` — the evaluation ground truth,
    decoded through the SAME frozen transform the reader uses (one
    authority; the metric never re-derives pixels)."""
    truth: dict[str, np.ndarray] = {}
    for clip in clips:
        _context, target = load_window(data_dir, clip)
        truth[clip_key(clip)] = target.numpy()
    return truth


register_task_data_path(DavisTaskDataPath())
