"""Step 12 / PR-12d — D4b: seams D and E, the scoring closure.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §D.D, §D.E, §M `D4b`.

D4b is the block where a composed contrast run stops being *describable* and
becomes *executable*: the evaluation scope reaches the scoring child, the
child asks the run's DECLARED metric instead of TIDMAD's, and the naming
authority stops answering a question it was never asked.

Three things are asserted here, and the frozen falsifiers are the reason each
one is worded the way it is:

* **seam D** — the route is NAMED rather than inferred from an absence, the
  scope crosses the process boundary, and the child's metric call carries
  only what the framework actually owns;
* **seam E** — ``DeliverableNaming`` is the INDEXED naming capability, and a
  composed run that declares none gets a refusal, not TIDMAD's template
  (**F-A4-1**);
* **TIDMAD is untouched** — the legacy route resolves the same names, the
  same argv and the same shipped default it always did.

The end-to-end witness that a REAL scoring child scores a REAL task-owned
deliverable is not here — it is the `G-12d` Pets track, because a subprocess
witness is the only thing that can carry that claim.
"""

from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

import pytest

from execute_tools.deliverable_spec import (
    DeliverableNaming,
    DeliverableNamingNotApplicableError,
    active_deliverable_naming,
    bind_deliverable_naming,
    default_deliverable_naming,
    derive_run_deliverable_spec,
    resolve_deliverable_naming,
)
from nodes.ml_hyperparameter_tune_agent.policy import ScoringRoute, resolve_scoring_route

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PETS_MANIFEST = "examples/oxford_iiit_pet/data/manifests/gate2_final.csv"
SCORING_CHILD = REPO_ROOT / "execute_tools" / "denoising_score_single.py"


def _source(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


class _Scopes:
    """The minimal shape the router reads — an `AttemptScopes` stand-in."""

    def __init__(self, evaluation=None):
        self.evaluation = evaluation


# ======================================================================
# Seam D — the route is named, not inferred
# ======================================================================


class TestScoringRouteIsNamed:
    """B4. The defect was a branch whose ``else`` described a condition the
    code did not test; the fix must therefore be readable, not merely
    correct."""

    def test_an_anchor_map_still_selects_anchor_normalized_scoring(self):
        """TIDMAD's trial route is unchanged, and takes precedence."""
        route = resolve_scoring_route({"anchors": {}, "s_max": 1.0}, _Scopes(evaluation="x"))
        assert route is ScoringRoute.ANCHOR_NORMALIZED

    def test_a_composed_eval_scope_selects_the_task_owned_route(self):
        """The route that did not exist before D4b.

        Every composed contrast run lands here, because no contrast
        implementation declares trial anchoring — which is precisely why the
        pre-D4b ``else`` swallowed them.
        """
        assert resolve_scoring_route(None, _Scopes(evaluation="x")) is ScoringRoute.TASK_OWNED

    @pytest.mark.parametrize("scopes", [None, _Scopes(), _Scopes(evaluation=None)])
    def test_no_anchor_and_no_scope_is_the_legacy_subprocess_route(self, scopes):
        """The un-composed formal round — NOT "legacy single-file mode".

        ``anchor_map_data`` is only ATTEMPTED on a trial round, so this branch
        has always carried every un-composed FORMAL round too. The old comment
        asserted otherwise and nothing checked it.
        """
        assert resolve_scoring_route(None, scopes) is ScoringRoute.SUBPROCESS_LEGACY

    def test_the_consumer_dispatches_on_the_route_not_on_the_anchor_map(self):
        """Reachability: the production branch reads the ROUTE.

        Without this, ``resolve_scoring_route`` could be perfectly correct and
        entirely unreached — the shape R-11-10 exists to prevent.
        """
        source = _source("nodes/ml_hyperparameter_tune_agent/execution.py")
        assert "_scoring_route = resolve_scoring_route(anchor_map_data, prepared.task_scopes)" in (
            source
        )
        assert "if _scoring_route is ScoringRoute.ANCHOR_NORMALIZED:" in source
        assert "# Legacy single-file mode (trial_allowed=False, no anchor map)" not in source


# ======================================================================
# Seam D — the child's metric call carries only what the framework owns
# ======================================================================


class TestTheChildAsksTheDeclaredMetric:
    """FALSIFIER 3, inverted into a positive contract.

    *"Plant a TIDMAD-shaped kwarg requirement back into the generic path and
    assert a contrast metric refuses it."* The generic path must pass exactly
    three values — the deliverable payload, the task's scope, and the data
    directory — because those are the only three the FRAMEWORK owns. Anything
    else (``sample_set``, ``anchor_map``, ``s_max``,
    ``denoised_filename_fn``, ``raw_data_dir``) is TIDMAD's physical
    vocabulary, and a contrast metric rejects it with a ``TypeError``.
    """

    #: What the TASK-OWNED route may pass. Not a style preference: each is a
    #: value the framework can produce for ANY task.
    GENERIC_SCORING_KWARGS = frozenset({"evaluation_payload", "task_scope", "data_dir"})

    def test_the_task_owned_route_passes_only_framework_owned_values(self):
        """UPGRADED after the route grew a shared kwargs dict (F-12d-18).

        The call became ``metric.evaluate({0: deliverable}, **compute_kwargs)``
        so the primary and the secondaries evaluate against the IDENTICAL
        inputs — one dict, not two independently-assembled ones that could
        drift. An AST scan of the call's own ``keywords`` therefore sees a
        single ``**`` unpack and nothing else; the property now lives in the
        DICT LITERAL that gets unpacked, so this traces that instead.
        """
        fn = next(
            node
            for node in ast.walk(ast.parse(SCORING_CHILD.read_text(encoding="utf-8")))
            if isinstance(node, ast.FunctionDef) and node.name == "_emit_task_owned_score"
        )
        calls = [
            node
            for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "evaluate"
        ]
        assert len(calls) == 1, "one metric call, or the route has grown a second authority"
        (call,) = calls
        assert len(call.keywords) == 1 and call.keywords[0].arg is None, (
            "expected exactly one **unpack keyword; a literal keyword here would be "
            "TIDMAD vocabulary re-entering the route"
        )
        unpacked_name = call.keywords[0].value.id

        assign = next(
            node
            for node in ast.walk(fn)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == unpacked_name
        )
        assert isinstance(assign.value, ast.Dict)
        passed = {key.value for key in assign.value.keys if isinstance(key, ast.Constant)}
        assert passed == self.GENERIC_SCORING_KWARGS, (
            f"the generic scoring route passes {sorted(passed)}; TIDMAD's physical "
            f"vocabulary must not re-enter it"
        )

    def test_the_primary_and_secondaries_see_the_SAME_kwargs_object(self):
        """The reason the dict was extracted at all — not merely tidiness.

        Two independently-built kwargs dicts could drift (a fix applied to
        one and not the other, e.g. F-12d-20's raw_data_dir correction).
        Passing the SAME name to both calls makes that class of drift
        syntactically impossible rather than merely untested.
        """
        source = SCORING_CHILD.read_text(encoding="utf-8")
        body = source.split("def _emit_task_owned_score")[1].split("\ndef ")[0]
        assert "metric.evaluate({0: deliverable}, **compute_kwargs)" in body
        assert "_evaluate_task_owned_secondaries(args, deliverable, compute_kwargs)" in body

    def test_the_child_binds_the_data_path_BEFORE_it_reads_the_scope(self):
        """ORDER, and it is load-bearing — not a tidiness claim.

        ``load_transported_scope`` resolves the deserializer from the
        run-scoped BINDING. Read the scope first and TIDMAD's regime-A default
        answers, which then refuses a Pets payload BY NAME — the pairing rule
        working correctly on a question that should never have been asked.
        This failed exactly this way on first execution.
        """
        source = SCORING_CHILD.read_text(encoding="utf-8")
        body = source.split("def _emit_task_owned_score")[1]
        bind_at = body.index("with bind_task_data_path(data_path):")
        load_at = body.index("load_transported_scope(")
        assert bind_at < load_at, "the scope is deserialized outside the binding"

    def test_a_contrast_metric_would_still_reject_the_tidmad_shaped_call(self):
        """The falsifier's own premise, kept executable.

        If someone re-inlines TIDMAD's keyword set into the generic route,
        the assertion above goes red — but only if this incompatibility is
        real. It is, and it is asserted rather than assumed.
        """
        import inspect

        from execute_tools.evaluation_metric import AccuracyMetric

        params = inspect.signature(AccuracyMetric._compute).parameters
        for tidmad_only in ("sample_set", "anchor_map", "s_max", "denoised_filename_fn"):
            assert tidmad_only not in params


# ======================================================================
# Seam E — the naming NARROWING, and F-A4-1
# ======================================================================


class TestDeliverableNamingIsNarrowed:
    """B10 / A4. The fix is a narrowing; these assert it is not a widening."""

    def test_the_accessors_take_an_opaque_input_identity_not_a_file_index(self):
        """What generic core holds is an integer identity, never a filename index."""
        source = _source("execute_tools/deliverable_spec.py")
        tree = ast.parse(source)
        cls = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "DeliverableNaming"
        )
        for accessor in ("name", "unqualified_name"):
            fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == accessor)
            names = {a.arg for a in fn.args.kwonlyargs}
            assert "file_index" not in names, "the generic contract still speaks of a file index"
            assert "input_identity" in names
            identity = next(a for a in fn.args.kwonlyargs if a.arg == "input_identity")
            assert ast.unparse(identity.annotation) == "int", (
                "`int | None` is explicitly NOT the fix — that is the widening A4 rejects"
            )

    def test_the_indexed_template_itself_is_byte_for_byte_unchanged(self):
        """A narrowing renames a concept; it must not move a produced NAME.

        Hardcoded, not read back from the object under test.
        """
        naming = DeliverableNaming()
        assert (
            naming.name(model_type="wavenet", run_name="r", exp_id="e", input_identity=7)
            == "abra_validation_denoised_wavenet_r_e_0007.h5"
        )
        assert naming.unqualified_name(model_type="wavenet", input_identity=7) == (
            "abra_validation_denoised_wavenet_0007.h5"
        )
        assert naming.attempt_glob(model_type="wavenet", run_name="r", exp_id="e") == (
            "abra_validation_denoised_wavenet_r_e_*.h5"
        )
        assert naming.experiment_glob(exp_id="e") == "abra_validation_denoised_*_e_*.h5"
        assert naming.input_identity_of("abra_validation_denoised_wavenet_r_e_0007.h5") == 7

    def test_an_UNCOMPOSED_run_still_resolves_the_shipped_default(self):
        """The legacy path, byte-for-byte. Composition PRESENCE is the test."""
        assert resolve_deliverable_naming() == DeliverableNaming()
        assert default_deliverable_naming() == DeliverableNaming()
        assert active_deliverable_naming() is None

    def test_F_A4_1_a_task_that_names_its_own_artifacts_is_REFUSED(self):
        """The defect, stated as the behaviour that must no longer happen.

        Before D4b this returned ``DeliverableNaming()`` — TIDMAD's template —
        to a bound Pets run, which then carried a ``--cleanup_denoised`` glob
        (``abra_validation_denoised_*_<exp>_*.h5``) addressing a filename
        pattern the run had never written.
        """
        from execute_tools.pets_data_path import PetsTaskDataPath
        from execute_tools.task_data_path import bind_task_data_path

        with bind_task_data_path(PetsTaskDataPath(manifest_path=PETS_MANIFEST)):
            with pytest.raises(DeliverableNamingNotApplicableError, match="task-owned"):
                resolve_deliverable_naming()

    def test_a_task_that_DECLARES_naming_still_gets_it(self):
        """The refusal is about the task owning its names, not about binding."""
        from execute_tools.pets_data_path import PetsTaskDataPath
        from execute_tools.task_data_path import bind_task_data_path

        declared = DeliverableNaming(prefix="predictions", extension=".csv")
        impl = PetsTaskDataPath(manifest_path=PETS_MANIFEST)
        with bind_task_data_path(impl), bind_deliverable_naming(declared):
            assert resolve_deliverable_naming() is declared

    def test_a_COMPOSED_TIDMAD_run_still_resolves_its_shipped_template(self):
        """The correction a coarser discriminator would have broken.

        Keyed on composition PRESENCE alone, this refused TIDMAD's OWN
        composed run — TIDMAD's manifest declares no ``deliverable:`` section
        because ``DeliverableNaming`` *is* its naming. Two Step-11 tests said
        so on the first execution. The question production must ask is *"does
        the task name its artifacts itself?"*, and TIDMAD's implementation
        declares no ``deliverable_name``.
        """
        from workflows.task_composition import (
            bind_run_task_composition,
            compose_run_task_bindings,
        )

        composition = compose_run_task_bindings(
            str(REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml")
        )
        with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
            assert active_deliverable_naming() is None
            assert resolve_deliverable_naming().prefix == "abra_validation_denoised"

    def test_the_optional_accessor_reports_the_absence_without_raising(self):
        """``active_*`` vs ``resolve_*``: the Step-11 split, applied here.

        A caller that can proceed without an indexed template must have a way
        to ask that does not raise — otherwise the refusal above just becomes
        a crash on the generic path.
        """
        assert active_deliverable_naming() is None

    def test_FALSIFIER_2_a_misspelled_naming_declaration_is_refused(self):
        """``extra="forbid"``, and why it is not decoration.

        A silently-ignored ``prefix_`` would resolve the shipped TIDMAD
        template and a cleanup glob deleting files the run never wrote.
        """
        with pytest.raises(ValueError, match="prefix_"):
            DeliverableNaming(prefix_="predictions")  # type: ignore[call-arg]


# ======================================================================
# Seam B closure — B11 in the scoring child
# ======================================================================


class TestTheChildrenNoLongerAssumeTidmadGeometry:
    """B11's last two sites. A profile with no physical geometry must not
    kill a child before it reaches its own route."""

    @pytest.mark.parametrize("child", ["denoising_score_single.py", "inference_single.py"])
    def test_neither_child_derives_the_TIDMAD_spec_unconditionally(self, child):
        source = _source(f"execute_tools/{child}")
        assert "derive_tidmad_deliverable_spec" not in source, (
            "the unconditional derivation is the B11 defect; the child must ask "
            "`derive_run_deliverable_spec`, which returns None for a profile that "
            "declares no physical geometry"
        )
        assert "derive_run_deliverable_spec" in source

    def test_a_profile_without_physical_geometry_yields_a_DECLARED_absence(self):
        from execute_tools.dataset_config import DatasetProfile

        profile = DatasetProfile(
            partition_count=3, anchor_selection_files=(0, 1), health_peek_files=(0,)
        )
        assert derive_run_deliverable_spec(profile) is None


# ======================================================================
# TIDMAD parity — the argv surface and the legacy child
# ======================================================================


@pytest.mark.allow_real_subprocess
class TestLegacyArgvIsUnchanged:
    """A composed-only flag must never appear on an un-composed child's argv."""

    def test_the_scoring_child_still_refuses_an_unknown_flag_the_same_way(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, str(SCORING_CHILD), "--not_a_flag"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
            timeout=180,
        )
        assert proc.returncode == 2
        assert "unrecognized arguments" in proc.stderr

    def test_the_transported_scope_flags_are_INERT_when_absent(self, tmp_path):
        """The whole legacy-parity claim in one probe.

        With no scope flags the child must take the TIDMAD path it always
        took — here, the structured refusal for a missing deliverable — and
        NOT the task-owned route.
        """
        out = tmp_path / "out.json"
        out.write_text("{}", encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(SCORING_CHILD),
                "--mode",
                "fix",
                "--data_dir",
                str(tmp_path),
                "--raw_data_dir",
                str(tmp_path),
                "--file_index",
                "6",
                "--output_json",
                str(out),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={"PYTHONPATH": str(REPO_ROOT), "PATH": "/usr/bin:/bin"},
            timeout=180,
        )
        assert proc.returncode == 1
        assert "Deliverable not scoreable" in proc.stderr
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["not_scoreable"]["metric_id"] == "tidmad_denoising_score"
