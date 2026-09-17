"""One caller-declared Data Analysis ceiling over raw input and prior models.

The scope is a narrowing authority, not a task-specific source catalog. Model
outputs produced by inference are transient action results; persisted outputs
and ground truth are never eligible source objects in this contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .access import AnalysisAccessPolicy, InformationClass
from .assets import AnalysisAsset, TrainedModelArtifactLocation
from .common import FrozenModel, NonEmptyStr


class DeclaredAnalysisScope(FrozenModel):
    """Exact caller-visible assets, with prior models ordered oldest to newest.

    The task/caller declares raw-input asset identities. A workflow may append
    certified prior model identities after training; their order is the
    authority for a prompt's ``last:N`` selection. A separate chronological
    iteration list, when supplied, also accounts for rounds without a model
    under ``last_rounds:N``. This declaration grants no data access without
    the independent AnalysisAccessPolicy.
    """

    raw_input_asset_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    historical_model_asset_ids: tuple[NonEmptyStr, ...] = ()
    history_run_names: tuple[NonEmptyStr, ...] = Field(
        default=(),
        exclude_if=lambda value: not value,
        description=(
            "Prior iteration run names in chronological order, including iterations "
            "without a trained model. Used only for previous-N-iterations selection."
        ),
    )

    @model_validator(mode="after")
    def validate_ids(self) -> DeclaredAnalysisScope:
        raw = self.raw_input_asset_ids
        models = self.historical_model_asset_ids
        if len(set(raw)) != len(raw) or len(set(models)) != len(models):
            raise ValueError("analysis scope asset IDs must be unique within each category")
        if set(raw) & set(models):
            raise ValueError("one asset cannot be both raw input and a trained model")
        if len(set(self.history_run_names)) != len(self.history_run_names):
            raise ValueError("history iteration run names must be unique")
        return self

    def validate_assets(
        self,
        assets: tuple[AnalysisAsset, ...],
        policy: AnalysisAccessPolicy,
    ) -> None:
        """Prove each declared identity is a usable, self-consistent object."""

        by_id = {asset.asset_id: asset for asset in assets}
        for asset_id in self.raw_input_asset_ids:
            asset = by_id.get(asset_id)
            if asset is None or asset.asset_type != "dataset":
                raise ValueError(f"raw input {asset_id!r} is not an available dataset asset")
            if "materialize" not in asset.allowed_operations or not policy.permits(
                split_id=asset.split_id, information_class="data"
            ):
                raise ValueError(f"raw input {asset_id!r} is not authorized for materialization")
        history_positions = {name: index for index, name in enumerate(self.history_run_names)}
        previous_position = -1
        for asset_id in self.historical_model_asset_ids:
            asset = by_id.get(asset_id)
            if asset is None or asset.asset_type != "trained_model":
                raise ValueError(f"historical model {asset_id!r} is not an available model asset")
            if not isinstance(asset.location, TrainedModelArtifactLocation):
                raise ValueError("historical model lacks an immutable trained-model artifact")
            if "infer" not in asset.allowed_operations or not policy.allow_model_inference:
                raise ValueError(f"historical model {asset_id!r} is not authorized for inference")
            if not policy.permits(split_id=asset.split_id, information_class="prediction"):
                raise ValueError(f"historical model {asset_id!r} has no prediction visibility")
            training_run = asset.location.artifact.training_run
            if asset.provenance.run_id != training_run.run_name or (
                asset.provenance.iteration_id is not None
                and asset.provenance.iteration_id != training_run.iteration_id
            ):
                raise ValueError(f"historical model {asset_id!r} has inconsistent provenance")
            if history_positions:
                position = history_positions.get(training_run.run_name)
                if position is None:
                    raise ValueError(f"historical model {asset_id!r} is outside declared history")
                if position < previous_position:
                    raise ValueError("historical models must follow declared iteration order")
                previous_position = position


class AnalysisSourceScope(FrozenModel):
    """Resolved single ceiling enforced at plan and materialization boundaries."""

    mode: Literal["automatic", "locked"]
    raw_input_asset_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    historical_model_asset_ids: tuple[NonEmptyStr, ...] = ()
    source_prompt: NonEmptyStr | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def validate_scope(self) -> AnalysisSourceScope:
        if len(set(self.raw_input_asset_ids)) != len(self.raw_input_asset_ids):
            raise ValueError("raw input IDs in the resolved scope must be unique")
        if len(set(self.historical_model_asset_ids)) != len(self.historical_model_asset_ids):
            raise ValueError("historical model IDs in the resolved scope must be unique")
        if set(self.raw_input_asset_ids) & set(self.historical_model_asset_ids):
            raise ValueError("one asset cannot appear in both scope categories")
        if self.mode == "automatic" and self.source_prompt is not None:
            raise ValueError("automatic scope cannot carry a lock directive")
        if self.mode == "locked" and self.source_prompt is None:
            raise ValueError("locked scope requires its inspectable directive")
        return self

    @classmethod
    def automatic(cls, declaration: DeclaredAnalysisScope) -> AnalysisSourceScope:
        return cls(
            mode="automatic",
            raw_input_asset_ids=declaration.raw_input_asset_ids,
            historical_model_asset_ids=declaration.historical_model_asset_ids,
        )

    def permits(
        self,
        *,
        asset_id: str,
        information_class: InformationClass,
        operation: str,
        fields: tuple[str, ...] = (),
    ) -> bool:
        """Bound object kind and operation; access policy still checks fields/split."""

        if asset_id in self.raw_input_asset_ids:
            return (
                operation in {"read", "materialize"}
                and information_class in {"data", "metadata"}
                and (information_class == "metadata" or not fields)
            )
        if asset_id in self.historical_model_asset_ids:
            return operation == "infer" and information_class == "prediction" and not fields
        return False
