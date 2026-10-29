"""Exact rational values for computed (non-metric) rubric scores.

A rubric weighted mean is computed with ``fractions.Fraction`` and carried as its
canonical string (``str(Fraction)``, e.g. ``"4"`` or ``"13/3"``), so ordering, ties
and thresholds compare exact values; floats are display copies only. Declared
decimals (rubric weights, ``threshold/v1`` ``at_least``) enter exact arithmetic as
the decimal they were written as (shortest ``repr``), never as their binary float.
"""

from fractions import Fraction
from typing import Annotated

from pydantic import AfterValidator


def _canonical(text: str) -> str:
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"not an exact rational: {text!r}") from error
    if str(value) != text:
        raise ValueError(f"exact rational {text!r} is not canonical ({value})")
    return text


ExactRational = Annotated[str, AfterValidator(_canonical)]


def decimal_fraction(value: float) -> Fraction:
    """The exact decimal a declared float was written as (``repr`` round-trips)."""
    return Fraction(repr(value))
