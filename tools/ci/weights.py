"""Measured per-file cost, used to balance shards.

File COUNT is not cost. The 8-shard by-count plan reported an imbalance of
1.004 and still took 654 s, because one file
(``test_step02b_checkpoint_c_live_integration.py``) is 460 s — 36 % of the
suite's 1288 measured test-seconds. Balancing by count cannot see that.

The committed measurements carry their own provenance, including the caveat
that they were taken under undeclared competing load: they are RELATIVE costs
for balancing, never absolute per-test timings.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

WEIGHTS_PATH = Path(__file__).resolve().parent / "weights.json"

#: A file with no measurement costs this much. 1.0 keeps an unmeasured file
#: comparable to a typical fast one rather than free — a new test file must not
#: look weightless and pile onto an already-heavy shard.
DEFAULT_WEIGHT = 1.0


@lru_cache(maxsize=1)
def load_weights(path: Path | None = None) -> dict[str, float]:
    """Measured per-file seconds. Empty when the file is missing.

    Missing measurements are not an error: the planner falls back to
    ``DEFAULT_WEIGHT`` per file, which degrades to by-count balancing.
    """
    target = path or WEIGHTS_PATH
    if not target.is_file():
        return {}
    doc = json.loads(target.read_text(encoding="utf-8"))
    return {k: float(v) for k, v in doc.get("weights", {}).items()}


@lru_cache(maxsize=1)
def load_splits(path: Path | None = None) -> dict[str, dict[str, float]]:
    """Measured per-node seconds for oversized files. Empty when absent.

    Shape: ``{file: {"TestClass::test_name": seconds}}``. Consumed by
    ``plan_shards(splits=...)`` to expand a file atom whose weight exceeds
    ``total/count`` into node-id atoms.
    """
    target = path or WEIGHTS_PATH
    if not target.is_file():
        return {}
    doc = json.loads(target.read_text(encoding="utf-8"))
    return {
        f: {n: float(c) for n, c in nodes.items()} for f, nodes in doc.get("splits", {}).items()
    }


def weight_provenance(path: Path | None = None) -> dict[str, object]:
    """The measurement's own record of how and where it was taken."""
    target = path or WEIGHTS_PATH
    if not target.is_file():
        return {}
    return dict(json.loads(target.read_text(encoding="utf-8")).get("_provenance", {}))
