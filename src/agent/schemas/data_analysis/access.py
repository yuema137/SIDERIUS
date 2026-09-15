"""Access and anti-leakage policy for Data Analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import FrozenModel, NonEmptyStr

InformationClass = Literal["identity", "data", "target", "prediction", "residual", "metadata"]


class InformationRequirement(FrozenModel):
    """One explicitly declared class of information and any named metadata fields."""

    information_class: InformationClass
    fields: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_fields(self) -> InformationRequirement:
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("information fields must be unique")
        if any("*" in field for field in self.fields):
            raise ValueError("metadata wildcard fields are forbidden")
        if self.information_class == "metadata" and not self.fields:
            raise ValueError("metadata information requires explicit field names")
        if self.information_class != "metadata" and self.fields:
            raise ValueError("field names are supported only for metadata information")
        return self


# Requests and declarations intentionally share one field-level vocabulary.
RequestedInformation = InformationRequirement


class MetadataVisibility(FrozenModel):
    mode: Literal["none", "allowlist"] = "none"
    fields: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_fields(self) -> MetadataVisibility:
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("metadata visibility fields must be unique")
        if self.mode == "none" and self.fields:
            raise ValueError("metadata fields must be empty when mode='none'")
        if self.mode == "allowlist" and not self.fields:
            raise ValueError("metadata mode='allowlist' requires at least one field")
        return self


class SplitAccessRule(FrozenModel):
    split_id: NonEmptyStr
    data_visible: bool = True
    targets_visible: bool = False
    predictions_visible: bool = False
    residuals_visible: bool = False
    metadata: MetadataVisibility = Field(default_factory=MetadataVisibility)


class AnalysisAccessPolicy(FrozenModel):
    policy_id: NonEmptyStr
    policy_version: int = Field(ge=1)
    purpose: NonEmptyStr
    split_rules: tuple[SplitAccessRule, ...]
    allow_model_inference: bool = False

    @model_validator(mode="after")
    def validate_split_rules(self) -> AnalysisAccessPolicy:
        split_ids = [rule.split_id for rule in self.split_rules]
        if not split_ids:
            raise ValueError("access policy requires at least one split rule")
        if len(set(split_ids)) != len(split_ids):
            raise ValueError("access policy split IDs must be unique")
        if not any(rule.data_visible for rule in self.split_rules):
            raise ValueError("access policy must expose data for at least one split")
        return self

    @property
    def allowed_splits(self) -> tuple[str, ...]:
        return tuple(rule.split_id for rule in self.split_rules if rule.data_visible)

    def rule_for(self, split_id: str) -> SplitAccessRule:
        for rule in self.split_rules:
            if rule.split_id == split_id:
                return rule
        raise ValueError(f"split {split_id!r} is not declared by access policy {self.policy_id!r}")

    def permits(
        self,
        *,
        split_id: str | None,
        information_class: InformationClass,
        source_fields: tuple[str, ...] = (),
    ) -> bool:
        if information_class == "identity":
            return split_id is None and not source_fields
        if split_id is None:
            return False
        rule = self.rule_for(split_id)
        if information_class == "data":
            return rule.data_visible
        if information_class == "target":
            return rule.data_visible and rule.targets_visible
        if information_class == "prediction":
            return rule.data_visible and rule.predictions_visible
        if information_class == "residual":
            return rule.data_visible and rule.residuals_visible
        if information_class == "metadata":
            return (
                rule.data_visible
                and rule.metadata.mode == "allowlist"
                and bool(source_fields)
                and set(source_fields).issubset(rule.metadata.fields)
            )
        return False
