"""Pseudo-mode sandbox: ``StubSandbox`` (selected only by ``--is_pseudo_training``).

Kept outside ``core.sandbox_executor`` on purpose (issue #1475):
``core.runtime_control.verifier_provider.verifier_assembly_digest`` hashes the
production executor's bytes, so pseudo-only edits here do not move the
paper-facing verifier assembly identity. Real runs never construct this class.
Synthetic deliverables and formula evidence are owned by
``core.pseudo_deliverables`` and ``core.pseudo_scoring``.
"""

import random
from typing import Any

from pydantic import StrictBool

from core.generated_artifact_name import validate_generated_artifact_name
from core.sandbox_executor import TidmadSandbox, _scope_violation_result
from core.training_execution_bindings import TrainingExecutionBindings
from core.training_seeds import SeedContext
from execute_tools.dataset_config import DataScope, ScopeViolationError
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.evaluation_metric import EvaluationMetric, MetricResult
from execute_tools.scope_artifact import task_scope_argv
from execute_tools.scoring_utils import validate_sample_set
from execute_tools.training_history import (
    TRAINING_HISTORY_KEY,
    TrainingHistory,
    objective_config_fingerprint,
    stamp_comparability,
)
from ml_models.models_format_sandbox import LossConfig


# ---------------------------------------------------------------------------
# StubSandbox — synthetic, deterministic sandbox for 0-cost smoke runs
# ---------------------------------------------------------------------------
#
# Subclasses ``TidmadSandbox`` so it inherits the recorder/workspace plumbing
# and stays a drop-in replacement at the chain orchestration layer. Overrides
# the four execution methods (``execute_training`` / ``execute_inference`` /
# ``execute_scoring`` / ``save_record``) to skip every subprocess launch and
# synthesise pydantic-valid results from a single run-id-seeded RNG.
#
# Determinism contract: ``random.Random(self._run_id)`` — passing the string
# directly uses CPython's stable SHA-512-based seeding path, so the same
# ``run_id`` yields the same number stream on every fresh interpreter.
# ``random.Random(hash(run_id))`` would NOT be stable: ``hash()`` on strings
# is randomized per-process via ``PYTHONHASHSEED``.
class StubSandbox(TidmadSandbox):
    """Stateless, deterministic sandbox for pseudo-mode smoke runs.

    The chain orchestration layer (``ml_hyperparameter_tune_agent``) treats
    a sandbox as a black box that returns ``status: success`` plus a results
    dict shaped like the production trainer / inference / scorer output.
    StubSandbox honours that contract without launching any subprocesses
    or writing any GPU artefacts. Composed inference reads task inputs
    and writes explicitly synthetic deliverables through the task codec.

    Per-method synthesis:
        * ``execute_training``: ``final_loss`` ∈ [0.5, 5.0],
          ``loss_history`` = [final_loss], ``model_params`` ∈ [1e3, 1e8].
        * ``execute_inference``: empty per-file timing list, fixed 10 ms
          ``process_startup_ms`` / ``subprocess_wall_ms``.
        * ``execute_scoring``: merges cached training results (mirroring the
          prod merge order in ``TidmadSandbox.execute_scoring``) and adds
          ``denoising_score`` ∈ [-3.0, -2.0], a length-9 ``file_vector``,
          ``is_degenerate=False``, ``failure_reason=None``.
        * ``save_record``: stamps ``_pseudo_origin = "stub_sandbox"`` on the
          record dict (audit trail to distinguish synthetic smoke results
          from real measurements), then delegates to the parent recorder
          for on-disk persistence and mirrors the record into
          ``self.saved_records`` for unit-test inspection.
    """

    def __init__(
        self,
        metadata_source: str = "local",
        mongodb_uri: str | None = None,
        run_name: str = "test_run",
        workspace: str = "./siderius_workspace",
        progress_bar: bool = False,
        file_index: int = 6,
        run_id: str | None = None,
        data_scope: DataScope | None = None,
        device_identity: Any = None,
        deliverable_naming: DeliverableNaming | None = None,
        device_available: StrictBool | None = None,
    ):
        # `deliverable_naming` mirrors the parent for exactly the reason given
        # below for `device_identity`: the tuner resolves the run's naming once
        # and passes it to whatever sandbox the factory returns, so a stub that
        # does not accept it makes pseudo mode unusable through the tuner.
        #
        # `device_identity` mirrors the parent (V20 PR B, #153). The tuner
        # resolves the identity ONCE at the orchestration boundary and passes
        # it to whatever sandbox the factory returns, so a stub that does not
        # accept it makes pseudo-training unusable through the tuner —
        # `TypeError: StubSandbox.__init__() got an unexpected keyword
        # argument 'device_identity'`. It is forwarded rather than dropped so
        # a pseudo run describes the same device as a real one.
        super().__init__(
            metadata_source=metadata_source,
            mongodb_uri=mongodb_uri,
            run_name=run_name,
            workspace=workspace,
            progress_bar=progress_bar,
            file_index=file_index,
            data_scope=data_scope,
            device_identity=device_identity,
            device_available=device_available,
            deliverable_naming=deliverable_naming,
        )
        self._run_id: str = run_id or run_name
        self._rng = random.Random(self._run_id)
        self.saved_records: list[dict[str, Any]] = []
        # Cache training results so ``execute_scoring`` can merge them like
        # prod does (the prod path reads ``experiment_results_*.json`` from
        # disk; the stub keeps an in-memory analogue keyed by ``exp_id``).
        self._train_results_cache: dict[str, dict[str, Any]] = {}

    def set_run_context(self, run_id: str) -> None:
        """Re-seed the RNG with a new run_id.

        Mirrors ``StubLLMBridge.set_run_context`` so the chain runner can
        bind both the bridge and the sandbox to the same ``run_id`` and get
        consistent synthetic outputs across the two layers.
        """
        self._run_id = run_id
        self._rng = random.Random(self._run_id)

    def execute_training(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: dict,
        t_cfg: dict,
        l_cfg: dict,
        sample_set: dict | None = None,
        train_portion: float | None = None,
        seed_context: SeedContext | None = None,
        runtime_policy: dict | None = None,
        order_strategy: str = "shuffle",
        file_order: list[int] | None = None,
        eval_sample_set: dict | None = None,
        execution_bindings: TrainingExecutionBindings | None = None,
    ) -> dict[str, Any]:
        """Synthesise a successful training result. No subprocess launch.

        DataScope parity with the production executor: pseudo-mode tests
        must exercise the boundary invariant, not bypass it.
        ``runtime_policy`` is accepted for signature parity (RT2-B); the
        stub never runs verification, so the result carries
        ``runtime_verification=None`` — the explicit-absence shape
        downstream consumers already fail closed on (§7.3).
        ``order_strategy`` / ``file_order`` are likewise accepted for
        signature parity (V19 PR 2) — the stub trains nothing, so there is
        no visitation order to apply, but a pseudo run must not diverge
        from production at the call boundary. ``eval_sample_set`` (Step
        07a) is accepted and scope-validated exactly like the executor's,
        so a pseudo run exercises the same boundary as production.
        """
        validate_generated_artifact_name(run_name, field="run_name")
        if sample_set is not None:
            try:
                validate_sample_set(sample_set, scope=self.data_scope)
                if eval_sample_set is not None:
                    validate_sample_set(eval_sample_set, scope=self.data_scope)
            except ScopeViolationError as e:
                return _scope_violation_result(e)
        # Step 07a (OD-S7-4): a plausible MULTI-EPOCH train + validation
        # history so pseudo runs and 07b's Gate 1 exercise a real diagnosis.
        # Deterministic from the stub's seeded rng: 5 strictly decreasing
        # training observations ending at `final_loss`; validation
        # decreasing for four epochs then rising slightly (a best-epoch that
        # is not the last). R3 is emitted ONLY when an eval SampleSet was
        # supplied — exactly the production trainer's expected/absent rule.
        final_loss = self._rng.uniform(0.5, 5.0)
        drops = sorted(self._rng.uniform(0.05, 0.6) for _ in range(4))
        loss_history = [final_loss]
        for d in drops:
            loss_history.insert(0, loss_history[0] * (1.0 + d))
        stub_loss_cfg = LossConfig(**l_cfg)
        validation_history = None
        validation_seconds = None
        validation_rows = None
        if eval_sample_set is not None:
            gap = self._rng.uniform(0.01, 0.15)
            validation_history = [v * (1.0 + gap) for v in loss_history]
            validation_history[-1] = validation_history[-2] * (1.0 + self._rng.uniform(0.01, 0.05))
            validation_seconds = [round(self._rng.uniform(0.05, 0.5), 3) for _ in loss_history]
            validation_rows = sum(len(v) for v in eval_sample_set.values())
        history = TrainingHistory(
            objective_kind=stub_loss_cfg.loss_type,
            objective_config_fingerprint=objective_config_fingerprint(stub_loss_cfg),
            objective_reduction=stub_loss_cfg.reduction,
            comparability=stamp_comparability(stub_loss_cfg)[0],
            comparability_reason=stamp_comparability(stub_loss_cfg)[1],
            epochs_planned=len(loss_history),
            epochs_completed=len(loss_history),
            train_objective=list(loss_history),
            validation_objective=None if validation_history is None else list(validation_history),
            validation_requested_samples=validation_rows,
            validation_samples=validation_rows,
            validation_seconds=validation_seconds,
        )
        results = {
            "final_loss": final_loss,
            "loss_history": loss_history,
            "model_params": self._rng.randint(1_000, 100_000_000),
            TRAINING_HISTORY_KEY: history.model_dump(),
        }
        self._train_results_cache[exp_id] = results
        return {
            "status": "success",
            "message": "stub_training_ok",
            "results": results,
            "runtime_verification": None,
        }

    def execute_inference(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: dict,
        l_cfg: dict,
        sample_set: dict | None = None,
        inference_batch: int | None = None,
        runtime_policy: dict | None = None,
        task_scopes: object = None,
    ) -> dict[str, Any]:
        """Synthesise a successful inference result. No subprocess launch.

        DataScope parity with the production executor (error-dict shape
        mirrors ``TidmadSandbox.execute_inference``, timing fields included).
        ``runtime_policy`` accepted for RT2-D signature parity;
        ``runtime_verification=None`` is the explicit-absence shape.
        Composed scopes use the production transport owner and task codec;
        synthetic predictions also pass through the ordinary task deliverable writer.
        """
        validate_generated_artifact_name(run_name, field="run_name")
        if getattr(task_scopes, "training", None) is not None:
            validate_generated_artifact_name(exp_id, field="exp_id")
        if sample_set is not None:
            try:
                validate_sample_set(sample_set, scope=self.data_scope)
            except ScopeViolationError as e:
                return {
                    **_scope_violation_result(e),
                    "per_file_timings_ms": [],
                    "process_startup_ms": None,
                    "subprocess_wall_ms": None,
                }
        task_scope_argv(self.dirs["configs"], exp_id, task_scopes)
        from core.pseudo_deliverables import write_pseudo_deliverable

        write_pseudo_deliverable(
            output_dir=self.base_dir,
            data_dir=self.dirs["data"],
            exp_id=exp_id,
            run_name=run_name,
            model_type=model_type,
            task_scopes=task_scopes,
            max_samples=(runtime_policy or {}).get("validation_max_samples"),
        )
        return {
            "status": "success",
            "message": "stub_inference_ok",
            "per_file_timings_ms": [],
            "process_startup_ms": 10.0,
            "subprocess_wall_ms": 10.0,
            "runtime_verification": None,
        }

    def execute_scoring(
        self,
        exp_id: str,
        run_name: str,
        model_type: str,
        m_cfg: dict,
        t_cfg: dict,
        l_cfg: dict,
        task_scopes: object = None,
    ) -> dict[str, Any]:
        """Synthesise scoring + merge cached training results.

        Mirrors the prod merge order in ``TidmadSandbox.execute_scoring``:
        training keys first, then scoring keys (so ``final_loss`` /
        ``loss_history`` / ``model_params`` from the cached trainer output
        appear alongside the synthetic ``denoising_score`` etc.).
        Composed scopes use the same transport owner as production, without
        launching the scorer or interpreting any scientific scope semantics.
        A composed formula ``evaluation`` additionally receives synthetic
        component evidence from ``core.pseudo_scoring`` (the child's
        aggregation owner, synthetic source values); other runs keep the
        legacy payload and random stream.
        """
        validate_generated_artifact_name(run_name, field="run_name")
        if getattr(task_scopes, "training", None) is not None:
            validate_generated_artifact_name(exp_id, field="exp_id")
        task_scope_argv(self.dirs["configs"], exp_id, task_scopes)
        results: dict[str, Any] = {}
        results.update(self._train_results_cache.get(exp_id, {}))
        results["denoising_score"] = self._rng.uniform(-3.0, -2.0)
        results["file_vector"] = [self._rng.uniform(-3.0, -2.0) for _ in range(9)]
        results["is_degenerate"] = False
        results["failure_reason"] = None
        from core.pseudo_scoring import synthetic_formula_scoring

        formula = synthetic_formula_scoring(
            self._rng, results["denoising_score"], results["file_vector"]
        )
        if formula is None:
            return {"status": "success", "results": results}
        results.update(formula)
        if "not_scoreable" in formula:
            message = "Synthetic formula evaluation evidence is not scoreable"
            return {"status": "error", "message": message, "results": results}
        return {"status": "success", "results": results}

    def evaluate_metric(
        self,
        metric: EvaluationMetric,
        sample_set,
        anchor_map: dict,
        s_max: float,
        denoised_filename_fn,
        **kwargs,
    ) -> MetricResult:
        """The pseudo-mode mirror of the production metric route (Step 06 C2).

        Legacy pseudo inference need not write a deliverable. This method
        retains synthetic scoring, including when composed inference writes
        synthetic Health evidence. It synthesises the same 2-tuple
        :meth:`score_vector` has always produced
        and returns it under the run's REAL metric identity/direction — the
        handle's own declaration, not an invention — so the record payload
        the tuner writes has the production shape. Values are synthetic
        exactly as ``denoising_score`` / ``file_vector`` on every pseudo
        record already are.
        """
        file_vector, final_scalar = self.score_vector(
            sample_set, anchor_map, s_max, denoised_filename_fn, **kwargs
        )
        return MetricResult(
            metric_id=metric.spec.id,
            direction=metric.spec.direction,
            scalar=final_scalar,
            per_sample=file_vector,
            references_used=(),
        )

    def score_vector(
        self,
        sample_set,
        anchor_map: dict,
        s_max: float,
        denoised_filename_fn,
        **kwargs,
    ) -> tuple:
        """Synthesise the anchor-normalised scoring 2-tuple. No h5 read.

        Production ``TidmadSandbox.score_vector`` delegates to
        ``execute_tools.scoring_utils.score_vector``, which opens the
        ``abra_validation_denoised_*.h5`` artefacts produced by inference.
        Legacy pseudo inference does not write those artefacts. Composed
        inference can write synthetic Health evidence, but scoring remains
        synthetic through this override. It mirrors the synthesis contract of ``execute_scoring`` — same
        ``denoising_score`` ∈ [-3.0, -2.0] band, length-9 ``file_vector``
        — and returns them in the 2-tuple order the tuner unpacks at
        ``ml_hyperparameter_tune_agent.py`` (``score_vector`` call site).

        Args mirror the production signature for swap-in compatibility;
        ``**kwargs`` remains for backward compatibility with any callers
        still passing removed kwargs like ``reference_file_vector`` (they
        are silently swallowed). No anchor lookup, no parallel workers,
        no disk I/O.

        Health-check separation (commit-5a): the fixed
        ``(is_degenerate=False, failure_reason=None)`` pair that this
        stub previously appended was removed together with
        ``score_vector``'s health-check logic. See
        ``docs/design/pluggable_health_checks.md`` §14 Option A.

        Returns:
            (file_vector, final_scalar)

        Raises:
            ValueError: On an invalid or out-of-scope ``sample_set`` —
                DataScope parity with the production ``score_vector``
                exception contract.
        """
        validate_sample_set(sample_set, scope=self.data_scope)
        file_vector = [self._rng.uniform(-3.0, -2.0) for _ in range(9)]
        final_scalar = self._rng.uniform(-3.0, -2.0)
        return file_vector, final_scalar

    def save_record(self, record: dict[str, Any]) -> None:
        """Stamp ``_pseudo_origin`` audit marker, persist via parent, mirror in-memory.

        ``ExperimentRecord`` (Pydantic v2 default) silently ignores extra
        keys during validation, so the upstream
        ``ExperimentRecord.model_validate(record)`` call in
        ``ml_hyperparameter_tune_agent`` accepts the marker. The raw dict
        (with the marker preserved) is what gets json-dumped on disk by
        ``LocalRecorder.save_record``, so operators can grep the records
        directory for synthetic results.
        """
        record["_pseudo_origin"] = "stub_sandbox"
        super().save_record(record)
        self.saved_records.append(record)
