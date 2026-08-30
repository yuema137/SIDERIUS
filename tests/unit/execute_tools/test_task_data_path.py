"""TaskDataPath contract, registry and fail-closed binding (D14-1 C1).

Child design FROZEN rev 2 (`pr_d14_1_task_data_path_seam.md`). The three
deterministic truth-table tests its §4.2 REQUIRES are here, plus the
transport-authority test §4.1 requires, plus the synthetic implementation
whose supervision-target representation is deliberately different from its
model-output representation (parent Amendment 1's strengthening — a
regression-shaped `target == output-shape` assumption must fail HERE first,
before any real task meets the seam).

The synthetic task is three independent axes away from TIDMAD by design:
in-memory (no HDF5, no files), scope = a list of string ids (not
file→segments), scalar int target vs vector float model output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch
from torch.utils.data import Dataset

import execute_tools.task_data_path as tdp
from execute_tools.task_data_path import (
    TASK_DATA_PATH_ARGV_FLAG,
    TASK_DATA_PATH_IDENTITY_FLAG,
    TIDMAD_COMPATIBILITY_ID,
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    TaskBindingContext,
    TaskDataPathRegistrationError,
    TaskDataPathResolutionError,
    bind_task_data_path,
    content_identity,
    register_task_data_path,
    resolve_bound_task_data_path,
    resolve_task_data_path,
    resolve_transported_task_data_path,
    transport_argv,
)


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """Each test sees an empty registry; nothing leaks between tests.

    BOTH structures, since C1: the content-identity map is written and cleared
    in lockstep with the registry, so isolating only one would leave a stale
    identity behind an absent id.
    """
    monkeypatch.setattr(tdp, "_REGISTRY", {})
    monkeypatch.setattr(tdp, "_CONTENT", {})


# ---------------------------------------------------------------------------
# The synthetic non-TIDMAD implementation (child §3; parent Amendment 1)
# ---------------------------------------------------------------------------


class _SyntheticDataset(Dataset):
    """In-memory samples over a string-id scope.

    model_input : float32 vector [4]      (what the model consumes)
    target      : int scalar              (what the objective consumes)

    The model OUTPUT for this task would be a float vector [2] — so the
    target shares neither shape, rank, nor dtype with the output. That
    asymmetry is the point (Amendment 1).
    """

    def __init__(self, ids: list[str], seed: int):
        gen = torch.Generator().manual_seed(seed)
        self._inputs = torch.rand((len(ids), 4), generator=gen, dtype=torch.float32)
        self._targets = torch.arange(len(ids)) % 2  # scalar int per sample
        self.ids = list(ids)

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return self._inputs[idx], int(self._targets[idx])


class SyntheticTaskDataPath:
    """A complete, deliberately non-TIDMAD implementation of the seam."""

    task_data_path_id = "synthetic_vector_pairs"

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset:
        assert isinstance(scope, list), "synthetic scope is a plain list of string ids"
        return _SyntheticDataset(scope, seed=params.epoch_seed or 0)

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset:
        assert isinstance(scope, list)
        # Exact materialization in THIS task's vocabulary: every id yields
        # exactly one sample; a missing id would be a hard error here.
        return _SyntheticDataset(scope, seed=0)

    def write_deliverable(self, outputs, request: DeliverableWriteRequest) -> None:
        path = Path(request.output_dir) / f"synthetic_{request.run_name}_{request.exp_id}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for sample_id, vector in outputs:
                fh.write(json.dumps({"id": sample_id, "output": list(map(float, vector))}) + "\n")

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        path = (
            Path(request.deliverable_dir) / f"synthetic_{request.run_name}_{request.exp_id}.jsonl"
        )
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _tidmad_stand_in():
    """A registry stand-in under the compatibility id, for C1-level tests.

    The REAL TIDMAD implementation arrives at C2b; the truth table's
    regime-A row is testable now because resolution is lookup-only.
    """
    impl = SyntheticTaskDataPath()
    impl_cls = type("TidmadStandIn", (SyntheticTaskDataPath,), {})
    impl = impl_cls()
    impl_cls.task_data_path_id = TIDMAD_COMPATIBILITY_ID
    return impl


# ---------------------------------------------------------------------------
# The frozen truth table (child §4.2) — all five rows
# ---------------------------------------------------------------------------


class TestTheResolverTruthTable:
    def test_legacy_regime_a_absent_binding_resolves_to_tidmad_compat(self):
        """Row 1, REQUIRED test 1: `None` context IS the legacy path."""
        register_task_data_path(_tidmad_stand_in())
        resolved = resolve_task_data_path(None)
        assert resolved.task_data_path_id == TIDMAD_COMPATIBILITY_ID

    def test_explicit_legacy_bootstrap_preserves_the_uncomposed_path(self):
        """Removing import-time registration must not remove regime A."""
        from execute_tools.task_data_path import bootstrap_legacy_tidmad_data_path

        resolved = bootstrap_legacy_tidmad_data_path()
        assert resolved.task_data_path_id == TIDMAD_COMPATIBILITY_ID

    def test_explicit_binding_with_absent_id_fails_closed(self):
        """Row 2, REQUIRED test 2 — the load-bearing genericity row.

        A future Pets run necessarily constructs a binding context; if its
        binding step were missed, THIS is what fires — never a silent train
        on TIDMAD's path."""
        register_task_data_path(_tidmad_stand_in())  # present, must NOT be used
        with pytest.raises(TaskDataPathResolutionError) as err:
            resolve_task_data_path(TaskBindingContext(task_data_path_id=None))
        assert "never fall back" in str(err.value)

    def test_known_id_resolves_to_that_implementation(self):
        """Row 3."""
        register_task_data_path(SyntheticTaskDataPath())
        resolved = resolve_task_data_path(
            TaskBindingContext(task_data_path_id="synthetic_vector_pairs")
        )
        assert resolved.task_data_path_id == "synthetic_vector_pairs"

    def test_unknown_id_fails_closed_naming_id_and_registry(self):
        """Row 4, REQUIRED test 3."""
        register_task_data_path(SyntheticTaskDataPath())
        register_task_data_path(_tidmad_stand_in())  # present, must NOT be used
        with pytest.raises(TaskDataPathResolutionError) as err:
            resolve_task_data_path(TaskBindingContext(task_data_path_id="petz_typo"))
        msg = str(err.value)
        assert "petz_typo" in msg, "the diagnostic must name the offending id"
        assert "synthetic_vector_pairs" in msg, "and the registered set"

    def test_regime_a_without_a_registered_compat_impl_fails_loudly(self):
        """Row 1's own fail-closed edge: absence of the compatibility
        implementation is an error, never a silent no-op."""
        with pytest.raises(TaskDataPathResolutionError, match=TIDMAD_COMPATIBILITY_ID):
            resolve_task_data_path(None)

    def test_malformed_implementation_refused_at_registration(self):
        """Row 5: before any execution."""

        class MissingMethods:
            task_data_path_id = "broken"

            def training_dataset(self, scope, params):  # only one of four
                raise NotImplementedError

        with pytest.raises(TaskDataPathRegistrationError) as err:
            register_task_data_path(MissingMethods())
        assert "write_deliverable" in str(err.value)

    def test_duplicate_registration_follows_the_two_phase_rule(self):
        """UPGRADED at Step 12 / PR-12bc C1.

        This asserted that ANY second registration of an id refuses. That
        compared the ID ALONE, which made a re-execution of the IDENTICAL
        module indistinguishable from a genuine collision — and that is
        CASE A: a module evicted from ``sys.modules`` re-runs its
        registration and is punished for doing exactly what it did the first
        time.

        The frozen §8 rule is two-phase, and BOTH halves are asserted here so
        neither can quietly disappear:

            same id + SAME content       -> idempotent
            same id + DIFFERENT content  -> refused, by name
        """
        register_task_data_path(SyntheticTaskDataPath())
        # Same class, same source file: the SAME implementation. Idempotent.
        register_task_data_path(SyntheticTaskDataPath())

        class _Different(SyntheticTaskDataPath):
            """A genuinely different implementation claiming the same id."""

        with pytest.raises(TaskDataPathRegistrationError, match="DIFFERENT content"):
            register_task_data_path(_Different())

    def test_blank_id_refused(self):
        class BlankId(SyntheticTaskDataPath):
            task_data_path_id = ""

        with pytest.raises(TaskDataPathRegistrationError, match="non-empty"):
            register_task_data_path(BlankId())


# ---------------------------------------------------------------------------
# One configuration authority (child §4.1)
# ---------------------------------------------------------------------------


class TestTransportCarriesOnlyTheResolvedBinding:
    def test_transport_argv_derives_from_the_implementation(self):
        """The signature IS the enforcement: `transport_argv` takes the
        resolved implementation, not a free string, so neither the transported
        id NOR the identity pinned beside it (PR-12bc C2) can be anything but
        the binding's own."""
        impl = SyntheticTaskDataPath()
        assert transport_argv(impl) == [
            TASK_DATA_PATH_ARGV_FLAG,
            "synthetic_vector_pairs",
            TASK_DATA_PATH_IDENTITY_FLAG,
            content_identity(impl),
        ]

    def test_round_trip_transported_id_resolves_to_the_same_registration(self):
        register_task_data_path(SyntheticTaskDataPath())
        impl = resolve_task_data_path(
            TaskBindingContext(task_data_path_id="synthetic_vector_pairs")
        )
        _flag, value, _identity_flag, identity = transport_argv(impl)
        assert resolve_transported_task_data_path(value, identity) is impl

    def test_a_transported_unknown_id_fails_closed_in_the_child(self):
        """The child-process side is an EXPLICIT binding — the parent resolved
        it — so corruption in transit fails, never falls back."""
        register_task_data_path(_tidmad_stand_in())
        with pytest.raises(TaskDataPathResolutionError):
            resolve_transported_task_data_path("garbled")


class TestRunScopedBinding:
    def test_bound_implementation_wins_and_reset_restores_regime_a(self):
        register_task_data_path(_tidmad_stand_in())
        synthetic = SyntheticTaskDataPath()
        with bind_task_data_path(synthetic):
            assert resolve_bound_task_data_path() is synthetic
        # After the scope closes, the legacy path is back.
        assert resolve_bound_task_data_path().task_data_path_id == TIDMAD_COMPATIBILITY_ID


# ---------------------------------------------------------------------------
# The synthetic implementation itself (parent Amendment 1's strengthening)
# ---------------------------------------------------------------------------


class TestTheSyntheticImplementation:
    def test_target_representation_differs_from_output_representation(self):
        """THE asymmetry requirement. The model output for this task is a
        float vector; the supervision target is a scalar int. Shape, rank
        and dtype all differ — a seam that assumes target == output-shape
        breaks here before any real task exists."""
        ds = SyntheticTaskDataPath().training_dataset(
            ["a", "b", "c"], EpochSamplingParams(data_dir="/unused", epoch_seed=7)
        )
        model_input, target = ds[0]
        assert model_input.shape == (4,) and model_input.dtype == torch.float32
        assert isinstance(target, int), "the target is a scalar, not a tensor"
        simulated_model_output = torch.zeros(2, dtype=torch.float32)
        assert simulated_model_output.shape != model_input.shape
        assert not isinstance(target, torch.Tensor)

    def test_the_full_surface_round_trips(self, tmp_path):
        """All four methods, in-process: dataset → outputs → deliverable →
        evaluation payload. Structural genericity at C1 scale; the e2e
        through `run_experiment_streaming` is C5's."""
        impl = SyntheticTaskDataPath()
        scope = ["x", "y"]
        train = impl.training_dataset(scope, EpochSamplingParams(data_dir="/unused", epoch_seed=1))
        val = impl.validation_dataset(scope, EvalMaterializationParams(data_dir="/unused"))
        assert len(train) == len(val) == 2

        outputs = [(sid, [0.25, 0.75]) for sid in scope]
        impl.write_deliverable(
            outputs,
            DeliverableWriteRequest(
                output_dir=str(tmp_path), exp_id="e1", run_name="r1", model_type="synth_mlp"
            ),
        )
        payload = impl.read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path), exp_id="e1", run_name="r1", model_type="synth_mlp"
            )
        )
        assert payload == [
            {"id": "x", "output": [0.25, 0.75]},
            {"id": "y", "output": [0.25, 0.75]},
        ]

    def test_epoch_seed_drives_deterministic_resampling(self):
        impl = SyntheticTaskDataPath()
        p = EpochSamplingParams(data_dir="/unused", epoch_seed=42)
        a = impl.training_dataset(["a", "b"], p)
        b = impl.training_dataset(["a", "b"], p)
        assert torch.equal(a[0][0], b[0][0])
        c = impl.training_dataset(
            ["a", "b"], EpochSamplingParams(data_dir="/unused", epoch_seed=43)
        )
        assert not torch.equal(a[0][0], c[0][0])
