"""The composed worker -> IPC model -> adapter path preserves the contract.

A5 (2026-08-01) ran the real chain and passed every GPU-lifecycle
criterion, then failed on artifacts: ``memory.vram_budget_gb`` was null
where 456 pre-PR-A records held 12.0. Eight fields were being dropped —
``limit_gb``, ``dominant_phase``, ``verdict``, ``suggestion``,
``violations``, ``offending_config``, ``memory_killer``, ``truncated``.
The whole D-A2 bounded-diagnostics mechanism was inert: built in the
worker, tested in the worker, and discarded one layer later.

Every layer was individually tested and individually correct. The
worker emitted the fields. The adapter forwarded them. The 47 adapter
tests passed because they call ``adapt_result`` with hand-built payload
dicts that already contain the keys — so nothing ever ran the sequence
the production code actually runs.

    Testing each serialization layer independently does not prove that
    the composed worker-JSON -> IPC-model -> adapter path preserves the
    contract.

So these tests drive the REAL production path — a real worker
subprocess, the real result file, the real payload mapping in
``run_isolated_preflight`` — and only then assert on the adapted
result. No GPU: the synthetic workers just print a payload and exit,
which is the same seam ``test_isolated_preflight.py`` uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.skills.evaluate_vram_skill.isolated_probe import (
    IsolatedProbeResult,
    IsolatedProbeSpec,
    run_isolated_preflight,
)
from agent.skills.evaluate_vram_skill.preflight_adapter import adapt_result
from agent.skills.evaluate_vram_skill.preflight_worker_main import (
    RICH_FIELD_BUDGET_BYTES,
    _bounded_rich_fields,
    _classify,
)

MIB = 1024**2


def _spec(tmp_path: Path, **over) -> IsolatedProbeSpec:
    base = dict(
        label="composition",
        model_type="fake_candidate",
        vram_budget_gb=12.0,
        result_path=str(tmp_path / "result.json"),
        worker_memory_limit_bytes=512 * MIB,
    )
    base.update(over)
    return IsolatedProbeSpec(**base)


def _emitting_worker(tmp_path: Path, payload: dict) -> list[str]:
    """A worker that writes exactly ``payload`` and exits cleanly."""
    script = tmp_path / "emitting_worker.py"
    script.write_text(
        "import json, pathlib\n"
        f"pathlib.Path({str(tmp_path / 'result.json')!r}).write_text(\n"
        f"    json.dumps({payload!r}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    import sys

    return [sys.executable, str(script)]


def _run(tmp_path: Path, payload: dict) -> dict:
    """worker subprocess -> IsolatedProbeResult -> adapt_result."""
    probe = run_isolated_preflight(
        _spec(tmp_path),
        deadline_seconds=30.0,
        command=_emitting_worker(tmp_path, payload),
    )
    return adapt_result(probe.model_dump())


COMPLETED = {
    "outcome": "COMPLETED_MEASUREMENT",
    "detail": "FITS - estimated 1.72 GB <= cap 12.00 GB",
    "phase": "complete",
    "realized_parameter_count": 6_762_568,
    "estimated_gb": 1.724,
    "inference_batch": 16,
    "limit_gb": 12.0,
    "dominant_phase": "training",
    "verdict": "FITS - estimated 1.72 GB <= cap 12.00 GB. Dominant phase: training.",
    "suggestion": "",
}

ABOVE_CAP = {
    **COMPLETED,
    "outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP",
    "estimated_gb": 19.5,
    "verdict": "DOES NOT FIT - estimated 19.50 GB > cap 12.00 GB",
    "suggestion": "halve batch_size, or reduce segmentation_size to 20000",
    "phase": "vram_gate",
    "memory_killer": {"driver": "activations", "share": 0.71},
}

SCHEMA_REJECTED = {
    "outcome": "SCHEMA_REJECTED",
    "detail": "plugin config rejected",
    "phase": "schema_validation",
    "schema_field": "depth",
    "schema_message": "Input should be a valid integer",
    "violations": [{"field": "depth", "message": "not an integer"}],
    "offending_config": {"depth": "four", "multi": 40},
    "truncated": True,
    "violations_omitted_count": 7,
}


class TestFieldsSurviveTheComposedPath:
    """Each field, through a real subprocess, not a hand-built dict."""

    def test_limit_gb_survives(self, tmp_path):
        assert _run(tmp_path, COMPLETED)["limit_gb"] == 12.0

    def test_dominant_phase_survives(self, tmp_path):
        assert _run(tmp_path, COMPLETED)["dominant_phase"] == "training"

    def test_verdict_survives(self, tmp_path):
        assert _run(tmp_path, COMPLETED)["verdict"] == COMPLETED["verdict"]

    def test_verdict_is_not_merely_the_detail_fallback(self, tmp_path):
        """The adapter falls back to ``detail`` when verdict is missing.

        In A5 the two texts happened to match, so verdict looked
        preserved while it was actually being reconstructed. Give them
        different values so only real forwarding can pass.
        """
        payload = {**COMPLETED, "verdict": "VERDICT-TEXT", "detail": "DETAIL-TEXT"}
        assert _run(tmp_path, payload)["verdict"] == "VERDICT-TEXT"

    def test_suggestion_survives(self, tmp_path):
        adapted = _run(tmp_path, ABOVE_CAP)
        assert adapted["suggestion"] == ABOVE_CAP["suggestion"]

    def test_memory_killer_survives(self, tmp_path):
        assert _run(tmp_path, ABOVE_CAP)["memory_killer"] == ABOVE_CAP["memory_killer"]

    def test_bounded_rich_fields_survive(self, tmp_path):
        adapted = _run(tmp_path, SCHEMA_REJECTED)
        assert adapted["violations"] == SCHEMA_REJECTED["violations"]
        assert adapted["offending_config"] == SCHEMA_REJECTED["offending_config"]
        assert adapted["truncated"] is True

    def test_truncation_count_travels_with_the_truncation_flag(self, tmp_path):
        """``truncated`` without the count says something was dropped but
        not how much — the measured part would be the part lost."""
        assert _run(tmp_path, SCHEMA_REJECTED)["violations_omitted_count"] == 7

    def test_a_dropped_field_keeps_its_marker_rather_than_becoming_none(self, tmp_path):
        """The worker replaces an over-budget field with an explicit
        marker string so its absence is visible. Typing the field as
        list-only would convert that deliberate marker back into the
        silent ``None`` the marker exists to prevent."""
        marker = "[dropped: exceeded the rich-field budget]"
        adapted = _run(tmp_path, {**SCHEMA_REJECTED, "violations": marker})
        assert adapted["violations"] == marker


class TestTruncationCountIsUniform:
    """Operator decision 2: ``truncated=true`` never appears alone.

    Three truncation modes exist — text shrinking, list trimming, and
    whole-field dropping — and only list trimming used to record a
    count. These run the real ``_bounded_rich_fields``.
    """

    @staticmethod
    def _violations(n: int, msg_len: int) -> dict:
        return {
            "violations": [
                {"loc": f"field_{i}", "msg": "m" * msg_len, "type": "value_error"} for i in range(n)
            ]
        }

    def test_list_trimming_reports_what_it_dropped(self):
        out = _bounded_rich_fields(self._violations(40, 900))
        assert out["truncated"] is True
        assert out["violations_omitted_count"] == 40 - len(out["violations"])

    def test_text_shrinking_alone_still_reports_a_count(self):
        """Previously this branch set ``truncated`` and no count."""
        out = _bounded_rich_fields(self._violations(3, 4000))
        if out.get("truncated"):
            assert "violations_omitted_count" in out
            assert out["violations_omitted_count"] >= 0

    def test_a_wholly_dropped_list_reports_every_entry_as_omitted(self):
        out = _bounded_rich_fields(self._violations(200, 2000))
        assert out["truncated"] is True
        if not isinstance(out["violations"], list):
            assert out["violations_omitted_count"] == 200

    @pytest.mark.parametrize("n,msg_len", [(40, 900), (3, 4000), (200, 2000), (2, 30)])
    def test_truncated_never_appears_without_a_count(self, n, msg_len):
        out = _bounded_rich_fields(self._violations(n, msg_len))
        if out.get("truncated"):
            assert "violations_omitted_count" in out, (
                "truncated=true without an omitted count: the record admits "
                "evidence was cut but not how much was lost"
            )

    @pytest.mark.parametrize("n,msg_len", [(40, 900), (3, 4000), (200, 2000)])
    def test_the_byte_budget_still_holds(self, n, msg_len):
        out = _bounded_rich_fields(self._violations(n, msg_len))
        assert len(json.dumps(out, default=str).encode("utf-8")) <= RICH_FIELD_BUDGET_BYTES


class TestLegacyContractIsRestored:
    def test_the_tuner_would_record_the_operator_budget(self, tmp_path):
        """The exact A5 regression: ml_hyperparameter_tune_agent.py:3970
        writes ``memory.vram_budget_gb`` from ``limit_gb``. It landed as
        null; every pre-PR-A record held 12.0."""
        assert _run(tmp_path, COMPLETED).get("limit_gb") == 12.0

    def test_a_worker_that_omits_a_field_yields_none_not_a_crash(self, tmp_path):
        lean = {k: v for k, v in COMPLETED.items() if k not in ("limit_gb", "dominant_phase")}
        adapted = _run(tmp_path, lean)
        assert adapted.get("limit_gb") is None
        assert adapted.get("dominant_phase") is None
        assert adapted["status"] == "success"

    @pytest.mark.parametrize("payload", [COMPLETED, ABOVE_CAP, SCHEMA_REJECTED])
    def test_every_outcome_class_composes(self, tmp_path, payload):
        adapted = _run(tmp_path, payload)
        assert adapted["preflight_outcome"] == payload["outcome"]
        assert adapted["status"]


class TestSchemaDiffGuardrail:
    """Fail when the worker grows a field the IPC model cannot carry.

    Enumerated behaviorally — ``_classify`` is called for every status
    it handles — rather than by parsing the source, so the guard cannot
    be fooled by formatting.
    """

    @staticmethod
    def _worker_emitted_keys() -> set[str]:
        skill_outcomes = [
            {
                "status": "success",
                "feasible": True,
                "num_params": 1,
                "estimated_gb": 1.0,
                "inference_batch": 8,
                "limit_gb": 12.0,
                "dominant_phase": "training",
                "verdict": "v",
                "suggestion": "s",
            },
            {
                "status": "success",
                "feasible": False,
                "num_params": 1,
                "estimated_gb": 99.0,
                "limit_gb": 12.0,
                "verdict": "v",
                "suggestion": "s",
                "memory_killer": {"a": 1},
            },
            {
                "status": "schema_violation",
                "violations": [{"field": "f", "message": "m"}],
                "offending_config": {"f": 1},
                "message": "bad",
            },
            {"status": "host_memory", "message": "oom"},
            {"status": "cuda_oom", "message": "cuda oom"},
            {
                "status": "timeout",
                "message": "slow",
                "timeout_record": {
                    "operation": "op",
                    "budget_seconds": 10.0,
                    "elapsed_seconds": 11.0,
                },
            },
            {"status": "inconclusive", "message": "unknown"},
            {"status": "error", "message": "boom"},
        ]
        keys: set[str] = set()
        for outcome in skill_outcomes:
            keys |= set(_classify(outcome))
        return keys

    def test_every_worker_field_is_declared_by_the_ipc_model(self):
        emitted = self._worker_emitted_keys()
        declared = set(IsolatedProbeResult.model_fields)
        undeclared = emitted - declared
        assert not undeclared, (
            f"the worker emits {sorted(undeclared)}, which IsolatedProbeResult "
            "does not declare. Pydantic drops undeclared keys silently, so "
            "these never reach the adapter. Declare them on the model AND "
            "pass them in the payload branch of run_isolated_preflight — "
            "adding one without the other still loses the field."
        )

    def test_the_model_does_not_accept_arbitrary_extra_fields(self):
        """A widened model must stay a contract, not a bag."""
        result = IsolatedProbeResult.model_validate(
            {"label": "x", "outcome": "COMPLETED_MEASUREMENT", "invented_key": 1}
        )
        assert not hasattr(result, "invented_key")

    def test_the_repair_covers_the_exact_fields_a5_lost(self):
        """Named explicitly so a future refactor cannot quietly re-drop
        them and still pass the generic diff above."""
        declared = set(IsolatedProbeResult.model_fields)
        for field in (
            "limit_gb",
            "dominant_phase",
            "verdict",
            "suggestion",
            "violations",
            "offending_config",
            "memory_killer",
            "truncated",
        ):
            assert field in declared, f"{field} was lost in A5 and must stay declared"
