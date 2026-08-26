"""Step 12 / PR-12d — D0: structural baselines and INVERTED defect guards.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §M / D0.

D0 changes **no production file**. It records the state every later seam
flips, so a seam commit turns a NAMED guard RED instead of asserting progress
against nothing. A baseline captured after a change is not a baseline — which
is why this is the first commit.

Inverted guards
---------------

Every ``TestInvertedGuardB*`` / ``TestInvertedGuardA5`` class asserts that a
defect in the §A.3a register is **PRESENT on today's source**. Each names its
flip owner, and **each fails once the defect is repaired** — that is the
point. R-11-10 applies: when the fix lands, the guard either becomes the
permanent owner of the corrected property or is deleted, never both.

=========  ====================================================  ===========
guard      defect asserted PRESENT                               flips in
=========  ====================================================  ===========
A5         no run-scoped plugin authority: the model plugin var  DP (seam P)
           is ASSIGNED (replace) at spawn while PYTHONPATH is
           joined; no operator/chain surface sets it; the doc
           seven production files cite does not exist; model
           plugins carry no content-identity provenance
B0         no shipped Pets/DAVIS composition manifest, and the   D5/D6,
           only compositions that name them are self-declared    closed at
           non-executable fixtures with fabricated TIDMAD-       CHECKPOINT B
           shaped topology
B1         the composition authority cannot hand a task its      D1 (seam A)
           scope authority — ``factory()`` takes no arguments,
           ``_load_symbol`` reads no ``config``, and the
           unknown-key refusal is TOP-LEVEL only
B2         ``build_sample_set`` decodes TIDMAD topology, and is  D2 (seam B)
           called unconditionally for every trial/formal round
B3         five DIRECT ``tidmad_topology()`` reads on the        D2 (seam B)
           composed attempt path
B4         the scoring route is decided by ANCHOR-MAP PRESENCE,  D4b (seam D)
           so a task with no anchor artifact takes the legacy
           single-file branch
B5         the production scoring API is TIDMAD-shaped and both  D4b (seam D)
           contrast metrics reject it (executed)
B6         scope transport reaches the TRAINING child only       D3 (seam C)
B7         the inference child defines the framework contract    D3 (seam C)
           as TIDMAD's SampleSet iteration
B8         the scoring child's TIDMAD assumptions sit at MODULE  D4a/D4b
           level, with an INTEGER deliverable key
B9         the training preflight opens TIDMAD HDF5              D3 (seam C)
           unconditionally, and ``validation_requested_rows``
           has no transport
B10        ``DeliverableNaming`` mandates a zero-padded          D4b (seam E)
           ``file_index`` in every accessor
B11        TRANSITIVE — ``HyperparamTuningAgent.run`` derives    D2 (seam B)
           the TIDMAD deliverable spec unconditionally, which
           reaches ``tidmad_topology`` four times
=========  ====================================================  ===========

What is deliberately NOT inverted
---------------------------------

``TestPreservedInvariants`` asserts rules 12d must **keep**: TIDMAD's
composition fingerprint, the legacy argv surface of all three children, and
the cross-task scope pairing rule. A seam that "fixes" one of these away is
the C-P56-1 failure class.

``TestStructuralBaseline`` records §E's pre-values so D-FINAL can perform the
mandatory comparison. It is a tripwire on GROWTH and silent on shrinkage,
which is the direction the rule wants.

Why several guards assert SOURCE and not behaviour
--------------------------------------------------

B3, B6, B7, B8, B9 and B11 sit inside orchestration functions of 26-68 branch
nodes, or at a child's module level. Driving them behaviourally would require
standing up the surrounding orchestrator or a real subprocess, which is Gate-2
class work for a property whose defect IS its source shape. Where a defect is
reachable in-process it is asserted BEHAVIOURALLY instead — B1, B2, B5 and B11
all execute the real production code and observe the real refusal.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
from typing import ClassVar
from unittest.mock import MagicMock, mock_open, patch

import pytest

from core.sandbox_executor import TidmadSandbox
from core.subprocess_env import PLUGIN_DIRS_ENV_VAR, subprocess_env
from execute_tools.dataset_config import DatasetProfile, tidmad_topology
from execute_tools.evaluation_metric import (
    AccuracyMetric,
    GlobalMseMetric,
    metric_spec_from_declaration,
)
from execute_tools.task_data_path import ScopeBuildRequest
from tests.unit.guardrails.test_step12_pr12a_c0_defect_baselines import (
    _qualified_functions,
    measure,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

EXP_ID = "pr12d_d0_exp"
RUN_NAME = "pr12d_d0_run"
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
BASELINE_SAMPLE_SET = {0: [1, 2], 3: [0, 4]}


# ======================================================================
# Shared helpers
# ======================================================================


def _source(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _tree(rel: str) -> ast.Module:
    return ast.parse(_source(rel))


def _direct_calls(rel: str, *names: str) -> list[int]:
    """Line numbers of every DIRECT call to any of ``names`` in ``rel``."""
    return sorted(
        node.lineno
        for node in ast.walk(_tree(rel))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in names
    )


def _options(cmd: list[str]) -> tuple[str, ...]:
    """Option tokens of an argv, in order, de-duplicated by first sight.

    Same convention as the Step-11 C0 and PR-12bc B0 baselines: a token that
    merely LOOKS like a flag (a negative number) is excluded by requiring a
    non-digit after the dashes.
    """
    seen: list[str] = []
    for tok in cmd:
        if tok.startswith("-") and not tok.lstrip("-")[:1].isdigit() and tok not in seen:
            seen.append(tok)
    return tuple(seen)


def honest_generic_profile() -> DatasetProfile:
    """A Q-12-4-conformant profile that declares NO TIDMAD topology.

    This is what D5/D6 will ship, in miniature: the three REQUIRED generic
    identity fields plus an opaque task-owned ``topology`` the framework
    never interprets. Several guards below use it to prove that today's
    generic path dies on exactly this shape — which is the whole finding.
    """
    return DatasetProfile(
        partition_count=3,
        topology={"kind": "d0_contrast_shaped_v1", "num_classes": 37},
        anchor_selection_files=[0],
        health_peek_files=[0],
    )


@pytest.fixture
def sandbox(tmp_path):
    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)


# ======================================================================
# A5 — seam P — RETIRED AT DP
# ======================================================================
#
# R-11-10: when a guard's fix lands, the guard either becomes the permanent
# owner of the corrected property or is deleted — never both. All five A5
# inverted guards are retired here, and their POSITIVE contracts live in
# ``tests/unit/ml_models/test_step12_pr12d_dp_plugin_binding.py``:
#
#   assign-vs-union asymmetry   -> TestUnionPropagation (falsifier 1)
#   no operator/run surface     -> TestDeclaredModelPlugins (the manifest
#                                  section IS the surface, so "no launcher
#                                  names the env var" stopped being a defect
#                                  and became an implementation detail)
#   the missing cited document  -> the docs the D-FINAL sync writes
#   no content identity         -> TestPluginProvenance
#   the loss-family precedent   -> consumed: `union_plugin_roots` is now the
#                                  ONE merge authority both families' shape
#                                  agrees with, pinned by TestUnionPropagation
#
# One fact the retired class recorded is kept, because it stays true and DP
# relies on it: `_resolve_loss_dirs` unions while the pre-DP
# `_resolve_plugin_dirs` did not. That asymmetry is now gone.

# ======================================================================
# B0 — no shipped contrast composition manifest
# ======================================================================


class TestInvertedGuardB0:
    """RETIRED at D5 + D6 — BOTH halves flipped, in their own commits.

    B0's structural half is now closed: both packs ship a shipped composition
    manifest, a `declared/dataset_profile.json` and a `declared/task_config.yaml`,
    none of the fabricated TIDMAD-shaped values survive, and every
    Gate-consumed manifest is checksum-pinned.

    **B0 itself still closes at CHECKPOINT B**, not here. What this class
    witnessed was the ABSENCE of the artifacts; what Checkpoint B must witness
    is the three-task matrix green ON those artifacts. Retiring this class
    does not discharge that.

    Positive ownership moved, per R-11-10, to the two pack modules:
    ``tests/unit/examples/test_step12_pr12d_d5_pets_declarations.py`` and
    ``tests/unit/examples/test_step12_pr12d_d6_davis_declarations.py``. Each
    asserts its own pack field-by-field — the shipped declaration AND the
    fixture — rather than the "looks generic" shape an inverted guard can only
    approximate.

    Two assertions are KEPT below rather than retired, because each names a
    property that must stay true rather than a defect that is now gone.
    """

    def test_the_shipped_composition_manifests_are_exactly_the_landed_set(self):
        """An exact set, not a membership test.

        Fails when a manifest is added or removed without this line moving —
        which is the point: a shipped composition manifest is an OPERATOR
        ENTRYPOINT, and one appearing unannounced is exactly what B0 watched
        for.

        DECLARED DELTA (arXiv-readiness S5, announced — the guard fired at
        final integration exactly as designed): ``quickstart.yaml`` joined
        the set. It is the collaborator-onboarding pack's entrypoint
        (`examples/quickstart/`), and it is ALSO what legitimizes the pack's
        committed ``declared/task_config.yaml`` under the landed governance
        guard (a) — the manifest's ``task_config.config:`` binding is the
        exemption mechanism 12d re-scoped that guard to. A FIFTH entry still
        needs its own announcement here.
        """
        shipped = sorted(p.name for p in (REPO_ROOT / "configs" / "task_composition").iterdir())
        assert shipped == ["davis.yaml", "pets.yaml", "quickstart.yaml", "tidmad.yaml"]

    def test_neither_pack_keeps_a_SECOND_dataset_profile_in_its_fixture(self):
        """The deletion, asserted — and it is the deletion that matters.

        Re-authoring the fabricated files in place would have left two
        profiles per pack free to drift. D5 deleted Pets' fixture profile
        outright so the fixture resolves the pack's own declaration; D6
        re-authored DAVIS' single fixture profile into the Q-12-4 shape. This
        fails if anyone re-creates a fixture-local Pets profile, which is the
        only way the drift could come back.
        """
        assert not (
            REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "pets" / "dataset_profile.json"
        ).exists()


# ======================================================================
# B1 — RETIRED AT D1
# ======================================================================
#
# R-11-10. The composition authority can now hand a task its own scope
# authority, so every B1 guard is retired and its POSITIVE contract lives in
# ``tests/unit/workflows/test_step12_pr12d_d1_task_instance_config.py``:
#
#   factory() called with nothing   -> TestConfiguredConstruction
#   `_load_symbol` reads no config  -> retired outright: `config:` is
#                                      deliberately NOT `_load_symbol`'s
#                                      business, so "it does not read it"
#                                      became an incidental fact
#   section unknown keys ignored    -> TestSectionKeyRefusal
#   the bare instance cannot build  -> KEPT, as a POSITIVE property: it is
#                                      the regime-A anchor ruling A1 relies
#                                      on, and it must stay true
#   configured constructions only
#   exist in a test                 -> TestProductionPathBuildsARealScope,
#                                      which asserts THROUGH the production
#                                      composition entry point (L4)

# ======================================================================
# B2 / B3 / B11 — RETIRED AT D2
# ======================================================================
#
# R-11-10. The composed attempt path no longer constructs TIDMAD facts while
# holding a bound task scope capability, so all three guard classes are
# retired and their POSITIVE contracts live in
# ``tests/unit/nodes/test_step12_pr12d_d2_scope_authority.py``:
#
#   B2  build_sample_set called unconditionally
#         -> TestConsumerSitesReadFacts::
#            test_the_sample_set_builder_is_reached_only_when_geometry_is_DECLARED
#            (and the builder's own fail-closed refusal is PRESERVED beside it,
#             because that refusal is what makes the guard necessary)
#   B3  five DIRECT decoders in the tuner package
#         -> TestConsumerSitesReadFacts, now asserting ZERO across NINE
#            modules rather than a recorded count across three
#   B11 the TRANSITIVE derivation at run():625
#         -> TestConsumerSitesReadFacts::
#            test_the_tuner_no_longer_derives_the_TIDMAD_deliverable_spec
#
# One brittleness worth recording rather than reproducing: B11's guard pinned
# the four `tidmad_topology` LINE NUMBERS in `deliverable_spec.py` (413-416).
# They moved to 446-449 for a reason that has nothing to do with the defect —
# a helper was added above them. The replacement asserts the CALL, never a
# line, which is the same lesson the Step-11 C0 module recorded about pinning
# line numbers in a tripwire.

# ======================================================================
# B4 / B5 — the scoring route and the scoring call convention
# ======================================================================


class TestInvertedGuardB4:
    """RETIRED at D4b (seam D) — the guard did its job and went RED.

    Both cases fired against the landed fix: the route no longer keys on
    ``anchor_map_data is not None``, and the ``else`` no longer claims to be
    "legacy single-file mode" — a description of a condition the code never
    tested, since ``anchor_map_data`` is only ATTEMPTED on a trial round.

    **The corrected property has an owner** (R-11-10), and it is not this
    file: ``tests/unit/execute_tools/test_step12_pr12d_d4b_scoring_closure.py``
    ``::TestScoringRouteIsNamed`` asserts all three routes by name, including
    the reachability check that the production branch dispatches on the route
    rather than on the anchor map. Keeping an inverted copy here would assert
    the defect is still present, which is now false.
    """


#: The EXACT keyword set ``TidmadSandbox.evaluate_metric`` passes today
#: (``core/sandbox_executor.py:2141-2150``). B5 is that this shape is
#: REQUIRED of every composed metric.
TIDMAD_SHAPED_SCORING_KWARGS = (
    "data_dir",
    "sample_set",
    "anchor_map",
    "s_max",
    "denoised_filename_fn",
    "raw_data_dir",
)


class TestInvertedGuardB5:
    """PRESERVED at D4b, and the reason is a correction to this guard's premise.

    D0 predicted B5 would flip. It did not, and that is the right outcome —
    the same shape B7 already recorded. The guard asserts that
    ``TidmadSandbox.evaluate_metric`` passes TIDMAD's six-keyword set and that
    a contrast metric rejects it. Both remain TRUE after D4b, because that
    handle IS TIDMAD's anchor-normalized route and must keep its semantics.

    What D4b actually closed is the BLOCKER the guard was describing: there is
    now a second route — the scoring child's ``_emit_task_owned_score`` —
    which passes only the three values the framework owns. The defect was
    never "TIDMAD-shaped code exists"; it was "the ONLY production scoring API
    is TIDMAD-shaped", and that is no longer true.

    So this stays green, as a PARITY anchor rather than an inverted guard: if
    a future change makes TIDMAD's own handle stop passing its own vocabulary,
    that is a TIDMAD regression and this catches it. The generic route's
    keyword contract is owned by
    ``test_step12_pr12d_d4b_scoring_closure.py::TestTheChildAsksTheDeclaredMetric``.
    """

    def test_the_production_handle_passes_the_tidmad_shaped_keyword_set(self):
        fn = _qualified_functions(REPO_ROOT / "core" / "sandbox_executor.py")[
            "TidmadSandbox.evaluate_metric"
        ]
        calls = [
            node
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "evaluate"
        ]
        assert len(calls) == 1
        passed = tuple(kw.arg for kw in calls[0].keywords if kw.arg)
        assert passed == TIDMAD_SHAPED_SCORING_KWARGS

    @pytest.mark.parametrize(
        ("metric_cls", "declaration"),
        [
            (AccuracyMetric, "examples/oxford_iiit_pet/declared/metric_accuracy.json"),
            (GlobalMseMetric, "examples/davis_future_prediction/declared/metric_mse.json"),
        ],
    )
    def test_a_contrast_metric_rejects_the_production_call(self, metric_cls, declaration, tmp_path):
        """The deliverable must EXIST or the scoreability contract refuses first.

        Recorded because the first reproduction attempt saw no ``TypeError``:
        ``evaluate`` runs ``check_scoreability`` BEFORE ``_compute``, so an
        absent deliverable short-circuits into a structured refusal and the
        keyword defect never surfaces. The guard therefore reaches the
        arithmetic, which is where the incompatibility lives.
        """
        deliverable = tmp_path / "deliverable.csv"
        deliverable.write_text("image_id,prediction\na,1\n", encoding="utf-8")
        metric = metric_cls(metric_spec_from_declaration(json.loads(_source(declaration))))
        with pytest.raises(TypeError, match="unexpected keyword argument 'data_dir'"):
            metric.evaluate(
                {0: str(deliverable)},
                data_dir=str(tmp_path),
                sample_set={0: [0]},
                anchor_map={},
                s_max=1.0,
                denoised_filename_fn=lambda _i: "x",
                raw_data_dir=str(tmp_path),
                profile=None,
            )

    def test_neither_contrast_metric_accepts_arbitrary_keywords(self):
        """The refusal is structural, not incidental: no ``**kwargs`` anywhere."""
        for cls in (AccuracyMetric, GlobalMseMetric):
            fn = _qualified_functions(REPO_ROOT / "execute_tools" / "evaluation_metric.py")[
                f"{cls.__name__}._compute"
            ]
            assert fn.args.kwarg is None
            assert {a.arg for a in fn.args.kwonlyargs} == {"predictions", "truth"}


# ======================================================================
# B6 / B7 / B9 — RETIRED AT D3
# ======================================================================
#
# R-11-10. The POSITIVE contracts live in
# ``tests/unit/execute_tools/test_step12_pr12d_d3_child_transport.py``:
#
#   B6 the emitter had ONE call site      -> TestTransportReachesTheInferenceChild,
#      and the other children never             which asserts TWO named holders and
#      mentioned a task scope                   ONE shared reader
#   B7 the inference child IS TIDMAD's    -> TestGenericIterationContract (driven
#      iteration                                over REAL Pets and DAVIS scopes) and
#                                              TestTidmadUntouched, which KEEPS the
#                                              TIDMAD assertions verbatim — its loop
#                                              survives as the TIDMAD adapter's
#                                              implementation, so those three
#                                              assertions changed OWNER, not meaning
#   B9 the preflight + the missing        -> TestValidationRowsDeclaration, incl. the
#      transport                                structural proof that the preflight is
#                                              unreachable without a SampleSet
#
# Worth recording: B7's three guards were never inverted in the usual sense.
# The SampleSet loop, `validation_file_name` and the 3-tuple write are all
# still there and MUST be — what changed is that they stopped being the
# framework's contract and became one adapter's implementation. A guard that
# asserts a preserved fact belongs with the preservation, not with the defect
# register.

# ======================================================================
# B8 — the scoring child's module-level TIDMAD assumptions
# ======================================================================


class TestInvertedGuardB8:
    """Flips in D4a (structure) then D4b (semantics)."""

    def test_the_child_now_has_a_function_for_its_logic_to_live_in(self):
        """RETIRED-AND-REPLACED at D4a — the POSITIVE half of B8.

        42 module-level statements meant the TIDMAD assumptions had nothing to
        be branched around. D4a gave them a function, changing NO behaviour
        (the PRE/POST oracle in
        ``tests/unit/execute_tools/test_step12_pr12d_d4a_scoring_restructure.py``
        is the evidence). The count is asserted as an UPPER BOUND rather than
        an equality, because what matters is that module import no longer
        executes the child — not that the number never moves again.
        """
        tree = _tree("execute_tools/denoising_score_single.py")
        executable = [
            node
            for node in tree.body
            if not isinstance(
                node,
                (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
        ]
        assert len(executable) <= 5, (
            f"the scoring child grew module-level execution again: "
            f"{[ast.unparse(n).split(chr(10))[0][:60] for n in executable]}"
        )
        names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert {"build_parser", "main"} <= names

    def test_the_tidmad_sample_set_construction_is_unguarded(self):
        """STILL RED-CAPABLE: D4a moved this statement, D4b removes the defect.

        Asserted STRUCTURALLY rather than as a source string. The literal form
        broke the moment D4a indented the statement into ``main`` — a
        behaviour-preserving move — which is exactly the brittleness the
        `test_step12_pr12a_c3_deliverable_pin` lesson names. What the guard
        must say is that the construction decodes TIDMAD topology and NOTHING
        guards it, and that survives being indented.
        """
        tree = _tree("execute_tools/denoising_score_single.py")
        assigns = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "sample_set"
        ]
        assert len(assigns) == 1
        body = ast.unparse(assigns[0])
        assert "tidmad_topology(dataset_profile)" in body
        assert "args.file_index" in body
        guards = [
            ast.unparse(node.test)
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and assigns[0] in list(ast.walk(node))
        ]
        assert guards == [], (
            f"DEFECT ASSERTED PRESENT: the TIDMAD SampleSet construction is "
            f"reached unconditionally; D4b is what guards or replaces it. "
            f"Enclosing guards found: {guards}"
        )

    def test_the_anchor_map_load_is_unguarded(self):
        src = _source("execute_tools/denoising_score_single.py")
        assert "anchor_data = load_anchor_map(args.anchor_map)" in src
        assert 's_max = float(anchor_data["s_max"])' in src

    def test_the_evaluation_payload_is_keyed_by_an_INTEGER_file_index(self):
        """Pets keys by ``image_id`` and DAVIS by ``"seq:start"``."""
        assert "_payload.get(args.file_index)" in _source("execute_tools/denoising_score_single.py")

    def test_the_metric_call_is_the_tidmad_shaped_one(self):
        src = _source("execute_tools/denoising_score_single.py")
        for kwarg in TIDMAD_SHAPED_SCORING_KWARGS:
            assert f"{kwarg}=" in src


# ======================================================================
# B10 — deliverable identity
# ======================================================================


class TestInvertedGuardB10:
    """RETIRED at D4b (seam E) — went RED on the NARROWING, as A4 required.

    ``DeliverableNaming.name`` / ``unqualified_name`` no longer take a
    ``file_index``; they take an opaque ``input_identity: int``, because what
    generic core holds is *which input this deliverable answers*, never an
    index in a filename. The annotation is still ``int`` and deliberately so —
    ``int | None`` is the widening A4 explicitly rejects.

    **Owner of the corrected property** (R-11-10):
    ``tests/unit/execute_tools/test_step12_pr12d_d4b_scoring_closure.py``
    ``::TestDeliverableNamingIsNarrowed``, which additionally owns **F-A4-1** —
    a composed run declaring no naming is REFUSED rather than silently handed
    TIDMAD's template — and pins the produced names byte-for-byte so the
    narrowing cannot move a filename.

    The third case here (*"the contrast packs own their names outright"*) was
    never inverted: it was A4's EVIDENCE that the fix is a narrowing. It moves
    with the property it describes, into that module's seam-E class.
    """


# ======================================================================
# PRESERVED — what 12d must NOT break
# ======================================================================

#: TIDMAD's shipped composition, at D0. Any seam that perturbs this changed
#: the science of the only task with real production evidence.
TIDMAD_COMPOSITION_FINGERPRINT = "9125bf587fea5bae1493800e9b50bafbb63164ff72ec1bfe3b08520ae1e72aac"

#: Composed-only flags that must never appear on a legacy child's argv.
FORBIDDEN_ON_LEGACY = (
    "--task_manifest",
    "--task_data_path_id",
    "--task_scope_ref",
    "--task_scope_digest",
    "--task_eval_scope_ref",
    "--task_eval_scope_digest",
)


class TestPreservedInvariants:
    """Not inverted. These are the parity anchors D-FINAL re-checks."""

    def test_the_tidmad_composition_fingerprint(self):
        from workflows.task_composition import compose_run_task_bindings

        composition = compose_run_task_bindings(
            str(REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml")
        )
        assert composition.semantic_fingerprint == TIDMAD_COMPOSITION_FINGERPRINT
        assert composition.task_data_path.task_data_path_id == "tidmad"
        assert composition.metric.spec.id == "tidmad_denoising_score"
        assert composition.metric.spec.direction == "higher"
        assert composition.dataset_profile.partition_count == 20
        assert composition.deliverable_naming is None

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_no_composed_only_flag_reaches_a_legacy_training_argv(self, mock_run, sandbox):
        def _side_effect(*_args, **_kwargs):
            os.makedirs(sandbox.dirs["models"], exist_ok=True)
            with open(os.path.join(sandbox.dirs["models"], f"_OK_{EXP_ID}"), "wb"):
                pass
            result = MagicMock()
            result.returncode = 0
            result.stdout = "done\n"
            result.stderr = ""
            return result, None

        mock_run.side_effect = _side_effect
        sandbox.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=BASELINE_SAMPLE_SET,
        )
        cmd = mock_run.call_args[0][0]
        assert [f for f in FORBIDDEN_ON_LEGACY if f in cmd] == []

    @patch("core.sandbox_executor._run_observed_subprocess")
    def test_no_composed_only_flag_reaches_a_legacy_inference_argv(self, mock_run, sandbox):
        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in (f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"):
            with open(os.path.join(cfg_dir, name), "w") as handle:
                json.dump({}, handle)
        open(os.path.join(sandbox.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth"), "w").close()
        result = MagicMock()
        result.returncode = 0
        result.stdout = "done\n"
        result.stderr = ""
        mock_run.return_value = (result, None)
        sandbox.execute_inference(
            EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, LOSS_CFG, sample_set=BASELINE_SAMPLE_SET
        )
        cmd = mock_run.call_args[0][0]
        assert [f for f in FORBIDDEN_ON_LEGACY if f in cmd] == []

    @patch("core.sandbox_executor.subprocess.run")
    def test_no_composed_only_flag_reaches_a_legacy_scoring_argv(self, mock_run, sandbox):
        """``--data_dir`` is the DELIVERABLE dir here (Step-11 C4), so it is
        excluded from the forbidden set rather than asserted absent."""
        result = MagicMock()
        result.returncode = 0
        result.stdout = "done\n"
        result.stderr = ""
        mock_run.return_value = result
        with (
            patch("builtins.open", mock_open(read_data=json.dumps({"denoising_score": 0.9}))),
            patch("os.path.exists", return_value=True),
            patch("os.remove"),
        ):
            sandbox.execute_scoring(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        cmd = mock_run.call_args[0][0]
        leaked = [f for f in FORBIDDEN_ON_LEGACY if f != "--data_dir" and f in cmd]
        assert leaked == []

    def test_the_cross_task_scope_pairing_rule_keeps_its_existing_owner(self):
        """12bc's rule: one task's scope is refused by another's implementation.

        D3 widens transport to two more children and must not soften it
        (falsifier 3). The rule is NOT re-asserted here — it already has one
        owner, ``test_step12_pr12bc_b0_baselines.py::
        TestPreservedCrossTaskPairingRule``, and a second copy would be the
        duplicate coverage §H forbids. What D0 owns is that the owner still
        exists, so a seam commit cannot quietly delete the guard instead of
        satisfying it.
        """
        owner = REPO_ROOT / "tests" / "unit" / "core" / "test_step12_pr12bc_b0_baselines.py"
        source = owner.read_text(encoding="utf-8")
        assert "class TestPreservedCrossTaskPairingRule:" in source
        assert "test_a_tidmad_scope_is_refused_by_the_pets_implementation" in source
        assert "test_a_foreign_scope_is_refused_by_the_tidmad_implementation" in source


# ======================================================================
# Structural baseline — D-FINAL compares against this
# ======================================================================

#: ``"<repo-relative path>::<qualified name>" -> (stmts, branch, loc, params)``
#: measured at D0 with the repository's own instrument. Matches §E exactly.
STRUCTURAL_BASELINE_12D: dict[str, tuple[int, int, int, int]] = {
    "execute_tools/inference_single.py::main": (225, 67, 677, 0),
    "execute_tools/train_engine_sandbox.py::run_experiment_streaming": (174, 62, 730, 19),
    (
        "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
        "::HyperparamTuningAgent.run"
    ): (254, 68, 1137, 2),
    "nodes/ml_hyperparameter_tune_agent/planning.py::prepare_attempt": (117, 32, 497, 7),
    "nodes/ml_hyperparameter_tune_agent/execution.py::run_inference_scoring_health": (
        112,
        26,
        488,
        6,
    ),
    "execute_tools/train_engine_sandbox.py::main": (96, 23, 360, 0),
    "core/sandbox_executor.py::TidmadSandbox.execute_training": (93, 39, 364, 15),
    "core/sandbox_executor.py::TidmadSandbox.execute_inference": (69, 28, 255, 9),
    "workflows/task_composition.py::_load_symbol": (35, 14, 95, 3),
    "execute_tools/sample_set_builder.py::build_sample_set": (28, 9, 101, 8),
    "core/sandbox_executor.py::TidmadSandbox.execute_scoring": (26, 10, 79, 7),
    "workflows/task_composition.py::_compose_task_data_path": (23, 11, 94, 2),
    "execute_tools/train_engine_sandbox.py::_preflight_validation_scope": (22, 6, 48, 4),
    # RELOCATED at D3 (seam C) beside the scope ABI it writes: the launch
    # consumer's own inherited file budget names that remedy (R-11-11), and a
    # second emitter in the same family made it the right home. Same body.
    "execute_tools/scope_artifact.py::task_scope_argv": (19, 4, 56, 3),
    "nodes/ml_hyperparameter_tune_agent/scope_acquisition.py::acquire_attempt_scopes": (
        13,
        6,
        104,
        12,
    ),
    "workflows/task_composition.py::resolve_child_task_data_path": (13, 3, 87, 3),
    # RELOCATED at D3 (seam C): the reader moved beside its writer in
    # `scope_artifact.py` when the inference child needed it too, so both
    # children import ONE implementation instead of copying it. Same
    # function, same body, public name — the row follows it rather than
    # being dropped, so the pre/post comparison stays meaningful.
    "execute_tools/scope_artifact.py::load_transported_scope": (11, 5, 46, 3),
    "core/sandbox_executor.py::TidmadSandbox.evaluate_metric": (9, 2, 73, 7),
    "execute_tools/dataset_config.py::tidmad_topology": (8, 5, 29, 1),
    # Surfaces the pre-freeze audit's seams added (§E, "recorded here so D0
    # cannot omit them"). Measured at D0 with the same instrument.
    "core/subprocess_env.py::subprocess_env": (12, 3, 36, 2),
    "ml_models/plugin_loader.py::_resolve_plugin_dirs": (6, 2, 19, 0),
    "ml_models/plugin_loader.py::extend_registries": (21, 7, 38, 2),
    "ml_models/plugin_loader.py::register_model_in_memory": (16, 3, 48, 1),
    "ml_models/loss_models_sandbox.py::get_criterion": (15, 7, 23, 2),
    "ml_models/loss_models_sandbox.py::_load_custom_loss": (11, 2, 59, 1),
    "execute_tools/training_history.py::stamp_comparability": (9, 3, 17, 1),
    "execute_tools/evaluation_metric.py::EvaluationMetric.evaluate": (7, 1, 23, 3),
    "execute_tools/evaluation_metric.py::AccuracyMetric._compute": (5, 2, 15, 4),
    "execute_tools/evaluation_metric.py::GlobalMseMetric._compute": (17, 5, 36, 4),
    "execute_tools/deliverable_spec.py::derive_tidmad_deliverable_spec": (3, 0, 33, 1),
    "execute_tools/deliverable_spec.py::DeliverableNaming.name": (3, 0, 10, 5),
}

#: §E.2: zero net branch growth is the target, achieved by EXTRACTION. A
#: function that must grow records the extraction considered and why it was
#: rejected. These are the outer bounds, not a licence.
MAX_BRANCH_GROWTH = 3
MAX_LOC_GROWTH = 80
MAX_PARAM_GROWTH = 1

#: §E.2 HARD CAPS — neither may end this PR larger than it started.
HARD_CAPPED_BRANCHES = {
    "execute_tools/inference_single.py::main": 67,
    (
        "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
        "::HyperparamTuningAgent.run"
    ): 68,
}

#: §E.2, as PR-12bc's §J froze it: exactly 19, never 20.
RUN_EXPERIMENT_STREAMING_PARAMS = 19

#: Module-level shape, which matters for the two script-style children.
#: ``repo-relative module -> (file loc, module-level statements ex-imports)``.
MODULE_LEVEL_BASELINE = {
    "core/sandbox_executor.py": 5,
    "workflows/task_composition.py": 9,
    "execute_tools/inference_single.py": 2,
    "execute_tools/task_data_path.py": 12,
    "execute_tools/deliverable_spec.py": 6,
    "execute_tools/denoising_score_single.py": 42,
}


def current_structure() -> dict[str, tuple[int, int, int, int]]:
    """The live measurement, for D-FINAL's recorded pre/post comparison."""
    out: dict[str, tuple[int, int, int, int]] = {}
    by_file: dict[str, list[str]] = {}
    for key in STRUCTURAL_BASELINE_12D:
        rel, qualified = key.split("::")
        by_file.setdefault(rel, []).append(qualified)
    for rel, names in by_file.items():
        functions = _qualified_functions(REPO_ROOT / rel)
        for qualified in names:
            fn = functions.get(qualified)
            if fn is not None:
                out[f"{rel}::{qualified}"] = measure(fn)
    return out


class TestStructuralBaseline:
    """A tripwire on GROWTH; deliberately silent on shrinkage."""

    def test_every_baselined_function_still_exists(self):
        missing = sorted(set(STRUCTURAL_BASELINE_12D) - set(current_structure()))
        assert missing == [], f"baselined function(s) vanished without a ledger entry: {missing}"

    @pytest.mark.parametrize("key", sorted(STRUCTURAL_BASELINE_12D))
    def test_no_function_grew_past_its_budget(self, key):
        live = current_structure()
        if key not in live:
            pytest.skip("covered by test_every_baselined_function_still_exists")
        _, branch, loc, params = live[key]
        _, base_branch, base_loc, base_params = STRUCTURAL_BASELINE_12D[key]
        assert branch - base_branch <= MAX_BRANCH_GROWTH, f"{key}: branch {base_branch} -> {branch}"
        assert loc - base_loc <= MAX_LOC_GROWTH, f"{key}: loc {base_loc} -> {loc}"
        assert params - base_params <= MAX_PARAM_GROWTH, f"{key}: params {base_params} -> {params}"

    @pytest.mark.parametrize("key", sorted(HARD_CAPPED_BRANCHES))
    def test_the_two_god_functions_never_grow(self, key):
        """§E.1 H1. `main` may gain a CALL, not a branch family."""
        assert current_structure()[key][1] <= HARD_CAPPED_BRANCHES[key]

    def test_run_experiment_streaming_keeps_exactly_its_parameters(self):
        fn = _qualified_functions(REPO_ROOT / "execute_tools" / "train_engine_sandbox.py")[
            "run_experiment_streaming"
        ]
        assert measure(fn)[3] == RUN_EXPERIMENT_STREAMING_PARAMS

    @pytest.mark.parametrize("rel", sorted(MODULE_LEVEL_BASELINE))
    def test_module_level_statement_counts(self, rel):
        """D4a must drive the scoring child's 42 DOWN; the rest must not grow."""
        tree = _tree(rel)
        count = sum(
            1
            for node in tree.body
            if not isinstance(
                node,
                (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
        )
        assert count <= MODULE_LEVEL_BASELINE[rel], (
            f"{rel}: module-level statements {MODULE_LEVEL_BASELINE[rel]} -> {count}. "
            "Adding module-level execution to a script-style child is the H2 hazard."
        )


# ======================================================================
# Runner-claim ledger — Q-12d-4's order starts here
# ======================================================================

#: Every distinct claim the three D14 harnesses own TODAY, with its intended
#: surviving owner. D8a maps, ``G-12d`` produces the evidence, D8b retires or
#: relabels — never the other way round. A claim with no entry blocks D8b.
RUNNER_CLAIMS: dict[str, dict[str, str]] = {
    "pets.real_jpeg_decode_to_tensors": {
        "runner": "scripts/run_pets_gate2.py",
        "intended_owner": "G-12d Pets track (real inference child)",
    },
    "pets.production_training_engine_on_real_data": {
        "runner": "scripts/run_pets_gate2.py",
        "intended_owner": "G-12d Pets track (real training child)",
    },
    "pets.real_inference": {
        "runner": "scripts/run_pets_gate2.py",
        "intended_owner": "G-12d Pets track (real inference child)",
    },
    "pets.real_deliverable_codec": {
        "runner": "scripts/run_pets_gate2.py",
        "intended_owner": "G-12d Pets track (write_deliverable in the real child)",
    },
    "pets.real_metric_handle_on_a_fresh_deliverable": {
        "runner": "scripts/run_pets_gate2.py",
        "intended_owner": "G-12d Pets track (real scoring child)",
    },
    "pets.pack_health_family_on_a_fresh_deliverable": {
        "runner": "scripts/_gate2_health_stage.py",
        "intended_owner": "G-12d Pets track (tuner round-boundary gates)",
    },
    "davis.real_frame_decode_to_windows": {
        "runner": "scripts/run_davis_gate2.py",
        "intended_owner": "G-12d DAVIS track (real inference child)",
    },
    "davis.production_training_engine_on_real_data": {
        "runner": "scripts/run_davis_gate2.py",
        "intended_owner": "G-12d DAVIS track (real training child)",
    },
    "davis.explicit_eval_scope_leg_with_declared_rows": {
        "runner": "scripts/run_davis_gate2.py",
        "intended_owner": "D3 (B9 transport) + G-12d DAVIS track",
    },
    "davis.real_npz_deliverable_codec": {
        "runner": "scripts/run_davis_gate2.py",
        "intended_owner": "G-12d DAVIS track (write_deliverable in the real child)",
    },
    "davis.real_metric_handle_global_mse": {
        "runner": "scripts/run_davis_gate2.py",
        "intended_owner": "G-12d DAVIS track (real scoring child)",
    },
    "davis.last_frame_copy_baseline_comparison": {
        "runner": "scripts/run_davis_gate2.py",
        "intended_owner": (
            "D8a DECISION: NO surviving owner needed. The runner computes it "
            "for RECORDING only (`run_davis_gate2.py:289`, never asserted); "
            "§I explicitly excludes benchmark improvement, model quality and "
            "score magnitude from G-12d's PASS criteria. D8b may retire the "
            "runner WITHOUT transferring this claim, and must say so by name "
            "rather than silently dropping it — an intentional non-transfer, "
            "not a gap."
        ),
    },
    "davis.pack_health_family_on_a_fresh_deliverable": {
        "runner": "scripts/_gate2_health_stage.py",
        "intended_owner": "G-12d DAVIS track (tuner round-boundary gates)",
    },
    "shared.explicit_health_binding_state_C_never_the_tidmad_default": {
        "runner": "scripts/_gate2_health_stage.py",
        "intended_owner": "G-12d both tracks (composed task_health binding)",
    },
    "shared.every_selected_gate_persisted_no_cross_gate_short_circuit": {
        "runner": "scripts/_gate2_health_stage.py",
        "intended_owner": "existing 08c deterministic guards (already transferred)",
    },
    # Added POST-D0, at integration (D-12d-33) — F-12d-17. Both runners load
    # THREE disjoint role manifests and pass task_scope/task_eval_scope
    # EXPLICITLY; a composed run held one manifest, so build_training_scope
    # and build_eval_scope both selected the same rows. Nothing green caught
    # it, because the runner was doing the composed path's choosing for it —
    # the exact shape RUNNER_CLAIMS exists to name. CLOSED, additively, in
    # the same commit that found it (77f40184): `eval_clips_path` is an
    # OPTIONAL config key on both TaskDataPath implementations.
    "pets.the_runner_separates_train_from_eval_scope": {
        "runner": "scripts/run_pets_gate2.py",
        "intended_owner": (
            "CLOSED — PetsTaskDataPath.eval_manifest_path (config), proven "
            "by test_step12_pr12d_pets_eval_scope.py::"
            "TestTheEvalScopeIsNotTheTrainingScope, train 370 / eval 74 / "
            "overlap 0 through the SHIPPED pets.yaml"
        ),
    },
    "davis.the_runner_separates_train_from_eval_scope": {
        "runner": "scripts/run_davis_gate2.py",
        "intended_owner": (
            "CLOSED — DavisTaskDataPath.eval_clips_path (config), proven by "
            "test_step12_pr12d_d6_davis_declarations.py::"
            "TestTheEvalScopeIsNotTheTrainingScope, train 60 / eval 15 / "
            "overlap 0 through the SHIPPED davis.yaml"
        ),
    },
}


class TestRunnerClaimLedger:
    """D0 records; D8a maps; ``G-12d`` witnesses; D8b retires. In that order."""

    @pytest.mark.parametrize(
        "runner",
        [
            "scripts/run_pets_gate2.py",
            "scripts/run_davis_gate2.py",
            "scripts/_gate2_health_stage.py",
        ],
    )
    def test_the_runner_still_exists(self, runner):
        """No runner is deleted at D0 (Q-12d-4's fixed order)."""
        assert (REPO_ROOT / runner).is_file()

    def test_every_claim_names_a_runner_that_exists_and_an_intended_owner(self):
        for claim, entry in RUNNER_CLAIMS.items():
            assert (REPO_ROOT / entry["runner"]).is_file(), claim
            assert entry["intended_owner"].strip(), claim

    def test_every_runner_contributes_at_least_one_claim(self):
        named = {entry["runner"] for entry in RUNNER_CLAIMS.values()}
        assert named == {
            "scripts/run_pets_gate2.py",
            "scripts/run_davis_gate2.py",
            "scripts/_gate2_health_stage.py",
        }

    def test_the_runners_carry_the_post_gate_retirement_disposition(self):
        """D8b: the CAP-SCOPE blocker is gone, and a DECISION stands in its place.

        This test used to assert the STALE prose was PRESENT, so that the
        correction could not be forgotten. ``G-12d`` has now produced the
        replacement evidence, so it asserts the correction instead — in both
        directions, because deleting the stale sentence without recording what
        replaced it would leave a reader unable to tell a decided retention
        from an abandoned transfer.
        """
        for runner in ("scripts/run_pets_gate2.py", "scripts/run_davis_gate2.py"):
            source = _source(runner)
            assert "FULL RETIREMENT IS BLOCKED ON **CAP-SCOPE**" not in source, (
                f"{runner} still claims CAP-SCOPE blocks retirement; it landed at 12bc"
            )
            assert "RETAINED, not retired" in source, (
                f"{runner} must record the D8b decision, not merely drop the stale blocker"
            )

    def test_the_davis_runner_names_its_one_intentional_non_transfer(self):
        """A claim with no owner must be NAMED, never silently dropped.

        ``davis.last_frame_copy_baseline_comparison`` is recorded for
        observation only and §I excludes score magnitude from PASS, so D8a
        ruled it needs no surviving owner. That ruling is only honest if the
        runner says so where a reader will find it.
        """
        source = _source("scripts/run_davis_gate2.py")
        assert "INTENTIONALLY NOT TRANSFERRED" in source
        assert "davis.last_frame_copy_baseline_comparison" in source


# ======================================================================
# §J changed-path derivation input
# ======================================================================

#: The common executable paths TIDMAD traverses that D1-D4b will touch.
#: CHECKPOINT A turns this into the smoke's covered-path list (§J).
TIDMAD_CHANGED_PATH_CANDIDATES = {
    "tuner_scope_fact_projection": "D2 — planning.py / execution.py / the tuner's run()",
    "training_child_validation_preflight": "D3 — _preflight_validation_scope + task_eval_scope",
    "inference_child_iteration_and_write": "D3 — inference_single.py::main",
    "scoring_handoff_payload_and_metric_call": "D4b — evaluate_metric + denoising_score_single.py",
    "deliverable_identity_and_cleanup_globs": "D4b — DeliverableNaming",
    "child_spawn_environment": "DP — subprocess_env at all three spawn sites",
}


class TestChangedPathDerivationInput:
    """§J's input, recorded BEFORE anything changes."""

    def test_every_candidate_names_the_block_that_will_touch_it(self):
        for path, owner in TIDMAD_CHANGED_PATH_CANDIDATES.items():
            assert owner.split(" — ")[0] in {"DP", "D1", "D2", "D3", "D4a", "D4b", "D4c"}, path

    def test_all_three_children_are_represented(self):
        joined = " ".join(TIDMAD_CHANGED_PATH_CANDIDATES.values())
        for child in ("_preflight_validation_scope", "inference_single", "denoising_score_single"):
            assert child in joined


# ======================================================================
# A3 — the exact-MAE objective, and why it is a REPAIR not a new family
# ======================================================================


# ======================================================================
# The three-task deterministic baseline, in its HONEST pre-12d form
# ======================================================================

#: The existing three-task closure suite (Step 10 / P5+P6 C6) and its D0 count.
#: **It composes FIXTURES, not shipped pack declarations** — which is exactly
#: why CHECKPOINT A may not use it to claim the final pack matrix, and why
#: CHECKPOINT B needs a separate module running the SHIPPED manifests.
THREE_TASK_CLOSURE_SUITE = "tests/unit/workflows/test_step10_p56_c6_three_task_closure.py"
THREE_TASK_CLOSURE_TESTS_AT_D0 = 29


class TestThreeTaskDeterministicBaseline:
    """What "three tasks pass today" actually means, stated precisely."""

    def test_the_closure_suite_composes_fixtures_not_shipped_packs(self):
        source = _source(THREE_TASK_CLOSURE_SUITE)
        assert 'FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"' in source
        assert "configs/task_composition/pets" not in source
        assert "configs/task_composition/davis" not in source

    def test_the_fixture_manifests_declare_themselves_non_executable(self):
        """F-12d-4. The disclaimer lives in the MANIFEST, not the profile.

        Recorded because the first reading looked for it in
        ``dataset_profile.json`` — JSON carries no comments, so the honest
        statement is in ``composition.yaml`` beside it. The profile's own
        evidence is its fabricated VALUES, asserted by ``TestInvertedGuardB0``.

        **Ledger correction (D0).** §A.2 attributes *"NOT evidence of
        task-correct training scope"* to the DAVIS fixture. That sentence is
        the Step-10 P5+P6 design's §10.3 honesty clause, not a byte of the
        fixture; DAVIS's own disclaimer is the two phrases below. The FINDING
        is unaffected — both fixtures do declare themselves non-executable —
        but a guard must assert the bytes that exist.
        """
        for pack, phrase in (
            ("pets", "not a claim that Pets is loop-executable"),
            ("davis", "REAL task-correct TRAINING through the loop is NOT delivered here"),
        ):
            raw = (
                REPO_ROOT / "tests" / "fixtures" / "step10_p1" / pack / "composition.yaml"
            ).read_text(encoding="utf-8")
            # The disclaimers are line-wrapped YAML comments, so compare
            # against the un-wrapped prose rather than the file's line breaks.
            manifest = " ".join(
                line.lstrip("# ").strip() for line in raw.splitlines() if line.startswith("#")
            )
            assert phrase in manifest, (
                f"the {pack} fixture manifest no longer carries its own disclaimer"
            )

    # RETIRED at D5 + D6. This asserted that both fixture profiles carried
    # TIDMAD's sections at the TOP LEVEL — the legacy wire form
    # `DatasetProfile` still accepts — rather than the Q-12-4 shape with an
    # opaque `topology`. It existed to argue that D5/D6 should AUTHOR FRESH
    # rather than edit values in place, because editing would have preserved
    # the wrong SHAPE along with the wrong numbers.
    #
    # Both did author fresh: Pets' fixture profile was DELETED (the fixture
    # resolves the pack's own declaration, so exactly one exists), and DAVIS'
    # was re-authored with `partition_count` plus a DAVIS-meaningful opaque
    # `topology`. The guard's own demand is what closed it, which is the
    # R-11-10 shape — and the positive successors are the field-by-field
    # assertions in the two pack modules, which say what the profiles ARE
    # rather than what they are not.

    def test_the_closure_suite_still_exists_with_its_recorded_size(self):
        """A tripwire on SILENT SHRINKAGE, which a seam commit could cause.

        Counted by collection rather than by running: D0 must not re-run
        another block's suite to record a number.
        """
        collected = sum(
            1
            for node in ast.walk(_tree(THREE_TASK_CLOSURE_SUITE))
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
        assert collected >= 1
        assert THREE_TASK_CLOSURE_TESTS_AT_D0 == 29, "the recorded D0 pass count"


class TestInvertedGuardA3:
    """PARTIALLY RETIRED at D4c. Two cases went RED; two are PRESERVED.

    **Retired** (the defect is gone, and the successor owns the property —
    ``tests/unit/examples/test_step12_pr12d_d4c_objective.py``):

    * ``test_no_mae_objective_plugin_exists_in_either_pack`` — blocker 1.
      `examples/davis_future_prediction/plugins/davis_exact_l1_loss.py` now
      exists and is reachable.
    * ``test_a_custom_objective_can_never_be_comparability_established`` —
      blocker 3. A plugin that DECLARES `PLUGIN_LOSS_REDUCTION = "mean"` is
      now stamped `established`; declaring nothing is unchanged.

    **Preserved**, and they are not leftovers — they are the two constraints
    A3 forbids relaxing, so they must outlive the seam that satisfied them:
    the closed `loss_type` Literal, and `smooth_l1`'s inability to degenerate
    to exact L1. Both would go red if a future change took the easy route.
    """

    def test_the_loss_type_literal_is_closed_and_has_no_l1_member(self):
        from ml_models.models_format_sandbox import LossConfig

        allowed = LossConfig.model_fields["loss_type"].annotation
        assert set(getattr(allowed, "__args__", ())) == {
            "focal",
            "focal_cw",
            "ce",
            "smooth_l1",
            "custom",
        }, "growing this Literal for DAVIS is FORBIDDEN (A3)"

    def test_smooth_l1_cannot_degenerate_to_exact_l1(self):
        """``beta`` is bounded ``ge=0.1``, so the L1 limit is unreachable."""
        import pydantic

        from ml_models.models_format_sandbox import LossConfig

        with pytest.raises(pydantic.ValidationError):
            LossConfig(loss_type="smooth_l1", beta=0.0)

    def test_an_UNDECLARED_custom_objective_is_still_not_established(self):
        """Blocker 3, RETIRED-AND-REPLACED — the half that must NOT change.

        D4c did not make custom objectives comparable by type; it gave a
        plugin a way to SAY how it normalizes. A plugin that says nothing is
        exactly as before, and for the same honest reason — which is what
        keeps this a repair rather than a relaxation.
        """
        from execute_tools.training_history import (
            COMPARABILITY_ESTABLISHED_KINDS,
            stamp_comparability,
        )
        from ml_models.models_format_sandbox import LossConfig

        assert "custom" not in COMPARABILITY_ESTABLISHED_KINDS
        verdict, reason = stamp_comparability(
            LossConfig(loss_type="custom", loss_name="a_loss_that_declared_nothing")
        )
        assert (verdict, reason) == ("not_established", "custom_objective_undeclared")

    def test_the_davis_runner_no_longer_declares_smooth_l1(self):
        """Blocker 4, RETIRED — it went RED against the landed fix.

        The runner declared `smooth_l1(beta=0.1)` AND hard-asserted
        `comparability == "established"`, and the pair is what made the
        numerical gap invisible: the run optimised a quadratic-near-zero
        objective while the report said MAE, and the assertion passed because
        `smooth_l1` is an audited built-in. It now declares the frozen exact-L1
        objective, and the comparability assertion still holds — for the right
        reason this time.
        """
        src = _source("scripts/run_davis_gate2.py")
        assert 'LossConfig(loss_type="smooth_l1", beta=0.1)' not in src
        assert 'LossConfig(loss_type="custom", loss_name="davis_exact_l1")' in src
        assert 'th["comparability"] == "established"' in src


def test_this_module_touches_no_production_file():
    """D0's own commit boundary, asserted rather than asserted-in-prose."""
    assert __file__.replace(os.sep, "/").endswith(
        "tests/unit/guardrails/test_step12_pr12d_d0_baselines.py"
    )
