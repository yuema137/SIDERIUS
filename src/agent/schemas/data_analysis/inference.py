"""Typed requests at the historical-model inference execution boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .access import RequestedInformation
from .assets import AnalysisAuthorizationReceipt, AnalysisScopeDescriptor, MaterializedAnalysisView
from .common import FrozenModel, NonEmptyStr, canonical_sha256
from .resources import AnalysisResourceEnvelope, CertifiedSelectionIdentity
from .trained_model import ModelInferenceReceipt, TrainedModelArtifact, TrainedModelArtifactRef


class HistoricalInferenceConfiguration(FrozenModel):
    batch_size: int = Field(gt=0)
    device: Literal["cpu", "gpu"]
    determinism: Literal["deterministic", "stochastic_seeded"] = "deterministic"
    seed: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_seed(self) -> HistoricalInferenceConfiguration:
        if self.determinism == "stochastic_seeded" and self.seed is None:
            raise ValueError("stochastic historical inference requires a seed")
        if self.determinism == "deterministic" and self.seed is not None:
            raise ValueError("deterministic historical inference does not accept a seed")
        return self


class HistoricalModelInferenceRequest(FrozenModel):
    request_id: NonEmptyStr
    invocation_id: NonEmptyStr
    output_binding_id: NonEmptyStr
    output_slot_id: NonEmptyStr
    output_asset_id: NonEmptyStr
    model_artifact: TrainedModelArtifact
    model_artifact_ref: TrainedModelArtifactRef
    model_authorization_receipt: AnalysisAuthorizationReceipt
    input_views: tuple[MaterializedAnalysisView, ...]
    split_id: NonEmptyStr
    requested_scope: AnalysisScopeDescriptor = Field(discriminator="kind")
    selection_identity: CertifiedSelectionIdentity
    requested_prediction_format: NonEmptyStr
    requested_information: tuple[RequestedInformation, ...]
    configuration: HistoricalInferenceConfiguration
    resource_envelope: AnalysisResourceEnvelope
    deadline_monotonic_s: float = Field(gt=0.0)

    def scientific_identity(self) -> dict[str, object]:
        """Host-independent determinants of the canonical prediction artifact."""

        return {
            "model_artifact_id": self.model_artifact.model_artifact_id,
            "executable_model_identity_sha256": (
                self.model_artifact.executable_model_identity_sha256
            ),
            "input_materializations": [
                {
                    "materialization_id": view.materialization_id,
                    "content_sha256": view.content_ref.sha256,
                    "format_id": view.format_id,
                    "certified_information": [
                        item.model_dump(mode="json") for item in view.certified_information
                    ],
                }
                for view in self.input_views
            ],
            "split_id": self.split_id,
            "requested_scope": self.requested_scope.model_dump(mode="json"),
            "selection_identity": self.selection_identity.model_dump(mode="json"),
            "requested_prediction_format": self.requested_prediction_format,
            "inference_protocol_id": self.model_artifact.inference_protocol_id,
            "configuration": self.configuration.model_dump(mode="json"),
        }

    @property
    def scientific_identity_sha256(self) -> str:
        return canonical_sha256(self.scientific_identity())

    @model_validator(mode="after")
    def validate_request(self) -> HistoricalModelInferenceRequest:
        if not self.input_views:
            raise ValueError("historical inference requires explicit input materializations")
        if tuple(item.information_class for item in self.requested_information) != ("prediction",):
            raise ValueError("historical inference output must contain only prediction")
        binding_ids = [view.binding_id for view in self.input_views]
        if len(set(binding_ids)) != len(binding_ids):
            raise ValueError("historical inference input binding IDs must be unique")
        observed_information: dict[str, set[str]] = {}
        inference = self.model_artifact.model_io_contract.inference
        assert inference is not None
        for view in self.input_views:
            if view.split_id != self.split_id:
                raise ValueError("historical inference inputs must use the authorized split")
            if view.selection_identity != self.selection_identity:
                raise ValueError("historical inference inputs must share the certified selection")
            if view.format_id not in inference.accepted_input_view_formats:
                raise ValueError("historical inference input format differs from ModelIOContract")
            if any(item.information_class == "target" for item in view.certified_information):
                raise ValueError("predictor inference inputs must never contain target information")
            for item in view.certified_information:
                if item.information_class in observed_information:
                    raise ValueError(
                        "historical inference information classes must have one explicit owner"
                    )
                observed_information[item.information_class] = set(item.fields)
        required_information = {
            item.information_class: set(item.fields) for item in inference.required_information
        }
        if observed_information != required_information:
            raise ValueError(
                "historical inference inputs must exactly match ModelIOContract information"
            )
        if self.requested_prediction_format != inference.prediction_output_format:
            raise ValueError("requested prediction format differs from ModelIOContract")
        if self.configuration.determinism != inference.determinism:
            raise ValueError("inference determinism differs from ModelIOContract")
        authorization = self.model_authorization_receipt
        if (
            authorization.invocation_id != self.invocation_id
            or authorization.binding_id != self.output_binding_id
            or authorization.slot_id != self.output_slot_id
        ):
            raise ValueError("historical inference output differs from its authorization receipt")
        ref = self.model_artifact_ref
        if (
            ref.model_artifact_id != self.model_artifact.model_artifact_id
            or ref.executable_model_identity_sha256
            != self.model_artifact.executable_model_identity_sha256
            or ref.artifact_ref.sha256 != canonical_sha256(self.model_artifact)
        ):
            raise ValueError("trained-model artifact ref differs from its document")
        return self


class HistoricalInferenceMaterialization(FrozenModel):
    view: MaterializedAnalysisView | None = None
    receipt: ModelInferenceReceipt

    @model_validator(mode="after")
    def validate_result(self) -> HistoricalInferenceMaterialization:
        if self.receipt.status == "completed":
            if self.view is None:
                raise ValueError("completed inference requires a prediction view")
            if self.view.historical_inference_receipt != self.receipt:
                raise ValueError("prediction view must carry the exact inference receipt")
        elif self.view is not None:
            raise ValueError("failed inference cannot return a prediction view")
        return self
