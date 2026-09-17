"""Pure validation of one inspectable raw-input/prior-model directive.

The schema layer owns this conditional contract. Workflow and standalone
entry points call the same resolver, without giving a prompt access authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .access import AnalysisAccessPolicy
from .assets import AnalysisAsset
from .source_scope import AnalysisSourceScope, DeclaredAnalysisScope


@dataclass(frozen=True)
class _Directive:
    raw: str
    models: str


def _parse_directive(prompt: str) -> _Directive:
    value = prompt.strip()
    if len(value) > 4096:
        raise ValueError("analysis source directive exceeds 4096 characters")
    prefix, separator, body = value.partition(":")
    if not separator or prefix.strip().lower() != "lock":
        raise ValueError(
            "analysis source directive must be 'auto' or "
            "'lock: raw=<asset IDs|all>; "
            "models=<all|none|last:N|last_rounds:N|ids:IDs>'"
        )
    parts = [part.strip() for part in body.split(";")]
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("one source lock requires raw and models selections")
    settings: dict[str, str] = {}
    for part in parts:
        name, equals, selected = part.partition("=")
        name = name.strip().lower()
        selected = selected.strip()
        if not equals or name not in {"raw", "models"} or name in settings or not selected:
            raise ValueError("source lock requires one raw and one models selection")
        settings[name] = selected
    if set(settings) != {"raw", "models"}:
        raise ValueError("source lock requires both raw and models selections")
    return _Directive(raw=settings["raw"], models=settings["models"])


def _ids(value: str) -> tuple[str, ...]:
    items = tuple(item.strip() for item in value.split(","))
    if not items or len(items) > 64 or any(not item for item in items):
        raise ValueError("source lock asset ID selection must contain 1-64 nonempty IDs")
    if len(set(items)) != len(items):
        raise ValueError("source lock asset IDs must be unique")
    return items


def _resolve_raw(value: str, declared: tuple[str, ...]) -> tuple[str, ...]:
    if value.lower() == "all":
        return declared
    selected = _ids(value)
    if not set(selected).issubset(declared):
        raise ValueError("source lock names a raw asset outside the declared scope")
    return selected


def _include_certified_derived_inputs(
    selected: tuple[str, ...],
    *,
    declared: tuple[str, ...],
    assets: tuple[AnalysisAsset, ...],
) -> tuple[str, ...]:
    """Inherit only already-declared input assets with exact parent provenance."""

    by_id = {asset.asset_id: asset for asset in assets}
    included = set(selected)
    for asset_id in declared:
        if asset_id in included:
            continue
        parents = by_id[asset_id].provenance.source_asset_ids
        if parents and set(parents).issubset(included):
            included.add(asset_id)
    return tuple(asset_id for asset_id in declared if asset_id in included)


def _positive_count(value: str, *, prefix: str) -> int:
    count_text = value[len(prefix) :]
    if not count_text.isdecimal() or int(count_text) < 1:
        raise ValueError(f"{prefix}N requires a positive integer N")
    return int(count_text)


def _resolve_models(
    value: str,
    declared: tuple[str, ...],
    *,
    assets: tuple[AnalysisAsset, ...] = (),
    history_run_names: tuple[str, ...] = (),
) -> tuple[str, ...]:
    lowered = value.lower()
    if lowered == "all":
        return declared
    if lowered == "none":
        return ()
    if lowered.startswith("last:"):
        return declared[-_positive_count(value, prefix="last:") :]
    if lowered.startswith("last_rounds:"):
        count = _positive_count(value, prefix="last_rounds:")
        if not declared:
            return ()
        if not history_run_names:
            raise ValueError("last_rounds:N requires declared prior iteration history")
        by_id = {asset.asset_id: asset for asset in assets}
        selected_runs = set(history_run_names[-count:])
        return tuple(
            asset_id for asset_id in declared if by_id[asset_id].provenance.run_id in selected_runs
        )
    if lowered.startswith("ids:"):
        selected = _ids(value[4:])
        if not set(selected).issubset(declared):
            raise ValueError("source lock names a model outside the declared history")
        return tuple(asset_id for asset_id in declared if asset_id in selected)
    raise ValueError("models must be all, none, last:N, last_rounds:N, or ids:<asset IDs>")


def source_prompt_identity(prompt: str | None) -> str | None:
    """Canonical launch pin; omission/auto preserve the pre-lock identity."""

    if prompt is None or prompt.strip().lower() == "auto":
        return None
    directive = _parse_directive(prompt)
    if directive.raw.lower() != "all":
        _ids(directive.raw)
    if directive.models.lower().startswith(("last:", "last_rounds:")):
        _resolve_models(directive.models, ())
    elif directive.models.lower().startswith("ids:"):
        _ids(directive.models[4:])
    elif directive.models.lower() not in {"all", "none"}:
        raise ValueError("models must be all, none, last:N, last_rounds:N, or ids:<asset IDs>")
    return hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()


def resolve_source_prompt(
    prompt: str | None,
    *,
    declared_scope: DeclaredAnalysisScope,
    available_assets: tuple[AnalysisAsset, ...],
    access_policy: AnalysisAccessPolicy,
) -> AnalysisSourceScope:
    """Resolve exact IDs from a finite declaration, never from the filesystem."""

    declared_scope.validate_assets(available_assets, access_policy)
    if prompt is None or prompt.strip().lower() == "auto":
        return AnalysisSourceScope.automatic(declared_scope)
    directive = _parse_directive(prompt)
    selected_raw = _resolve_raw(directive.raw, declared_scope.raw_input_asset_ids)
    return AnalysisSourceScope(
        mode="locked",
        raw_input_asset_ids=_include_certified_derived_inputs(
            selected_raw,
            declared=declared_scope.raw_input_asset_ids,
            assets=available_assets,
        ),
        historical_model_asset_ids=_resolve_models(
            directive.models,
            declared_scope.historical_model_asset_ids,
            assets=available_assets,
            history_run_names=declared_scope.history_run_names,
        ),
        source_prompt=prompt.strip(),
    )
