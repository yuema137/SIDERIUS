"""Unit tests for ``_resolve_chain_run_id`` in
``sdsc_submission_scripts/run_one_iteration.py``.

The chain runner invokes one fresh subprocess per iteration; without a
sidecar, every iter would generate its own run_id (different pid +
timestamp) and the bridge's §1.4.1 immutability check would abort
iter ≥ 2. The sidecar at ``{workspace}/.token_run_id`` carries the
value forward — iter 1 generates and writes it; later iters read it
back unchanged.

These tests pin the contract:
  - fresh workspace → new id with shape ``{name}-{utc8}-{pid}``
  - second call on same workspace → identical id (idempotent re-read)
  - sidecar file content matches the returned id
"""

from __future__ import annotations

import os
import re

from sdsc_submission_scripts.run_one_iteration import _resolve_chain_run_id


_ID_SHAPE = re.compile(r"^[A-Za-z0-9_]+-\d{8}T\d{6}-\d+$")


def test_fresh_workspace_generates_id_with_expected_shape(tmp_path):
    """A workspace without a sidecar gets a freshly-minted run_id whose
    shape matches ``{run_name}-{YYYYMMDDThhmmss}-{pid}`` — the same
    format ``run_exploration_adaptive._generate_run_id`` produces."""
    workspace = str(tmp_path)
    run_name = "explore_v12_test"

    rid = _resolve_chain_run_id(workspace, run_name)

    assert _ID_SHAPE.match(rid), f"unexpected id shape: {rid!r}"
    assert rid.startswith(f"{run_name}-"), (
        f"id should start with run_name prefix, got {rid!r}"
    )
    sidecar = os.path.join(workspace, ".token_run_id")
    assert os.path.exists(sidecar), "sidecar must be written"
    assert open(sidecar, encoding="utf-8").read().strip() == rid


def test_second_call_returns_same_id(tmp_path):
    """The whole point of the sidecar — calling twice on the same
    workspace must return bit-identical strings, even if the second call
    happens far enough later that the timestamp would differ."""
    workspace = str(tmp_path)
    run_name = "exploit_v12_test"

    first = _resolve_chain_run_id(workspace, run_name)
    second = _resolve_chain_run_id(workspace, run_name)

    assert first == second


def test_run_name_in_subsequent_call_is_ignored(tmp_path):
    """If iter 2 is launched with a different ``--run_name`` (operator
    typo, copy-paste mistake), the sidecar's persisted id must win — we
    never silently re-anchor mid-chain. The bridge would catch a
    re-anchored id with LLMBridgeContextError later, but the sidecar
    layer should not even attempt the mutation."""
    workspace = str(tmp_path)

    first = _resolve_chain_run_id(workspace, "explore_v12_test")
    second = _resolve_chain_run_id(workspace, "wrong_name_typo")

    assert first == second
    assert second.startswith("explore_v12_test-")


def test_empty_sidecar_is_treated_as_missing(tmp_path):
    """Defensive: a zero-byte or whitespace-only sidecar (e.g. a crashed
    iter 1 that opened the file but never wrote) must not freeze the
    chain into an empty id. A fresh id is generated and the sidecar
    overwritten."""
    workspace = str(tmp_path)
    sidecar = os.path.join(workspace, ".token_run_id")
    with open(sidecar, "w", encoding="utf-8") as f:
        f.write("   \n")

    rid = _resolve_chain_run_id(workspace, "explore_v12_test")

    assert _ID_SHAPE.match(rid)
    assert rid.startswith("explore_v12_test-")
    assert open(sidecar, encoding="utf-8").read().strip() == rid


def test_workspace_is_created_if_missing(tmp_path):
    """The runner calls ``_resolve_chain_run_id`` before the iter dir
    is created; the helper must therefore tolerate a not-yet-existing
    workspace and create it (mkdirs(exist_ok=True))."""
    workspace = str(tmp_path / "nested" / "fresh_chain")
    assert not os.path.exists(workspace)

    rid = _resolve_chain_run_id(workspace, "explore_v12_test")

    assert os.path.isdir(workspace)
    assert _ID_SHAPE.match(rid)
