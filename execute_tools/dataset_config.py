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

from pydantic import BaseModel, Field


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
