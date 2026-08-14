"""Model-I/O resolution — Step 03 Phase A, milestone M2.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§11 rungs **FX-3 / FX-4 / 3-E**, §16, §21; Step-01 §6A.5 / roadmap **D13**,
which handed FX-3 and FX-4 to the contract owner because Step 01 *"cannot
fail closed on a conflict it has no way to represent"*.

These are the three Stage-B rungs M2 owns. Each varies exactly one semantic
axis and asserts the unvaried surfaces are unchanged (§11.1).

**Why FX-4's timing matters more than its exception type.** The rung is not
*"a mismatch raises"* — it is *"a mismatch fails BEFORE any LLM request is
constructed"*. A check that ran after prompt assembly would satisfy a naive
raises-test while letting a contradictory contract reach the model, which is
exactly the failure §6A.5 names. The timing property is proven at the
production boundary in Checkpoint C (ii) with an LLMBridge call count; here
it is proven structurally — resolution is a pure function of the
declaration, reachable with no bridge, no network and no prompt.
"""

from __future__ import annotations

import pytest

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.schemas.model_io_resolution import (
    PRESETS,
    DatasetContradictionError,
    ModelIOPreset,
    ModelIOResolutionError,
    PresetContradictionError,
    UnknownPresetError,
    resolve_model_io_contract,
)


def _axis(role: AxisRole | None = None, **dim) -> TensorAxis:
    return TensorAxis(dimension=Dimension(**dim), role=role)


def _contract(*, output_class_dim: int | None = 256) -> ModelIOContract:
    """The TIDMAD-shaped contract, with the class extent parameterized.

    Only the class axis varies, so the cardinality rungs below change one
    thing and nothing else.
    """
    output_axes = [
        _axis(AxisRole.BATCH, symbolic="B"),
        _axis(AxisRole.TEMPORAL, symbolic="T"),
    ]
    if output_class_dim is not None:
        output_axes.insert(1, _axis(AxisRole.CLASS, fixed=output_class_dim))
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


class TestFX3PresetResolution:
    """**FX-3** — preset resolution only, over a fixed explicit contract.

    §11's failure criterion is *"a preset producing a second runtime path"*.
    """

    def test_resolving_with_a_preset_yields_the_identical_contract(self):
        """The rung: adding a preset changes NOTHING about the result.

        Asserted as equality against the un-presetted resolution, so a
        preset that quietly supplied, reordered or defaulted an axis would
        red here rather than silently becoming a second authoring path.
        """
        contract = _contract()
        without = resolve_model_io_contract(contract)
        with_preset = resolve_model_io_contract(contract, preset="sequence")
        assert with_preset == without
        assert with_preset is contract

    def test_the_preset_does_not_survive_resolution(self):
        """Structural, not conventional: the resolved object is the same
        type every consumer already takes and has no preset field, so no
        runtime consumer CAN branch on a label (§21)."""
        resolved = resolve_model_io_contract(_contract(), preset="sequence")
        assert isinstance(resolved, ModelIOContract)
        assert set(type(resolved).model_fields) == {"input", "output"}
        assert not hasattr(resolved, "preset")

    def test_no_production_module_reads_a_preset_after_resolution(self):
        """§16: *"no preset label is read at runtime after resolution —
        greppable"*. Asserted mechanically so the property survives a later
        edit that would otherwise reintroduce a label read somewhere else.
        """
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[4]
        resolver = repo / "agent" / "schemas" / "model_io_resolution.py"
        offenders: list[str] = []
        for path in repo.glob("*/**/*.py"):
            parts = path.parts
            if any(p in {"tests", ".venv", "agent_generated", "docs"} for p in parts):
                continue
            if path == resolver:
                continue  # the ONE place a preset is legitimately read
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "PRESETS" in text or "ModelIOPreset" in text:
                offenders.append(str(path.relative_to(repo)))
        assert offenders == [], (
            "a preset is read outside the resolver — that is a second runtime "
            f"authority (§21): {offenders}"
        )

    def test_an_unknown_preset_fails_closed(self):
        """§16 lists *"invalid preset name"* as an invalid-state analogue.
        It must not silently resolve as if no preset had been authored."""
        with pytest.raises(UnknownPresetError, match="unknown Model-I/O preset"):
            resolve_model_io_contract(_contract(), preset="no_such_preset")

    def test_the_shipped_preset_is_not_named_for_a_modality(self):
        """A modality-named preset invites a modality branch. The shipped
        registry carries the requirement, not the domain — and stays small
        so no preset ships without an authored task needing it."""
        assert set(PRESETS) == {"sequence"}
        assert PRESETS["sequence"].required_input_roles == frozenset(
            {AxisRole.BATCH, AxisRole.TEMPORAL}
        )


class TestFX4PresetMismatch:
    """**FX-4** — preset contradicts the explicit contract.

    §11's failure criterion: *"the contradiction reaching LLMBridge, or
    being silently repaired"*.
    """

    def test_a_missing_required_role_is_a_typed_failure(self):
        """`sequence` over a contract with no temporal axis — §6A.5's own
        example, in neutral clothing."""
        no_temporal = ModelIOContract(
            input=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(fixed=64)),
                dtype=DtypeAdmissibility(admissible=("int64",)),
            ),
            output=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
        )
        with pytest.raises(PresetContradictionError) as exc:
            resolve_model_io_contract(no_temporal, preset="sequence")
        message = str(exc.value)
        assert "input.temporal" in message
        assert "sequence" in message

    def test_the_mismatch_names_every_missing_role_not_only_the_first(self):
        """A diagnostic that stops at the first problem sends an author
        round the loop once per role."""
        bare = ModelIOContract(
            input=TensorContract(
                axes=(_axis(fixed=8),),
                dtype=DtypeAdmissibility(admissible=("int64",)),
            ),
            output=TensorContract(
                axes=(_axis(fixed=8),),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
        )
        with pytest.raises(PresetContradictionError) as exc:
            resolve_model_io_contract(bare, preset="sequence")
        message = str(exc.value)
        for expected in ("input.batch", "input.temporal", "output.batch", "output.temporal"):
            assert expected in message

    def test_the_contract_is_neither_repaired_nor_the_preset_dropped(self):
        """The forbidden repairs of §6A.5 and §21, asserted as an outcome:
        a contradiction produces NO contract at all."""
        no_temporal = ModelIOContract(
            input=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"),),
                dtype=DtypeAdmissibility(admissible=("int64",)),
            ),
            output=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"),),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
        )
        with pytest.raises(PresetContradictionError):
            resolve_model_io_contract(no_temporal, preset="sequence")
        # and the same declaration without the preset still resolves, so the
        # failure is attributable to the contradiction and nothing else
        assert resolve_model_io_contract(no_temporal) is no_temporal

    def test_resolution_needs_no_bridge_prompt_or_network(self):
        """FX-4's real property is TIMING: the failure precedes any LLM
        request. Proven structurally here — resolution is a pure function of
        the declaration — and at the production boundary in Checkpoint C(ii)
        with an LLMBridge call count of 0."""
        import inspect

        import agent.schemas.model_io_resolution as resolution

        source = inspect.getsource(resolution)
        for forbidden in ("LLMBridge", "llm_bridge", "requests", "httpx", "generate("):
            assert forbidden not in source


class TestRung3EDatasetConsistency:
    """**3-E** — contract cardinality vs ``ValueEncoding.num_classes``.

    §11's failure criterion: *"silent coercion, or the contradiction
    reaching training"*.
    """

    def test_a_matching_cardinality_resolves(self):
        assert resolve_model_io_contract(_contract(), dataset_num_classes=256) is not None

    def test_a_contradicting_cardinality_is_a_typed_failure(self):
        """Only the class extent varies from the passing case above."""
        with pytest.raises(DatasetContradictionError) as exc:
            resolve_model_io_contract(_contract(output_class_dim=10), dataset_num_classes=256)
        message = str(exc.value)
        assert "10" in message
        assert "256" in message

    def test_neither_side_is_coerced(self):
        """The contract is returned unchanged when consistent, and no
        contract is returned at all when not — so there is no path on which
        one value silently becomes the other."""
        contract = _contract()
        assert resolve_model_io_contract(contract, dataset_num_classes=256) is contract
        with pytest.raises(DatasetContradictionError):
            resolve_model_io_contract(contract, dataset_num_classes=99)
        assert contract.class_cardinality == 256

    def test_an_output_without_class_semantics_is_not_forced_to_match(self):
        """§4b's deliberate asymmetry: where cardinality is not meaningful,
        the dataset's class count is NOT pushed into the model contract.

        Without this, every continuous-output task would have to restate a
        class count it does not have — the redeclaration §4b forbids.
        """
        continuous = _contract(output_class_dim=None)
        assert continuous.class_cardinality is None
        assert resolve_model_io_contract(continuous, dataset_num_classes=256) is continuous

    def test_no_dataset_profile_means_no_dataset_check(self):
        """A caller with no bound profile is not forced to invent one, and
        must not be silently defaulted to TIDMAD's 256 (§21)."""
        assert resolve_model_io_contract(_contract(output_class_dim=10)) is not None


class TestAtomicity:
    """§11.1 — each rung varies ONE axis, proven mechanically."""

    def test_the_preset_and_dataset_axes_are_independent(self):
        """A preset contradiction and a dataset contradiction are separate
        failures with separate types, so neither rung can pass by
        accidentally tripping the other's check."""
        contract = _contract(output_class_dim=10)
        # dataset axis alone
        with pytest.raises(DatasetContradictionError):
            resolve_model_io_contract(contract, dataset_num_classes=256)
        # preset axis alone — the same contract satisfies `sequence`
        assert resolve_model_io_contract(contract, preset="sequence") is contract

    def test_every_failure_is_one_typed_family(self):
        """A caller can fail closed on 'not resolvable' without enumerating
        causes, which is what lets a production boundary be strict without
        knowing the taxonomy."""
        for error in (UnknownPresetError, PresetContradictionError, DatasetContradictionError):
            assert issubclass(error, ModelIOResolutionError)
        assert issubclass(ModelIOResolutionError, ValueError)

    def test_a_preset_declares_roles_only(self):
        """A preset that could carry dimensions or dtype would be a second
        contract authority. Its fields are the guard."""
        assert set(ModelIOPreset.model_fields) == {
            "name",
            "required_input_roles",
            "required_output_roles",
        }
