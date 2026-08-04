"""The parent half of the live-stability loop: watch, decide, signal, report.

V20 PR C2. `test_formal_stability.py` proves the RULE; this proves the
component that closes the loop around it — the edge that was missing when the
rule landed, and the reason a Gate arm would have run to its backstop with the
stop signal never written.

Every case here names a way the loop could silently stop being a loop:
computing a decision and not acting on it, acting and not reporting it,
counting another arm's steps, or certifying a peak the watch never saw.
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.runtime_control.formal_stability import FormalStabilityChannel, StepEventLog
from core.runtime_control.formal_stability_controller import (
    FormalStabilityController,
    FormalStabilityMisuse,
    FormalStabilityWatcher,
)
from core.runtime_control.gpu_measurement_sampler import TreeMemorySample

REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS = REPO_ROOT / "scripts" / "c2_prephase_validation.py"


def _channel(tmp_path: Path, **overrides) -> FormalStabilityChannel:
    payload = {
        "events_path": str(tmp_path / "steps.ndjson"),
        "stop_path": str(tmp_path / "stop"),
        "run_id": "gate-c12a-p1_with_probe",
        "candidate_id": "c2lite_c12a_p1_with_probe",
        # Small, so a test can express "one short of enough" without
        # writing 500 events. The real defaults are asserted in
        # test_formal_stability.py, where they belong.
        "stable_steps_after_last_peak": 500,
        "min_samples_after_last_peak": 3,
    }
    payload.update(overrides)
    return FormalStabilityChannel(**payload)


def _sample(at: float, mib: int | None) -> TreeMemorySample:
    """One driver reading. `None` MiB is a FAILED query, not an idle card."""
    if mib is None:
        return TreeMemorySample(at=at, telemetry_available=False)
    return TreeMemorySample(at=at, telemetry_available=True, own_tree_mib=mib)


def _write_steps(channel: FormalStabilityChannel, count: int, *, start_at: float) -> None:
    """Append `count` completed steps, one per 0.001 s, from `start_at`."""
    log = StepEventLog(channel, clock=iter([start_at + i * 0.001 for i in range(count)]).__next__)
    for _ in range(count):
        log.record_completed_step(synchronized=True)


def _controller_then_steps(
    channel: FormalStabilityChannel,
    *,
    samples,
    steps: int = 0,
    start_at: float = 1.0,
    clock=None,
    started_at: float = 0.0,
) -> FormalStabilityController:
    """Open the controller FIRST, then let the trainer write.

    This is production's order and the tests follow it deliberately: the
    parent opens the channel before the training subprocess is launched. An
    earlier draft of this file built the controller after writing the events
    and every case errored on the pre-existing-log guard — which is the guard
    doing its job, and the reason it is not relaxed.
    """
    controller = FormalStabilityController(
        channel,
        samples=samples,
        clock=clock or _Clock(9.0),
        started_at=started_at,
    )
    if steps:
        _write_steps(channel, steps, start_at=start_at)
    return controller


class _Clock:
    def __init__(self, *values: float) -> None:
        self._values = list(values)
        self.last = self._values[0]

    def __call__(self) -> float:
        if self._values:
            self.last = self._values.pop(0)
        return self.last


# ─────────────────────────────────────────────────────────────────────────
# The criterion, reached through the production boundary
# ─────────────────────────────────────────────────────────────────────────


class TestBothConditionsAreRequired:
    """Steps and readings are independent. Either alone is a way to certify
    a peak that was never watched settling, or a watch of a peak that never
    settled."""

    def _controller(self, tmp_path, *, steps: int, readings: list[float]):
        channel = _channel(tmp_path)
        # The peak rises once, at t=0. Everything after is the stable tail.
        series = [_sample(0.0, 3434)] + [_sample(t, 3434) for t in readings]
        return _controller_then_steps(
            channel, samples=lambda: series, steps=steps, clock=_Clock(100.0)
        )

    def test_499_stable_steps_cannot_pass(self, tmp_path):
        """MUTATION TARGET: `>=` loosened to `>`, or the threshold lowered.

        One step short is not a plateau; it is 499 steps of agreement and an
        unasked question.
        """
        c = self._controller(tmp_path, steps=499, readings=[1.0, 2.0, 3.0])
        decision = c.poll()
        assert decision.status == "NOT_YET_STABLE"
        assert decision.should_stop is False
        assert not Path(c.channel.stop_path).exists(), "the parent signalled one step early"
        assert c.completion().succeeded is False

    def test_500_stable_steps_with_two_readings_cannot_pass(self, tmp_path):
        """500 steps during which nobody looked twice proves nothing about
        the peak: the plateau is asserted from readings, not from steps."""
        c = self._controller(tmp_path, steps=500, readings=[1.0, 2.0])
        decision = c.poll()
        assert decision.samples_after_last_increase == 2
        assert decision.status == "NOT_YET_STABLE"
        assert not Path(c.channel.stop_path).exists()

    def test_three_readings_without_the_steps_cannot_pass(self, tmp_path):
        """MUTATION TARGET: inferring step progress from sample count.

        A stalled trainer emits samples at full cadence and no steps at all.
        A rule that counted readings would call that stability.
        """
        c = self._controller(tmp_path, steps=4, readings=[1.0, 2.0, 3.0, 4.0])
        decision = c.poll()
        assert decision.samples_after_last_increase >= 3
        assert decision.stable_steps == 4
        assert decision.status == "NOT_YET_STABLE"

    def test_500_steps_and_three_readings_passes_and_signals(self, tmp_path):
        c = self._controller(tmp_path, steps=500, readings=[1.0, 2.0, 3.0])
        decision = c.poll()
        assert decision.status == "STABLE"
        assert decision.should_stop is True
        assert Path(c.channel.stop_path).exists(), "the parent decided and did not signal"
        completion = c.completion()
        assert completion.succeeded is True
        assert completion.stop_signalled is True
        assert completion.cumulative_peak_mib == 3434


class TestANewPeakResetsBothCounters:
    def test_a_later_increase_collapses_steps_and_readings(self, tmp_path):
        """MUTATION TARGET: resetting one counter and not the other.

        The reset is a consequence of measuring both from the last increase,
        so it cannot be forgotten in one place and applied in another.
        """
        channel = _channel(tmp_path)
        # 600 steps land between t=1.0 and t=1.6. The peak rises again at
        # t=1.5, so only the steps after that are stable.
        series = [_sample(0.0, 3000), _sample(1.5, 3600), _sample(1.9, 3600), _sample(2.0, 3600)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=600)
        decision = c.poll()
        assert decision.cumulative_peak_mib == 3600
        assert decision.last_peak_increase_at == 1.5
        assert decision.stable_steps < 600, "the step counter survived a peak increase"
        assert decision.samples_after_last_increase == 2, (
            "the reading counter survived a peak increase"
        )
        assert decision.status == "NOT_YET_STABLE"

    def test_a_repeated_peak_is_not_an_increase(self, tmp_path):
        """A plateau reported twice is the same plateau. Treating a tie as a
        rise would reset forever and no phase would ever settle."""
        channel = _channel(tmp_path)
        series = [_sample(0.0, 3434), _sample(2.0, 3434), _sample(3.0, 3434), _sample(4.0, 3434)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=500)
        assert c.poll().status == "STABLE"


class TestBackstopsStopAndDoNotCertify:
    def test_the_step_ceiling_is_inconclusive_not_a_pass(self, tmp_path):
        channel = _channel(tmp_path, max_completed_steps=50)
        series = [_sample(float(i), 3000 + i) for i in range(5)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=50)
        decision = c.poll()
        assert decision.status == "INCONCLUSIVE_MAX_STEPS"
        # It STOPS -- there is no point running on -- but it certifies
        # nothing. Those are different questions and this is where they part.
        assert decision.should_stop is True
        assert Path(channel.stop_path).exists()
        assert c.completion().succeeded is False

    def test_the_wall_clock_cap_is_inconclusive_not_a_pass(self, tmp_path):
        channel = _channel(tmp_path, max_phase_seconds=10.0)
        series = [_sample(float(i), 3000 + i) for i in range(5)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=5, clock=_Clock(11.0))
        decision = c.poll()
        assert decision.status == "INCONCLUSIVE_DEADLINE"
        assert c.completion().succeeded is False
        assert "safety stop, never a success criterion" in decision.detail

    def test_stability_is_checked_before_the_backstops(self, tmp_path):
        """A run that settles on its very last allowed step passes. Checking
        the ceiling first would fail it for arriving late."""
        channel = _channel(tmp_path, max_completed_steps=501)
        series = [_sample(0.0, 3434), _sample(2.0, 3434), _sample(3.0, 3434), _sample(4.0, 3434)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=501)
        assert c.poll().status == "STABLE"


# ─────────────────────────────────────────────────────────────────────────
# Identity, staleness and races
# ─────────────────────────────────────────────────────────────────────────


class TestOnlyThisArmsWorkIsCounted:
    def test_another_runs_events_are_ignored(self, tmp_path):
        """Case 12 runs six formal arms under one Gate. An arm counting a
        sibling's steps would reach 500 without executing them."""
        channel = _channel(tmp_path)
        series = [_sample(0.0, 3434), _sample(2.0, 3434), _sample(3.0, 3434), _sample(4.0, 3434)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=10)
        _write_steps(_channel(tmp_path, run_id="some-other-gate"), 600, start_at=1.0)
        decision = c.poll()
        assert decision.completed_steps == 10, "another run's steps were counted"
        assert decision.status == "NOT_YET_STABLE"

    def test_the_same_run_but_another_candidate_is_ignored(self, tmp_path):
        """MUTATION TARGET: filtering on run_id alone.

        Both arms of one pair share a Gate. Only the candidate identity
        separates their steps.
        """
        channel = _channel(tmp_path)
        series = [_sample(0.0, 3434), _sample(2.0, 3434), _sample(3.0, 3434), _sample(4.0, 3434)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=10)
        _write_steps(
            _channel(tmp_path, candidate_id="c2lite_c12a_p1_without_probe"), 600, start_at=1.0
        )
        assert c.poll().completed_steps == 10, "a sibling arm's steps were counted"

    def test_a_malformed_trailing_line_is_skipped_not_fatal(self, tmp_path):
        """The file is appended to live and may be read mid-write."""
        channel = _channel(tmp_path)
        series = [_sample(0.0, 3434), _sample(2.0, 3434), _sample(3.0, 3434)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=5)
        with open(channel.events_path, "a", encoding="utf-8") as fh:
            fh.write('{"step_index": 6, "at": 1.0')  # torn write
        assert c.poll().completed_steps == 5


class TestMisusesOfTheChannelRaise:
    def test_a_pre_existing_stop_signal_refuses_to_open(self, tmp_path):
        """MUTATION TARGET: deleting the guard.

        A leftover signal stops the trainer at step 1, and the arm reports a
        single step's peak as a settled one — a number that looks measured.
        """
        channel = _channel(tmp_path)
        Path(channel.stop_path).touch()
        with pytest.raises(FormalStabilityMisuse, match="already exists"):
            FormalStabilityController(channel, samples=list)

    def test_a_pre_existing_event_log_refuses_to_open(self, tmp_path):
        """Its lines carry THIS run_id by construction, so they would be
        counted as this phase's work."""
        channel = _channel(tmp_path)
        _write_steps(channel, 3, start_at=1.0)
        with pytest.raises(FormalStabilityMisuse, match="step-event log"):
            FormalStabilityController(channel, samples=list)


class TestTheRaceBoundaries:
    def test_a_step_at_the_exact_peak_timestamp_is_not_counted_as_after(self, tmp_path):
        """A step event and a peak sample can arrive in the same instant.

        The tie resolves conservatively — the step is NOT credited to the
        stable tail — so a simultaneous arrival delays stability rather than
        manufacturing it.
        """
        channel = _channel(tmp_path)
        series = [_sample(5.0, 3434), _sample(6.0, 3434), _sample(7.0, 3434)]
        c = FormalStabilityController(
            channel, samples=lambda: series, clock=_Clock(9.0), started_at=0.0
        )
        StepEventLog(channel, clock=lambda: 5.0).record_completed_step()
        assert c.poll().stable_steps == 0

    def test_the_trainer_finishing_first_is_reported_not_hidden(self, tmp_path):
        """The workload ran out before stability did. Nothing is claimed, and
        the reason says which of the two happened."""
        channel = _channel(tmp_path)
        series = [_sample(0.0, 3434), _sample(2.0, 3434), _sample(3.0, 3434)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=12)
        c.poll()
        completion = c.completion()
        assert completion.succeeded is False
        assert completion.stop_signalled is False
        assert "returned before the peak settled" in completion.stop_reason

    def test_a_crash_before_any_evaluation_claims_nothing(self, tmp_path):
        """MUTATION TARGET: defaulting an unevaluated phase to STABLE, or to
        a zero peak."""
        c = FormalStabilityController(_channel(tmp_path), samples=list)
        completion = c.completion()
        assert completion.succeeded is False
        assert completion.status == "INCONCLUSIVE_NO_STEP"
        assert completion.cumulative_peak_mib is None, "an unmeasured peak became a number"
        assert "never computed" in completion.stop_reason

    def test_the_signal_records_when_the_parent_decided_not_when_it_last_looked(self, tmp_path):
        channel = _channel(tmp_path)
        series = [_sample(0.0, 3434), _sample(2.0, 3434), _sample(3.0, 3434), _sample(4.0, 3434)]
        c = _controller_then_steps(
            channel, samples=lambda: series, steps=500, clock=_Clock(50.0, 60.0, 70.0)
        )
        c.poll()
        first = c.signalled_at
        c.poll()
        c.poll()
        assert c.signalled_at == first == 50.0


class TestAnIncompleteWatchCannotCertify:
    def test_a_missed_reading_refuses_the_claim_even_when_stable(self, tmp_path):
        """MUTATION TARGET: dropping `sampling_complete` from `succeeded`.

        A peak that rose inside an unwatched stretch is invisible to the
        arithmetic, so the arithmetic saying STABLE is not enough.
        """
        channel = _channel(tmp_path)
        series = [
            _sample(0.0, 3434),
            _sample(2.0, None),  # driver query failed
            _sample(3.0, 3434),
            _sample(4.0, 3434),
            _sample(5.0, 3434),
        ]
        c = _controller_then_steps(channel, samples=lambda: series, steps=500)
        assert c.poll().status == "STABLE"
        completion = c.completion()
        assert completion.sampling_complete is False
        assert completion.samples_missed == 1
        assert completion.succeeded is False, "an incomplete watch certified a peak"
        assert "rerun" in completion.stop_reason

    def test_a_failed_query_is_missed_not_a_low_reading(self, tmp_path):
        """Reading a gap as 0 MiB would look like the peak falling, which is
        the under-report direction."""
        channel = _channel(tmp_path)
        series = [_sample(0.0, 3434), _sample(1.0, None), _sample(2.0, 3434), _sample(3.0, 3434)]
        c = _controller_then_steps(channel, samples=lambda: series, steps=500)
        assert c.poll().cumulative_peak_mib == 3434


# ─────────────────────────────────────────────────────────────────────────
# The loop actually closes
# ─────────────────────────────────────────────────────────────────────────


class TestTheWatcherDrivesTheController:
    def test_the_trainer_stops_mid_workload_when_the_parent_decides(self, tmp_path):
        """The whole point of the loop, asserted without a race.

        The trainer is given a workload far longer than stability needs. It
        must stop partway through — a run that reaches the end of its data
        proves only that the data ran out.
        """
        channel = _channel(tmp_path, stable_steps_after_last_peak=3, min_samples_after_last_peak=3)
        series = [_sample(0.0, 3434), _sample(0.1, 3434), _sample(0.2, 3434), _sample(0.3, 3434)]
        controller = FormalStabilityController(channel, samples=lambda: series)
        log = StepEventLog(channel)
        for _ in range(500):
            if log.observe_completed_step():
                break
            controller.poll()  # the parent, interleaved as the watcher does it
        assert log.completed_steps == 4, (
            "the trainer did not stop one step after the parent signalled at 3"
        )
        assert Path(channel.stop_path).exists()
        assert controller.completion().succeeded is True

    def test_the_thread_really_polls_without_the_caller(self, tmp_path):
        """`execute_training` blocks, so nothing in the parent's own flow can
        poll. The thread is the only thing that can, and this proves it does.
        """
        channel = _channel(tmp_path, stable_steps_after_last_peak=3, min_samples_after_last_peak=3)
        series = [_sample(0.0, 3434), _sample(0.1, 3434), _sample(0.2, 3434), _sample(0.3, 3434)]
        controller = FormalStabilityController(channel, samples=lambda: series)
        log = StepEventLog(channel)
        for _ in range(9):
            log.record_completed_step()
        with FormalStabilityWatcher(controller, interval_seconds=0.01):
            deadline = time.monotonic() + 5.0
            while not Path(channel.stop_path).exists() and time.monotonic() < deadline:
                time.sleep(0.01)
        assert Path(channel.stop_path).exists(), "the watcher thread never polled"
        assert controller.polls > 0
        assert controller.completion().succeeded is True

    def test_the_final_tick_sees_the_last_steps(self, tmp_path):
        """MUTATION TARGET: removing the poll in `__exit__`.

        Steps completed after the last tick are real work. A phase whose
        final decision predates its final steps under-reports both.
        """
        channel = _channel(tmp_path, stable_steps_after_last_peak=5, min_samples_after_last_peak=3)
        series = [_sample(0.0, 3434), _sample(0.1, 3434), _sample(0.2, 3434)]
        controller = FormalStabilityController(channel, samples=lambda: series)
        log = StepEventLog(channel)
        # A long interval, so the loop's own ticks never see these steps.
        with FormalStabilityWatcher(controller, interval_seconds=3600.0):
            for _ in range(9):
                log.record_completed_step()
        assert controller.completion().completed_steps == 9

    def test_a_failing_poll_is_counted_not_fatal(self, tmp_path):
        """A dead watcher thread leaves the trainer running with nobody
        watching, and the phase ends at the workload's length with no
        explanation."""

        def boom():
            raise RuntimeError("nvidia-smi went away")

        controller = FormalStabilityController(_channel(tmp_path), samples=boom)
        with FormalStabilityWatcher(controller, interval_seconds=0.01):
            pass
        assert controller.poll_errors > 0
        assert controller.completion().succeeded is False


# ─────────────────────────────────────────────────────────────────────────
# Production reachability, structurally
# ─────────────────────────────────────────────────────────────────────────


def _harness_function(name: str) -> ast.FunctionDef:
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {HARNESS}")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


class TestTheHarnessActuallyClosesTheLoop:
    """Three ways the loop can exist and do nothing. Each gets a test,
    because each would leave every unit test above passing."""

    def test_the_formal_arm_constructs_a_controller(self):
        """MUTATION TARGET: deleting the parent's polling entirely.

        Without this the trainer emits events nobody reads, no stop is ever
        written, and the phase runs to the end of its workload — which is
        precisely the state this whole module was added to end.
        """
        called = _called_names(_harness_function("run_formal_execution"))
        assert "FormalStabilityController" in called, (
            "the formal arm never constructs a stability controller; nothing polls"
        )
        assert "FormalStabilityWatcher" in called, (
            "the controller is constructed but never driven; poll() is never called"
        )

    def test_the_watcher_wraps_the_training_boundary(self):
        """Polling after `execute_training` returns is not watching."""
        fn = _harness_function("run_formal_execution")
        for node in ast.walk(fn):
            if isinstance(node, ast.With):
                items = {
                    item.context_expr.func.id
                    for item in node.items
                    if isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Name)
                }
                if "FormalStabilityWatcher" in items:
                    assert "execute_training" in _called_names(node), (
                        "the watcher does not span the training boundary"
                    )
                    return
        raise AssertionError("no `with FormalStabilityWatcher(...)` in run_formal_execution")

    def test_the_completion_is_carried_into_the_artifact(self):
        """MUTATION TARGET: signalling the stop and discarding the result.

        A phase that stopped correctly and reported nothing is
        indistinguishable, in the artifact, from one that never stopped.
        """
        fn = _harness_function("run_formal_execution")
        assert "completion" in _called_names(fn), "the controller's typed result is never collected"
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        keys = {
            k.value
            for r in returns
            if isinstance(r.value, ast.Dict)
            for k in r.value.keys
            if isinstance(k, ast.Constant)
        }
        assert "stability" in keys, (
            "the formal arm's returned record has no stability key; the decision "
            "never reaches the artifact"
        )

    def test_the_channel_reaches_the_trainer_only_through_the_environment(self):
        """There is no CLI flag and no config key for the channel: its
        absence IS the disabled state, which cannot be half-configured."""
        source = HARNESS.read_text(encoding="utf-8")
        assert "STABILITY_ENV_VAR" in source, (
            "the harness never sets the channel; the trainer would emit nothing"
        )
        assert "os.environ[STABILITY_ENV_VAR]" in source

    def test_no_cli_flag_configures_the_channel_itself(self):
        """Thresholds are the operator's; WHERE events and the signal live is
        derived from the arm. An operator-supplied events path could point two
        arms at one file, and each would count the other's steps."""
        forbidden = {"events_path", "stop_path", "run_id", "candidate_id"}
        tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        bare = arg.value.lstrip("-")
                        assert bare not in forbidden, (
                            f"--{bare} lets an operator point two arms at one channel"
                        )

    def test_the_environment_is_restored_after_training(self):
        """MUTATION TARGET: setting the variable and not restoring it.

        A variable left set follows every later arm and the inference
        subprocess, so a single Case 12 invocation would leak one arm's
        channel into five others.
        """
        fn = _harness_function("run_formal_execution")
        tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
        assert tries, "the channel is set with no `finally` to restore it"
        restored = any(
            "STABILITY_ENV_VAR" in (ast.unparse(stmt) or "") for t in tries for stmt in t.finalbody
        )
        assert restored, "the `finally` does not restore the stability channel"


class TestProductionIsUnchangedWithoutTheChannel:
    def test_the_trainer_opens_nothing_when_the_variable_is_absent(self, monkeypatch, tmp_path):
        """The whole safety argument in one assertion: no channel, no file,
        no read, no behaviour."""
        from core.runtime_control.formal_stability import (
            STABILITY_ENV_VAR,
            channel_from_environment,
        )

        monkeypatch.delenv(STABILITY_ENV_VAR, raising=False)
        assert channel_from_environment() is None
        assert not list(tmp_path.iterdir())

    def test_an_empty_value_is_also_disabled(self, monkeypatch):
        from core.runtime_control.formal_stability import (
            STABILITY_ENV_VAR,
            channel_from_environment,
        )

        monkeypatch.setenv(STABILITY_ENV_VAR, "   ")
        assert channel_from_environment() is None

    def test_a_malformed_channel_is_reported_not_ignored(self, monkeypatch):
        """Silently dropping it would run a Gate with no stability evidence
        and no warning, at the full cost of the run."""
        from core.runtime_control.formal_stability import (
            STABILITY_ENV_VAR,
            channel_from_environment,
        )

        monkeypatch.setenv(STABILITY_ENV_VAR, json.dumps({"events_path": "only-one-field"}))
        with pytest.raises(ValidationError):
            channel_from_environment()

    def test_a_bare_boolean_is_refused_as_a_channel(self, monkeypatch):
        """The operator's condition: the variable's value must be a channel,
        never a switch. `true` IS valid JSON, so it slips past the parse and
        is caught by the object check — the branch that makes
        `SIDERIUS_C2_FORMAL_STABILITY=1` impossible.
        """
        from core.runtime_control.formal_stability import (
            STABILITY_ENV_VAR,
            channel_from_environment,
        )

        monkeypatch.setenv(STABILITY_ENV_VAR, "true")
        with pytest.raises(ValueError, match="must be a JSON object"):
            channel_from_environment()
