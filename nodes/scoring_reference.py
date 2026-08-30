"""
Reference-data loader for the per-file score comparison table (Phase 2 of
``docs/aggregated_score_table_awareness.md``).

Reads the 20 raw-baseline per-file JSONs, the 20 ground-truth per-file JSONs,
and their two ``*_anchor_normalized.json`` scalar files into a single frozen
``ReferenceScores`` object. The dataclass carries both the log-space per-file
scores (for populating table rows) and the per-file linear sums + segment
counts (required to recompute grand-mean scalars over a trial-mode subset —
see Decision 14).

The loader is node-side (does disk I/O + module-level caching) per Decision
10 in the design doc. Pure table math — `build_score_table` and
`render_comparison_table` — lives in ``execute_tools/scoring_helpers.py``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from execute_tools.data_paths import legacy_siderius_data_dir
from execute_tools.dataset_config import resolve_dataset_profile


def _fine_indices() -> tuple[int, ...]:
    """File indices the per-file reference artifacts are keyed by.

    Was a module-level ``tuple(range(NUM_FILES))`` evaluated at import, which
    fixed this node to TIDMAD's 20 files no matter what a task declared. It
    is now derived per call from the resolved Dataset Profile, so this node
    and its generator (``scripts/compute_raw_baseline.py``) cannot silently
    disagree about how many files exist.
    """
    return tuple(range(resolve_dataset_profile().partition_count))


_RAW_PER_FILE_FMT = "raw_baseline_score_file_{idx:04d}.json"
_GT_PER_FILE_FMT = "ground_truth_score_file_{idx:04d}.json"
_RAW_SCALAR_FILE = "scalar_anchor_normalized.json"
_GT_SCALAR_FILE = "ceiling_anchor_normalized.json"

_REGEN_HINT = (
    "Regenerate with `python scripts/compute_raw_baseline.py` and "
    "`python scripts/compute_ground_truth.py` (both under the project venv)."
)


# ---------------------------------------------------------------------------
# Immutable reference-data bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceScores:
    """Frozen bundle of on-disk reference data for the score-comparison table.

    Lengths: all six per-file list fields are length 20 and aligned on file
    index. ``raw_scalar_full`` / ``gt_scalar_full`` are the pre-computed
    grand-mean scalars over all 20 fine files — cheap reference values; the
    subset-aware recomputation in ``build_score_table`` reproduces them
    exactly when all 20 files are sampled.
    """

    raw_per_file_log: list[float]
    gt_per_file_log: list[float]
    raw_per_file_linear_sum: list[float]
    raw_per_file_n_segments: list[int]
    gt_per_file_linear_sum: list[float]
    gt_per_file_n_segments: list[int]
    raw_scalar_full: float
    gt_scalar_full: float
    s_max: float


# ---------------------------------------------------------------------------
# Loader (module-level cache)
# ---------------------------------------------------------------------------

_CACHE: ReferenceScores | None = None


def _default_reference_dir(name: str) -> str:
    """Resolve a reference-score directory (``"raw_baseline"`` / ``"ground_truth"``).

    The reference scores are a fixed artifact uniquely determined by the TIDMAD
    data (+ anchor map), so prefer the committed, server-independent copy at
    ``reference_data/{name}`` — resolved from the package location, independent
    of the current working directory. Fall back to ``{SIDERIUS_DATA_DIR}/{name}``
    for machines predating the committed copy.
    """
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    committed = os.path.join(pkg_root, "reference_data", name)
    if os.path.isdir(committed):
        return committed
    return os.path.join(legacy_siderius_data_dir(), name)


def load_reference_scores(
    raw_dir: str | None = None,
    gt_dir: str | None = None,
    *,
    use_cache: bool = True,
) -> ReferenceScores:
    """Return the frozen ``ReferenceScores`` bundle.

    Reads from the committed, server-independent ``reference_data/raw_baseline/``
    and ``reference_data/ground_truth/`` (resolved package-relative) by default,
    falling back to ``{SIDERIUS_DATA_DIR}/...`` on machines predating the
    committed copy. Tests pass explicit directories and set ``use_cache=False``.

    Raises ``FileNotFoundError`` with a regenerate-hint if any of the 42
    expected JSON files (20 raw per-file + raw scalar + 20 gt per-file +
    gt scalar) is missing, or ``KeyError`` if a per-file JSON predates
    Phase 1 and lacks ``linear_sum`` / ``n_segments``.
    """
    global _CACHE
    if use_cache and _CACHE is not None:
        return _CACHE

    raw_dir = raw_dir or _default_reference_dir("raw_baseline")
    gt_dir = gt_dir or _default_reference_dir("ground_truth")

    raw_log: list[float] = []
    gt_log: list[float] = []
    raw_ls: list[float] = []
    raw_ns: list[int] = []
    gt_ls: list[float] = []
    gt_ns: list[int] = []

    for idx in _fine_indices():
        raw_path = os.path.join(raw_dir, _RAW_PER_FILE_FMT.format(idx=idx))
        gt_path = os.path.join(gt_dir, _GT_PER_FILE_FMT.format(idx=idx))
        raw = _read_json(raw_path)
        gt = _read_json(gt_path)

        for field in ("score", "linear_sum", "n_segments"):
            if field not in raw:
                raise KeyError(
                    f"Raw baseline JSON {raw_path} is missing required field "
                    f"'{field}'. {_REGEN_HINT}"
                )
            if field not in gt:
                raise KeyError(
                    f"Ground-truth JSON {gt_path} is missing required field "
                    f"'{field}'. {_REGEN_HINT}"
                )

        raw_log.append(float(raw["score"]))
        gt_log.append(float(gt["score"]))
        raw_ls.append(float(raw["linear_sum"]))
        raw_ns.append(int(raw["n_segments"]))
        gt_ls.append(float(gt["linear_sum"]))
        gt_ns.append(int(gt["n_segments"]))

    raw_scalar_path = os.path.join(raw_dir, _RAW_SCALAR_FILE)
    gt_scalar_path = os.path.join(gt_dir, _GT_SCALAR_FILE)
    raw_scalar_doc = _read_json(raw_scalar_path)
    gt_scalar_doc = _read_json(gt_scalar_path)

    for field in ("scalar_score", "s_max"):
        if field not in raw_scalar_doc:
            raise KeyError(f"Raw scalar file {raw_scalar_path} is missing '{field}'. {_REGEN_HINT}")
        if field not in gt_scalar_doc:
            raise KeyError(f"Ceiling file {gt_scalar_path} is missing '{field}'. {_REGEN_HINT}")

    raw_smax = float(raw_scalar_doc["s_max"])
    gt_smax = float(gt_scalar_doc["s_max"])
    if raw_smax != gt_smax:
        raise ValueError(
            f"s_max mismatch between raw baseline ({raw_smax}) and ground "
            f"truth ({gt_smax}); the two reference sets must share one ruler."
        )

    result = ReferenceScores(
        raw_per_file_log=raw_log,
        gt_per_file_log=gt_log,
        raw_per_file_linear_sum=raw_ls,
        raw_per_file_n_segments=raw_ns,
        gt_per_file_linear_sum=gt_ls,
        gt_per_file_n_segments=gt_ns,
        raw_scalar_full=float(raw_scalar_doc["scalar_score"]),
        gt_scalar_full=float(gt_scalar_doc["scalar_score"]),
        s_max=raw_smax,
    )

    if use_cache:
        _CACHE = result
    return result


def _reset_cache() -> None:
    """Clear the module-level cache. Test-only."""
    global _CACHE
    _CACHE = None


def _read_json(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Reference data file not found: {path}. {_REGEN_HINT}")
    with open(path) as f:
        return json.load(f)
