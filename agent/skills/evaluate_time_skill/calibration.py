"""
Per-GPU learned calibration for evaluate_time_skill.

Maintains a `k(gpu, model_type)` correction factor that multiplies the
warmup-measured ms/step. Updated post-training via an asymmetric EMA
(faster correction toward safety, slower drift toward optimism) — see
docs/resource_estimator_implement.md §2.6.5.

File layout (one JSON per GPU; lives at ``$SIDERIUS_CALIBRATION_DIR`` or
``~/.siderius``):

```json
{
  "gpu_name":  "NVIDIA GeForce RTX 5090",
  "k_values":  { "wavenet": 1.23, "punet": 0.95, "*": 1.10 },
  "history":   [ { ...entry... }, ... ]
}
```

The table is loaded fresh on each call (no in-process cache) and written
atomically (tmp + rename) so concurrent tuners on the same GPU don't
corrupt each other's writes.

The proposer is read-only against this file; the tuner is the sole writer
(post-training, after a real ``train_time_s`` is available).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime

# Asymmetric EMA constants (§2.6.5). α_up > α_down so under-prediction
# (the expensive failure mode) corrects faster than over-prediction.
ALPHA_UP: float = 0.5
ALPHA_DOWN: float = 0.1

# Hard clip on `k` so a single broken run can't poison the table for hours.
K_MIN: float = 0.5
K_MAX: float = 5.0

# Wildcard model_type used as the per-GPU fallback for never-seen models.
WILDCARD_KEY: str = "*"

# Default location ~/.siderius — overridable via env var so SDSC users can
# point at $HOME or $SCRATCH depending on quota (§2.6.4).
_ENV_VAR: str = "SIDERIUS_CALIBRATION_DIR"
_DEFAULT_SUBDIR: str = ".siderius"


# ── path / IO helpers ────────────────────────────────────────────────────────


def calibration_dir() -> str:
    """Return the directory holding `time_calibration_*.json` files."""
    override = os.environ.get(_ENV_VAR)
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), _DEFAULT_SUBDIR)


def gpu_slug(gpu_name: str) -> str:
    """Slugify a GPU name to a stable lowercase filesystem-safe token."""
    s = gpu_name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "unknown_gpu"


def calibration_path(gpu_name: str) -> str:
    return os.path.join(calibration_dir(), f"time_calibration_{gpu_slug(gpu_name)}.json")


def _empty_table(gpu_name: str) -> dict:
    return {"gpu_name": gpu_name, "k_values": {}, "history": []}


def load_table(gpu_name: str) -> dict:
    """Read the per-GPU table from disk, or return an empty default.

    Defensive: a corrupt JSON file (manual edit, partial write) is treated
    the same as a missing file — return an empty table so the skill keeps
    running with k=1.0. The next successful update will overwrite it.
    """
    path = calibration_path(gpu_name)
    if not os.path.isfile(path):
        return _empty_table(gpu_name)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_table(gpu_name)
    # Defensive: ensure required keys are present.
    data.setdefault("gpu_name", gpu_name)
    data.setdefault("k_values", {})
    data.setdefault("history", [])
    return data


def save_table(gpu_name: str, table: dict) -> None:
    """Atomically write the table — tmp file + rename so a partial write
    can never corrupt the on-disk copy."""
    path = calibration_path(gpu_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(table, f, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ── lookup / update logic ────────────────────────────────────────────────────


def lookup_k(table: dict, model_type: str) -> float:
    """Resolve the correction factor for (gpu, model_type).

    Fallback chain (§2.6.5):
        (gpu, model_type)  →  (gpu, *)  →  1.0
    """
    k_values = table.get("k_values") or {}
    if model_type in k_values:
        return float(k_values[model_type])
    if WILDCARD_KEY in k_values:
        return float(k_values[WILDCARD_KEY])
    return 1.0


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_entry(
    gpu_name: str,
    model_type: str,
    seg_size: int,
    batch_size: int,
    total_steps: int,
    warmup_ms_per_step: float,
    actual_ms_per_step: float,
    estimated_minutes: float,
    actual_minutes: float,
) -> dict:
    """Build the canonical history-entry dict from a completed run."""
    ratio = actual_ms_per_step / warmup_ms_per_step if warmup_ms_per_step > 0 else 1.0
    return {
        "gpu_name": gpu_name,
        "model_type": model_type,
        "seg_size": int(seg_size),
        "batch_size": int(batch_size),
        "total_steps": int(total_steps),
        "warmup_ms_per_step": round(float(warmup_ms_per_step), 4),
        "actual_ms_per_step": round(float(actual_ms_per_step), 4),
        "ratio": round(float(ratio), 4),
        "estimated_minutes": round(float(estimated_minutes), 4),
        "actual_minutes": round(float(actual_minutes), 4),
        "estimate_violated": actual_minutes > estimated_minutes,
        "timestamp": _now_iso(),
    }


def update_k(table: dict, entry: dict) -> dict:
    """Apply the asymmetric EMA from §2.6.5 to ``table`` in place.

    α_up is used when the prior estimate was too low (under-prediction),
    so we correct toward safety quickly. α_down is used when the prior
    estimate was too high (over-prediction), so we drift toward optimism
    slowly. The new ``k`` is clipped to ``[K_MIN, K_MAX]``.

    Returns the same table dict (mutated). The history list gains the
    entry. Caller is responsible for ``save_table``.
    """
    model_type = entry["model_type"]
    ratio = float(entry["ratio"])
    violated = bool(entry["estimate_violated"])

    k_values = table.setdefault("k_values", {})
    k_old = float(k_values.get(model_type, lookup_k(table, model_type)))

    alpha = ALPHA_UP if violated else ALPHA_DOWN
    k_new = alpha * ratio + (1.0 - alpha) * k_old
    k_new = max(K_MIN, min(K_MAX, k_new))

    k_values[model_type] = round(k_new, 4)
    table.setdefault("history", []).append(entry)
    return table


def detect_drift(table: dict, last_n: int = 3) -> str | None:
    """Warning string when the last ``last_n`` history entries all violated
    their estimates — a signal the EMA can't track smoothly (driver upgrade,
    partition switch, neighboring job hogging the node). User intervention
    expected: clear the calibration file or investigate the environment.

    Returns None when there are fewer than ``last_n`` entries or when the
    last ``last_n`` entries are not all violations.
    """
    history = table.get("history") or []
    if len(history) < last_n:
        return None
    last = history[-last_n:]
    if not all(bool(e.get("estimate_violated")) for e in last):
        return None
    gpu = table.get("gpu_name", "?")
    model_types = sorted({e.get("model_type", "?") for e in last})
    return (
        f"[time-calibration drift] last {last_n} runs on '{gpu}' all "
        f"violated their wall-time estimate (model_types={model_types}). "
        f"Consider clearing the calibration file or investigating the "
        f"environment (driver upgrade, shared-node contention, partition "
        f"change)."
    )
