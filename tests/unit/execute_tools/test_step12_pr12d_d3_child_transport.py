"""Step 12 / PR-12d — D3 (seam C): child scope transport + generic iteration.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §D.C / §M `D3`.

Three blockers, one seam:

* **B6** — ``_task_scope_argv`` had exactly ONE call site, inside
  ``execute_training``. The inference child received no scope at all, so it
  could not know what to iterate.
* **B7** — ``inference_single.py::main`` DEFINED the framework's inference
  contract as TIDMAD's: a SampleSet loop, ``validation_file_name``, HDF5
  channel reads, PSD slicing and a 3-tuple deliverable write no contrast pack
  can consume.
* **B9** — the training preflight's TIDMAD assumptions, and
  ``validation_requested_rows``, which ``run_experiment_streaming`` REQUIRES
  for an explicit eval scope and which **nothing in production emitted**.

What each class owns
--------------------

``TestTransportReachesTheInferenceChild``
    B6: the same emitter, at a second spawn site, under the same
    emitted-only-when-bound rule.

``TestGenericIterationContract``
    B7: the extracted unit, driven over REAL contrast scopes, plus the
    ordering properties that make positional pairing safe.

``TestValidationRowsDeclaration``
    B9: the caller's declaration now crosses, and it comes from the PARENT so
    the child's ``requested == materialized`` check compares two sides of a
    boundary rather than the pass against itself.

``TestLegacyArgvUnchanged`` / ``TestTidmadUntouched``
    Backward compatibility: an un-composed argv is byte-identical and TIDMAD's
    iteration is still TIDMAD's.

``TestFailClosed``
    The four frozen falsifiers.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
from unittest.mock import MagicMock, patch

import pytest
import torch
import torch.nn as nn

from core.sandbox_executor import TidmadSandbox
from execute_tools.generic_inference import run_generic_inference
from execute_tools.scope_artifact import (
    load_transported_scope,
    scope_digest,
)
from execute_tools.scope_artifact import (
    task_scope_argv as _task_scope_argv,
)
from execute_tools.scope_artifact import (
    validation_rows_argv as _validation_rows_argv,
)
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EvaluationReadRequest,
    ScopeBuildRequest,
    bind_task_data_path,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

PETS_DATA = pathlib.Path("/home/klz/Data/OXFORD_IIIT_PET/images")
DAVIS_DATA = pathlib.Path("/home/klz/Data/DAVIS_2017")
PETS_MANIFEST = REPO_ROOT / "examples/oxford_iiit_pet/data/manifests/gate2_final.csv"
DAVIS_MANIFEST = REPO_ROOT / "examples/davis_future_prediction/data/manifests/gate2_final.csv"

BUILD = ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)

EXP_ID = "pr12d_d3"
RUN_NAME = "pr12d_d3_run"
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}


class PetsProbeNet(nn.Module):
    """``[B,3,144,144] -> [B,37]``. Deterministic, no parameters."""

    def forward(self, x):
        return x.flatten(1)[:, :37]


class DavisProbeNet(nn.Module):
    """``[B,3,8,128,224] -> [B,3,4,128,224]``. The first four context frames."""

    def forward(self, x):
        return x[:, :, :4]


def _truncated(scope, limit):
    """The same scope, bounded — real data, bounded cost."""
    return type(scope)(rows=tuple(scope.rows[:limit]))


@pytest.fixture
def pets(tmp_path):
    if not PETS_DATA.is_dir():
        pytest.skip(f"real Pets images not present at {PETS_DATA}")
    from execute_tools.pets_data_path import PetsTaskDataPath

    impl = PetsTaskDataPath(manifest_path=str(PETS_MANIFEST))
    return impl, _truncated(impl.build_eval_scope(BUILD), 8), str(PETS_DATA), PetsProbeNet()


@pytest.fixture
def davis(tmp_path):
    if not DAVIS_DATA.is_dir():
        pytest.skip(f"real DAVIS frames not present at {DAVIS_DATA}")
    from execute_tools.davis_data_path import DavisTaskDataPath

    impl = DavisTaskDataPath(clips_path=str(DAVIS_MANIFEST))
    return impl, _truncated(impl.build_eval_scope(BUILD), 2), str(DAVIS_DATA), DavisProbeNet()


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)


def _write_request(directory) -> DeliverableWriteRequest:
    return DeliverableWriteRequest(
        output_dir=str(directory), exp_id=EXP_ID, run_name=RUN_NAME, model_type="probe"
    )


# ======================================================================
# B6 — the transport reaches a second child
# ======================================================================


class TestTransportReachesTheInferenceChild:
    """One emitter, two spawn sites, one ABI."""

    def test_the_emitter_reaches_every_child_that_needs_a_scope(self):
        tree = ast.parse((REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8"))
        holders = sorted(
            fn.name
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            and any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "task_scope_argv"
                for node in ast.walk(fn)
            )
        )
        assert holders == ["execute_inference", "execute_scoring", "execute_training"], (
            "the scope transport must reach ALL THREE children through the SAME "
            "emitter — §D.C names the inference AND scoring spawn sites, and D4b "
            "added scoring because a task-owned metric's ground truth lives in "
            "the evaluation scope"
        )

    def test_the_inference_child_accepts_the_same_four_flags(self):
        source = (REPO_ROOT / "execute_tools" / "inference_single.py").read_text(encoding="utf-8")
        for flag in (
            "--task_scope_ref",
            "--task_scope_digest",
            "--task_eval_scope_ref",
            "--task_eval_scope_digest",
        ):
            assert f'"{flag}"' in source, f"{flag} is not an argv surface of the inference child"

    def test_the_child_reuses_the_ONE_reader(self):
        """No duplicated child-side verification (§E.2).

        The reader moved beside its writer when the second child needed it; a
        copy in either child would be the duplication the structural rule
        forbids.
        """
        for child in (
            "inference_single.py",
            "train_engine_sandbox.py",
            "denoising_score_single.py",
        ):
            source = (REPO_ROOT / "execute_tools" / child).read_text(encoding="utf-8")
            assert "from execute_tools.scope_artifact import load_transported_scope" in source
            assert "def load_transported_scope" not in source, f"{child} defines its own reader"
        owner = (REPO_ROOT / "execute_tools" / "scope_artifact.py").read_text(encoding="utf-8")
        assert owner.count("def load_transported_scope") == 1

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_an_uncomposed_inference_argv_gains_nothing(self, mock_run, sandbox):
        self._prepare_inference(sandbox)
        result = MagicMock()
        result.returncode, result.stdout, result.stderr = 0, "done\n", ""
        mock_run.return_value = (result, None)
        sandbox.execute_inference(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG, sample_set={0: [1]}
        )
        cmd = mock_run.call_args[0][0]
        assert [t for t in cmd if t.startswith("--task_scope") or t.startswith("--task_eval")] == []

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_a_composed_inference_argv_carries_the_scope(self, mock_run, sandbox, pets):
        impl, scope, _data_dir, _model = pets
        self._prepare_inference(sandbox)
        result = MagicMock()
        result.returncode, result.stdout, result.stderr = 0, "done\n", ""
        mock_run.return_value = (result, None)
        scopes = type("S", (), {"training": scope, "evaluation": scope})()
        with bind_task_data_path(impl):
            sandbox.execute_inference(
                EXP_ID,
                RUN_NAME,
                "fcnet",
                MODEL_CFG,
                LOSS_CFG,
                sample_set={0: [1]},
                task_scopes=scopes,
            )
        cmd = mock_run.call_args[0][0]
        assert "--task_eval_scope_ref" in cmd
        assert "--task_eval_scope_digest" in cmd
        ref = cmd[cmd.index("--task_eval_scope_ref") + 1]
        digest = cmd[cmd.index("--task_eval_scope_digest") + 1]
        assert scope_digest(pathlib.Path(ref).read_text(encoding="utf-8")) == digest

    def test_the_skill_wrapper_forwards_the_scopes(self):
        source = (REPO_ROOT / "agent" / "skills" / "inference_skill" / "wrapper.py").read_text(
            encoding="utf-8"
        )
        assert 'task_scopes=kwargs.get("task_scopes")' in source, (
            "the tuner already holds the scopes for the training spawn; the "
            "inference spawn must FORWARD them, never re-acquire them"
        )

    @staticmethod
    def _prepare_inference(sandbox):
        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in (f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"):
            (pathlib.Path(cfg_dir) / name).write_text("{}", encoding="utf-8")
        open(os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth"), "w").close()


# ======================================================================
# B7 — the generic iteration contract
# ======================================================================


class TestGenericIterationContract:
    """Driven over REAL contrast scopes; bounded to a handful of samples."""

    def test_pets_iterates_and_writes_its_own_deliverable(self, pets, tmp_path):
        impl, scope, data_dir, model = pets
        outcome = run_generic_inference(
            data_path=impl,
            task_scope=scope,
            model=model,
            device=torch.device("cpu"),
            data_dir=data_dir,
            batch_size=4,
            write_request=_write_request(tmp_path),
        )
        assert outcome.samples == len(scope.rows) == 8
        assert outcome.batches == 2
        assert (tmp_path / outcome.deliverable_name).is_file()
        payload = impl.read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path),
                exp_id=EXP_ID,
                run_name=RUN_NAME,
                model_type="probe",
            )
        )
        assert set(payload) == {row.image_id for row in scope.rows}
        assert all(isinstance(v, int) for v in payload.values())

    def test_davis_iterates_and_writes_its_own_deliverable(self, davis, tmp_path):
        impl, scope, data_dir, model = davis
        outcome = run_generic_inference(
            data_path=impl,
            task_scope=scope,
            model=model,
            device=torch.device("cpu"),
            data_dir=data_dir,
            batch_size=2,
            write_request=_write_request(tmp_path),
        )
        assert outcome.samples == len(scope.rows) == 2
        assert (tmp_path / outcome.deliverable_name).is_file()
        payload = impl.read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path),
                exp_id=EXP_ID,
                run_name=RUN_NAME,
                model_type="probe",
            )
        )
        assert len(payload) == 2
        for array in payload.values():
            assert array.shape[1] == 4, "the 4 predicted future frames"

    def test_the_outputs_are_paired_POSITIONALLY_with_the_scope(self, pets, tmp_path):
        """The property that makes ``shuffle=False`` load-bearing.

        A deterministic model whose output depends on WHICH image it saw lets
        a mis-pairing be observed rather than assumed: reverse the scope and
        every prediction must follow its own row.
        """
        impl, scope, data_dir, model = pets
        first = self._predictions(impl, scope, data_dir, model, tmp_path / "a")
        reversed_scope = type(scope)(rows=tuple(reversed(scope.rows)))
        second = self._predictions(impl, reversed_scope, data_dir, model, tmp_path / "b")
        assert first == second, "each image's prediction must follow the image, not its position"

    def test_the_unit_adds_no_new_capability_family(self):
        """§D.C's proof obligation, discharged executably.

        Only the FOUR FROZEN ``TaskDataPath`` methods may be called on the
        implementation. A fifth would be the new capability family §F stops
        for.
        """
        tree = ast.parse(
            (REPO_ROOT / "execute_tools" / "generic_inference.py").read_text(encoding="utf-8")
        )
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "data_path"
        }
        assert called <= {
            "training_dataset",
            "validation_dataset",
            "write_deliverable",
            "read_evaluation_payload",
        }, f"the generic unit reaches for a non-protocol method: {sorted(called)}"
        assert called == {"validation_dataset", "write_deliverable"}

    def test_the_unit_names_no_task(self):
        lowered = (
            (REPO_ROOT / "execute_tools" / "generic_inference.py")
            .read_text(encoding="utf-8")
            .lower()
        )
        for task in ("pets", "oxford", "davis", "image_id", "clip"):
            assert f'"{task}"' not in lowered, f"the generic unit names {task!r} as a value"

    @staticmethod
    def _predictions(impl, scope, data_dir, model, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        run_generic_inference(
            data_path=impl,
            task_scope=scope,
            model=model,
            device=torch.device("cpu"),
            data_dir=data_dir,
            batch_size=3,
            write_request=_write_request(out_dir),
        )
        return impl.read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(out_dir),
                exp_id=EXP_ID,
                run_name=RUN_NAME,
                model_type="probe",
            )
        )


# ======================================================================
# B9 — the caller's declaration crosses
# ======================================================================


class TestValidationRowsDeclaration:
    """The count comes from the PARENT, and it is real."""

    def test_the_child_accepts_the_declaration(self):
        source = (REPO_ROOT / "execute_tools" / "train_engine_sandbox.py").read_text(
            encoding="utf-8"
        )
        assert '"--validation_requested_rows"' in source
        assert "validation_requested_rows=args.validation_requested_rows" in source

    def test_an_uncomposed_run_declares_nothing(self):
        assert _validation_rows_argv(None, "/nowhere") == []
        assert _validation_rows_argv(type("S", (), {"evaluation": None})(), "/nowhere") == []

    def test_the_declaration_is_the_scopes_real_row_count(self, pets):
        impl, scope, data_dir, _model = pets
        scopes = type("S", (), {"training": scope, "evaluation": scope})()
        with bind_task_data_path(impl):
            argv = _validation_rows_argv(scopes, data_dir)
        assert argv == ["--validation_requested_rows", str(len(scope.rows))]

    def test_the_declaration_comes_from_the_PARENT_not_the_pass(self):
        """Why the emitter lives in the spawner.

        ``TrainingHistory`` asserts ``requested == materialized`` and the
        materialized value comes from the validation pass itself. A
        declaration the child derived would compare the pass to itself and
        pass for any number.
        """
        source = (REPO_ROOT / "execute_tools" / "scope_artifact.py").read_text(encoding="utf-8")
        assert "def validation_rows_argv" in source
        child = (REPO_ROOT / "execute_tools" / "train_engine_sandbox.py").read_text(
            encoding="utf-8"
        )
        assert "def validation_rows_argv" not in child

    def test_the_preflight_is_unreachable_without_a_sample_set(self):
        """B9's other half: the TIDMAD preflight is already guarded.

        ``_preflight_validation_scope`` opens TIDMAD HDF5, and a composed
        contrast run must never reach it. It is called only inside
        ``if eval_sample_set is not None``, which is the regime-A leg — so the
        guard is structural rather than added, and this asserts it rather
        than assuming it.
        """
        tree = ast.parse(
            (REPO_ROOT / "execute_tools" / "train_engine_sandbox.py").read_text(encoding="utf-8")
        )
        streaming = next(
            fn
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef) and fn.name == "run_experiment_streaming"
        )

        def _preflight_calls(node) -> list[ast.Call]:
            return [
                call
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "_preflight_validation_scope"
            ]

        every = _preflight_calls(streaming)
        assert every, "the preflight call was not found"
        # The guard that must contain them ALL. Inner guards (the 07c
        # validation ceiling) also enclose one, so the assertion is
        # containment by the eval-SampleSet guard, not "every enclosing test
        # mentions it".
        eval_guards = [
            node
            for node in ast.walk(streaming)
            if isinstance(node, ast.If) and ast.unparse(node.test) == "eval_sample_set is not None"
        ]
        assert len(eval_guards) == 1, "exactly one regime-A eval guard expected"
        assert len(_preflight_calls(eval_guards[0])) == len(every), (
            "a preflight call escaped the regime-A guard; a composed contrast "
            "run would open TIDMAD HDF5 it has no business opening"
        )


# ======================================================================
# Backward compatibility
# ======================================================================


class TestLegacyArgvUnchanged:
    """An un-composed command line is byte-identical."""

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_training(self, mock_run, sandbox):
        def _ok(*_a, **_k):
            os.makedirs(sandbox.dirs["models"], exist_ok=True)
            open(os.path.join(sandbox.dirs["models"], f"_OK_{EXP_ID}"), "wb").close()
            result = MagicMock()
            result.returncode, result.stdout, result.stderr = 0, "done\n", ""
            return result, None

        mock_run.side_effect = _ok
        sandbox.execute_training(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG, sample_set={0: [1, 2]}
        )
        cmd = mock_run.call_args[0][0]
        assert "--validation_requested_rows" not in cmd
        assert "--task_scope_ref" not in cmd

    def test_the_emitter_is_empty_without_scopes(self, tmp_path):
        assert _task_scope_argv(str(tmp_path), EXP_ID, None) == []
        assert _task_scope_argv(str(tmp_path), EXP_ID, type("S", (), {"training": None})()) == []


class TestTidmadUntouched:
    """TIDMAD's iteration survives as the TIDMAD adapter's implementation."""

    def test_the_sample_set_loop_is_still_there(self):
        source = (REPO_ROOT / "execute_tools" / "inference_single.py").read_text(encoding="utf-8")
        assert "for file_index_str, psd_segment_indices in sorted(sample_set.items()):" in source
        assert "profile_dataset.validation_file_name(file_index)" in source
        assert "[(file_index, denoised, injected)]" in source

    def test_the_generic_route_cannot_express_it(self):
        """The separation is real, not a comment.

        Nothing in the generic unit can produce a SampleSet loop, an HDF5
        read or a PSD slice — asserted on its source, because the point of
        the extraction is that TIDMAD's physics is not reachable from it.
        """
        source = (REPO_ROOT / "execute_tools" / "generic_inference.py").read_text(encoding="utf-8")
        body = source.split('"""', 2)[2]  # exclude the module docstring's example
        for tidmad_ism in ("h5py", "psd_segment", "sample_set", "validation_file_name"):
            assert tidmad_ism not in body, f"the generic unit reaches for {tidmad_ism}"


# ======================================================================
# Falsifiers
# ======================================================================


class TestFailClosed:
    """The four frozen falsifiers."""

    def test_falsifier_1_a_tampered_artifact_is_refused_BEFORE_deserialization(
        self, pets, tmp_path
    ):
        """The deserializer must never be reached (12bc's spy pattern)."""
        from execute_tools.scope_artifact import ScopeArtifactError, write_scope_artifact

        impl, scope, _data_dir, _model = pets
        path = str(tmp_path / "scope.json")
        digest = write_scope_artifact(path, impl.serialize_scope(scope))
        pathlib.Path(path).write_text("tampered", encoding="utf-8")
        with (
            bind_task_data_path(impl),
            patch.object(
                type(impl), "deserialize_scope", side_effect=AssertionError("reached")
            ) as spy,
            pytest.raises(ScopeArtifactError),
        ):
            load_transported_scope(path, digest, leg="evaluation")
        assert spy.call_count == 0, "the parser authenticated the bytes instead of the digest"

    def test_falsifier_2_a_half_supplied_pair_is_refused_by_name(self):
        with pytest.raises(ValueError, match="half-supplied"):
            load_transported_scope("/some/path", None, leg="evaluation")
        with pytest.raises(ValueError, match="half-supplied"):
            load_transported_scope(None, "deadbeef", leg="evaluation")

    def test_falsifier_3_a_foreign_scope_is_still_refused(self, pets):
        """The pairing rule must not soften as transport widens."""
        from execute_tools.tidmad_data_path import TidmadScope

        impl, _scope, _data_dir, _model = pets
        with pytest.raises(TypeError):
            impl.serialize_scope(TidmadScope(sample_set={0: [0]}, seg_size=10, profile=None))

    def test_falsifier_4_main_never_hosts_the_generic_branch_family(self):
        """§E H1's budget assertion, at its own site."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "c0", REPO_ROOT / "tests/unit/guardrails/test_step12_pr12a_c0_defect_baselines.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = module._qualified_functions(REPO_ROOT / "execute_tools" / "inference_single.py")[
            "main"
        ]
        assert module.measure(fn)[1] <= 67, (
            "inference_single.py::main is hard-capped at its D0 branch count; "
            "the generic contract belongs in the extracted unit"
        )

    def test_an_unpaired_write_without_a_scope_is_refused_by_name(self, pets, tmp_path):
        """The pairing helper fails closed rather than mis-attributing."""
        from execute_tools.pets_data_path import pair_with_scope

        _impl, _scope, _data_dir, _model = pets
        request = _write_request(tmp_path).model_copy(update={"task_scope": object()})
        with pytest.raises(ValueError, match="declares no rows"):
            pair_with_scope([1, 2], request)

    def test_a_length_mismatch_between_scope_and_outputs_is_refused(self, pets, tmp_path):
        from execute_tools.pets_data_path import pair_with_scope

        _impl, scope, _data_dir, _model = pets
        request = _write_request(tmp_path).model_copy(update={"task_scope": scope})
        with pytest.raises(ValueError):
            pair_with_scope([1, 2], request)


def test_the_write_request_carries_the_scope_only_when_the_framework_pairs(tmp_path):
    """An OPTIONAL field: every pre-12d construction is unchanged."""
    request = _write_request(tmp_path)
    assert request.task_scope is None
    assert json.loads(request.model_dump_json())["task_scope"] is None
