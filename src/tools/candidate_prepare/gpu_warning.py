"""The training-without-GPU advisory for one prepared run (issue #1562).

Preparation never refuses a run for lacking a GPU: it cannot know where the run
will launch, and a workflow without training needs none. When the prepared
worker request declares a ``tuning`` node and its ``devices`` name no GPU device
node, the run's training admission will refuse it (no CPU execution mode), so
the CLI and the console Run review show this warning beforehand. The wording is
owned by ``core.gpu_requirement.training_gpu_warning``.
"""

from __future__ import annotations

from core.gpu_requirement import training_gpu_warning
from tools.candidate_worker.models import CandidateRunRequest


def prepared_gpu_warning(request: CandidateRunRequest) -> str | None:
    """The advisory for ``request``, or None when it does not train or has a GPU node."""
    trains = any(node.capability == "tuning" for node in request.preview.document.definition.nodes)
    return training_gpu_warning(trains=trains, devices=request.devices)
