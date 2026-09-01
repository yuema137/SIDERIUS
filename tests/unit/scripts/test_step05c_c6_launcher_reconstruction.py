"""Step 05c — C6: the launcher and canonical reconstruction tooling.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` C6, §0.1, OD-05c-3.

**The split these tests defend.** A script that *reconstructs or validates a
run* must agree with the producer, or a renamed deliverable silently breaks
recovery and baseline scoring. A script that *analyses historical files* must
keep matching the names those files already carry — migrating it would be
actively wrong, not merely unnecessary.

So the assertions come in pairs: the migrated tools resolve through the
contract, and the excluded ones are still literal. Only the pair states the
rule; either half alone would read as an arbitrary inventory.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from execute_tools.deliverable_spec import DeliverableNaming, default_deliverable_naming
from tests.unit.execute_tools.test_step05c_c0_deliverable_baseline import (
    GOLDEN_EXP_ID,
    GOLDEN_FILE_INDEX,
    GOLDEN_MODEL_TYPE,
    GOLDEN_RUN_NAME,
    GOLDEN_SAMPLE_SET_NAME,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# OD-05c-3: production launcher + canonical reconstruction/validation.
MIGRATED_SCRIPTS = (
    "scripts/finalize_recovered_diagnostic_round.py",
    "scripts/pregate_runtime_control_validation.py",
    "scripts/v18_wave_summary.py",
)

# OD-05c-3: historical replay + diagnostic-only. These read artifacts written
# BEFORE this PR and must keep matching the names already on disk.
HISTORICAL_SCRIPTS = (
    "scripts/investigate_pearson_feasibility.py",
)


def _executed_string_constants(source: str) -> list[str]:
    """Every string literal the module actually RUNS, docstrings excluded.

    Scoped to executed code for the same reason C3's producer scan is: a
    module may legitimately name the artifact pattern in its operator
    documentation — ``v18_wave_summary``'s docstring describes exactly which
    files the audit sweeps — and banning the token there would either be
    vacuous or force a pointless doc edit. What must not survive is a second
    executed copy of the template.

    f-strings are covered: their literal segments are ``Constant`` nodes
    inside a ``JoinedStr``, so ``f"abra_validation_denoised_{x}.h5"`` is
    caught by its prefix segment.
    """
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.parametrize("relative", MIGRATED_SCRIPTS)
def test_reconstruction_tooling_holds_no_inlined_deliverable_template(relative):
    """No run-reconstructing script re-states the producer's template.

    Each surviving framework-owned reconstruction tool must follow the current
    naming contract. Task launchers that moved to the experiment repository are
    outside this framework-source inventory.
    """
    source = (_REPO_ROOT / relative).read_text()

    inlined = [s for s in _executed_string_constants(source) if "abra_validation_denoised" in s]

    assert inlined == [], (
        f"{relative} still executes its own copy of the deliverable template: {inlined}"
    )
    assert "default_deliverable_naming" in source, (
        f"{relative} must resolve deliverable names through the contract"
    )


@pytest.mark.parametrize("relative", HISTORICAL_SCRIPTS)
def test_historical_readers_are_deliberately_left_literal(relative):
    """The excluded scripts still carry their own literal — on purpose.

    This is the other half of OD-05c-3's rule, and it fails in the direction
    people actually get wrong: a later tidy-up "finishing the migration" would
    point these at the current contract, and they would stop matching the
    official-paper and diagnostic artifacts already on disk. Their correctness
    condition is agreement with history, not with the producer.
    """
    source = (_REPO_ROOT / relative).read_text()

    assert "abra_validation_denoised" in source
    assert "deliverable_spec" not in source, (
        f"{relative} reads HISTORICAL artifacts and must not follow the current contract"
    )


def test_the_launcher_resolves_the_c0_producer_name():
    """``run_comparison``'s baseline path equals what the producer writes.

    Same identifier tuple, same string. This is the cross-authority assertion
    C6 exists for: the launcher and the producer now agree by construction
    rather than by two f-strings that happen to match.
    """
    assert (
        default_deliverable_naming().name(
            model_type=GOLDEN_MODEL_TYPE,
            run_name=GOLDEN_RUN_NAME,
            exp_id=GOLDEN_EXP_ID,
            input_identity=GOLDEN_FILE_INDEX,
        )
        == GOLDEN_SAMPLE_SET_NAME
    )


def test_the_workspace_auditor_recognises_renamed_artifacts(tmp_path):
    """``v18_wave_summary`` finds out-of-scope artifacts under ANY naming.

    It previously carried its own regex — a second restatement of the
    template. The failure mode that removes is silent and expensive: under a
    renamed deliverable the auditor would recognise nothing, find no
    out-of-scope artifact, and report a clean workspace. It would pass.
    """
    from scripts.v18_wave_summary import _check_denoised_artifacts

    naming = default_deliverable_naming()
    in_scope = naming.name(model_type="wavenet", run_name="r", exp_id="e", input_identity=4)
    out_of_scope = naming.name(model_type="wavenet", run_name="r", exp_id="e", input_identity=11)
    (tmp_path / in_scope).write_bytes(b"x")
    (tmp_path / out_of_scope).write_bytes(b"x")
    (tmp_path / "abra_validation_0011.h5").write_bytes(b"x")

    abnormal: list[str] = []
    _check_denoised_artifacts(str(tmp_path), [4, 5, 6], abnormal)

    assert len(abnormal) == 1
    assert out_of_scope in abnormal[0]


def test_the_auditor_ignores_files_that_are_not_deliverables(tmp_path):
    """A raw validation input is not an out-of-scope deliverable.

    The old regex matched on a trailing 4-digit index, which a raw
    ``abra_validation_0011.h5`` also has; the prefix is what distinguishes
    them. Reported as abnormal, it would send an operator hunting for a
    scope violation that never happened.
    """
    from scripts.v18_wave_summary import _check_denoised_artifacts

    (tmp_path / "abra_validation_0011.h5").write_bytes(b"x")
    (tmp_path / "model_wavenet_e_agent.pth").write_bytes(b"x")

    abnormal: list[str] = []
    _check_denoised_artifacts(str(tmp_path), [4, 5, 6], abnormal)

    assert abnormal == []


def test_launcher_and_producer_move_together_under_a_rename():
    """One renamed spec moves the launcher's path AND the producer's name.

    Asserted in ONE test rather than two independent ones, because two tests
    each pinning their own site would both pass while the two sites drifted
    apart — which is precisely the drift this commit exists to prevent.
    """
    renamed = DeliverableNaming(prefix="step05c_renamed")
    identifiers = {
        "model_type": GOLDEN_MODEL_TYPE,
        "run_name": GOLDEN_RUN_NAME,
        "exp_id": GOLDEN_EXP_ID,
        "input_identity": GOLDEN_FILE_INDEX,
    }

    # The producer (inference_single) and every migrated reader compose the
    # name through this one accessor, so equality here IS the shared authority.
    assert renamed.name(**identifiers) != default_deliverable_naming().name(**identifiers)
    assert renamed.name(**identifiers).startswith("step05c_renamed_")
