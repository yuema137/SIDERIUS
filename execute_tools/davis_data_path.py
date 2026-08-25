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

import json
import random
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
    ScopeBuildRequest,
    ValidationScopeError,
    deserialize_rows_scope,
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


def pair_with_scope(outputs, request: DeliverableWriteRequest):
    """Pair unpaired per-sample outputs with this task's own row identities.

    Step 12 / PR-12d seam C (B7). The generic inference unit iterates
    ``validation_dataset`` and hands back per-sample outputs IN DATASET ORDER
    together with the scope it iterated — it cannot pair them itself without
    learning this task's vocabulary, which is exactly what the seam exists to
    prevent. So the pairing happens HERE, in the task's own file.

    ``request.task_scope is None`` means the caller already paired them, which
    is what every pre-12d producer does; that shape passes straight through.

    ``strict=True`` is the point rather than a detail: a length mismatch means
    the outputs and the scope disagree about how many samples there were, and
    silently zipping to the shorter one would mis-attribute every prediction
    after the first missing sample.
    """
    if request.task_scope is None:
        return list(outputs)
    rows = getattr(request.task_scope, "rows", None)
    if rows is None:
        raise ValueError(
            f"deliverable write for {DAVIS_TASK_DATA_PATH_ID!r} received a task_scope "
            f"of type {type(request.task_scope).__name__}, which declares no "
            f"rows to pair the outputs with."
        )
    return list(zip(rows, outputs, strict=True))


class DavisTaskDataPath:
    """The registered DAVIS implementation of the four-method seam."""

    task_data_path_id: ClassVar[str] = DAVIS_TASK_DATA_PATH_ID

    #: The scope payload's self-identifying tag (PR-12bc B8).
    _SCOPE_KIND: ClassVar[str] = "davis_scope_v1"

    def __init__(
        self, *, clips_path: str | None = None, eval_clips_path: str | None = None
    ) -> None:
        """Step 12 / PR-12bc B8 — TASK-INSTANCE CONFIGURATION (§D.1).

        DAVIS' scope authority is its committed CLIP manifest — the windows
        themselves, already derived deterministically (``load_davis_clips``,
        no RNG ever). Named ``clips_path`` rather than ``sequences_path``
        because that is what the loader actually reads: a sequences manifest
        has a different header and is refused by it.

        The module-level registration passes nothing — the regime-A instance
        materializes a scope it is HANDED and refuses to BUILD one, by name.

        ``eval_clips_path`` — Step 12 / PR-12d, closing **F-12d-17**. This
        pack ships THREE DISJOINT role manifests (train 60 / validation 15 /
        final 15, train n validation = 0), and the `scope` column inside each
        one is CONSTANT — the role IS the file. Before this, both
        :meth:`build_training_scope` and :meth:`build_eval_scope` selected
        from the single ``clips_path``, so a composed run trained and
        evaluated on the identical clips. The D14 runner never showed it
        because the runner loads all three manifests and passes both scopes
        itself; the composed path is the only caller that has to CHOOSE.

        OPTIONAL and additive: absent, both scopes come from ``clips_path``
        exactly as before, so every existing caller — the runner, the
        registration, every current test — is unchanged.
        """
        self._clips_path = clips_path
        self._eval_clips_path = eval_clips_path

    # ------------------------------------------------------------------
    # TaskScopeCapability (PR-12bc B8)
    # ------------------------------------------------------------------

    def _select(self, request: ScopeBuildRequest, *, source: str | None = None) -> DavisScope:
        source = source or self._clips_path
        if source is None:
            raise ValueError(
                f"task data path {self.task_data_path_id!r} was asked to BUILD a "
                f"scope but was constructed with no sequences manifest. Declare "
                f"`config: {{clips_path: ...}}` in the composition's "
                f"`task_data_path` section — the manifest is this task's scope "
                f"authority and there is nothing to select without it."
            )
        if request.selection_strategy == "anchors":
            raise ValueError(
                f"task data path {self.task_data_path_id!r} declares no anchor "
                f"representatives, so the 'anchors' selection strategy has no "
                f"content for it. Use 'snapshot', or 'target' with an explicit "
                f"subset."
            )
        clips = load_davis_clips(source)
        if request.selection_strategy == "target":
            if not request.target_partitions:
                raise ValueError("'target' selection requires a non-empty subset.")
            bound = len(clips)
            out_of_range = [i for i in request.target_partitions if not 0 <= i < bound]
            if out_of_range:
                raise ValueError(
                    f"target partitions {out_of_range} are outside this task's {bound} clips."
                )
            clips = tuple(clips[i] for i in request.target_partitions)
        keep = max(1, round(request.portion * len(clips)))
        if request.seed is not None:
            clips = tuple(random.Random(request.seed).sample(list(clips), keep))
        else:
            clips = clips[:keep]
        if request.max_samples is not None:
            clips = clips[: request.max_samples]
        return DavisScope(rows=clips)

    def build_training_scope(self, request: ScopeBuildRequest) -> object:
        return self._select(request)

    def build_eval_scope(self, request: ScopeBuildRequest) -> object:
        """The EVAL manifest when one is declared, else the training one.

        The fallback is what keeps this additive (F-12d-17); it is not a
        recommendation. A composition that declares only ``clips_path`` gets
        an evaluation scope drawn from its training clips, which is the
        pre-existing behaviour and is why the shipped manifest declares both.
        """
        return self._select(request, source=self._eval_clips_path or self._clips_path)

    def serialize_scope(self, scope: object) -> str:
        s = self._scope(scope)
        return json.dumps(
            {"kind": self._SCOPE_KIND, "rows": [r.model_dump() for r in s.rows]},
            sort_keys=True,
            separators=(",", ":"),
        )

    def deserialize_scope(self, payload: str) -> object:
        return deserialize_rows_scope(payload, self._SCOPE_KIND, DavisClip, DavisScope)

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
        for clip, prediction in pair_with_scope(outputs, request):
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


# Regime-A instance: no manifest, so it materializes a scope it is HANDED
# but refuses to BUILD one, by name (PR-12bc B8).
register_task_data_path(DavisTaskDataPath())
