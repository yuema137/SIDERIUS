"""Architectural-pattern tagger — rule-based classifier for proposal configs.

Given a ``(model_type, model_config)`` pair, emit zero or more tags from a
fixed closed vocabulary describing what structural pattern the proposal
belongs to. Used by:

* ``nodes/ml_hyperparameter_tune_agent.py`` — populates
  ``GateExhaustionInfo.disallowed_architectural_patterns`` for attempts
  that blew past the time/VRAM budget by a margin large enough to be a
  structural (not hyperparameter) problem.
* ``nodes/ml_model_proposal_agent.py`` (upcoming) — renders each tag's
  English description under a ``[DISALLOWED PATTERNS]`` block in the
  next iteration's proposer prompt.

The mechanism is **keyword + config-key heuristics**, not ML
classification — hence "tagger". v1 vocabulary:

    recurrent_over_T        — RNN/GRU/LSTM-style sequential recurrence
    scan_over_T             — selective-scan / SSM / Mamba state scan
    dense_attention_over_T  — O(T²) attention without windowing

Extending the vocabulary is intentionally cheap: add a ``_is_*`` helper,
register it in ``_TAGGERS`` below, and add a description entry to
``ARCHITECTURAL_PATTERNS``. No schema migration is required because the
field that carries these tags (``disallowed_architectural_patterns``)
stores a plain ``list[str]``.

See ``docs/reliable_resource_proposer.md`` §7 Decision 1 + §9 Commit 2.
"""

from __future__ import annotations

# ── thresholds (used by the tuner, not by tag_architecture itself) ───────────
# Only attempts that overshoot the budget by this much contribute tags. A
# 1.3× overshoot may be recoverable by reducing depth/width, so banning the
# whole architectural class on marginal overshoots would over-constrain the
# next proposer. See §7 Decision 2.
TIME_FACTOR_THRESHOLD: float = 5.0
VRAM_FACTOR_THRESHOLD: float = 2.0


# ── tag → English description (single source of truth) ──────────────────────
# The proposer-prompt renderer imports this map so the tagger and the
# renderer cannot drift.
ARCHITECTURAL_PATTERNS: dict[str, str] = {
    "recurrent_over_T": (
        "Avoid any RNN/GRU/LSTM or other sequential recurrence over the "
        "time dimension at the active segmentation_size — such models are "
        "structurally incapable of meeting the time budget at this seg_size."
    ),
    "scan_over_T": (
        "Avoid selective-scan / SSM / Mamba-style sequential state "
        "recurrence over the time dimension — the scan cost scales linearly "
        "with T and blows the time budget at the active segmentation_size."
    ),
    "dense_attention_over_T": (
        "Avoid dense (non-windowed) attention over the time dimension — "
        "O(T²) cost is infeasible at the active segmentation_size. Use "
        "windowed/local/chunked attention if attention is required."
    ),
}


# ── per-tag heuristics ──────────────────────────────────────────────────────

_RECURRENT_NAME_HINTS: tuple[str, ...] = ("rnn", "gru", "lstm", "recurrent")
_RECURRENT_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "gru_hidden_size",
        "lstm_hidden_size",
        "rnn_hidden_size",
        "recurrent_hidden",
    }
)

_SCAN_NAME_HINTS: tuple[str, ...] = ("scan", "ssm", "mamba", "s4", "s5")

_ATTENTION_NAME_HINTS: tuple[str, ...] = ("transformer", "attention")
_WINDOWING_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "window_size",
        "chunk_size",
        "attention_window",
        "local_window",
    }
)


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(n in haystack for n in needles)


def _is_recurrent_over_T(model_type_lower: str, model_config: dict) -> bool:
    if _contains_any(model_type_lower, _RECURRENT_NAME_HINTS):
        return True
    return bool(_RECURRENT_CONFIG_KEYS & model_config.keys())


def _is_scan_over_T(model_type_lower: str, model_config: dict) -> bool:
    if _contains_any(model_type_lower, _SCAN_NAME_HINTS):
        return True
    # Conjunctive config-key trigger: state_dim + any ssm_* key together
    # mean the model is building an SSM even if its name hides it.
    has_state_dim = "state_dim" in model_config
    has_ssm_key = any(k.startswith("ssm_") for k in model_config)
    return has_state_dim and has_ssm_key


def _is_dense_attention_over_T(model_type_lower: str, model_config: dict) -> bool:
    if not _contains_any(model_type_lower, _ATTENTION_NAME_HINTS):
        return False
    # "dense" means no windowing mechanism declared in config.
    return not (_WINDOWING_CONFIG_KEYS & model_config.keys())


# Registry: adding a new tag is one line here + one entry in ARCHITECTURAL_PATTERNS.
_TAGGERS: dict[str, callable] = {
    "recurrent_over_T": _is_recurrent_over_T,
    "scan_over_T": _is_scan_over_T,
    "dense_attention_over_T": _is_dense_attention_over_T,
}


# ── public entry point ──────────────────────────────────────────────────────


def tag_architecture(model_type: str, model_config: dict) -> list[str]:
    """Return the sorted list of architectural-pattern tags matched by this
    proposal.

    Args:
        model_type:   the proposer's ``model_name`` / ``model_type``
                      identifier, e.g. ``"dual_path_gated_gru_stack"``.
        model_config: the proposal's ``baseline_config.model_config`` dict
                      (raw kwargs for the config dataclass).

    Returns:
        A sorted list of unique tags from the closed vocabulary in
        ``ARCHITECTURAL_PATTERNS``. Empty list if nothing matches — the
        caller treats this as "no structural ban for this attempt".

    The function is deterministic and side-effect-free: the same inputs
    always produce the same output, and tag order is stable (sorted).
    """
    mt_lower = (model_type or "").lower()
    cfg = model_config or {}
    tags = {tag for tag, matcher in _TAGGERS.items() if matcher(mt_lower, cfg)}
    return sorted(tags)
