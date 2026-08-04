"""Completion must come from live execution, not from another card's clock.

V20 PR C2, operator decision 2026-08-04.

The shortened Case 12 bounded the formal arm at 2000 steps / 160 batches,
derived from 8.0762 ms/step and 0.705 s/file **measured on an RTX 5090**.
Those are observations of one machine. On an H100 the same integers buy a
different amount of execution and nothing would notice — and 29 % of the
inference phase they came from was filesystem, so the duration was partly a
storage benchmark.

The replacement stops when the driver-visible cumulative peak has provably
stopped moving on the machine under test. Each test below names a way that
rule could certify a peak that was still moving.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core.runtime_control.formal_stability import (
    DEFAULT_MAX_COMPLETED_STEPS,
    DEFAULT_MIN_SAMPLES_AFTER_LAST_PEAK,
    DEFAULT_STABLE_STEPS_AFTER_LAST_PEAK,
    STABILITY_ENV_VAR,
    FormalStabilityChannel,
    StepEvent,
    StepEventLog,
    channel_from_environment,
    evaluate_stability,
    read_step_events,
)
from core.runtime_control.gpu_measurement_sampler import TreeMemorySample

REPO_ROOT = Path(__file__).resolve().parents[3]
TRAINER_SOURCE = REPO_ROOT / "execute_tools" / "train_engine_sandbox.py"


def _channel(tmp_path, **over) -> FormalStabilityChannel:
    payload = dict(
        events_path=str(tmp_path / "steps.ndjson"),
        stop_path=str(tmp_path / "STOP"),
        run_id="lite-a",
        candidate_id="cfg:abc123",
    )
    payload.update(over)
    return FormalStabilityChannel(**payload)


def _events(n: int, *, start: float = 100.0, spacing: float = 1.0) -> list[StepEvent]:
    return [
        StepEvent(
            step_index=i + 1,
            at=start + i * spacing,
            run_id="lite-a",
            candidate_id="cfg:abc123",
            forward_ok=True,
            backward_ok=True,
            optimizer_ok=True,
            synchronized=True,
        )
        for i in range(n)
    ]


def _samples(*pairs: tuple[float, int | None]) -> list[TreeMemorySample]:
    out = []
    for at, mib in pairs:
        if mib is None:
            out.append(TreeMemorySample(at=at, telemetry_available=False))
        else:
            out.append(TreeMemorySample(at=at, telemetry_available=True, own_tree_mib=mib))
    return out


# ─────────────────────────────────────────────────────────────────────────
# Disabled by default
# ─────────────────────────────────────────────────────────────────────────


class TestItIsInertWithoutAChannel:
    def test_no_variable_means_no_channel(self):
        assert channel_from_environment(environ={}) is None

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_value_is_still_off(self, value):
        assert channel_from_environment(environ={STABILITY_ENV_VAR: value}) is None

    def test_the_trainer_holds_nothing_when_the_channel_is_absent(self, monkeypatch):
        """The production path. With no channel the trainer's loop is the
        loop it always was: no file opened, no event written, no signal
        read."""
        monkeypatch.delenv(STABILITY_ENV_VAR, raising=False)
        from execute_tools.train_engine_sandbox import _stability_log

        assert _stability_log() is None

    def test_a_malformed_channel_is_reported_not_ignored(self):
        """Silently dropping it would run a Gate with no stability evidence
        and no warning, at the full cost of the run."""
        with pytest.raises(ValueError, match="not JSON"):
            channel_from_environment(environ={STABILITY_ENV_VAR: "/tmp/plain-path"})

    def test_no_production_cli_or_config_exposes_it(self):
        """The control must be unreachable from an ordinary run. A flag or
        config key would make it something an operator could switch on
        without validation infrastructure."""
        source = TRAINER_SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
            ):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        assert "stability" not in arg.value.lower(), (
                            f"a production CLI flag exposes the validation control: {arg.value}"
                        )
        # Checked over the AST with docstrings excluded, not over the text.
        # The trainer's own docstring *explains* the variable, and a
        # substring scan cannot tell an explanation from a lookup -- the
        # same false positive that made the DeviceIdentity guardrail cry
        # wolf. The property is that the trainer never reads the variable
        # itself; it goes through `channel_from_environment`, which is the
        # one place the channel is parsed and validated.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", None)
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                ):
                    docstrings.add(id(body[0].value))
        offenders = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant)
            and n.value == STABILITY_ENV_VAR
            and id(n) not in docstrings
        ]
        assert not offenders, (
            f"the trainer names the variable in code at line(s) {offenders}; it must "
            "reach it only through channel_from_environment"
        )

    def test_the_control_is_not_active_by_default(self):
        """MUTATION TARGET: making the channel default to enabled."""
        assert channel_from_environment(environ={}) is None
        assert channel_from_environment(environ={"SOMETHING_ELSE": "1"}) is None


# ─────────────────────────────────────────────────────────────────────────
# Step events describe COMPLETED work
# ─────────────────────────────────────────────────────────────────────────


class TestOnlyCompletedStepsAreRecorded:
    def test_each_completed_step_emits_exactly_one_event(self, tmp_path):
        log = StepEventLog(_channel(tmp_path))
        for _ in range(5):
            log.record_completed_step()
        events = read_step_events(tmp_path / "steps.ndjson")
        assert [e.step_index for e in events] == [1, 2, 3, 4, 5]
        assert log.completed_steps == 5

    def test_a_partial_step_cannot_be_expressed_at_all(self):
        """The schema refuses it, so no caller can record one by accident.
        Counting a failed step would advance the stable total on work that
        never happened — the one way this rule could certify a moving peak
        as settled."""
        for bad in ({"forward_ok": False}, {"backward_ok": False}, {"optimizer_ok": False}):
            kwargs = dict(
                step_index=1,
                at=1.0,
                run_id="r",
                candidate_id="c",
                forward_ok=True,
                backward_ok=True,
                optimizer_ok=True,
            )
            kwargs.update(bad)
            with pytest.raises(ValueError, match="COMPLETED step"):
                StepEvent(**kwargs)

    def test_events_from_another_run_are_not_counted(self, tmp_path):
        """A stale log from a previous attempt would hand this phase
        stability it never earned."""
        path = tmp_path / "steps.ndjson"
        mine = _events(2)[0].model_dump()
        theirs = dict(mine, run_id="a-different-run")
        path.write_text(json.dumps(mine) + "\n" + json.dumps(theirs) + "\n", encoding="utf-8")
        assert len(read_step_events(path, run_id="lite-a")) == 1

    def test_a_torn_trailing_line_is_skipped_not_raised(self, tmp_path):
        """The file is appended to live and may be read mid-write."""
        path = tmp_path / "steps.ndjson"
        path.write_text(json.dumps(_events(1)[0].model_dump()) + '\n{"step_ind', encoding="utf-8")
        assert len(read_step_events(path)) == 1


class TestTheParentOwnsTheStopDecision:
    def test_the_log_cannot_decide_anything(self, tmp_path):
        """It exposes no policy: the trainer cannot see its own process
        tree's driver-visible memory, so it must not conclude."""
        log = StepEventLog(_channel(tmp_path))
        assert not hasattr(log, "is_stable")
        assert not hasattr(log, "evaluate")
        assert log.should_stop() is False

    def test_it_stops_only_when_the_parent_signals(self, tmp_path):
        channel = _channel(tmp_path)
        log = StepEventLog(channel)
        assert log.should_stop() is False
        Path(channel.stop_path).touch()
        assert log.should_stop() is True


class TestTheCombinedStepObservation:
    """`observe_completed_step` is what both engines call. The order inside
    it is load-bearing and no longer visible at the call site, so it is
    asserted here."""

    def test_the_step_is_recorded_before_the_signal_is_read(self, tmp_path):
        """MUTATION TARGET: reading the signal first.

        The parent may write the signal while THIS step is in flight. The
        step still happened and is still evidence; reading first would drop
        it, so the recorded count would be one short of the work done.
        """
        channel = _channel(tmp_path)
        log = StepEventLog(channel)
        Path(channel.stop_path).touch()
        assert log.observe_completed_step() is True
        assert log.completed_steps == 1
        assert len(read_step_events(channel.events_path, run_id=channel.run_id)) == 1, (
            "the in-flight step was discarded instead of recorded"
        )

    def test_it_reports_false_and_records_while_running(self, tmp_path):
        channel = _channel(tmp_path)
        log = StepEventLog(channel)
        assert log.observe_completed_step(synchronized=True) is False
        assert log.observe_completed_step(synchronized=True) is False
        events = read_step_events(channel.events_path, run_id=channel.run_id)
        assert [e.step_index for e in events] == [1, 2]
        assert all(e.synchronized for e in events)


# ─────────────────────────────────────────────────────────────────────────
# The stability criterion
# ─────────────────────────────────────────────────────────────────────────


class TestTheStabilityCriterion:
    def test_the_defaults_are_the_operator_decision(self):
        assert DEFAULT_STABLE_STEPS_AFTER_LAST_PEAK == 500
        assert DEFAULT_MIN_SAMPLES_AFTER_LAST_PEAK == 3
        assert DEFAULT_MAX_COMPLETED_STEPS == 5000

    def test_five_hundred_stable_steps_with_three_readings_passes(self, tmp_path):
        # peak rises at t=100, then 500 steps and 3 readings follow.
        events = _events(501, start=100.0, spacing=1.0)
        samples = _samples((100.0, 1476), (300.0, 1476), (400.0, 1476), (500.0, 1476))
        d = evaluate_stability(events=events, samples=samples, channel=_channel(tmp_path))
        assert d.status == "STABLE"
        assert d.should_stop is True
        assert d.stable_steps == 500
        assert d.samples_after_last_increase == 3
        assert d.cumulative_peak_mib == 1476

    def test_four_hundred_and_ninety_nine_cannot_pass(self, tmp_path):
        """MUTATION TARGET: an off-by-one that accepts 499."""
        events = _events(500, start=100.0)
        samples = _samples((100.0, 1476), (300.0, 1476), (400.0, 1476), (500.0, 1476))
        d = evaluate_stability(events=events, samples=samples, channel=_channel(tmp_path))
        assert d.stable_steps == 499
        assert d.status == "NOT_YET_STABLE"
        assert d.should_stop is False

    def test_five_hundred_steps_with_too_few_readings_cannot_pass(self, tmp_path):
        """MUTATION TARGET: dropping the sample requirement. 500 steps
        during which nobody looked proves nothing about the peak."""
        events = _events(501, start=100.0)
        samples = _samples((100.0, 1476), (300.0, 1476))  # only 2 after
        d = evaluate_stability(events=events, samples=samples, channel=_channel(tmp_path))
        assert d.stable_steps == 500
        assert d.samples_after_last_increase == 1
        assert d.status == "NOT_YET_STABLE"

    def test_enough_readings_without_enough_steps_cannot_pass(self, tmp_path):
        events = _events(10, start=100.0)
        samples = _samples((100.0, 1476), *[(100.5 + i, 1476) for i in range(8)])
        d = evaluate_stability(events=events, samples=samples, channel=_channel(tmp_path))
        assert d.samples_after_last_increase >= 3
        assert d.stable_steps < 500
        assert d.status == "NOT_YET_STABLE"

    def test_a_later_peak_increase_resets_the_counter(self, tmp_path):
        """MUTATION TARGET: failing to reset after a new peak.

        The peak rises again at t=400 after 300 quiet steps. Everything
        before that moment stops counting, because it described a smaller
        peak that no longer holds.
        """
        events = _events(600, start=100.0, spacing=1.0)
        samples = _samples((100.0, 1400), (200.0, 1400), (400.0, 1476), (500.0, 1476))
        d = evaluate_stability(events=events, samples=samples, channel=_channel(tmp_path))
        assert d.cumulative_peak_mib == 1476
        assert d.last_peak_increase_at == 400.0
        # 600 steps at 1 s from t=100 -> the last is t=699; steps after 400
        # number 299, not the 500 the pre-increase run had accumulated.
        assert d.stable_steps == 299
        assert d.status == "NOT_YET_STABLE"

    def test_a_repeated_peak_is_not_an_increase(self, tmp_path):
        """A tie must not reset the counter — the same peak observed twice
        is the same peak, and treating it as new would make stability
        unreachable on a steady phase."""
        events = _events(501, start=100.0)
        samples = _samples((100.0, 1476), (200.0, 1476), (300.0, 1476), (400.0, 1476))
        d = evaluate_stability(events=events, samples=samples, channel=_channel(tmp_path))
        assert d.last_peak_increase_at == 100.0
        assert d.status == "STABLE"

    def test_a_failed_reading_is_not_a_fallen_peak(self, tmp_path):
        """A gap is not a zero. Reading a failed query as 0 MiB would look
        like the peak had dropped and would never reset correctly."""
        events = _events(501, start=100.0)
        samples = _samples(
            (100.0, 1476), (150.0, None), (300.0, 1476), (400.0, 1476), (450.0, 1476)
        )
        d = evaluate_stability(events=events, samples=samples, channel=_channel(tmp_path))
        assert d.cumulative_peak_mib == 1476
        assert d.status == "STABLE"


class TestTheFirstStepIsMandatory:
    def test_no_completed_step_is_inconclusive(self, tmp_path):
        d = evaluate_stability(events=[], samples=_samples((1.0, 1476)), channel=_channel(tmp_path))
        assert d.status == "INCONCLUSIVE_NO_STEP"
        assert d.should_stop is False

    def test_no_observed_peak_is_inconclusive(self, tmp_path):
        d = evaluate_stability(events=_events(600), samples=[], channel=_channel(tmp_path))
        assert d.status == "INCONCLUSIVE_NO_PEAK"
        assert d.should_stop is False


class TestBackstopsAreNotPasses:
    def test_the_step_ceiling_is_inconclusive(self, tmp_path):
        """MUTATION TARGET: treating a backstop as success. The peak was
        still moving when the measurement stopped, so no requirement may be
        claimed."""
        channel = _channel(tmp_path, max_completed_steps=100)
        events = _events(100, start=100.0)
        samples = _samples((100.0, 1400), (190.0, 1476))
        d = evaluate_stability(events=events, samples=samples, channel=channel)
        assert d.status == "INCONCLUSIVE_MAX_STEPS"
        # It stops the run, but it is NOT a pass.
        assert d.should_stop is True
        assert d.status != "STABLE"

    def test_the_time_cap_is_inconclusive(self, tmp_path):
        channel = _channel(tmp_path, max_phase_seconds=30.0)
        d = evaluate_stability(
            events=_events(50, start=100.0),
            samples=_samples((100.0, 1476)),
            channel=channel,
            elapsed_seconds=31.0,
        )
        assert d.status == "INCONCLUSIVE_DEADLINE"
        assert d.status != "STABLE"

    def test_stability_is_checked_before_the_backstops(self, tmp_path):
        """A phase that settles on its very last allowed step passes,
        rather than being failed for arriving late."""
        channel = _channel(tmp_path, max_completed_steps=501, max_phase_seconds=1.0)
        events = _events(501, start=100.0)
        samples = _samples((100.0, 1476), (300.0, 1476), (400.0, 1476), (500.0, 1476))
        d = evaluate_stability(
            events=events, samples=samples, channel=channel, elapsed_seconds=999.0
        )
        assert d.status == "STABLE"

    def test_only_stable_reports_a_settled_peak(self, tmp_path):
        """The single property every backstop test depends on."""
        channel = _channel(tmp_path, max_completed_steps=10)
        d = evaluate_stability(events=_events(10), samples=_samples((100.0, 1476)), channel=channel)
        assert (d.status == "STABLE") is False


# ─────────────────────────────────────────────────────────────────────────
# The trainer's side, structurally
# ─────────────────────────────────────────────────────────────────────────


#: Both training engines. `run_experiment_streaming` is THE production path
#: -- `main()` dispatches to it whenever a sample set is supplied, which
#: every Gate arm and every chain round does; `run_experiment` is the legacy
#: single-file mode. Parameterizing over both is the point: the first wiring
#: landed only in `run_experiment`, so no formal arm emitted a single event
#: and the stop rule was inert on the path it exists for.
TRAINING_ENGINES = ("run_experiment", "run_experiment_streaming")


def _engine_ast(engine: str) -> ast.FunctionDef:
    """The named training function, so a structural claim is scoped to it.

    THE DEFECT THIS FIXES. The previous helper's docstring said "inside the
    streaming training loop" and its body was `ast.walk(tree)` over the whole
    module. Every assertion below therefore passed on wiring that existed
    only in the OTHER function, and the production path was unguarded while
    three tests reported it covered. A structural test that does not scope to
    the thing it names is not testing that thing.
    """
    tree = ast.parse(TRAINER_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == engine:
            return node
    raise AssertionError(f"{engine} not found in {TRAINER_SOURCE}")


def _training_loop_calls(engine: str) -> list[str]:
    """Ordered attribute-call names inside ONE training engine."""
    wanted = {
        "zero_grad",
        "backward",
        "step",
        "record_completed_step",
        "observe_completed_step",
        "should_stop",
    }
    found: list[tuple[int, str]] = []
    for node in ast.walk(_engine_ast(engine)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in wanted:
                found.append((node.lineno, node.func.attr))
    return [name for _, name in sorted(found)]


@pytest.mark.parametrize("engine", TRAINING_ENGINES)
class TestTheTrainerRecordsAndObeysInTheRightOrder:
    def test_the_engine_emits_completed_steps(self, engine):
        """MUTATION TARGET: removing the step event from EITHER engine.

        Scoped per engine, so wiring one and not the other fails here rather
        than passing on the other's lines.
        """
        calls = _training_loop_calls(engine)
        assert "observe_completed_step" in calls, (
            f"{engine} emits no completed-step event; a Gate arm running this "
            "engine would produce no stability evidence at all"
        )

    def test_the_event_follows_the_optimizer_step(self, engine):
        """MUTATION TARGET: emitting the event before the update completes."""
        calls = _training_loop_calls(engine)
        first = calls.index("observe_completed_step")
        preceding = [c for c in calls[:first] if c in {"zero_grad", "backward", "step"}]
        assert preceding[-1] == "step", (
            f"{engine} emits the event before the optimizer update completes: {preceding[-3:]}"
        )

    def test_the_event_is_synchronized(self, engine):
        """CUDA is asynchronous: an unsynchronized event can precede the
        work it claims, and the parent would credit readings to steps that
        had not finished."""
        for node in ast.walk(_engine_ast(engine)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "observe_completed_step"
            ):
                assert any(kw.arg == "synchronized" for kw in node.keywords), (
                    f"{engine} records an unsynchronized step event"
                )

    def test_the_engine_is_inert_without_a_channel(self, engine):
        """Every stability call site must sit behind `is not None`.

        An unguarded call would open a file in every production round.
        """
        source = ast.get_source_segment(
            TRAINER_SOURCE.read_text(encoding="utf-8"), _engine_ast(engine)
        )
        assert source is not None
        for line_no, line in enumerate(source.splitlines()):
            if "observe_completed_step" in line:
                window = source.splitlines()[max(0, line_no - 2) : line_no + 1]
                assert any("stability_log is not None" in w for w in window), (
                    f"{engine} calls the step log without checking the channel exists"
                )


class TestTheStopEndsThePhaseNotJustTheEpoch:
    def test_the_streaming_engine_breaks_the_epoch_loop_too(self):
        """A stop that only broke the batch loop would continue into epoch 1
        and keep executing after the parent concluded the peak had settled.

        MUTATION TARGET: deleting the outer `if stability_stopped: break`.
        """
        engine = _engine_ast("run_experiment_streaming")
        breaks_on_flag = [
            node
            for node in ast.walk(engine)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "stability_stopped"
            and any(isinstance(b, ast.Break) for b in node.body)
        ]
        assert breaks_on_flag, (
            "the streaming engine never leaves the epoch loop on a stability stop; "
            "it would run every remaining epoch after the parent had decided"
        )


class TestPhasesStayDistinct:
    def test_the_stability_rule_names_no_inference_concept(self):
        """Training completion is steps; inference completion is observed
        batches. One rule answering both would let a training criterion
        authorise an inference requirement."""
        source = (REPO_ROOT / "core" / "runtime_control" / "formal_stability.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        assert not any("inference" in n.lower() for n in names)

    def test_inference_completion_remains_observation_based(self):
        """The probe's inference phase ends on captured samples and
        released outputs — never an inherited duration."""
        from core.runtime_control.gpu_measurement_spec import RealismEvidence

        evidence = RealismEvidence()
        assert hasattr(evidence, "outputs_released")
        assert hasattr(evidence, "peak_state_observed")


class TestNoFixedHardwareConstantSurvives:
    def test_the_stability_module_encodes_no_5090_timing(self):
        """The whole point: 8.0762 ms/step and 0.705 s/file are 5090
        observations and must not appear in a portable rule."""
        source = (REPO_ROOT / "core" / "runtime_control" / "formal_stability.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        literals = [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, float)
        ]
        for banned in (8.0762, 0.705, 16.15, 5.64, 5.883, 1.342):
            assert banned not in literals, f"a 5090 timing constant leaked into the rule: {banned}"
