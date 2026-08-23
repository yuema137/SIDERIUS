"""
Dataset configuration — physical constants for a specific dataset.

All data-processing modules import from here instead of hardcoding constants.
TIDMAD is the default. Other datasets override by creating a different
DatasetConfig instance.

Constants:
    psd_segment_length:  Number of raw samples per PSD segment (1 second
                         at the dataset's sampling rate).
    segments_per_file:   Number of usable PSD segments per validation file.
    num_files:           Number of validation/training files.
    sampling_frequency:  Sampling rate in Hz (used for PSD frequency axis).
    training_file_pattern:    Format string for training file names.
    validation_file_pattern:  Format string for validation file names.
"""

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from string import Formatter
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

# Arbitrary in-range index used only to probe that a filename pattern
# actually formats. Never used to build a path that is read.
_PATTERN_PROBE_INDEX = 7


class DatasetConfig(BaseModel):
    """Physical constants for a dataset. Immutable once created."""

    psd_segment_length: int = Field(
        description="Number of raw samples per PSD segment.",
    )
    segments_per_file: int = Field(
        description="Number of usable PSD segments per file.",
    )
    num_files: int = Field(
        description="Number of validation/training files.",
    )
    sampling_frequency: float = Field(
        description="Sampling rate in Hz.",
    )
    training_file_pattern: str = Field(
        default="abra_training_{file_index:04d}.h5",
        description="Format string for training file names. Use {file_index}.",
    )
    validation_file_pattern: str = Field(
        default="abra_validation_{file_index:04d}.h5",
        description="Format string for validation file names. Use {file_index}.",
    )

    @field_validator("training_file_pattern", "validation_file_pattern")
    @classmethod
    def _validate_file_index_placeholder(cls, value: str, info: ValidationInfo) -> str:
        """Reject filename patterns that cannot map an index to a distinct file.

        ``str.format()`` does NOT raise when a replacement field is absent, so
        a pattern like ``"training_file.h5"`` maps EVERY file index to the SAME
        filename — a whole run would train and score on one file with no error
        raised anywhere. This validator is the only place that failure mode is
        caught, and it fires at config construction, before any file is opened.

        Two checks, in order:

        1. a ``file_index`` replacement field is present — the silent case
           above, and the only one ``.format()`` will not surface itself;
        2. the pattern actually formats with an integer index — catches
           unknown fields, bad format specs, and index/attribute access. Those
           all DO raise, but at training time; the probe moves them here.

        Args:
            value: The candidate pattern.
            info:  Pydantic validation context (supplies the field name).

        Returns:
            The pattern unchanged when both checks pass.

        Raises:
            ValueError: The pattern has no usable ``file_index`` field, is not
                a valid format string, or does not format with an int index.
        """
        field = info.field_name
        try:
            field_names = [name for _, name, _, _ in Formatter().parse(value)]
        except ValueError as exc:
            raise ValueError(f"{field}={value!r} is not a valid format string ({exc}).") from exc
        # "file_index[0]" / "file_index.attr" carry the base name plus access
        # syntax; strip it so presence is judged on the name itself. Such
        # patterns pass this check and are then rejected by the format probe.
        base_names = {name.split("[")[0].split(".")[0] for name in field_names if name}
        if "file_index" not in base_names:
            raise ValueError(
                f"{field}={value!r} has no {{file_index}} replacement field, so every "
                f"file index would resolve to the same filename. str.format() does not "
                f"raise on an absent field, so this would corrupt a run silently rather "
                f"than fail. Use e.g. 'training_{{file_index}}.h5' or "
                f"'training_{{file_index:04d}}.h5'."
            )
        try:
            value.format(file_index=_PATTERN_PROBE_INDEX)
        except Exception as exc:
            raise ValueError(
                f"{field}={value!r} contains a {{file_index}} field but does not format "
                f"with an integer index ({type(exc).__name__}: {exc})."
            ) from exc
        return value

    def training_file_name(self, file_index: int) -> str:
        """Return the training filename for ``file_index``.

        The single place a training filename is built from the pattern, so
        loaders never re-inline a dataset-specific template.
        """
        return self.training_file_pattern.format(file_index=file_index)

    def validation_file_name(self, file_index: int) -> str:
        """Return the RAW validation filename for ``file_index``.

        The counterpart to :meth:`training_file_name`, and the first real
        consumer of ``validation_file_pattern`` — a seam that shipped without
        one (roadmap §0.8's seam-without-consumer anti-pattern). Before this
        existed, the raw validation name was re-inlined as an f-string at
        eight production sites, two of which built it two different ways
        (``f"{i:04d}"`` vs ``str(i).zfill(4)``).

        **Scope boundary.** This returns the RAW INPUT filename, which is
        Step-02-owned topology. It must never be used to build a
        DENOISED/deliverable name: that template belongs to the Deliverable
        Contract, whose owner is still an open convergence-ledger question.
        """
        return self.validation_file_pattern.format(file_index=file_index)

    def valid_segmentation_sizes(self, lo: int = 100, hi: int = 100_000) -> list[int]:
        """Return sorted divisors of ``psd_segment_length`` in ``[lo, hi]``.

        ``segmentation_size`` (a model-config field) must exactly divide
        ``psd_segment_length`` so a PSD segment splits cleanly into ML segments.
        This helper enumerates the legal values for use in validators and prompts.

        Uses sqrt enumeration so it is fast even for large ``psd_segment_length``.
        """
        psd = self.psd_segment_length
        divisors: set[int] = set()
        i = 1
        while i * i <= psd:
            if psd % i == 0:
                if lo <= i <= hi:
                    divisors.add(i)
                j = psd // i
                if lo <= j <= hi:
                    divisors.add(j)
            i += 1
        return sorted(divisors)


# ---------------------------------------------------------------------------
# DataScope — which subset of the dataset a run may access
# ---------------------------------------------------------------------------


class ScopeViolationError(ValueError):
    """A SampleSet (or file access) referenced files outside the DataScope.

    Subclass of ``ValueError`` so callers with an existing "raises
    ValueError" contract (e.g. ``score_vector``) are unaffected, while the
    sandbox executors can catch this class specifically and convert it into
    their structured error-dict contract with
    ``error_type="scope_violation"`` — a non-retryable configuration/
    invariant failure, never a transient training error.
    """


class DataScope(BaseModel):
    """Which subset of the dataset this run may access.

    Sits between :class:`DatasetConfig` (the complete dataset) and the
    sampling strategies (how to sample within the allowed subset)::

        DatasetConfig → DataScope → sampling strategy → SampleSet → execution

    ``file_indices=None`` means the complete dataset. "File" is the dataset's
    partition unit as defined by the :class:`DatasetConfig` file patterns —
    a future dataset whose partitions are not literal files maps its own
    partition notion onto integer indices. If richer scope shapes are ever
    needed (time ranges, named splits), extend via a discriminated union so
    ``resolve()`` consumers stay untouched.

    Instances are frozen (hashable, safe to share across components). The
    validator normalizes ``file_indices`` to a sorted, deduplicated list at
    construction, so equality and serialization are canonical.

    See ``docs/design/enable_partial_file_list.md``.
    """

    model_config = ConfigDict(frozen=True)

    file_indices: list[int] | None = Field(
        default=None,
        description=(
            "Allowed file indices, or None for the complete dataset. "
            "Normalized to sorted/deduplicated at construction; must be "
            "non-empty and non-negative when provided."
        ),
    )

    @field_validator("file_indices")
    @classmethod
    def _normalize(cls, v: list[int] | None) -> list[int] | None:
        """Sort, dedupe, and bound-check below zero. Empty list is illegal."""
        if v is None:
            return None
        if not v:
            raise ValueError(
                "DataScope.file_indices must be non-empty when provided — "
                "an empty scope is never legal. Use file_indices=None for "
                "the complete dataset."
            )
        normalized = sorted(set(v))
        if normalized[0] < 0:
            raise ValueError(f"DataScope.file_indices must be non-negative, got {normalized[0]}.")
        return normalized

    @classmethod
    def default(cls) -> "DataScope":
        """The complete dataset (resolves to all files of any dataset)."""
        return cls(file_indices=None)

    @classmethod
    def from_cli(cls, spec: str) -> "DataScope":
        """Parse a CLI scope spec into a DataScope.

        Accepts comma-separated tokens, each either a single index or an
        inclusive ``a-b`` range: ``"4-9"``, ``"4,5,6,7,8,9"``, and mixed
        forms like ``"0-3,7"``.

        Raises:
            ValueError: On an empty spec, a malformed token, or a
                descending range (``"9-4"``).
        """
        if not spec or not spec.strip():
            raise ValueError("DataScope.from_cli: empty scope spec.")
        indices: list[int] = []
        for token in spec.split(","):
            token = token.strip()
            if not token:
                raise ValueError(f"DataScope.from_cli: empty token in spec {spec!r}.")
            # Range token "a-b" (split from position 1 so a leading minus
            # sign is not mistaken for a range separator and falls through
            # to int() → a clear negative-index error from the validator).
            if "-" in token[1:]:
                lo_str, _, hi_str = token[1:].partition("-")
                try:
                    lo = int(token[0] + lo_str)
                    hi = int(hi_str)
                except ValueError as e:
                    raise ValueError(
                        f"DataScope.from_cli: malformed range token {token!r} in spec {spec!r}."
                    ) from e
                if lo > hi:
                    raise ValueError(
                        f"DataScope.from_cli: descending range {token!r} "
                        f"in spec {spec!r} (expected low-high)."
                    )
                indices.extend(range(lo, hi + 1))
            else:
                try:
                    indices.append(int(token))
                except ValueError as e:
                    raise ValueError(
                        f"DataScope.from_cli: malformed token {token!r} in spec {spec!r}."
                    ) from e
        return cls(file_indices=indices)

    def to_cli(self) -> str | None:
        """The inverse of :meth:`from_cli`: the operator spelling, or ``None``.

        Step 12 / PR-12bc B5. A composed run transports the operator's
        partition restriction as an OPAQUE string (``ScopeBuildRequest.
        subset_ref``) which the TASK interprets, so the framework needs a way
        to spell a scope it already holds. ``None`` for the complete dataset,
        which is what "no restriction" means — deliberately not the empty
        string, which ``from_cli`` would have to disambiguate.
        """
        if self.file_indices is None:
            return None
        return ",".join(str(i) for i in self.file_indices)

    def resolve(self, partition_count: int) -> list[int]:
        """Return the concrete allowed partition indices.

        ``None`` resolves to every partition. Explicit indices are validated
        against the bound — resolution is the single place where scope meets
        the dataset's partition domain.

        Step 12 / PR-12bc B2 (Q-12-4): the parameter is the **partition
        count**, not a ``DatasetConfig``. This function only ever read
        ``num_files``, and the partition count is generic identity while the
        rest of that object is task-owned topology. Taking the whole config
        made a purely generic operation look like it needed TIDMAD's
        geometry.

        Args:
            partition_count: How many partitions the dataset has —
                ``DatasetProfile.partition_count``.

        Returns:
            Sorted list of allowed partition indices (a fresh copy).

        Raises:
            ValueError: If any index is outside ``[0, partition_count)``.
        """
        if self.file_indices is None:
            return list(range(partition_count))
        out_of_range = [i for i in self.file_indices if i >= partition_count]
        if out_of_range:
            raise ValueError(
                f"DataScope file_indices {out_of_range} out of range for "
                f"dataset with num_files={partition_count} "
                f"(valid: 0..{partition_count - 1})."
            )
        return list(self.file_indices)

    def is_full(self, partition_count: int) -> bool:
        """Whether this scope covers every partition."""
        return self.resolve(partition_count) == list(range(partition_count))


# ---------------------------------------------------------------------------
# TIDMAD dataset (default)
# ---------------------------------------------------------------------------

TIDMAD = DatasetConfig(
    psd_segment_length=10_000_000,  # 1 second at 10 MS/s
    segments_per_file=200,  # usable segments per validation file
    num_files=20,  # validation files 0-19
    sampling_frequency=10_000_000.0,  # 10 MS/s
    training_file_pattern="abra_training_{file_index:04d}.h5",
    validation_file_pattern="abra_validation_{file_index:04d}.h5",
)

# Backward-compatible module-level constants (import these for existing code)
SEGMENT_LENGTH = TIDMAD.psd_segment_length
SEGMENTS_PER_FILE = TIDMAD.segments_per_file
NUM_FILES = TIDMAD.num_files


# ---------------------------------------------------------------------------
# Dataset Profile — the resolved declaration the production data path reads
# ---------------------------------------------------------------------------


class ChannelIdentity(BaseModel):
    """Which in-file channel is the model INPUT and which is the TRUTH.

    Before this declaration existed the pair was addressed by a hardcoded
    HDF5 path at ~15 production sites (``"timeseries"/"channel0001"`` for the
    input, ``"channel0002"`` for the target) with nothing naming the concept
    — so "which channel is the ground truth" was an undeclared dataset fact
    that no task could override.

    Identity ONLY. Truth *absence* (an unsupervised task with no clean
    channel at all) changes what a model must emit and what can be scored,
    and belongs to the model-contract and metric modules — not here.
    """

    model_config = ConfigDict(frozen=True)

    input_channel: str = Field(
        description="In-file channel holding the model INPUT signal.",
    )
    target_channel: str = Field(
        description="In-file channel holding the TRUTH/target signal.",
    )

    @field_validator("target_channel")
    @classmethod
    def _distinct_from_input(cls, value: str, info: ValidationInfo) -> str:
        """Reject input == target.

        Loaders read the two channels into the input and target slots
        independently, so an identical pair would train a model to predict
        its own input and score it against itself — producing a plausible
        run with meaningless results rather than any error.
        """
        other = info.data.get("input_channel")
        if other is not None and value == other:
            raise ValueError(
                f"target_channel and input_channel are both {value!r}. The truth "
                f"channel must differ from the input channel, or training and "
                f"scoring would compare a signal against itself."
            )
        return value


class ValueEncoding(BaseModel):
    """How raw stored samples map onto the model's class alphabet.

    TIDMAD stores int8 ADC codes and every loader shifts them by ``+128``
    into ``[0, 256)`` before use, with ``minlength=256`` on the class
    histogram. Those three numbers were inlined independently at ~8
    production sites with no declaration tying them together.

    **Scope (frozen).** This DECLARES the data-side encoding and nothing
    more. Deriving a model's input/output contract from it — class counts,
    embedding widths, output heads — belongs to the model-contract module.
    Declaring an encoding here does NOT assert that any model supports it.
    """

    model_config = ConfigDict(frozen=True)

    storage_dtype: str = Field(
        description="NumPy dtype name the samples are stored as on disk, e.g. 'int8'.",
    )
    compute_dtype: str = Field(
        description="NumPy dtype name samples are widened to before the offset is applied.",
    )
    value_offset: int = Field(
        description="Added to a stored sample to move it into [0, num_classes).",
    )
    num_classes: int = Field(
        gt=0,
        description="Size of the class alphabet; the histogram's minlength.",
    )

    @field_validator("num_classes")
    @classmethod
    def _alphabet_covers_the_shifted_range(cls, value: int, info: ValidationInfo) -> int:
        """Reject an alphabet that the declared dtype+offset would overflow.

        A too-small ``num_classes`` does not raise at load time — it silently
        truncates the class histogram, which reweights the loss. Checking it
        here, at construction, is the only place the three fields are visible
        together.
        """
        dtype_name = info.data.get("storage_dtype")
        offset = info.data.get("value_offset")
        if dtype_name is None or offset is None:
            return value
        widths = {"int8": (-128, 127), "uint8": (0, 255), "int16": (-32768, 32767)}
        bounds = widths.get(dtype_name)
        if bounds is None:
            return value
        lo, hi = bounds
        if lo + offset < 0 or hi + offset >= value:
            raise ValueError(
                f"num_classes={value} cannot hold {dtype_name} shifted by "
                f"{offset}: the range becomes [{lo + offset}, {hi + offset}], "
                f"which falls outside [0, {value})."
            )
        return value


class DatasetProfile(BaseModel):
    """The resolved dataset declaration the production data path reads.

    Composes — rather than replaces — :class:`DatasetConfig`, so the shipped
    ``TIDMAD`` object and its ``model_dump()`` stay byte-identical. That
    matters: the Step-00 golden baseline pins ``TIDMAD.model_dump()`` field
    by field, and adding fields to ``DatasetConfig`` would have broken a
    frozen compatibility surface in order to introduce a new one.

    Three declarations, one object::

        dataset   file topology, decomposition geometry, the legality rule
        channels  which channel is input, which is truth
        encoding  dtype, offset, class-alphabet size

    Consumers receive this object; they do not import module-level dataset
    constants and do not re-inline a filename template, a channel name or a
    ``+128``.
    """

    model_config = ConfigDict(frozen=True)

    partition_count: int = Field(
        gt=0,
        description=(
            "**GENERIC IDENTITY.** How many partitions this dataset has — the "
            "cardinality of the index domain :class:`DataScope` addresses.\n\n"
            "Step 12 / PR-12bc B2 (Q-12-4). This is the ONE topology fact "
            "framework infrastructure reasons about with the SAME semantics "
            "across materially different tasks: 16 production sites compute "
            "``list(range(...))`` over it, compare a resolved scope against "
            "it, or allocate one slot per index, and each means the same "
            "thing for TIDMAD files, Pets shards and DAVIS clips. It was "
            "``dataset.num_files``; the rename to ``partition`` is not what "
            "earns it generic status — the consumer audit did (§Q.B2.1)."
        ),
    )
    topology: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "**OPAQUE TASK-OWNED TOPOLOGY.** The task's own physical layout: "
            "TIDMAD's PSD geometry, sampling frequency, file-name patterns, "
            "h5 channel identities and value encoding all live in here.\n\n"
            "**The framework NEVER inspects inside this payload** — it "
            "transports it, serializes it and hands it back to the task. "
            "There is deliberately no ``TidmadTopology | PetsTopology | "
            "DavisTopology`` union and no catalog of optional built-in "
            "blocks: one optional built-in block is the same defect with "
            "N=1, and it is exactly what forced the Pets fixture to declare "
            "``sampling_frequency: 1.0`` and ``psd_segment_length: 256`` for "
            "an image-classification task.\n\n"
            "A task that has no physical topology to declare leaves it "
            "empty and every generic-identity reader still works."
        ),
    )

    # --- Task-owned file sets (Step 02c) --------------------------------
    #
    # Two SEPARATE declarations, deliberately not one mapping. They answer
    # different scientific questions, are consumed by different subsystems,
    # and a future task may well set one without the other being
    # interesting. A generic ``groups: dict[str, list[int]]`` would make
    # them look interchangeable and would invite a third "all files" entry
    # — which must never exist, because "every file" already has an
    # authority in ``dataset.num_files``.
    #
    # Both are REQUIRED. A TIDMAD-shaped default here would be exactly the
    # smuggling that ``DatasetProfile`` was introduced to stop: a new task
    # would silently inherit somebody else's frequency bands and produce
    # plausible, wrong selections. There is no formula to fall back on —
    # neither list is derivable from the topology.

    anchor_selection_files: list[int] = Field(
        description=(
            "Files the ``anchors`` selection strategy trains on — the "
            "task's own choice of maximally informative representatives. "
            "TIDMAD declares [0, 10, 19] (low/mid/high frequency extrema). "
            "NOT derived as [0, n//2, n-1]: that expression merely "
            "coincides with TIDMAD's value at n=20, and a coincidence is "
            "not a contract for inventing another task's science. "
            "Declaration order is preserved — it is the order the sample "
            "set is populated in."
        ),
    )
    health_peek_files: list[int] = Field(
        description=(
            "Files the task's blocking health checks peek by default. "
            "TIDMAD declares [3, 10, 17] — INTERIOR low/mid/high "
            "frequency-band representatives, which is why no arithmetic on "
            "``num_files`` produces them and why they must be declared. "
            "This is the DEFAULT only: an explicit run-level "
            "``--health_gate_files`` still overrides it, unchanged.\n\n"
            "It is deliberately NOT the population of the recording-only "
            "checks. Those ship no ``peek_file_indices`` and evaluate every "
            "file; giving them this triplet would silently narrow them from "
            "20 files to 3, which is a HealthGate policy change wearing an "
            "authority change's clothes."
        ),
    )

    #: The legacy document's sections, in their original declaration order.
    #: Named ONCE so the wire reader, the wire writer and ``model_copy``'s
    #: adapter cannot drift — three call sites, one definition of "what the
    #: pre-B2 shape was".
    _LEGACY_SECTIONS: ClassVar[tuple[str, ...]] = ("dataset", "channels", "encoding")

    @staticmethod
    def _partition_count_from_legacy(topology: Mapping[str, Any]) -> int | None:
        """The partition count a LEGACY topology payload carries, if any.

        The one place the legacy shape's interior is read. Every other
        framework site reads :attr:`partition_count`.
        """
        dataset = topology.get("dataset")
        if isinstance(dataset, Mapping):
            count = dataset.get("num_files")
        else:
            # Direct keyword construction — ``DatasetProfile(dataset=TIDMAD,
            # …)`` — hands a MODEL here, not a mapping. Accepted for the same
            # reason the mapping form is: it is the pre-B2 spelling, and
            # rejecting it would turn a legacy caller into an obscure
            # "partition_count field required" instead of just working.
            count = getattr(dataset, "num_files", None)
        return count if isinstance(count, int) else None

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Any:
        """``model_copy`` that still understands the legacy section names.

        Step 12 / PR-12bc B2, and it is a CORRECTNESS fix rather than a
        convenience. ``model_copy(update=...)`` bypasses validation entirely
        in Pydantic v2, so after the split
        ``profile.model_copy(update={"dataset": smaller})`` would have
        SILENTLY DONE NOTHING — the caller would get a profile still carrying
        20 partitions and no error anywhere. That is precisely the class of
        quiet wrongness this contract exists to remove, so the legacy section
        names are translated into a topology update instead, and
        ``partition_count`` follows ``num_files`` rather than going stale.
        """
        if update:
            legacy = {k: update[k] for k in self._LEGACY_SECTIONS if k in update}
            if legacy:
                update = {k: v for k, v in update.items() if k not in legacy}
                topology = dict(self.topology)
                for key, value in legacy.items():
                    topology[key] = (
                        value.model_dump() if isinstance(value, BaseModel) else dict(value)
                    )
                update["topology"] = topology
                if "partition_count" not in update:
                    resolved = self._partition_count_from_legacy(topology)
                    if resolved is not None:
                        update["partition_count"] = resolved
        return super().model_copy(update=dict(update) if update else None, deep=deep)

    @model_validator(mode="before")
    @classmethod
    def _accept_the_legacy_wire_form(cls, data: Any) -> Any:
        """BOUNDED LEGACY ADAPTER: read a pre-B2 profile document.

        Step 12 / PR-12bc B2. The `--dataset_profile_json` wire form predates
        the generic/opaque split and its **bytes are contract** (R-11-13):
        every committed profile snapshot, every persisted config a resume
        reads, and the Step-00 golden are written in it. This adapter is the
        ONE place that shape is understood.

        ```text
        LEGACY IN   {"dataset": {...,"num_files": N}, "channels": {...},
                     "encoding": {...}, "anchor_selection_files": [...],
                     "health_peek_files": [...]}
        INTERNAL    {"partition_count": N, "topology": {dataset, channels,
                     encoding}, "anchor_selection_files": [...],
                     "health_peek_files": [...]}
        ```

        **This is not the framework inspecting task topology.** It is the
        framework parsing its OWN legacy serialization, which happens to be
        TIDMAD-shaped because it predates the split. A profile authored in
        the new form passes through untouched, and nothing downstream of this
        function looks inside ``topology`` again — which is what the §Q.B2
        census enforces.

        Bounded exactly as 08b's ``TASK_HEALTH_PEEK`` adapter is: it exists
        so existing documents stay readable, it is named, it is tested, and
        it is the only legacy reader.
        """
        if not isinstance(data, dict):
            return data
        if "partition_count" in data:
            return data  # already the internal form
        if "dataset" not in data:
            return data  # let the schema report what is actually missing
        legacy = dict(data)
        topology: dict[str, Any] = {}
        for key in cls._LEGACY_SECTIONS:
            if key in legacy:
                # Normalized to plain data AND copied: the topology is an
                # OPAQUE payload, so a model handed in by a legacy keyword
                # caller becomes its dump, and a caller's dict must not
                # become live state inside a frozen profile.
                section = legacy.pop(key)
                topology[key] = (
                    section.model_dump() if isinstance(section, BaseModel) else deepcopy(section)
                )
        resolved = cls._partition_count_from_legacy(topology)
        if resolved is None:
            return data  # malformed: let the schema say so, do not guess
        legacy["partition_count"] = resolved
        legacy["topology"] = topology
        return legacy

    def to_wire(self) -> dict[str, Any]:
        """The LEGACY observable form, for transport and persistence.

        §D.3a: the internal domain model has ONE semantic authority; legacy
        byte compatibility lives HERE, at the boundary, rather than by
        retaining duplicate live physical fields.

        For any profile whose topology carries the legacy sections this
        reproduces the pre-B2 document **byte-identically** — the property
        `--dataset_profile_json` and the Step-00 golden depend on. A profile
        with no such topology serializes its generic identity plus whatever
        the task did declare; there is no TIDMAD-shaped default to fall back
        on and none is invented.
        """
        # DEEP-COPIED, never aliased. ``DatasetProfile`` is frozen, but a
        # plain ``dict`` inside it is not: returning the profile's own
        # sections would let ``profile.to_wire()["dataset"].update(...)`` —
        # the obvious way to build a variant — silently mutate the SHIPPED
        # profile for the rest of the process. That is not hypothetical; it
        # is what this method did when first written, and it poisoned every
        # later test in the same interpreter.
        wire: dict[str, Any] = {}
        for key in self._LEGACY_SECTIONS:
            if key in self.topology:
                wire[key] = deepcopy(self.topology[key])
        extra = {k: deepcopy(v) for k, v in self.topology.items() if k not in wire}
        if extra:
            wire["topology"] = extra
        if "dataset" not in wire:
            # Nothing in this task's topology carries the legacy partition
            # count, so the generic identity must cross explicitly or the
            # child could not reconstruct it.
            wire["partition_count"] = self.partition_count
        wire["anchor_selection_files"] = list(self.anchor_selection_files)
        wire["health_peek_files"] = list(self.health_peek_files)
        return wire

    @model_validator(mode="after")
    def _declared_file_sets_are_legal_for_this_topology(self) -> "DatasetProfile":
        """Both declared file sets must index files this dataset has.

        Checked here rather than on a sub-model because ``num_files`` lives
        on a SIBLING field: only the assembled profile can see a declared
        index and the topology it must be legal against.

        Empty is rejected. An empty anchor set would build an empty sample
        set — a run that trains on nothing and reports a score; an empty
        peek set would fall THROUGH the configured tier into the
        single-file/all-files fallbacks rather than meaning "monitor
        nothing", which is the same falsy-list trap
        ``apply_monitored_files`` already refuses. "Monitor nothing" is
        spelled ``health_gate_enabled=False``.

        Duplicates are rejected rather than silently deduplicated. Both
        consumers do dedupe what they are handed, so a duplicate here
        cannot corrupt a selection — but in a DECLARATION it is an
        authoring mistake, and the profile's other validators
        (``_distinct_from_input``, ``_alphabet_covers_the_shifted_range``)
        establish that this object fails loudly rather than quietly
        repairing. Consumer-side dedupe of RUNTIME lists is untouched.
        """
        num_files = self.partition_count
        for field_name in ("anchor_selection_files", "health_peek_files"):
            declared: list[int] = getattr(self, field_name)
            if not declared:
                raise ValueError(
                    f"{field_name} is empty. A task must declare which files "
                    f"this set contains; an empty list does not mean 'none' "
                    f"to any consumer — it falls through to a fallback."
                )
            duplicates = sorted({i for i in declared if declared.count(i) > 1})
            if duplicates:
                raise ValueError(
                    f"{field_name}={declared} contains duplicate indices "
                    f"{duplicates}. Declare each file once."
                )
            out_of_range = sorted(i for i in declared if not 0 <= i < num_files)
            if out_of_range:
                raise ValueError(
                    f"{field_name}={declared} indexes files {out_of_range} "
                    f"that this dataset does not have (num_files={num_files}, "
                    f"valid: 0..{num_files - 1})."
                )
        return self


# The shipped TIDMAD profile.
#
# REGIME-A COMPATIBILITY ADAPTER, not a universal framework default. Every
# value below is a property of the TIDMAD dataset specifically; a bound task
# declares its own. The adapter exists so an existing caller that predates
# the profile transport keeps resolving exactly today's behaviour — it is
# NOT a statement about what a generic dataset looks like.
TIDMAD_CHANNELS = ChannelIdentity(
    input_channel="channel0001",
    target_channel="channel0002",
)
TIDMAD_ENCODING = ValueEncoding(
    storage_dtype="int8",
    compute_dtype="int16",
    value_offset=128,
    num_classes=256,
)

TIDMAD_PROFILE = DatasetProfile(
    partition_count=TIDMAD.num_files,
    # TIDMAD's own physical layout, as OPAQUE task topology (B2 / Q-12-4).
    # Built from the same three declarations as before, dumped in their
    # declaration order so `to_wire()` reproduces the pre-B2 document
    # byte-identically.
    topology={
        "dataset": TIDMAD.model_dump(),
        "channels": TIDMAD_CHANNELS.model_dump(),
        "encoding": TIDMAD_ENCODING.model_dump(),
    },
    # TIDMAD's own task-owned file sets. Both were hardcoded before Step
    # 02c — the anchors list at sample_set_builder.py, the peek triplet as
    # a YAML literal PLUS a hardcoded copy inside the campaign validator.
    anchor_selection_files=[0, 10, 19],
    health_peek_files=[3, 10, 17],
)


# ---------------------------------------------------------------------------
# TIDMAD's typed topology view — TASK-OWNED, never read by generic core
# ---------------------------------------------------------------------------
#
# Step 12 / PR-12bc B2. `DatasetConfig`, `ChannelIdentity` and `ValueEncoding`
# stopped being FIELDS of `DatasetProfile` because no cross-task framework
# consumer reasons about them with one semantics (§Q.B2.1). They remain the
# TYPES through which TIDMAD reads its own opaque payload.
#
# The census in `tests/unit/execute_tools/test_step12_pr12bc_b2_topology_contract.py`
# is what keeps this honest: a module on the GENERIC list that calls
# `tidmad_topology()` turns it RED. Being declared in this file is not the
# same as being read by generic core, and the census asserts the second.


class TidmadTopology(BaseModel):
    """TIDMAD's physical layout, decoded from the opaque topology payload."""

    model_config = ConfigDict(frozen=True)

    dataset: DatasetConfig
    channels: ChannelIdentity
    encoding: ValueEncoding


def tidmad_topology(profile: DatasetProfile) -> TidmadTopology:
    """Decode ``profile``'s opaque payload as TIDMAD's typed topology.

    **FAILS CLOSED.** A profile whose topology does not carry TIDMAD's
    sections is a profile TIDMAD's code cannot run against, and saying so by
    name is the whole point of the split — the alternative is what the Pets
    fixture had to do, invent a ``sampling_frequency`` for a task that has no
    sampling frequency.

    Raises:
        ValueError: The payload is missing a section or does not satisfy the
            typed view.
    """
    missing = [k for k in ("dataset", "channels", "encoding") if k not in profile.topology]
    if missing:
        raise ValueError(
            f"this dataset profile declares no TIDMAD topology (missing "
            f"{missing}); its topology keys are {sorted(profile.topology)}. "
            f"TIDMAD-physical code cannot run against a task that did not "
            f"declare TIDMAD's physical layout."
        )
    try:
        return TidmadTopology.model_validate(
            {k: profile.topology[k] for k in ("dataset", "channels", "encoding")}
        )
    except ValidationError as exc:
        raise ValueError(
            f"this dataset profile's topology does not satisfy TIDMAD's typed view ({exc})."
        ) from exc


def resolve_tidmad_topology() -> TidmadTopology:
    """The bound profile's TIDMAD topology — the regime-A convenience hop.

    Exists so the many TIDMAD-physical call sites do not each repeat
    ``tidmad_topology(resolve_dataset_profile())``.
    """
    return tidmad_topology(resolve_dataset_profile())


_ACTIVE_PROFILE: ContextVar[DatasetProfile | None] = ContextVar(
    "siderius_active_dataset_profile", default=None
)


def resolve_dataset_profile() -> DatasetProfile:
    """Return the dataset profile in effect for the current context.

    This is the **Regime-A resolution seam**, for the small number of
    consumers that need the profile where an argument cannot reach them —
    Pydantic field validation and module-scope constants, which run at import
    or validation time with no caller to thread a parameter through.

    **Prefer an explicit argument.** Ordinary consumers take the profile as a
    parameter, and the subprocess entry points load it from their own
    explicit config file and pass it down. This accessor is deliberately NOT
    the general injection mechanism, because an ambient lookup hides the
    dependency that the profile object exists to make visible.

    With nothing bound it resolves the shipped TIDMAD profile, preserving
    today's behaviour for every caller that predates the transport.
    """
    return _ACTIVE_PROFILE.get() or TIDMAD_PROFILE


def load_dataset_profile(path: str) -> DatasetProfile:
    """Load a resolved profile from a JSON config file. **FAILS CLOSED.**

    This is the subprocess side of the parent→child transport. The rule it
    enforces is the sharp half of §5c:

    * an explicit profile path that is **missing, unreadable, not JSON, or
      schema-invalid** raises, with a diagnostic naming the path;
    * it **never** falls back to the shipped TIDMAD profile.

    The distinction that matters: *"the flag is present but the file is
    broken"* must fail loudly, because a silent fallback would run a bound
    task against TIDMAD's topology and produce plausible, wrong numbers.
    *"an old caller has never heard of the flag"* is a different case
    entirely — that one keeps Regime-A, and it is handled by the caller
    choosing not to call this function at all.

    Args:
        path: Filesystem path to a JSON document produced by
            ``DatasetProfile.model_dump()``.

    Returns:
        The validated profile.

    Raises:
        ValueError: The path is missing, unreadable, malformed JSON, or does
            not satisfy the :class:`DatasetProfile` schema.
    """
    try:
        with open(path) as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(
            f"dataset profile config not found at {path!r}. A profile path was "
            f"supplied, so this fails closed rather than falling back to the "
            f"shipped TIDMAD profile — a silent fallback would run against the "
            f"wrong dataset topology and produce plausible, wrong numbers."
        ) from exc
    except OSError as exc:
        raise ValueError(f"dataset profile config at {path!r} is unreadable ({exc}).") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"dataset profile config at {path!r} is not valid JSON ({exc}).") from exc

    try:
        return DatasetProfile.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            f"dataset profile config at {path!r} does not satisfy the "
            f"DatasetProfile schema ({exc})."
        ) from exc


@contextmanager
def bind_dataset_profile(profile: DatasetProfile) -> Iterator[DatasetProfile]:
    """Bind ``profile`` for the duration of the ``with`` block.

    Scoped through a :class:`~contextvars.ContextVar` rather than module
    state, so the previous value is always restored — including on an
    exception, and independently per thread or async task. A plain mutable
    global would leak a contrast profile from one test into the next, and
    the leak would surface as an unrelated failure somewhere downstream.
    """
    token = _ACTIVE_PROFILE.set(profile)
    try:
        yield profile
    finally:
        _ACTIVE_PROFILE.reset(token)
