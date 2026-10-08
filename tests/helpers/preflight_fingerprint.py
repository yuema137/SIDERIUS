"""Retain pre-estimator receipts for unrelated composition declarations."""

import hashlib

from workflows import task_composition


def capture_pre_estimator_fingerprints(monkeypatch) -> list[str]:
    """Capture the semantic payload before the two preflight policy additions.

    Callers compare with independently frozen receipts, never a newly computed
    expected hash. Estimator identity arrived in 98c35f31 (#618), followed by
    inference-preflight policy in 73c1cb40 (#621). These receipts predate both;
    current-run identity is separately tested to include both policies.
    """
    canonical = task_composition._canonical
    captured: list[str] = []

    def capture(payload):
        if "preflight_estimator" in payload:
            legacy = {
                key: value
                for key, value in payload.items()
                if key not in {"preflight_estimator", "inference_preflight"}
            }
            captured.append(hashlib.sha256(canonical(legacy).encode()).hexdigest())
        return canonical(payload)

    monkeypatch.setattr(task_composition, "_canonical", capture)
    return captured
