"""Step 05c — C7: the Stage-B rung and the structural no-inlined-authority guard.

Design: ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` §5, C7, §3.2a.

**One axis: deliverable naming/transport.** Under the TIDMAD profile, with a
renamed template supplied as ONE injected runtime naming, every owned seam
must resolve names exclusively through it. Nothing else varies — the dataset
profile, the encoding, the attrs, cleanup policy, the metric and the scorer
are all held fixed.

**What this rung deliberately does NOT claim** (§3.2a, Option A). The renamed
template does **not** cross the real subprocess, and it cannot: a template is
a frozen compatibility literal, not a derivable fact, and 05c adds no
transport for it. The rung supplies the renamed naming **in-process at the
owned seams**; Checkpoint C separately proves the *shipped default* spec is
reconstructed across the real boundary. Claiming more here would be an
overclaim the design explicitly forbids.

**Scorer-side literals are out of scope**, explicitly. A "no ``abra_*``
anywhere" assertion is unsatisfiable at Step 05 and would be a test-design
error: ``denoising_score_single.py`` legitimately keeps its literals until
Step 06.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from execute_tools.deliverable_spec import DeliverableNaming, default_deliverable_naming

_REPO_ROOT = Path(__file__).resolve().parents[3]

RENAMED = DeliverableNaming(prefix="step05c_stage_b")

IDENTIFIERS = {
    "model_type": "wavenet",
    "run_name": "stage_b_run",
    "exp_id": "wavenet_stage_b_run_001",
    "file_index": 3,
}

# Every production CONSUMER the §0 census assigns to 05c. The structural guard
# sweeps exactly these — the point is that it also covers a site that does not
# exist yet. ``deliverable_spec.py`` is deliberately absent: it is the
# declaration, not a consumer, and it is checked separately for holding the
# literal exactly ONCE.
OWNED_PRODUCTION_FILES = (
    "execute_tools/inference_single.py",
    "execute_tools/array2h5.py",
    "core/sandbox_executor.py",
    "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
    "scripts/run_comparison.py",
    "scripts/finalize_recovered_diagnostic_round.py",
    "scripts/pregate_runtime_control_validation.py",
    "scripts/v18_wave_summary.py",
)

# Outside the rung by design: Step 06 owns the scorer, and the historical
# readers must keep matching artifacts already on disk.
OUT_OF_RUNG_FILES = (
    "execute_tools/denoising_score_single.py",
    "scripts/score_tidmad_official_banded.py",
    "scripts/score_tidmad_official_wavenet.py",
)

TIDMAD_PREFIX = "abra_validation_denoised"


def _executed_string_constants(path: Path) -> list[str]:
    """String literals the module RUNS — docstrings excluded.

    f-string segments are ``Constant`` nodes inside a ``JoinedStr``, so an
    inlined ``f"abra_validation_denoised_{m}_…"`` is caught by its prefix
    segment. Docstrings are excluded because several of these modules
    legitimately document the artifact pattern in operator-facing prose, and
    banning the token there would be vacuous.
    """
    tree = ast.parse(path.read_text())
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


# ---------------------------------------------------------------------------
# The structural guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relative", OWNED_PRODUCTION_FILES)
def test_no_owned_surface_executes_an_inlined_deliverable_authority(relative):
    """No owned production file runs its own copy of the template.

    This is the assertion no value-level mutation can replace, and the reason
    it exists is precise: a mutation proves that a **known** site is
    load-bearing, but it cannot see a site that does not exist yet. A future
    commit adding an eighth consumer with an inlined f-string would leave
    every behavioural test in this PR green — and would reintroduce failure
    class 1 the moment the template changed.
    """
    inlined = [s for s in _executed_string_constants(_REPO_ROOT / relative) if TIDMAD_PREFIX in s]

    assert inlined == [], (
        f"{relative} executes an inlined deliverable-template authority: {inlined}. "
        f"Resolve it through the DeliverableSpec instead."
    )


def test_the_template_is_declared_exactly_once():
    """The stem lives in ONE executed constant, in the declaration.

    The other half of the guard above, and the property the whole contract
    reduces to: the template is declared once and consumed everywhere. Two
    declarations inside the spec module would satisfy the consumer sweep
    perfectly while reintroducing the drift 05c removed — a rename would move
    one and not the other.
    """
    declarations = [
        s
        for s in _executed_string_constants(_REPO_ROOT / "execute_tools" / "deliverable_spec.py")
        if TIDMAD_PREFIX in s
    ]

    assert declarations == [TIDMAD_PREFIX]


@pytest.mark.parametrize("relative", OUT_OF_RUNG_FILES)
def test_the_out_of_rung_surfaces_still_hold_their_literals(relative):
    """The scorer and the historical readers are OUTSIDE the rung.

    Stated as an assertion rather than as prose so nobody mistakes the guard
    above for "no ``abra_*`` anywhere". That claim is unsatisfiable at Step 05
    and would be a test-design error: the scorer is Step 06's surface, and the
    official-paper scripts must keep matching files already on disk. If this
    ever goes red, someone has widened 05c's scope.
    """
    assert TIDMAD_PREFIX in (_REPO_ROOT / relative).read_text()


# ---------------------------------------------------------------------------
# The rung — one axis, all owned seams move together
# ---------------------------------------------------------------------------


def test_every_owned_seam_moves_together_under_one_renamed_naming(tmp_path):
    """ONE renamed naming, and every owned seam follows it.

    The seams, and the production consumer each one stands for:

    * ``name`` — the three producer constructions in ``inference_single``
    * ``unqualified_name`` — the legacy fix-mode producer
    * the path builder — what the scorer and the HealthGate peeks open
    * ``experiment_glob`` — ``--cleanup_denoised``
    * ``attempt_glob`` — the watchdog's partial-artifact cleanup
    * ``any_glob`` + ``file_index_of`` — the workspace auditor
    * the launcher's baseline path — ``run_comparison``

    Asserted in one test, on one axis, because that is the property: they
    share an authority. Seven separate tests would each pass while the seams
    drifted apart, which is exactly the pre-05c situation.
    """
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _build_denoised_filename,
    )

    renamed_name = RENAMED.name(**IDENTIFIERS)
    resolved = {
        "producer_qualified": renamed_name,
        "producer_fix_mode": RENAMED.unqualified_name(
            model_type=IDENTIFIERS["model_type"], file_index=IDENTIFIERS["file_index"]
        ),
        "path_builder": _build_denoised_filename(
            **IDENTIFIERS, base_dir=str(tmp_path), naming=RENAMED
        ),
        "cleanup_experiment": RENAMED.experiment_glob(exp_id=IDENTIFIERS["exp_id"]),
        "cleanup_attempt": RENAMED.attempt_glob(
            model_type=IDENTIFIERS["model_type"],
            run_name=IDENTIFIERS["run_name"],
            exp_id=IDENTIFIERS["exp_id"],
        ),
        "auditor_glob": RENAMED.any_glob(),
    }

    # Every seam moved...
    for seam, value in resolved.items():
        assert "step05c_stage_b" in value, f"{seam} did not follow the renamed naming"
        assert TIDMAD_PREFIX not in value, f"{seam} still resolves the TIDMAD template"

    # ...and the auditor's index parse inverts the renamed producer name,
    # which is what proves the glob and the parse are one authority and not
    # two that happen to agree under TIDMAD.
    assert RENAMED.file_index_of(renamed_name) == IDENTIFIERS["file_index"]
    assert RENAMED.file_index_of(default_deliverable_naming().name(**IDENTIFIERS)) is None


def test_the_rung_does_not_fire_on_the_legitimate_single_spec_binding():
    """The negative case: with the SHIPPED naming, every seam resolves TIDMAD.

    Without this the rung would pass for a trivial reason — a seam that
    returned the renamed value unconditionally, or one that returned an empty
    string, would satisfy every "renamed" assertion above. This pins that the
    same seams still produce the production names.
    """
    shipped = default_deliverable_naming()

    assert shipped.name(**IDENTIFIERS).startswith(TIDMAD_PREFIX)
    assert shipped.experiment_glob(exp_id=IDENTIFIERS["exp_id"]).startswith(TIDMAD_PREFIX)
    assert shipped.file_index_of(shipped.name(**IDENTIFIERS)) == IDENTIFIERS["file_index"]


def test_only_the_naming_axis_moves_under_a_rename():
    """A renamed naming changes NO storage fact.

    One axis means one axis. If renaming a deliverable also moved the channel
    groups, the storage dtype or the value offset, the rung would be varying
    three things and proving none of them — and a rename would silently
    rewrite the persisted representation.
    """
    from execute_tools.dataset_config import resolve_dataset_profile
    from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec

    shipped = derive_tidmad_deliverable_spec(resolve_dataset_profile())
    renamed = shipped.model_copy(update={"naming": RENAMED})

    assert renamed.storage == shipped.storage
    assert renamed.naming != shipped.naming
