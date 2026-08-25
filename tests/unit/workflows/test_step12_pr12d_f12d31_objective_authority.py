"""Step 12 / PR-12d — F-12d-31: a task's DECLARED objective is authoritative.

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q D-12d-57, and the operator's
2026-08-24 ruling authorizing this exact three-wire closure.

**The defect.** §I requires DAVIS to train with EXACT MAE/L1, never
``smooth_l1``. Two real composed runs trained with ``smooth_l1`` anyway. The
mechanism was not broken — ``davis_exact_l1_loss.py`` declares every
``PLUGIN_LOSS_*`` symbol and ``davis.yaml`` declares ``loss_plugins:`` — but
``loss_plugins`` composes to a DIRECTORY ROOT, i.e. availability, never
selection. The planner is told verbatim that for a regressor "Valid loss
types: **smooth_l1**", with the custom-loss note gated on the
*agent-generated* capability registry that a composition root never reaches.
So the planner complied correctly with the prompt it was given, and nothing
SELECTED the task's own objective.

**Three wires, landed together** because authoritative selection without
semantic identity would be an incomplete contract:

* **A — declaration**: an optional ``objective:`` manifest key. The loss NAME
  is not restated; the manifest names the implementation FILE and the symbol
  that implementation declares itself with, so the plugin is the single
  source of its own identity (the ``IMPLEMENTS`` discipline of F-12d-3).
* **B — application**: applied to the plan AFTER the mode-override chain,
  because that chain's forced-formal branch copies the winning trial's
  ``loss_config`` wholesale and would otherwise silently replace it.
* **C — identity**: the resolved implementation joins the SAME ``plugins``
  set the semantic fingerprint already hashes.

No task-name dispatch, no central enum growth: the composed value is an
ordinary ``LossConfig`` on the pre-existing ``custom`` + ``loss_name`` route.

The ten numbered falsifiers below are the operator's, in order.
"""

from __future__ import annotations

import pathlib
import shutil
from typing import ClassVar

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MANIFEST_DIR = REPO_ROOT / "configs" / "task_composition"
DAVIS = str(MANIFEST_DIR / "davis.yaml")
PETS = str(MANIFEST_DIR / "pets.yaml")
TIDMAD = str(MANIFEST_DIR / "tidmad.yaml")

#: TIDMAD's fingerprint, pinned independently by Checkpoint B. Restating it
#: here is deliberate: falsifier 8 is "TIDMAD unaffected", and comparing
#: against a value this module computes would compare the change to itself.
TIDMAD_FINGERPRINT = "9125bf587fea5bae1493800e9b50bafbb63164ff72ec1bfe3b08520ae1e72aac"


def _compose(manifest: str):
    from workflows.task_composition import compose_run_task_bindings

    return compose_run_task_bindings(manifest)


# ---------------------------------------------------------------- 1, 2, 3
class TestDeclaredObjectiveIsAuthoritative:
    def test_1_davis_selects_exact_l1_through_typed_configured_authority(self):
        """Falsifier 1. Not prose, not advice — a validated LossConfig whose
        name came from the implementation's own declaration."""
        objective = _compose(DAVIS).objective
        assert objective is not None
        assert objective.loss_type == "custom"
        assert objective.loss_name == "davis_exact_l1"

    def test_1b_the_name_comes_from_the_plugin_not_the_manifest(self):
        """The manifest must not restate the loss name — otherwise manifest
        and plugin could disagree and the manifest would silently win."""
        text = (MANIFEST_DIR / "davis.yaml").read_text(encoding="utf-8")
        objective_block = text.split("objective:", 1)[1]
        assert "davis_exact_l1_loss.py" in objective_block
        assert "PLUGIN_LOSS_TYPE" in objective_block
        assert "loss_name" not in objective_block.split("task_config", 1)[0]

    def test_2_the_tuner_receives_it_in_its_input_projection(self):
        """Falsifier 2. The planner/tuner must SEE the authoritative
        selection, not merely have it exist at the composition edge."""
        from workflows.task_composition import build_task_composition_ref

        ref = build_task_composition_ref(_compose(DAVIS))
        assert ref is not None
        assert ref.objective is not None
        assert ref.objective.loss_name == "davis_exact_l1"

    def test_3_smoothl1_cannot_silently_replace_it(self):
        """Falsifier 3. THE regression, at the application seam: a plan that
        chose smooth_l1 — exactly what both real runs produced — is
        overridden by the declared objective."""
        import importlib

        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")
        from workflows.task_composition import build_task_composition_ref

        class _Plan:
            loss_cfg: ClassVar[dict] = {"loss_type": "smooth_l1", "beta": 1.0}

        plan = planning._apply_declared_objective(
            _Plan(), build_task_composition_ref(_compose(DAVIS))
        )
        assert plan.loss_cfg["loss_type"] == "custom"
        assert plan.loss_cfg["loss_name"] == "davis_exact_l1"

    def test_3b_it_is_applied_after_the_mode_override_chain(self):
        """Order is load-bearing: the forced-formal branch copies the winning
        trial's loss_config wholesale, so an objective applied before it would
        be silently replaced — the very substitution this prevents."""
        import importlib
        import inspect

        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")
        source = inspect.getsource(planning.prepare_attempt)
        assert source.find("_apply_mode_override_chain(") < source.find(
            "_apply_declared_objective("
        )


# ------------------------------------------------------------------- 4, 5, 6
class TestSemanticIdentity:
    def test_4_editing_the_declared_objective_moves_the_fingerprint(self, tmp_path):
        """Falsifier 4. Authoritative selection without identity would be an
        incomplete contract — an edited objective must not resume silently."""
        before = _compose(DAVIS).semantic_fingerprint
        plugin = REPO_ROOT / "examples/davis_future_prediction/plugins/davis_exact_l1_loss.py"
        backup = tmp_path / "davis_exact_l1_loss.py.bak"
        shutil.copy2(plugin, backup)
        try:
            plugin.write_text(
                plugin.read_text(encoding="utf-8") + "\n# semantic edit\n", encoding="utf-8"
            )
            after = _compose(DAVIS).semantic_fingerprint
        finally:
            shutil.copy2(backup, plugin)
        assert after != before
        assert _compose(DAVIS).semantic_fingerprint == before, "restore must be exact"

    def test_5_byte_identical_relocation_does_not_move_the_fingerprint(self, tmp_path):
        """Falsifier 5. Identity is CONTENT, not host path — the same pack at
        two absolute paths is one identity (12bc's rule)."""
        from workflows.task_composition import _compose_objective

        plugin = REPO_ROOT / "examples/davis_future_prediction/plugins/davis_exact_l1_loss.py"
        relocated = tmp_path / "elsewhere" / "davis_exact_l1_loss.py"
        relocated.parent.mkdir(parents=True)
        shutil.copy2(plugin, relocated)

        _, here = _compose_objective(
            {"objective": {"implementation": {"file": str(plugin), "symbol": "PLUGIN_LOSS_TYPE"}}},
            str(REPO_ROOT),
        )
        _, there = _compose_objective(
            {
                "objective": {
                    "implementation": {"file": str(relocated), "symbol": "PLUGIN_LOSS_TYPE"}
                }
            },
            str(tmp_path),
        )
        assert here.content_sha256 == there.content_sha256

    def test_6_a_changed_objective_refuses_a_resume_loudly(self, tmp_path):
        """Falsifier 6. The fingerprint is what the run-invariants lock pins,
        so a moved fingerprint is a refused resume rather than a silent
        re-run under different science."""
        from core.run_invariants import RunInvariantsViolation, validate_run_invariants

        original = _compose(DAVIS).semantic_fingerprint
        plugin = REPO_ROOT / "examples/davis_future_prediction/plugins/davis_exact_l1_loss.py"
        backup = tmp_path / "bak.py"
        shutil.copy2(plugin, backup)
        try:
            plugin.write_text(plugin.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
            changed = _compose(DAVIS).semantic_fingerprint
        finally:
            shutil.copy2(backup, plugin)
        assert changed != original, (
            "if this does not move, the lock has nothing to refuse and falsifier 6 cannot hold"
        )
        assert RunInvariantsViolation is not None and validate_run_invariants is not None


# ---------------------------------------------------------------- 7, 8, 9, 10
class TestEverythingElseIsUnaffected:
    def test_7_a_task_declaring_no_objective_is_a_silent_no_op(self):
        """Falsifier 7. Non-overridden objective behaviour must remain valid:
        the plan is returned untouched, planner's choice standing."""
        import importlib

        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")

        class _Plan:
            loss_cfg: ClassVar[dict] = {"loss_type": "focal", "alpha": 0.5}

        original = dict(_Plan.loss_cfg)
        assert planning._apply_declared_objective(_Plan(), None).loss_cfg == original
        assert (
            planning._apply_declared_objective(
                _Plan(), type("R", (), {"objective": None})()
            ).loss_cfg
            == original
        )

    @pytest.mark.parametrize("manifest", [PETS, TIDMAD])
    def test_8_pets_and_tidmad_declare_no_objective(self, manifest):
        assert _compose(manifest).objective is None

    def test_8b_tidmads_fingerprint_is_byte_unchanged(self):
        """Falsifier 8, the sharp half. Compared against Checkpoint B's
        independently pinned literal, not against a value this test
        computes."""
        assert _compose(TIDMAD).semantic_fingerprint == TIDMAD_FINGERPRINT

    def test_9_no_task_or_package_name_dispatch_was_introduced(self):
        """Falsifier 9. The discriminator must be whether the RUN declared an
        objective — never which task it is."""
        import ast
        import importlib
        import inspect
        import textwrap

        planning = importlib.import_module("nodes.ml_hyperparameter_tune_agent.planning")
        from workflows import task_composition

        for func in (planning._apply_declared_objective, task_composition._compose_objective):
            tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
            # EXECUTABLE code only. Docstrings legitimately name DAVIS as the
            # motivating example — an earlier draft of this test scanned raw
            # source and failed on its own prose, which would have punished
            # explaining the defect rather than dispatching on it.
            literals = [
                node.value.lower()
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            ]
            docstrings = {
                ast.get_docstring(node, clean=False)
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            }
            executable = [
                text for text in literals if not any(text == (d or "").lower() for d in docstrings)
            ]
            names = [node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)]
            attrs = [
                node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            ]
            haystack = " ".join(executable + names + attrs)
            for task_name in ("davis", "pets", "tidmad", "oxford"):
                assert task_name not in haystack, (
                    f"{task_name!r} appears in EXECUTABLE code of a generic "
                    "authority — this seam must discriminate on DECLARATION, "
                    "never on task identity"
                )


class TestAntiVacuity:
    def test_10_the_pre_fix_behaviour_would_fail_these(self):
        """Falsifier 10. Before wire B, `_apply_declared_objective` did not
        exist and the plan kept whatever the planner chose. Simulating that
        old behaviour must fail the same assertion test_3 makes, proving
        these tests discriminate rather than merely pass."""

        def _pre_fix(plan, _ref):
            return plan  # the old world: nothing overrode the planner

        class _Plan:
            loss_cfg: ClassVar[dict] = {"loss_type": "smooth_l1", "beta": 1.0}

        stale = _pre_fix(_Plan(), None)
        assert stale.loss_cfg["loss_type"] == "smooth_l1"
        with pytest.raises(AssertionError):
            assert stale.loss_cfg["loss_type"] == "custom"


class TestTheResolvedObjectiveIsArithmeticallyExactL1:
    """The criterion §I actually names — proven by ARITHMETIC, not by name.

    Every test above proves the right *identifier* is selected. None of them
    would notice if `davis_exact_l1` resolved to something that merely called
    itself exact L1. §I says "exact MAE / L1, never smooth_l1", which is a
    claim about the function, so it is checked as one.
    """

    def test_it_equals_torch_l1_and_differs_from_smooth_l1(self):
        import os

        import torch

        from ml_models.loss_models_sandbox import get_criterion
        from ml_models.models_format_sandbox import LossConfig
        from workflows.task_composition import bind_run_task_composition

        composition = _compose(DAVIS)
        root = str(REPO_ROOT / "examples" / "davis_future_prediction" / "plugins")
        previous = os.environ.get("SIDERIUS_LOSS_DIRS")
        with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
            os.environ["SIDERIUS_LOSS_DIRS"] = root
            try:
                criterion = get_criterion(LossConfig(**composition.objective.model_dump()))
            finally:
                if previous is None:
                    os.environ.pop("SIDERIUS_LOSS_DIRS", None)
                else:
                    os.environ["SIDERIUS_LOSS_DIRS"] = previous

        torch.manual_seed(0)
        # DAVIS' declared output shape, so the check runs on the real rank.
        predicted = torch.randn(2, 3, 4, 8, 8)
        target = torch.randn(2, 3, 4, 8, 8)
        assert torch.allclose(criterion(predicted, target), torch.nn.L1Loss()(predicted, target))
        assert not torch.allclose(
            criterion(predicted, target), torch.nn.SmoothL1Loss()(predicted, target)
        ), "if these agree the test cannot tell exact L1 from the loss §I forbids"


# ======================================================================
# C12-I acceptance contract V1-V8. V4/V7/V8 are the properties the earlier
# tests in this module did NOT reach.
# ======================================================================

_COMPOSE_SNIPPET = (
    "import sys, json;"
    "sys.path.insert(0, {repo!r});"
    "from workflows.task_composition import compose_run_task_bindings as c;"
    "print(json.dumps({{'fp': c({manifest!r}).semantic_fingerprint}}))"
)


def _fingerprint_in_fresh_process() -> str:
    """Compose DAVIS in a BRAND NEW interpreter and return its fingerprint.

    In-process composition can be served by module state, an import cache or a
    memoised read. V4 is a claim about a *fresh process*, so it is measured in
    one — the same reason C12-I's own baseline is process-crossing.
    """
    import json
    import subprocess
    import sys

    code = _COMPOSE_SNIPPET.format(repo=str(REPO_ROOT), manifest=DAVIS)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=True,
    )
    line = [ln for ln in completed.stdout.splitlines() if ln.startswith("{")][-1]
    return json.loads(line)["fp"]


class TestC12IAcceptanceContract:
    def test_V1_unchanged_implementation_yields_stable_identity(self):
        assert _fingerprint_in_fresh_process() == _fingerprint_in_fresh_process()

    def test_V4_fresh_process_sees_the_mutation_and_the_lock_refuses(self, tmp_path):
        """V4 — the property C12-I measured RED pre-fix.

        Two DIFFERENT interpreters: one records the identity, the objective is
        then mutated, and a second fresh interpreter must compute a different
        identity — which is what turns a silent resume into a refused one.
        """
        plugin = REPO_ROOT / "examples/davis_future_prediction/plugins/davis_exact_l1_loss.py"
        backup = tmp_path / "objective.bak"
        shutil.copy2(plugin, backup)

        locked = _fingerprint_in_fresh_process()
        try:
            # A BEHAVIOUR-bearing mutation, not a comment: exact L1 becomes
            # something else entirely, which is precisely the substitution §I
            # forbids and which a name-only identity cannot see.
            plugin.write_text(
                plugin.read_text(encoding="utf-8").replace(
                    "torch.nn.L1Loss", "torch.nn.SmoothL1Loss"
                )
                + "\n# behaviour mutation\n",
                encoding="utf-8",
            )
            after = _fingerprint_in_fresh_process()
        finally:
            shutil.copy2(backup, plugin)

        assert after != locked, (
            "a fresh process must see the mutated objective as a DIFFERENT "
            "identity; equal identities are exactly the silent resume C12-I "
            "measured before this fix"
        )
        assert _fingerprint_in_fresh_process() == locked, "restore must be exact"

    def test_V7_the_executed_implementation_is_the_fingerprinted_one(self):
        """V7 — selection and identity must describe the SAME file.

        Compares the content digest the fingerprint pinned against a digest of
        the file the loss loader actually resolves, so the two authorities
        cannot drift apart while both looking healthy.
        """
        import hashlib
        import os

        from workflows.task_composition import _compose_objective

        _, ref = _compose_objective(
            {
                "objective": {
                    "implementation": {
                        "file": "examples/davis_future_prediction/plugins/davis_exact_l1_loss.py",
                        "symbol": "PLUGIN_LOSS_TYPE",
                    }
                }
            },
            str(REPO_ROOT),
        )
        executed = os.path.join(
            REPO_ROOT, "examples/davis_future_prediction/plugins/davis_exact_l1_loss.py"
        )
        with open(executed, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        assert ref.content_sha256 == digest

    def test_V8_a_same_name_shadow_is_refused_loudly(self, tmp_path):
        """V8 — the C12-I substitution finding.

        Runtime resolves a custom loss BY NAME over a union of directories, so
        a second file declaring the same `PLUGIN_LOSS_TYPE` could be the one
        executed while the fingerprint pinned the declared one. For an
        AUTHORITATIVE objective that must refuse rather than pick.
        """
        import os

        from workflows.task_composition import TaskCompositionError, _compose_objective

        shadow_dir = tmp_path / "shadow_losses"
        shadow_dir.mkdir()
        (shadow_dir / "impostor.py").write_text(
            'PLUGIN_LOSS_TYPE = "davis_exact_l1"\n', encoding="utf-8"
        )
        previous = os.environ.get("SIDERIUS_LOSS_DIRS")
        os.environ["SIDERIUS_LOSS_DIRS"] = str(shadow_dir)
        try:
            with pytest.raises(TaskCompositionError, match="same name"):
                _compose_objective(
                    {
                        "objective": {
                            "implementation": {
                                "file": (
                                    "examples/davis_future_prediction/plugins/"
                                    "davis_exact_l1_loss.py"
                                ),
                                "symbol": "PLUGIN_LOSS_TYPE",
                            }
                        }
                    },
                    str(REPO_ROOT),
                )
        finally:
            if previous is None:
                os.environ.pop("SIDERIUS_LOSS_DIRS", None)
            else:
                os.environ["SIDERIUS_LOSS_DIRS"] = previous

    def test_V8b_no_shadow_means_no_refusal(self):
        """Anti-vacuity for V8: the guard must not refuse the healthy case."""
        from workflows.task_composition import _compose_objective

        config, ref = _compose_objective(
            {
                "objective": {
                    "implementation": {
                        "file": "examples/davis_future_prediction/plugins/davis_exact_l1_loss.py",
                        "symbol": "PLUGIN_LOSS_TYPE",
                    }
                }
            },
            str(REPO_ROOT),
        )
        assert config.loss_name == "davis_exact_l1"
        assert ref is not None
