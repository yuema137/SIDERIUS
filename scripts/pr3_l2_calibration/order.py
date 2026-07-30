# scripts/pr3_l2_calibration/order.py
"""Frozen execution order for the pilot (protocol §3.2).

Method (recorded per protocol): a FIXED pre-registered interleave
pattern, no RNG — fully auditable and independent of anything
observable at run time. C and T alternate within each scenario so
provider/temporal drift cannot align with one arm; the single
diagnostic sample occupies the pre-registered middle position.
Scenarios run S1 then S2 (ascending fixture size). Retries stay
attached to their sample's position and never create a new one.

Samples are independent stochastic repetitions under identical
configuration — NOT paired-seed samples (no API seed control).
"""

from __future__ import annotations

import json

ORDER_VERSION = "p3l2p-order-1"

PILOT_ORDER: list[dict] = [
    {"idx": 0, "scenario": "S1", "arm": "C", "rep": 1},
    {"idx": 1, "scenario": "S1", "arm": "T", "rep": 1},
    {"idx": 2, "scenario": "S1", "arm": "D", "rep": 1},
    {"idx": 3, "scenario": "S1", "arm": "C", "rep": 2},
    {"idx": 4, "scenario": "S1", "arm": "T", "rep": 2},
    {"idx": 5, "scenario": "S2", "arm": "C", "rep": 1},
    {"idx": 6, "scenario": "S2", "arm": "T", "rep": 1},
    {"idx": 7, "scenario": "S2", "arm": "D", "rep": 1},
    {"idx": 8, "scenario": "S2", "arm": "C", "rep": 2},
    {"idx": 9, "scenario": "S2", "arm": "T", "rep": 2},
]


def write_manifest(path: str, fixture_hashes: dict[str, str]) -> dict:
    manifest = {
        "order_version": ORDER_VERSION,
        "method": "fixed pre-registered interleave, no RNG",
        "order": PILOT_ORDER,
        "fixture_hashes": fixture_hashes,
        "note": (
            "Order frozen before any LLM output was observed; retries "
            "attach to their original sample index."
        ),
    }
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest
