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

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
