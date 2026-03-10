# dashboard/data_sources/local_json.py
"""
DataSource implementation that reads experiment records from local JSON
summary files written by the SIDERIUS pipeline.

File layout expected under root_data_dir:
  {model}/baseline/summary_baseline_{model}.json
  {model}/{run_name}/agent/summary_{run_name}_agent.json

Each file is a JSON array of experiment record dicts.
"""

import glob
import json
import os
from typing import Optional

from dashboard.data_sources.base import DataSource


class LocalJsonDataSource(DataSource):

    def __init__(self, root_data_dir: str, models: Optional[list[str]] = None):
        """
        Args:
            root_data_dir: Root directory containing per-model subdirectories.
            models:        Explicit model list. If empty or None, auto-discovered
                           by scanning root_data_dir for subdirectories.
        """
        self.root = root_data_dir
        self._explicit_models = models or []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _model_dir(self, model: str) -> str:
        return os.path.join(self.root, model)

    def _baseline_summary_path(self, model: str) -> Optional[str]:
        """
        Glob for the baseline summary file. Returns the first match or None.
        Uses glob because run_comparison.py names the file
        summary_baseline_{model}.json but a timestamp variant may exist.
        """
        pattern = os.path.join(self._model_dir(model), "baseline", "summary_*.json")
        matches = glob.glob(pattern)
        return matches[0] if matches else None

    def _agent_summary_path(self, model: str, run_name: str) -> str:
        """
        Canonical path for an agent run summary.
        run_name is the raw run label (e.g. "v1"); the file lives under
        {model}/{run_name}/agent/summary_{run_name}_agent.json
        """
        return os.path.join(
            self._model_dir(model), run_name, "agent",
            f"summary_{run_name}_agent.json"
        )

    def _read_json(self, path: str) -> list[dict]:
        """Read a summary JSON file. Returns [] on any error."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _list_agent_run_names(self, model: str) -> list[str]:
        """
        Scan {model}/ for subdirectories that contain an agent summary file.
        Returns run labels (e.g. ["v1", "v2"]) sorted alphabetically.
        """
        model_dir = self._model_dir(model)
        if not os.path.isdir(model_dir):
            return []
        runs = []
        for entry in sorted(os.listdir(model_dir)):
            if entry == "baseline":
                continue
            agent_path = self._agent_summary_path(model, entry)
            if os.path.exists(agent_path):
                runs.append(entry)
        return runs

    def _all_records_for_model(self, model: str) -> list[dict]:
        """Return every record across all runs (baseline + all agents)."""
        records = []
        baseline_path = self._baseline_summary_path(model)
        if baseline_path:
            records.extend(self._read_json(baseline_path))
        for run_name in self._list_agent_run_names(model):
            path = self._agent_summary_path(model, run_name)
            for rec in self._read_json(path):
                # Skip the seeded baseline record that run_comparison.py
                # inserts at position 0 of every agent summary to avoid
                # double-counting it in aggregates.
                if "baseline" in rec.get("exp_id", ""):
                    continue
                rec = dict(rec, _run_name=run_name)  # inject run_name for leaderboard
                records.append(rec)
        return records

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_models(self) -> list[str]:
        if self._explicit_models:
            return [m for m in self._explicit_models if os.path.isdir(self._model_dir(m))]
        if not os.path.isdir(self.root):
            return []
        return sorted(
            e for e in os.listdir(self.root)
            if os.path.isdir(os.path.join(self.root, e))
        )

    def list_runs(self, model: str) -> list[str]:
        if not os.path.isdir(self._model_dir(model)):
            raise KeyError(f"Model '{model}' not found in {self.root}")
        runs = []
        if self._baseline_summary_path(model):
            runs.append("baseline")
        runs.extend(self._list_agent_run_names(model))
        return runs

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------

    def get_run_records(
        self,
        model: str,
        run_name: str,
        limit: int = 200,
        offset: int = 0,
        status_filter: str | None = None,
    ) -> tuple[list[dict], int]:
        if run_name == "baseline":
            path = self._baseline_summary_path(model)
            records = self._read_json(path) if path else []
        else:
            path = self._agent_summary_path(model, run_name)
            if not os.path.exists(path):
                raise KeyError(f"Run '{run_name}' not found for model '{model}'")
            # Exclude the seeded baseline record at position 0
            records = [
                r for r in self._read_json(path)
                if "baseline" not in r.get("exp_id", "")
            ]

        if status_filter:
            records = [r for r in records if r.get("status") == status_filter]

        total = len(records)
        return records[offset: offset + limit], total

    def get_experiment(self, model: str, run_name: str, exp_id: str) -> dict:
        records, _ = self.get_run_records(model, run_name, limit=10_000)
        for rec in records:
            if rec.get("exp_id") == exp_id:
                return rec
        raise KeyError(f"Experiment '{exp_id}' not found in {model}/{run_name}")

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def get_model_overview(self, model: str) -> dict:
        if not os.path.isdir(self._model_dir(model)):
            raise KeyError(f"Model '{model}' not found in {self.root}")

        # Baseline score
        baseline_score = None
        baseline_path = self._baseline_summary_path(model)
        if baseline_path:
            baseline_records = self._read_json(baseline_path)
            if baseline_records:
                baseline_score = baseline_records[0].get("denoising_score")

        # Agent records across all runs
        status_counts: dict[str, int] = {}
        best_score: Optional[float] = None
        best_run_name: Optional[str] = None

        for run_name in self._list_agent_run_names(model):
            path = self._agent_summary_path(model, run_name)
            for rec in self._read_json(path):
                if "baseline" in rec.get("exp_id", ""):
                    continue
                status = rec.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
                score = rec.get("denoising_score")
                if score is not None and (best_score is None or score > best_score):
                    best_score = score
                    best_run_name = run_name

        total = sum(status_counts.values())
        runs = self.list_runs(model)

        return {
            "model": model,
            "baseline_score": baseline_score,
            "best_agent_score": best_score,
            "best_run_name": best_run_name,
            "total_experiments": total,
            "status_counts": status_counts,
            "runs": runs,
        }

    def get_leaderboard(
        self,
        model: str,
        top_n: int = 10,
        status_filter: str = "success",
    ) -> list[dict]:
        if not os.path.isdir(self._model_dir(model)):
            raise KeyError(f"Model '{model}' not found in {self.root}")

        entries = []
        for run_name in self._list_agent_run_names(model):
            path = self._agent_summary_path(model, run_name)
            for rec in self._read_json(path):
                if "baseline" in rec.get("exp_id", ""):
                    continue
                if status_filter and rec.get("status") != status_filter:
                    continue
                score = rec.get("denoising_score")
                if score is None:
                    continue
                entries.append({
                    "exp_id":          rec.get("exp_id"),
                    "run_name":        run_name,
                    "denoising_score": score,
                    "final_loss":      rec.get("results", {}).get("final_loss"),
                    "model_params":    rec.get("results", {}).get("model_params"),
                    "loss_type":       rec.get("params", {}).get("loss_config", {}).get("loss_type"),
                    "epochs":          rec.get("params", {}).get("train_config", {}).get("epochs"),
                    "timestamp":       rec.get("timestamp"),
                })

        entries.sort(key=lambda e: e["denoising_score"], reverse=True)
        for i, entry in enumerate(entries[:top_n], start=1):
            entry["rank"] = i
        return entries[:top_n]

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        try:
            return os.path.isdir(self.root)
        except Exception:
            return False
