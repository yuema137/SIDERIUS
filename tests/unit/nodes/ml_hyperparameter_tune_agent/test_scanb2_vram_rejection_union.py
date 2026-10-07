"""F-SCANB-2 — a truncation-marker union payload must not crash admission.

The VRAM pre-flight worker deliberately replaces an oversized rich diagnostic
field with the truncation-marker STRING
``"[dropped: exceeded the rich-field budget]"``
(``agent/skills/evaluate_vram_skill/preflight_worker_main.py``,
``_bounded_rich_fields``) so its absence is explicit, and the parent-side
schema types the forwarded fields as unions —
``IsolatedProbeResult.violations: list[Any] | str | None`` and
``memory_killer`` / ``offending_config`` as ``dict[str, Any] | str | None``
(``agent/skills/evaluate_vram_skill/isolated_probe.py``). The consumer
``execution.run_admission_preflight`` never honoured the ``str`` member:
``.get`` on the marker string raised ``AttributeError``, so a CORRECT VRAM
rejection crashed the attempt — twice historically, each crash SPENDING the
attempt — instead of reaching the existing ``skipped_oom_risk`` /
``skipped_schema_violation`` record and the non-consuming
``AdmissionOutcome.next_attempt()``.

Fixture machinery mirrors ``test_c12p_b7_composed_step_guardrail.py``: the
node's private ``execution`` module is reached by full dotted path, internals
are stubbed on the module that CALLS them (``run_production_preflight`` and
``_check_and_record_guardrail_skip`` in ``execution``'s namespace), and
records are captured on ``_records._emit_record`` — the node's ONE emission
point.

The marker payloads are produced by driving the WORKER'S OWN truncation
function with an oversized field, never a hand-typed approximation, so
producer drift (a reworded marker) turns these tests red.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, PhysicalRejection
from agent.schemas.ordering import ResolvedOrdering
from agent.skills.evaluate_vram_skill.preflight_worker_main import _bounded_rich_fields
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AdmissionOutcome,
    AttemptIdentity,
    AttemptStage,
)

# The node package rebinds ``sys.modules[...]`` to its main module (see the
# package ``__init__``), so the private module is reached by its full dotted
# path — the same route ``execution`` itself uses for ``records``.
execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")

#: The marker DOCUMENTED on ``IsolatedProbeResult``'s union fields and on the
#: two ``execution.py`` helpers. Test (a) asserts the worker's own truncation
#: PRODUCES exactly this string, so the constant is anchored to the producer.
DOCUMENTED_MARKER = "[dropped: exceeded the rich-field budget]"


def _worker_truncated_field(field_name: str, oversized_value: object) -> str:
    """Drive the REAL producer until it drops ``field_name`` to the marker.

    ``_bounded_rich_fields`` clips text first and shortens lists before
    dropping a whole field, so the oversized fixtures below are built so that
    neither remedy can fit them inside ``RICH_FIELD_BUDGET_BYTES`` — the drop
    branch (``preflight_worker_main.py``, the marker assignment) must fire.
    """
    shrunk = _bounded_rich_fields({field_name: oversized_value})
    marker = shrunk[field_name]
    assert isinstance(marker, str), (
        f"fixture defect: the worker did not drop {field_name!r}; "
        f"got {type(marker).__name__} — the witness would no longer exercise "
        f"the str member of the union"
    )
    return marker


def _oversized_killer() -> dict:
    """A ``memory_killer`` too large for the 8 KiB rich-field budget even
    after text clipping (values are under the 400-char clip, so only the
    whole-field drop can shrink it)."""
    return {
        "binding_cap": "vram",
        "dominant_layer": "encoder.block3.conv",
        "dominant_layer_bytes": 5 * 1024**3,
        "dominant_fraction": 0.42,
        **{f"pad_{i:03d}": "x" * 100 for i in range(200)},
    }


def _oversized_violations() -> list[dict]:
    """A SINGLE oversized violation entry: the worker's list-shortening loop
    only halves lists longer than one, so the whole field must be dropped."""
    return [
        {
            "loc": "channels",
            "type": "value_error",
            "msg": "m" * 100,
            "input": 7,
            **{f"pad_{i:03d}": "y" * 100 for i in range(200)},
        }
    ]


def _infeasible_payload(memory_killer: object) -> dict:
    """The adapter-shaped ``feasible=False`` resource_check
    (``OUTCOME_TO_LEGACY`` maps ``MEASURED_PEAK_ABOVE_VRAM_CAP`` to legacy
    status ``"success"`` + ``feasible=False``)."""
    return {
        "status": "success",
        "preflight_outcome": "MEASURED_PEAK_ABOVE_VRAM_CAP",
        "feasible": False,
        "estimated_gb": 29.1,
        "limit_gb": 11.5,
        "verdict": "Estimated 29.1 GB exceeds 11.5 GB limit.",
        "suggestion": "Reduce batch_size or segmentation_size.",
        "truncated": True,
        "memory_killer": memory_killer,
    }


def _schema_violation_payload(violations: object) -> dict:
    return {
        "status": "schema_violation",
        "preflight_outcome": "SCHEMA_REJECTED",
        "verdict": "plugin schema rejected the proposed config",
        "suggestion": "",
        "violations": violations,
        "offending_config": DOCUMENTED_MARKER,
        "truncated": True,
        "violations_omitted_count": 1,
    }


def _drive_admission(monkeypatch, payload: dict):
    """Run ``run_admission_preflight`` with the pre-flight stubbed to return
    ``payload``. Returns ``(outcome, emitted_records, rejections_buffer)``.

    Stubs sit in ``execution``'s namespace — the module that CALLS them —
    per the node public-boundary recipe. The guardrail boundary is stubbed
    pass-through because its seam is owned by the B7 tests; everything from
    the VRAM gate onward is the production path.
    """
    emitted: list[dict] = []

    def _spy(
        sandbox,
        record,
        *,
        status=None,
        candidate_id=None,
        experiment_arm=None,
        ordering=None,
        ordering_observation=None,
        attempt_role=None,
    ):
        # #447 preserves selected ordering without claiming training executed.
        assert ordering == prepared.ordering
        assert ordering_observation.model_dump() == {
            "selection_state": "selected",
            "refused_before_phase": "preflight",
        }
        assert attempt_role == "trial"
        emitted.append(record)

    monkeypatch.setattr(execution._records, "_emit_record", _spy)
    monkeypatch.setattr(execution, "run_production_preflight", lambda **kwargs: payload)
    monkeypatch.setattr(execution, "_check_and_record_guardrail_skip", lambda **kwargs: False)

    bindings = SimpleNamespace(
        agent_input=HyperparamTuningInput(
            model_type="synthetic_model",
            run_name="scanb2",
            workspace="/tmp/scanb2-unused",
            candidate_id=None,
            experiment_arm=None,
            task_composition_ref=None,
            validation_max_train_samples=None,
        ),
        device_identity=None,
        expert_advice_str="",
        file_index=6,
        formal_reference_score=None,
        formal_time_budget=None,
        formal_vram_budget=None,
        hardware_context=SimpleNamespace(),
        resolved_bypass_formal_threshold=None,
        run_model_io=None,
        run_name="scanb2",
        run_order=None,
        run_profile=None,
        sandbox=SimpleNamespace(plugin_dir=None, loss_dir=None),
        time_data_dir=None,
        trial_time_budget=None,
        trial_vram_budget=11.5,
        workspace="/tmp/scanb2-unused",
    )
    prepared = SimpleNamespace(
        ordering=ResolvedOrdering(resolved_strategy="shuffle", resolution_source="default"),
        active_params={
            "model_type": "punet",
            "model_config": {"depth": 4},
            "train_config": {"epochs": 1},
            "loss_config": {"loss_type": "ce"},
            "batch_size": 4,
            "segmentation_size": 40_000,
            "depth": 4,
        },
        exp_id="scanb2-exp",
        hypothesis="h",
        memory_history=[],
        model_config={"depth": 4},
        model_type="punet",
        plan=SimpleNamespace(is_trial=True),
        record_params={},
        train_sample_set=None,
        trial_config=SimpleNamespace(
            train_base_seed=None,
            train_portion=None,
        ),
        task_scopes=None,
        expected_custom_loss_snapshot=None,
    )
    rejections: list[PhysicalRejection] = []
    outcome = execution.run_admission_preflight(
        bindings,
        prepared,
        AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=False),
        AttemptStage(name="start"),
        formal_trial_winner=None,
        physical_rejections_buffer=rejections,
    )
    return outcome, emitted, rejections


class TestRealMarkerInfeasibleRejection:
    def test_worker_truncated_memory_killer_reaches_the_skip_record(self, monkeypatch):
        """F-SCANB-2, the infeasible branch — the defect only this catches:
        a CORRECT VRAM rejection whose ``memory_killer`` was truncated to the
        worker's marker string crashed ``run_admission_preflight`` with
        ``AttributeError`` (``.get`` on a str), which happened twice
        historically and SPENT the attempt each time, instead of emitting the
        ``skipped_oom_risk`` record and returning the non-consuming
        ``next_attempt`` outcome.

        The payload's marker comes from the worker's OWN truncation function,
        and this test pins it EQUAL to the documented string — producer drift
        (a reworded marker) fails here first.

        HOW IT FAILS WHEN THE BEHAVIOUR BREAKS: the ``.get``-on-str crash
        returns — ``run_admission_preflight`` raises ``AttributeError``
        instead of returning, and no record is emitted.
        """
        marker = _worker_truncated_field("memory_killer", _oversized_killer())
        assert marker == DOCUMENTED_MARKER, (
            "the worker's truncation marker drifted from the documented "
            "string; update the union docstrings and the execution.py helpers "
            "TOGETHER with the producer"
        )
        payload = _infeasible_payload(memory_killer=marker)

        outcome, emitted, rejections = _drive_admission(monkeypatch, payload)

        assert len(emitted) == 1, f"expected exactly one skip record, got {len(emitted)}"
        record = emitted[0]
        assert record["status"] == "skipped_oom_risk"
        # Absence of structure stays EXPLICIT through the forwarded prose:
        # the record carries the worker's verdict and suggestion verbatim.
        assert record["memory"]["discovery"] == payload["verdict"]
        assert record["memory"]["memory_update"] == payload["suggestion"]
        assert record["memory"]["vram_estimate_gb"] == 29.1
        assert record["memory"]["vram_budget_gb"] == 11.5
        # Best-effort PhysicalRejection capture survives the marker: the
        # structural fields default rather than crash.
        assert len(rejections) == 1
        assert rejections[0].binding_cap == "vram"
        assert rejections[0].dominant_layer == ""
        assert rejections[0].dominant_layer_gb == 0.0
        assert rejections[0].dominant_fraction == 0.0
        # The existing non-consuming shape — this attempt does NOT count.
        assert outcome == AdmissionOutcome.next_attempt()

    def test_the_marker_payload_exercises_the_str_member_of_the_union(self):
        """F-SCANB-2 mutation control — the defect only this catches: the
        witness above silently degrading to a dict/None-shaped fixture, which
        would make it pass against the PRE-FIX consumer too and guard
        nothing (the two historical attempt-spending crashes were exactly
        the str member nobody drove).

        The expression below is the pre-fix consumer read
        (``execution.py``'s infeasible branch before the F-SCANB-2 repair,
        ``resource_check.get("memory_killer") or {}`` then ``.get``). It must
        CRASH on this payload.

        HOW IT FAILS WHEN THE BEHAVIOUR BREAKS: if the fixture ever stops
        carrying the str member (dict or absent ``memory_killer``), the
        pre-fix expression succeeds and ``pytest.raises`` errors — pinning
        that the sibling test still exercises the fixed line.
        """
        payload = _infeasible_payload(
            memory_killer=_worker_truncated_field("memory_killer", _oversized_killer())
        )
        with pytest.raises(AttributeError):
            (payload.get("memory_killer") or {}).get("binding_cap", "vram")


class TestRealMarkerSchemaViolation:
    def test_worker_truncated_violations_reach_the_skip_record(self, monkeypatch):
        """F-SCANB-2, the schema-violation twin — the defect only this
        catches: a ``violations`` payload truncated to the marker string is
        ITERABLE, so the branch crashed one line later than the infeasible
        one (``v.get(...)`` on a character), again before its
        ``skipped_schema_violation`` record — the same attempt-spending
        failure class as the two historical crashes.

        HOW IT FAILS WHEN THE BEHAVIOUR BREAKS: ``run_admission_preflight``
        raises ``AttributeError`` from the per-violation reads instead of
        returning, and no record is emitted.
        """
        marker = _worker_truncated_field("violations", _oversized_violations())
        assert marker == DOCUMENTED_MARKER
        payload = _schema_violation_payload(violations=marker)

        outcome, emitted, _ = _drive_admission(monkeypatch, payload)

        assert len(emitted) == 1
        record = emitted[0]
        assert record["status"] == "skipped_schema_violation"
        # No structured violations -> the branch's own explicit-absence
        # wording; and the raw union field interpolates AS the marker, so
        # the truncation stays visible in the record text.
        assert "Violating fields: unknown" in record["memory"]["conclusion"]
        assert DOCUMENTED_MARKER in record["memory"]["conclusion"]
        assert "unspecified schema violation" in record["memory"]["memory_update"]
        assert outcome == AdmissionOutcome.next_attempt()


class TestStructuredPayloadParity:
    def test_dict_shaped_memory_killer_is_consumed_exactly_as_before(self, monkeypatch):
        """F-SCANB-2 parity guard — the defect only this catches: the
        normalization helpers OVER-normalizing, i.e. flattening a
        dict-shaped ``memory_killer`` to ``{}`` and silently degrading every
        structured rejection to defaults. The fix exists to stop the two
        historical marker crashes; the structured path must stay
        byte-for-byte in semantics.

        HOW IT FAILS WHEN THE BEHAVIOUR BREAKS: a helper that discards the
        dict makes ``dominant_layer`` collapse to ``""`` (and the other
        killer fields to their defaults), and the exact-value assertions
        below go red.
        """
        payload = _infeasible_payload(
            memory_killer={
                "binding_cap": "vram",
                "dominant_layer": "encoder.attention.block7.mha",
                "dominant_layer_bytes": int(13.4 * 1024**3),
                "dominant_fraction": 0.46,
            }
        )

        outcome, emitted, rejections = _drive_admission(monkeypatch, payload)

        assert len(emitted) == 1
        record = emitted[0]
        assert record["status"] == "skipped_oom_risk"
        assert record["memory"]["discovery"] == payload["verdict"]
        assert record["memory"]["memory_update"] == payload["suggestion"]
        assert record["memory"]["vram_estimate_gb"] == 29.1
        assert record["memory"]["vram_budget_gb"] == 11.5
        assert len(rejections) == 1
        rej = rejections[0]
        assert isinstance(rej, PhysicalRejection)
        assert rej.binding_cap == "vram"
        assert rej.dominant_layer == "encoder.attention.block7.mha"
        assert rej.dominant_layer_gb == 13.4
        assert rej.dominant_fraction == 0.46
        assert rej.budget_gb == 11.5
        assert rej.estimated_gb == 29.1
        assert rej.suggestion == payload["suggestion"]
        assert outcome == AdmissionOutcome.next_attempt()
