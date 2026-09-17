"""Render measured training-phase evidence without confusing it with attempt time."""

from __future__ import annotations

import math


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def render_training_epoch_evidence(record: dict) -> str:
    """Summarize a completed attempt's measured loop, or return no claim.

    The parent ``timing.train_time_s`` includes setup and validation. The
    runtime-verification training component excludes both, but includes
    per-epoch data-loader work as well as optimizer steps.
    Refuse conflicting epoch counts rather than pairing unrelated observations.
    """
    params = record.get("params") or {}
    train_config = params.get("train_config") or {}
    configured_epochs = _positive_int(train_config.get("epochs"))
    verification = record.get("runtime_verification") or {}
    training = (verification.get("components") or {}).get("training") or {}
    workload = (training.get("workload") or {}).get("detail") or {}
    measured_epochs = _positive_int(workload.get("epochs"))
    steps_per_epoch = _positive_int(workload.get("steps_per_epoch"))
    actual_seconds = training.get("actual_seconds")

    if (
        configured_epochs is None
        or measured_epochs != configured_epochs
        or steps_per_epoch is None
        or isinstance(actual_seconds, bool)
        or not isinstance(actual_seconds, (int, float))
        or not math.isfinite(actual_seconds)
        or actual_seconds <= 0
    ):
        return ""

    return (
        f"Measured training phase: {configured_epochs} epoch(s), "
        f"{steps_per_epoch} steps/epoch, {actual_seconds / 60:.2f} min actual "
        "(excludes setup, validation and inference). At comparable model, "
        "training data and batch size, more epochs add roughly proportional "
        "optimizer steps; validation may also repeat each epoch. Do not scale "
        "the whole attempt time from this phase measurement.\n"
    )
