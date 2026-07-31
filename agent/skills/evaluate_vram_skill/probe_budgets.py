"""Separate, named time budgets for the VRAM pre-flight, and the typed
disposition of a pre-flight that did not finish.

The defect this replaces (V19 campaign `v19r2_10iter_20260731_0750`,
stopped 2026-07-31): ONE 60-second alarm wrapped the ENTIRE
inference-batch search, while that search internally probes seven
candidate batches `(64, 32, 16, 8, 4, 2, 1)`, each with a full
`torchinfo.summary(depth=10)` trace, on CPU. For a 24-block WaveNet at
T=16000 the cumulative cost exceeds 60 s by construction — a property of
OUR search, not of the candidate.

Worse than being wrong, it was wrong in a direction that compounds. The
timeout surfaced as a hard `Resource check error`, the message blamed a
loop "inside `nn.Module.forward`", and the agent — reasonably — concluded
that large models are unsafe and downsized. Nine timeouts later both
chains were proposing models at 2-3 % of their VRAM budget, against
advice that asks for 4-12 GB and cites FCNet's 323 M parameters. The same
configuration both failed and passed depending on CPU load, which is what
proves it was never a capacity signal.

Two rules follow, and this module exists to make them structural:

1. **A budget names the operation it bounds.** Seven sequential checks
   must not share the budget meant for one pathological forward.
2. **Not finishing is not a verdict.** A timeout means the measurement
   did not complete. Only a MEASURED result — a CUDA OOM, or a measured
   peak above the configured cap — may reject a candidate for capacity,
   and only a measured result may tell an agent to make its model
   smaller.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: What a pre-flight attempt concluded.
#:
#: * ``completed``                — the measurement finished; its numbers decide.
#: * ``measured_capacity_failure``— a MEASURED OOM or a measured peak over the
#:                                  configured cap. The only outcome that may
#:                                  reject for capacity or ask for a smaller model.
#: * ``inconclusive``             — the inspection did not finish (timeout,
#:                                  tracing failure). Says nothing about the
#:                                  candidate and must never become capacity
#:                                  evidence or downsizing feedback.
#: * ``infrastructure_failure``   — the measurement system itself is broken.
PreflightDisposition = Literal[
    "completed",
    "measured_capacity_failure",
    "inconclusive",
    "infrastructure_failure",
]

#: Which bounded operation a record belongs to. Each has its OWN budget,
#: so a record can never be read as "one forward took this long" when it
#: is really "a whole search took this long".
ProbeOperation = Literal[
    "model_inspection",
    "batch_candidate",
    "batch_search",
    "training_probe",
    "inference_probe",
    "preflight_total",
]


class ProbeBudgets(BaseModel):
    """Per-operation wall budgets for one VRAM pre-flight.

    Defaults are deliberately generous relative to the old single 60 s
    alarm, because the old value was not a considered limit on anything
    in particular — it was one number doing four jobs. Each budget here
    bounds exactly one operation, so each can be set on its own merits.

    Sizing note: C12 measured the official 323 M-parameter FCNet on this
    environment at 17.68 ms/step and 6.04 GiB peak. A baseline-scale
    model is expected to pass; these budgets exist to stop a pathological
    candidate, not a large one.
    """

    model_config = ConfigDict(frozen=True)

    #: One `torchinfo`/structural inspection of the model.
    single_inspection_seconds: float = Field(default=120.0, gt=0.0)
    #: One candidate batch inside the resolution search.
    single_candidate_seconds: float = Field(default=120.0, gt=0.0)
    #: The whole descending batch search, across every candidate.
    batch_search_seconds: float = Field(default=600.0, gt=0.0)
    #: One bounded training or inference footprint probe.
    single_probe_seconds: float = Field(default=180.0, gt=0.0)
    #: The entire pre-flight. A backstop, not the working limit.
    preflight_total_seconds: float = Field(default=1200.0, gt=0.0)

    def for_operation(self, operation: ProbeOperation) -> float:
        return {
            "model_inspection": self.single_inspection_seconds,
            "batch_candidate": self.single_candidate_seconds,
            "batch_search": self.batch_search_seconds,
            "training_probe": self.single_probe_seconds,
            "inference_probe": self.single_probe_seconds,
            "preflight_total": self.preflight_total_seconds,
        }[operation]


class ProbeTimeoutRecord(BaseModel):
    """Exactly which bounded operation ran out of time, and in what context.

    Every field here exists because its absence previously made a timeout
    unreadable: without the operation name and the candidate batch, nine
    search timeouts looked identical to nine pathological forwards.
    """

    model_config = ConfigDict(frozen=True)

    operation: ProbeOperation
    budget_seconds: float = Field(gt=0.0)
    elapsed_seconds: float = Field(ge=0.0)
    #: Time consumed by the enclosing search when this fired, so a
    #: per-candidate timeout can be told apart from a search that simply
    #: had many candidates.
    search_elapsed_seconds: float | None = Field(default=None, ge=0.0)
    candidate_batch: int | None = Field(default=None, gt=0)
    phase: str | None = None
    model_identity: str
    realized_parameter_count: int | None = Field(default=None, ge=0)
    device: str = "cpu"
    #: How the bound was enforced — an in-process alarm cannot interrupt a
    #: stuck native call, so this is not cosmetic.
    provenance: Literal["in_process_alarm", "subprocess_deadline"] = "in_process_alarm"
    disposition: PreflightDisposition = "inconclusive"

    @property
    def is_capacity_evidence(self) -> bool:
        """Whether this record may influence a capacity decision.

        Always False for a timeout: an operation that did not finish
        measured nothing.
        """
        return self.disposition == "measured_capacity_failure"

    def agent_facing_summary(self) -> str:
        """Text an agent may see.

        Deliberately does NOT speculate about the candidate. The old
        message asserted that the most common cause was a loop inside
        `nn.Module.forward`, which sent agents chasing their own model
        when the loop was in our batch search.
        """
        where = self.operation.replace("_", " ")
        batch = f" at candidate batch {self.candidate_batch}" if self.candidate_batch else ""
        return (
            f"VRAM pre-flight did not complete: the bounded '{where}' step{batch} "
            f"exceeded its {self.budget_seconds:.0f}s budget after "
            f"{self.elapsed_seconds:.1f}s. This is an INCONCLUSIVE inspection "
            f"result, not a measurement of this model. It does NOT indicate the "
            f"model is too large or too slow, and it is not a reason to reduce "
            f"model capacity or batch size."
        )


def timeout_disposition(operation: ProbeOperation) -> PreflightDisposition:
    """A timeout is inconclusive, whichever operation it bounded.

    Kept as a function rather than a constant so the rule has one place
    to live and one place to be argued with.
    """
    return "inconclusive"


def may_recommend_downsizing(disposition: PreflightDisposition) -> bool:
    """Only a MEASURED capacity failure may ask for a smaller model."""
    return disposition == "measured_capacity_failure"


class InconclusivePreflight(Exception):
    """The VRAM pre-flight did not complete.

    Distinct from every capacity error on purpose. An attempt still cannot
    proceed without a footprint, but the reason is "we failed to measure",
    not "the model is too big" — and only the second may reach an agent as
    guidance to shrink anything.
    """

    def __init__(self, message: str, *, record: dict | None = None):
        self.record = record or {}
        super().__init__(message)


# ── Host-memory exception recognition (single source of truth) ──────────────
#
# The second GPU validation (2026-07-31, SHA d83f397) failed because this
# recognition was scattered and incomplete. PyTorch reports a CPU
# allocation failure as a plain `RuntimeError`:
#
#     RuntimeError: [enforce fail at alloc_cpu.cpp:127] err == 0.
#     DefaultCPUAllocator: can't allocate memory: you tried to allocate
#     3152543744 bytes. Error code 12 (Cannot allocate memory)
#
# `except MemoryError` did not catch it, so two candidates were recorded
# as PROBE_INFRASTRUCTURE_FAILURE — i.e. "our machinery is broken" — when
# the machinery worked and the CANDIDATE could not be allocated. A third
# was recorded as a timeout after 3.771 s against a 600 s deadline.
#
# One helper, used by every path, because the previous version had two
# near-identical string checks and the batch resolver's looked for
# "cannot allocate" while PyTorch says "can't allocate".

#: Exception type NAMES that always mean a memory failure, wherever they
#: are raised from. Matched by name so a torch import is never required
#: to classify.
_MEMORY_EXCEPTION_NAMES = frozenset(
    {
        "MemoryError",
        "OutOfMemoryError",
        "CudaOutOfMemoryError",
        "OutOfMemoryException",
    }
)

#: Message fragments, lower-cased. Both apostrophe forms are listed
#: because PyTorch says "can't" and glibc says "cannot".
_MEMORY_MESSAGE_FRAGMENTS = (
    "out of memory",
    "can't allocate memory",
    "cannot allocate memory",
    "can not allocate memory",
    "bad_alloc",
    "defaultcpuallocator",
    "error code 12",
    "enomem",
    "not enough memory",
    "failed to allocate",
    "unable to allocate",
)

#: Fragments that specifically indicate the GPU rather than the host.
_CUDA_MESSAGE_FRAGMENTS = ("cuda", "gpu", "hip")


def is_memory_exception(exc: BaseException) -> bool:
    """Any allocation failure, host or device."""
    if isinstance(exc, MemoryError):
        return True
    if type(exc).__name__ in _MEMORY_EXCEPTION_NAMES:
        return True
    text = str(exc).lower()
    return any(fragment in text for fragment in _MEMORY_MESSAGE_FRAGMENTS)


def classify_host_memory_exception(exc: BaseException) -> str | None:
    """Name the memory failure, or None if it is not one.

    Returns ``"host"`` for a CPU/host allocation failure, ``"cuda"`` for a
    device one. The distinction decides which advice an agent may be
    given: a host failure must never be phrased as a VRAM verdict, because
    the model may fit the GPU perfectly and still have exhausted CPU
    tracing memory.
    """
    if not is_memory_exception(exc):
        return None
    text = str(exc).lower()
    name = type(exc).__name__
    if name in ("OutOfMemoryError", "CudaOutOfMemoryError") or any(
        fragment in text for fragment in _CUDA_MESSAGE_FRAGMENTS
    ):
        return "cuda"
    return "host"
