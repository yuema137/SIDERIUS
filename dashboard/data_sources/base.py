# dashboard/data_sources/base.py
"""
Abstract base class for all dashboard data sources.

Implementations:
  - LocalJsonDataSource  (dashboard/data_sources/local_json.py)
  - PostgresDataSource   (dashboard/data_sources/postgres.py, future)

The API layer depends only on this ABC. Switching backends requires only a
config change — no modifications to routes or response models.
"""

from abc import ABC, abstractmethod


class DataSource(ABC):

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @abstractmethod
    def list_models(self) -> list[str]:
        """
        Return the list of model names available in this data source.
        Example: ["punet", "wavenet", "rnn", "fcnet", "transformer"]
        """

    @abstractmethod
    def list_runs(self, model: str) -> list[str]:
        """
        Return all run names for a given model, including "baseline".
        Example: ["baseline", "v1", "v2"]
        Raises KeyError if the model does not exist.
        """

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------

    @abstractmethod
    def get_run_records(
        self,
        model: str,
        run_name: str,
        limit: int = 200,
        offset: int = 0,
        status_filter: str | None = None,
    ) -> tuple[list[dict], int]:
        """
        Return a paginated slice of raw experiment records for model/run_name.

        Args:
            model:         Model name (e.g. "punet").
            run_name:      Run name (e.g. "v1_agent") or "baseline".
            limit:         Maximum number of records to return.
            offset:        Number of records to skip from the beginning.
            status_filter: If set, only return records with this status
                           (e.g. "success", "skipped_oom_risk").

        Returns:
            A (records, total_count) tuple where total_count is the count
            BEFORE pagination (used by the frontend for page navigation).

        Raises:
            KeyError: if model or run_name does not exist.
        """

    @abstractmethod
    def get_experiment(self, model: str, run_name: str, exp_id: str) -> dict:
        """
        Return a single full experiment record by its exp_id.

        Raises:
            KeyError: if model, run_name, or exp_id does not exist.
        """

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    @abstractmethod
    def get_model_overview(self, model: str) -> dict:
        """
        Return aggregated stats for one model across all runs:
          - baseline_score       float | None
          - best_agent_score     float | None
          - best_run_name        str | None
          - total_experiments    int  (success + skipped, all runs combined)
          - status_counts        dict  {"success": N, "skipped_oom_risk": N}
          - runs                 list[str]  all run names including "baseline"

        Raises:
            KeyError: if model does not exist.
        """

    @abstractmethod
    def get_leaderboard(
        self,
        model: str,
        top_n: int = 10,
        status_filter: str = "success",
    ) -> list[dict]:
        """
        Return top_n experiment records across all runs for a model,
        ranked by denoising_score descending (higher is better).

        Each entry is a flat dict with keys:
          exp_id, run_name, denoising_score, final_loss, model_params,
          loss_type, epochs, timestamp

        Raises:
            KeyError: if model does not exist.
        """

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @abstractmethod
    def health_check(self) -> bool:
        """
        Return True if the data source is reachable and readable.
        Should never raise — catch all exceptions internally and return False.
        """
