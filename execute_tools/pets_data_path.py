"""Oxford-IIIT Pet's executable data path (D14-2; Track B, roadmap §22.9a).

OWNERSHIP. This module owns how Pets bytes become tensors and how model
outputs become the classification deliverable — the task-owned side of the
D14-1 ``TaskDataPath`` seam. The TRANSFORM here is the ONE authority the
execution-manifest generator (``tools/example_packs/oxford_iiit_pet.py``)
and the runtime reader share; what keeps that single authority honest is the
COMMITTED ``execution.json`` probe hashes (generated once, byte-immutable,
double-run-proven in two processes) — any drift in PIL/torch/environment
fails the pinned comparison loudly instead of being regenerated away.

FROZEN TRANSFORM (child design §2.2; task table §22.9a "input topology"):

    decode: PIL.Image.open -> .convert("RGB")     (NO EXIF transpose)
    resize: aspect-preserving, SHORTER side = 160, PIL BILINEAR
    crop:   center 144 x 144
    values: float32 [3, 144, 144] = pixel / 255.0  (CHW, RGB order)

BOUNDARIES (parent Amendment 2): codec only — no metric arithmetic, no
objective semantics; accuracy lives with the Step-06 authority.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, ClassVar

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

#: Frozen preprocessing parameters (§22.9a; interpolation frozen by D14-2).
RESIZE_SHORTER_SIDE = 160
CROP_SIZE = 144
NUM_CLASSES = 37

#: The registered task-data-path id (declared once; never inspected by
#: spelling — parent §3.1 capability-key row).
PETS_TASK_DATA_PATH_ID = "oxford_iiit_pet"


def decode_and_transform(image_path: str | Path) -> torch.Tensor:
    """The frozen JPEG → ``float32 [3, 144, 144]`` transform.

    Deterministic by construction: plain decode (``convert("RGB")`` — CMYK
    and palette images normalize, EXIF orientation is deliberately NOT
    applied), BILINEAR shorter-side-160 resize with ``round()`` on the long
    side, exact center crop, ``/255`` scaling, CHW layout.

    Raises:
        FileNotFoundError: the image is absent — the manifests are the scope
            authority and must materialize exactly (never skip).
        OSError: PIL cannot decode the bytes (truncated/corrupt file).
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(
            f"manifest names {path} but it does not exist — the declared "
            "scope must materialize exactly (no skip-a-missing-file "
            "semantics on this task)."
        )
    with Image.open(path) as img:
        rgb = img.convert("RGB")
        width, height = rgb.size
        shorter = min(width, height)
        scale = RESIZE_SHORTER_SIDE / shorter
        new_w = RESIZE_SHORTER_SIDE if width == shorter else round(width * scale)
        new_h = RESIZE_SHORTER_SIDE if height == shorter else round(height * scale)
        resized = rgb.resize((new_w, new_h), resample=Image.Resampling.BILINEAR)
        left = (new_w - CROP_SIZE) // 2
        top = (new_h - CROP_SIZE) // 2
        cropped = resized.crop((left, top, left + CROP_SIZE, top + CROP_SIZE))
    # PIL -> [H, W, 3] uint8 -> float32 CHW / 255.
    hwc = torch.frombuffer(bytearray(cropped.tobytes()), dtype=torch.uint8).reshape(
        CROP_SIZE, CROP_SIZE, 3
    )
    return hwc.permute(2, 0, 1).contiguous().to(torch.float32).div_(255.0)


def transform_probe_sha256(image_path: str | Path) -> str:
    """The canonical probe hash: sha256 over the transformed tensor's bytes
    (float32, CHW, contiguous). Used by the committed execution manifest and
    by the parity tests — one byte definition, two consumers."""
    import hashlib

    tensor = decode_and_transform(image_path)
    return hashlib.sha256(tensor.numpy().tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# The TaskDataPath implementation (D14-2 C3)
# ---------------------------------------------------------------------------


class PetsItem(BaseModel):
    """One manifest row's identity: which image, which class."""

    model_config = ConfigDict(frozen=True)

    image_id: str
    class_index: int = Field(ge=0, lt=NUM_CLASSES)


class PetsScope(BaseModel):
    """Pets' opaque ``scope``: the manifest rows in play — WHICH data.

    WHERE the data lives travels as the seam's own ``params.data_dir``
    (child design §2.1: the machine-local images root, the TIDMAD `data_dir`
    pattern). The transform rule is deliberately NOT carried here: the rule
    is CODE (`decode_and_transform`, one authority) whose behaviour the
    committed ``execution.json`` probe hashes pin — a parameters copy in the
    scope would be a second, dead interpretation channel.
    """

    model_config = ConfigDict(frozen=True)

    rows: tuple[PetsItem, ...] = Field(min_length=1)


#: The committed identity/gate manifests' header (frozen at PR0).
PETS_MANIFEST_HEADER = "image_id,class_index,official_class_id,scope"


def load_pets_manifest(path: str | Path) -> tuple[PetsItem, ...]:
    """Parse a committed Pets manifest CSV into scope rows.

    Production-owned (§22.23.9 separability: production never imports the
    pack tooling): the manifests are this task's scope authority, so its
    data-path module knows their format. Header-checked, fail closed.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != PETS_MANIFEST_HEADER:
        raise ValueError(f"{path} is not a Pets manifest (header must be {PETS_MANIFEST_HEADER!r})")
    rows: list[PetsItem] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        image_id, class_index, _official, _scope = line.split(",")
        rows.append(PetsItem(image_id=image_id, class_index=int(class_index)))
    return tuple(rows)


class _PetsManifestDataset(Dataset):
    """``(float32 [3,144,144], int class_index)`` per manifest row.

    Amendment 1 live: the supervision target is a scalar int (the objective's
    vocabulary); the model output is ``[37]`` float logits — shape, rank and
    dtype all differ. Decoding is lazy per item; EXISTENCE of every named
    file is verified at construction (fail closed naming the id — the
    manifests are the scope authority and must materialize exactly).
    """

    def __init__(self, rows: tuple[PetsItem, ...], images_root: Path):
        missing = [
            row.image_id for row in rows if not (images_root / f"{row.image_id}.jpg").exists()
        ]
        if missing:
            raise ValidationScopeError(
                f"declared scope names {len(missing)} image(s) absent under "
                f"{images_root} (first: {missing[0]!r}) — the declared scope "
                "must materialize exactly."
            )
        self._rows = rows
        self._images_root = images_root

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(self, idx: int):
        row = self._rows[idx]
        return decode_and_transform(self._images_root / f"{row.image_id}.jpg"), int(row.class_index)


def _pets_image_id(identity: object) -> str:
    """The image id, from either a paired caller's string or a scope row."""
    return str(getattr(identity, "image_id", identity))


def _pets_class_index(prediction: object) -> int:
    """The predicted class, from a caller's int or the model's raw logits.

    The generic inference unit hands back what the MODEL produced — a logit
    vector per sample — because it has no idea that this task's deliverable is
    a class index. Turning logits into a label is task semantics, so it
    happens here. An already-decided int (every pre-12d caller) passes
    through.
    """
    import torch

    if isinstance(prediction, torch.Tensor) and prediction.ndim >= 1:
        return int(torch.argmax(prediction).item())
    return int(prediction)  # type: ignore[arg-type]


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
            f"deliverable write for {PETS_TASK_DATA_PATH_ID!r} received a task_scope "
            f"of type {type(request.task_scope).__name__}, which declares no "
            f"rows to pair the outputs with."
        )
    return list(zip(rows, outputs, strict=True))


class PetsTaskDataPath:
    """The registered Pets implementation of the four-method seam."""

    task_data_path_id: ClassVar[str] = PETS_TASK_DATA_PATH_ID

    #: The scope payload's self-identifying tag (PR-12bc B8).
    _SCOPE_KIND: ClassVar[str] = "pets_scope_v1"

    def __init__(
        self, *, manifest_path: str | None = None, eval_manifest_path: str | None = None
    ) -> None:
        """Step 12 / PR-12bc B8 — TASK-INSTANCE CONFIGURATION (§D.1).

        An implementation that needs its own sources to BUILD scopes receives
        them at CONSTRUCTION, via the manifest's ``task_data_path`` section.
        Pets' scope authority is its committed manifest, so that is what it
        takes. The module-level registration below passes nothing, which is
        the regime-A instance: it can still materialize a scope it is HANDED,
        it simply cannot build one from nothing — and it says so by name.

        The task's own plugin reading the task's own manifest is never a
        FRAMEWORK import of ``examples/``, so the governance census
        (``test_pack_governance.py:211-221``) stays green.

        ``eval_manifest_path`` — Step 12 / PR-12d, closing **F-12d-17** on the
        Pets side (DAVIS closed first, in `davis_data_path.py`). This pack
        ships THREE DISJOINT role manifests (train 370 / validation 74 /
        final 370, `scope` constant per file), and before this both
        :meth:`build_training_scope` and :meth:`build_eval_scope` selected
        from the single ``manifest_path`` — so a composed run trained and
        evaluated on the identical images. The D14 runner never showed it: it
        loads all three manifests itself and passes both scopes explicitly.

        OPTIONAL and additive: absent, both scopes come from ``manifest_path``
        exactly as before, so every existing caller is byte-unchanged.
        """
        self._manifest_path = manifest_path
        self._eval_manifest_path = eval_manifest_path

    # ------------------------------------------------------------------
    # TaskScopeCapability (PR-12bc B8)
    # ------------------------------------------------------------------

    def _rows(self, *, source: str | None = None) -> tuple[PetsItem, ...]:
        source = source or self._manifest_path
        if source is None:
            raise ValueError(
                f"task data path {self.task_data_path_id!r} was asked to BUILD a "
                f"scope but was constructed with no manifest. Declare "
                f"`config: {{manifest_path: ...}}` in the composition's "
                f"`task_data_path` section — the manifest is this task's scope "
                f"authority and there is nothing to sample without it."
            )
        return load_pets_manifest(source)

    def _select(self, request: ScopeBuildRequest, *, source: str | None = None) -> PetsScope:
        rows = self._rows(source=source)
        if request.selection_strategy == "anchors":
            raise ValueError(
                f"task data path {self.task_data_path_id!r} declares no anchor "
                f"representatives, so the 'anchors' selection strategy has no "
                f"content for it. Use 'snapshot', or 'target' with an explicit "
                f"subset."
            )
        if request.selection_strategy == "target":
            if not request.target_partitions:
                raise ValueError("'target' selection requires a non-empty subset.")
            bound = len(rows)
            out_of_range = [i for i in request.target_partitions if not 0 <= i < bound]
            if out_of_range:
                raise ValueError(
                    f"target partitions {out_of_range} are outside this task's "
                    f"{bound} manifest rows."
                )
            rows = tuple(rows[i] for i in request.target_partitions)
        keep = max(1, round(request.portion * len(rows)))
        if request.seed is not None:
            rows = tuple(random.Random(request.seed).sample(list(rows), keep))
        else:
            rows = rows[:keep]
        if request.max_samples is not None:
            rows = rows[: request.max_samples]
        return PetsScope(rows=rows)

    def build_training_scope(self, request: ScopeBuildRequest) -> object:
        return self._select(request)

    def build_eval_scope(self, request: ScopeBuildRequest) -> object:
        """The EVAL manifest when one is declared, else the training one.

        The fallback keeps this additive (F-12d-17); it is not a
        recommendation. A composition declaring only ``manifest_path`` gets an
        evaluation scope drawn from its training rows — the pre-existing
        behaviour, and why the shipped manifest declares both.
        """
        return self._select(request, source=self._eval_manifest_path or self._manifest_path)

    def serialize_scope(self, scope: object) -> str:
        s = self._scope(scope)
        return json.dumps(
            {"kind": self._SCOPE_KIND, "rows": [r.model_dump() for r in s.rows]},
            sort_keys=True,
            separators=(",", ":"),
        )

    def deserialize_scope(self, payload: str) -> object:
        return deserialize_rows_scope(payload, self._SCOPE_KIND, PetsItem, PetsScope)

    @staticmethod
    def _scope(scope: object) -> PetsScope:
        if not isinstance(scope, PetsScope):
            raise TypeError(
                f"Pets data path requires a PetsScope, got {type(scope).__name__} "
                "— the binding and the scope object must come from the same task."
            )
        return scope

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset[Any]:
        s = self._scope(scope)
        if params.train_portion is not None and params.train_portion < 1.0:
            raise ValueError(
                "the Pets task defines no fractional-epoch subsampling rule "
                f"(frozen task, no augmentation); train_portion={params.train_portion} "
                "is refused rather than invented."
            )
        rows = s.rows
        if params.max_samples is not None:
            # Harness-owned validation-posture ceiling: deterministic prefix
            # in manifest order (the TIDMAD ceiling analog — bounding by
            # reading less, never by stopping later).
            rows = rows[: params.max_samples]
        return _PetsManifestDataset(rows, Path(params.data_dir))

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset[Any]:
        s = self._scope(scope)
        return _PetsManifestDataset(s.rows, Path(params.data_dir))

    def write_deliverable(
        self, outputs: Iterable[tuple[str, int]], request: DeliverableWriteRequest
    ) -> None:
        """The classification deliverable: ONE CSV, header
        ``image_id,predicted_class_index``, rows sorted by image_id
        (byte-deterministic). Codec only — no correctness knowledge."""
        paired = pair_with_scope(outputs, request)
        rows = sorted(
            (str(_pets_image_id(identity)), _pets_class_index(prediction))
            for identity, prediction in paired
        )
        path = Path(request.output_dir) / deliverable_name(request)
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write("image_id,predicted_class_index\n")
            for image_id, pred in rows:
                fh.write(f"{image_id},{pred}\n")
        _write_probabilities_sidecar(paired, request)

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        """Decode the deliverable to ``{image_id: predicted_class_index}``.

        A missing file yields ``{}`` — absence is DATA for the Step-06
        scoreability contract, which owns the structured refusal (the
        TIDMAD C4 rationale, verbatim)."""
        path = Path(request.deliverable_dir) / deliverable_name(request)
        if not path.exists():
            return {}
        payload: dict[str, int] = {}
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0] != "image_id,predicted_class_index":
            raise ValueError(
                f"{path} is not a Pets classification deliverable (bad or missing header)."
            )
        for line in lines[1:]:
            if not line.strip():
                continue
            image_id, pred = line.split(",")
            payload[image_id] = int(pred)
        probabilities = _read_probabilities_sidecar(request)
        if probabilities is None:
            return payload
        return PetsEvaluationPayload(labels=payload, probabilities=probabilities)


class PetsEvaluationPayload(Mapping):
    """The deliverable, read back: arg-max labels PLUS the distribution.

    Step 12 / PR-12d. A ``Mapping`` of ``{image_id: class_index}`` so every
    label-reading consumer — `accuracy`, `macro_f1`, and every pre-12d caller
    — is unchanged and cannot tell the difference. ``probabilities`` is the
    additive half `log_loss` needs.

    Being a Mapping rather than a pair of arguments is what keeps this
    task-owned: the framework hands whatever ``read_evaluation_payload``
    returns to whatever metric the task declared, and never inspects it.
    """

    def __init__(self, labels: dict[str, int], probabilities: dict[str, Any]) -> None:
        self._labels = labels
        self.probabilities = probabilities

    def __getitem__(self, key: str) -> int:
        return self._labels[key]

    def __iter__(self):
        return iter(self._labels)

    def __len__(self) -> int:
        return len(self._labels)


def _write_probabilities_sidecar(paired, request: DeliverableWriteRequest) -> None:
    """Persist the predicted distribution, when the model produced one.

    A caller that already decided a label (every pre-12d producer, and the
    D14 runner) hands back ints, not logits — there is no distribution to
    write and none is written. That absence is DATA, not an error: the
    sidecar's reader returns ``None`` and `log_loss` refuses by name.
    """
    import numpy as np
    import torch

    rows: dict[str, Any] = {}
    for identity, prediction in paired:
        if not isinstance(prediction, torch.Tensor) or prediction.ndim < 1:
            return
        rows[str(_pets_image_id(identity))] = (
            torch.softmax(prediction.detach().float().flatten(), dim=0).cpu().numpy()
        )
    if not rows:
        return
    np.savez_compressed(Path(request.output_dir) / probabilities_sidecar_name(request), **rows)


def _read_probabilities_sidecar(request: EvaluationReadRequest) -> dict[str, Any] | None:
    """The distribution, or ``None`` when this run wrote none."""
    import numpy as np

    path = Path(request.deliverable_dir) / probabilities_sidecar_name(request)
    if not path.exists():
        return None
    with np.load(path) as handle:
        return {key: handle[key] for key in handle.files}


def deliverable_name(request: DeliverableWriteRequest | EvaluationReadRequest) -> str:
    """ONE naming rule, both directions (write + read)."""
    return f"predictions_{request.model_type}_{request.run_name}_{request.exp_id}.csv"


def probabilities_sidecar_name(request: DeliverableWriteRequest | EvaluationReadRequest) -> str:
    """The predicted DISTRIBUTION's file, beside the CSV.

    Step 12 / PR-12d. `log_loss` needs the probability the model assigned to
    the true class, and the CSV carries only the arg-max label — so with the
    CSV alone that declaration could compose and never compute.

    **A SIDECAR rather than extra CSV columns, and the reason is bytes.** The
    CSV's exact header and row format are pinned in several places, including
    the sha-pinned D14 Pets collapse fixture and the codec-parity regression.
    Widening it would move digests that record a REAL observed collapse, for
    a reason that has nothing to do with that collapse. An additive file moves
    nothing: every existing reader, and the CSV's own digest, are untouched.
    """
    return f"predictions_{request.model_type}_{request.run_name}_{request.exp_id}_probs.npz"


# Regime-A instance: no manifest, so it materializes a scope it is HANDED
# but refuses to BUILD one, by name (PR-12bc B8).
register_task_data_path(PetsTaskDataPath())
