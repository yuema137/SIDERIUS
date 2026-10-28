"""Typed refusal for custom adaptor admission and execution."""

from __future__ import annotations

from typing import Literal

CustomAdaptorReason = Literal[
    "manifest_invalid",
    "package_unreadable",
    "fixture_invalid",
    "custom_invalid_input",
    "custom_timeout",
    "custom_exception",
    "custom_invalid_output",
    "custom_identity_mismatch",
    "custom_nondeterministic",
    "fixture_mismatch",
    "admission_location",
    "admission_conflict",
    "io_error",
]


class CustomAdaptorError(RuntimeError):
    """A custom adaptor cannot be admitted or its invocation failed; never retried."""

    def __init__(self, reason: CustomAdaptorReason, message: str):
        super().__init__(f"[{reason}] {message}")
        self.reason: CustomAdaptorReason = reason
