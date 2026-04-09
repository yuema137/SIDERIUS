# dashboard/api/router.py
"""
All REST API routes for the SIDERIUS dashboard.

Mounted at /api by main.py. The router depends only on the DataSource ABC
and Pydantic response models — no storage-specific code lives here.
"""

import os
import glob
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from dashboard.data_sources.base import DataSource
from dashboard.api.models import (
    ExperimentRecord,
    FrontendConfig,
    HealthResponse,
    LeaderboardResponse,
    ModelListResponse,
    ModelOverview,
    RunListResponse,
    RunSummary,
    StatusCounts,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency injection — DataSource and Settings are injected by main.py
# ---------------------------------------------------------------------------

# These are set once at startup by main.py via router.dependency_overrides
# or by passing them through a shared app state. We use a module-level
# holder pattern so tests can swap implementations without a running server.

_data_source: Optional[DataSource] = None
_frontend_config: Optional[FrontendConfig] = None


def set_data_source(ds: DataSource) -> None:
    global _data_source
    _data_source = ds


def set_frontend_config(cfg: FrontendConfig) -> None:
    global _frontend_config
    _frontend_config = cfg


def get_data_source() -> DataSource:
    if _data_source is None:
        raise RuntimeError("DataSource has not been initialised. Call set_data_source() at startup.")
    return _data_source


def get_frontend_cfg() -> FrontendConfig:
    if _frontend_config is None:
        raise RuntimeError("FrontendConfig has not been initialised. Call set_frontend_config() at startup.")
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
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.")

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
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.")
    return RunListResponse(model=model, runs=runs)


@router.get("/models/{model}/runs/{run_name}", response_model=RunSummary, tags=["runs"])
def get_run(
    model: str,
    run_name: str,
    limit: int  = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None, description="Filter by status: success | skipped_oom_risk"),
):
    """
    Paginated experiment records for a model/run combination.

    Query params:
      - limit:   max records to return (1–1000, default 200)
      - offset:  records to skip (default 0)
      - status:  filter by status string
    """
    ds = get_data_source()
    try:
        records, total = ds.get_run_records(
            model, run_name,
            limit=limit, offset=offset, status_filter=status,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run '{run_name}' not found for model '{model}'.")

    parsed = [ExperimentRecord.model_validate(r) for r in records]
    return RunSummary(
        model=model,
        run_name=run_name,
        total_count=total,
        offset=offset,
        limit=limit,
        records=parsed,
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
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Experiment '{exp_id}' not found in {model}/{run_name}.",
        )
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
    Top N experiments for a model across all runs, ranked by denoising_score
    descending (higher is better).
    """
    ds = get_data_source()
    try:
        entries = ds.get_leaderboard(model, top_n=top_n, status_filter=status)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Model '{model}' not found.")

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
# Exploration run discovery — supports two on-disk layouts:
#
# 1. **Legacy** (single workflow, multiple iterations under one run dir):
#       {root}/exploration/{run_name}/iteration_NNN/{model}/summary_{run_name}.json
#
# 2. **Chain** (per-iteration slurm jobs, one chain workspace per submission):
#       {root}/{chain_dir}/iter_NNN/iteration_001/{model}/summary_iter_NNN.json
#       {root}/{chain_dir}/iter_NNN/manifest.json
#
# A directory is recognized as a chain workspace iff it contains at least
# one `iter_*/manifest.json`. The chain layout's per-iteration `run_name`
# is `iter_NNN`, but the dashboard's "run name" identity is the chain
# workspace dir itself — that's the unit a user wants to browse.
# ---------------------------------------------------------------------------

def _is_chain_workspace(d: str) -> bool:
    """A dir is a chain workspace if it has at least one iter_*/manifest.json."""
    return bool(glob.glob(os.path.join(d, "iter_*", "manifest.json")))


def _resolve_run_dir(root: str, run_name: str) -> Optional[tuple[str, str]]:
    """Resolve a run_name to (run_dir, layout) where layout is 'legacy' or 'chain'.

    Returns None if the run does not exist.
    """
    legacy_dir = os.path.join(root, "exploration", run_name)
    if os.path.isdir(legacy_dir):
        return legacy_dir, "legacy"
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
            d for d in os.listdir(legacy_root)
            if os.path.isdir(os.path.join(legacy_root, d))
        )

    # Chain: any top-level dir under root that contains iter_*/manifest.json
    if os.path.isdir(ds.root):
        for d in os.listdir(ds.root):
            full = os.path.join(ds.root, d)
            if os.path.isdir(full) and _is_chain_workspace(full):
                runs.append(d)

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
                if os.path.isdir(full) and not entry.startswith("attempt_") and entry != "__pycache__":
                    summary = os.path.join(full, f"summary_{run_name}.json")
                    if os.path.isfile(summary):
                        models.append(entry)
    else:  # chain
        for chain_iter_dir in sorted(glob.glob(os.path.join(run_dir, "iter_*"))):
            iter_name = os.path.basename(chain_iter_dir)  # e.g. "iter_001"
            for inner in glob.glob(os.path.join(chain_iter_dir, "iteration_*")):
                for entry in os.listdir(inner):
                    full = os.path.join(inner, entry)
                    if os.path.isdir(full) and not entry.startswith("attempt_") and entry != "__pycache__":
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
    status: Optional[str] = Query(default=None),
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
                with open(summary_path, "r") as f:
                    records = json.load(f)
                break
    else:  # chain — concatenate records from every chain iteration that ran this model
        for chain_iter_dir in sorted(glob.glob(os.path.join(run_dir, "iter_*"))):
            iter_name = os.path.basename(chain_iter_dir)
            for inner in sorted(glob.glob(os.path.join(chain_iter_dir, "iteration_*"))):
                summary_path = os.path.join(inner, model_name, f"summary_{iter_name}.json")
                if os.path.isfile(summary_path):
                    with open(summary_path, "r") as f:
                        records.extend(json.load(f))

    if not records:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found in exploration run '{run_name}'.")

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
    )
