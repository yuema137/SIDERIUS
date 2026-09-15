"""Explicit runtime access passed to trusted, selected skill implementations."""

from __future__ import annotations

from pathlib import Path

from agent.schemas.data_analysis.assets import MaterializedAnalysisView

from .view_formats import LoadedMaterializedView, load_materialized_view


class SkillRuntime:
    """Resolve authorized views and artifact destinations without path conventions."""

    def __init__(
        self,
        *,
        materialization_paths: dict[str, str],
        materializations: tuple[MaterializedAnalysisView, ...],
        artifact_directory: str,
    ) -> None:
        self._materialization_paths = {
            key: Path(value).resolve() for key, value in materialization_paths.items()
        }
        self._materializations = {view.binding_id: view for view in materializations}
        self._artifact_directory = Path(artifact_directory).resolve()

    def load_materialization(self, binding_id: str) -> LoadedMaterializedView:
        try:
            path = self._materialization_paths[binding_id]
            descriptor = self._materializations[binding_id]
        except KeyError as exc:
            raise KeyError(f"no authorized materialization for binding {binding_id!r}") from exc
        return load_materialized_view(descriptor, path)

    def artifact_path(self, relative_path: str) -> Path:
        path = (self._artifact_directory / relative_path).resolve()
        if path == self._artifact_directory or self._artifact_directory not in path.parents:
            raise ValueError("artifact path must remain inside the invocation output directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
