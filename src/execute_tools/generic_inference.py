"""The GENERIC inference iteration — one extracted, testable unit (PR-12d, seam C).

Step 12 / PR-12d, §D.C (B7). Before this, ``inference_single.py::main``
DEFINED the framework's inference contract as TIDMAD's::

    for file_index, psd_segment_indices in sorted(sample_set.items()):
        fname = profile_dataset.validation_file_name(file_index)
        with h5py.File(fname) as f:            # TIDMAD channel reads
            ...                                 # PSD slicing
        data_path.write_deliverable([(file_index, denoised, injected)], ...)

Every line of that is TIDMAD's PHYSICS, and none of it is a framework
contract. A 37-way image classifier has no PSD segments; a frame-window
predictor has no validation file per partition. So this module states what
the framework actually needs, and nothing more:

```text
task scope  ->  TaskDataPath.validation_dataset(scope, params)   [FROZEN method]
            ->  a torch Dataset in a DETERMINISTIC order
            ->  forward pass, batch by batch, shuffle=False
            ->  per-sample outputs IN THAT ORDER
            ->  TaskDataPath.write_deliverable(outputs, request) [FROZEN method]
```

**Reuse before invention, discharged explicitly (§D.C's proof obligation).**
No new capability family was added. The iteration uses ``validation_dataset``
and ``write_deliverable`` — two of the four FROZEN ``TaskDataPath`` methods.
The existing ``DeliverableWriteRequest`` carries the opaque ``task_scope`` and
an optional run-bound source context. The latter lets a source-aware task
rematerialize its own validation values without retaining an entire dataset in
framework memory or teaching the framework task vocabulary.

**Why the scope and source context ride the write request.**
``write_deliverable`` needs to pair
each output with the identity of the sample that produced it — an
``image_id`` for Pets, a ``(sequence, start_frame)`` clip for DAVIS. That
pairing is TASK vocabulary: the framework must not learn that a Pets scope has
``.rows`` whose members have ``.image_id``. So the framework supplies the two
things it legitimately owns — the scope it iterated, and the outputs IN THAT
ORDER — and the task pairs them in its own file. If the deliverable also needs
source- or supervision-associated values, the task uses the supplied physical
data root to invoke its same ``validation_dataset`` method and checks the
declared sample count before pairing.

Every composed task carrying an evaluation scope uses this route, including
external scientific tasks. The legacy indexed loop in ``inference_single.py``
is a separate compatibility route. A transported Model-I/O contract must reach
this iterator's input conversion; task storage dtype is not a model contract.
"""

from __future__ import annotations

import time
from collections.abc import Sized

import torch
from pydantic import BaseModel, ConfigDict, Field
from torch.utils.data import DataLoader

from execute_tools.inference_forward import forward_inference_batch
from execute_tools.task_data_path import (
    DeliverableSourceContext,
    DeliverableWriteRequest,
    EvalMaterializationParams,
    TaskDataPath,
    resolve_max_inference_batch_size,
    task_declared_deliverable_name,
)


class GenericInferenceOutcome(BaseModel):
    """What one generic inference pass produced, for the child's result JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    samples: int = Field(ge=0, description="Samples the scope materialized to.")
    batches: int = Field(ge=0, description="Forward passes executed.")
    inference_seconds: float = Field(ge=0.0)
    deliverable_name: str = Field(min_length=1, description="What the task wrote.")


def run_generic_inference(
    *,
    data_path: TaskDataPath,
    task_scope: object,
    model: torch.nn.Module,
    device: torch.device,
    data_dir: str,
    batch_size: int,
    write_request: DeliverableWriteRequest,
    input_dtype: torch.dtype | None = None,
) -> GenericInferenceOutcome:
    """Iterate a task's own evaluation scope and persist its own deliverable.

    Args:
        data_path: the run's BOUND implementation. Resolved by the caller, so
            this unit states its dependency rather than reaching for ambient
            state.
        task_scope: the task's opaque evaluation scope, already verified and
            deserialized by the transport.
        model: the loaded model, already on ``device`` and in ``eval()``.
        device: where the forward pass runs.
        data_dir: the run's PHYSICAL data root (Step 11 C4's composed value).
        batch_size: forward-pass batch size.
        write_request: identity and location for the deliverable. Its
            ``task_scope`` field is populated HERE, from ``task_scope``, so a
            caller cannot pass one and iterate another.
        input_dtype: cast for the model input when the run declares one.

    Returns:
        The pass's own accounting.

    Raises:
        Whatever the implementation raises. ``validation_dataset`` owns the
        exact-materialization obligation and fails closed by contract; this
        unit never pads, truncates or reorders.
    """
    started = time.perf_counter()
    task_batch_ceiling = resolve_max_inference_batch_size(data_path)
    if task_batch_ceiling is not None and batch_size > task_batch_ceiling:
        raise ValueError(
            f"inference batch {batch_size} exceeds the task-declared maximum "
            f"of {task_batch_ceiling}"
        )
    dataset = data_path.validation_dataset(task_scope, EvalMaterializationParams(data_dir=data_dir))
    if not isinstance(dataset, Sized):
        raise TypeError("validation_dataset must return a sized, map-style dataset")
    dataset_size = len(dataset)
    # `shuffle=False` and `drop_last=False` are LOAD-BEARING, not defaults:
    # the outputs are handed back positionally, so any reordering or dropped
    # tail would silently mis-pair every sample with somebody else's identity.
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, drop_last=False)

    produced = 0
    batches = 0

    def _prediction_stream():
        """Yield detached predictions without retaining the complete scope."""
        nonlocal batches, produced
        for batch in loader:
            # `validation_dataset` yields (model_input, supervision_target);
            # inference consumes the input and ignores the target, which is
            # present because ONE method serves both the R3 pass and this one.
            inputs = batch[0] if isinstance(batch, (list, tuple)) else batch
            predictions = forward_inference_batch(
                model, inputs, device=device, input_dtype=input_dtype, stage="task inference"
            )
            batches += 1
            for prediction in predictions:
                produced += 1
                yield prediction.detach().cpu()

    request = write_request.model_copy(
        update={
            "task_scope": task_scope,
            "source_context": DeliverableSourceContext(
                data_dir=data_dir,
                sample_count=dataset_size,
            ),
        }
    )
    data_path.write_deliverable(_prediction_stream(), request)
    if produced != dataset_size:
        raise RuntimeError(
            f"task deliverable writer consumed {produced} predictions, "
            f"but the evaluation scope materialized {dataset_size} samples"
        )
    return GenericInferenceOutcome(
        samples=produced,
        batches=batches,
        inference_seconds=time.perf_counter() - started,
        deliverable_name=task_declared_deliverable_name(data_path, request),
    )
