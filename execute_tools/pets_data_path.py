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

from collections.abc import Iterable
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
    ValidationScopeError,
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


class PetsTaskDataPath:
    """The registered Pets implementation of the four-method seam."""

    task_data_path_id: ClassVar[str] = PETS_TASK_DATA_PATH_ID

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
        rows = sorted((str(image_id), int(pred)) for image_id, pred in outputs)
        path = Path(request.output_dir) / deliverable_name(request)
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write("image_id,predicted_class_index\n")
            for image_id, pred in rows:
                fh.write(f"{image_id},{pred}\n")

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
        return payload


def deliverable_name(request: DeliverableWriteRequest | EvaluationReadRequest) -> str:
    """ONE naming rule, both directions (write + read)."""
    return f"predictions_{request.model_type}_{request.run_name}_{request.exp_id}.csv"


register_task_data_path(PetsTaskDataPath())
