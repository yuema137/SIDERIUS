"""Contract-keyed model-boundary input dtype — Step 03 M5 (Phase B).

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
**§4a.1 AMENDMENT A-1**, §11 rungs **3-B / 3-B-neg**, §16, §21,
§24.9 **Q7 / Q8** (the two questions deferred until this code existed).

**What baseline A6 covers, and what it cannot.** A6 pins the CONCRETE dtype
reaching every builtin at every boundary, and it passes UNMODIFIED against
the migrated path — that is the compatibility half, and it is the strongest
evidence that M5 changed no executed tensor. A6 is deliberately blind to
*how* the dtype was chosen, so it would stay green if the model-name branch
were still there. This module covers the half A6 cannot see:

===========================================  ==========================
failure class                                 caught here by
===========================================  ==========================
dtype still resolved from a model NAME        ``TestNoModelNameBranch``
a site preference treated as a CONSTRAINT,    ``TestQ7SupportedAlternative``
so an inadmissible preference fails
instead of selecting an alternative
an unsatisfiable requirement silently         ``TestQ8FailsClosed``
coerced instead of failing closed
the contract does not survive the real        ``TestTransport``
subprocess boundary
===========================================  ==========================
"""

from __future__ import annotations

import inspect
import textwrap
from types import SimpleNamespace

import pytest
import torch

import execute_tools.inference_single as inf
import execute_tools.train_engine_sandbox as tes
from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
    load_model_io_contract,
)
from execute_tools.model_input_dtype import (
    INFERENCE_SITE_DTYPE,
    RUNTIME_SUPPORTED_DTYPES,
    TRAINING_SITE_DTYPE,
    UnsupportedModelInputDtypeError,
    model_input_admissibility,
    resolve_contract_input_dtype,
    resolve_input_dtype,
    resolve_model_input_dtype,
)
from ml_models.models_sandbox import BUILTIN_INPUT_DTYPES, BUILTIN_OUTPUT_TYPES


def _axis(role: AxisRole | None = None, **dim) -> TensorAxis:
    return TensorAxis(dimension=Dimension(**dim), role=role)


def _contract(*admissible: str) -> ModelIOContract:
    """A contract varying ONLY the input dtype admissibility."""
    return ModelIOContract(
        input=TensorContract(
            axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
            dtype=DtypeAdmissibility(admissible=admissible),
        ),
        output=TensorContract(
            axes=(
                _axis(AxisRole.BATCH, symbolic="B"),
                _axis(AxisRole.CLASS, fixed=256),
                _axis(AxisRole.TEMPORAL, symbolic="T"),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
    )


TIDMAD = _contract("int64", "int32")


class TestComposedRuntimeDtype:
    def test_training_and_inference_use_one_declared_representation(self):
        assert resolve_contract_input_dtype(TIDMAD.input.dtype) is torch.int64
        assert resolve_input_dtype(
            "generated_model", TIDMAD, site_preference=TRAINING_SITE_DTYPE
        ) is torch.int64
        assert resolve_input_dtype(
            "generated_model", TIDMAD, site_preference=INFERENCE_SITE_DTYPE
        ) is torch.int64

    def test_another_task_can_declare_a_different_canonical_dtype(self):
        contract = _contract("int32", "int64")
        assert resolve_input_dtype(
            "generated_model", contract, site_preference=TRAINING_SITE_DTYPE
        ) is torch.int32
        assert resolve_input_dtype(
            "generated_model", contract, site_preference=INFERENCE_SITE_DTYPE
        ) is torch.int32

    @pytest.mark.parametrize(
        ("admissible", "expected"),
        [(("int64", "int32"), torch.int64), (("int32", "int64"), torch.int32)],
    )
    def test_generated_and_live_probes_match_training_boundary(self, admissible, expected):
        from agent.skills.model_io_probe_skill import build_model_input
        from nodes.ml_model_implementor.ml_model_implementor import _render_test_input_expr

        contract = _contract(*admissible)
        training_dtype = resolve_input_dtype(
            "generated_model", contract, site_preference=TRAINING_SITE_DTYPE
        )
        live_probe = build_model_input(contract, batch=2, symbolic=8)
        rendered_probe = eval(
            _render_test_input_expr(contract, index_extent=16, batch_literal=2),
            {"torch": torch, "config": SimpleNamespace(segmentation_size=8)},
        )
        assert training_dtype is expected
        assert live_probe.dtype is expected
        assert rendered_probe.dtype is expected


class TestRung3BDtypeRequirement:
    """**3-B** — vary the declared requirement, hold everything else fixed."""

    def test_the_site_preference_wins_when_it_is_admissible(self):
        """The compatibility path that keeps A6 exact."""
        assert (
            resolve_model_input_dtype(TIDMAD.input.dtype, site_preference=TRAINING_SITE_DTYPE)
            is torch.int32
        )
        assert (
            resolve_model_input_dtype(TIDMAD.input.dtype, site_preference=INFERENCE_SITE_DTYPE)
            is torch.int64
        )

    def test_narrowing_the_requirement_changes_the_resolved_dtype(self):
        """Only the declared admissibility varies; the site preference and
        every other axis are unchanged. A resolver ignoring the contract
        would return int32 here and red."""
        only64 = _contract("int64")
        assert (
            resolve_model_input_dtype(only64.input.dtype, site_preference=TRAINING_SITE_DTYPE)
            is torch.int64
        )

    def test_a_float_requirement_resolves_to_float(self):
        assert (
            resolve_model_input_dtype(
                _contract("float32").input.dtype, site_preference=TRAINING_SITE_DTYPE
            )
            is torch.float32
        )

    def test_the_dataset_dtype_is_not_consulted(self):
        """§4a — dataset dtype and model-boundary dtype are DISTINCT. The
        resolver's signature is the proof: it cannot consult a dataset it is
        never given."""
        params = set(inspect.signature(resolve_model_input_dtype).parameters)
        assert params == {"admissibility", "site_preference"}


class TestQ7SupportedAlternative:
    """**§24.9 Q7** — an inadmissible site preference must NOT fail."""

    def test_an_inadmissible_preference_selects_an_admissible_alternative(self):
        """The rule A-1 correction 1 exists for. 'Site dtype or fail' would
        elevate a legacy preference into a semantic constraint."""
        resolved = resolve_model_input_dtype(
            _contract("float32").input.dtype, site_preference=TRAINING_SITE_DTYPE
        )
        assert resolved is torch.float32

    def test_the_alternative_is_the_contracts_canonical_representation(self):
        """Deterministic, per A-1: `admissible[0]` filtered to runtime
        support — not an arbitrary member of the set."""
        assert (
            resolve_model_input_dtype(
                _contract("int64", "float32").input.dtype, site_preference="bfloat16"
            )
            is torch.int64
        )
        assert (
            resolve_model_input_dtype(
                _contract("float32", "int64").input.dtype, site_preference="bfloat16"
            )
            is torch.float32
        )

    def test_fcnet_is_the_LIVE_production_case_for_this_rule(self):
        """Not a synthetic rung: `fcnet` declares float32 alone, so the
        training site's int32 preference is inadmissible and resolution
        falls through — every real training run exercises Q7."""
        assert BUILTIN_INPUT_DTYPES["fcnet"].admissible == ("float32",)
        assert resolve_input_dtype("fcnet", TIDMAD, site_preference=TRAINING_SITE_DTYPE) is (
            torch.float32
        )
        assert resolve_input_dtype("fcnet", TIDMAD, site_preference=INFERENCE_SITE_DTYPE) is (
            torch.float32
        )


class TestQ8FailsClosed:
    """**§24.9 Q8** — an empty intersection is a typed failure."""

    def test_a_requirement_the_runtime_cannot_materialize_raises(self):
        """`bfloat16` is EXPRESSIBLE in the contract (A-1 correction 2) but
        the adaptation path does not materialize it. Expressing it must not
        be silently downgraded to something plausible."""
        with pytest.raises(UnsupportedModelInputDtypeError) as exc:
            resolve_model_input_dtype(
                _contract("bfloat16").input.dtype, site_preference=TRAINING_SITE_DTYPE
            )
        message = str(exc.value)
        assert "bfloat16" in message
        assert "intersection is empty" in message

    def test_it_does_not_fall_back_to_the_site_preference(self):
        """The dangerous repair: quietly using int32 because that is what
        this site always used would produce a plausible, wrong tensor."""
        with pytest.raises(UnsupportedModelInputDtypeError):
            resolve_model_input_dtype(
                _contract("complex64").input.dtype, site_preference=TRAINING_SITE_DTYPE
            )

    def test_a_partially_supported_requirement_still_resolves(self):
        """Only a WHOLLY unsupported requirement fails — one supported member
        is enough, which is what keeps expressiveness ahead of support
        without breaking anything."""
        assert (
            resolve_model_input_dtype(
                _contract("bfloat16", "int32").input.dtype, site_preference=TRAINING_SITE_DTYPE
            )
            is torch.int32
        )

    def test_only_evidenced_dtypes_are_claimed_supported(self):
        """§24.9 Q14 — the runtime-capability table is exactly the three
        dtypes baseline A6 executes. Adding a row is a claim needing
        evidence."""
        assert set(RUNTIME_SUPPORTED_DTYPES) == {"int64", "int32", "float32"}


class TestNoModelNameBranch:
    """The failure class A6 is structurally blind to."""

    # `test_the_data_path_contains_no_input_dtype_name_branch` lived here and
    # was REMOVED, not lost. It counted the surviving `== "fcnet"` lines and
    # asserted none carried a dtype cast — brittle (it would red if a future
    # step legitimately added a constructor branch) and now subsumed by
    # `tests/unit/guardrails/test_no_model_name_dtype_routing.py`, which
    # states the same property semantically over the AST and proves it
    # detects both removed forms. One claim, one owner.

    def test_resolution_keys_a_declaration_not_a_branch(self):
        """A model name is a KEY into a declaration — the
        `LOSS_TARGET_DTYPE_REGISTRY` precedent — never a condition.

        Asserted over EXECUTABLE source with the docstring removed. The
        docstring deliberately quotes the branch it replaced, and a naive
        substring scan matches that quotation — which is a test reading
        prose as if it were code.
        """
        import ast

        tree = ast.parse(textwrap.dedent(inspect.getsource(resolve_input_dtype)))
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)
        if (
            func.body
            and isinstance(func.body[0], ast.Expr)
            and isinstance(func.body[0].value, ast.Constant)
        ):
            func.body = func.body[1:]  # drop the docstring
        code = ast.unparse(func)

        assert "BUILTIN_INPUT_DTYPES" in code
        assert '== "fcnet"' not in code
        assert "'fcnet'" not in code

    def test_only_a_genuinely_differing_model_declares(self):
        """A registry listing every builtin would be a second place to look
        up every model's dtype. Only `fcnet` differs from the task
        contract, so only `fcnet` appears."""
        assert set(BUILTIN_INPUT_DTYPES) == {"fcnet"}
        for model_type in BUILTIN_OUTPUT_TYPES:
            if model_type == "fcnet":
                continue
            assert model_input_admissibility(model_type, TIDMAD) is TIDMAD.input.dtype


class TestRegimeA:
    """A caller predating the contract must not be broken."""

    def test_no_contract_keeps_each_sites_historical_dtype(self):
        assert resolve_input_dtype("punet", None, site_preference=TRAINING_SITE_DTYPE) is (
            torch.int32
        )
        assert resolve_input_dtype("punet", None, site_preference=INFERENCE_SITE_DTYPE) is (
            torch.int64
        )

    def test_no_contract_still_honours_a_models_own_declaration(self):
        """`fcnet` gets float32 even with no contract in sight — the
        declaration is the model's, not the task's."""
        assert resolve_input_dtype("fcnet", None, site_preference=TRAINING_SITE_DTYPE) is (
            torch.float32
        )

    def test_no_tidmad_contract_is_fabricated(self):
        """§21 — the Regime-A path must not invent a contract. Its source
        touches no task config and no shipped literal."""
        source = inspect.getsource(resolve_input_dtype)
        assert "load_task_config" not in source
        assert "256" not in source


class TestTransport:
    """The contract crosses the real subprocess boundary (§16, no new IPC)."""

    def test_both_engines_accept_the_flag(self):
        for module in (tes, inf):
            assert "--model_io_json" in inspect.getsource(module)

    def test_the_flag_uses_the_established_config_file_mechanism(self):
        """Mirrors `--dataset_profile_json` rather than inventing a channel."""
        source = inspect.getsource(tes)
        assert "--dataset_profile_json" in source
        assert "load_model_io_contract(args.model_io_json)" in source

    def test_a_supplied_but_broken_contract_fails_closed(self, tmp_path):
        """The sharp half: never a silent fallback to a fabricated contract."""
        broken = tmp_path / "broken.json"
        broken.write_text("{ not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_model_io_contract(str(broken))

        invalid = tmp_path / "invalid.json"
        invalid.write_text('{"input": {"axes": []}}')
        with pytest.raises(ValueError, match="schema-invalid"):
            load_model_io_contract(str(invalid))

        with pytest.raises(ValueError, match="unreadable"):
            load_model_io_contract(str(tmp_path / "absent.json"))

    def test_a_contract_round_trips_through_the_transport(self, tmp_path):
        """Serialize exactly as the parent does, load exactly as the child
        does, and the resolved dtype must be unchanged."""
        import json

        path = tmp_path / "model_io.json"
        path.write_text(json.dumps(TIDMAD.model_dump(mode="json")))
        loaded = load_model_io_contract(str(path))
        assert loaded == TIDMAD
        assert resolve_input_dtype(
            "punet", loaded, site_preference=TRAINING_SITE_DTYPE
        ) is resolve_input_dtype("punet", TIDMAD, site_preference=TRAINING_SITE_DTYPE)
