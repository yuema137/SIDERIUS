"""Retain pre-estimator receipts for unrelated composition declarations."""

import hashlib

from workflows import task_composition


def capture_pre_estimator_fingerprints(monkeypatch) -> list[str]:
    """Capture the old semantic payload, excluding only the new policy identity.

    Callers compare with independently frozen receipts, never a newly computed
    expected hash. New-run identity is separately tested to include the policy.
    """
    canonical = task_composition._canonical
    captured: list[str] = []

    def capture(payload):
        if "preflight_estimator" in payload:
            legacy = {key: value for key, value in payload.items() if key != "preflight_estimator"}
            captured.append(hashlib.sha256(canonical(legacy).encode()).hexdigest())
        return canonical(payload)

    monkeypatch.setattr(task_composition, "_canonical", capture)
    return captured
