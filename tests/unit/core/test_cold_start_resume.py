"""Cold-start resume / iteration-1 -> iteration-2 restore tests. No LLM, no GPU.

Uses real (test-fixture) manifests + a minimal valid HyperparamTuningOutput —
the PRODUCT code never fabricates history; these are legitimate test fixtures
that exercise restore_prior_state and the auto-resume next-iter computation.
"""

import json
from pathlib import Path

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.resume import restore_prior_state
from scripts.inspect_run_state import compute_next_iter


def _commit_iter1(ws: Path) -> str:
    """Write a real completed iter_001 (run_output + manifest). Returns output path."""
    out = HyperparamTuningOutput(
        run_name="iter_001",
        model_type="wavenet",
        file_index=6,
        status="completed",
        completed_rounds=1,
        total_attempts=1,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:10:00Z",
    )
    iterdir = ws / "iter_001"
    iterdir.mkdir(parents=True)
    out_path = iterdir / "run_output_iter_001_agent.json"
    out_path.write_text(out.model_dump_json())
    (iterdir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "iteration_dir": str(iterdir),
                "output_path": str(out_path),
                "model_name": "wavenet",
                "best_score": 0.5,
            }
        )
    )
    return str(out_path)


class TestColdStartResume:
    def test_iter1_no_seeds_is_cold(self, tmp_path):
        st = restore_prior_state(str(tmp_path), current_iter=1, seed_paths=[])
        assert st.resolved_source_paths == []
        assert st.committed_iters == []

    def test_iter2_restores_committed_iter1_as_real_history(self, tmp_path):
        out_path = _commit_iter1(tmp_path)
        st = restore_prior_state(str(tmp_path), current_iter=2, seed_paths=[])
        assert st.resolved_source_paths == [out_path]
        assert st.committed_iters == [1]

    def test_seeds_plus_resume_no_duplicate_and_history_preserved(self, tmp_path):
        out_path = _commit_iter1(tmp_path)
        seed = str(tmp_path / "seed.json")
        st = restore_prior_state(str(tmp_path), current_iter=2, seed_paths=[seed])
        # seeds prepended, committed iter output appended, no duplication
        assert st.resolved_source_paths == [seed, out_path]
        assert st.committed_iters == [1]

    def test_empty_seeds_do_not_erase_committed_history(self, tmp_path):
        out_path = _commit_iter1(tmp_path)
        st = restore_prior_state(str(tmp_path), current_iter=2, seed_paths=[])
        assert out_path in st.resolved_source_paths


class TestAutoResumeNextIter:
    def test_empty_workspace_reruns_iter1_cold(self):
        # Interrupted before iter-1 commit → no reports → next iter is 1 (cold).
        assert compute_next_iter([], gap=None) == 1
