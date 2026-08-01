"""Tests for the production pre-flight wiring (V20 PR A).

The defect these lock down is not "the adapter mis-maps a field". It is
that a component can be built, tested, and never called — which is how
the isolated worker sat unused while the chain parent held 6,962 MiB for
a whole iteration. So the reachability and no-fallback tests matter as
much as the mapping tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import get_args

import pytest

from agent.skills.evaluate_vram_skill import preflight_adapter as adapter
from agent.skills.evaluate_vram_skill.isolated_probe import (
    HardwareSnapshot,
    IsolatedProbeSpec,
    PreflightOutcome,
)
from agent.skills.evaluate_vram_skill.preflight_worker_main import (
    RICH_FIELD_BUDGET_BYTES,
    _bounded_rich_fields,
)

# --- the six attributes run_skill actually reads (audited) ------------------
RUN_SKILL_HARDWARE_SURFACE = (
    "usable_cap_bytes",
    "usable_cap_gb",
    "total_memory_bytes",
    "total_memory_gb",
    "device_name",
    "device_available",
)


def _snapshot(**over) -> HardwareSnapshot:
    base = {
        "usable_cap_bytes": 25 * 1024**3,
        "usable_cap_gb": 25.0,
        "total_memory_bytes": 32 * 1024**3,
        "total_memory_gb": 32.0,
        "device_name": "NVIDIA GeForce RTX 5090",
        "device_available": True,
        "hardware_fingerprint": "sha256:test",
    }
    base.update(over)
    return HardwareSnapshot(**base)


def _spec(**over) -> IsolatedProbeSpec:
    base = {
        "label": "cand",
        "model_type": "wavenet",
        "result_path": "/tmp/x.json",
        "worker_memory_limit_bytes": 1024,
    }
    base.update(over)
    return IsolatedProbeSpec(**base)


class TestOutcomeMapping:
    def test_mapping_is_exhaustive_over_the_declared_vocabulary(self):
        """A new PreflightOutcome must fail here, not reach production."""
        assert set(get_args(PreflightOutcome)) == set(adapter.OUTCOME_TO_LEGACY)

    @pytest.mark.parametrize("outcome", get_args(PreflightOutcome))
    def test_every_outcome_adapts_without_raising(self, outcome):
        result = adapter.adapt_result({"outcome": outcome, "detail": "d"})
        assert result["status"] == adapter.OUTCOME_TO_LEGACY[outcome][0]
        assert result["preflight_outcome"] == outcome

    def test_unmapped_outcome_raises_rather_than_defaulting(self):
        with pytest.raises(adapter.PreflightWiringError, match="unmapped"):
            adapter.adapt_result({"outcome": "SOMETHING_NEW"})

    def test_missing_outcome_raises(self):
        with pytest.raises(adapter.PreflightWiringError):
            adapter.adapt_result({})

    @pytest.mark.parametrize(
        ("outcome", "status", "feasible"),
        [
            ("COMPLETED_MEASUREMENT", "success", True),
            ("MEASURED_PEAK_ABOVE_VRAM_CAP", "success", False),
            ("MEASURED_CUDA_OOM", "success", False),
            ("SCHEMA_REJECTED", "schema_violation", None),
            ("MEASURED_HARD_TIMEOUT", "timeout", None),
            ("INCONCLUSIVE_MEASUREMENT", "inconclusive", None),
            ("HOST_MEMORY_ALLOCATION_FAILURE", "host_memory", None),
            ("MEASURED_HOST_MEMORY_EXCEEDED", "host_memory", None),
            ("PROBE_INFRASTRUCTURE_FAILURE", "error", None),
        ],
    )
    def test_legacy_pair_is_exact(self, outcome, status, feasible):
        """The §6.1 table, asserted row by row rather than by inspection."""
        result = adapter.adapt_result({"outcome": outcome})
        assert result["status"] == status
        assert result.get("feasible") == feasible

    def test_capacity_outcomes_stay_distinguishable_despite_a_shared_pair(self):
        """D-A1: same control flow, different typed cause."""
        cap = adapter.adapt_result({"outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP"})
        oom = adapter.adapt_result({"outcome": "MEASURED_CUDA_OOM"})
        assert (cap["status"], cap["feasible"]) == (oom["status"], oom["feasible"])
        assert cap["preflight_outcome"] != oom["preflight_outcome"]


class TestFieldPreservation:
    def test_rich_schema_fields_survive(self):
        payload = {
            "outcome": "SCHEMA_REJECTED",
            "violations": [{"loc": "channels", "msg": "must not decrease"}],
            "offending_config": {"channels": [4, 2]},
        }
        result = adapter.adapt_result(payload)
        assert result["violations"] == payload["violations"]
        assert result["offending_config"] == payload["offending_config"]

    def test_memory_killer_survives(self):
        result = adapter.adapt_result(
            {"outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP", "memory_killer": {"layer": "conv7"}}
        )
        assert result["memory_killer"] == {"layer": "conv7"}

    def test_truncation_marker_is_propagated(self):
        result = adapter.adapt_result({"outcome": "SCHEMA_REJECTED", "truncated": True})
        assert result["truncated"] is True

    def test_agent_text_is_forwarded_not_composed(self):
        """16.1-A: if a string reaches the agent, the worker produced it."""
        result = adapter.adapt_result(
            {
                "outcome": "MEASURED_CUDA_OOM",
                "verdict": "V-from-worker",
                "suggestion": "S-from-worker",
            }
        )
        assert result["verdict"] == "V-from-worker"
        assert result["suggestion"] == "S-from-worker"

    def test_realized_parameter_count_becomes_num_params(self):
        result = adapter.adapt_result(
            {"outcome": "COMPLETED_MEASUREMENT", "realized_parameter_count": 2_388_992}
        )
        assert result["num_params"] == 2_388_992

    def test_timeout_record_is_reconstructed(self):
        result = adapter.adapt_result(
            {
                "outcome": "MEASURED_HARD_TIMEOUT",
                "phase": "batch_search",
                "timeout_operation": "batch_search",
                "timeout_budget_seconds": 600.0,
                "timeout_elapsed_seconds": 601.2,
            }
        )
        record = result["timeout_record"]
        assert record["operation"] == "batch_search"
        assert record["budget_seconds"] == 600.0
        assert record["elapsed_seconds"] == 601.2

    def test_dead_field_is_not_resurrected(self):
        """FU-A-1 / D-A5 — the skill removed it; the adapter must not fake it."""
        result = adapter.adapt_result({"outcome": "COMPLETED_MEASUREMENT"})
        assert "inference_batch_uncalibrated" not in result
        assert result.get("inference_batch_uncalibrated") is None


class TestHardwareSnapshot:
    def test_snapshot_satisfies_the_audited_run_skill_surface(self):
        """If run_skill starts reading a seventh attribute, fail here.

        The worker passes a HardwareSnapshot where a HardwareContext is
        annotated, justified by this audited six-attribute surface. The
        cast is local; this test is what keeps it honest.
        """
        snapshot = _snapshot()
        for attribute in RUN_SKILL_HARDWARE_SURFACE:
            assert hasattr(snapshot, attribute), attribute

    def test_missing_hardware_context_is_an_error_not_a_fallback(self):
        with pytest.raises(adapter.PreflightWiringError, match="hardware_context is required"):
            adapter.build_hardware_snapshot(None)

    def test_snapshot_rejects_impossible_values(self):
        with pytest.raises(ValueError):
            _snapshot(usable_cap_bytes=0)
        with pytest.raises(ValueError):
            _snapshot(device_name="")


class TestEffectiveCap:
    def test_operator_budget_wins(self):
        spec = _spec(vram_budget_gb=12.0, hardware=_snapshot())
        assert spec.effective_cap_gb() == 12.0
        assert spec.effective_limit_source() == "operator_vram_budget"

    def test_none_budget_uses_the_frozen_defensive_cap(self):
        """D-A4: None means 'no operator ceiling', not 'unset'."""
        spec = _spec(vram_budget_gb=None, hardware=_snapshot(usable_cap_gb=25.0))
        assert spec.effective_cap_gb() == 25.0
        assert spec.effective_limit_source() == "hardware_snapshot_defensive_cap"

    def test_no_budget_and_no_snapshot_is_unbounded(self):
        spec = _spec()
        assert spec.effective_cap_gb() is None
        assert spec.effective_limit_source() == "unbounded_no_snapshot"

    @pytest.mark.parametrize("bad", [0.0, -1.0])
    def test_non_positive_budget_is_rejected(self, bad):
        with pytest.raises(ValueError):
            _spec(vram_budget_gb=bad)

    def test_legacy_spec_without_hardware_still_validates(self):
        assert _spec(vram_budget_gb=12.0).hardware is None


class TestBoundedRichFields:
    def test_small_payload_passes_through_untouched(self):
        fields = {"violations": [{"loc": "x", "msg": "bad"}]}
        assert _bounded_rich_fields(fields) == fields

    def test_empty_inputs_produce_nothing(self):
        assert _bounded_rich_fields({"memory_killer": None, "violations": []}) == {}

    def test_oversized_payload_stays_within_budget_and_valid(self):
        fields = {
            "violations": [
                {"loc": f"field_{i}", "msg": "m" * 900, "type": "value_error"} for i in range(40)
            ],
            "offending_config": {"k" * 50: "v" * 900},
        }
        result = _bounded_rich_fields(fields)
        encoded = json.dumps(result, default=str).encode("utf-8")
        assert len(encoded) <= RICH_FIELD_BUDGET_BYTES
        json.loads(encoded)
        assert result["truncated"] is True

    def test_truncation_shortens_lists_before_discarding_them(self):
        """Ten violations with their field names beat zero."""
        fields = {
            "violations": [
                {"loc": f"field_{i}", "msg": "m" * 900, "type": "value_error"} for i in range(40)
            ]
        }
        result = _bounded_rich_fields(fields)
        assert isinstance(result["violations"], list)
        assert len(result["violations"]) >= 1
        assert result["violations_omitted_count"] > 0
        assert set(result["violations"][0]) == {"loc", "msg", "type"}

    def test_dropped_field_is_marked_not_removed(self):
        result = _bounded_rich_fields(
            {"memory_killer": {"layers": [{"n": "l" * 200, "b": i} for i in range(500)]}}
        )
        assert "memory_killer" in result
        assert len(json.dumps(result, default=str).encode()) <= RICH_FIELD_BUDGET_BYTES


class TestParentStaysCpuOnly:
    def test_importing_the_adapter_does_not_import_torch(self):
        """The whole point: the parent must never touch CUDA on this path."""
        code = (
            "import sys;"
            "import agent.skills.evaluate_vram_skill.preflight_adapter;"
            "print('torch' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        assert out.stdout.strip() == "False", out.stdout

    def test_adapter_source_never_constructs_a_candidate(self):
        source = __import__("pathlib").Path(adapter.__file__).read_text(encoding="utf-8")
        for forbidden in ("import torch", "MODEL_REGISTRY", "get_config_class", "empty_cache"):
            assert forbidden not in source, forbidden


class TestNoSilentFallback:
    def test_infrastructure_failure_maps_to_error_not_a_retry(self):
        """A worker failure must surface, never re-run in-process."""
        result = adapter.adapt_result(
            {"outcome": "PROBE_INFRASTRUCTURE_FAILURE", "detail": "worker died"}
        )
        assert result["status"] == "error"
        assert "feasible" not in result

    def test_adapter_imports_no_in_process_skill_module(self):
        """Assert over the import graph, not the raw text.

        A substring search matches prose — an earlier version of this test
        failed on a comment that merely cited ``wrapper.py:34``. What
        matters is whether the module can *reach* the in-process skill, so
        the assertion parses imports instead of reading comments.
        """
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(adapter.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)

        forbidden = {"torch"} | {
            name
            for name in imported
            if name.endswith(".wrapper") or name.endswith("evaluate_vram_skill.wrapper")
        }
        assert not (forbidden & imported), (
            f"the adapter must not reach the in-process skill: {sorted(forbidden & imported)}"
        )
        assert not any(name == "torch" or name.startswith("torch.") for name in imported)
