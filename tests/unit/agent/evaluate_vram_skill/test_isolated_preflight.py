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

    def test_the_worker_applies_its_limit_before_importing_torch(self):
        source = (
            REPO_ROOT / "agent/skills/evaluate_vram_skill/preflight_worker_main.py"
        ).read_text()
        limit_at = source.index("_apply_memory_limit(int(spec[")
        import_at = source.index("from agent.skills.evaluate_vram_skill.wrapper import run_skill")
        assert limit_at < import_at, "the limit must be set before torch can be loaded"

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

    @pytest.mark.parametrize(
        "exc",
        [
            MemoryError("out of memory"),
            RuntimeError("CUDA out of memory. Tried to allocate 61.00 GiB"),
            RuntimeError("std::bad_alloc"),
        ],
    )
    def test_every_memory_shaped_error_is_recognised(self, exc):
        from agent.skills.evaluate_vram_skill.batch_resolver import _is_memory_error

        assert _is_memory_error(exc) is True

    def test_an_unrelated_runtime_error_is_not(self):
        from agent.skills.evaluate_vram_skill.batch_resolver import _is_memory_error

        assert _is_memory_error(RuntimeError("shape mismatch")) is False


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
