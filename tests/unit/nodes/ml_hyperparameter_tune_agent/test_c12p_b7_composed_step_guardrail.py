"""C12-P / B7 — ``--max_steps_per_attempt`` is inert for a composed run.

FALSIFIERS. Every test here is expected to FAIL on the code as it stands;
each names the single defect it alone catches and how it goes red again if
that defect returns.

The mechanism, verified on this checkout rather than taken from the report::

    planning.py (PR-12d seam B)   a composed task that declares no physical
                                  partition geometry builds NO legacy
                                  SampleSet -> ``train_sample_set is None``
    runtime.py:906-907            ``if train_sample_set is None: return None``
                                  -- a SILENT early return, zero output
    runtime.py:857-860            ``max_steps_per_attempt is not None and
                                  n_steps is not None and ...`` short-circuits
                                  on the ``None``

Two things the original report got wrong and that these tests must not
re-assert:

* there is **no** ``[guardrails] step resolution failed (non-fatal)`` line for
  this cause. That print sits in the ``except`` at ``runtime.py:941`` and is
  unreachable from the ``None`` early return, so an operator watching the log
  sees a bound that simply never speaks;
* ``min_formal_batch_size`` (``runtime.py:866``) is **not** affected -- it
  reads ``batch_size``, which is always present. A fix that repairs both has
  changed something it did not need to.

Why the falsifiers exercise ``_check_and_record_guardrail_skip`` directly and
not a whole composed round: on this checkout (master ``c991d6f6``) a composed
non-TIDMAD run dies EARLIER, inside ``prepare_attempt``'s ``tidmad_topology``
decode, so an end-to-end fixture here would fail for a reason that is not B7.
The boundary below is the one that emits the record, it is unchanged by
PR-12d, and feeding it the exact state PR-12d's planning seam produces
reproduces B7 and nothing else.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from agent.schemas.ordering import resolve_ordering
from execute_tools.task_data_path import bind_task_data_path
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import AttemptScopes
from tests.helpers.two_family_profile import make_two_family_profile

# The node package rebinds ``sys.modules[...]`` to its main module (see the
# package ``__init__``), so ``from nodes.ml_hyperparameter_tune_agent import
# runtime`` resolves against that module and fails. ``import_module`` on the
# full dotted path is how the private module is reached — the same route
# ``runtime`` itself uses for ``records``.
runtime = importlib.import_module("nodes.ml_hyperparameter_tune_agent.runtime")

#: The composed attempt's task-owned training scope. OPAQUE to the framework
#: by contract -- what matters is that it is TINY and it EXISTS, so a bound of
#: one optimizer step per attempt is unambiguously exceeded by any run of it.
TINY_TASK_SCOPE = {"partitions": {"0": list(range(8))}, "sample_count": 8}

#: The run's resolved physical data root. A VALUE the caller holds
#: (``bindings.time_data_dir``), never a path this test reads.
DATA_ROOT = "/c12p/b7/data-root"
PROFILE = make_two_family_profile(
    num_files=1,
    psd_segment_length=80_000,
    segments_per_file=1,
)


class _ScopeRows:
    """The rows a task's ``training_dataset`` materializes for a scope.

    Only ``__len__`` is exercised: the framework's whole question is *how
    many samples*, which is what ``len()`` on a ``Sized`` torch ``Dataset``
    answers — the same instrument ``scope_artifact.validation_rows_argv``
    already uses on the eval leg.
    """

    def __init__(self, rows: list[int]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(self, index: int) -> int:
        return self._rows[index]


class _TaskOwnedDataPath:
    """A task data path that OWNS the vocabulary of ``TINY_TASK_SCOPE``.

    The count it returns is READ OFF THE SCOPE, not a constant: this stands
    in for the implementation that built the scope, which is the only thing
    that can say how big it is. The framework never learns the shape.
    """

    task_data_path_id = "c12p-b7-task-owned"

    def training_dataset(self, scope, params):
        assert params.data_dir == DATA_ROOT, (
            f"the run's resolved data root must reach the implementation; got {params.data_dir!r}"
        )
        rows: list[int] = []
        for partition in scope["partitions"].values():
            rows.extend(partition)
        return _ScopeRows(rows)

    def validation_dataset(self, scope, params):  # pragma: no cover - never called
        raise AssertionError("the step guardrail must not touch the eval leg")

    def write_deliverable(self, outputs, request):  # pragma: no cover - never called
        raise AssertionError("the step guardrail must not write a deliverable")

    def read_evaluation_payload(self, request):  # pragma: no cover - never called
        raise AssertionError("the step guardrail must not read a deliverable")


def _composed_agent_input():
    """A composed run whose operator asked for at most ONE optimizer step.

    ``task_composition_ref`` is the discriminator the whole repository already
    uses for "this run is composed" (``ml_hyperparameter_tune_agent.py:687``,
    ``planning.py``'s ``acquire_attempt_scopes(composed=...)`` argument). It is
    deliberately the signal used here too: B7 must never be fixed by keying on
    a task name.
    """
    return SimpleNamespace(
        task_composition_ref="c12p://composed-task",
        max_steps_per_attempt=1,
        min_formal_batch_size=None,
        allow_extreme_steps=False,
        validation_max_train_samples=None,
        candidate_id=None,
        # arXiv U1 (reconciliation upgrade, 12d-fixture precedent): the
        # emission path stamps the run's experiment arm; a fixture predating
        # the field carries its unlabelled default — never suppress the
        # threading.
        experiment_arm=None,
    )


def _plan():
    return SimpleNamespace(
        is_trial=True,
        train_cfg={"batch_size": 1, "epochs": 1},
    )


def _trial_config():
    return SimpleNamespace(train_portion=1.0, mode="trial")


@pytest.fixture
def emitted(monkeypatch):
    """Capture every record the guardrail boundary persists.

    Stubbed on ``records``, the module that OWNS ``_emit_record`` and the one
    ``runtime`` calls through -- the node's public-boundary recipe.
    """
    captured: list[dict] = []

    def _spy(
        sandbox,
        record,
        *,
        status=None,
        candidate_id=None,
        experiment_arm=None,
        ordering=None,
        ordering_observation=None,
    ):
        captured.append(record)

    monkeypatch.setattr(runtime._records, "_emit_record", _spy)
    return captured


def _run_guardrail(agent_input, *, train_sample_set):
    """Drive the boundary with the exact state PR-12d's planning seam B builds.

    CORRECTED (C12-P / B7 implementation): this helper used to pass NO
    ``task_scopes`` and NO ``data_dir``, while the two tests below described
    "an attempt that carries a task-owned scope of 8 training samples". It
    therefore drove a state production cannot reach — ``planning.py:524-565``
    sets ``train_sample_set = None`` only when the profile declares no
    physical geometry, and ``acquire_attempt_scopes`` on the very next lines
    ALWAYS acquires scopes for a composed trial/formal round. "Composed, no
    sample set, no scope" is the ``single_file`` legacy mode, which is the
    case ``TestTheLegacyPathIsUntouched`` owns.

    Every assertion in both tests is unchanged; what changed is that the
    fixture now constructs the state its own docstrings name.
    """
    with bind_task_data_path(_TaskOwnedDataPath()):
        return runtime._check_and_record_guardrail_skip(
            sandbox=SimpleNamespace(),
            agent_input=agent_input,
            plan=_plan(),
            trial_config=_trial_config(),
            train_sample_set=train_sample_set,
            task_scopes=AttemptScopes(training=TINY_TASK_SCOPE, evaluation=TINY_TASK_SCOPE),
            data_dir=DATA_ROOT,
            model_config={"segmentation_size": 10_000},
            exp_id="c12p-b7",
            model_type="wavenet",
            file_index=0,
            record_params={},
            expert_advice_str="",
            hypothesis="",
            round_index=1,
            attempt_in_round=1,
            dataset_profile=PROFILE,
            ordering=resolve_ordering(resolved_scope=[0]),
        )


class TestAnOperatorBoundIsNeverSilentlyDisabled:
    def test_composed_attempt_without_a_legacy_sample_set_still_enforces_max_steps(self, emitted):
        """B7. The defect this alone catches: an operator hard bound that a
        COMPOSED run silently ignores.

        The attempt below carries a task-owned scope of 8 training samples at
        ``batch_size=1`` -- 8 optimizer steps against
        ``max_steps_per_attempt=1``. The guardrail must refuse it.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES: ``_resolve_guardrail_steps``
        returns ``None`` for the composed attempt again, ``_evaluate_step_guardrails``
        short-circuits, no record is emitted, and ``emitted`` is empty. That is
        exactly the assertion below, and it is the whole defect: not a wrong
        number, an absent decision.

        This is NOT covered by ``test_rt5_guardrails.py``: that file pins
        ``n_steps=None -> []`` as CORRECT, because on the legacy single-file
        path it is. What is missing everywhere is the case where ``None`` means
        "a composed task built the scope and nobody asked it how big".
        """
        agent_input = _composed_agent_input()
        assert agent_input.task_composition_ref is not None, "fixture must be composed"

        skipped = _run_guardrail(agent_input, train_sample_set=None)

        assert skipped is True, (
            "a composed attempt exceeding max_steps_per_attempt must be skipped; "
            "returning False means the operator's bound was silently inert"
        )
        assert len(emitted) == 1, (
            f"the guardrail must emit exactly one planner-visible record; got {len(emitted)}"
        )
        assert emitted[0]["status"] == "skipped_time_risk"
        assert emitted[0]["memory"]["verification_stage"] == "guardrail"

    def test_step_guardrails_are_never_evaluated_with_an_unresolved_count(
        self, emitted, monkeypatch
    ):
        """B7, the mechanism rather than the consequence.

        The defect this alone catches: the composed attempt REACHES
        ``_evaluate_step_guardrails`` carrying ``n_steps=None``, so the
        comparison at ``runtime.py:857-860`` is decided by the missing value
        and not by the workload. Asserting on the emitted record (the test
        above) proves the outcome; this one proves WHERE it was decided, so a
        future fix that merely suppresses the record cannot pass it.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES: ``seen`` records ``None``
        again.

        Deliberately NOT asserted: that ``n_steps == 8``. The framework cannot
        read an opaque task scope today, so the number is a property of the
        fix, not of the defect; pinning it here would pin one implementation.
        """
        seen: list[object] = []
        real = runtime._evaluate_step_guardrails

        def _spy(**kwargs):
            seen.append(kwargs["n_steps"])
            return real(**kwargs)

        monkeypatch.setattr(runtime, "_evaluate_step_guardrails", _spy)

        _run_guardrail(_composed_agent_input(), train_sample_set=None)

        assert seen, "the guardrail evaluation must actually be reached"
        assert seen[-1] is not None, (
            "a composed attempt reached the step guardrail with an UNRESOLVED "
            "step count; max_steps_per_attempt cannot decide anything against "
            "None, so the bound is inert (runtime.py:906-907 -> :857-860)"
        )


class TestTheGuardrailCanSeeTheAttemptsTaskOwnedScope:
    def test_the_boundary_accepts_the_attempts_acquired_scopes(self, emitted):
        """B7's missing SEAM, stated as a contract rather than a behaviour.

        ``prepare_attempt`` already builds ``AttemptScopes`` and already puts
        them on ``PreparedAttempt.task_scopes`` (12bc B5). The guardrail
        boundary is the one admission decision that never receives them, which
        is why it has nothing to price. Whatever shape the fix takes, the
        attempt's own scopes must reach this function.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES: ``TypeError: unexpected
        keyword argument 'task_scopes'`` -- the parameter was removed and the
        boundary went blind again.

        This test is a specification, and it says so: the production hunk is
        DEFERRED because ``runtime.py`` is inside PR-12d's active write set,
        so C12-P reconciles against landed 12d rather than editing under it.
        """
        scopes = AttemptScopes(training=TINY_TASK_SCOPE, evaluation=TINY_TASK_SCOPE)
        assert scopes.acquired is True

        runtime._check_and_record_guardrail_skip(
            sandbox=SimpleNamespace(),
            agent_input=_composed_agent_input(),
            plan=_plan(),
            trial_config=_trial_config(),
            train_sample_set=None,
            task_scopes=scopes,
            model_config={"segmentation_size": 10_000},
            exp_id="c12p-b7",
            model_type="wavenet",
            file_index=0,
            record_params={},
            expert_advice_str="",
            hypothesis="",
            round_index=1,
            attempt_in_round=1,
            dataset_profile=PROFILE,
            ordering=resolve_ordering(resolved_scope=[0]),
        )


class TestTheLegacyPathIsUntouched:
    def test_min_formal_batch_size_was_never_part_of_this_defect(self, emitted):
        """Guards the FIX, not the defect: ``min_formal_batch_size`` reads
        ``batch_size``, which is always present, so it fires for a composed
        formal attempt today and must still fire afterwards.

        HOW IT FAILS: a fix that routes the whole guardrail through the task
        scope, or that returns early when no step count is available, takes
        the batch floor down with it and ``emitted`` goes empty.

        This test is expected to PASS today. It is here so that the two red
        tests above cannot be made green by widening the blast radius.
        """
        agent_input = _composed_agent_input()
        agent_input.max_steps_per_attempt = None
        agent_input.min_formal_batch_size = 4

        plan = _plan()
        plan.is_trial = False

        skipped = runtime._check_and_record_guardrail_skip(
            sandbox=SimpleNamespace(),
            agent_input=agent_input,
            plan=plan,
            trial_config=_trial_config(),
            train_sample_set=None,
            model_config={"segmentation_size": 10_000},
            exp_id="c12p-b7",
            model_type="wavenet",
            file_index=0,
            record_params={},
            expert_advice_str="",
            hypothesis="",
            round_index=1,
            attempt_in_round=1,
            dataset_profile=PROFILE,
            ordering=resolve_ordering(resolved_scope=[0]),
        )

        assert skipped is True
        assert len(emitted) == 1
        assert "min_formal_batch_size" in emitted[0]["memory"]["conclusion"]
