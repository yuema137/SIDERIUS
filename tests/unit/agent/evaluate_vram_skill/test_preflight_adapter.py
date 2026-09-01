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
from pathlib import Path
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
    def test_the_import_time_exhaustiveness_guard_is_wired(self):
        """The vocabulary and the table must agree, and the check that
        enforces it must actually run on import.

        The set comparison alone cannot fail on its own: `preflight_adapter`
        calls `_assert_mapping_is_exhaustive()` at module scope, so a
        divergence makes the import raise and this whole file errors during
        collection. What is NOT otherwise covered is someone deleting that
        module-scope call, after which a missing row would reach production
        silently. Hence the reachability half.
        """
        assert set(get_args(PreflightOutcome)) == set(adapter.OUTCOME_TO_LEGACY)

        source = Path(adapter.__file__).read_text()
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        assert "\n_assert_mapping_is_exhaustive()" in code, (
            "the exhaustiveness check is no longer invoked at import; a new "
            "PreflightOutcome without a table row would now reach production"
        )

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
        """The §6.1 table, asserted row by row rather than by inspection.

        `feasible=None` in this table means the key is ABSENT, not present
        and null -- `adapt_result` writes it only when it is not None. That
        distinction is the whole of #156: the tuner read
        `.get("feasible", True)` and a missing key meant "safe to run".

        This assertion used to be `result.get("feasible") == feasible`,
        which returns None for an absent key and so passed either way. Only
        one row (PROBE_INFRASTRUCTURE_FAILURE, below) pinned absence, so
        five of the six None rows were unguarded. Verified by making the
        adapter always write the key: this table stayed green.
        """
        result = adapter.adapt_result({"outcome": outcome, "detail": "d"})

        assert result["status"] == status
        assert result["preflight_outcome"] == outcome, (
            "the typed outcome must survive the adaptation -- it is the only "
            "thing distinguishing rows that share a legacy pair"
        )

        if feasible is None:
            assert "feasible" not in result, (
                f"{outcome} carries no capacity verdict, so the key must be "
                "ABSENT; present-and-null reads as a conclusion downstream"
            )
        else:
            assert result["feasible"] is feasible

    @pytest.mark.parametrize(
        "payload",
        [{"outcome": "SOMETHING_NEW"}, {}],
        ids=["unmapped", "missing"],
    )
    def test_an_unknown_outcome_raises_rather_than_defaulting(self, payload):
        """Both reach the same guard: an outcome not in the table. Neither
        may fall through to a legacy pair."""
        with pytest.raises(adapter.PreflightWiringError, match="unmapped"):
            adapter.adapt_result(payload)

    def test_capacity_outcomes_stay_distinguishable_despite_a_shared_pair(self):
        """D-A1: same control flow, different typed cause."""
        cap = adapter.adapt_result({"outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP"})
        oom = adapter.adapt_result({"outcome": "MEASURED_CUDA_OOM"})
        assert (cap["status"], cap["feasible"]) == (oom["status"], oom["feasible"])
        assert cap["preflight_outcome"] != oom["preflight_outcome"]


class TestFieldPreservation:
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


class TestWorkflowOwnedProbeBudgets:
    def test_custom_budgets_reach_both_worker_layers(self, tmp_path, monkeypatch):
        """Deleting either transport makes this red.

        The per-forward value must cross the JSON IPC boundary, while the
        total value must also govern the parent process deadline. Testing only
        the spec or only the deadline would leave the other limit on its
        module default and make a workflow override only half effective.
        """
        from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeResult

        captured: dict[str, object] = {}

        def _capture(spec, *, deadline_seconds, **_kwargs):
            captured["spec"] = spec
            captured["deadline_seconds"] = deadline_seconds
            return IsolatedProbeResult(label=spec.label, outcome="COMPLETED_MEASUREMENT")

        monkeypatch.setattr(adapter, "run_isolated_preflight", _capture)
        monkeypatch.setattr(adapter, "build_hardware_snapshot", lambda _ctx: None)

        adapter.run_production_preflight(
            model_type="synthetic_model",
            model_config={},
            train_config={},
            loss_config={},
            vram_budget_gb=None,
            hardware_context=None,
            workspace=tmp_path,
            label="custom_budget",
            plugin_dir=None,
            loss_dir=None,
            probe_step_timeout_seconds=321.0,
            deadline_seconds=987.0,
        )

        spec = captured["spec"]
        assert isinstance(spec, IsolatedProbeSpec)
        assert spec.probe_budgets.single_probe_seconds == 321.0
        assert spec.probe_budgets.preflight_total_seconds == 987.0
        assert captured["deadline_seconds"] == 987.0


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
