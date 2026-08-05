"""Unit tests for V19 PR 1 P1-C2 — chain-incumbent reconstruction in
``core/resume.py`` (design: docs/design/v19_priorities/pr1_chain_incumbents.md
§3.3 commit-time validity, §3.6 replay integrity).

Fixtures build real chain workspaces on disk: ``iter_NNN/manifest.json``
plus schema-valid ``run_output_iter_NNN.json`` files, exactly as the
chain runner commits them. No LLM, no training, no repo-policy reads.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib

import pytest

import core.resume as resume
from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.resume import ReplayIntegrityError, restore_prior_state

# ---------------------------------------------------------------------------
# Workspace builders
# ---------------------------------------------------------------------------

_BLOCKING_IDS = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)


def _passing_verdicts() -> list[dict]:
    return [
        {
            "gate_name": gate_id,
            "execution_status": "passed",
            "check_passed": True,
            "would_invalidate_under_production_policy": False,
            "resolved_action": "continue",
        }
        for gate_id in _BLOCKING_IDS
    ]


def _record(
    exp_id: str,
    score: float | None,
    *,
    is_trial: bool = False,
    status: str = "success",
    logical_round: int | None = None,
    waiver: bool | None = False,
    verdicts: list[dict] | None = None,
    eval_fields: bool = True,
) -> dict:
    """One schema-valid ExperimentRecord dict.

    ``waiver=False`` stamps ``health_gate_enabled=False`` (DS5 disabled-mode
    waiver → commit-time VALID without any policy artifact). ``waiver=None``
    leaves the stamp absent (legacy) so validity depends on ``verdicts`` +
    the workspace's effective policy.
    """
    rec: dict = {
        "exp_id": exp_id,
        "status": status,
        "model_type": "punet",
        "timestamp": "2026-07-27 00:00:00",
        "params": {},
        "logical_round": logical_round,
        "denoising_score": score,
        "health_gate_results": verdicts or [],
    }
    if waiver is False:
        rec["health_gate_enabled"] = False
    if is_trial:
        rec["is_trial"] = True
        rec["memory"] = {
            "expert_advice_followed": "n/a (test fixture)",
            "hypothesis": "n/a (test fixture)",
            "time_mode": "trial",
        }
        if eval_fields:
            rec["trial_strategy"] = "snapshot"
            rec["eval_strategy"] = "snapshot"
            rec["eval_portion"] = 0.1
            rec["train_portion"] = 0.1
            rec["trial_portion"] = 0.1
    return rec


def _write_iter(
    workspace: str,
    iter_idx: int,
    records: list[dict],
    *,
    best_valid_formal_score: float | None = None,
    best_valid_formal_exp_id: str | None = None,
    manifest_extra: dict | None = None,
    with_hash: bool = True,
    health_config_sha256: str | None = None,
    manifest_status: str = "completed",
) -> str:
    """Write one committed iteration (manifest + run_output). Returns the
    run_output path."""
    run_name = f"iter_{iter_idx:03d}"
    iter_dir = os.path.join(workspace, run_name)
    model_dir = os.path.join(iter_dir, f"iteration_{iter_idx:03d}", "punet")
    os.makedirs(model_dir, exist_ok=True)

    if manifest_status == "no_records":
        manifest = {"status": "no_records", "iteration_dir": iter_dir, "output_path": None}
        with open(os.path.join(iter_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f)
        return ""

    output = HyperparamTuningOutput(
        run_name=run_name,
        model_type="punet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        all_records=records,
        started_at="2026-07-27 00:00:00",
        finished_at="2026-07-27 00:00:01",
        best_valid_formal_denoising_score=best_valid_formal_score,
        best_valid_formal_exp_id=best_valid_formal_exp_id,
        health_config_sha256=health_config_sha256,
    )
    output_path = os.path.join(model_dir, f"run_output_{run_name}.json")
    with open(output_path, "w") as f:
        f.write(output.model_dump_json())

    manifest = {
        "status": "completed",
        "iteration_dir": iter_dir,
        "output_path": output_path,
        "model_name": "punet",
        "best_valid_formal_score": best_valid_formal_score,
    }
    if with_hash:
        manifest["run_output_sha256"] = hashlib.sha256(open(output_path, "rb").read()).hexdigest()
    if manifest_extra:
        manifest.update(manifest_extra)
    with open(os.path.join(iter_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f)
    return output_path


def _restore(workspace: str, current_iter: int):
    return restore_prior_state(workspace, current_iter, seed_paths=[])


# ---------------------------------------------------------------------------
# Committed-fields fast path + provenance
# ---------------------------------------------------------------------------


def test_formal_incumbent_from_committed_fields(tmp_path, capsys):
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("f1", 1.2, logical_round=3)],
        best_valid_formal_score=1.2,
        best_valid_formal_exp_id="f1",
    )
    _write_iter(
        ws,
        2,
        [_record("f2", 0.8, logical_round=3)],
        best_valid_formal_score=0.8,
        best_valid_formal_exp_id="f2",
    )
    state = _restore(ws, 3)
    assert state.chain_best_valid_formal_score == 1.2
    prov = state.chain_best_valid_formal_provenance
    assert prov["iter_idx"] == 1
    assert prov["exp_id"] == "f1"
    assert prov["round_index"] == 3
    assert prov["round_provenance"] == "persisted"
    assert prov["validity_basis"] == "committed_fields"
    assert prov["artifact_verified"] is True
    out = capsys.readouterr().out
    assert "incumbent carry-over: score=1.2000 iter=001" in out
    assert "verified=true" in out


def test_trial_only_iter_yields_trial_incumbent_only(tmp_path, capsys):
    ws = str(tmp_path)
    _write_iter(ws, 1, [_record("t1", 0.5, is_trial=True, logical_round=1)])
    state = _restore(ws, 2)
    assert state.chain_best_valid_formal_score is None
    assert state.chain_best_trial_score == 0.5
    prov = state.chain_best_trial_provenance
    assert prov["eval_strategy"] == "snapshot"
    assert prov["eval_portion"] == 0.1
    assert prov["train_portion"] == 0.1
    assert prov["round_index"] == 1
    out = capsys.readouterr().out
    assert "incumbent carry-over: none" in out
    assert "trial-incumbent carry-over: score=0.5000" in out


# ---------------------------------------------------------------------------
# Summary-vs-source validation negatives (each → excluded + warning)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    ["null_exp_id", "missing_record", "score_mismatch", "trial_source", "manifest_conflict"],
)
def test_committed_summary_negatives_excluded(tmp_path, capsys, case):
    ws = str(tmp_path)
    kwargs: dict = {
        "best_valid_formal_score": 1.2,
        "best_valid_formal_exp_id": "f1",
    }
    records = [_record("f1", 1.2)]
    if case == "null_exp_id":
        kwargs["best_valid_formal_exp_id"] = None
    elif case == "missing_record":
        records = [_record("other", 1.2)]
    elif case == "score_mismatch":
        records = [_record("f1", 1.3)]
    elif case == "trial_source":
        records = [_record("f1", 1.2, is_trial=True)]
    elif case == "manifest_conflict":
        kwargs["manifest_extra"] = {"best_valid_formal_score": 0.9}
    _write_iter(ws, 1, records, **kwargs)
    state = _restore(ws, 2)
    assert state.chain_best_valid_formal_score is None
    assert "SUMMARY-MISMATCH" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Round-provenance rules — never fabricated from position
# ---------------------------------------------------------------------------


def test_round_index_null_when_not_persisted(tmp_path):
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("f1", 1.0, logical_round=None)],
        best_valid_formal_score=1.0,
        best_valid_formal_exp_id="f1",
    )
    state = _restore(ws, 2)
    prov = state.chain_best_valid_formal_provenance
    assert prov["round_index"] is None
    assert prov["round_provenance"] == "legacy_unknown"


# ---------------------------------------------------------------------------
# Walk semantics: no_records, ties
# ---------------------------------------------------------------------------


def test_no_records_iter_contributes_nothing(tmp_path):
    ws = str(tmp_path)
    _write_iter(ws, 1, [], manifest_status="no_records")
    _write_iter(
        ws,
        2,
        [_record("f2", 0.7)],
        best_valid_formal_score=0.7,
        best_valid_formal_exp_id="f2",
    )
    state = _restore(ws, 3)
    assert state.chain_best_valid_formal_score == 0.7
    assert state.chain_best_valid_formal_provenance["iter_idx"] == 2


def test_tie_earliest_iteration_wins(tmp_path):
    ws = str(tmp_path)
    for idx in (1, 2):
        _write_iter(
            ws,
            idx,
            [_record(f"f{idx}", 1.0)],
            best_valid_formal_score=1.0,
            best_valid_formal_exp_id=f"f{idx}",
        )
    state = _restore(ws, 3)
    assert state.chain_best_valid_formal_provenance["iter_idx"] == 1


def test_same_iter_tie_lexicographic_exp_id(tmp_path):
    ws = str(tmp_path)
    # Verdict path (no committed fields): two equal-scoring valid formals.
    _write_iter(ws, 1, [_record("b_exp", 1.0), _record("a_exp", 1.0)])
    state = _restore(ws, 2)
    assert state.chain_best_valid_formal_score == 1.0
    assert state.chain_best_valid_formal_provenance["exp_id"] == "a_exp"
    assert state.chain_best_valid_formal_provenance["validity_basis"] == "persisted_verdicts"


# ---------------------------------------------------------------------------
# Commit-time validity: verdict re-derivation, UNKNOWN exclusion,
# repo-policy independence
# ---------------------------------------------------------------------------


def test_legacy_rederivation_with_effective_policy(tmp_path):
    """No committed best_valid_formal_* fields; records carry persisted
    verdicts; the workspace's materialized effective policy (sha-matching
    the stamp) judges gate-set completeness."""
    from execute_tools.health_checks.config import materialize_effective_config

    ws = str(tmp_path)
    model_dir = os.path.join(ws, "iter_001", "iteration_001", "punet")
    os.makedirs(model_dir, exist_ok=True)
    _, sha = materialize_effective_config(None, None, model_dir)
    _write_iter(
        ws,
        1,
        [_record("f1", 0.9, waiver=None, verdicts=_passing_verdicts(), logical_round=2)],
        health_config_sha256=sha,
    )
    state = _restore(ws, 2)
    assert state.chain_best_valid_formal_score == 0.9
    prov = state.chain_best_valid_formal_provenance
    assert prov["validity_basis"] == "persisted_verdicts"
    assert prov["health_config_sha256"] == sha


def test_unestablishable_commit_time_excluded(tmp_path):
    """Verdicts present but NO effective-policy artifact matching the
    stamp → completeness not judgeable → UNKNOWN → excluded."""
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("f1", 0.9, waiver=None, verdicts=_passing_verdicts())],
        health_config_sha256="deadbeef" * 8,
    )
    state = _restore(ws, 2)
    assert state.chain_best_valid_formal_score is None


def test_repo_policy_never_consulted(tmp_path, monkeypatch):
    """Decision state must never read the repo-current shipped config.

    Reconstruction must resolve policy from the iteration's own sha-pinned
    effective config, never from whatever the repository happens to ship
    today — otherwise replaying an old chain after a config change silently
    re-judges its history.

    **This test was vacuous before the role hotfix.** It monkeypatched the
    resolver and asserted on its argument, but the fixture never stamped a
    `health_config_sha256` and never materialized an effective config, so
    `_commit_time_gate_ids` returned None on the missing-stamp branch and
    the guard was never reached. It passed for years without exercising the
    thing it names. The `calls` assertion below is what makes that
    impossible to repeat.
    """
    from execute_tools.health_checks.config import materialize_effective_config

    real = resume.resolve_scientific_gate_ids
    repo_config = str(
        pathlib.Path(resume.__file__).resolve().parents[1] / "configs" / "health_checks.yaml"
    )
    calls: list[str] = []

    def guarded(config_path):
        calls.append(config_path)
        assert os.path.realpath(config_path) != os.path.realpath(repo_config), (
            f"reconstruction resolved policy from the repo-current shipped "
            f"config ({config_path}) instead of the iteration's effective one"
        )
        return real(config_path)

    monkeypatch.setattr(resume, "resolve_scientific_gate_ids", guarded)

    ws = str(tmp_path)
    model_dir = os.path.join(ws, "iter_001", "iteration_001", "punet")
    os.makedirs(model_dir, exist_ok=True)
    _, sha = materialize_effective_config(None, None, model_dir)
    _write_iter(
        ws,
        1,
        [_record("f1", 0.9, waiver=None, verdicts=_passing_verdicts(), logical_round=2)],
        health_config_sha256=sha,
    )

    state = _restore(ws, 2)

    assert state.chain_best_valid_formal_score == 0.9
    assert calls, (
        "the guard was never invoked — this test is not reaching "
        "resolve_scientific_gate_ids and proves nothing"
    )


def test_phantom_collapsed_record_never_incumbent(tmp_path):
    ws = str(tmp_path)
    _write_iter(ws, 1, [_record("ph", 5.5762667, status="failed_mode_collapse")])
    state = _restore(ws, 2)
    assert state.chain_best_valid_formal_score is None
    assert state.chain_best_trial_score is None


# ---------------------------------------------------------------------------
# Replay integrity (rev 3: STOP on mismatch; legacy visible-unverified)
# ---------------------------------------------------------------------------


def test_tampered_artifact_raises_replay_integrity(tmp_path):
    ws = str(tmp_path)
    output_path = _write_iter(
        ws,
        1,
        [_record("f1", 1.2)],
        best_valid_formal_score=1.2,
        best_valid_formal_exp_id="f1",
    )
    expected = hashlib.sha256(open(output_path, "rb").read()).hexdigest()
    with open(output_path, "a") as f:
        f.write("\n")
    actual = hashlib.sha256(open(output_path, "rb").read()).hexdigest()

    with pytest.raises(ReplayIntegrityError) as exc:
        _restore(ws, 2)
    msg = str(exc.value)
    assert "REPLAY-INTEGRITY" in msg
    assert output_path in msg
    assert expected[:16] in msg
    assert actual[:16] in msg


def test_legacy_manifest_without_hash_visibly_unverified(tmp_path, capsys):
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("f1", 1.2)],
        best_valid_formal_score=1.2,
        best_valid_formal_exp_id="f1",
        with_hash=False,
    )
    state = _restore(ws, 2)
    assert state.chain_best_valid_formal_score == 1.2
    assert state.chain_best_valid_formal_provenance["artifact_verified"] is False
    assert "verified=false" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Degraded tolerance + determinism
# ---------------------------------------------------------------------------


def test_degraded_output_without_bests_tolerated(tmp_path):
    ws = str(tmp_path)
    _write_iter(ws, 1, [])  # completed, empty records, all bests None
    state = _restore(ws, 2)
    assert state.chain_best_valid_formal_score is None
    assert state.chain_best_trial_score is None
    assert state.committed_iters == [1]


def test_reconstruction_is_deterministic(tmp_path):
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("f1", 1.2, logical_round=2), _record("t1", 0.4, is_trial=True)],
        best_valid_formal_score=1.2,
        best_valid_formal_exp_id="f1",
    )
    a = _restore(ws, 2)
    b = _restore(ws, 2)
    assert a.chain_best_valid_formal_score == b.chain_best_valid_formal_score
    assert a.chain_best_valid_formal_provenance == b.chain_best_valid_formal_provenance
    assert a.chain_best_trial_score == b.chain_best_trial_score
    assert a.chain_best_trial_provenance == b.chain_best_trial_provenance
