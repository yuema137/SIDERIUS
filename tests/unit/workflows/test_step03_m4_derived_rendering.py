"""Derived rendering and the live resolution boundary — Step 03 M4.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§1 row 7 (the renderer asserts a temporal axis from a cardinality fact),
§5 A1 + the Regime-A inventory, §9, §16, §21.

M4 turns the normalized contract into the AUTHORITY behind the prose that
reaches the LLM, and wires resolution into the production loader. Its
failure classes:

==================================================  =====================
failure class                                        caught here by
==================================================  =====================
the prose stops being derived, so contract and       ``TestContractIsTheAuthority``
prose can silently disagree
Regime A breaks — a legacy prose-only contract       ``TestRegimeAIsUntouched``
stops rendering as it always has
the per-timestep clause reverts to "cardinality      ``TestClauseDerivesFromRoles``
is truthy", re-asserting a temporal axis that
the contract does not declare (row 7)
resolution is not actually reached from the          ``TestResolutionIsWiredAtTheEntryPoint``
production entry point, so a contradiction
loads cleanly
==================================================  =====================

The rendered-byte property itself is owned by the A1 goldens
(``tests/unit/agent/ml_model_proposal_agent/goldens/pb3_*``), which must
pass **UNMODIFIED**. This module does not restate them; it pins the
authority and the wiring they cannot see.
"""

from __future__ import annotations

import textwrap

import pytest
from pydantic import ValidationError

import workflows.task_config as tc
from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.schemas.task_config import ForwardContract
from workflows.task_config import load_task_config, render_forward_contract


def _axis(role: AxisRole | None = None, **dim) -> TensorAxis:
    return TensorAxis(dimension=Dimension(**dim), role=role)


def _model_io(*, with_class: bool = True, with_temporal: bool = True) -> ModelIOContract:
    output_axes = [_axis(AxisRole.BATCH, symbolic="B")]
    if with_class:
        output_axes.append(_axis(AxisRole.CLASS, fixed=256))
    if with_temporal:
        output_axes.append(_axis(AxisRole.TEMPORAL, symbolic="T"))
    return ModelIOContract(
        input=TensorContract(
            axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
            dtype=DtypeAdmissibility(admissible=("int64", "int32")),
        ),
        output=TensorContract(
            axes=tuple(output_axes),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
    )


class TestContractIsTheAuthority:
    """§21 — one authority. The prose is derived, never co-authored."""

    def test_the_prose_fields_are_derived_from_the_contract(self):
        fc = ForwardContract(model_io=_model_io(), task_type="classification")
        assert fc.input_shape == "[B, T] int64"
        assert fc.output_shape == "[B, 256, T] float32"
        assert fc.num_classes == 256

    def test_contradicting_prose_is_a_typed_failure_not_a_silent_overwrite(self):
        """The dangerous alternative. Silently overwriting would let an
        author believe a value that never reached the model — which is the
        'nothing silently repairs' rule of §21."""
        with pytest.raises(ValidationError) as exc:
            ForwardContract(model_io=_model_io(), input_shape="[B, 999] int8")
        assert "authored" in str(exc.value)
        assert "derived" in str(exc.value)

    def test_agreeing_prose_is_accepted(self):
        """Restating the derived value is redundant but not wrong — only a
        CONTRADICTION fails, so a migration can proceed incrementally."""
        fc = ForwardContract(model_io=_model_io(), input_shape="[B, T] int64")
        assert fc.input_shape == "[B, T] int64"


class TestRegimeAIsUntouched:
    """§5's Regime-A inventory — the legacy prose form keeps working."""

    def test_a_prose_only_contract_renders_exactly_as_before(self):
        fc = ForwardContract(
            input_shape="[B, T] int64",
            input_description="raw signal",
            output_shape="[B, 256, T] float32",
            output_description="logits",
            num_classes=256,
            task_type="classification",
        )
        rendered = render_forward_contract(fc)
        assert "    input:  [B, T] int64   — raw signal" in rendered
        assert "    output: [B, 256, T] float32  — logits" in rendered
        assert "Task type: classification (per-timestep 256-class)." in rendered

    def test_a_prose_only_contract_derives_nothing_and_checks_nothing(self):
        """No `model_io` means no derivation and no validation — a legacy
        caller cannot be broken by a rule it never opted into."""
        fc = ForwardContract(input_shape="anything at all", num_classes=7)
        assert fc.model_io is None
        assert fc.input_shape == "anything at all"
        assert fc.num_classes == 7

    def test_a_bare_contract_still_renders_empty(self):
        """The named Regime-A case *"a legacy caller constructing a bare
        ForwardContract()"*."""
        assert ForwardContract().is_empty()
        assert render_forward_contract(ForwardContract()) == ""


class TestClauseDerivesFromRoles:
    """§1 row 7 — the per-timestep clause is licensed by axis ROLES."""

    def test_tidmad_keeps_the_clause(self):
        fc = ForwardContract(model_io=_model_io(), task_type="classification")
        assert fc.renders_per_timestep_class_clause()
        assert "(per-timestep 256-class)" in render_forward_contract(fc)

    def test_a_class_axis_without_a_temporal_axis_drops_the_clause(self):
        """The row-7 defect, isolated. The old rule keyed on cardinality
        being truthy, so this contract — which has a class count but no
        temporal axis — would have claimed 'per-timestep' about a tensor
        that has no timesteps.

        Note the cardinality is UNCHANGED at 256: only the temporal axis
        varies, so a consumer still reading `num_classes` truthiness reds
        here and nowhere else.
        """
        fc = ForwardContract(model_io=_model_io(with_temporal=False), task_type="classification")
        assert fc.num_classes == 256
        assert not fc.renders_per_timestep_class_clause()
        rendered = render_forward_contract(fc)
        assert "per-timestep" not in rendered
        assert "Task type: classification." in rendered

    def test_a_temporal_axis_without_a_class_axis_drops_the_clause(self):
        fc = ForwardContract(model_io=_model_io(with_class=False), task_type="classification")
        assert fc.num_classes == 0
        assert not fc.renders_per_timestep_class_clause()

    def test_regime_a_keeps_the_legacy_truthiness_rule(self):
        """Unmigrated callers must not change behaviour, even though the
        legacy rule is the one row 7 criticises."""
        assert ForwardContract(num_classes=8, task_type="x").renders_per_timestep_class_clause()
        assert not ForwardContract(num_classes=0, task_type="x").renders_per_timestep_class_clause()


class TestResolutionIsWiredAtTheEntryPoint:
    """The M2 resolver must actually be REACHED from production.

    A resolver that exists but is never called is the reachability failure
    CLAUDE.md names: a rule existing in source is not evidence that any
    consumer honours it.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        tc._clear_cache_for_tests()
        yield
        tc._clear_cache_for_tests()

    def _write(self, tmp_path, *, preset: str, class_dim: int) -> str:
        path = tmp_path / "task_config.yaml"
        path.write_text(
            textwrap.dedent(f"""\
                task_description: |
                  a synthetic contrast task
                forward_contract:
                  preset: {preset}
                  model_io:
                    input:
                      axes:
                        - {{role: batch, dimension: {{symbolic: "B"}}}}
                        - {{role: temporal, dimension: {{symbolic: "T"}}}}
                      dtype: {{admissible: ["int64", "int32"]}}
                    output:
                      axes:
                        - {{role: batch, dimension: {{symbolic: "B"}}}}
                        - {{role: class, dimension: {{fixed: {class_dim}}}}}
                        - {{role: temporal, dimension: {{symbolic: "T"}}}}
                      dtype: {{admissible: ["float32"]}}
                  task_type: "classification"
                """)
        )
        return str(path)

    def test_a_consistent_declaration_loads(self, tmp_path):
        config = load_task_config(self._write(tmp_path, preset="sequence", class_dim=256))
        resolved = config["forward_contract"]
        assert resolved["preset"] == "sequence"
        assert resolved["input_shape"] == "[B, T] int64"
        assert resolved["output_shape"] == "[B, 256, T] float32"
        assert resolved["num_classes"] == 256
        assert ForwardContract(**resolved).model_io is not None

    def test_an_unknown_preset_fails_at_load(self, tmp_path):
        """FX-4's timing property at the PRODUCTION entry point: the failure
        happens while reading the config, long before any prompt exists."""
        from agent.schemas.model_io_resolution import UnknownPresetError

        with pytest.raises(UnknownPresetError):
            load_task_config(self._write(tmp_path, preset="no_such_preset", class_dim=256))

    def test_a_dataset_cardinality_contradiction_fails_at_load(self, tmp_path):
        """3-E at the production entry point. The bound profile declares 256;
        a contract claiming 10 must not load."""
        from agent.schemas.model_io_resolution import DatasetContradictionError

        with pytest.raises(DatasetContradictionError):
            load_task_config(self._write(tmp_path, preset="sequence", class_dim=10))


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
