"""Typed fingerprint-history restore from chain interpretation digests.

CB5-b suite (``pr3_healthgate_feedback.md`` §3.8/§11-CB5). Pins the
digest-only, one-directional flow's FIRST leg: latest digest → typed
``RestoredState.collapse_fingerprint_history``, with latest-wins
semantics, legacy default, file-level soft-fail, and the data-level
loud-failure contract (corrupted entries raise, naming iter + model —
deterministic policy data is never silently dropped).
"""

import json
import os

import pytest

from agent.schemas.health_feedback import CollapseFingerprintHistoryEntry
from core.committed_digests import read_committed_digests
from core.resume import project_fingerprint_history


# Step 09.5a C1 — the four carried-state loaders became PURE projections over
# one shared committed-digest read (core/committed_digests.py). These shims keep
# every assertion below unchanged while exercising the real production
# composition: one read, then the projection under test.
def load_latest_fingerprint_history(workspace, current_iter, committed_iters):
    return project_fingerprint_history(
        read_committed_digests(workspace, current_iter, committed_iters)
    )


SIG = "output_diversity_blocking:n_unique_int8_values=1"


def _entry_dict(sig=SIG, iteration=3, count=2):
    return {
        "signature": sig,
        "check_name": "output_diversity_blocking",
        "metrics": {"n_unique_int8_values": 1},
        "human_readable": "collapsed",
        "occurrences": [
            {"iteration": iteration, "count": count, "source_exp_ids": ["m_iter_003_001"]}
        ],
    }


def _write_digest(workspace, iter_idx, payload):
    run_name = f"iter_{iter_idx:03d}"
    d = os.path.join(str(workspace), run_name, f"iteration_{iter_idx:03d}")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"interpretation_{run_name}.json"), "w") as f:
        json.dump(payload, f)


def test_round_trip_restores_typed_entries(tmp_path):
    _write_digest(tmp_path, 1, {"collapse_fingerprint_history": {"m": [_entry_dict()]}})
    history = load_latest_fingerprint_history(str(tmp_path), 2, [1])
    [entry] = history["m"]
    assert isinstance(entry, CollapseFingerprintHistoryEntry)  # typed, not raw dict
    assert entry.signature == SIG
    assert [(o.iteration, o.count) for o in entry.occurrences] == [(3, 2)]


def test_latest_digest_wins(tmp_path):
    """Each digest is already the merged post-retention history — the
    latest replaces, never concatenates (double-merge would resurrect
    expired buckets)."""
    _write_digest(tmp_path, 1, {"collapse_fingerprint_history": {"m": [_entry_dict(count=9)]}})
    _write_digest(tmp_path, 2, {"collapse_fingerprint_history": {"m": [_entry_dict(count=1)]}})
    history = load_latest_fingerprint_history(str(tmp_path), 3, [1, 2])
    assert history["m"][0].occurrences[0].count == 1


def test_legacy_digest_without_field_resolves_empty(tmp_path):
    _write_digest(tmp_path, 1, {"key_findings": ["old digest"]})
    assert load_latest_fingerprint_history(str(tmp_path), 2, [1]) == {}


def test_missing_digest_file_soft_fails_with_warning(tmp_path):
    with pytest.warns(UserWarning, match="fingerprint-history"):
        assert load_latest_fingerprint_history(str(tmp_path), 2, [1]) == {}


def test_corrupted_entry_raises_naming_iter_and_model(tmp_path):
    """Data-level corruption is LOUD (design §11-CB5 failure contract):
    deterministic gate evidence is never dropped silently."""
    _write_digest(tmp_path, 1, {"collapse_fingerprint_history": {"m": [{"signature": ""}]}})
    with pytest.raises(ValueError, match=r"iter 001.*'m'"):
        load_latest_fingerprint_history(str(tmp_path), 2, [1])


def test_first_iter_short_circuits(tmp_path):
    assert load_latest_fingerprint_history(str(tmp_path), 1, []) == {}
