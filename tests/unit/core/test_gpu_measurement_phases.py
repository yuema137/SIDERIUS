"""The measurement must actually train, and must say what it did.

V20 PR C2 / C2-2.

The defect these guard is the one the producer audit found in the only
existing isolated probe: it never calls `backward()`
(`structural_probe.py:177`, and `:201` raises if it does), so gradients,
Adam's two moment buffers and cuDNN's backward workspaces were *estimated*
and never observed. A requirement built on that under-states in the OOM
direction, which is the direction that kills a formal run.

Every test here uses a REAL `nn.Module` on the CPU. That is deliberate: a
mock would let a detached loss, a missing `backward()` or a no-op optimizer
step pass, and those are precisely the failures being ruled out. Real
autograd on two parameters costs microseconds and cannot be fooled.
"""

from __future__ import annotations

import json
from contextlib import nullcontext

import pytest
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from core.runtime_control.gpu_measurement_phases import (
    CandidateComponents,
    PhaseJournal,
    run_measured_phases,
)
from execute_tools.task_probe_batch import InferenceProbeBatches


class _TinyNet(nn.Module):
    """Two real parameters and a real graph. Small enough to be free."""

    def __init__(self) -> None:
        super().__init__()
        self.linear = nn.Linear(4, 4)

    def forward(self, x):
        return self.linear(x)


def _components(*, lr: float = 0.1, detach: bool = False) -> CandidateComponents:
    model = _TinyNet()
    inputs = torch.ones(2, 4)
    target = torch.zeros(2, 4)
    base_loss = nn.MSELoss()

    def loss_fn(output, tgt):
        # `detach=True` reproduces the exact defect being guarded: a loss
        # that is numerically identical and connected to nothing.
        return base_loss(output.detach() if detach else output, tgt)

    def inference_batches(units):
        dataset = TensorDataset(inputs.repeat(units, 1))
        return nullcontext(
            InferenceProbeBatches(
                loader=DataLoader(dataset, batch_size=len(inputs)),
                dataset_samples=len(dataset),
                selected_samples=len(dataset),
                selected_batches=units,
            )
        )

    return CandidateComponents(
        model=model,
        model_input=inputs,
        loss_target=target,
        optimizer=torch.optim.AdamW(model.parameters(), lr=lr),
        loss_fn=loss_fn,
        inference_batches_factory=inference_batches,
    )


def _run(phase: str = "training", **over):
    kwargs = dict(
        build_components=_components,
        phase=phase,
        device="cpu",
        training_steps=3,
        inference_batches=2,
    )
    kwargs.update(over)
    return run_measured_phases(**kwargs)  # type: ignore[arg-type]


class TestTheTrainingPhaseIsReal:
    def test_forward_backward_and_step_all_happen(self):
        outcome = _run()
        assert outcome.status == "COMPLETED"
        assert outcome.realism.forward_calls == 3
        assert outcome.realism.backward_calls == 3
        assert outcome.realism.optimizer_steps == 3

    def test_a_trainable_parameter_actually_moves(self):
        """The single strongest realism proof: if the optimizer step moved
        nothing, the graph was detached and the backward was decorative."""
        outcome = _run()
        assert outcome.realism.parameter_update_verified is True
        delta = outcome.realism.parameter_update_max_abs_delta
        assert delta is not None and delta > 0.0

    def test_an_optimizer_over_the_wrong_module_is_caught(self):
        """The negative control for the test above.

        This is the defect shape that SURVIVES: the optimizer is built over
        a different module instance than the one being trained -- a
        one-word copy-paste error. Every count still looks perfect, the
        backward really runs, `step()` really executes, and the model being
        measured never moves. Only the parameter-delta check sees it.
        """

        def build() -> CandidateComponents:
            components = _components()
            return CandidateComponents(
                model=components.model,
                model_input=components.model_input,
                loss_target=components.loss_target,
                optimizer=torch.optim.AdamW(_TinyNet().parameters(), lr=0.1),
                loss_fn=components.loss_fn,
            )

        outcome = _run(build_components=build)
        assert outcome.status == "COMPLETED"
        assert outcome.realism.optimizer_steps == 3, "every count still looks right"
        assert outcome.realism.backward_calls == 3
        assert outcome.realism.parameter_update_verified is False
        assert outcome.realism.parameter_update_max_abs_delta == 0.0

    def test_a_detached_loss_is_reported_rather_than_crashing_the_worker(self):
        """Torch itself refuses to backward through a detached loss. The
        runner must turn that into a reported result -- a measurement
        process that dies on a bad candidate measures nothing."""
        outcome = _run(build_components=lambda: _components(detach=True))
        assert outcome.status == "WORKER_FAILURE"
        assert "does not require grad" in outcome.detail
        assert outcome.realism.backward_calls == 0

    def test_gradients_reach_the_parameters(self):
        """Directly: after the phase the watched parameter carries a
        non-zero gradient, which no forward-only probe can produce."""
        built: list[CandidateComponents] = []

        def build():
            components = _components()
            built.append(components)
            return components

        _run(build_components=build)
        grad = built[0].model.linear.weight.grad
        assert grad is not None
        assert torch.any(grad != 0)


class TestTheInferencePhaseRunsWithoutAutograd:
    def test_inference_builds_no_graph(self):
        outcome = _run(phase="inference")
        assert outcome.status == "COMPLETED"
        assert outcome.realism.inference_grad_free is True
        assert outcome.realism.inference_batches == 2

    def test_inference_takes_no_backward_and_no_step(self):
        """A retained activation graph is most of what a TRAINING peak is
        made of. If inference kept one, the inference requirement would be
        a training-shaped number."""
        outcome = _run(phase="inference")
        assert outcome.realism.backward_calls == 0
        assert outcome.realism.optimizer_steps == 0


class TestPhasesStaySeparate:
    def test_one_run_measures_setup_and_exactly_one_work_phase(self):
        """Production launches training and inference as separate
        subprocesses. Measuring both in one process would describe a
        process that never runs, and would leave the cumulative-peak trap
        that made `probe_production.py` unusable here."""
        training = _run("training")
        assert [p.phase for p in training.phases] == ["setup", "training"]
        inference = _run("inference")
        assert [p.phase for p in inference.phases] == ["setup", "inference"]

    def test_the_training_run_never_executes_an_inference_batch(self):
        assert _run("training").realism.inference_batches == 0

    def test_the_inference_run_never_executes_a_training_step(self):
        assert _run("inference").realism.optimizer_steps == 0

    def test_each_phase_carries_its_own_window(self):
        outcome = _run()
        setup = outcome.phases[0]
        work = outcome.phases[1]
        assert setup.ended_at <= work.started_at, (
            "the parent partitions its driver samples by these windows; "
            "overlapping windows would attribute one phase's memory to the other"
        )


class TestFailuresAreValuesNotExceptions:
    def test_a_setup_failure_is_reported_not_raised(self):
        def explode() -> CandidateComponents:
            raise RuntimeError("registry is empty")

        outcome = _run(build_components=explode)
        assert outcome.status == "WORKER_FAILURE"
        assert "registry is empty" in outcome.detail

    def test_a_phase_that_never_ran_is_marked_not_reached(self):
        """Distinct from "ran and produced nothing" -- collapsing the two
        would let an aborted run read as a complete one with no result."""

        def explode() -> CandidateComponents:
            raise RuntimeError("boom")

        outcome = _run(build_components=explode)
        assert outcome.phases[1].phase == "training"
        assert outcome.phases[1].status == "NOT_REACHED"

    def test_a_cuda_oom_during_training_is_classified_as_such(self):
        """PyTorch reports a device OOM as a RuntimeError whose text names
        CUDA; PR A's classifier is reused rather than rewritten."""

        def build() -> CandidateComponents:
            components = _components()

            def oom(output, tgt):
                raise RuntimeError("CUDA out of memory. Tried to allocate 20.00 GiB")

            return CandidateComponents(
                model=components.model,
                model_input=components.model_input,
                loss_target=components.loss_target,
                optimizer=components.optimizer,
                loss_fn=oom,
            )

        outcome = _run(build_components=build)
        assert outcome.status == "CUDA_OOM"
        assert outcome.phases[1].status == "CUDA_OOM"

    def test_a_partial_phase_reports_what_it_completed(self):
        """A short phase must be visible as short. Reporting only the peak
        would let three steps of a four-step measurement read as complete."""
        calls = {"n": 0}

        def build() -> CandidateComponents:
            components = _components()
            base = components.loss_fn

            def counting(output, tgt):
                calls["n"] += 1
                if calls["n"] > 2:
                    raise RuntimeError("kernel fault")
                return base(output, tgt)

            return CandidateComponents(
                model=components.model,
                model_input=components.model_input,
                loss_target=components.loss_target,
                optimizer=components.optimizer,
                loss_fn=counting,
            )

        outcome = _run(build_components=build)
        assert outcome.phases[1].units_executed == 2
        assert outcome.phases[1].units_requested == 3


class TestTheWorkerBudgetStopsCleanly:
    def test_an_exhausted_budget_ends_the_phase_with_partial_evidence(self):
        """The parent's kill is the hard deadline. This budget exists so
        the worker can stop and REPORT instead of being killed with its
        evidence lost."""
        ticks = iter([0.0, 0.0, 0.0, 0.0, 99.0, 99.0, 99.0, 99.0])

        outcome = _run(soft_deadline_seconds=5.0, elapsed_clock=lambda: next(ticks))
        assert outcome.status == "DEADLINE_EXCEEDED"
        assert "budget" in outcome.detail

    def test_no_budget_means_the_parent_is_the_only_bound(self):
        outcome = _run(soft_deadline_seconds=None)
        assert outcome.status == "COMPLETED"


class TestTheJournalSurvivesTheProcess:
    def test_boundaries_are_flushed_as_they_happen(self, tmp_path):
        """A worker killed at the deadline writes no report. Without the
        journal the parent could not say which phase was in flight, and an
        OOM during training would be indistinguishable from a crash."""
        path = tmp_path / "phases.ndjson"
        _run(journal=PhaseJournal(str(path)))
        events = [json.loads(line) for line in path.read_text().splitlines()]
        assert [(e["event"], e["phase"]) for e in events] == [
            ("phase_start", "setup"),
            ("phase_end", "setup"),
            ("phase_start", "training"),
            ("phase_end", "training"),
        ]

    def test_an_unwritable_journal_does_not_end_the_measurement(self, tmp_path):
        outcome = _run(journal=PhaseJournal(str(tmp_path / "missing-dir" / "j.ndjson")))
        assert outcome.status == "COMPLETED"


class TestAllocatorFiguresAreAbsentOffCuda:
    def test_a_cpu_run_reports_no_allocator_peak(self):
        """A zero here would be a number, and a number is admissible-looking.
        `None` says "not measured", which is the truth on the CPU."""
        outcome = _run()
        assert all(p.allocator_peak_mib is None for p in outcome.phases)


@pytest.mark.parametrize("phase", ["training", "inference"])
def test_the_phase_runner_never_raises_for_a_measurable_outcome(phase):
    """The control-flow rule: every outcome O-7 has a rule for arrives as a
    typed value, not through an `except` block."""

    def build() -> CandidateComponents:
        raise RuntimeError("CUDA out of memory")

    outcome = run_measured_phases(
        build_components=build, phase=phase, device="cpu", training_steps=1
    )
    assert outcome.status == "CUDA_OOM"


class TestAShortPhaseIsMadeObservable:
    """D-C2-13/14. Gate 2 Lite-A c7 ran inference in 0.138 s against a
    0.25 s cadence: ZERO in-phase samples, so the phase was unmeasurable at
    any candidate speed. Attempt 3 then hit a 40-repetition ceiling after
    0.344 s still holding ONE sample -- a repetition COUNT cannot express a
    duration target when the per-repetition cost is unknown.

    So the PARENT decides: it counts the samples that actually landed and
    signals completion. These drive that signal directly.
    """

    def _after(self, n: int):
        """A completion signal that reports 'enough' only on call `n`."""
        calls = {"n": 0}

        def signal() -> bool:
            calls["n"] += 1
            return calls["n"] > n

        return signal

    def test_the_phase_repeats_until_the_parent_says_enough(self):
        outcome = _run("training", training_steps=1, phase_observed_enough=self._after(5))
        work = outcome.phases[1]
        assert work.repetitions == 6
        assert work.completion_reason == "sample_target_reached"
        assert work.observation_bound_reached is False

    def test_no_fixed_repetition_ceiling_terminates_a_fast_phase(self):
        """The attempt-3 defect, directly: 40 repetitions was reached in
        0.344 s and stopped the phase one sample short. Nothing may cut the
        phase off at a guessed count."""
        outcome = _run("training", training_steps=1, phase_observed_enough=self._after(120))
        assert outcome.phases[1].repetitions == 121
        assert outcome.phases[1].completion_reason == "sample_target_reached"

    def test_a_phase_already_observed_is_not_repeated(self):
        """Positive control: repetition is a remedy, not a default."""
        outcome = _run("training", training_steps=1, phase_observed_enough=lambda: True)
        assert outcome.phases[1].repetitions == 1
        assert outcome.phases[1].completion_reason == "sample_target_reached"

    def test_the_duration_bound_still_stops_it(self):
        """With the count gone, time is the only normal bound -- so it has
        to work."""
        ticks = iter([0.0, 0.0] + [50.0 * i for i in range(1, 400)])
        outcome = _run(
            "training",
            training_steps=1,
            phase_observed_enough=lambda: False,
            max_phase_seconds=10.0,
            elapsed_clock=lambda: next(ticks),
        )
        work = outcome.phases[1]
        assert work.observation_bound_reached is True
        assert work.completion_reason == "duration_bound"

    def test_the_worker_budget_still_stops_it(self):
        ticks = iter([0.0] * 6 + [99.0] * 400)
        outcome = _run(
            "training",
            training_steps=1,
            phase_observed_enough=lambda: False,
            soft_deadline_seconds=5.0,
            max_phase_seconds=1_000.0,
            elapsed_clock=lambda: next(ticks),
        )
        assert outcome.phases[1].completion_reason == "deadline"

    def test_repetition_preserves_the_workload_exactly(self):
        """Same model, same batch, same semantics -- repetition is
        measurement protocol, not a different candidate."""
        outcome = _run("training", training_steps=2, phase_observed_enough=self._after(2))
        assert outcome.realism.optimizer_steps == 6, "2 steps x 3 repetitions"
        assert outcome.realism.inference_batches == 0

    def test_training_repetition_stays_model_connected(self):
        """The same remedy applies to training, so a faster model does not
        reintroduce the c7 gap."""
        outcome = _run("training", training_steps=2, phase_observed_enough=self._after(2))
        assert outcome.realism.optimizer_steps == 6
        assert outcome.realism.backward_calls == 6
        assert outcome.realism.parameter_update_verified is True

    def test_a_failing_phase_is_never_repeated(self):
        """Repeating a phase that already failed would multiply the failure
        and hide when it first happened."""

        def build() -> CandidateComponents:
            components = _components()

            def boom(output, tgt):
                raise RuntimeError("kernel fault")

            return CandidateComponents(
                model=components.model,
                model_input=components.model_input,
                loss_target=components.loss_target,
                optimizer=components.optimizer,
                loss_fn=boom,
            )

        outcome = _run(build_components=build, phase_observed_enough=self._after(10))
        assert outcome.phases[1].repetitions == 1
        assert outcome.phases[1].completion_reason == "failed"

    def test_without_a_parent_signal_the_phase_runs_once(self):
        outcome = _run("training")
        assert outcome.phases[1].repetitions == 1
        assert outcome.phases[1].completion_reason == "single_pass"

    def test_the_required_count_is_recorded(self):
        outcome = _run("training", min_authoritative_samples=3, phase_observed_enough=lambda: True)
        assert outcome.phases[1].required_samples == 3


class TestTheSamplerHandshake:
    """A phase must not open before anything is watching."""

    def test_the_phase_waits_for_the_sampler(self):
        order: list[str] = []
        outcome = _run(await_sampler_ready=lambda: order.append("ready") or True)
        assert order == ["ready"]
        assert outcome.phases[1].sampler_ready is True

    def test_a_timed_out_handshake_is_reported_not_ignored(self):
        """The phase still runs -- the parent's coverage decides what is
        admissible -- but the record says the sampler was never confirmed."""
        outcome = _run(await_sampler_ready=lambda: False)
        assert outcome.phases[1].sampler_ready is False

    def test_the_handshake_precedes_the_work(self):
        """Confirming afterwards would prove nothing about the window that
        was just measured."""
        events: list[str] = []

        def build() -> CandidateComponents:
            components = _components()
            base = components.loss_fn

            def watched(output, tgt):
                events.append("work")
                return base(output, tgt)

            return CandidateComponents(
                model=components.model,
                model_input=components.model_input,
                loss_target=components.loss_target,
                optimizer=components.optimizer,
                loss_fn=watched,
            )

        _run(build_components=build, await_sampler_ready=lambda: events.append("ready") or True)
        assert events[0] == "ready"


class TestInferenceHoldsOneRealStateInsteadOfRepeating:
    """D-C2-18. Repeating the inference forward to obtain samples grew the
    caching allocator's pool -- 14 repetitions x 3 batches reserved 4266 MiB
    against 2588 MiB allocated, and the driver figure counts reserved. That
    inflated inference to 4870 MiB against a real 3642 MiB and opened a
    false-refusal band at a 4 GiB ceiling.

    The workload now runs exactly as configured, and the real post-forward
    state is HELD open long enough to be seen. Holding allocates nothing.
    """

    def test_only_the_configured_batches_execute(self):
        """The defect, directly: no measurement-only forwards."""
        outcome = _run("inference", inference_batches=3, phase_observed_enough=lambda: True)
        assert outcome.realism.inference_batches == 3, "exactly the configured count"
        assert outcome.phases[1].repetitions == 1, "no repetition for observability"

    def test_it_does_not_repeat_even_when_the_parent_wants_more_samples(self):
        """A parent that never says 'enough' must not cause extra forwards
        -- the bound is time, not more allocation."""
        outcome = _run(
            "inference",
            inference_batches=2,
            phase_observed_enough=lambda: False,
            max_phase_seconds=0.5,
        )
        assert outcome.realism.inference_batches == 2
        assert outcome.phases[1].repetitions == 1

    def test_the_hold_happens_once_per_configured_batch(self):
        outcome = _run("inference", inference_batches=3, phase_observed_enough=lambda: True)
        assert outcome.realism.peak_state_holds == 3

    def test_the_output_is_still_resident_during_the_hold(self):
        """The hold must expose the REAL peak state. If it ran after the
        output was released it would sample a smaller, meaningless one."""
        import weakref

        seen: list[bool] = []
        holder: dict[str, object] = {}

        def build() -> CandidateComponents:
            components = _components()
            real_forward = components.model.forward

            def watched(x):
                out = real_forward(x)
                # A WEAK reference: a strong one here would keep the tensor
                # alive by itself and the test could not tell whether the
                # runner had released it.
                holder["ref"] = weakref.ref(out)
                return out

            components.model.forward = watched
            return components

        def hold() -> bool:
            ref = holder.get("ref")
            seen.append(ref is not None and ref() is not None)
            return True

        _run("inference", inference_batches=1, build_components=build, phase_observed_enough=hold)
        assert seen == [True]

    def test_the_output_lifetime_matches_the_production_task_stream(self):
        """The prior batch and its last view remain live during the next forward.

        Releasing them early would under-read the actual task inference loop.
        Weak references observe lifetime without changing it.
        """
        import gc
        import weakref

        refs: list[weakref.ref] = []
        alive_at_forward: list[int] = []

        def build() -> CandidateComponents:
            components = _components()
            real_forward = components.model.forward

            def watched(x):
                gc.collect()
                alive_at_forward.append(sum(1 for r in refs if r() is not None))
                out = real_forward(x)
                refs.append(weakref.ref(out))
                return out

            components.model.forward = watched
            return components

        outcome = _run(
            "inference",
            inference_batches=3,
            build_components=build,
            phase_observed_enough=lambda: True,
        )
        assert len(alive_at_forward) == 3, "all three configured batches must still run"
        assert alive_at_forward == [0, 1, 1]
        assert outcome.realism.outputs_released == 0

    def test_every_executed_batch_records_real_coverage(self):
        """Coverage counts real consumed examples and does not claim early releases."""
        for batches in (1, 2, 3):
            outcome = _run(
                "inference", inference_batches=batches, phase_observed_enough=lambda: True
            )
            assert outcome.realism.outputs_released == 0
            assert outcome.realism.inference_batches == batches
            assert outcome.realism.inference_data.consumed_samples == 2 * batches

    def test_data_coverage_does_not_imply_driver_sampling_succeeded(self):
        outcome = _run("inference", inference_batches=3, phase_observed_enough=lambda: False)
        assert outcome.realism.outputs_released == 0
        assert outcome.realism.peak_state_observed is False

    def test_a_confirmed_hold_records_the_sample_target_as_reached(self):
        outcome = _run("inference", inference_batches=1, phase_observed_enough=lambda: True)
        assert outcome.realism.peak_state_observed is True
        assert outcome.phases[1].completion_reason == "sample_target_reached"

    def test_an_unconfirmed_hold_is_not_recorded_as_observed(self):
        """Fails closed: the parent never confirmed three samples."""
        outcome = _run("inference", inference_batches=1, phase_observed_enough=lambda: False)
        assert outcome.realism.peak_state_observed is False

    def test_inference_still_never_backwards_or_steps(self):
        outcome = _run("inference", inference_batches=2, phase_observed_enough=lambda: True)
        assert outcome.realism.backward_calls == 0
        assert outcome.realism.optimizer_steps == 0

    def test_training_is_unchanged_and_still_repeats(self):
        """Training matched formal to 2 MiB (1474 vs 1476) and must not be
        disturbed by the inference correction."""
        calls = {"n": 0}

        def after_two() -> bool:
            calls["n"] += 1
            return calls["n"] > 2

        outcome = _run("training", training_steps=1, phase_observed_enough=after_two)
        assert outcome.phases[1].repetitions == 3
        assert outcome.realism.peak_state_holds == 0, "training does not hold"
