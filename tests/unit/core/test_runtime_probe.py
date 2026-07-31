"""C6a — bounded live probe engine (pure orchestration, fake executors).

Covers: caps honored (wall cap at every stage), OOM/load-failure paths
preserve partial measured evidence, concurrency classification
(count-based, D3-neutral), realized-property capture, §16.6
training/inference separation through extrapolation, probe→registry
observation records, and the §7.4 authority interplay (clean probe
blocking-capable; contended probe demoted; measured failures REJECT).
No GPU, no torch, no data — executors are injected fakes (repo unit
standard); the production executors run only in the operator-gated GPU
smoke."""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.decision_policy import (
    RuntimeBudget,
    RuntimeDecisionPolicy,
    RuntimeMode,
)
from core.runtime_control.probe import (
    ContentionSnapshot,
    ProbeCaps,
    ProbeExecutors,
    RealizedModelProperties,
    capture_contention_snapshot,
    extrapolate_probe,
    probe_observations,
    run_bounded_probe,
)

REALIZED = RealizedModelProperties(
    parameter_count=5_000_000,
    trainable_parameter_count=5_000_000,
    parameter_memory_gb=0.02,
    dtype="float32",
)

IDLE = ContentionSnapshot(
    foreign_compute_processes=0,
    gpu_utilization_pct=0.0,
    gpu_memory_used_gb=0.3,
    telemetry_available=True,
)
BUSY = ContentionSnapshot(
    foreign_compute_processes=2,
    gpu_utilization_pct=80.0,
    gpu_memory_used_gb=10.0,
    telemetry_available=True,
)
BLIND = ContentionSnapshot(telemetry_available=False)


def _executors(
    *,
    train_ms=(20.0, 21.0, 22.0, 20.5, 21.5, 20.0, 21.0, 22.0, 20.0, 21.0),
    inf_ms=(50.0, 51.0, 52.0, 50.0, 51.0),
    setup=lambda: REALIZED,
    peak=lambda: 4.2,
) -> ProbeExecutors:
    train_iter = iter(train_ms)
    inf_iter = iter(inf_ms)
    return ProbeExecutors(
        setup=setup,
        train_step=lambda: next(train_iter),
        inference_batch=lambda: next(inf_iter),
        peak_vram_gb=peak,
    )


def _window(samples, *, peer_pids=()):
    """C8e: the probe now consumes a bounded WINDOW. Tests inject a
    deterministic one built by the real D3 classifier, so the engine's
    behavior is exercised against the production classification path."""
    from core.runtime_control.calibration_policy import sample_contention_window

    def _sampler(**kwargs):
        it = iter(samples)
        last = samples[-1]
        return sample_contention_window(
            device_vram_gb=kwargs.get("device_vram_gb", 32.0),
            expected_peer_pids=kwargs.get("expected_peer_pids", peer_pids),
            capture=lambda *a, **k: next(it, last),
            sleep=lambda _s: None,
        )

    return _sampler


def _probe(**kw):
    defaults = dict(
        model_identity="probe_target",
        executors=_executors(),
        device_vram_gb=32.0,
        contention_window=_window([IDLE] * 5),
    )
    defaults.update(kw)
    return run_bounded_probe(**defaults)


class TestConcurrencyClassification:
    def test_probe_uses_the_windowed_classifier(self):
        """C8e: no count-based fallback remains — the identity on the
        result is the D3 window's verdict, and every raw sample it rests
        on is carried on the result."""
        result = _probe()
        assert result.concurrency_identity == "single_candidate_idle"
        assert len(result.contention_telemetry["samples"]) == 5
        assert result.contention_telemetry["policy_identity"].startswith("calibration_policy@")
        assert result.contention_telemetry["reasons"]

    def test_foreign_process_contends_and_peer_pid_does_not(self):
        busy = ContentionSnapshot(
            foreign_compute_processes=1,
            foreign_compute_pids=(4242,),
            gpu_utilization_pct=5.0,
            gpu_memory_used_gb=0.5,
            telemetry_available=True,
        )
        assert _probe(contention_window=_window([busy] * 5)).concurrency_identity == (
            "foreign_contended"
        )
        paired = _probe(
            contention_window=_window([busy] * 5, peer_pids=(4242,)),
            expected_peer_pids=(4242,),
        )
        assert paired.concurrency_identity == "pairwise_expected_peer"

    def test_telemetry_gap_is_unknown_contention(self):
        assert _probe(contention_window=_window([BLIND] * 5)).concurrency_identity == (
            "unknown_contention"
        )

    def test_count_based_classifier_is_gone(self):
        import core.runtime_control.probe as probe_mod

        assert not hasattr(probe_mod, "classify_concurrency")

    def test_snapshot_failure_records_gap(self, monkeypatch):
        import subprocess

        def _boom(*a, **k):
            raise FileNotFoundError("nvidia-smi not found")

        monkeypatch.setattr(subprocess, "run", _boom)
        snap = capture_contention_snapshot()
        assert snap.telemetry_available is False
        assert snap.foreign_compute_processes is None


class TestProbeEngine:
    def test_ok_path_measures_all_phases(self):
        r = _probe()
        assert r.status == "ok"
        assert r.realized == REALIZED
        assert r.setup_seconds is not None
        assert r.train_ms_per_step == 21.0  # median of 7 timed (3 warmup dropped)
        assert r.train_ms_spread == (20.0, 22.0)
        assert r.inference_ms_per_batch == 51.0
        assert r.peak_vram_gb == 4.2
        assert r.concurrency_identity == "single_candidate_idle"

    def test_warmup_steps_excluded_from_timing(self):
        r = _probe(
            executors=_executors(
                train_ms=(999.0, 999.0, 999.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0)
            )
        )
        assert r.train_ms_per_step == 10.0

    def test_setup_load_failure(self):
        def _bad_setup():
            raise RuntimeError("plugin import exploded")

        r = _probe(executors=_executors(setup=_bad_setup))
        assert r.status == "load_failure"
        assert "plugin import exploded" in (r.error or "")

    def test_setup_oom(self):
        def _oom():
            raise MemoryError("CUDA OOM")

        r = _probe(executors=_executors(setup=_oom))
        assert r.status == "oom"

    def test_training_oom_preserves_partial_evidence(self):
        timings = iter([20.0, 20.0, 20.0, 21.0, 21.0])

        def _train():
            try:
                return next(timings)
            except StopIteration:
                raise MemoryError("OOM at step 6") from None

        ex = ProbeExecutors(
            setup=lambda: REALIZED,
            train_step=_train,
            inference_batch=lambda: 1.0,
            peak_vram_gb=lambda: 30.5,
        )
        r = run_bounded_probe(
            model_identity="m",
            executors=ex,
            device_vram_gb=32.0,
            contention_window=_window([IDLE] * 5),
        )
        assert r.status == "oom"
        assert r.peak_vram_gb == 30.5  # measured peak preserved
        assert r.realized == REALIZED

    def test_wall_cap_during_training(self):
        t = {"now": 0.0}

        def _clock():
            return t["now"]

        def _train():
            t["now"] += 30.0
            return 30_000.0

        ex = ProbeExecutors(
            setup=lambda: REALIZED,
            train_step=_train,
            inference_batch=lambda: 1.0,
            peak_vram_gb=lambda: 2.0,
        )
        r = run_bounded_probe(
            model_identity="m",
            executors=ex,
            device_vram_gb=32.0,
            contention_window=_window([IDLE] * 5),
            caps=ProbeCaps(max_wall_seconds=90.0),
            clock=_clock,
        )
        assert r.status == "wall_cap"
        assert "training steps" in (r.error or "")

    def test_caps_are_recorded_on_the_result(self):
        caps = ProbeCaps(max_wall_seconds=45.0, n_timed_train_steps=3)
        r = _probe(
            caps=caps,
            executors=_executors(train_ms=(1.0,) * 6, inf_ms=(2.0,) * 5),
        )
        assert r.caps == caps


class TestExtrapolationAndAuthority:
    def test_phases_stay_separate(self):
        r = _probe()
        est = extrapolate_probe(r, train_steps=25_000, inference_batches=400, producer_identity="p")
        assert est.training_seconds == pytest.approx(21.0 * 25_000 / 1000.0)
        assert est.inference_seconds == pytest.approx(51.0 * 400 / 1000.0)
        assert est.setup_seconds == r.setup_seconds
        assert est.provenance == "bounded_live_probe"
        assert est.lower_seconds is not None and est.upper_seconds is not None
        assert est.lower_seconds < est.expected_seconds < est.upper_seconds

    def test_non_ok_probe_cannot_extrapolate(self):
        r = _probe(executors=_executors(setup=lambda: (_ for _ in ()).throw(MemoryError())))
        with pytest.raises(ValueError, match="non-ok"):
            extrapolate_probe(r, train_steps=1, inference_batches=1, producer_identity="p")

    def test_clean_probe_estimate_is_blocking_capable(self):
        est = extrapolate_probe(
            _probe(), train_steps=25_000, inference_batches=400, producer_identity="p"
        )
        assert est.blocking_eligible is True
        assert est.formal_execution_eligible is False  # verification is RT2's job

    def test_contended_probe_estimate_is_demoted(self):
        r = _probe(contention_window=_window([BUSY] * 5))
        est = extrapolate_probe(r, train_steps=25_000, inference_batches=400, producer_identity="p")
        assert est.concurrency_identity == "foreign_contended"
        assert est.blocking_eligible is False

    def test_probe_oom_maps_to_reject_via_policy(self):
        policy = RuntimeDecisionPolicy()
        est = extrapolate_probe(
            _probe(), train_steps=10, inference_batches=1, producer_identity="p"
        )
        d = policy.decide(
            est,
            RuntimeBudget(time_seconds=10_000.0),
            RuntimeMode(phase="trial", candidate_stage="post_implementation"),
            measured_failure="oom",
        )
        assert d.kind == "REJECT"


class TestProbeObservations:
    def test_distinct_training_and_inference_records(self, tmp_path):
        r = _probe()
        obs = probe_observations(
            r,
            hardware_compatibility_id="sha256:" + "a" * 64,
            execution_environment_id="sha256:" + "b" * 64,
            workload={"batch_size": 8, "segment_length": 40_000},
            software_stack={"torch": "2.7.0"},
            source_run={"run_name": "unit"},
            timestamp_metadata="2026-07-30T12:00:00Z",
        )
        assert [o.operation for o in obs] == ["training", "inference"]
        assert all(o.validation_status == "unvalidated" for o in obs)
        assert all(o.provenance == "bounded_live_probe" for o in obs)
        assert obs[0].realized_model["parameter_count"] == 5_000_000
        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        ids = [registry.record_observation(o) for o in obs]
        assert registry.load_manifest().observation_ids == sorted(ids)

    def test_non_ok_probe_produces_no_observations(self):
        r = _probe(executors=_executors(setup=lambda: (_ for _ in ()).throw(MemoryError())))
        with pytest.raises(ValueError, match="only ok probes"):
            probe_observations(
                r,
                hardware_compatibility_id="sha256:" + "a" * 64,
                execution_environment_id="sha256:" + "b" * 64,
                workload={},
                software_stack={},
                source_run={},
            )


class TestSelfPidExclusion:
    def test_own_process_is_not_foreign(self, monkeypatch):
        """C6 GPU-smoke regression (2026-07-30): the probing process's own
        CUDA context appeared in --query-compute-apps and was counted as
        foreign, misclassifying an idle GPU as foreign_contended."""
        import os
        import subprocess
        from types import SimpleNamespace

        own = str(os.getpid())

        def _fake_run(cmd, **kw):
            if "--query-gpu=utilization.gpu,memory.used" in cmd[1]:
                return SimpleNamespace(stdout="5, 1024\n")
            return SimpleNamespace(stdout=f"{own}\n")  # only ourselves

        monkeypatch.setattr(subprocess, "run", _fake_run)
        snap = capture_contention_snapshot()
        assert snap.telemetry_available is True
        assert snap.foreign_compute_processes == 0
        from core.runtime_control.calibration_policy import classify_contention_window

        assert (
            classify_contention_window([snap] * 5, device_vram_gb=32.0)[0]
            == "single_candidate_idle"
        )

    def test_other_processes_still_counted(self, monkeypatch):
        import os
        import subprocess
        from types import SimpleNamespace

        own = str(os.getpid())

        def _fake_run(cmd, **kw):
            if "--query-gpu=utilization.gpu,memory.used" in cmd[1]:
                return SimpleNamespace(stdout="50, 8000\n")
            return SimpleNamespace(stdout=f"{own}\n12345\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        snap = capture_contention_snapshot()
        assert snap.foreign_compute_processes == 1

    # ── C7/D3 telemetry enrichment ─────────────────────────────────────
    def test_descendant_pids_finds_a_real_child(self):
        import os
        import subprocess

        from core.runtime_control.probe import descendant_pids

        child = subprocess.Popen(["sleep", "5"])
        try:
            assert child.pid in descendant_pids(os.getpid())
        finally:
            child.kill()
            child.wait()

    def test_child_pids_are_excluded_from_the_foreign_set(self, monkeypatch):
        """D3: a probe's own dataloader/worker subprocesses are not
        foreign — only genuinely external PIDs are."""
        import os
        import subprocess
        from types import SimpleNamespace

        from core.runtime_control import probe as probe_mod

        own, child, stranger = os.getpid(), 424242, 999999
        monkeypatch.setattr(probe_mod, "descendant_pids", lambda _pid: frozenset({child}))
        monkeypatch.setattr(probe_mod, "_query_throttle_reasons", lambda: 0x4)

        def _fake_run(cmd, **kw):
            if "--query-gpu=utilization.gpu,memory.used" in cmd[1]:
                return SimpleNamespace(stdout="7, 2048\n")
            return SimpleNamespace(stdout=f"{own}\n{child}\n{stranger}\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        snap = capture_contention_snapshot()
        assert snap.compute_process_pids == (own, child, stranger)
        assert snap.foreign_compute_pids == (stranger,)
        assert snap.foreign_compute_processes == 1
        assert own in snap.excluded_pids and child in snap.excluded_pids
        assert snap.throttle_reasons_hex == 0x4

    def test_explicitly_excluded_pids_are_honored(self, monkeypatch):
        import os
        import subprocess
        from types import SimpleNamespace

        from core.runtime_control import probe as probe_mod

        monkeypatch.setattr(probe_mod, "descendant_pids", lambda _pid: frozenset())
        monkeypatch.setattr(probe_mod, "_query_throttle_reasons", lambda: None)

        def _fake_run(cmd, **kw):
            if "--query-gpu=utilization.gpu,memory.used" in cmd[1]:
                return SimpleNamespace(stdout="7, 2048\n")
            return SimpleNamespace(stdout=f"{os.getpid()}\n555\n")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        assert capture_contention_snapshot().foreign_compute_processes == 1
        snap = capture_contention_snapshot(exclude_pids=[555])
        assert snap.foreign_compute_processes == 0
        assert snap.throttle_reasons_hex is None

    def test_probe_observations_carry_the_declared_family(self):
        from core.runtime_control.probe import probe_observations

        records = probe_observations(
            _probe(),
            hardware_compatibility_id="sha256:" + "a" * 64,
            execution_environment_id="sha256:" + "b" * 64,
            workload={"batch_size": 8},
            software_stack={"torch": "2.7.0"},
            source_run={"run_name": "t"},
            model_family="punet",
        )
        assert {r.model_family for r in records} == {"punet"}
        assert {
            r.model_family
            for r in probe_observations(
                _probe(),
                hardware_compatibility_id="sha256:" + "a" * 64,
                execution_environment_id="sha256:" + "b" * 64,
                workload={"batch_size": 8},
                software_stack={"torch": "2.7.0"},
                source_run={"run_name": "t"},
            )
        } == {"unknown"}


class TestRealCudaOomClassification:
    """C12 finding (2026-07-31): `torch.cuda.OutOfMemoryError` subclasses
    RuntimeError, NOT MemoryError. Every OOM handler caught MemoryError,
    so a real CUDA OOM escaped unclassified — and the C9b resolver then
    turned that into ABORT, halting the chain for a candidate that merely
    did not fit. These tests use a CUDA-SHAPED exception, because the old
    ones used MemoryError, a shape production cannot produce.
    """

    class _CudaOom(RuntimeError):
        """Same name and base class as torch.cuda.OutOfMemoryError."""

        __name__ = "OutOfMemoryError"

    def _cuda_oom(self):
        exc = type("OutOfMemoryError", (RuntimeError,), {})(
            "CUDA out of memory. Tried to allocate 158.00 MiB. GPU 0 has a total "
            "capacity of 31.34 GiB of which 115.31 MiB is free."
        )
        return exc

    def test_the_detector_recognises_a_real_cuda_oom(self):
        from core.runtime_control.probe import is_out_of_memory

        assert is_out_of_memory(self._cuda_oom()) is True
        assert is_out_of_memory(MemoryError("host oom")) is True
        # message-based fallback for backends this repo does not import
        assert is_out_of_memory(RuntimeError("HIP out of memory")) is True
        # and it must not swallow unrelated failures
        assert is_out_of_memory(RuntimeError("shape mismatch")) is False
        assert is_out_of_memory(KeyError("missing")) is False

    def test_a_cuda_oom_during_setup_is_measured_not_a_load_failure(self):
        def _boom():
            raise self._cuda_oom()

        result = _probe(executors=_executors(setup=_boom))
        assert result.status == "oom"  # was "load_failure" before the fix
        assert "setup OOM" in (result.error or "")

    def test_a_cuda_oom_during_training_is_measured_not_an_escape(self):
        timings = iter([20.0, 20.0, 20.0, 21.0])

        def _train():
            try:
                return next(timings)
            except StopIteration:
                raise self._cuda_oom() from None

        result = _probe(
            executors=ProbeExecutors(
                setup=lambda: REALIZED,
                train_step=_train,
                inference_batch=lambda: 1.0,
                peak_vram_gb=lambda: 30.9,
            )
        )
        assert result.status == "oom"
        assert result.peak_vram_gb == 30.9  # the measured peak survives

    def test_a_cuda_oom_during_inference_is_measured(self):
        def _infer():
            raise self._cuda_oom()

        result = _probe(
            executors=ProbeExecutors(
                setup=lambda: REALIZED,
                train_step=lambda: 20.0,
                inference_batch=_infer,
                peak_vram_gb=lambda: 12.0,
            )
        )
        assert result.status == "oom"
        assert "inference OOM" in (result.error or "")

    def test_a_non_oom_runtime_error_still_propagates(self):
        """The fix must not turn every RuntimeError into an OOM."""

        def _train():
            raise RuntimeError("expected 3 channels, got 1")

        with pytest.raises(RuntimeError, match="expected 3 channels"):
            _probe(
                executors=ProbeExecutors(
                    setup=lambda: REALIZED,
                    train_step=_train,
                    inference_batch=lambda: 1.0,
                    peak_vram_gb=lambda: 1.0,
                )
            )
