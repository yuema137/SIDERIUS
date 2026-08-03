"""Host-memory isolation for the VRAM pre-flight.

On 2026-07-31 a Transformer candidate's pre-flight grew to 60.5 GB of
anonymous RSS on a 61 GB host and the kernel OOM-killer reaped the whole
validation process. The GPU sat at 273 MiB — VRAM was never the
constraint. Nothing was measured about that candidate, because the
process that was supposed to measure it died.

The protection that used to prevent this was accidental: a 60-second
alarm whose own comment recorded that it existed because "a Python
time-loop inside forward() at long T will burn host RAM linearly under
autograd". Wall time was standing in for a memory bound, and removing
the timeout to fix a different defect removed it.

Every test drives a synthetic worker — a short program that allocates,
stalls, lies, or crashes — so the isolation guarantees are proved without
a GPU and without endangering the host.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.skills.evaluate_vram_skill.isolated_probe import (
    HOST_MEMORY_OUTCOMES,
    NO_DOWNSIZING_AUTHORITY,
    VRAM_CAPACITY_OUTCOMES,
    HostMemoryEvidence,
    IsolatedProbeResult,
    IsolatedProbeSpec,
    default_worker_memory_limit_bytes,
    run_isolated_preflight,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
MIB = 1024**2


def _spec(tmp_path: Path, limit_mib: int = 512, **over) -> IsolatedProbeSpec:
    base = dict(
        label="synthetic",
        model_type="fake_candidate",
        vram_budget_gb=12.0,
        result_path=str(tmp_path / "result.json"),
        worker_memory_limit_bytes=limit_mib * MIB,
    )
    base.update(over)
    return IsolatedProbeSpec(**base)


def _worker(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "synthetic_worker.py"
    script.write_text(body, encoding="utf-8")
    import sys

    return [sys.executable, str(script)]


GROWS_FOREVER = """
import time
blocks = []
while True:
    blocks.append(bytearray(64 * 1024 * 1024))   # 64 MiB at a time
    time.sleep(0.01)
"""

STALLS = """
import signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)   # worst case
time.sleep(600)
"""

COMPLETES = """
import json, sys
json.dump({{
    "outcome": "COMPLETED_MEASUREMENT",
    "realized_parameter_count": 323281352,
    "estimated_gb": 5.732,
    "inference_batch": 16,
    "phase": "complete",
}}, open(r"{result}", "w"))
"""

REPORTS_CUDA_OOM = """
import json
json.dump({{"outcome": "MEASURED_CUDA_OOM", "detail": "CUDA out of memory",
           "phase": "cuda_probe"}}, open(r"{result}", "w"))
"""

CORRUPT_RESULT = """
open(r"{result}", "w").write("{{not valid json")
"""

DIES_SILENTLY = """
import os, signal
os.kill(os.getpid(), signal.SIGKILL)
"""


class TestHostMemoryBound:
    """The regression: a worker that grows without limit."""

    def test_a_growing_worker_is_stopped_at_the_limit(self, tmp_path):
        started = time.monotonic()
        result = run_isolated_preflight(
            _spec(tmp_path, limit_mib=512),
            deadline_seconds=60.0,
            command=_worker(tmp_path, GROWS_FOREVER),
        )
        elapsed = time.monotonic() - started

        assert result.outcome == "MEASURED_HOST_MEMORY_EXCEEDED"
        assert elapsed < 45.0, "the memory bound must fire well before the deadline"
        assert result.host_memory is not None
        assert result.host_memory.exceeded is True
        assert result.host_memory.peak_worker_rss_gib > 0

    def test_the_parent_survives_it(self, tmp_path):
        """The whole point: the controller must outlive the candidate."""
        run_isolated_preflight(
            _spec(tmp_path, limit_mib=512),
            deadline_seconds=60.0,
            command=_worker(tmp_path, GROWS_FOREVER),
        )
        assert os.getpid() > 0  # reached at all == the parent was not killed

    def test_no_descendant_survives(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path, limit_mib=512),
            deadline_seconds=60.0,
            command=_worker(tmp_path, GROWS_FOREVER),
        )
        assert result.orphans_remaining is False
        assert result.worker_pgid is not None
        with pytest.raises(ProcessLookupError):
            os.killpg(result.worker_pgid, 0)

    def test_host_memory_evidence_is_recorded_even_when_fine(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=30.0,
            command=_worker(tmp_path, COMPLETES.format(result=tmp_path / "result.json")),
        )
        assert result.host_memory is not None
        assert result.host_memory.exceeded is False
        assert result.host_memory.limit_gib > 0


class TestDeadline:
    def test_a_stalled_worker_hits_the_deadline_not_the_memory_bound(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=1.0,
            grace_seconds=0.5,
            command=_worker(tmp_path, STALLS),
        )
        assert result.outcome == "MEASURED_HARD_TIMEOUT"
        assert result.host_memory is not None
        assert result.host_memory.exceeded is False
        assert result.orphans_remaining is False

    def test_a_timeout_carries_no_downsizing_authority(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=1.0,
            grace_seconds=0.5,
            command=_worker(tmp_path, STALLS),
        )
        assert result.may_recommend_vram_downsizing is False
        assert result.may_recommend_host_memory_reduction is False


class TestResultClassification:
    def test_a_completed_measurement_is_passed_through(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=30.0,
            command=_worker(tmp_path, COMPLETES.format(result=tmp_path / "result.json")),
        )
        assert result.outcome == "COMPLETED_MEASUREMENT"
        assert result.realized_parameter_count == 323281352
        assert result.estimated_gb == 5.732

    def test_a_reported_cuda_oom_stays_a_cuda_oom(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=30.0,
            command=_worker(tmp_path, REPORTS_CUDA_OOM.format(result=tmp_path / "result.json")),
        )
        assert result.outcome == "MEASURED_CUDA_OOM"
        assert result.may_recommend_vram_downsizing is True
        assert result.may_recommend_host_memory_reduction is False

    def test_a_corrupt_result_is_infrastructure_not_a_measurement(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=30.0,
            command=_worker(tmp_path, CORRUPT_RESULT.format(result=tmp_path / "result.json")),
        )
        assert result.outcome == "PROBE_INFRASTRUCTURE_FAILURE"
        assert result.has_capacity_authority is False

    def test_a_silent_kill_far_below_the_limit_is_not_a_clean_result(self, tmp_path):
        """Exit 137 with no evidence must not be dressed up as measured."""
        result = run_isolated_preflight(
            _spec(tmp_path, limit_mib=4096),
            deadline_seconds=30.0,
            command=_worker(tmp_path, DIES_SILENTLY),
        )
        assert result.outcome == "PROBE_INFRASTRUCTURE_FAILURE"
        assert result.signal_number == signal.SIGKILL
        assert result.outcome != "COMPLETED_MEASUREMENT"

    def test_an_unlaunchable_worker_is_infrastructure(self, tmp_path):
        result = run_isolated_preflight(_spec(tmp_path), command=["/nonexistent/interpreter", "x"])
        assert result.outcome == "PROBE_INFRASTRUCTURE_FAILURE"


class TestAuthoritySeparation:
    """Host memory and VRAM are different constraints."""

    @pytest.mark.parametrize("outcome", sorted(VRAM_CAPACITY_OUTCOMES))
    def test_vram_outcomes_grant_vram_authority_only(self, outcome):
        r = IsolatedProbeResult(label="x", outcome=outcome, vram_cap_gb=12.0)
        assert r.may_recommend_vram_downsizing is True
        assert r.may_recommend_host_memory_reduction is False

    @pytest.mark.parametrize("outcome", sorted(HOST_MEMORY_OUTCOMES))
    def test_host_outcomes_never_grant_vram_authority(self, outcome):
        r = IsolatedProbeResult(label="x", outcome=outcome, vram_cap_gb=12.0)
        assert r.may_recommend_vram_downsizing is False
        assert r.may_recommend_host_memory_reduction is True

    @pytest.mark.parametrize("outcome", sorted(NO_DOWNSIZING_AUTHORITY))
    def test_these_grant_no_downsizing_authority_at_all(self, outcome):
        r = IsolatedProbeResult(label="x", outcome=outcome, vram_cap_gb=12.0)
        assert r.may_recommend_vram_downsizing is False
        assert r.may_recommend_host_memory_reduction is False
        assert r.has_capacity_authority is False

    def test_a_host_memory_message_is_never_phrased_as_a_vram_verdict(self):
        r = IsolatedProbeResult(
            label="x",
            outcome="MEASURED_HOST_MEMORY_EXCEEDED",
            vram_cap_gb=12.0,
            host_memory=HostMemoryEvidence(limit_bytes=24 * 1024**3, limit_gib=24.0, exceeded=True),
        )
        message = r.agent_facing_message()
        assert "HOST (CPU) memory limit" in message
        assert "NOT" in message
        assert "Do not reduce GPU parameter count" in message

    def test_a_schema_rejection_points_at_the_field_only(self):
        r = IsolatedProbeResult(
            label="x",
            outcome="SCHEMA_REJECTED",
            schema_field="residual_channels",
            schema_message="residual_channels=256 (less_than_equal)",
        )
        message = r.agent_facing_message()
        assert "residual_channels" in message
        assert "says nothing about model capacity" in message

    def test_outcomes_are_a_closed_set(self):
        with pytest.raises(ValidationError):
            IsolatedProbeResult(label="x", outcome="SOMETHING_ELSE")


class TestParentStaysSmall:
    """A limit applied after the model is resident protects nothing."""

    def test_the_parent_module_never_imports_torch(self):
        source = (REPO_ROOT / "agent/skills/evaluate_vram_skill/isolated_probe.py").read_text()
        assert "import torch" not in source

    def test_the_worker_does_not_use_rlimit_as(self):
        """RLIMIT_AS bounds VIRTUAL ADDRESS SPACE, and torch+CUDA reserve
        ~19.0 GiB of it while holding ~0.65 GiB resident. Using it as a
        memory bound made all three validation candidates fail to allocate
        at 3.9-5.7 GiB RSS (2026-07-31, SHA d83f397)."""
        import ast

        path = REPO_ROOT / "agent/skills/evaluate_vram_skill/preflight_worker_main.py"
        tree = ast.parse(path.read_text())
        # Executable code only: the module docstring and one log line
        # deliberately NAME RLIMIT_AS to record why it is not used.
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "resource" not in imported
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "setrlimit" not in calls

    def test_the_worker_states_who_bounds_its_memory(self):
        source = (
            REPO_ROOT / "agent/skills/evaluate_vram_skill/preflight_worker_main.py"
        ).read_text()
        assert "parent RSS monitor" in source

    def test_the_worker_runs_in_its_own_process_group(self):
        source = (REPO_ROOT / "agent/skills/evaluate_vram_skill/isolated_probe.py").read_text()
        assert "start_new_session=True" in source

    def test_only_bounded_metadata_crosses_the_boundary(self):
        """No tensors, models, or state dicts in the result schema."""
        for name, field in IsolatedProbeResult.model_fields.items():
            annotation = str(field.annotation)
            assert "Tensor" not in annotation, name
            assert "Module" not in annotation, name


class TestMemoryLimitPolicy:
    def test_the_default_leaves_headroom_for_two_concurrent_chains(self):
        limit = default_worker_memory_limit_bytes()
        gib = limit / 1024**3
        assert gib == 24.0
        # production runs two chains concurrently
        assert 2 * gib + 5 < 61.8, "two workers plus OS must fit the host"

    def test_it_is_overridable_per_deployment(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_PREFLIGHT_WORKER_MEM_GIB", "8")
        assert default_worker_memory_limit_bytes() == 8 * 1024**3

    @pytest.mark.parametrize("bad", ["", "abc", "0", "-3"])
    def test_a_malformed_override_falls_back(self, monkeypatch, bad):
        monkeypatch.setenv("SIDERIUS_PREFLIGHT_WORKER_MEM_GIB", bad)
        assert default_worker_memory_limit_bytes() == 24 * 1024**3


class TestValidationHarness:
    def test_every_committed_candidate_is_schema_valid(self):
        """The first version guessed residual_channels=256 against a cap of
        128, and then reported the rejection as 'completed'."""
        from scripts.vram_preflight_validation import CANDIDATES, validate_config

        for entry in CANDIDATES:
            normalized, error = validate_config(entry)
            assert error is None, f"{entry['label']}: {error}"
            assert normalized is not None

    def test_an_invalid_config_is_rejected_before_any_worker(self, tmp_path):
        from scripts.vram_preflight_validation import run_candidate

        record = run_candidate(
            {
                "label": "invalid",
                "model_type": "wavenet",
                "config": {"residual_channels": 256},  # schema cap is 128
                "expected": "SCHEMA_REJECTED",
            },
            tmp_path,
        )
        assert record["outcome"] == "SCHEMA_REJECTED"
        assert "before any worker was launched" in record["note"]
        assert not (tmp_path / "workers").exists(), "no worker may have been launched"

    def test_a_schema_rejection_is_never_completed(self, tmp_path):
        from scripts.vram_preflight_validation import run_candidate

        record = run_candidate(
            {
                "label": "invalid2",
                "model_type": "wavenet",
                "config": {"num_blocks": 999},
                "expected": "SCHEMA_REJECTED",
            },
            tmp_path,
        )
        assert record["outcome"] != "COMPLETED_MEASUREMENT"

    def test_each_candidate_gets_its_own_worker_result_path(self):
        source = (REPO_ROOT / "scripts/vram_preflight_validation.py").read_text()
        assert "f\"{entry['label']}.json\"" in source
        assert "run_isolated_preflight(" in source

    def test_the_harness_never_builds_a_model_in_the_controller(self):
        source = (REPO_ROOT / "scripts/vram_preflight_validation.py").read_text()
        assert "MODEL_REGISTRY[" not in source
        assert "get_config_class" in source  # validates WITHOUT constructing

    def test_the_wavenet_candidate_is_in_the_encouraged_range(self):
        from scripts.vram_preflight_validation import CANDIDATES

        wavenet = next(c for c in CANDIDATES if c["model_type"] == "wavenet")
        assert 10_000_000 <= wavenet["expected_parameters"] <= 20_000_000

    def test_no_candidate_reads_old_campaign_state(self):
        source = (REPO_ROOT / "scripts/vram_preflight_validation.py").read_text()
        assert "v19r2_10iter" not in source
        assert "v19_arch_15_19" not in source


class TestIpcBounds:
    def test_worker_output_is_written_to_a_file_not_an_undrained_pipe(self):
        source = (REPO_ROOT / "agent/skills/evaluate_vram_skill/isolated_probe.py").read_text()
        assert "subprocess.PIPE" not in source
        assert "log_path.open(" in source

    def test_detail_fields_are_truncated(self, tmp_path):
        worker = REPO_ROOT / "agent/skills/evaluate_vram_skill/preflight_worker_main.py"
        source = worker.read_text()
        assert "[:800]" in source or "[:400]" in source

    def test_a_chatty_worker_does_not_deadlock(self, tmp_path):
        body = (
            "import json\n"
            "for i in range(20000):\n"
            "    print('noise %d' % i)\n"
            f"json.dump({{'outcome': 'COMPLETED_MEASUREMENT'}}, open(r'{tmp_path / 'result.json'}', 'w'))\n"
        )
        result = run_isolated_preflight(
            _spec(tmp_path), deadline_seconds=60.0, command=_worker(tmp_path, body)
        )
        assert result.outcome == "COMPLETED_MEASUREMENT"


class TestBatchSearchSurvivesAnUnprobeableCandidate:
    """B=64 must not end the search for a model that fits at B=8.

    The descending list tries the largest batch first, and for a
    quadratic-attention model at T=8000 that first candidate needs 61 GiB
    for one attention matrix (64 x 4 heads x 8000 x 8000 x 4 bytes). On
    2026-07-31 that allocation killed the host at 57.7 GiB anon-rss.
    """

    def _model(self, fail_above: int):
        import torch.nn as nn

        class _Fake(nn.Module):
            def __init__(self):
                super().__init__()
                self.weight = nn.Parameter(__import__("torch").zeros(4, 4))

            def forward(self, x):
                if x.shape[0] > fail_above:
                    raise MemoryError(f"cannot allocate for batch {x.shape[0]}")
                import torch

                return torch.zeros((x.shape[0], 256, x.shape[1]))

        return _Fake()

    def test_the_search_falls_through_to_a_workable_batch(self, monkeypatch):
        from agent.skills.evaluate_vram_skill import batch_resolver

        monkeypatch.setattr(
            batch_resolver, "probe_activation_footprint", _raising_probe(fail_above=8)
        )
        chosen = batch_resolver.resolve_inference_batch(
            self._model(fail_above=8), segmentation_size=100, cap_bytes=10**12
        )
        assert chosen == 8, "the first probeable batch must be selected"

    def test_a_non_memory_error_still_propagates(self, monkeypatch):
        from agent.skills.evaluate_vram_skill import batch_resolver

        def _boom(**_kwargs):
            raise ValueError("a real bug, not a batch problem")

        monkeypatch.setattr(batch_resolver, "probe_activation_footprint", _boom)
        with pytest.raises(ValueError, match="a real bug"):
            batch_resolver.resolve_inference_batch(
                self._model(fail_above=8), segmentation_size=100, cap_bytes=10**12
            )

    # `test_every_memory_shaped_error_is_recognised` (MemoryError, CUDA OOM,
    # std::bad_alloc) and `test_an_unrelated_runtime_error_is_not` (shape
    # mismatch) lived here, calling `is_memory_exception` directly.
    #
    # `classify_host_memory_exception` opens with
    # `if not is_memory_exception(exc): return None`, so it returns None
    # EXACTLY when the predicate is False. All four of those inputs appear in
    # `TestOneClassifierEverywhere`'s nine-row table, which therefore pins the
    # predicate's answer for each of them and the classification on top.


def _raising_probe(fail_above: int):
    """A probe that refuses batches above `fail_above`, like a real OOM.

    Reuses the ProbeResult shape the existing resolver tests already
    establish, rather than reconstructing the schema by hand.
    """
    from agent.skills.evaluate_vram_skill.structural_probe import (
        ForwardLayerReport,
        ProbeResult,
    )

    def _probe(*, input_sample, **_kwargs):
        batch = input_sample.shape[0]
        if batch > fail_above:
            raise MemoryError(f"cannot allocate for batch {batch}")
        return ProbeResult(
            mode="inference",
            model_forward=ForwardLayerReport(
                module_name="Fake",
                layers=[],
                total_param_bytes=1024,
                forward_output_bytes_sum=1024,
                forward_output_bytes_max=1024,
            ),
            loss_forward=None,
            autograd_tape=None,
            input_bytes=0,
            output_bytes=0,
        )

    return _probe


class TestRssIsAuthoritativeNotAddressSpace:
    """Reservation is not consumption.

    Measured on 2026-07-31 (SHA d83f397): importing torch and touching
    CUDA reserves ~19.0 GiB of VIRTUAL address space while holding
    ~0.65 GiB resident. A 24 GiB `RLIMIT_AS` therefore left ~5 GiB for
    real work, and all three validation candidates failed to allocate
    while their resident memory was only 3.9-5.7 GiB.
    """

    def test_high_virtual_reservation_with_low_rss_is_allowed(self, tmp_path):
        """A worker that RESERVES far more than the ceiling but stays
        resident-small must complete normally."""
        body = (
            "import json, mmap\n"
            # 8 GiB of reserved-but-untouched address space
            "reserved = mmap.mmap(-1, 8 * 1024**3)\n"
            f"json.dump({{'outcome': 'COMPLETED_MEASUREMENT'}}, open(r'{tmp_path / 'result.json'}', 'w'))\n"
        )
        result = run_isolated_preflight(
            _spec(tmp_path, limit_mib=4096),  # ceiling BELOW the reservation
            deadline_seconds=60.0,
            command=_worker(tmp_path, body),
        )
        assert result.outcome == "COMPLETED_MEASUREMENT", (
            "address-space reservation must not be mistaken for consumption"
        )
        assert result.host_memory is not None
        assert result.host_memory.exceeded is False

    def test_the_enforcement_field_names_the_rss_monitor(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path, limit_mib=512),
            deadline_seconds=60.0,
            command=_worker(tmp_path, GROWS_FOREVER),
        )
        assert result.outcome == "MEASURED_HOST_MEMORY_EXCEEDED"
        assert result.host_memory is not None
        assert result.host_memory.enforcement == "parent_rss_monitor"


class TestHostAllocationFailureIsCandidateLevel:
    """An allocator refusal is about the candidate, not our machinery."""

    def test_it_is_not_infrastructure_failure(self, tmp_path):
        body = (
            "import json\n"
            f"json.dump({{'outcome': 'HOST_MEMORY_ALLOCATION_FAILURE',\n"
            f"  'detail': \"DefaultCPUAllocator: can't allocate memory\",\n"
            f"  'phase': 'host_allocation'}}, open(r'{tmp_path / 'result.json'}', 'w'))\n"
        )
        result = run_isolated_preflight(
            _spec(tmp_path), deadline_seconds=30.0, command=_worker(tmp_path, body)
        )
        assert result.outcome == "HOST_MEMORY_ALLOCATION_FAILURE"
        assert result.outcome != "PROBE_INFRASTRUCTURE_FAILURE"
        assert result.outcome != "MEASURED_HARD_TIMEOUT"

    def test_it_carries_host_authority_not_vram_authority(self):
        r = IsolatedProbeResult(
            label="x", outcome="HOST_MEMORY_ALLOCATION_FAILURE", vram_cap_gb=12.0
        )
        assert r.may_recommend_host_memory_reduction is True
        assert r.may_recommend_vram_downsizing is False

    def test_its_message_is_never_a_vram_verdict(self):
        r = IsolatedProbeResult(
            label="x", outcome="HOST_MEMORY_ALLOCATION_FAILURE", vram_cap_gb=12.0
        )
        message = r.agent_facing_message()
        assert "HOST memory result" in message
        assert "NOT a GPU VRAM verdict" in message
        assert "Do not reduce GPU parameter count" in message


class TestNoFalseTimeout:
    def test_a_fast_completion_cannot_be_a_timeout(self, tmp_path):
        """FCNet was filed as MEASURED_HARD_TIMEOUT after 3.771 s against
        a 600 s deadline. A timeout must at least have reached its own
        deadline."""
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=600.0,
            command=_worker(tmp_path, COMPLETES.format(result=tmp_path / "result.json")),
        )
        assert result.elapsed_seconds < 600.0
        assert result.outcome != "MEASURED_HARD_TIMEOUT"

    def test_a_real_timeout_reaches_its_deadline(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=1.0,
            grace_seconds=0.5,
            command=_worker(tmp_path, STALLS),
        )
        assert result.outcome == "MEASURED_HARD_TIMEOUT"
        assert result.elapsed_seconds >= 1.0


class TestOneClassifierEverywhere:
    """Two near-identical string checks is how the last one was missed:
    the resolver looked for 'cannot allocate' while PyTorch says
    "can't allocate"."""

    PYTORCH_CPU_OOM = (
        "[enforce fail at alloc_cpu.cpp:127] err == 0. DefaultCPUAllocator: "
        "can't allocate memory: you tried to allocate 3152543744 bytes. "
        "Error code 12 (Cannot allocate memory)"
    )

    @pytest.mark.parametrize(
        "exc,expected",
        [
            (MemoryError("x"), "host"),
            (RuntimeError(PYTORCH_CPU_OOM), "host"),
            (RuntimeError("cannot allocate memory"), "host"),
            (RuntimeError("std::bad_alloc"), "host"),
            (RuntimeError("ENOMEM"), "host"),
            (RuntimeError("Error code 12"), "host"),
            (RuntimeError("CUDA out of memory. Tried to allocate 11 GiB"), "cuda"),
            (RuntimeError("shape mismatch"), None),
            (ValueError("unrelated"), None),
        ],
    )
    def test_the_classifier_covers_every_observed_form(self, exc, expected):
        from agent.skills.evaluate_vram_skill.probe_budgets import (
            classify_host_memory_exception,
        )

        assert classify_host_memory_exception(exc) == expected

    @pytest.mark.parametrize(
        "path",
        [
            "agent/skills/evaluate_vram_skill/batch_resolver.py",
            "agent/skills/evaluate_vram_skill/wrapper.py",
            "agent/skills/evaluate_vram_skill/preflight_worker_main.py",
        ],
    )
    def test_every_path_uses_the_shared_helper_and_defines_no_other(self, path):
        """Both halves of "one classifier", per file. They were two tests
        iterating the same three paths; a file that imports the helper AND
        keeps a private one is the state neither caught alone.

        Comment lines are stripped first: a comment explaining why a private
        check was removed would otherwise re-fail this.
        """
        source = (REPO_ROOT / path).read_text()
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))

        assert "probe_budgets import" in code, path
        assert ("is_memory_exception" in code) or ("classify_host_memory_exception" in code), path
        assert "def _is_memory_error" not in code, path


class TestInconclusiveIsNotTimeout:
    """A 65.6 s inspection was filed as a timeout against a 600 s deadline.

    The cause was a single mapping: every "inconclusive" status became
    MEASURED_HARD_TIMEOUT. "We did not measure it" and "a deadline
    elapsed" are different facts, and only the second is a timeout.
    """

    def test_a_non_timeout_inspection_failure_is_inconclusive(self, tmp_path):
        body = (
            "import json\n"
            f"json.dump({{'outcome': 'INCONCLUSIVE_MEASUREMENT',\n"
            f"  'detail': 'structural tracing failed', 'phase': 'model_inspection'}},\n"
            f"  open(r'{tmp_path / 'result.json'}', 'w'))\n"
        )
        result = run_isolated_preflight(
            _spec(tmp_path), deadline_seconds=600.0, command=_worker(tmp_path, body)
        )
        assert result.outcome == "INCONCLUSIVE_MEASUREMENT"
        assert result.outcome != "MEASURED_HARD_TIMEOUT"
        assert result.outcome != "PROBE_INFRASTRUCTURE_FAILURE"

    def test_inconclusive_carries_no_authority_of_any_kind(self):
        r = IsolatedProbeResult(label="x", outcome="INCONCLUSIVE_MEASUREMENT", vram_cap_gb=12.0)
        assert r.may_recommend_vram_downsizing is False
        assert r.may_recommend_host_memory_reduction is False
        assert r.has_capacity_authority is False

    def test_its_message_forbids_inferring_infeasibility(self):
        r = IsolatedProbeResult(label="x", outcome="INCONCLUSIVE_MEASUREMENT", vram_cap_gb=12.0)
        message = r.agent_facing_message()
        assert "inconclusive" in message.lower()
        assert "Do not infer" in message
        assert "too large" in message
        assert "reduce" not in message.lower().replace("produced no measured", "")

    def test_the_schema_refuses_a_timeout_faster_than_its_budget(self):
        """The exact 2026-07-31 shape: 65.6 s against a 600 s deadline."""
        with pytest.raises(ValidationError, match="deadline was reached"):
            IsolatedProbeResult(
                label="x",
                outcome="MEASURED_HARD_TIMEOUT",
                timeout_budget_seconds=600.0,
                timeout_elapsed_seconds=65.556,
            )

    def test_a_genuine_timeout_with_provenance_is_accepted(self):
        r = IsolatedProbeResult(
            label="x",
            outcome="MEASURED_HARD_TIMEOUT",
            timeout_operation="worker_deadline",
            timeout_budget_seconds=600.0,
            timeout_elapsed_seconds=601.2,
        )
        assert r.outcome == "MEASURED_HARD_TIMEOUT"
        assert r.timeout_operation == "worker_deadline"

    def test_a_real_worker_deadline_records_its_provenance(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=1.0,
            grace_seconds=0.5,
            command=_worker(tmp_path, STALLS),
        )
        assert result.outcome == "MEASURED_HARD_TIMEOUT"
        assert result.timeout_operation == "worker_deadline"
        assert result.timeout_budget_seconds == 1.0
        assert result.timeout_elapsed_seconds is not None
        assert result.timeout_elapsed_seconds >= 1.0

    def test_the_wrapper_separates_timeout_from_inconclusive_status(self):
        source = (REPO_ROOT / "agent/skills/evaluate_vram_skill/wrapper.py").read_text()
        assert '"status": "timeout"' in source, "a real deadline needs its own status"
        assert '"status": "inconclusive"' in source, "tracing failure keeps inconclusive"

    def test_the_worker_no_longer_maps_inconclusive_to_timeout(self):
        source = (
            REPO_ROOT / "agent/skills/evaluate_vram_skill/preflight_worker_main.py"
        ).read_text()
        start = source.index('if status == "inconclusive":')
        block = source[start : source.index("if status ==", start + 10)]
        assert "INCONCLUSIVE_MEASUREMENT" in block
        assert "MEASURED_HARD_TIMEOUT" not in block


class TestThirdValidationOutcomesUnchanged:
    """The paths that already worked must keep working."""

    def test_completed_measurement_is_unaffected(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=600.0,
            command=_worker(tmp_path, COMPLETES.format(result=tmp_path / "result.json")),
        )
        assert result.outcome == "COMPLETED_MEASUREMENT"
        assert result.realized_parameter_count == 323281352

    def test_rss_enforcement_is_unaffected(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path, limit_mib=512),
            deadline_seconds=60.0,
            command=_worker(tmp_path, GROWS_FOREVER),
        )
        assert result.outcome == "MEASURED_HOST_MEMORY_EXCEEDED"
        assert result.host_memory is not None
        assert result.host_memory.enforcement == "parent_rss_monitor"

    def test_corrupt_ipc_remains_infrastructure(self, tmp_path):
        result = run_isolated_preflight(
            _spec(tmp_path),
            deadline_seconds=30.0,
            command=_worker(tmp_path, CORRUPT_RESULT.format(result=tmp_path / "result.json")),
        )
        assert result.outcome == "PROBE_INFRASTRUCTURE_FAILURE"

    def test_candidate_configs_and_hashes_are_unchanged(self):
        import hashlib
        import json as _json

        from scripts.vram_preflight_validation import CANDIDATES, validate_config

        expected = {
            "fcnet@323M-official": "ad0e07aa864a6492",
            "wavenet@17M": "958440417b837b89",
            "transformer@medium": "80581a7d24d2f100",
        }
        for entry in CANDIDATES:
            normalized, error = validate_config(entry)
            assert error is None
            digest = hashlib.sha256(
                _json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            assert digest.startswith(expected[entry["label"]]), entry["label"]
