#!/usr/bin/env python
"""Gold campaign persisted-state helper — band state and Stage-2 finalize.

Two commands, one shared winner authority, zero re-implementation of
existing verifiers:

``band-state``
    Derive a band's Stage-1 loop state ENTIRELY from persisted artifacts
    (D-ARCH-1 invariant: resume from persisted state, never shell memory):

    * next incomplete iteration + committed count via the SAME functions
      ``run_chain.sh`` auto-resume uses (``scripts/inspect_run_state.py`` —
      gap / tamper refusals included, fail closed);
    * the cumulative HealthGate-valid FORMAL incumbent per the FROZEN
      winner-field table of ``docs/campaign/stage_artifact_contract.md``
      section 1: ``status == "success"``, ``is_trial`` ABSENT or ``False``
      (the persisted record always carries the materialized default —
      see ``core.record_role.is_formal_role``, the ONE role authority this
      scanner shares with the iteration manifest; #316 B2),
      HealthGate-valid under the WORKSPACE'S OWN pinned effective config
      (``pinned_workspace_gate_ids`` + ``classify_under_pinned_policy``,
      the ONE eligibility authority,
      ``execute_tools/health_checks/candidate_eligibility.py``; the
      repo-current shipped config is never consulted and an
      unestablished roster is UNKNOWN, never a pass), maximal
      ``denoising_score`` under ``MetricOrder`` (direction from the run's
      stamped ``metric_spec`` — NEVER assumed; a score-bearing formal
      candidate without a stamped spec is a NAMED refusal, Step-09a rule);
    * the FCNet+2 band-local stop verdict — EVALUABLE only when a
      per-band reference is supplied (A2-FCNET produces it; none exists in
      the repository today), computed as
      ``is_at_least(incumbent, toward_better(reference, +margin))`` so no
      metric direction is assumed here either.

    The result is written ATOMICALLY to ``--out`` as one JSON object whose
    shell-read scalars come FIRST (the shell extracts them with the same
    head-1 grep convention as ``_chain_common.sh``'s ``_manifest_status``;
    nested objects must not re-declare those keys). Nothing is printed to
    stdout: framework imports may emit loader banners there, which is the
    exact corruption class the auto-resume capture note records.

``stage2-finalize``
    Finalize one Stage-2 retrain unit per contract section 2 (BAND-SCOPED,
    Q-S3-2 ruling A): identify the unit's own best FORMAL success record
    (validity RECORDED, not required — the marker carries
    ``healthgate_valid`` honestly and Stage-3's strict_best filters on
    it), COPY its TARGET-BAND deliverables ONLY — the band's file indices
    are derived through the SAME ``DataScope`` authority that parsed the
    unit chain's own ``--data_scope`` (a band-scoped run produces the
    scope's files ONLY, so out-of-band indices are never consulted, never
    copied, never named in refusals), each named by the
    ``DeliverableNaming`` authority and resolved uniquely (a missing or
    duplicate BAND file refuses, mirroring the compose_and_score rule) —
    into ``{unit}/deliverables/``, then write ``COMPLETE.json`` LAST via
    an atomic rename with ``deliverable_count`` = the counted band-set
    copies (4/6/5/5 under the DS8 band vocabulary). A refusal leaves NO
    marker, and a partial dir without the marker is ignored by every
    consumer.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2
from typing import Any

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.record_role import RecordRoleError, is_formal_role  # noqa: E402
from execute_tools.dataset_config import DataScope  # noqa: E402
from execute_tools.deliverable_spec import default_deliverable_naming  # noqa: E402
from execute_tools.evaluation_metric import (  # noqa: E402
    MetricSpec,
    metric_spec_from_declaration,
)
from execute_tools.health_checks.candidate_eligibility import (  # noqa: E402
    CandidateHealthValidity,
    classify_under_pinned_policy,
    pinned_workspace_gate_ids,
)
from execute_tools.metric_order import MetricOrder  # noqa: E402


def _load_inspect_run_state():
    """Import ``scripts/inspect_run_state.py`` from THIS checkout.

    ``scripts/`` is not a package, so the module is loaded by path — from
    the repository root derived from this file's own location (CLAUDE.md
    portability rule: the current checkout, never another clone).
    """
    path = REPO_ROOT / "scripts" / "inspect_run_state.py"
    spec = importlib.util.spec_from_file_location("gold_inspect_run_state", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load inspector module: {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: the inspector's @dataclass resolves its own
    # module through sys.modules at class-creation time.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StateRefusal(RuntimeError):
    """A fail-closed persisted-state refusal (gap, tamper, missing spec)."""


class BandIncumbent(BaseModel):
    """The contract section-1 winner identity (plus its locator)."""

    exp_id: str
    model_type: str
    iteration: int
    experiment_arm: str | None
    denoising_score: float
    healthgate_valid: bool
    run_output: str
    metric_id: str
    metric_direction: str


class FormalCandidate(BaseModel):
    """One eligible record, as scanned (internal carrier)."""

    exp_id: str
    model_type: str
    iteration: int
    run_name: str
    denoising_score: float
    healthgate_valid: bool
    run_output: Path
    iter_dir: Path
    spec: MetricSpec


class ScanCounts(BaseModel):
    run_outputs: int = 0
    records: int = 0
    formal_success: int = 0
    healthgate_valid: int = 0
    unreadable_run_outputs: int = 0
    nonfinite_scores: int = 0


def _iter_index_of(iter_dir: Path) -> int:
    return int(iter_dir.name.split("_")[1])


def _scan_formal_candidates(
    workspace: Path, iter_dirs: list[Path], *, require_valid: bool
) -> tuple[list[FormalCandidate], MetricSpec | None, ScanCounts]:
    """Collect eligible FORMAL candidates per the frozen winner table.

    ``require_valid=True`` (band incumbent): only HealthGate-valid records
    are candidates. ``require_valid=False`` (Stage-2 finalize): validity is
    recorded on each candidate instead, so the COMPLETE.json can carry it.

    Refuses (fail closed) when a formal success record carries a usable
    score but its run output has NO stamped ``metric_spec`` (direction
    would have to be assumed), or when two outputs disagree on the metric
    identity or direction (their scalars are not one comparison).

    **F-4 — validity is judged against THIS RUN'S pinned policy.** Eligibility
    used to be asked as ``is_valid_candidate(rec)``, whose zero-argument
    default resolves the REPO-CURRENT ``configs/health_checks.yaml`` and
    collapses UNKNOWN to the empty set on the way. A record whose own run
    declared a different roster was therefore judged against a roster it never
    ran: a record whose run-declared blocking gate FAILED came back valid,
    because the repo-current gates it happened to also carry all passed. That
    boolean is the band incumbent, the FCNet+2 stop input and
    ``healthgate_valid`` in Stage-2's ``COMPLETE.json``.
    """
    # The workspace's OWN pinned effective config, exactly as
    # `stage3_composed_best.select_band_winner` resolves it. `None` is
    # UNKNOWN — a run that materialized no effective config — and
    # `classify_under_pinned_policy` is what may never turn that into a pass.
    required_gate_ids = pinned_workspace_gate_ids(workspace)
    counts = ScanCounts()
    candidates: list[FormalCandidate] = []
    spec_seen: MetricSpec | None = None
    for iter_dir in iter_dirs:
        for ro_path in sorted(iter_dir.rglob("run_output_*.json")):
            counts.run_outputs += 1
            try:
                data = json.loads(ro_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                counts.unreadable_run_outputs += 1
                continue
            if not isinstance(data, dict):
                counts.unreadable_run_outputs += 1
                continue
            records = data.get("all_records") or []
            spec_raw = data.get("metric_spec")
            run_name = str(data.get("run_name") or "")
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                counts.records += 1
                if rec.get("status") != "success":
                    continue
                # Contract section 1: formal == `is_trial` ABSENT or False.
                # NOT "absence of the key" — the persisted record always
                # carries the materialized default. The rule lives in
                # `core.record_role` because the iteration manifest asks the
                # same question (F-SCANB-3); a second copy here is how the
                # `"is_trial" in rec` variant survived (#316 B2).
                if not is_formal_role(rec, f"{ro_path} exp_id={rec.get('exp_id')!r}"):
                    continue
                score = rec.get("denoising_score")
                if (
                    not isinstance(score, (int, float))
                    or isinstance(score, bool)
                    or not math.isfinite(float(score))
                ):
                    counts.nonfinite_scores += 1
                    continue
                counts.formal_success += 1
                valid = (
                    classify_under_pinned_policy(rec, required_gate_ids)
                    is CandidateHealthValidity.VALID
                )
                if valid:
                    counts.healthgate_valid += 1
                if require_valid and not valid:
                    continue
                if spec_raw is None:
                    raise StateRefusal(
                        f"{ro_path} carries a formal success record but NO stamped "
                        "metric_spec — the winner rule refuses to assume a metric "
                        "direction (contract section 1; Step-09a fail-closed rule)."
                    )
                try:
                    # The SAME reconstruction authority MetricSpecField uses
                    # (a plain model_validate refuses the serialized
                    # scoreability contract by design).
                    spec = metric_spec_from_declaration(dict(spec_raw))
                except Exception as exc:
                    raise StateRefusal(
                        f"{ro_path}: stamped metric_spec does not reconstruct "
                        f"({type(exc).__name__}: {exc})"
                    ) from exc
                if spec_seen is None:
                    spec_seen = spec
                elif (spec.id, spec.direction) != (spec_seen.id, spec_seen.direction):
                    raise StateRefusal(
                        f"metric identity mismatch inside {workspace}: "
                        f"({spec_seen.id}, {spec_seen.direction}) vs "
                        f"({spec.id}, {spec.direction}) at {ro_path} — scalars from "
                        "different metrics are not one comparison."
                    )
                candidates.append(
                    FormalCandidate(
                        exp_id=str(rec.get("exp_id") or ""),
                        model_type=str(rec.get("model_type") or ""),
                        iteration=_iter_index_of(iter_dir),
                        run_name=run_name,
                        denoising_score=float(score),
                        healthgate_valid=valid,
                        run_output=ro_path,
                        iter_dir=iter_dir,
                        spec=spec,
                    )
                )
    return candidates, spec_seen, counts


def _pick_winner(
    candidates: list[FormalCandidate], spec: MetricSpec | None
) -> FormalCandidate | None:
    if not candidates:
        return None
    assert spec is not None  # _scan_formal_candidates pairs them
    order = MetricOrder(spec)
    return order.best(candidates, key=lambda c: c.denoising_score)


def _experiment_arm_of(workspace: Path) -> str | None:
    lock = workspace / "run_invariants_lock.json"
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    arm = payload.get("experiment_arm")
    return arm if isinstance(arm, str) else None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# band-state
# ---------------------------------------------------------------------------


def _load_fcnet_reference(path: Path, band: str) -> float | None:
    """Read the per-band FCNet reference. Absent band key -> None.

    Accepted shapes (the A2-FCNET seam; the producer does not exist yet):
    a flat ``{"0-3": <float>, ...}`` mapping, or the same mapping nested
    under ``"per_band"``. A present-but-non-finite value refuses.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    table = data.get("per_band") if isinstance(data, dict) and "per_band" in data else data
    if not isinstance(table, dict):
        raise StateRefusal(f"{path}: FCNet reference must be a band->float mapping")
    if band not in table:
        return None
    value = table[band]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise StateRefusal(f"{path}: per-band reference for {band!r} is not a finite number")
    return float(value)


def cmd_band_state(args: argparse.Namespace) -> int:
    irs = _load_inspect_run_state()
    workspace = Path(args.workspace)
    horizon = int(args.horizon)

    if workspace.is_dir():
        iter_dirs = irs._find_chain_iter_dirs(workspace)
        reports = [irs.inspect_chain_iteration(d) for d in iter_dirs]
        gap = irs.find_iter_gap(reports)
        if gap is not None:
            print(
                f"REFUSED: non-contiguous chain at {workspace} (missing iter_{gap:03d}); "
                "operator must inspect before resuming.",
                file=sys.stderr,
            )
            return 2
        tampered = irs.find_tampered_iters(reports)
        if tampered:
            names = ", ".join(f"iter_{i:03d}" for i in tampered)
            print(f"REFUSED: tampered iteration(s) at {workspace}: {names}", file=sys.stderr)
            return 2
        next_iter = irs.compute_next_iter(reports, gap)
        committed = sorted(r.iter_idx for r in reports if r.status == "COMMITTED")
        workspace_nonempty = any(workspace.iterdir())
        iter1_report = next((r for r in reports if r.iter_idx == 1), None)
        needs_force_fresh = (
            next_iter == 1
            and workspace_nonempty
            and iter1_report is not None
            and iter1_report.status != "COMMITTED"
        )
    else:
        iter_dirs = []
        next_iter = 1
        committed = []
        needs_force_fresh = False

    try:
        candidates, spec, counts = _scan_formal_candidates(workspace, iter_dirs, require_valid=True)
        winner = _pick_winner(candidates, spec)
    # `RecordRoleError` is the shared role authority's own refusal; it is
    # caught beside this module's because an anomalous role shape is the same
    # fail-closed rc-2 outcome it always was.
    except (StateRefusal, RecordRoleError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    stop_margin = float(args.stop_margin)
    reference: float | None = None
    if args.fcnet_reference_json:
        try:
            reference = _load_fcnet_reference(Path(args.fcnet_reference_json), args.band)
        except (OSError, json.JSONDecodeError, StateRefusal) as exc:
            print(f"REFUSED: fcnet reference unusable: {exc}", file=sys.stderr)
            return 2
    evaluable = reference is not None
    satisfied = False
    stop_reason = (
        "no per-band FCNet reference supplied (A2-FCNET open) — full horizon runs"
        if not evaluable
        else "reference present; incumbent absent"
    )
    if evaluable and winner is not None:
        order = MetricOrder(winner.spec)
        target = order.toward_better(float(reference), +stop_margin)
        satisfied = order.is_at_least(winner.denoising_score, target)
        stop_reason = (
            f"incumbent {winner.denoising_score} vs target {target} "
            f"(reference {reference} moved +{stop_margin} toward better)"
        )

    horizon_exhausted = next_iter > horizon
    terminal = horizon_exhausted or satisfied
    terminal_ok = satisfied or (horizon_exhausted and len(committed) == horizon)
    terminal_reason = (
        "stop_rule_satisfied" if satisfied else ("horizon_exhausted" if horizon_exhausted else None)
    )

    incumbent_payload = None
    if winner is not None:
        incumbent_payload = BandIncumbent(
            exp_id=winner.exp_id,
            model_type=winner.model_type,
            iteration=winner.iteration,
            experiment_arm=_experiment_arm_of(workspace),
            denoising_score=winner.denoising_score,
            healthgate_valid=winner.healthgate_valid,
            run_output=str(winner.run_output),
            metric_id=winner.spec.id,
            metric_direction=str(winner.spec.direction),
        ).model_dump()

    # Shell-read scalars FIRST; nested objects must not re-declare their keys.
    payload: dict[str, Any] = {
        "schema": "gold_band_state_v1",
        "band": args.band,
        "horizon": horizon,
        "next_iter": next_iter,
        "committed_count": len(committed),
        "terminal": terminal,
        "terminal_ok": terminal_ok,
        "terminal_reason": terminal_reason,
        "stop_rule_evaluable": evaluable,
        "stop_rule_satisfied": satisfied,
        "needs_force_fresh": needs_force_fresh,
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "incumbent": incumbent_payload,
        "stop_detail": {
            "rule": "fcnet_plus_margin",
            "margin": stop_margin,
            "reference": reference,
            "reason": stop_reason,
        },
        "scan": counts.model_dump(),
        "committed_iters": committed,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(out, payload)
    return 0


# ---------------------------------------------------------------------------
# stage2-finalize
# ---------------------------------------------------------------------------


class Stage2Complete(BaseModel):
    """The FROZEN COMPLETE.json schema (contract section 2).

    ``deliverable_count`` is REQUIRED with no default (Q-S3-2 ruling A):
    the emitted value is the COUNTED target-band copies — 4/6/5/5 under
    the DS8 band vocabulary, never 20. The retired ``default=20`` was a
    hidden default that could silently reassert the superseded 20-file
    contract shape.
    """

    design: str
    target_band: str
    exp_id: str
    model_type: str
    repo_sha: str
    denoising_score: float
    healthgate_valid: bool
    deliverable_count: int
    completed_utc: str


def _repo_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return out.stdout.strip()
    except Exception as exc:  # recorded, not fatal
        print(f"WARNING: repo sha unavailable ({exc}); recording 'unknown'", file=sys.stderr)
        return "unknown"


def cmd_stage2_finalize(args: argparse.Namespace) -> int:
    irs = _load_inspect_run_state()
    unit = Path(args.unit_dir)
    # Q-S3-2 ruling A (contract section 2): a Stage-2 unit is BAND-SCOPED end
    # to end — the unit chain ran under --data_scope <target band>, so the
    # winner's iteration dir holds the TARGET band's files ONLY. The band's
    # file indices are derived through the SAME authority the chain itself
    # used to parse that scope (run_one_iteration.py --data_scope ->
    # DataScope.from_cli), so the finalize set cannot drift from the scope
    # the run enforced; out-of-band indices are never consulted. No second
    # band map is declared anywhere (one-authority rule).
    try:
        band_scope = DataScope.from_cli(args.target_band)
    except ValueError as exc:
        print(
            f"REFUSED: --target-band {args.target_band!r} is not a DataScope band spec ({exc})",
            file=sys.stderr,
        )
        return 2
    band_files = band_scope.file_indices
    assert band_files is not None  # from_cli always yields explicit indices
    workspace = unit / "workspace"
    if not workspace.is_dir():
        print(f"REFUSED: unit workspace missing: {workspace}", file=sys.stderr)
        return 2
    iter_dirs = irs._find_chain_iter_dirs(workspace)
    reports = [irs.inspect_chain_iteration(d) for d in iter_dirs]
    if not any(r.status == "COMMITTED" for r in reports):
        print(f"REFUSED: no COMMITTED iteration in {workspace}", file=sys.stderr)
        return 2

    try:
        candidates, spec, _counts = _scan_formal_candidates(
            workspace, iter_dirs, require_valid=False
        )
        winner = _pick_winner(candidates, spec)
    except (StateRefusal, RecordRoleError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if winner is None:
        print(
            f"REFUSED: no FORMAL success record with a usable score in {workspace}",
            file=sys.stderr,
        )
        return 2

    naming = default_deliverable_naming()
    deliverables = unit / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)
    copied = 0
    for idx in band_files:
        name = naming.name(
            model_type=winner.model_type,
            run_name=winner.run_name,
            exp_id=winner.exp_id,
            input_identity=idx,
        )
        hits = sorted(winner.iter_dir.rglob(name))
        if len(hits) == 0:
            print(
                f"REFUSED: deliverable missing for band {args.target_band} "
                f"file {idx}: no '{name}' under {winner.iter_dir} (was the "
                "chain launched with retention? R-RETENTION-1 forbids "
                "--cleanup_denoised for campaign chains)",
                file=sys.stderr,
            )
            return 2
        if len(hits) > 1:
            listed = ", ".join(str(h) for h in hits)
            print(
                f"REFUSED: duplicate deliverable resolution for band "
                f"{args.target_band} file {idx}: {listed}",
                file=sys.stderr,
            )
            return 2
        copy2(hits[0], deliverables / name)
        copied += 1

    marker = Stage2Complete(
        design=args.design,
        target_band=args.target_band,
        exp_id=winner.exp_id,
        model_type=winner.model_type,
        repo_sha=_repo_sha(),
        denoising_score=winner.denoising_score,
        healthgate_valid=winner.healthgate_valid,
        deliverable_count=copied,
        completed_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # The marker is written LAST, atomically: its existence IS the unit's
    # completion signal (contract section 2 — partial dirs without it are
    # ignored by Stage-3).
    _atomic_write_json(unit / "COMPLETE.json", marker.model_dump())
    print(f"finalized {unit} ({copied} deliverables)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_state = sub.add_parser("band-state", help="derive a band's Stage-1 loop state")
    p_state.add_argument("--workspace", required=True)
    p_state.add_argument("--horizon", required=True, type=int)
    p_state.add_argument("--band", required=True)
    p_state.add_argument("--out", required=True)
    p_state.add_argument("--fcnet-reference-json", default=None)
    p_state.add_argument("--stop-margin", default=2.0, type=float)
    p_state.set_defaults(func=cmd_band_state)

    p_fin = sub.add_parser("stage2-finalize", help="finalize one Stage-2 retrain unit")
    p_fin.add_argument("--unit-dir", required=True)
    p_fin.add_argument("--design", required=True)
    p_fin.add_argument(
        "--target-band",
        required=True,
        help=(
            "DS8 band spec the unit chain ran under (its --data_scope value); "
            "parsed by DataScope.from_cli to derive the band's file set "
            "(Q-S3-2 ruling A)."
        ),
    )
    p_fin.set_defaults(func=cmd_stage2_finalize)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
