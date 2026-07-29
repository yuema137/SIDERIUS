# scripts/pr3_l2_calibration/blind.py
"""Generate blinded rubric scoring copies (protocol §11). No LLM calls.

Creates ``<run_dir>/blinded/`` with shuffled opaque ids. Each scoring
copy contains ONLY: the parsed proposal, the scenario fixture summary,
and an arm-free subset of the deterministic score record. The
id → sample mapping lives in ``blinding_key.json`` OUTSIDE the blinded
directory; reviewers never open it.

Arm-revealing scorer fields (prompt-side facts) are stripped; scenario
is retained (the rubric is scenario-aware by design).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ARM_REVEALING_SCORE_FIELDS = (
    "prompt_has_treatment_block",
    "prompt_has_fingerprint",
    "treatment_isolation_ok",
)


def make_blinded(run_dir: Path) -> dict:
    blinded_dir = run_dir / "blinded"
    blinded_dir.mkdir(exist_ok=True)
    key = {}
    for meta_path in sorted(run_dir.glob("*/sample_meta.json")):
        sample_dir = meta_path.parent
        meta = json.loads(meta_path.read_text())
        sid = meta["sample_id"]
        # Opaque, deterministic, arm-free id.
        bid = "sample_" + hashlib.sha256(f"blind:{sid}".encode()).hexdigest()[:8]
        key[bid] = sid
        proposal_path = sample_dir / "proposal_output.json"
        score_path = sample_dir / "deterministic_score.json"
        score = json.loads(score_path.read_text()) if score_path.exists() else {}
        copy = {
            "blinded_id": bid,
            "scenario": meta["scenario"],
            "schema_valid": score.get("schema_valid"),
            "proposal": (json.loads(proposal_path.read_text()) if proposal_path.exists() else None),
            "deterministic_score_arm_free": {
                k: v for k, v in score.items() if k not in ARM_REVEALING_SCORE_FIELDS
            },
        }
        (blinded_dir / f"{bid}.json").write_text(json.dumps(copy, indent=2))
    (run_dir / "blinding_key.json").write_text(json.dumps(key, indent=2))
    return key


if __name__ == "__main__":
    print(json.dumps(make_blinded(Path(sys.argv[1])), indent=2))
