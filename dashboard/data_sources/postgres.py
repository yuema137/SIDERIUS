# dashboard/data_sources/postgres.py
"""
PostgreSQL DataSource — future implementation.

To activate:
  1. Set data_source.type = "postgres" in dashboard_config.yaml.
  2. Implement each abstract method below using asyncpg or SQLAlchemy async.
  3. Run ingest.py to populate the database from existing JSON summary files.
"""

from dashboard.data_sources.base import DataSource


class PostgresDataSource(DataSource):
    def __init__(self, connection_string: str, schema: str = "public"):
        self.connection_string = connection_string
        self.schema = schema
        raise NotImplementedError(
            "PostgresDataSource is not yet implemented. "
            "Set data_source.type=local in dashboard_config.yaml."
        )

    @property
    def root(self) -> str:
        raise NotImplementedError(
            "Postgres backend storage is pending architectural integration."
        )

    def list_models(self) -> list[str]:
        raise NotImplementedError

    def list_runs(self, model: str) -> list[str]:
        raise NotImplementedError

    def get_run_records(self, model, run_name, limit=200, offset=0, status_filter=None):
        raise NotImplementedError

    def get_experiment(self, model, run_name, exp_id):
        raise NotImplementedError

    def get_model_overview(self, model):
        raise NotImplementedError

    def get_leaderboard(self, model, top_n=10, status_filter="success"):
        raise NotImplementedError

    def health_check(self) -> bool:
        return False
