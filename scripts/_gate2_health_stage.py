# scripts/_gate2_health_stage.py
"""The ONE shared Health evidence stage for the D14 Gate-2 runners (Step 08c C5).

Both bounded runners (``run_pets_gate2.py``, ``run_davis_gate2.py``) call
:func:`run_health_stage` after their metric stage, so the Gate-2 artifact
each run's Health family judges is the FRESH deliverable this run's
training and inference just produced.

Frozen semantics (child design §3.5):

* **The binding is ALWAYS explicit** (state C — the pack's own
  ``task_health.yaml``). An omitted binding would compose the legacy
  TIDMAD default — the exact cross-task hazard the 08b audit pinned — so
  the stage takes the path as a REQUIRED argument and refuses a missing
  file loudly, before any evaluation.
* **Every selected gate is evaluated and persisted.** This stage collects
  EVIDENCE; it is not the tuner's round-control state machine. On a
  collapsed deliverable, every gate's verdict must be present — an
  earlier blocking gate's ``invalidate_round`` never suppresses a later
  gate's evidence.
* **The returned block is ADDITIVE.** The runner assigns it to ONE new
  key (``health``) in its existing evidence dict; no existing D14
  evidence field is renamed, removed or reinterpreted.
* **A FAILED verdict can be a Gate-2 PASS**: the Gate asks whether Health
  classified the real artifact CORRECTLY, not whether the artifact was
  healthy. The runner prints exactly that framing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from execute_tools.health_checks import loaded_plugin_set
from execute_tools.health_checks.config import (
    load_health_gates_config,
    materialize_effective_config,
)
from execute_tools.health_checks.runner import evaluate_gate, get_gates_for_position
from execute_tools.health_checks.schemas import HealthCheckContext


def run_health_stage(
    *,
    workspace: str | Path,
    task_health_binding: str | Path,
    deliverable_path: str | Path,
    evaluation_payload: object,
    model_name: str,
    run_name: str,
) -> dict[str, Any]:
    """Evaluate the pack's Health family on the fresh deliverable.

    Args:
        workspace: the run's evidence/output directory; the pinned
            ``health_checks_effective.yaml`` is materialized here.
        task_health_binding: the pack's ``task_health.yaml`` path — the
            EXPLICIT state-C binding. Never optional.
        deliverable_path: the fresh deliverable this run just wrote; the
            pack's provider reads it through the context's
            produced-artifact slot.
        evaluation_payload: the same deliverable decoded by the task-owned
            evaluation codec.
        model_name: the run's model identity (context metadata).
        run_name: the run's name (context metadata).

    Returns:
        The additive ``health`` evidence block: binding path, pinned
        effective-config sha, resolved plugin identities, and one ordered
        entry per selected gate (check ids, composed check configs — the
        thresholds needed to interpret the result — verdicts, resolved
        action, decisive metrics).

    Raises:
        FileNotFoundError: the binding path does not exist. Loud and
            BEFORE evaluation — a runner that silently dropped its health
            stage would pass off D14-era evidence as 08c evidence.
    """
    binding = Path(task_health_binding)
    if not binding.is_file():
        raise FileNotFoundError(
            f"task health binding not found: {binding} — the health stage "
            f"refuses to run without its EXPLICIT state-C binding"
        )

    effective_path, effective_sha = materialize_effective_config(
        None,  # the shipped framework config: POLICY ONLY since 08b
        None,
        str(workspace),
        task_health_binding=str(binding),
    )
    effective = load_health_gates_config(effective_path)
    by_id = {gate.id: gate for gate in effective.health_gates}

    ctx = HealthCheckContext(
        model_name=model_name,
        run_name=run_name,
        round_index=1,
        denoised_paths={0: str(deliverable_path)},
        evaluation_payload_fn=lambda: evaluation_payload,
    )

    gates_evidence: list[dict[str, Any]] = []
    for gate_id in get_gates_for_position(1, config_path=effective_path):
        # Evidence collection: EVERY selected gate, regardless of what an
        # earlier one resolved to.
        result = evaluate_gate(gate_id, ctx, config_path=effective_path)
        gate_cfg = by_id[gate_id]
        gates_evidence.append(
            {
                "gate_id": gate_id,
                "gate_role": gate_cfg.gate_role,
                "check_ids": [ref.name for ref in gate_cfg.checks],
                "check_configs": {ref.name: ref.config for ref in gate_cfg.checks},
                "check_verdicts": {r.check_name: r.verdict.value for r in result.check_results},
                "passed": result.passed,
                "resolved_action": result.action.value,
                "failure_reason": result.failure_reason,
                "metrics": {r.check_name: r.metrics for r in result.check_results},
            }
        )

    return {
        "task_health_binding": str(binding),
        "effective_config_sha256": effective_sha,
        "resolved_plugins": [p.canonical_identity() for p in loaded_plugin_set()],
        "gates": gates_evidence,
    }
