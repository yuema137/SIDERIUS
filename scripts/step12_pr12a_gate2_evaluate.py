#!/usr/bin/env python
"""Step 12 / PR-12a — G-12a-2 acceptance evaluation, from persisted artifacts.

Design: ``pr_12a_composed_path_closure.md`` §5 C9 and §6.3. Parent Gate row:
``step_12_external_extensibility_graduation.md`` §14 G-12a-2.

**Written BEFORE the run's outcome was known**, deliberately. A Gate evaluator
authored after reading the results is an evaluator fitted to them, and Step 09b
lost three "findings" to defects in its own probes rather than in production.
This reads only what the chain persisted; it never re-runs anything.

The failure class under test
----------------------------
The composed run's LOCK / FINGERPRINT / RESUME chain across a REAL process
restart: iteration 1 produces the lock and the records, a fresh process for
iteration 2 consumes them, and the composed identity survives.

The three acceptance criteria, verbatim from the frozen disposition:

  A1  iteration 2's pre-flight validates against iteration 1's lock
      (the composition fingerprint is carried, not recomputed or dropped)
  A2  the per-model lock carries the fingerprint AND an honest health identity
  A3  records / outputs are stamped from the ONE run-scoped authority

Explicitly NOT criteria — a Gate never acquires acceptance criteria by
proximity (the Step-10 P5+P6 governance correction):

    model quality · HealthGate PASS · score magnitude · convergence

A collapsed candidate with an INVALID HealthGate round is a legitimate
scientific outcome of this run and says nothing about the failure class above.

Usage::

    ./.venv/bin/python scripts/step12_pr12a_gate2_evaluate.py \\
        --workspace <chain workspace> [--out <evidence dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: The composed identity this run must carry end to end. Hardcoded from the
#: shipped manifest so the check compares against a DECLARED value rather than
#: against whatever the run happened to write.
EXPECTED_FINGERPRINT = "9125bf587fea5bae1493800e9b50bafbb63164ff72ec1bfe3b08520ae1e72aac"

#: Manifest statuses from which `restore_prior_state` legally chains. A failed
#: iteration is REFUSED by design, so chaining off one would be a defect, not a
#: pass — see the attempt-3 log, where that refusal fired correctly.
CHAINABLE = {"completed", "no_records"}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _per_model_locks(workspace: Path) -> list[Path]:
    return sorted(p for p in workspace.rglob("run_invariants_lock.json") if p.parent != workspace)


def check_a1(workspace: Path) -> dict[str, Any]:
    """A1 — iteration 2 consumed iteration 1's committed state in a fresh process.

    Three things must all hold, and the third is what makes it a RESTORE rather
    than merely a second launch:

      * both iterations produced a manifest;
      * iteration 1's status is one `restore_prior_state` accepts;
      * iteration 2 reached its own tuner work, which it can only do after the
        pre-flight validated the workspace lock — `validate_stamped_invariants`
        raises on mismatch and is silent on success, so surviving it IS the
        witness.
    """
    findings: list[str] = []
    m1 = workspace / "iter_001" / "manifest.json"
    m2 = workspace / "iter_002" / "manifest.json"

    if not m1.is_file() or not m2.is_file():
        return {
            "passed": False,
            "detail": f"manifests present: iter1={m1.is_file()} iter2={m2.is_file()}",
        }

    status1 = _load(m1).get("status")
    if status1 not in CHAINABLE:
        findings.append(f"iteration 1 status {status1!r} is not chainable {sorted(CHAINABLE)}")

    # Iteration 2 must have produced its OWN artifacts — proof it ran real work
    # after the pre-flight, not that it merely started and refused.
    iter2_locks = [p for p in _per_model_locks(workspace) if "iter_002" in str(p)]
    if not iter2_locks:
        findings.append("iteration 2 produced no per-model lock — it did not reach real work")

    return {
        "passed": not findings,
        "iteration_1_status": status1,
        "iteration_2_locks": [str(p.relative_to(workspace)) for p in iter2_locks],
        "detail": "; ".join(findings) or "iteration 2 ran real work after validating the lock",
    }


def check_a2(workspace: Path) -> dict[str, Any]:
    """A2 — every per-model lock carries the fingerprint and an honest health id.

    This is F-P56-3's target. Before C1/C2 the per-model lock recorded `None`
    for the fingerprint and re-materialized the effective health config under
    `LEGACY_OMITTED`, so it disagreed with the chain-level lock it was supposed
    to mirror. Both fields are compared against the CHAIN lock, and the
    fingerprint additionally against the declared manifest value — agreeing
    with each other but on a wrong value would otherwise pass.
    """
    chain_lock = workspace / "run_invariants_lock.json"
    if not chain_lock.is_file():
        return {"passed": False, "detail": "no chain-level lock"}

    chain = _load(chain_lock)
    locks = _per_model_locks(workspace)
    if not locks:
        return {"passed": False, "detail": "no per-model lock was written"}

    rows: list[dict[str, Any]] = []
    ok = True
    if chain.get("task_composition_fingerprint") != EXPECTED_FINGERPRINT:
        ok = False
        rows.append(
            {
                "lock": "chain",
                "problem": "fingerprint is not the shipped manifest's declared value",
                "found": chain.get("task_composition_fingerprint"),
            }
        )

    for lock_path in locks:
        lock = _load(lock_path)
        row: dict[str, Any] = {"lock": str(lock_path.relative_to(workspace))}
        for key in ("task_composition_fingerprint", "health_config_sha256"):
            row[key] = lock.get(key)
            if lock.get(key) != chain.get(key):
                ok = False
                row[f"{key}_MISMATCH_vs_chain"] = chain.get(key)
            if lock.get(key) is None:
                ok = False
                row[f"{key}_IS_NONE"] = True
        rows.append(row)

    return {
        "passed": ok,
        "chain_fingerprint": chain.get("task_composition_fingerprint"),
        "chain_health_sha256": chain.get("health_config_sha256"),
        "per_model_locks": rows,
        "detail": "every per-model lock mirrors the chain lock" if ok else "see per_model_locks",
    }


def check_a3(workspace: Path) -> dict[str, Any]:
    """A3 — persisted records carry the composition stamp from ONE authority.

    Step-11's F-11-C10-a is the reason this is checked on the ARTIFACTS rather
    than trusted: there, the record stamp and the output stamp read different
    locks, one resolved to `None`, and no unit test could see it. Any record
    that carries the key at all must carry the declared value.
    """
    records = sorted(workspace.rglob("*.json"))
    stamped: list[dict[str, Any]] = []
    wrong: list[dict[str, Any]] = []

    for path in records:
        if path.name == "run_invariants_lock.json":
            continue
        try:
            payload = _load(path)
        except (ValueError, OSError):
            continue
        for holder in _iter_dicts(payload):
            if "task_composition_fingerprint" not in holder:
                continue
            value = holder["task_composition_fingerprint"]
            entry = {"file": str(path.relative_to(workspace)), "value": value}
            stamped.append(entry)
            if value != EXPECTED_FINGERPRINT:
                wrong.append(entry)
            break

    # ANTI-VACUITY: "0 artifacts, all correct" is not evidence, it is an empty
    # set. Caught by falsifying this evaluator against a known-bad run before
    # the real one finished — the Step-09b lesson, applied to my own probe.
    if not stamped:
        return {
            "passed": False,
            "stamped_artifact_count": 0,
            "detail": "NO artifact carries a composition stamp — nothing to verify, so A3 cannot pass",
        }

    return {
        "passed": not wrong,
        "stamped_artifact_count": len(stamped),
        "stamped_artifacts": stamped[:20],
        "wrong": wrong,
        "detail": (
            f"{len(stamped)} stamped artifact(s), all carrying the declared fingerprint"
            if not wrong
            else f"{len(wrong)} artifact(s) carry a fingerprint that is not the declared one"
        ),
    }


def _iter_dicts(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_dicts(item)


def observed_non_criteria(workspace: Path) -> dict[str, Any]:
    """Scientific outcomes — RECORDED so the ledger can state them, never gating.

    Written explicitly so a later reader who sees "HealthGate INVALID" in the
    log cannot mistake it for a Gate failure.
    """
    out: dict[str, Any] = {}
    for name in ("iter_001", "iter_002"):
        manifest = workspace / name / "manifest.json"
        if manifest.is_file():
            payload = _load(manifest)
            out[name] = {
                "status": payload.get("status"),
                "best_score": payload.get("best_score"),
                "model_name": payload.get("model_name"),
                "healthgate_mode": payload.get("healthgate_mode"),
            }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    workspace = Path(args.workspace)
    if not workspace.is_dir():
        print(f"no such workspace: {workspace}")
        return 2

    criteria = {
        "A1_iteration2_validated_iteration1_lock": check_a1(workspace),
        "A2_per_model_lock_identity": check_a2(workspace),
        "A3_records_stamped_from_one_authority": check_a3(workspace),
    }
    passed = all(c["passed"] for c in criteria.values())

    payload = {
        "gate": "G-12a-2",
        "workspace": str(workspace),
        "expected_fingerprint": EXPECTED_FINGERPRINT,
        "criteria": criteria,
        "observed_but_NOT_gating": observed_non_criteria(workspace),
        "not_criteria": [
            "model quality",
            "HealthGate PASS",
            "score magnitude",
            "convergence",
        ],
        "verdict": "PASS" if passed else "FAIL",
    }

    print("=" * 72)
    for name, result in criteria.items():
        print(f"  [{'PASS' if result['passed'] else 'FAIL'}] {name}")
        print(f"         {result['detail']}")
    print("-" * 72)
    print("  observed but NOT gating:")
    for name, row in payload["observed_but_NOT_gating"].items():
        print(f"    {name}: status={row['status']} best_score={row['best_score']}")
    print("=" * 72)
    print(f"  G-12a-2: {payload['verdict']}")
    print("=" * 72)

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "gate2_result.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  written: {out / 'gate2_result.json'}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
