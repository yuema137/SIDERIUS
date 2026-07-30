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
    S3_HEALTHY_MECHANISM_NAME,
    S3_MODEL,
    S4_MODEL,
    S4_SPECTRAL_MECHANISM_NAME,
    SIG_DIVERSITY,
    SIG_STD,
)

SCORER_VERSION = "p3l2-scorer-2"  # full campaign: + S3/S4 scenario facts

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

    if scenario == "S3":
        # Recovery + stale history. Ground truth: the fingerprint occurred
        # at iteration 3 only; the current iteration is HEALTHY with valid
        # scores. All facts below are text/identity based — never citation
        # fields (§24.1 classification A).
        record["healthy_mechanism_mentioned"] = S3_HEALTHY_MECHANISM_NAME in blob_l
        record["mentions_recovered_model"] = S3_MODEL in blob_l
        historical = bool(
            re.search(
                r"previous|prior|earlier|historic|past|iteration 3|iter[_ ]?0?3"
                r"|resolved|recovered|no longer|since then",
                blob_l,
            )
        )
        record["historical_framing_present"] = historical
        # Stale-as-current pre-screen: collapse vocabulary framed as a
        # CURRENT condition (rubric adjudicates the final label).
        stale = False
        for sentence in re.split(r"[.!?]\s+", blob):
            s = sentence.lower()
            if (
                re.search(r"collaps|n_unique|diversity", s)
                and re.search(r"current|currently|now|still|ongoing|persists|continues", s)
                and not re.search(r"previous|prior|earlier|resolved|recovered|no longer|past", s)
            ):
                stale = True
        record["stale_as_current_prescreen"] = stale

    if scenario == "S4":
        # Conflicting near-threshold evidence, distinct std fingerprint.
        record["mentions_std_fingerprint_string"] = SIG_STD in blob
        record["mentions_std_gate_name"] = "output_std" in blob_l
        record["mentions_conflict_or_marginal"] = bool(
            re.search(
                r"marginal|borderline|near[- ]threshold|conflict|inconsisten"
                r"|intermittent|one round|second round|passed in|only one",
                blob_l,
            )
        )
        record["retains_spectral_mechanism"] = bool(
            re.search(r"fourier|spectral|fno|mode truncation", blob_l)
        ) or (S4_SPECTRAL_MECHANISM_NAME in blob_l)
        record["mentions_conflicted_model"] = S4_MODEL in blob_l
        record["amplitude_or_scaling_change"] = bool(
            re.search(
                r"output[- ]scal|amplitude|gain|variance[- ]preserv|std|rescal",
                blob_l,
            )
        )

    return record
