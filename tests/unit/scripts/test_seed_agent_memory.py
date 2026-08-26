"""S2 / U5 — ``run_comparison.seed_agent_memory`` goes through the recorder.

The defect: the seed used to write ``summary_<run>.json`` directly, putting
a record in the derived VIEW that was in no history. Once the view is a
projection of the canonical log, the tuner's next save rebuilds the view
from the log and the baseline vanishes. Each test states which half of
that it guards.
"""

from __future__ import annotations

import json
import os

from core.record_log import RECORD_LOG_BASENAME
from core.sandbox_executor import LocalRecorder, sandbox_records_dir
from scripts.run_comparison import seed_agent_memory

RUN = "v1_agent"
BASELINE = {"exp_id": "baseline_punet_1700000000", "status": "success", "denoising_score": 1.0}


def _tuner_recorder(ws: str) -> LocalRecorder:
    """Exactly how ``TidmadSandbox(workspace=ws, run_name=RUN)`` builds its recorder."""
    base = os.path.abspath(ws)
    return LocalRecorder(sandbox_records_dir(base), os.path.join(base, f"summary_{RUN}.json"), RUN)


def test_the_seed_is_index_zero_of_what_the_tuner_reads_on_a_fresh_workspace(tmp_path):
    """Ordering preserved: the production launch seeds a fresh workspace,
    so the baseline is the first canonical record and index 0 of the view
    — where ``existing.insert(0, ...)`` used to put it."""
    ws = str(tmp_path / "agent")
    seed_agent_memory(BASELINE, ws, RUN)

    tuner = _tuner_recorder(ws)
    assert tuner.get_summary() == [BASELINE]
    tuner.save_record({"exp_id": f"punet_{RUN}_001", "status": "success"})
    view = json.loads((tmp_path / "agent" / f"summary_{RUN}.json").read_text(encoding="utf-8"))
    assert [r["exp_id"] for r in view] == [BASELINE["exp_id"], f"punet_{RUN}_001"]


def test_a_seed_into_a_workspace_with_history_survives_the_tuner_s_next_save(tmp_path):
    """THE DEFECT. With the old direct summary write, the tuner's first
    ``save_record`` rebuilt the view from a log that never held the
    baseline. Fails if the baseline is absent after the next save."""
    ws = str(tmp_path / "agent")
    tuner = _tuner_recorder(ws)
    tuner.save_record({"exp_id": f"punet_{RUN}_001", "status": "success"})

    seed_agent_memory(BASELINE, ws, RUN)
    tuner.save_record({"exp_id": f"punet_{RUN}_002", "status": "success"})

    ids = [r["exp_id"] for r in _tuner_recorder(ws).get_summary()]
    assert ids == [f"punet_{RUN}_001", BASELINE["exp_id"], f"punet_{RUN}_002"]
    log = tmp_path / "agent" / "records" / RUN / RECORD_LOG_BASENAME
    assert len(log.read_text(encoding="utf-8").splitlines()) == 3


def test_reseeding_is_a_noop(tmp_path):
    ws = str(tmp_path / "agent")
    seed_agent_memory(BASELINE, ws, RUN)
    seed_agent_memory(BASELINE, ws, RUN)
    assert _tuner_recorder(ws).get_summary() == [BASELINE]
    log = tmp_path / "agent" / "records" / RUN / RECORD_LOG_BASENAME
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
