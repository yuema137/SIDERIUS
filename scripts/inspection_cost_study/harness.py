"""V21 PR F — the wall-bounded measurement harness (design §0.E/§0.F/§0.G).

Every timed call is a REAL production function under its REAL enforcement
semantics (operator reconciliation 1 — per operation, never a uniform 2×):

```text
candidate_probe   probe_activation_footprint(inference) — production's
                  120 s check is POST-HOC, so the harness lets the call
                  complete and keeps the EXACT elapsed even beyond 120;
                  a 240 s SIGALRM is an EMERGENCY backstop only
full_search       the real resolve_inference_batch, native semantics
                  untouched; BatchSearchTimeout's typed ProbeTimeoutRecord
                  preserved VERBATIM; 840 s outer emergency backstop
training_probe    production's OWN seam: probe under
                  _forward_pass_timeout(single_probe_seconds=180) exactly
                  as wrapper.py:591 — a fired 180 s alarm IS the studied
                  behaviour (native_timeout, lower bound 180).
                  NO 2× relaxation exists for this operation
```

Known limitation, inherited from production and stated rather than
papered over: SIGALRM cannot interrupt a stuck native call. If that
happens the run hangs, the external backstop kills it, the
append-per-point file keeps everything measured, and the in-flight point
is identified from the file tail + manifest on restart.
"""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from scripts.inspection_cost_study.schemas import (
    Measurement,
    StudyHeader,
    SweepEntry,
    manifest_hash,
)

#: Emergency backstops (design §0.E). NOT production semantics — a fired
#: backstop is recorded as study infrastructure (`harness_backstop`).
_CANDIDATE_BACKSTOP_S = 240.0
_SEARCH_BACKSTOP_S = 840.0

#: Study constant: the training probe's batch, matching the baseline
#: train_config production default. Recorded in the header via budgets.
_TRAIN_BATCH = 1


def _alarm_in_chain(exc: BaseException) -> bool:
    """True when a SIGALRM ForwardPassTimeoutError is anywhere in the
    exception chain.

    Finding F-A3 (recorded in the design ledger, observation only):
    torchinfo catches exceptions raised inside hooked forwards and
    re-raises `RuntimeError("Failed to run torchinfo...")`, so an alarm
    that fires during the torchinfo phase arrives LAUNDERED — the
    ForwardPassTimeoutError survives only as `__cause__`/`__context__`.
    The harness walks the chain so a timeout is never misfiled as an
    ordinary failure; production's own wrapper handles the same case via
    its `"torchinfo" in str(e)` RuntimeError branch.
    """
    from agent.skills.evaluate_vram_skill.wrapper import ForwardPassTimeoutError

    seen: set[int] = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        if isinstance(e, ForwardPassTimeoutError):
            return True
        seen.add(id(e))
        e = e.__cause__ or e.__context__
    return False


def _loadavg() -> float | None:
    try:
        return os.getloadavg()[0]
    except OSError:  # pragma: no cover — non-POSIX
        return None


def _production_budgets():
    from agent.skills.evaluate_vram_skill.probe_budgets import ProbeBudgets

    return ProbeBudgets()


def _candidate_batches() -> tuple[int, ...]:
    from agent.skills.evaluate_vram_skill.batch_resolver import (
        _DEFAULT_CANDIDATE_BATCHES,
    )

    return tuple(_DEFAULT_CANDIDATE_BATCHES)


def _build(entry: SweepEntry):
    from agent.skills.evaluate_vram_skill.wrapper import _build_model

    return _build_model(entry.model_identity, entry.exact_config, entry.loss_type)


def _measure_candidate_probe(entry: SweepEntry, model, batch: int, repeat: int) -> Measurement:
    from agent.skills.evaluate_vram_skill.batch_resolver import _build_probe_input
    from agent.skills.evaluate_vram_skill.structural_probe import (
        probe_activation_footprint,
    )
    from agent.skills.evaluate_vram_skill.wrapper import (
        ForwardPassTimeoutError,
        _forward_pass_timeout,
    )

    x = _build_probe_input(batch, entry.segmentation_size)
    started = time.monotonic()
    try:
        with _forward_pass_timeout(_CANDIDATE_BACKSTOP_S, "study_candidate_backstop"):
            probe_activation_footprint(
                model=model,
                loss_module=None,
                input_sample=x,
                target_sample=None,
                mode="inference",
            )
    except ForwardPassTimeoutError:
        return Measurement(
            entry_id=entry.entry_id,
            operation="candidate_probe",
            candidate_batch=batch,
            repeat_index=repeat,
            execution_outcome="harness_backstop",
            lower_bound_seconds=_CANDIDATE_BACKSTOP_S,
            loadavg_1m=_loadavg(),
        )
    except Exception as exc:
        if _alarm_in_chain(exc):
            # The backstop fired inside torchinfo and was laundered (F-A3).
            return Measurement(
                entry_id=entry.entry_id,
                operation="candidate_probe",
                candidate_batch=batch,
                repeat_index=repeat,
                execution_outcome="harness_backstop",
                lower_bound_seconds=_CANDIDATE_BACKSTOP_S,
                loadavg_1m=_loadavg(),
            )
        return Measurement(
            entry_id=entry.entry_id,
            operation="candidate_probe",
            candidate_batch=batch,
            repeat_index=repeat,
            execution_outcome="unloadable",
            error=f"{type(exc).__name__}: {exc}"[:400],
            loadavg_1m=_loadavg(),
        )
    return Measurement(
        entry_id=entry.entry_id,
        operation="candidate_probe",
        candidate_batch=batch,
        repeat_index=repeat,
        execution_outcome="completed",
        elapsed_seconds=round(time.monotonic() - started, 4),
        loadavg_1m=_loadavg(),
    )


def _measure_full_search(entry: SweepEntry, model, cap_bytes: int, repeat: int) -> Measurement:
    from agent.skills.evaluate_vram_skill.batch_resolver import (
        BatchSearchTimeout,
        resolve_inference_batch,
    )
    from agent.skills.evaluate_vram_skill.wrapper import (
        ForwardPassTimeoutError,
        _forward_pass_timeout,
    )

    started = time.monotonic()
    try:
        with _forward_pass_timeout(_SEARCH_BACKSTOP_S, "study_search_backstop"):
            resolved = resolve_inference_batch(
                model,
                entry.segmentation_size,
                cap_bytes,
                model_identity=entry.model_identity,
            )
    except BatchSearchTimeout as exc:
        # NATIVE production semantics ended the call. The typed record is
        # the evidence, verbatim — and for these POST-HOC operations its
        # elapsed is a real measurement, kept as exact.
        return Measurement(
            entry_id=entry.entry_id,
            operation="full_search",
            repeat_index=repeat,
            execution_outcome="native_timeout",
            elapsed_seconds=float(exc.record.elapsed_seconds),
            native_record=exc.record.model_dump(mode="json"),
            native_operation=str(exc.record.operation),
            loadavg_1m=_loadavg(),
        )
    except ForwardPassTimeoutError:
        return Measurement(
            entry_id=entry.entry_id,
            operation="full_search",
            repeat_index=repeat,
            execution_outcome="harness_backstop",
            lower_bound_seconds=_SEARCH_BACKSTOP_S,
            loadavg_1m=_loadavg(),
        )
    except Exception as exc:
        if not isinstance(exc, ValueError):
            if _alarm_in_chain(exc):
                return Measurement(
                    entry_id=entry.entry_id,
                    operation="full_search",
                    repeat_index=repeat,
                    execution_outcome="harness_backstop",
                    lower_bound_seconds=_SEARCH_BACKSTOP_S,
                    loadavg_1m=_loadavg(),
                )
            return Measurement(
                entry_id=entry.entry_id,
                operation="full_search",
                repeat_index=repeat,
                execution_outcome="unloadable",
                error=f"{type(exc).__name__}: {exc}"[:400],
                loadavg_1m=_loadavg(),
            )
        # ValueError: "no candidate satisfies both caps" — a COMPLETED
        # search with a negative capacity result; its cost is still exact.
        return Measurement(
            entry_id=entry.entry_id,
            operation="full_search",
            repeat_index=repeat,
            execution_outcome="completed",
            elapsed_seconds=round(time.monotonic() - started, 4),
            error=f"no_feasible_batch: {exc}"[:400],
            loadavg_1m=_loadavg(),
        )
    return Measurement(
        entry_id=entry.entry_id,
        operation="full_search",
        repeat_index=repeat,
        execution_outcome="completed",
        elapsed_seconds=round(time.monotonic() - started, 4),
        resolved_batch=int(resolved),
        loadavg_1m=_loadavg(),
    )


def _measure_training_probe(entry: SweepEntry, model, repeat: int) -> Measurement:
    from agent.skills.evaluate_vram_skill.structural_probe import (
        probe_activation_footprint,
    )
    from agent.skills.evaluate_vram_skill.wrapper import (
        ForwardPassTimeoutError,
        _build_probe_tensors,
        _forward_pass_timeout,
    )
    from ml_models.loss_models_sandbox import get_criterion
    from ml_models.models_format_sandbox import LossConfig

    budgets = _production_budgets()
    loss_module = get_criterion(LossConfig(loss_type=entry.loss_type))
    x_train, y_train = _build_probe_tensors(
        _TRAIN_BATCH,
        entry.segmentation_size,
        entry.loss_type,
        None,
        model_type=entry.model_identity,
    )
    started = time.monotonic()
    try:
        # PRODUCTION'S OWN SEAM (wrapper.py:591): the native 180 s
        # preemptive alarm IS the behaviour under study. No relaxation.
        with _forward_pass_timeout(budgets.single_probe_seconds, "training_probe"):
            probe_activation_footprint(
                model=model,
                loss_module=loss_module,
                input_sample=x_train,
                target_sample=y_train,
                mode="training",
            )
    except ForwardPassTimeoutError:
        return Measurement(
            entry_id=entry.entry_id,
            operation="training_probe",
            repeat_index=repeat,
            execution_outcome="native_timeout",
            lower_bound_seconds=float(budgets.single_probe_seconds),
            native_operation="training_probe",
            loadavg_1m=_loadavg(),
        )
    except Exception as exc:
        if _alarm_in_chain(exc):
            # The NATIVE alarm fired inside torchinfo and was laundered
            # (F-A3) — still the native production timeout.
            return Measurement(
                entry_id=entry.entry_id,
                operation="training_probe",
                repeat_index=repeat,
                execution_outcome="native_timeout",
                lower_bound_seconds=float(budgets.single_probe_seconds),
                native_operation="training_probe",
                loadavg_1m=_loadavg(),
            )
        return Measurement(
            entry_id=entry.entry_id,
            operation="training_probe",
            repeat_index=repeat,
            execution_outcome="unloadable",
            error=f"{type(exc).__name__}: {exc}"[:400],
            loadavg_1m=_loadavg(),
        )
    return Measurement(
        entry_id=entry.entry_id,
        operation="training_probe",
        repeat_index=repeat,
        execution_outcome="completed",
        elapsed_seconds=round(time.monotonic() - started, 4),
        loadavg_1m=_loadavg(),
    )


def run_study(
    entries: list[SweepEntry],
    out_path: str | Path,
    *,
    wall_seconds: float,
    repeats: int = 3,
    cap_bytes: int = 12 * 1024**3,
) -> dict[str, int]:
    """Measure every entry, append-per-point, stop cleanly at the wall.

    Returns disposition counts. Raises nothing on wall expiry — the file
    carries a wall marker and the return notes coverage; per the frozen
    operator rule the CALLER decides that the study is thereby NOT
    complete.
    """
    out_path = Path(out_path)
    if out_path.exists():
        raise FileExistsError(
            f"{out_path} already exists — study evidence is append-only; "
            f"choose a new path (operator rule: never overwrite evidence)"
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    budgets = _production_budgets()
    header = StudyHeader(
        manifest_hash=manifest_hash(entries),
        seed=0,
        repeats=repeats,
        wall_seconds=wall_seconds,
        production_budgets={
            "single_candidate_seconds": budgets.single_candidate_seconds,
            "batch_search_seconds": budgets.batch_search_seconds,
            "single_probe_seconds": budgets.single_probe_seconds,
        },
        host=socket.gethostname(),
        cap_bytes_for_full_search=cap_bytes,
    )
    counts: dict[str, int] = {}
    wall_started = time.monotonic()

    with open(out_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"header": header.model_dump(mode="json")}) + "\n")
        fh.flush()

        def _emit(m: Measurement) -> None:
            counts[m.execution_outcome] = counts.get(m.execution_outcome, 0) + 1
            fh.write(json.dumps({"measurement": m.model_dump(mode="json")}) + "\n")
            fh.flush()

        def _wall_ok() -> bool:
            return (time.monotonic() - wall_started) < wall_seconds

        expired = False
        for entry in entries:
            if not _wall_ok():
                expired = True
                break
            if entry.load_error is not None:
                _emit(
                    Measurement(
                        entry_id=entry.entry_id,
                        operation="candidate_probe",
                        repeat_index=0,
                        execution_outcome=(
                            "invalid_config"
                            if entry.population == "builtin_reference"
                            else "unloadable"
                        ),
                        error=entry.load_error,
                    )
                )
                continue
            try:
                model = _build(entry)
            except Exception as exc:
                _emit(
                    Measurement(
                        entry_id=entry.entry_id,
                        operation="candidate_probe",
                        repeat_index=0,
                        execution_outcome="unloadable",
                        error=f"{type(exc).__name__}: {exc}"[:400],
                    )
                )
                continue
            for repeat in range(repeats):
                for batch in _candidate_batches():
                    if not _wall_ok():
                        expired = True
                        break
                    _emit(_measure_candidate_probe(entry, model, batch, repeat))
                if expired or not _wall_ok():
                    expired = True
                    break
                _emit(_measure_full_search(entry, model, cap_bytes, repeat))
                if not _wall_ok():
                    expired = True
                    break
                _emit(_measure_training_probe(entry, model, repeat))
            del model
            if expired:
                break

        if expired:
            fh.write(
                json.dumps(
                    {
                        "wall_expired": {
                            "elapsed_seconds": round(time.monotonic() - wall_started, 2),
                            "wall_seconds": wall_seconds,
                        }
                    }
                )
                + "\n"
            )
    return counts


def read_measurements(path: str | Path) -> tuple[StudyHeader, list[Measurement], bool]:
    """Schema-validated read-back. Returns (header, measurements,
    wall_expired). Malformed lines raise — conclusions are never drawn
    from an unvalidated file."""
    header: StudyHeader | None = None
    out: list[Measurement] = []
    wall_expired = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            payload = json.loads(line)
            if "header" in payload:
                header = StudyHeader.model_validate(payload["header"])
            elif "measurement" in payload:
                out.append(Measurement.model_validate(payload["measurement"]))
            elif "wall_expired" in payload:
                wall_expired = True
            else:
                raise ValueError(f"unrecognised evidence line: {line[:120]}")
    if header is None:
        raise ValueError(f"{path}: no header line")
    return header, out, wall_expired
