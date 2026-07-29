# scripts/pr3_l2_calibration/scorer.py
"""Deterministic scorer for calibration samples (protocol §10).

Emits raw comparison FACTS from typed proposal fields — never
judgments. The blinded rubric adjudicates only what this scorer marks
inconclusive (semantic equivalence, mechanism relevance of novel
components, indirect claims). Scorer output and rubric output are
separate records by construction.

Determinism: pure function of (parsed proposal dict, scenario spec).
Re-running on identical artifacts must produce identical records — a
protocol stop condition otherwise (§16).
"""

from __future__ import annotations

import re
from typing import Any

from scripts.pr3_l2_calibration.fixtures import (
    FAILED_CONFIG,
    HEALTHY_MECHANISM_NAME,
    SIG_DIVERSITY,
)

SCORER_VERSION = "p3l2p-scorer-1"

# Treatment-only strings whose presence in a CONTROL/DIAGNOSTIC proposer
# prompt or output indicates leakage (§16 stop) or an unsupported-use
# probe hit (metric 8.1).
TREATMENT_MARKERS = (
    "[HEALTHGATE EVIDENCE]",
    SIG_DIVERSITY,
    "Representative observation:",
)

_ACTIVATION_WORDS = r"activation|softmax|sigmoid|tanh|relu|gelu|silu|logits"
_NORM_WORDS = r"normali[sz]|batchnorm|layernorm|groupnorm|instance ?norm|rmsnorm"
_QUANT_WORDS = r"quanti[sz]|clip|clamp|saturat|int8 (?:head|output|range)"
_DIVERSITY_LOSS_WORDS = r"diversity|entropy|variance|anti[- ]collapse|repulsi|decorrelat"


def _text_blob(proposal: dict[str, Any]) -> str:
    parts = [
        str(proposal.get("model_description", "")),
        str(proposal.get("mathematical_definition", "")),
        str(proposal.get("motivation", "")),
    ]
    return "\n".join(parts)


def score_sample(
    scenario: str,
    arm: str,
    proposal: dict[str, Any] | None,
    proposing_prompt: str,
) -> dict[str, Any]:
    """Deterministic fact record for one sample."""
    record: dict[str, Any] = {
        "scorer_version": SCORER_VERSION,
        "scenario": scenario,
        "schema_valid": proposal is not None,
    }

    # --- prompt-side facts (leak / delivery checks) ---
    record["prompt_has_treatment_block"] = "[HEALTHGATE EVIDENCE]" in proposing_prompt
    record["prompt_has_fingerprint"] = SIG_DIVERSITY in proposing_prompt
    expected_block = arm == "T"
    record["treatment_isolation_ok"] = record["prompt_has_treatment_block"] == expected_block

    if proposal is None:
        return record

    blob = _text_blob(proposal)
    blob_l = blob.lower()
    cfg = proposal.get("baseline_config") or {}
    model_cfg = cfg.get("model_config") or {}
    train_cfg = cfg.get("train_config") or {}
    loss_cfg = cfg.get("loss_config") or {}

    # --- output-side facts ---
    record["model_name"] = proposal.get("model_name")
    record["mentions_fingerprint_string"] = SIG_DIVERSITY in blob
    record["mentions_gate_name"] = "output_diversity" in blob_l
    record["mentions_model_a"] = "collapsing_tcn_a" in blob_l
    record["mentions_model_b"] = "spectral_resnet_b" in blob_l
    record["claims_feedback_use"] = bool(
        re.search(r"healthgate|structured (?:health )?feedback|collapse fingerprint", blob_l)
    )

    # --- deterministic mechanism-change facts vs the FAILED config ---
    record["loss_type_changed"] = (
        loss_cfg.get("loss_type") is not None
        and loss_cfg.get("loss_type") != FAILED_CONFIG["loss_config"]["loss_type"]
    )
    record["custom_loss_populated"] = bool(proposal.get("custom_loss_spec"))
    record["lr_changed"] = (
        train_cfg.get("lr") is not None
        and train_cfg.get("lr") != FAILED_CONFIG["train_config"]["lr"]
    )
    record["epochs_changed"] = (
        train_cfg.get("epochs") is not None
        and train_cfg.get("epochs") != FAILED_CONFIG["train_config"]["epochs"]
    )
    record["architecture_name_new"] = proposal.get("model_name") not in (
        None,
        FAILED_CONFIG["model_config"]["model_type"],
    )
    record["mentions_activation_mechanism"] = bool(re.search(_ACTIVATION_WORDS, blob_l))
    record["mentions_normalization_mechanism"] = bool(re.search(_NORM_WORDS, blob_l))
    record["mentions_quantization_mechanism"] = bool(re.search(_QUANT_WORDS, blob_l))
    record["mentions_diversity_loss_mechanism"] = bool(re.search(_DIVERSITY_LOSS_WORDS, blob_l))
    record["deterministic_relevant_change"] = any(
        (
            record["loss_type_changed"] and record["mentions_diversity_loss_mechanism"],
            record["custom_loss_populated"],
            record["mentions_activation_mechanism"],
            record["mentions_normalization_mechanism"],
            record["mentions_quantization_mechanism"],
        )
    )
    # Same-config repeat pre-screen (rubric decides semantic equivalence).
    record["config_equals_failed"] = (
        model_cfg.get("depth") == FAILED_CONFIG["model_config"]["depth"]
        and model_cfg.get("channels") == FAILED_CONFIG["model_config"]["channels"]
        and loss_cfg.get("loss_type") == FAILED_CONFIG["loss_config"]["loss_type"]
        and not record["custom_loss_populated"]
    )

    if scenario == "S2":
        record["healthy_mechanism_mentioned"] = HEALTHY_MECHANISM_NAME in blob_l
        # Cross-attribution pre-screen: model_b named in the same sentence
        # as the diversity-collapse vocabulary.
        cross = False
        for sentence in re.split(r"[.!?]\s+", blob):
            s = sentence.lower()
            if "spectral_resnet_b" in s and re.search(r"collaps|n_unique|diversity", s):
                cross = True
        record["cross_attribution_prescreen"] = cross

    return record
