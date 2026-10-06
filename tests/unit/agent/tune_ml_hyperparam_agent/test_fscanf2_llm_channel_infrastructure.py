"""A provider outage is not a verdict on the candidate.

F-SCANF-2 (release blocker). ``INFRASTRUCTURE_FAILURE_STATUS`` exists and is
correctly designed — it was split out of ``skipped_resource_admission`` after
V20 attempt 2 wrote 15 "the GPU was full" records while the GPU held 1.6 of
32.6 GiB — but its reason map covered only resource-admission reasons, and its
only callers were the admission path. A grep of
``nodes/ml_hyperparameter_tune_agent/records.py`` for ``LLMError``,
``llm_error``, ``APIError`` or ``provider`` returned ZERO matches.

So an LLM or provider failure reaching the planner or the reflector was
recorded as ``status: "error"`` with ``counts_toward_attempt_budget: True``,
and — the half that reaches the model — a memory narrative reading "Do not
repeat the failing configuration unchanged. Correct the planning failure
before retrying." An API timeout arrived at the next planner as evidence about
the candidate. That violates frozen ``D-FAIL-1``/``D-FAIL-5``: an
infrastructure failure must not consume scientific opportunity.

SCOPE, stated so these tests are not over-read. This is the REPORTING half:
the record's status, its budget accounting, and the narrative the LLM channel
receives. It does NOT change the attempt loop's control flow — whether a
provider outage should be RETRIED into the same scientific opportunity is
``D-FAIL-2``'s accounting half and lives in ``run()``'s retry structure. The
tests below assert the record, and deliberately assert nothing about how many
attempts the loop spends.
"""

from __future__ import annotations

import ast
import tempfile
from unittest.mock import patch

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    INFRASTRUCTURE_FAILURE_STATUS,
    LLM_PROVIDER_FAILURE_REASON,
    RESOURCE_ADMISSION_REASONS,
    HyperparamTuningAgent,
)
from nodes.ml_hyperparameter_tune_agent.records import (
    classify_attempt_failure_disposition,
)
from nodes.scoring_reference import ReferenceScores
from tests.helpers.tuner_source import tuner_node_source

_REQUEST = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")


_REFERENCE_STUB = ReferenceScores(
    raw_per_file_log=[-2.7] * 20,
    gt_per_file_log=[7.0] * 20,
    raw_per_file_linear_sum=[2.0] * 20,
    raw_per_file_n_segments=[200] * 20,
    gt_per_file_linear_sum=[2000.0] * 20,
    gt_per_file_n_segments=[200] * 20,
    raw_scalar_full=-2.7,
    gt_scalar_full=7.0,
    s_max=295_715_680.14,
)


def _drive_one_attempt(tmp_path, planning_error: BaseException) -> list[dict]:
    """Run ONE tuner attempt whose ``brain.plan`` raises ``planning_error``.

    Everything heavy is stubbed (bridge, sandbox, skills, reference scores)
    and the round position declares no gates, so the only thing this exercises
    is the attempt handler: a real ``run()``, a real exception out of the
    planning stage, and the records the sandbox is asked to save.
    """
    agent_input = HyperparamTuningInput(
        planner_strategy="native-timing-v1",
        model_type="punet",
        file_index=6,
        max_rounds=1,
        attempts_per_round=1,
        attempts_per_formal_round=1,
        max_fail_rounds=1,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="fscanf2_run"),
        ),
        progress_bar=False,
    )
    saved: list[dict] = []
    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_REFERENCE_STUB,
        ),
        patch(
            "nodes.ml_hyperparameter_tune_agent.round_health.get_gates_for_position",
            return_value=[],
        ),
        patch("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent.time.sleep"),
        patch(
            "nodes.ml_hyperparameter_tune_agent.runtime._run_skill",
            side_effect=lambda folder, sandbox, **kw: (
                {"status": "success", "data": {"punet": {"fields": ["depth"]}}}
                if folder == "check_config_format_skill"
                else {"status": "error", "message": f"unexpected skill {folder}"}
            ),
        ),
        tempfile.TemporaryDirectory() as configs_dir,
    ):
        MockBridge.return_value.plan.side_effect = planning_error
        sandbox = MockSandbox.return_value
        sandbox.get_summary.side_effect = lambda: list(saved)
        sandbox.save_record.side_effect = saved.append
        sandbox.dirs = {"configs": configs_dir}
        agent = HyperparamTuningAgent()
        agent.run(agent_input)
    return saved


def _failure_record_dict() -> ast.Dict:
    """The ``failure_record = {...}`` literal in the tuner's attempt handler.

    Located by AST so the assertions below are about THAT dict and nothing
    else in the node. Its absence is itself a failure: a rename means the
    guard no longer watches what it claims to.
    """
    for node in ast.walk(ast.parse(tuner_node_source())):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "failure_record" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    raise AssertionError("no `failure_record = {...}` assignment found in the tuner node")


def _provider_errors() -> list[BaseException]:
    """One instance of each shape ``_call_with_retry`` re-raises.

    ``LLMBridge._call_with_retry`` re-raises the SDK exception UNWRAPPED —
    immediately for a non-retryable status, and after its bounded budget for
    connection/timeout errors — and neither ``plan`` nor ``reflect`` catches
    it. These are the objects that actually reach the attempt handler.
    """
    return [
        APITimeoutError(request=_REQUEST),
        APIConnectionError(request=_REQUEST),
        APIStatusError("bad key", response=httpx.Response(401, request=_REQUEST), body=None),
        APIStatusError("rate limited", response=httpx.Response(429, request=_REQUEST), body=None),
    ]


class TestAProviderFailureIsClassifiedAsInfrastructure:
    """The row's acceptance test."""

    @pytest.mark.parametrize("exc", _provider_errors(), ids=lambda e: type(e).__name__ + "_")
    def test_it_resolves_to_the_infrastructure_status(self, exc: BaseException) -> None:
        """FAILS with ``status == "error"`` when the fix is removed."""
        disposition = classify_attempt_failure_disposition(exc, failure_type=type(exc).__name__)

        assert disposition.status == INFRASTRUCTURE_FAILURE_STATUS
        assert disposition.reason_code == LLM_PROVIDER_FAILURE_REASON

    @pytest.mark.parametrize("exc", _provider_errors(), ids=lambda e: type(e).__name__ + "__")
    def test_it_does_not_spend_scientific_opportunity(self, exc: BaseException) -> None:
        disposition = classify_attempt_failure_disposition(exc, failure_type=type(exc).__name__)

        assert disposition.counts_toward_attempt_budget is False

    def test_the_llm_reason_is_not_an_admission_reason(self) -> None:
        """It shares the status map, never the admission vocabulary.

        ``_build_resource_admission_record`` refuses an unknown reason code,
        and a provider outage is not an admission decision — filing it as one
        would repeat the V20 attempt-2 mistake in a different coordinate.
        """
        assert LLM_PROVIDER_FAILURE_REASON not in RESOURCE_ADMISSION_REASONS


class TestACandidateFailureIsUnCHANGED:
    """Every non-provider failure keeps the posture it had."""

    @pytest.mark.parametrize(
        "exc",
        [ValueError("bad config"), RuntimeError("CUDA out of memory"), KeyError("missing")],
        ids=["value", "runtime", "key"],
    )
    def test_it_still_consumes_the_attempt_and_reads_as_an_error(self, exc: BaseException) -> None:
        disposition = classify_attempt_failure_disposition(exc, failure_type=type(exc).__name__)

        assert disposition.status == "error"
        assert disposition.reason_code is None
        assert disposition.counts_toward_attempt_budget is True

    def test_its_narrative_is_byte_identical_to_the_pre_fix_wording(self) -> None:
        """A real code bug must teach exactly what it taught before.

        Hardcoded, not re-derived from the production strings: the point is
        that these three sentences did not move.
        """
        disposition = classify_attempt_failure_disposition(
            ValueError("boom"), failure_type="ValueError"
        )
        narrative = disposition.memory_narrative(
            failure_stage="training", failure_reason="boom", record_params={"lr": 0.1}
        )

        assert narrative == {
            "conclusion": "Attempt failed during training: boom",
            "discovery": "ValueError in training; proposed_config={'lr': 0.1}",
            "memory_update": (
                "Do not repeat the failing configuration unchanged. "
                "Correct the training failure before retrying."
            ),
        }


class TestTheNarrativeTheModelReadsNoLongerBlamesTheCandidate:
    """The LLM channel is where the misattribution actually landed."""

    def test_it_does_not_tell_the_planner_to_change_the_configuration(self) -> None:
        disposition = classify_attempt_failure_disposition(
            APITimeoutError(request=_REQUEST), failure_type="APITimeoutError"
        )
        narrative = disposition.memory_narrative(
            failure_stage="planning", failure_reason="timed out", record_params={"lr": 0.1}
        )

        assert "Do not repeat the failing configuration" not in narrative["memory_update"]
        assert "Do NOT change the configuration" in narrative["memory_update"]
        assert "infrastructure condition" in narrative["conclusion"]
        assert "NOT evidence about" in narrative["discovery"]
        assert narrative["reason_code"] == LLM_PROVIDER_FAILURE_REASON

    def test_the_key_order_the_record_depends_on_is_preserved(self) -> None:
        """``memory`` key order is a recorded property (OD-1)."""
        science = classify_attempt_failure_disposition(
            ValueError("x"), failure_type="ValueError"
        ).memory_narrative(failure_stage="training", failure_reason="x", record_params={})
        infra = classify_attempt_failure_disposition(
            APITimeoutError(request=_REQUEST), failure_type="APITimeoutError"
        ).memory_narrative(failure_stage="planning", failure_reason="x", record_params={})

        assert list(science) == ["conclusion", "discovery", "memory_update"]
        assert list(infra) == ["conclusion", "discovery", "memory_update", "reason_code"]


class TestProductionReachesTheBoundary:
    """A second hand-rolled classification would silently restore the defect."""

    def test_the_attempt_handler_reads_the_disposition_for_both_fields(self) -> None:
        """Severing the call is not enough to keep this green.

        The handler must take BOTH its status and its budget flag from the
        disposition. Re-inlining either literal — ``"status": "error"`` or
        ``"counts_toward_attempt_budget": True`` — is what this catches.
        """
        source = tuner_node_source()

        assert "classify_attempt_failure_disposition(" in source
        assert '"status": disposition.status,' in source
        assert "disposition.counts_toward_attempt_budget" in source
        assert "disposition.memory_narrative(" in source

    def test_the_attempt_failure_record_holds_no_status_constant(self) -> None:
        """The two literals must be GONE from that dict, not merely shadowed.

        Scoped to the ``failure_record`` dict by AST rather than by a text
        search over the node: ``"status": "error"`` legitimately appears in
        ``records._interpret_training_status``'s rewritten TRAINING status,
        which is a different concept, and a whole-node string ban would fail
        on it while proving nothing about this record.
        """
        record = _failure_record_dict()
        for key, value in zip(record.keys, record.values, strict=True):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if key.value not in ("status", "counts_toward_attempt_budget"):
                continue
            assert isinstance(value, ast.Attribute) and value.attr in (
                "status",
                "counts_toward_attempt_budget",
            ), (
                f"failure_record[{key.value!r}] is a literal again — it must be "
                "read from the disposition"
            )

    def test_nobody_hand_assembles_the_provider_reason(self) -> None:
        """One spelling, in the constant that owns it.

        Mirrors the resource-admission census: the reason string must not
        appear as a literal inside any function in the tuner's main module.
        """
        holders = set()
        tree = ast.parse(tuner_node_source())
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value == "llm_provider_unavailable"
                ):
                    holders.add(fn.name)
        assert holders == set(), (
            f"{sorted(holders)} name the reason literally; it belongs to "
            "LLM_PROVIDER_FAILURE_REASON so there is one spelling"
        )


class TestTheRecordAProviderOutageActuallyPersists:
    """The production path, driven: ``brain.plan`` raises, ``run()`` records.

    The AST guards above prove the handler READS the disposition. This proves
    what a real round persists when the provider is down — the artifact an
    auditor reads and the memory the next planner is handed.
    """

    def test_a_planning_provider_timeout_is_recorded_as_infrastructure(self, tmp_path) -> None:
        saved = _drive_one_attempt(tmp_path, APITimeoutError(request=_REQUEST))

        failure = next(r for r in saved if r.get("record_type") == "attempt_failure")
        assert failure["status"] == INFRASTRUCTURE_FAILURE_STATUS
        assert failure["counts_toward_attempt_budget"] is False
        assert failure["counts_toward_completed_rounds"] is False
        assert failure["memory"]["reason_code"] == LLM_PROVIDER_FAILURE_REASON
        assert "Do NOT change the configuration" in failure["memory"]["memory_update"]

    def test_a_planning_code_bug_is_still_the_candidates(self, tmp_path) -> None:
        """The discriminator, driven the same way: same stage, same handler."""
        saved = _drive_one_attempt(tmp_path, ValueError("bad plan"))

        failure = next(r for r in saved if r.get("record_type") == "attempt_failure")
        assert failure["status"] == "error"
        assert failure["counts_toward_attempt_budget"] is True
        assert "reason_code" not in failure["memory"]
        assert "Do not repeat the failing configuration" in failure["memory"]["memory_update"]


class TestTheProviderSurfaceIsDeclaredByItsOwner:
    """The transport module declares what it can raise; records consumes it."""

    def test_the_bridge_exports_the_transport_error_family(self) -> None:
        from agent.llm_bridge import LLM_PROVIDER_TRANSPORT_ERRORS

        assert LLM_PROVIDER_TRANSPORT_ERRORS
        for exc in _provider_errors():
            assert isinstance(exc, LLM_PROVIDER_TRANSPORT_ERRORS), (
                f"{type(exc).__name__} escapes the declared provider surface"
            )

    def test_the_classifier_matches_by_type_not_by_class_name(self) -> None:
        """A string match on the class name is the defect one layer down.

        A provider SDK subclass nobody enumerated must still classify as
        infrastructure, which an `isinstance` check gives and a name list
        does not.
        """

        class UnenumeratedProviderError(APIConnectionError):
            pass

        disposition = classify_attempt_failure_disposition(
            UnenumeratedProviderError(request=_REQUEST),
            failure_type="UnenumeratedProviderError",
        )

        assert disposition.status == INFRASTRUCTURE_FAILURE_STATUS


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
