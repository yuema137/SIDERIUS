# dashboard/api/router.py
"""
All REST API routes for the SIDERIUS dashboard.

Mounted at /api by main.py. The router depends only on the DataSource ABC
and Pydantic response models — no storage-specific code lives here.
"""

import glob
import json
import os

from fastapi import APIRouter, HTTPException, Query

from dashboard.api.models import (
    ExperimentRecord,
    FrontendConfig,
    HealthResponse,
    IterationRound,
    IterationTableResponse,
    IterationTableRow,
    LeaderboardResponse,
    ModelListResponse,
    ModelOverview,
    RunListResponse,
    RunSummary,
    SeriesMetricIdentity,
    StatusCounts,
)
from dashboard.data_sources.base import DataSource
from execute_tools.evaluation_metric import metric_identity_unavailable_notice
from execute_tools.persisted_ranking import corpus_order, partition_by_metric_identity

router = APIRouter()


def _series_metric_identity(records: list[dict]) -> SeriesMetricIdentity:
    """The ONE order a series of persisted records may be ranked in.

    Step 12 / PR-12e (F-12e-UX-9). Reconciled HERE, server-side, by the
    authority that owns it — the browser is TOLD the direction and never
    infers it (§V.13e: the view must not own metric direction).

    Both routes that return a :class:`RunSummary` feed the same two charts,
    and before this the direction never crossed the wire at all: the mirror
    dropped ``metric_result``, so ``app.js`` hardcoded higher-is-better at
    three comparison sites and asserted it in two axis labels. A
    lower-is-better run — DAVIS's ``mse``, Pets' declared ``log_loss`` —
    rendered an inverted best-curve under a contradicting label.

    Returns a value with ``direction`` set when one order covers the series,
    and ``direction=None`` plus a NAMED ``note`` otherwise. Never a guess:
    ``partition_by_metric_identity`` excludes identity-less records
    individually (they stay fully readable, they simply never receive a rank),
    and ``corpus_order`` refuses a corpus that mixes two known metrics.
    """
    rankable, unranked = partition_by_metric_identity(records)
    order, conflict = corpus_order(rankable)
    if order is None:
        return SeriesMetricIdentity(
            note=conflict
            or metric_identity_unavailable_notice(
                "this series",
                detail="no record declares a metric identity, so it is not ranked",
            )
        )
    identity = next(
        (r["metric_result"] for r in rankable if isinstance(r.get("metric_result"), dict)),
        {},
    )
    note = None
    if unranked:
        note = metric_identity_unavailable_notice(
            f"{len(unranked)} of {len(records)} records in this series",
            detail="excluded from ranking individually",
        )
    return SeriesMetricIdentity(
        metric_id=identity.get("metric_id"), direction=order.direction, note=note
    )


# ---------------------------------------------------------------------------
# Dependency injection — DataSource and Settings are injected by main.py
# ---------------------------------------------------------------------------

# These are set once at startup by main.py via router.dependency_overrides
# or by passing them through a shared app state. We use a module-level
# holder pattern so tests can swap implementations without a running server.

_data_source: DataSource | None = None
_frontend_config: FrontendConfig | None = None


def set_data_source(ds: DataSource) -> None:
    global _data_source
    _data_source = ds


def set_frontend_config(cfg: FrontendConfig) -> None:
    global _frontend_config
    _frontend_config = cfg


def get_data_source() -> DataSource:
    if _data_source is None:
        raise RuntimeError(
            "DataSource has not been initialised. Call set_data_source() at startup."
        )
    return _data_source


def get_frontend_cfg() -> FrontendConfig:
    if _frontend_config is None:
        raise RuntimeError(
            "FrontendConfig has not been initialised. Call set_frontend_config() at startup."
        )
    return _frontend_config


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health():
    """Liveness check + data source connectivity."""
    ds = get_data_source()
    cfg = get_frontend_cfg()
    readable = ds.health_check()
    return HealthResponse(
        status="ok" if readable else "degraded",
        data_source_type=cfg.data_source_type,
        readable=readable,
    )


# ---------------------------------------------------------------------------
# Config (frontend bootstrap)
# ---------------------------------------------------------------------------


@router.get("/config", response_model=FrontendConfig, tags=["meta"])
def config():
    """
    Return dashboard settings the frontend needs on first load:
    refresh interval, model list, default run name.
    """
    return get_frontend_cfg()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@router.get("/models", response_model=ModelListResponse, tags=["models"])
def list_models():
    """List all model names available in the data source."""
    ds = get_data_source()
    return ModelListResponse(models=ds.list_models())


@router.get("/models/{model}", response_model=ModelOverview, tags=["models"])
def model_overview(model: str):
    """
    Aggregated stats for one model: baseline score, best agent score,
    total experiments, status breakdown, and available run names.
    """
    ds = get_data_source()
    try:
        raw = ds.get_model_overview(model)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.") from e

    return ModelOverview(
        model=raw["model"],
        baseline_score=raw.get("baseline_score"),
        best_agent_score=raw.get("best_agent_score"),
        best_run_name=raw.get("best_run_name"),
        total_experiments=raw.get("total_experiments", 0),
        status_counts=StatusCounts(**raw.get("status_counts", {})),
        runs=raw.get("runs", []),
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.get("/models/{model}/runs", response_model=RunListResponse, tags=["runs"])
def list_runs(model: str):
    """List all run names for a model, including 'baseline'."""
    ds = get_data_source()
    try:
        runs = ds.list_runs(model)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.") from e
    return RunListResponse(model=model, runs=runs)


@router.get("/models/{model}/runs/{run_name}", response_model=RunSummary, tags=["runs"])
def get_run(
    model: str,
    run_name: str,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(
        default=None, description="Filter by status: success | skipped_oom_risk"
    ),
):
    """
    Paginated experiment records for a model/run combination.

    Query params:
      - limit:   max records to return (1-1000, default 200)
      - offset:  records to skip (default 0)
      - status:  filter by status string
    """
    ds = get_data_source()
    try:
        records, total = ds.get_run_records(
            model,
            run_name,
            limit=limit,
            offset=offset,
            status_filter=status,
        )
    except KeyError as e:
        raise HTTPException(
            status_code=404, detail=f"Run '{run_name}' not found for model '{model}'."
        ) from e

    parsed = [ExperimentRecord.model_validate(r) for r in records]
    return RunSummary(
        model=model,
        run_name=run_name,
        total_count=total,
        offset=offset,
        limit=limit,
        records=parsed,
        metric=_series_metric_identity(records),
    )


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


@router.get(
    "/models/{model}/runs/{run_name}/experiments/{exp_id}",
    response_model=ExperimentRecord,
    tags=["experiments"],
)
def get_experiment(model: str, run_name: str, exp_id: str):
    """Full record for a single experiment."""
    ds = get_data_source()
    try:
        raw = ds.get_experiment(model, run_name, exp_id)
    except KeyError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Experiment '{exp_id}' not found in {model}/{run_name}.",
        ) from e
    return ExperimentRecord.model_validate(raw)


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


@router.get("/models/{model}/leaderboard", response_model=LeaderboardResponse, tags=["leaderboard"])
def leaderboard(
    model: str,
    top_n: int = Query(default=10, ge=1, le=100),
    status: str = Query(default="success", description="Filter by status"),
):
    """
    Top N experiments for a model across all runs, ranked best-first on the
    metric the records declare they were scored under.

    Step 10 P2a C3: the ordering direction comes from each record's persisted
    metric identity rather than being assumed. Rows with no declared identity
    are returned unranked (``rank: null``) with a ``metric_ranking`` note,
    and keep their raw scores.
    """
    ds = get_data_source()
    try:
        entries = ds.get_leaderboard(model, top_n=top_n, status_filter=status)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.") from e

    from dashboard.api.models import LeaderboardEntry

    return LeaderboardResponse(
        model=model,
        top_n=top_n,
        status_filter=status,
        entries=[LeaderboardEntry(**e) for e in entries],
    )


# ---------------------------------------------------------------------------
# Exploration (agent-generated models)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Exploration run discovery — supports three on-disk layouts:
#
# 1. **Legacy** (single workflow, multiple iterations under one run dir):
#       {root}/exploration/{run_name}/iteration_NNN/{model}/summary_{run_name}.json
#
# 2. **Chain** (per-iteration slurm jobs, one chain workspace per submission):
#       {root}/{chain_dir}/iter_NNN/iteration_001/{model}/summary_iter_NNN.json
#       {root}/{chain_dir}/iter_NNN/manifest.json
#
# 3. **Wrapper** (per-run wrapper dir at the data root, structurally identical
#    to legacy once you descend one level):
#       {root}/exploration_{run_name}/{run_name}/iteration_NNN/{model}/run_output_{run_name}.json
#
# A directory is recognized as a chain workspace iff it contains at least
# one `iter_*/manifest.json`. The chain layout's per-iteration `run_name`
# is `iter_NNN`, but the dashboard's "run name" identity is the chain
# workspace dir itself — that's the unit a user wants to browse.
#
# The wrapper layout is treated as "legacy" once resolved, because below the
# wrapper dir the on-disk shape (iteration_NNN/{model}/run_output_*.json) is
# identical. Only the discovery step differs.
# ---------------------------------------------------------------------------


def _is_chain_workspace(d: str) -> bool:
    """A dir is a chain workspace if it has at least one iter_NNN/ subdir.

    Earlier versions required iter_*/manifest.json — but the manifest is
    only written at iter completion, so an in-flight chain (iter_001 still
    training) was invisible to the dashboard. Now any iter_NNN/ subdirectory
    matching the 3-digit chain naming convention counts, so live chains
    surface immediately. Iter rows whose run_output isn't ready yet fall
    through to the partial-row path in iteration_table().
    """
    return bool(glob.glob(os.path.join(d, "iter_[0-9][0-9][0-9]")))


def _resolve_run_dir(root: str, run_name: str) -> tuple[str, str] | None:
    """Resolve a run_name to (run_dir, layout) where layout is 'legacy' or 'chain'.

    Returns None if the run does not exist.
    """
    legacy_dir = os.path.join(root, "exploration", run_name)
    if os.path.isdir(legacy_dir):
        return legacy_dir, "legacy"
    wrapper_dir = os.path.join(root, f"exploration_{run_name}", run_name)
    if os.path.isdir(wrapper_dir):
        return wrapper_dir, "legacy"
    chain_dir = os.path.join(root, run_name)
    if os.path.isdir(chain_dir) and _is_chain_workspace(chain_dir):
        return chain_dir, "chain"
    return None


@router.get("/exploration/runs", tags=["exploration"])
def list_exploration_runs():
    """List all exploration run names (both legacy and chain layouts)."""
    ds = get_data_source()
    runs: list[str] = []

    # Legacy: {root}/exploration/{run_name}/
    legacy_root = os.path.join(ds.root, "exploration")
    if os.path.isdir(legacy_root):
        runs.extend(
            d for d in os.listdir(legacy_root) if os.path.isdir(os.path.join(legacy_root, d))
        )

    # Chain: any top-level dir under root that contains iter_*/manifest.json
    # Wrapper: any top-level "exploration_<run_name>" dir whose inner <run_name> exists
    if os.path.isdir(ds.root):
        for d in os.listdir(ds.root):
            full = os.path.join(ds.root, d)
            if not os.path.isdir(full):
                continue
            if _is_chain_workspace(full):
                runs.append(d)
                continue
            if d.startswith("exploration_"):
                candidate = d[len("exploration_") :]
                if candidate and os.path.isdir(os.path.join(full, candidate)):
                    runs.append(candidate)

    return {"runs": sorted(set(runs))}


@router.get("/exploration/runs/{run_name}/models", tags=["exploration"])
def list_exploration_models(run_name: str):
    """List all agent-generated models in an exploration run."""
    ds = get_data_source()
    resolved = _resolve_run_dir(ds.root, run_name)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Exploration run '{run_name}' not found.")
    run_dir, layout = resolved

    models: list[str] = []
    if layout == "legacy":
        for iter_dir in sorted(glob.glob(os.path.join(run_dir, "iteration_*"))):
            for entry in os.listdir(iter_dir):
                full = os.path.join(iter_dir, entry)
                if (
                    os.path.isdir(full)
                    and not entry.startswith("attempt_")
                    and entry != "__pycache__"
                ):
                    summary = os.path.join(full, f"summary_{run_name}.json")
                    if os.path.isfile(summary):
                        models.append(entry)
    else:  # chain
        for chain_iter_dir in sorted(glob.glob(os.path.join(run_dir, "iter_*"))):
            iter_name = os.path.basename(chain_iter_dir)  # e.g. "iter_001"
            for inner in glob.glob(os.path.join(chain_iter_dir, "iteration_*")):
                for entry in os.listdir(inner):
                    full = os.path.join(inner, entry)
                    if (
                        os.path.isdir(full)
                        and not entry.startswith("attempt_")
                        and entry != "__pycache__"
                    ):
                        summary = os.path.join(full, f"summary_{iter_name}.json")
                        if os.path.isfile(summary):
                            models.append(entry)

    # Dedup while preserving sorted order
    return {"run_name": run_name, "models": sorted(set(models))}


@router.get("/exploration/runs/{run_name}/models/{model_name}", tags=["exploration"])
def get_exploration_records(
    run_name: str,
    model_name: str,
    limit: int = Query(default=200, ge=1, le=1000),
    status: str | None = Query(default=None),
):
    """Get experiment records for an agent-generated model in an exploration run."""
    ds = get_data_source()
    resolved = _resolve_run_dir(ds.root, run_name)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Exploration run '{run_name}' not found.")
    run_dir, layout = resolved

    records: list[dict] = []
    if layout == "legacy":
        for iter_dir in sorted(glob.glob(os.path.join(run_dir, "iteration_*"))):
            summary_path = os.path.join(iter_dir, model_name, f"summary_{run_name}.json")
            if os.path.isfile(summary_path):
                with open(summary_path) as f:
                    records = json.load(f)
                break
    else:  # chain — concatenate records from every chain iteration that ran this model
        for chain_iter_dir in sorted(glob.glob(os.path.join(run_dir, "iter_*"))):
            iter_name = os.path.basename(chain_iter_dir)
            for inner in sorted(glob.glob(os.path.join(chain_iter_dir, "iteration_*"))):
                summary_path = os.path.join(inner, model_name, f"summary_{iter_name}.json")
                if os.path.isfile(summary_path):
                    with open(summary_path) as f:
                        records.extend(json.load(f))

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{model_name}' not found in exploration run '{run_name}'.",
        )

    if status:
        records = [r for r in records if r.get("status") == status]

    total = len(records)
    records = records[:limit]

    parsed = [ExperimentRecord.model_validate(r) for r in records]
    return RunSummary(
        model=model_name,
        run_name=run_name,
        total_count=total,
        offset=0,
        limit=limit,
        records=parsed,
        metric=_series_metric_identity(records),
    )


# ---------------------------------------------------------------------------
# Exploration iteration-summary table
# ---------------------------------------------------------------------------


def _model_dir_in_iteration(iter_dir: str) -> str | None:
    """Find the successful (non-attempt) model dir inside an iteration dir.

    Returns the dir name or None. If only `attempt_*` dirs exist, returns
    None — the caller can fall back to the attempt name for display.
    """
    for entry in os.listdir(iter_dir):
        full = os.path.join(iter_dir, entry)
        if not os.path.isdir(full):
            continue
        if entry.startswith("attempt_") or entry == "__pycache__":
            continue
        return entry
    return None


def _attempt_model_name(iter_dir: str) -> str | None:
    """Recover model name from `attempt_NNN_<modelname>` dirs as a fallback.

    Used when an iteration produced no successful run_output_*.json — the
    attempt dir name is the only signal of which model was tried.
    """
    for entry in sorted(os.listdir(iter_dir)):
        full = os.path.join(iter_dir, entry)
        if not os.path.isdir(full) or not entry.startswith("attempt_"):
            continue
        # Strip `attempt_NNN_` prefix
        parts = entry.split("_", 2)
        if len(parts) == 3:
            return parts[2]
    return None


def _row_from_run_output(
    iter_label: str,
    model_name: str | None,
    run_output: dict,
) -> IterationTableRow:
    """Pivot one run_output_*.json into an iteration table row.

    Each ``status == "success"`` record in ``all_records`` becomes one
    round-block in chronological order (sorted by the numeric suffix of
    ``exp_id``). Skipped/error attempts are dropped — they carry no signal
    worth a column.
    """

    def _exp_index(exp_id: str) -> int:
        try:
            return int(exp_id.rsplit("_", 1)[-1])
        except (ValueError, AttributeError):
            return 0

    successful = [r for r in run_output.get("all_records", []) if r.get("status") == "success"]
    successful.sort(key=lambda r: _exp_index(r.get("exp_id", "")))

    rounds = [
        IterationRound(
            exp_id=r.get("exp_id", ""),
            is_trial=r.get("is_trial"),
            trial_portion=r.get("trial_portion"),
            train_portion=r.get("train_portion"),
            final_loss=r.get("final_loss"),
            denoising_score=r.get("denoising_score"),
        )
        for r in successful
    ]

    return IterationTableRow(
        iteration=iter_label,
        model_name=model_name,
        status=run_output.get("status"),
        termination_reason=run_output.get("termination_reason"),
        completed_rounds=run_output.get("completed_rounds"),
        total_attempts=run_output.get("total_attempts"),
        rounds=rounds,
    )


@router.get(
    "/exploration/runs/{run_name}/iteration_table",
    response_model=IterationTableResponse,
    tags=["exploration"],
)
def iteration_table(run_name: str):
    """One row per explore-loop iteration, summarising the best record.

    Layout-aware:
      - legacy/wrapper: each `iteration_NNN/` dir produces one row.
      - chain: each `iter_NNN/` dir produces one row, drawing from its
        single inner `iteration_*/<model>/run_output_iter_NNN.json`.
    """
    ds = get_data_source()
    resolved = _resolve_run_dir(ds.root, run_name)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Exploration run '{run_name}' not found.")
    run_dir, layout = resolved

    rows: list[IterationTableRow] = []

    if layout == "legacy":
        for iter_dir in sorted(glob.glob(os.path.join(run_dir, "iteration_*"))):
            iter_label = os.path.basename(iter_dir)
            model_name = _model_dir_in_iteration(iter_dir)
            ro_path: str | None = None
            if model_name:
                candidate = os.path.join(iter_dir, model_name, f"run_output_{run_name}.json")
                if os.path.isfile(candidate):
                    ro_path = candidate
            if ro_path is None:
                # No successful run_output. Surface the iteration with attempt-derived model name.
                rows.append(
                    IterationTableRow(
                        iteration=iter_label,
                        model_name=model_name or _attempt_model_name(iter_dir),
                    )
                )
                continue
            try:
                with open(ro_path) as f:
                    run_output = json.load(f)
            except (json.JSONDecodeError, OSError):
                # Partial / corrupt run_output (common after disk-full or
                # mid-write crash). Don't let one bad file 500 the table —
                # surface the row with a placeholder so the rest still loads.
                rows.append(
                    IterationTableRow(
                        iteration=iter_label,
                        model_name=model_name or _attempt_model_name(iter_dir),
                    )
                )
                continue
            rows.append(_row_from_run_output(iter_label, model_name, run_output))

    else:  # chain — each chain-iter dir is one logical iteration
        # Match exactly the 3-digit chain naming (iter_NNN) so we skip
        # sibling files like iter_NNN_hardware.json that share the prefix.
        for chain_iter_dir in sorted(glob.glob(os.path.join(run_dir, "iter_[0-9][0-9][0-9]"))):
            iter_label = os.path.basename(chain_iter_dir)  # "iter_001"
            ro_path: str | None = None
            model_name: str | None = None
            for inner in sorted(glob.glob(os.path.join(chain_iter_dir, "iteration_*"))):
                model_name = _model_dir_in_iteration(inner)
                if model_name:
                    candidate = os.path.join(inner, model_name, f"run_output_{iter_label}.json")
                    if os.path.isfile(candidate):
                        ro_path = candidate
                        break
                if model_name is None:
                    model_name = _attempt_model_name(inner)
            if ro_path is None:
                rows.append(IterationTableRow(iteration=iter_label, model_name=model_name))
                continue
            try:
                with open(ro_path) as f:
                    run_output = json.load(f)
            except (json.JSONDecodeError, OSError):
                # Partial / corrupt run_output (common after disk-full or
                # mid-write crash). Don't let one bad file 500 the table —
                # surface the row with a placeholder so the rest still loads.
                rows.append(IterationTableRow(iteration=iter_label, model_name=model_name))
                continue
            rows.append(_row_from_run_output(iter_label, model_name, run_output))

    max_rounds = max((len(r.rounds) for r in rows), default=0)
    return IterationTableResponse(run_name=run_name, max_rounds=max_rounds, rows=rows)
