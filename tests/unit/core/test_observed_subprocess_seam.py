"""B-C2a2 — one seam, plain mode on observable Popen.

Four GPU launch sites existed: training and inference, each with a
watchdog and a plain branch, and the watchdog is off by default so the
plain branches are the ordinary production path. Telemetry attached at
four sites would eventually lose a branch, so all four now go through
``_run_observed_subprocess``.

B-C2a1 routed the four sites without changing either implementation.
B-C2a2 moves plain mode onto ``Popen`` so B-C2b can hold the child PID
while the child is alive, and migrates the 48 stubs that were aimed at
the retired ``subprocess.run`` call point.

**The parity assertions had to be rewritten, not deleted.** Before
B-C2a2 the only place ``check`` / ``env`` / ``cwd`` / ``text`` /
``preexec_fn`` were verified was a test asserting on ``subprocess.run``
kwargs — so the migration invalidated the very test holding that
evidence. ``check=True`` has no ``Popen`` analogue at all; its
replacement is behavioural, that a non-zero exit still raises
``CalledProcessError``.

No GPU and no TIDMAD data: every child here is a scripted `python -c`.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.sandbox_executor import _run_observed_subprocess

SOURCE = Path(__file__).resolve().parents[3] / "core" / "sandbox_executor.py"


def _child(body: str) -> list[str]:
    return [sys.executable, "-c", body]


ECHO_OK = _child("import sys; sys.stdout.write('OUT'); sys.stderr.write('ERR')")
EXIT_3 = _child("import sys; sys.stderr.write('BOOM'); sys.exit(3)")


def _plain(cmd, **over):
    import os

    kwargs: dict = {"env": dict(os.environ), "preexec_fn": None, "capture_stdout": True}
    kwargs.update(over)
    return _run_observed_subprocess(cmd, **kwargs)


class TestRoutingOnly:
    """The seam must be a door, not a re-implementation."""

    def test_plain_mode_uses_popen(self):
        """B-C2b needs the child PID while the child is alive, which
        ``subprocess.run`` cannot provide."""
        real = subprocess.Popen
        seen: dict = {}

        def _spy(cmd, **kw):
            seen["called"] = True
            return real(cmd, **kw)

        with patch("core.sandbox_executor.subprocess.Popen", side_effect=_spy):
            result, kill_info = _plain(ECHO_OK)
        assert seen.get("called") is True
        assert kill_info is None
        assert result is not None

    def test_plain_mode_no_longer_calls_subprocess_run(self):
        """The retired call point. 48 stubs were migrated off it; a
        regression here would silently un-migrate them."""
        with patch("core.sandbox_executor.subprocess.run") as mock_run:
            _plain(ECHO_OK)
        assert not mock_run.called, (
            "plain mode fell back to subprocess.run — the migrated stubs "
            "would stop intercepting and real training could launch"
        )

    def test_deadline_mode_still_reaches_the_watchdog_popen(self):
        seen: dict = {}
        real = subprocess.Popen

        def _spy(cmd, **kw):
            seen.update(kw)
            return real(cmd, **kw)

        with patch("core.sandbox_executor.subprocess.Popen", side_effect=_spy):
            _plain(
                ECHO_OK,
                deadline_provider=lambda: (None, "test"),
                grace_seconds=1.0,
                poll_seconds=0.05,
                label="test",
            )
        assert seen.get("start_new_session") is True, (
            "the deadline path must keep its own process group so killpg reaches every descendant"
        )


class TestSemanticsUnchanged:
    """The parity evidence for the whole codebase.

    Before B-C2a2 these facts were asserted against ``subprocess.run``
    kwargs. The migration invalidated that test, so the assertions are
    rewritten here against ``Popen`` rather than dropped — this is the
    only place ``env`` / ``cwd`` / ``text`` / ``preexec_fn`` are verified
    at all.
    """

    @staticmethod
    def _popen_kwargs(**over) -> dict:
        seen: dict = {}
        real = subprocess.Popen

        def _spy(cmd, **kw):
            seen.update(kw)
            seen["__cmd__"] = cmd
            return real(cmd, **kw)

        with patch("core.sandbox_executor.subprocess.Popen", side_effect=_spy):
            _plain(ECHO_OK, **over)
        return seen

    def test_plain_forwards_every_argument_unchanged(self):
        import os

        env = dict(os.environ)

        def _marker():  # pragma: no cover - would run in the child
            pass

        kwargs = self._popen_kwargs(env=env, preexec_fn=_marker)
        assert kwargs["env"] is env
        assert kwargs["preexec_fn"] is _marker
        assert kwargs["text"] is True
        assert kwargs["stderr"] is subprocess.PIPE
        assert kwargs["cwd"] == os.getcwd()
        assert kwargs["__cmd__"] == ECHO_OK

    def test_check_true_has_no_popen_analogue_so_the_behaviour_is_asserted(self):
        """``Popen`` has no ``check`` argument. The property that mattered
        was never the keyword — it was that a non-zero exit raises, which
        several downstream handlers depend on. Asserted behaviourally in
        ``test_plain_nonzero_exit_still_raises``; this pins that no
        ``check`` kwarg is smuggled through instead."""
        assert "check" not in self._popen_kwargs()

    def test_progress_bar_mode_leaves_stdout_uncaptured(self):
        assert self._popen_kwargs(capture_stdout=False)["stdout"] is None

    def test_progress_bar_off_captures_stdout(self):
        assert self._popen_kwargs(capture_stdout=True)["stdout"] is subprocess.PIPE

    def test_plain_nonzero_exit_still_raises(self):
        """Downstream `except subprocess.CalledProcessError` handlers at
        sandbox_executor.py:972 and :1204 depend on this."""
        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            _plain(EXIT_3)
        assert excinfo.value.returncode == 3

    def test_plain_output_matches_subprocess_run(self):
        import os

        env = dict(os.environ)
        reference = subprocess.run(
            ECHO_OK, check=True, capture_output=True, text=True, cwd=os.getcwd(), env=env
        )
        result, _ = _plain(ECHO_OK, env=env)
        assert result is not None
        assert (result.returncode, result.stdout, result.stderr) == (
            reference.returncode,
            reference.stdout,
            reference.stderr,
        )


class TestSeamReachability:
    """Removing any production call site must fail a test, not go
    unnoticed — the guardrail pattern PR A established."""

    @staticmethod
    def _seam_call_lines() -> list[int]:
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        return [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_run_observed_subprocess"
        ]

    def test_all_four_gpu_launches_go_through_the_seam(self):
        calls = self._seam_call_lines()
        assert len(calls) == 4, (
            f"expected 4 GPU launch sites through the seam, found {len(calls)} "
            f"at lines {calls}. training and inference each have a watchdog "
            "and a plain branch; a branch that bypasses the seam would "
            "silently lose telemetry in B-C2b."
        )

    def test_only_cpu_scoring_still_calls_subprocess_run(self):
        """After B-C2a2 the seam no longer delegates, so scoring is the
        sole remaining direct caller — it is CPU-only
        (`_ROLE_DEFAULT_RSS_GB` marks it so) and a GPU seam there would
        be a no-op."""
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        direct = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "subprocess"
        ]
        assert len(direct) == 1, (
            f"subprocess.run called at lines {direct}; expected exactly one — "
            "CPU-only scoring. The seam must not fall back to it."
        )


class TestNoTelemetryYet:
    """The executor consumes telemetry; it does not own it.

    Narrowed at B-C4b (2026-08-02). This class was written for B-C2a1,
    when the executor was routing alone and *any* telemetry reference
    would have made a parity regression un-attributable. It also
    forbade `gpu_accounting`, which stayed true through B-C2b only
    because the observer was reached via `gpu_observer`.

    B-C4b's approved design requires reading device occupancy **before**
    spawn, so that term is now obsolete and was removed rather than
    worked around. What remains is the real invariant and is unchanged:
    the executor must not own the telemetry backend and must not mint a
    device identity — the backend belongs to `gpu_accounting`, and
    identity is resolved upstream and passed in, so the executor cannot
    quietly decide which GPU it is talking about.
    """

    def test_the_executor_owns_neither_the_backend_nor_the_identity(self):
        text = SOURCE.read_text(encoding="utf-8")
        for term in ("nvidia-smi", "DeviceIdentity"):
            assert term not in text, (
                f"{term!r} appears in sandbox_executor; the telemetry backend "
                "belongs to gpu_accounting and device identity is resolved "
                "upstream, so the executor cannot choose its own device"
            )

    def test_the_executor_starts_no_thread(self):
        assert "threading" not in SOURCE.read_text(encoding="utf-8"), (
            "observer threads belong to B-C2b"
        )


class TestObserverLifecycle:
    """B-C2b checkpoint 3 — the seam drives the observer, and the
    observer can never affect the child's result."""

    class _Spy:
        def __init__(self, *, boom: bool = False) -> None:
            self.events: list = []
            self.boom = boom

        def capture_baseline(self):
            self.events.append(("baseline", None))
            if self.boom:
                raise RuntimeError("observer exploded")

        def start(self, pid):
            self.events.append(("start", pid))
            if self.boom:
                raise RuntimeError("observer exploded")

        def stop(self, *, child_pid=None, failed=False):
            self.events.append(("stop", failed))
            if self.boom:
                raise RuntimeError("observer exploded")

    def test_baseline_precedes_the_child_and_start_follows_it(self):
        """The baseline must be taken before Popen — after it, the
        candidate is already on the device and the slot would describe
        something other than what it had to fit into."""
        spy = self._Spy()
        _plain(ECHO_OK, observer=spy)
        kinds = [e[0] for e in spy.events]
        assert kinds == ["baseline", "start", "stop"]
        assert spy.events[1][1] > 0, "start() must receive the real child PID"

    def test_stop_reports_success_as_not_failed(self):
        spy = self._Spy()
        _plain(ECHO_OK, observer=spy)
        assert ("stop", False) in spy.events

    def test_stop_reports_a_nonzero_exit_as_failed(self):
        spy = self._Spy()
        with pytest.raises(subprocess.CalledProcessError):
            _plain(EXIT_3, observer=spy)
        assert ("stop", True) in spy.events

    def test_the_observer_stops_even_when_the_child_raises(self):
        """`finally`, not the happy path — otherwise a wedged sampler
        outlives the phase it was watching."""
        spy = self._Spy()

        class _Boom(Exception):
            pass

        real = subprocess.Popen

        class _Raising(real):  # type: ignore[misc, valid-type]
            def communicate(self, *_a, **_kw):
                raise _Boom

        with patch("core.sandbox_executor.subprocess.Popen", _Raising), pytest.raises(_Boom):
            _plain(_child("import time; time.sleep(30)"), observer=spy)
        assert [e[0] for e in spy.events] == ["baseline", "start", "stop"]

    def test_no_observer_is_the_default_and_changes_nothing(self):
        result, kill_info = _plain(ECHO_OK)
        assert kill_info is None
        assert result is not None and result.stdout == "OUT"

    def test_the_deadline_path_also_drives_the_observer(self):
        spy = self._Spy()
        _plain(
            ECHO_OK,
            observer=spy,
            deadline_provider=lambda: (None, "test"),
            grace_seconds=1.0,
            poll_seconds=0.05,
            label="test",
        )
        assert [e[0] for e in spy.events] == ["baseline", "start", "stop"]


class TestFailureEvidencePersistence:
    """B-C2b checkpoint 4b — the bundle reaches a failure result, and
    only a failure result."""

    @staticmethod
    def _sandbox(tmp_path, identity):
        from core.sandbox_executor import TidmadSandbox

        return TidmadSandbox(
            run_name="ev", workspace=str(tmp_path), file_index=6, device_identity=identity
        )

    @staticmethod
    def _identity():
        from core.runtime_control.gpu_accounting import DeviceIdentity

        return DeviceIdentity(uuid="GPU-test-0000", physical_index=0)

    def test_a_failed_training_result_carries_the_bundle(self, tmp_path):
        sandbox = self._sandbox(tmp_path, self._identity())
        with patch("core.sandbox_executor._run_observed_subprocess") as seam:
            seam.side_effect = subprocess.CalledProcessError(1, ["x"], output="", stderr="boom")
            out = sandbox.execute_training(
                exp_id="e",
                run_name="ev",
                model_type="wavenet",
                m_cfg={"model_type": "wavenet", "segmentation_size": 1000},
                t_cfg={"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                l_cfg={},
                sample_set={6: [0]},
            )
        assert out["status"] in {"error", "oom_host_ram"}
        assert "gpu_evidence" in out
        assert out["gpu_evidence"]["device"]["uuid"] == "GPU-test-0000"

    def test_no_identity_means_no_bundle_and_no_rediscovery(self, tmp_path):
        """`None` is telemetry unavailable, not a cue to go find a GPU."""
        sandbox = self._sandbox(tmp_path, None)
        with patch("core.sandbox_executor._run_observed_subprocess") as seam:
            seam.side_effect = subprocess.CalledProcessError(1, ["x"], output="", stderr="boom")
            out = sandbox.execute_training(
                exp_id="e",
                run_name="ev",
                model_type="wavenet",
                m_cfg={"model_type": "wavenet", "segmentation_size": 1000},
                t_cfg={"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                l_cfg={},
                sample_set={6: [0]},
            )
        assert "gpu_evidence" not in out

    def test_a_successful_result_does_not_carry_the_bundle(self, tmp_path):
        """Persisting four snapshots on every success would be an
        unannounced schema and storage change on the hot path."""
        import os

        sandbox = self._sandbox(tmp_path, self._identity())

        def _ok(cmd, **_kw):
            os.makedirs(sandbox.dirs["models"], exist_ok=True)
            with open(os.path.join(sandbox.dirs["models"], "_OK_e"), "wb"):
                pass
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

        with patch("core.sandbox_executor._run_observed_subprocess", _ok):
            out = sandbox.execute_training(
                exp_id="e",
                run_name="ev",
                model_type="wavenet",
                m_cfg={"model_type": "wavenet", "segmentation_size": 1000},
                t_cfg={"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                l_cfg={},
                sample_set={6: [0]},
            )
        assert out["status"] == "success"
        assert "gpu_evidence" not in out

    def test_the_record_schema_accepts_the_bundle_and_still_accepts_none(self):
        from agent.schemas.hyperparam_tuning import ExperimentRecord

        assert "gpu_evidence" in ExperimentRecord.model_fields
        assert ExperimentRecord.model_fields["gpu_evidence"].default is None
