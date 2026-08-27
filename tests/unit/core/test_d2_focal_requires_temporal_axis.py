"""D2 — `focal` / `focal_cw` are rank-locked, and the availability rule now says so.

**The defect.** ``FocalLoss1D`` and ``FocalLoss1DCW``
(``ml_models/loss_models_sandbox.py:186`` and ``:227``) build their targets as
``F.one_hot(targets, num_classes=inputs.shape[1]).permute(0, 2, 1)``. That
permute is only defined on a rank-3 one-hot, i.e. on TIDMAD's per-timestep
geometry: ``[B, C, T]`` scores against ``[B, T]`` targets. A task emitting the
ORDINARY classifier geometry — ``[B, C]`` logits with ``[B]`` targets, which
is what ``examples/quickstart`` (``[B, 2]``) and ``examples/oxford_iiit_pet``
(``[B, 37]``) both declare — makes ``F.one_hot`` return a 2-D tensor and the
permute raises ``RuntimeError`` on the first training step, every time.

The constraint existed only as a comment above ``CLASSIFICATION_LOSSES``
(*"Losses that consume per-timestep class logits, [B, C, T]"*), while
``validate_semantic_loss_compatibility`` — whose own docstring calls it
**THE** loss-availability rule — checked semantics and never geometry. So the
framework advertised ``focal`` as available to classifiers generally and then
crashed three layers below the config that chose it.

**What each class below catches, and how it fails when the fix regresses.**

===========================================  ==========================================
class                                        goes red when
===========================================  ==========================================
``TestTheCrashTheRuleExistsToPrevent``       the loss stops being rank-locked (then the
                                             availability rule is over-tight and must
                                             be revisited, not deleted)
``TestTheProductionPathRefusesThePairing``   the geometry rule stops reaching the
                                             PLUGIN branch of the production validator
``TestTheBuiltInBranchIsGovernedToo``        it stops reaching ``ExperimentConfig`` —
                                             the A2b failure class, one rule governing
                                             only one of two branches
``TestTheRefusalIsActionable``               the message stops naming the reason or the
                                             working alternative, i.e. degrades back
                                             into an opaque rejection
``TestThePreFlightRefusesBeforeItProbes``    the fix becomes correct-but-unreachable:
                                             admission runs BEFORE
                                             ``execute_training``, so the probe hit the
                                             permute first and the config-validation
                                             refusal was never reached
``TestPerTimestepGeometryIsStillAccepted``   TIDMAD (or any per-timestep task) starts
                                             being refused ``focal`` — the false
                                             positive that would break the campaign
``TestUndeclaredGeometryKeepsShippedVerdict``an absent declaration starts being read as
                                             a declaration of absence
===========================================  ==========================================

MUTATION EVIDENCE — four independent targets, each with its own red set:

===================================================  =====================================
removed                                              red
===================================================  =====================================
the ``PER_TIMESTEP_CLASSIFICATION_LOSSES`` branch     11 (the rule itself)
``_validate_configs``'s ``ExperimentConfig`` kwarg    2 (built-in branch only)
``_validate_configs``'s plugin-branch kwarg          4 (plugin branch only)
the pre-flight's ``_refuse_unrunnable_loss_geometry`` 2, with the ORIGINAL
                                                     ``RuntimeError: permute(sparse_coo)``
===================================================  =====================================
"""

from __future__ import annotations

import pathlib

import pytest
import torch
import torch.nn.functional as F
from pydantic import BaseModel

from core.sandbox_executor import TidmadSandbox
from ml_models import plugin_loader
from ml_models.models_format_sandbox import (
    CLASSIFICATION_LOSSES,
    PER_TIMESTEP_CLASSIFICATION_LOSSES,
    PLUGIN_CONFIG_REGISTRY,
    ExperimentConfig,
    LossConfig,
    validate_semantic_loss_compatibility,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MANIFEST_DIR = REPO_ROOT / "configs" / "task_composition"

#: A SHIPPED task whose declared output is ``[B, 2]`` — a class axis and no
#: temporal axis. Deliberately a real manifest rather than a synthetic
#: contract: this is the geometry the onboarding pack hands a first-time user.
NON_TEMPORAL_MANIFEST = MANIFEST_DIR / "quickstart.yaml"

#: TIDMAD — ``[B, 256, T]``, the geometry ``focal`` was written for.
TEMPORAL_MANIFEST = MANIFEST_DIR / "tidmad.yaml"

#: `compose_run_task_bindings` needs a data root that exists; none of these
#: tests load data. Same self-deriving precedent as
#: ``test_step12_pr12d_g12d_model_io_wiring.py``.
DATA_ROOT = str(REPO_ROOT)


class _FakePluginConfig(BaseModel):
    """Stand-in for an agent-generated plugin's PLUGIN_CONFIG_CLASS."""

    depth: int = 2


@pytest.fixture
def bound_run():
    """Bind a real composed run, exactly as ``main`` does, and yield.

    Not a monkeypatch of the accessor: the point is that the fact travels
    from a real manifest through ``run_bound_model_io_contract`` into the
    production validator. A test that stubbed the accessor could not tell
    the wiring from the rule.
    """
    import contextlib

    from execute_tools.task_registration_scope import run_registration_scope
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    @contextlib.contextmanager
    def _bind(manifest: pathlib.Path):
        # `run_registration_scope` is what keeps a real composition from
        # leaking a task registration into the process-global registry and
        # tripping the two-phase identity rule for the NEXT module that
        # composes the same pack. Same discipline as
        # ``tests/unit/examples/test_quickstart_pack.py``.
        with run_registration_scope():
            composition = compose_run_task_bindings(str(manifest))
            with bind_run_task_composition(composition, physical_data_root=DATA_ROOT):
                yield

    return _bind


@pytest.fixture
def registered_plugin(monkeypatch):
    """Register a generated-style plugin under a chosen output contract.

    Mirrors ``tests/unit/core/test_plugin_loss_compatibility.py`` — the
    registries a real ``plugin_loader`` run populates.
    """

    def _register(output_type: str, name: str = "d2_probe_model") -> str:
        monkeypatch.setitem(PLUGIN_CONFIG_REGISTRY, name, _FakePluginConfig)
        monkeypatch.setitem(plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY, name, output_type)
        return name

    return _register


def _validate(model_type: str, loss_type: str, m_cfg: dict | None = None):
    """Invoke the REAL production validator, plugin branch or built-in branch.

    ``__new__`` so no workspace is created — the same construction
    ``test_plugin_loss_compatibility.py`` uses.
    """
    executor = TidmadSandbox.__new__(TidmadSandbox)
    return TidmadSandbox._validate_configs(
        executor,
        model_type,
        m_cfg if m_cfg is not None else {"depth": 2},
        {"lr": 5e-4, "epochs": 1, "batch_size": 2},
        {"loss_type": loss_type},
        "exp-d2",
        "run-d2",
    )


class TestTheCrashTheRuleExistsToPrevent:
    """The rank lock is real, and it is in the loss, not in the model.

    If this goes green-for-the-wrong-reason — i.e. the losses stop raising —
    the availability rule has become a false refusal and must be re-derived
    from the new implementation, never simply removed.
    """

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_the_ordinary_classifier_geometry_raises_inside_the_loss(self, loss_type):
        from ml_models.loss_models_sandbox import get_criterion

        criterion = get_criterion(LossConfig(loss_type=loss_type), None)
        scores = torch.randn(4, 10, requires_grad=True)  # [B, C]
        targets = torch.randint(0, 10, (4,))  # [B]
        with pytest.raises(RuntimeError, match="permute"):
            criterion(scores, targets)

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_the_per_timestep_geometry_is_what_it_accepts(self, loss_type):
        from ml_models.loss_models_sandbox import get_criterion

        criterion = get_criterion(LossConfig(loss_type=loss_type), None)
        scores = torch.randn(4, 10, 7, requires_grad=True)  # [B, C, T]
        targets = torch.randint(0, 10, (4, 7))  # [B, T]
        assert torch.isfinite(criterion(scores, targets)).all()

    def test_ce_is_the_alternative_the_refusal_names(self):
        """The message tells the planner to use 'ce'; that must actually work."""
        criterion = torch.nn.CrossEntropyLoss()
        loss = criterion(torch.randn(4, 10), torch.randint(0, 10, (4,)))
        assert torch.isfinite(loss)

    def test_the_frozenset_names_exactly_the_permuting_losses(self):
        """Membership is a claim about the implementation, so check it there.

        A loss added to the set without the permute would be refused for a
        constraint it does not have; one that permutes and is missing from the
        set would keep crashing.
        """
        import inspect

        from ml_models import loss_models_sandbox

        permuting = {
            "focal": loss_models_sandbox.FocalLoss1D,
            "focal_cw": loss_models_sandbox.FocalLoss1DCW,
            "ce": None,
            "smooth_l1": None,
        }
        for loss_type, cls in permuting.items():
            permutes = cls is not None and ".permute(0, 2, 1)" in inspect.getsource(cls)
            assert permutes == (loss_type in PER_TIMESTEP_CLASSIFICATION_LOSSES), (
                f"{loss_type}: implementation permutes={permutes}, but "
                f"PER_TIMESTEP_CLASSIFICATION_LOSSES membership says otherwise"
            )

    def test_the_geometry_set_is_a_subset_of_the_semantic_one(self):
        """Geometry NARROWS classification availability; it never widens it."""
        assert PER_TIMESTEP_CLASSIFICATION_LOSSES < CLASSIFICATION_LOSSES


class TestTheProductionPathRefusesThePairing:
    """The plugin branch — the kind of model the agent actually invents."""

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_a_shipped_non_temporal_task_refuses_the_loss(
        self, bound_run, registered_plugin, loss_type
    ):
        with bound_run(NON_TEMPORAL_MANIFEST):
            name = registered_plugin("classifier")
            with pytest.raises(ValueError) as exc:
                _validate(name, loss_type)
        assert "Plugin Experiment Configuration Rejected" in str(exc.value)

    def test_the_real_shipped_quickstart_model_is_refused_too(self, bound_run):
        """No synthetic registration at all: the manifest's own model plugin.

        This is the whole pairing a first-time user gets — shipped task,
        shipped model, the loss the planner prompt steers them toward.
        """
        with bound_run(NON_TEMPORAL_MANIFEST):
            assert "quickstart_reference_mlp" in PLUGIN_CONFIG_REGISTRY
            with pytest.raises(ValueError) as exc:
                _validate("quickstart_reference_mlp", "focal", m_cfg={"hidden_dim": 8})
        assert "Plugin Experiment Configuration Rejected" in str(exc.value)

    def test_ce_is_still_accepted_for_the_same_task(self, bound_run, registered_plugin):
        """The refusal is about geometry, not about classification.

        Without this cell the rule could refuse every classification loss and
        still look correct above.
        """
        with bound_run(NON_TEMPORAL_MANIFEST):
            name = registered_plugin("classifier")
            _m, _t, loss_cfg = _validate(name, "ce")
        assert loss_cfg["loss_type"] == "ce"

    def test_a_regressor_still_gets_the_regressor_advice(self, bound_run, registered_plugin):
        """Ordering: the semantic rule must fire before the geometry rule.

        DAVIS declares a continuous output that also carries no temporal
        axis. Pointing that run at 'ce' would be actively wrong, so the
        geometry branch is evaluated LAST.
        """
        with bound_run(NON_TEMPORAL_MANIFEST):
            name = registered_plugin("regressor")
            with pytest.raises(ValueError) as exc:
                _validate(name, "focal")
        assert "regressor" in str(exc.value)
        assert "smooth_l1" in str(exc.value)


class TestTheBuiltInBranchIsGovernedToo:
    """A2b's lesson: one branch carrying the rule is not evidence for the other.

    ``ExperimentConfig`` cannot ask the run what geometry it declared —
    ``ml_models`` does not import ``workflows``. The fact is therefore
    delivered by ``_validate_configs``, and this class is what proves the
    delivery happens rather than being assumed.
    """

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_a_built_in_classifier_is_refused_under_a_non_temporal_task(self, bound_run, loss_type):
        with bound_run(NON_TEMPORAL_MANIFEST):
            with pytest.raises(ValueError) as exc:
                _validate("wavenet", loss_type, m_cfg={"model_type": "wavenet"})
        assert "Experiment Configuration Rejected" in str(exc.value)

    def test_the_executor_supplies_the_fact_rather_than_experiment_config_fetching_it(self):
        """The delivery is structural, so state it structurally.

        If a future edit makes ``ExperimentConfig`` reach for the run binding
        itself, that is the layer inversion the Model-I/O contract module is
        arranged to avoid, and this reds.
        """
        import ast
        import inspect

        executor_src = inspect.getsource(TidmadSandbox._validate_configs)
        assert "run_bound_output_has_temporal_axis" in executor_src

        authority = REPO_ROOT / "ml_models" / "models_format_sandbox.py"
        tree = ast.parse(authority.read_text(encoding="utf-8"))
        upward = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] in ("workflows", "agent", "core", "nodes")
        ] + [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name.split(".")[0] in ("workflows", "agent", "core", "nodes")
        ]
        assert upward == [], (
            f"{authority.name} imports {upward} — the layer inversion that "
            f"supplying `output_has_temporal_axis` from the executor avoids"
        )

    def test_the_field_is_not_something_the_planner_authors(self):
        """It is a caller-supplied fact; its default must be the legacy one."""
        assert ExperimentConfig.model_fields["output_has_temporal_axis"].default is None


class TestTheRefusalIsActionable:
    """A refusal that does not say why, or what to do, is a crash with a nicer
    traceback. The planner reads this string."""

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_it_names_the_reason_and_the_alternative(self, loss_type):
        from ml_models.models_format_sandbox import OutputSemantic

        with pytest.raises(ValueError) as exc:
            validate_semantic_loss_compatibility(
                OutputSemantic.CATEGORICAL,
                loss_type,
                model_type="d2_probe",
                output_has_temporal_axis=False,
            )
        message = str(exc.value)
        assert loss_type in message
        assert "PER-TIMESTEP" in message
        assert "[B, C, T]" in message
        assert "no temporal axis" in message
        assert "'ce'" in message

    def test_it_reaches_the_operator_through_the_production_wrapper(
        self, bound_run, registered_plugin
    ):
        """The executor re-wraps the ValueError; the reason must survive."""
        with bound_run(NON_TEMPORAL_MANIFEST):
            name = registered_plugin("classifier")
            with pytest.raises(ValueError) as exc:
                _validate(name, "focal")
        message = str(exc.value)
        assert "PER-TIMESTEP" in message
        assert "'ce'" in message


class TestThePreFlightRefusesBeforeItProbes:
    """The consumer a real run reaches FIRST.

    ``run_admission_preflight`` runs before ``execute_training``, and the VRAM
    pre-flight instantiates the candidate's loss and CALLS it
    (``structural_probe.probe_activation_footprint`` →
    ``loss_module(logits, target)``). So on the real ordering the permute fired
    here, surfaced as an opaque ``"VRAMEval runtime error: permute(sparse_coo)
    ..."``, and the refusal waiting in ``_validate_configs`` was never reached.

    Without this class the fix would be correct and unreachable: every
    assertion above would stay green while a real run still died on a tensor
    op. It goes red if the pre-flight stops consulting the shared authority.
    """

    @staticmethod
    def _preflight(loss_type: str, contract):
        from datetime import UTC, datetime

        from agent.skills.evaluate_vram_skill import wrapper
        from core.hardware_context import HardwareContext

        gpu = HardwareContext(
            device_name="MockGPU 9000",
            total_memory_bytes=32 * 1024**3,
            compute_capability=(9, 0),
            multiprocessor_count=128,
            cuda_runtime_version="12.1",
            torch_version="2.0.0",
            hostname="test-host",
            device_available=True,
            discovered_at=datetime.now(UTC),
        )
        return wrapper.run_skill(
            sandbox=None,
            hardware_context=gpu,
            model_type="quickstart_reference_mlp",
            model_config={"hidden_dim": 8},
            train_config={"batch_size": 2, "optimizer": "adam"},
            loss_config={"loss_type": loss_type},
            model_io_contract=contract,
        )

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_it_refuses_instead_of_dying_in_the_permute(self, bound_run, loss_type):
        from workflows.task_config import run_bound_model_io_contract

        with bound_run(NON_TEMPORAL_MANIFEST):
            contract = run_bound_model_io_contract()
            assert contract is not None and not contract.output_has_temporal_axis
            result = self._preflight(loss_type, contract)

        assert result["status"] != "success", result
        message = result.get("message", "")
        assert "PER-TIMESTEP" in message, message
        assert "'ce'" in message, message
        # The failure it replaced. If this substring comes back, the pre-flight
        # reached the tensor op again.
        assert "permute(sparse_coo)" not in message, message

    def test_ce_still_reaches_the_actual_measurement(self, bound_run):
        """The pre-flight refuses the pairing, not the task."""
        from workflows.task_config import run_bound_model_io_contract

        with bound_run(NON_TEMPORAL_MANIFEST):
            contract = run_bound_model_io_contract()
            result = self._preflight("ce", contract)

        assert result["status"] == "success", result

    def test_the_pre_flight_calls_the_shared_authority(self):
        """One rule, two consumers — not two rules.

        Reds if someone re-inlines the loss-family literals here, which is
        the duplicate-authority defect V21 PR A1 deleted.
        """
        import io
        import tokenize

        source = (REPO_ROOT / "agent" / "skills" / "evaluate_vram_skill" / "wrapper.py").read_text(
            encoding="utf-8"
        )
        assert "validate_loss_output_geometry" in source

        code_only = "".join(
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(source).readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        )
        assert "focal_cw" not in code_only
        assert "PER_TIMESTEP_CLASSIFICATION_LOSSES" not in code_only

    def test_the_pre_flight_does_not_re_decide_semantic_legality(self, bound_run):
        """Bounded on purpose: classifier + smooth_l1 still probes fine here.

        That pairing is refused, with its own advice, at config validation.
        Refusing it a stage earlier would move where an ordinary LLM mistake
        is reported on the TIDMAD campaign path — a behaviour change D2 does
        not need and does not make.
        """
        from workflows.task_config import run_bound_model_io_contract

        with bound_run(TEMPORAL_MANIFEST):
            contract = run_bound_model_io_contract()
            assert contract is not None and contract.output_has_temporal_axis
            from ml_models.models_format_sandbox import validate_loss_output_geometry

            validate_loss_output_geometry(
                "smooth_l1",
                model_type="wavenet",
                output_has_temporal_axis=contract.output_has_temporal_axis,
            )

    def test_the_geometry_rule_has_exactly_one_implementation(self):
        """The semantic authority must DELEGATE, never carry a second copy.

        Comments and docstrings are stripped before scanning — naming the
        constant while explaining the delegation is not a second copy of the
        rule. Same idiom as
        ``test_plugin_loss_compatibility.py::test_executor_does_not_reimplement_the_rule``.
        """
        import inspect
        import io
        import tokenize

        from ml_models.models_format_sandbox import (
            validate_loss_output_geometry,
            validate_semantic_loss_compatibility,
        )

        def _code_only(src: str) -> str:
            return "".join(
                tok.string
                for tok in tokenize.generate_tokens(io.StringIO(src).readline)
                if tok.type not in (tokenize.COMMENT, tokenize.STRING)
            )

        semantic_src = inspect.getsource(validate_semantic_loss_compatibility)
        assert "validate_loss_output_geometry(" in _code_only(semantic_src)
        assert "PER_TIMESTEP_CLASSIFICATION_LOSSES" not in _code_only(semantic_src)
        assert "PER_TIMESTEP_CLASSIFICATION_LOSSES" in _code_only(
            inspect.getsource(validate_loss_output_geometry)
        )


class TestPerTimestepGeometryIsStillAccepted:
    """The false-positive guard. TIDMAD's campaign runs on ``focal``."""

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_a_temporal_task_accepts_the_loss_on_the_plugin_branch(
        self, bound_run, registered_plugin, loss_type
    ):
        with bound_run(TEMPORAL_MANIFEST):
            name = registered_plugin("classifier")
            _m, _t, loss_cfg = _validate(name, loss_type)
        assert loss_cfg["loss_type"] == loss_type

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_a_temporal_task_accepts_the_loss_on_the_built_in_branch(self, bound_run, loss_type):
        with bound_run(TEMPORAL_MANIFEST):
            _m, _t, loss_cfg = _validate("wavenet", loss_type, {"model_type": "wavenet"})
        assert loss_cfg["loss_type"] == loss_type

    def test_the_run_scoped_accessor_reads_the_declared_roles(self, bound_run):
        """The fact itself, at its single acquisition point."""
        from workflows.task_config import run_bound_output_has_temporal_axis

        with bound_run(TEMPORAL_MANIFEST):
            assert run_bound_output_has_temporal_axis() is True
        with bound_run(NON_TEMPORAL_MANIFEST):
            assert run_bound_output_has_temporal_axis() is False


class TestUndeclaredGeometryKeepsShippedVerdict:
    """``None`` is *"no declaration"*, never *"declared absent"*.

    A legacy prose-only (Regime-A) task declares no ``model_io``. Reading that
    as ``False`` would refuse ``focal`` for every such task — a changed verdict
    on the legacy path, which Step 03 §21 makes a stop condition.
    """

    @pytest.mark.parametrize("loss_type", sorted(PER_TIMESTEP_CLASSIFICATION_LOSSES))
    def test_an_undeclared_geometry_permits_the_loss(self, loss_type):
        from ml_models.models_format_sandbox import OutputSemantic

        validate_semantic_loss_compatibility(
            OutputSemantic.CATEGORICAL,
            loss_type,
            model_type="d2_probe",
            output_has_temporal_axis=None,
        )

    def test_the_accessor_returns_none_for_a_prose_only_task(self, tmp_path):
        from workflows.task_config import run_bound_output_has_temporal_axis

        config = tmp_path / "task_config.yaml"
        config.write_text(
            "task_description: a prose-only Regime-A task\n"
            "forward_contract:\n"
            '  input_shape: "[B, T]"\n'
            '  output_shape: "[B, 256, T]"\n'
            "  num_classes: 256\n",
            encoding="utf-8",
        )
        assert run_bound_output_has_temporal_axis(str(config)) is None


def test_one_hot_is_the_mechanism_this_whole_module_is_about():
    """The two-line reproduction, so a reader never has to take it on trust."""
    with pytest.raises(RuntimeError):
        F.one_hot(torch.randint(0, 10, (4,)), num_classes=10).permute(0, 2, 1)
    assert F.one_hot(torch.randint(0, 10, (4, 7)), num_classes=10).permute(0, 2, 1).shape == (
        4,
        10,
        7,
    )
