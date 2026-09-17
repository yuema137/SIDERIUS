"""Versioned public identifiers for SIDERIUS-owned materialized view ABIs."""

NUMERIC_ARRAY_V1 = "siderius.numeric-array.v1"
TIMESERIES_ARRAY_V1 = "siderius.timeseries-array.v1"

# The generated-program runner implements exactly these read-only v1 ABIs.
GENERATED_PROGRAM_VIEW_FORMATS_V1 = frozenset({NUMERIC_ARRAY_V1, TIMESERIES_ARRAY_V1})
