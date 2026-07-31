"""C12 fix — the probe's wall cap must be a HARD bound.

`max_wall_seconds` was only checked between operations, so one slow CUDA
setup/step/batch ran unbounded; `transformer@8M-ceiling` never returned
at a 900 s and then a 2400 s external kill.

Every test here drives a deterministic fake worker — a short Python
program that sleeps, OOMs, or writes garbage — so the hard-termination
guarantee is proved without a GPU.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from core.runtime_control.probe_subprocess import (
    DEFAULT_GRACE_SECONDS,
    ProbeInfrastructureFailure,
    ProbeWorkerResult,
    ProbeWorkerSpec,
    run_worker,
    worker_result_paths,
)


def _spec(tmp_path: Path) -> ProbeWorkerSpec:
    return ProbeWorkerSpec(
        model_type="fake_candidate",
        device_vram_gb=31.34,
        result_path=str(tmp_path / "probe_result.json"),
    )


def _fake_worker(tmp_path: Path, body: str) -> list[str]:
    """A worker program that ignores SIGTERM unless told otherwise."""
    script = tmp_path / "fake_worker.py"
    script.write_text(body, encoding="utf-8")
    return [sys.executable, str(script)]


STUCK_IN_PHASE = """
import sys, time, signal
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)   # worst case: ignores TERM
Path(r"{progress}").write_text("{phase}")
time.sleep(600)
"""

COMPLETES = """
import json
from pathlib import Path
Path(r"{progress}").write_text("complete")
Path(r"{result}").write_text(json.dumps({{
    "status": "ok", "phase": "complete", "model_identity": "fake_candidate",
    "setup_seconds": 1.0, "train_ms_per_step": 20.0, "train_ms_spread": [19.0, 21.0],
    "inference_ms_per_batch": 8.0, "peak_vram_gb": 2.0,
    "concurrency_identity": "single_candidate_idle"
}}))
"""

REPORTS_OOM = """
import json
from pathlib import Path
Path(r"{result}").write_text(json.dumps({{
    "status": "oom", "phase": "training", "model_identity": "fake_candidate",
    "setup_seconds": 2.0, "peak_vram_gb": 30.9,
    "error": "CUDA out of memory. Tried to allocate 11.31 GiB."
}}))
"""

TERM_GRACEFUL = """
import json, signal, sys, time
from pathlib import Path
def _bye(signum, frame):
    sys.exit(0)
signal.signal(signal.SIGTERM, _bye)
Path(r"{progress}").write_text("training")
time.sleep(600)
"""

MALFORMED = """
from pathlib import Path
Path(r"{result}").write_text("{{not valid json")
"""

CRASHES = """
import sys
sys.exit(3)
"""


def _run(tmp_path, body, *, phase="training", cap=1.0, grace=DEFAULT_GRACE_SECONDS):
    spec = _spec(tmp_path)
    paths = worker_result_paths(spec.result_path)
    command = _fake_worker(
        tmp_path,
        body.format(progress=paths["progress"], result=paths["result"], phase=phase),
    )
    return run_worker(spec, hard_cap_seconds=cap, grace_seconds=grace, command=command)


class TestHardTermination:
    @pytest.mark.parametrize("phase", ["setup", "training", "inference"])
    def test_a_worker_stuck_in_any_phase_is_killed(self, tmp_path, phase):
        """The defect: one slow operation used to run forever."""
        started = time.monotonic()
        outcome = _run(tmp_path, STUCK_IN_PHASE, phase=phase, cap=1.0, grace=0.5)
        elapsed = time.monotonic() - started

        assert outcome.classification == "measured_failure"
        assert outcome.termination.timed_out is True
        assert outcome.termination.phase_at_timeout == phase
        assert outcome.termination.term_sent is True
        assert outcome.termination.kill_sent is True  # it ignored TERM
        assert elapsed < 10.0, "the hard cap must actually bound the wall time"

    def test_no_orphan_process_group_survives(self, tmp_path):
        outcome = _run(tmp_path, STUCK_IN_PHASE, cap=1.0, grace=0.5)
        assert outcome.termination.orphans_remaining is False
        pgid = outcome.termination.worker_pgid
        assert pgid is not None
        with pytest.raises(ProcessLookupError):
            os.killpg(pgid, 0)

    def test_a_cooperative_worker_exits_in_the_grace_period(self, tmp_path):
        outcome = _run(tmp_path, TERM_GRACEFUL, cap=1.0, grace=5.0)
        assert outcome.termination.term_sent is True
        assert outcome.termination.kill_sent is False  # no escalation needed
        assert outcome.classification == "measured_failure"

    def test_the_wall_cap_is_respected_within_bounded_overhead(self, tmp_path):
        cap, grace = 1.0, 0.5
        started = time.monotonic()
        _run(tmp_path, STUCK_IN_PHASE, cap=cap, grace=grace)
        elapsed = time.monotonic() - started
        # cap + grace + process-control overhead, nothing unbounded
        assert elapsed < cap + grace + 5.0

    def test_a_timeout_records_what_it_did(self, tmp_path):
        outcome = _run(tmp_path, STUCK_IN_PHASE, phase="inference", cap=1.0, grace=0.5)
        t = outcome.termination
        assert t.worker_pid and t.worker_pgid
        assert t.hard_cap_seconds == 1.0
        assert t.elapsed_seconds >= 1.0
        assert t.phase_at_timeout == "inference"
        assert "hard cap" in outcome.detail

    def test_no_throughput_is_fabricated_for_an_operation_that_never_returned(self, tmp_path):
        outcome = _run(tmp_path, STUCK_IN_PHASE, cap=1.0, grace=0.5)
        assert outcome.result is None or outcome.result.train_ms_per_step is None


class TestClassification:
    def test_normal_completion(self, tmp_path):
        outcome = _run(tmp_path, COMPLETES, cap=30.0)
        assert outcome.classification == "ok"
        assert outcome.result is not None
        assert outcome.result.train_ms_per_step == 20.0
        assert outcome.termination.timed_out is False
        assert outcome.termination.kill_sent is False

    def test_a_reported_oom_is_a_measured_failure(self, tmp_path):
        outcome = _run(tmp_path, REPORTS_OOM, cap=30.0)
        assert outcome.classification == "measured_failure"
        assert outcome.result is not None
        assert outcome.result.status == "oom"
        assert outcome.result.peak_vram_gb == 30.9  # the measurement survives
        assert "out of memory" in (outcome.result.error or "")

    def test_a_candidate_timeout_is_never_an_infrastructure_abort(self, tmp_path):
        """The operator-approved distinction, asserted directly."""
        outcome = _run(tmp_path, STUCK_IN_PHASE, cap=1.0, grace=0.5)
        assert outcome.classification == "measured_failure"
        assert outcome.classification != "infrastructure_failure"

    def test_a_malformed_result_is_an_infrastructure_failure(self, tmp_path):
        with pytest.raises(ProbeInfrastructureFailure, match="does not validate"):
            _run(tmp_path, MALFORMED, cap=30.0)

    def test_a_worker_that_writes_nothing_is_an_infrastructure_failure(self, tmp_path):
        with pytest.raises(ProbeInfrastructureFailure, match="without writing a result"):
            _run(tmp_path, CRASHES, cap=30.0)

    def test_an_unlaunchable_worker_is_an_infrastructure_failure(self, tmp_path):
        spec = _spec(tmp_path)
        with pytest.raises(ProbeInfrastructureFailure, match="could not launch"):
            run_worker(
                spec,
                hard_cap_seconds=5.0,
                command=["/nonexistent/interpreter", "x"],
            )


class TestWorkerContract:
    def test_the_spec_and_result_travel_as_typed_files(self, tmp_path):
        spec = _spec(tmp_path)
        paths = worker_result_paths(spec.result_path)
        assert paths["spec"].name.endswith(".spec.json")
        assert paths["progress"].name.endswith(".phase")
        _run(tmp_path, COMPLETES, cap=30.0)
        assert paths["spec"].is_file()
        payload = json.loads(paths["spec"].read_text())
        assert payload["model_type"] == "fake_candidate"

    def test_the_result_schema_rejects_impossible_values(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ProbeWorkerResult(status="ok", model_identity="m", train_ms_per_step=-1.0)

    def test_the_worker_writes_no_run_workspace_state(self, tmp_path):
        """Everything the worker produces lives beside its result file."""
        _run(tmp_path, COMPLETES, cap=30.0)
        produced = {p.name for p in tmp_path.iterdir()}
        assert produced <= {
            "fake_worker.py",
            "probe_result.json",
            "probe_result.spec.json",
            "probe_result.phase",
            "probe_result.worker.log",  # diagnostics, beside the result
        }


class TestProductionWorkerWiring:
    def test_the_worker_module_runs_the_same_bounded_probe(self):
        import inspect

        from core.runtime_control import probe_worker_main

        source = inspect.getsource(probe_worker_main)
        assert "run_bounded_probe" in source
        assert "production_probe_executors" in source

    def test_the_worker_reports_usage_on_bad_arguments(self):
        from core.runtime_control.probe_worker_main import main

        assert main([]) == 2

    def test_signal_constants_are_the_expected_ones(self):
        assert signal.SIGTERM == 15
        assert signal.SIGKILL == 9


SELF_SIGNAL = """
import os, signal, sys
from pathlib import Path
{announce}
print("reached {phase}", flush=True)
if signal.{sig} != signal.SIGKILL:   # SIGKILL is uncatchable: no handler to reset
    signal.signal(signal.{sig}, signal.SIG_DFL)
os.kill(os.getpid(), signal.{sig})
"""

SIGNAL_AFTER_RESULT = """
import json, os, signal
from pathlib import Path
Path(r"{{progress}}").write_text("training")
Path(r"{{result}}").write_text(json.dumps({{{{
    "status": "oom", "phase": "training", "model_identity": "fake_candidate",
    "peak_vram_gb": 30.5, "error": "CUDA out of memory."
}}}}))
if signal.{sig} != signal.SIGKILL:
    signal.signal(signal.{sig}, signal.SIG_DFL)
os.kill(os.getpid(), signal.{sig})
"""


class TestSignalTermination:
    """A worker killed by a signal must not be silently called
    infrastructure.

    `transformer@8M-ceiling` died exactly this way — SIGKILL from the host
    OOM killer right after dataset indexing, no traceback, no result. That
    is a REJECT-worthy fact about the candidate; classifying it as
    infrastructure would (via the C9b resolver) ABORT a whole chain
    because one model does not fit.

    The discriminator is evidence, not the bare presence of a signal: the
    signal must be one a candidate can raise, AND the worker must have
    reached candidate work.
    """

    def _signal_worker(self, tmp_path, sig, *, phase="training", announce=True):
        paths = worker_result_paths(_spec(tmp_path).result_path)
        announcement = f'Path(r"{paths["progress"]}").write_text("{phase}")' if announce else ""
        body = SELF_SIGNAL.format(announce=announcement, phase=phase, sig=sig)
        return run_worker(
            _spec(tmp_path),
            hard_cap_seconds=30.0,
            command=_fake_worker(tmp_path, body),
        )

    @pytest.mark.parametrize("sig", ["SIGKILL", "SIGABRT", "SIGSEGV", "SIGBUS"])
    def test_a_candidate_signal_during_candidate_work_is_a_measured_failure(self, tmp_path, sig):
        outcome = self._signal_worker(tmp_path, sig)
        assert outcome.classification == "measured_failure"
        assert outcome.termination.signal_number == getattr(signal, sig)
        assert outcome.termination.signal_name == sig
        assert outcome.termination.phase_at_exit == "training"
        assert outcome.termination.result_present is False
        assert "resource/candidate failure" in outcome.detail

    @pytest.mark.parametrize("phase", ["setup", "training", "inference"])
    def test_every_candidate_work_phase_counts(self, tmp_path, phase):
        """Setup counts: a model that cannot even be built inside the
        machine is a fact about the model."""
        outcome = self._signal_worker(tmp_path, "SIGKILL", phase=phase)
        assert outcome.classification == "measured_failure"
        assert outcome.termination.phase_at_exit == phase

    def test_a_signal_before_any_candidate_work_is_infrastructure(self, tmp_path):
        """Dying during interpreter start-up says nothing about the
        candidate — it never ran."""
        with pytest.raises(ProbeInfrastructureFailure, match="SIGKILL"):
            self._signal_worker(tmp_path, "SIGKILL", announce=False)

    def test_a_non_candidate_signal_is_infrastructure(self, tmp_path):
        """SIGINT is the operator or the environment speaking, not the
        candidate — even mid-training."""
        with pytest.raises(ProbeInfrastructureFailure, match="SIGINT"):
            self._signal_worker(tmp_path, "SIGINT")

    def test_a_result_the_worker_did_write_still_wins(self, tmp_path):
        """Signalled AFTER reporting: the report is the evidence."""
        paths = worker_result_paths(_spec(tmp_path).result_path)
        body = SIGNAL_AFTER_RESULT.format(sig="SIGKILL").format(
            progress=paths["progress"], result=paths["result"]
        )
        outcome = run_worker(
            _spec(tmp_path), hard_cap_seconds=30.0, command=_fake_worker(tmp_path, body)
        )
        assert outcome.classification == "measured_failure"
        assert outcome.result is not None
        assert outcome.result.status == "oom"
        assert outcome.termination.result_present is True

    def test_the_full_diagnostic_set_is_preserved(self, tmp_path):
        outcome = self._signal_worker(tmp_path, "SIGKILL")
        t = outcome.termination
        assert t.exit_code == -signal.SIGKILL
        assert t.signal_number == signal.SIGKILL
        assert t.worker_pid and t.worker_pgid
        assert t.elapsed_seconds > 0.0
        assert t.phase_at_exit == "training"
        assert t.result_present is False
        assert "reached training" in t.worker_log_tail
        assert t.term_sent is False and t.kill_sent is False  # it died on its own
        assert t.orphans_remaining is False

    def test_no_throughput_is_invented_for_a_worker_that_died(self, tmp_path):
        outcome = self._signal_worker(tmp_path, "SIGSEGV")
        assert outcome.result is None


class TestWorkerDiagnostics:
    """A worker that dies without writing a result must not be silent.

    Found during the C12 closeout: `transformer@8M-ceiling` exited in
    setup with no result, and the parent had captured stdout/stderr to a
    PIPE it never drained — so the reason was lost, and an undrained PIPE
    can deadlock a chatty child besides.
    """

    def test_worker_output_is_captured_to_a_file(self, tmp_path):
        body = """
import sys
from pathlib import Path
print("worker said something useful")
print("and something on stderr", file=sys.stderr)
sys.exit(7)
"""
        spec = _spec(tmp_path)
        command = _fake_worker(tmp_path, body)
        with pytest.raises(ProbeInfrastructureFailure) as exc:
            run_worker(spec, hard_cap_seconds=30.0, command=command)
        message = str(exc.value)
        assert "worker said something useful" in message
        assert "and something on stderr" in message  # stderr is merged in

    def test_the_log_survives_a_hard_kill(self, tmp_path):
        body = """
import signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("about to stall", flush=True)
Path(r"{progress}").write_text("training")
time.sleep(600)
"""
        outcome = _run(tmp_path, body, cap=1.0, grace=0.5)
        assert outcome.termination.kill_sent is True
        assert "about to stall" in outcome.detail

    def test_a_chatty_worker_does_not_deadlock(self, tmp_path):
        """An undrained PIPE would hang here; a file does not."""
        body = """
import json
from pathlib import Path
for i in range(20000):
    print("noise line %d" % i)
Path(r"{result}").write_text(json.dumps({{
    "status": "ok", "phase": "complete", "model_identity": "fake_candidate",
    "train_ms_per_step": 5.0
}}))
"""
        outcome = _run(tmp_path, body, cap=60.0)
        assert outcome.classification == "ok"
        assert outcome.result is not None
        assert outcome.result.train_ms_per_step == 5.0
