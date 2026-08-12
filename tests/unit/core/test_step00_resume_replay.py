"""Step-00 RES-1 — operational replay from a COMMITTED workspace fixture.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.3 / §15.1 (roadmap steps 09/10 A-surfaces).

This is a REWRITTEN-HEADER replay (design §13.3, review F10): production
manifests carry absolute ``output_path`` values that
``restore_prior_state`` requires to exist, so the committed fixture
(``fixtures/step00_replay_workspace/``) stores RELATIVE placeholders; the
test stages it into ``tmp_path``, rewrites the header paths, inserts the
``run_output_sha256`` (consistent with the integrity check), copies the
tracked ``pe_wavenet_delta`` plugin into ``plugins/iter_001/``, then runs
the REAL ``restore_prior_state`` loader chain. Before Step 00 no test
consumed a committed on-disk workspace (all resume workspaces were
synthesized under ``tmp_path``).

RES-2 (tamper → ``ReplayIntegrityError``) and RES-3 (behavioral floor)
are REGISTERED existing suites (``test_resume_incumbent.py``,
``test_resume*.py``) — not duplicated here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from core.resume import restore_prior_state

FIXTURE_WS = Path(__file__).parent / "fixtures" / "step00_replay_workspace"
TRACKED_PLUGIN = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "pseudo_data"
    / "plugins"
    / "pe_wavenet_delta.py"
)
MODEL = "pe_wavenet_delta"


def stage_workspace(tmp_path, *, with_plugin: bool = True, with_digest: bool = True) -> Path:
    ws = tmp_path / "ws"
    shutil.copytree(FIXTURE_WS, ws)
    run_output = ws / "iter_001" / "iteration_001" / MODEL / "run_output_iter_001.json"
    manifest_path = ws / "iter_001" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["iteration_dir"] = str(ws / "iter_001")
    manifest["output_path"] = str(run_output)
    manifest["run_output_sha256"] = hashlib.sha256(run_output.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if with_plugin:
        plugin_dir = ws / "plugins" / "iter_001"
        plugin_dir.mkdir(parents=True)
        shutil.copy(TRACKED_PLUGIN, plugin_dir / f"{MODEL}.py")
    if not with_digest:
        (ws / "iter_001" / "iteration_001" / "interpretation_iter_001.json").unlink()
    return ws


class TestRES1CommittedReplay:
    def test_full_replay_projection(self, tmp_path):
        ws = stage_workspace(tmp_path)
        state = restore_prior_state(str(ws), 2, [])
        assert state.committed_iters == [1]
        assert state.resolved_source_paths == [
            str(ws / "iter_001" / "iteration_001" / MODEL / "run_output_iter_001.json")
        ]
        assert state.restored_plugins == [MODEL]
        # The loader parses vocab entries into typed VocabEntry objects.
        assert [v.name for v in state.runtime_vocab] == ["dilated_causal_conv"]
        assert state.accumulated_key_findings == ["step00 replay fixture finding"]
        assert state.model_knowledge_cache == {
            MODEL: {"key_findings": ["cached fixture finding"], "bottlenecks": []}
        }
        assert state.collapse_fingerprint_history == {}
        assert state.previous_proposal_data == {
            "model_name": MODEL,
            "motivation": "step00 replay fixture proposal",
        }
        # No per-record evidence in the minimal run_output → no chain
        # incumbents restored; the loader must degrade, not invent.
        assert state.chain_best_valid_formal_score is None
        assert state.chain_best_trial_score is None

    def test_degradation_ladder_missing_optionals(self, tmp_path):
        """The optional files are INDEPENDENTLY degradable (audit C):
        missing plugin → UserWarning + empty; missing digest → warning +
        empty carry-over. Neither aborts the replay."""
        ws = stage_workspace(tmp_path, with_plugin=False, with_digest=False)
        with pytest.warns(UserWarning):
            state = restore_prior_state(str(ws), 2, [])
        assert state.committed_iters == [1]
        assert state.restored_plugins == []
        assert state.runtime_vocab == []
        assert state.accumulated_key_findings == []
        assert state.model_knowledge_cache == {}
