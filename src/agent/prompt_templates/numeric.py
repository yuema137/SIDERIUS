"""Lossless text for validated floating-point scientific evidence."""


def format_evidence_float(value: float, *, signed: bool = False) -> str:
    """Use the shortest decimal that round-trips, with no precision cutoff.

    Validation and non-finite verdicts belong to the evidence schema/producer.
    This presenter neither changes values nor invents a validity classification.
    """
    text = repr(value)
    return f"+{text}" if signed and not text.startswith("-") else text
