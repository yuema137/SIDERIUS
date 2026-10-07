"""Independent record facts retained when a formal result becomes a summary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictFloat

from execute_tools.health_checks.schemas import PersistedHealthGateResult


class FormalResultEvidence(BaseModel):
    """Evidence for the exact formal score, not a second validity verdict.

    None and an empty gate roster are distinct. The classifier owns their
    meaning; this projection preserves the producing run's resolved inputs.
    The policy hash is provenance when available, not fabricated proof.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_type: str
    run_name: str
    exp_id: str
    status: str
    denoising_score: StrictFloat | None
    is_trial: StrictBool
    health_gate_enabled: StrictBool | None
    health_gate_results: tuple[PersistedHealthGateResult, ...] = ()
    required_gate_ids: tuple[str, ...] | None
    healthgate_mode: Literal["blocking", "observe_only"] | None
    result_authority: Literal["scientific", "diagnostic"] | None
    health_config_sha256: str | None = None
