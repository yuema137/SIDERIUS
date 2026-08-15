"""Step 05c — C3: the three PRODUCER name constructions resolve through the spec.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` C3, §3.2a.

Producer and consumer now share one authority. The three constructions live
inside ``inference_single.main()`` — a function that loads a checkpoint, builds
a model and opens HDF5 — so they cannot be called in isolation. Their evidence
is therefore split deliberately, and the split is stated rather than glossed:

* **value** — C0/C1 already pin that the spec resolves exactly the names the
  inlined literals built;
* **structure** — asserted here, by AST over the real module, in the idiom
  ``test_inference_single.py`` already uses for this file;
* **behaviour** — Checkpoint C (a real spawn writing a real artifact) and
  Gate 2.

A structural assertion is not a weaker value assertion. It catches a site
re-inlining the template, which no value check can, because a value check does
not know the site exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec
from tests.unit.execute_tools.test_step05c_c0_deliverable_baseline import (
    GOLDEN_EXP_ID,
    GOLDEN_FILE_INDEX,
    GOLDEN_FIX_MODE_NAME,
    GOLDEN_MODEL_TYPE,
    GOLDEN_RUN_NAME,
    GOLDEN_SAMPLE_SET_NAME,
)

_INFERENCE_SOURCE = Path(__file__).resolve().parents[3] / "execute_tools" / "inference_single.py"


def _source() -> str:
    return _INFERENCE_SOURCE.read_text()


def _main_function() -> ast.FunctionDef:
    for node in ast.parse(_source()).body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("inference_single.main() not found")


def test_no_deliverable_template_is_executed_in_the_producer():
    """No executable ``abra_validation_denoised`` literal remains.

    Scoped to executed code, not to the file: the module legitimately keeps
    ``abra_validation_0000.h5`` in a memory-incident comment (``:888``), and
    the RAW INPUT name — ``profile_dataset.validation_file_name(file_index)``
    — is Step 02's authority and is explicitly out of scope. Banning the token
    everywhere would either be vacuous or force a pointless comment edit; what
    matters is that nothing *runs* a second copy of the template.
    """
    executed_literals = [
        node.value
        for node in ast.walk(ast.parse(_source()))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "abra_validation_denoised" in node.value
    ]

    assert executed_literals == [], (
        f"an inlined deliverable template survived in the producer: {executed_literals}"
    )


def test_the_input_filename_authority_is_untouched():
    """The RAW validation input still resolves through the Step-02 profile.

    ``inference_single.py:641`` reads `validation_file_name`, which is the
    Input Dataset Contract's authority — a different contract from the one
    05c introduces. If C3 had "helpfully" routed it through the deliverable
    spec, inference would start reading files that do not exist while every
    deliverable-side assertion stayed green.
    """
    assert "profile_dataset.validation_file_name(file_index)" in _source()


def test_all_three_producer_names_resolve_through_the_spec():
    """Each construction calls a naming accessor — and the fix-mode branch
    calls the UNQUALIFIED one.

    The two shapes are not interchangeable: ``mode == "fix"`` omits run_name
    and exp_id. Collapsing them onto one accessor would rename every fix-mode
    artifact, and no value-level test of the qualified name would notice.
    """
    accessors = [
        node.func.attr
        for node in ast.walk(_main_function())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"name", "unqualified_name"}
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "naming"
    ]

    assert sorted(accessors) == ["name", "name", "unqualified_name"], (
        f"expected three spec-resolved producer names (two qualified, one "
        f"fix-mode); found {accessors}"
    )


def test_the_child_reconstructs_the_spec_and_adds_no_second_resolution():
    """The child derives ONCE, from the profile it was given.

    §3.2a's frozen acceptance has two halves and both are asserted:

    * the child calls ``derive_tidmad_deliverable_spec`` — it does not receive
      a serialized spec and does not rebuild the template itself;
    * it adds **no** ``resolve_dataset_profile()`` call. Exactly one remains,
      the pre-existing legacy adapter in the ``else`` branch at ``:339`` for a
      caller that never heard of ``--dataset_profile_json``. A second one
      would be an ambient re-resolution that could silently disagree with the
      transported profile — the defect Steps 02b/05a/05b removed elsewhere.
    """
    tree = ast.parse(_source())

    derivations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "derive_tidmad_deliverable_spec"
    ]
    ambient = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "resolve_dataset_profile"
    ]

    assert len(derivations) == 1, "the child must derive the spec exactly once"
    assert len(ambient) == 1, (
        f"expected exactly one resolve_dataset_profile() — the pre-existing "
        f"legacy adapter at :339 — found {len(ambient)}"
    )


@pytest.mark.parametrize(
    ("accessor", "kwargs", "expected"),
    [
        (
            "name",
            {
                "model_type": GOLDEN_MODEL_TYPE,
                "run_name": GOLDEN_RUN_NAME,
                "exp_id": GOLDEN_EXP_ID,
                "file_index": GOLDEN_FILE_INDEX,
            },
            GOLDEN_SAMPLE_SET_NAME,
        ),
        (
            "unqualified_name",
            {"model_type": GOLDEN_MODEL_TYPE, "file_index": GOLDEN_FILE_INDEX},
            GOLDEN_FIX_MODE_NAME,
        ),
    ],
    ids=["qualified", "fix_mode"],
)
def test_the_reconstructed_spec_resolves_the_c0_filename_set(accessor, kwargs, expected):
    """A spec derived the way the CHILD derives it resolves the C0 names.

    C1 asserted this for ``default_deliverable_naming()``; this asserts it for
    the value ``derive_tidmad_deliverable_spec(dataset_profile)`` actually
    produces, which is what the migrated producer calls. If the derivation
    ever stopped composing the shipped naming — say by keying it off the
    profile — the two would diverge and every artifact would be renamed.
    """
    spec = derive_tidmad_deliverable_spec(resolve_dataset_profile())

    assert getattr(spec.naming, accessor)(**kwargs) == expected
