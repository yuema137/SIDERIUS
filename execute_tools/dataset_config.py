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
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from string import Formatter

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

    def resolve(self, dataset: DatasetConfig) -> list[int]:
        """Return the concrete allowed file indices for ``dataset``.

        ``None`` resolves to every file. Explicit indices are validated
        against the dataset bound — resolution is the single place where
        scope meets dataset definition.

        Returns:
            Sorted list of allowed file indices (a fresh copy).

        Raises:
            ValueError: If any index is outside ``[0, dataset.num_files)``.
        """
        if self.file_indices is None:
            return list(range(dataset.num_files))
        out_of_range = [i for i in self.file_indices if i >= dataset.num_files]
        if out_of_range:
            raise ValueError(
                f"DataScope file_indices {out_of_range} out of range for "
                f"dataset with num_files={dataset.num_files} "
                f"(valid: 0..{dataset.num_files - 1})."
            )
        return list(self.file_indices)

    def is_full(self, dataset: DatasetConfig) -> bool:
        """Whether this scope covers the complete dataset."""
        return self.resolve(dataset) == list(range(dataset.num_files))


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

    dataset: DatasetConfig = Field(
        description="File topology, sample geometry, and the sample-shape legality rule.",
    )
    channels: ChannelIdentity = Field(
        description="Which in-file channel is the model input and which is the truth.",
    )
    encoding: ValueEncoding = Field(
        description="Data-side dtype/offset/class-count declaration.",
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
        num_files = self.dataset.num_files
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
TIDMAD_PROFILE = DatasetProfile(
    dataset=TIDMAD,
    channels=ChannelIdentity(
        input_channel="channel0001",
        target_channel="channel0002",
    ),
    encoding=ValueEncoding(
        storage_dtype="int8",
        compute_dtype="int16",
        value_offset=128,
        num_classes=256,
    ),
    # TIDMAD's own task-owned file sets. Both were hardcoded before Step
    # 02c — the anchors list at sample_set_builder.py, the peek triplet as
    # a YAML literal PLUS a hardcoded copy inside the campaign validator.
    anchor_selection_files=[0, 10, 19],
    health_peek_files=[3, 10, 17],
)


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
