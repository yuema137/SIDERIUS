"""Standard launch identities resolved from explicit configuration and advice."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import cast

import yaml

from core.runtime_control.gpu_execution_policy import GpuExecutionPolicy
from workflows.advice import resolve_advice_artifact
from workflows.scientific_evidence_stage import EvidenceStageOrder


@dataclass(frozen=True)
class LaunchIdentity:
    """The run-identity values this launch resolved ONCE (arXiv U1).

    Built by :func:`resolve_launch_identity` before any manifest can be
    written, and handed — as ONE object — to the invariants pre-flight, the
    workflow launch config and every ``write_manifest`` call, so the three
    cannot resolve the lit-review flag or the arm label differently (the W7
    lesson, applied to identity instead of composition).

    Attributes:
        experiment_arm: The opaque arm label, or ``None`` (unlabelled).
        lit_review_enabled: Resolved topology flag (CLI > YAML > ``False``).
        lit_review_config_path: The operator's config path, as given.
        lit_review_config_sha256: sha256 of the resolved config bytes when
            enabled, else ``None``.
        baseline_isolation: arXiv U3 — the WITHOUT arm's explicit isolation
            flag, straight from ``--baseline_isolation``.
        advice_path: Resolved absolute path of the advice artifact this
            launch read, or ``None``. Recorded, never compared.
        advice_sha256: The OBSERVED digest of that artifact's bytes, or
            ``None``. This is the campaign's treatment identity and it is
            CANONICAL in the workspace lock.
    """

    experiment_arm: str | None
    lit_review_enabled: bool
    lit_review_config_path: str | None
    lit_review_config_sha256: str | None
    data_analysis_enabled: bool | None = None
    retain_model_outputs: bool = False
    retain_training_checkpoints: bool = False
    scientific_evidence_order: EvidenceStageOrder = "analysis_then_literature"
    baseline_isolation: bool = False
    advice_path: str | None = None
    advice_sha256: str | None = None
    gpu_execution_policy: GpuExecutionPolicy | None = field(
        default=None, metadata={"omit_if_none": True}
    )


def resolve_lit_review_enabled(cli_flag: bool | None, config_path: str | None) -> bool:
    """Resolve the lit-review enable flag (Design Decisions 1 + 2, 2026-06-11).

    Priority: CLI flag (when explicitly set) > the YAML's top-level
    ``enabled`` key > ``False``. The workflow opens + parses the YAML
    internally (only when enabled); this peeks at ``enabled`` only for the
    CLI-fallback case. A missing or malformed YAML resolves to ``False``
    (fail-safe: do not run lit-review). Pure — no side effects — so it can
    run before the first manifest is written.
    """
    if cli_flag is not None:
        return cli_flag
    if config_path is None:
        return False
    from workflows.literature_config import resolve_lit_review_config_path

    yaml_path = resolve_lit_review_config_path(config_path)
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return bool(data.get("enabled", False))
    except (FileNotFoundError, yaml.YAMLError):
        return False


def resolve_launch_identity(args: argparse.Namespace) -> LaunchIdentity:
    """Resolve the launch's identity values from the parsed CLI (arXiv U1).

    Raises:
        ValueError: lit-review is enabled but its config cannot be read (the
            lock must pin the config's sha256, so the launch is refused), or
            the declared advice artifact cannot be certified
            (:class:`AdviceArtifactError`).
    """
    from workflows.literature_config import lit_review_config_sha256

    retain_model_outputs = bool(getattr(args, "retain_model_outputs", False))
    if getattr(args, "cleanup_denoised", False) and retain_model_outputs:
        raise ValueError("--cleanup_denoised conflicts with --retain_model_outputs")

    enabled = resolve_lit_review_enabled(args.ml_lit_review_enabled, args.ml_lit_review_config)
    # The advice pin comes from the SAME single read the advice CONTENT does
    # (`resolve_advice_artifact` is the one authority and caches on `args`),
    # so the identity locked and the advice injected into the proposer are
    # provably the same bytes.
    advice = resolve_advice_artifact(args)
    from core.runtime_control.gpu_execution_policy import load_gpu_execution_policy

    return LaunchIdentity(
        gpu_execution_policy=load_gpu_execution_policy(
            getattr(args, "gpu_execution_policy_json", None)
        ),
        experiment_arm=args.experiment_arm,
        lit_review_enabled=enabled,
        data_analysis_enabled=args.data_analysis_enabled,
        retain_model_outputs=retain_model_outputs,
        retain_training_checkpoints=bool(args.retain_training_checkpoints),
        lit_review_config_path=args.ml_lit_review_config,
        lit_review_config_sha256=lit_review_config_sha256(
            args.ml_lit_review_config, enabled=enabled
        ),
        scientific_evidence_order=cast(EvidenceStageOrder, args.scientific_evidence_order),
        baseline_isolation=bool(args.baseline_isolation),
        advice_path=None if advice is None else advice.path,
        advice_sha256=None if advice is None else advice.sha256,
    )
