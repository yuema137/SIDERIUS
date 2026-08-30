"""Step 12 / PR-12d — CHECKPOINT A: the runtime genericization checkpoint.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` — ⛔ CHECKPOINT A, placed after D4b and
before D5.

**Checkpoint A is primarily an AGGREGATION boundary.** D0-D4c each carry their
own semantic-owner evidence and it is not re-run here. What this module adds is
the one claim no single seam can make alone: **a contrast-SHAPED run traverses
every generic runtime seam in ONE pass**, with no seam silently falling back to
TIDMAD.

Scoped to what can honestly be true at this point: **the shipped Pets/DAVIS
declarations do not exist yet** — D5 and D6 create them, and B0 closes at
Checkpoint B. The fixtures used here are the contrast-shaped composition
fixtures that have existed since Step 10, not the shipped packs, and the
checkpoint deliberately does **not** claim the three-task matrix is green.

The fabricated TIDMAD-shaped values condemned in F-12d-4 are used by nothing
here; every fixture below is either a Step-10 contrast composition or is
authored inline with honest contrast shape.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"

# Declared delta (arXiv #255, 2026-08-26): the fingerprint payload gained
# task_data_path_content_identity (the registration-captured implementation
# source identity), moving EVERY composed fingerprint once, uniformly — the
# declared consequence (the 12a proposal_blocks precedent). The SEMANTIC of
# this pin (additive keys leave undeclared manifests at a stable literal) is
# unchanged; the literals are re-recorded at the #255 tree.
# Declared delta (C2 aggregation flip, operator-frozen 2026-08-26): blocking
# per-file aggregation moved any_pass -> all_pass and the aggregation prose in
# configs/task_health/tidmad.yaml's blocking reason strings moved with it; the
# task health document is composed identity, so TIDMAD's fingerprint
# legitimately moved 3fd178b5… -> 9b497798…. A pre-C2 composed workspace
# fails its resume closed — intended.
#: TIDMAD's shipped composition identity. Every Checkpoint-A claim is worthless
#: if the only task with real production evidence moved underneath it.
# Re-recorded again (false-header correction, 2026-08-27): 9b497798… ->
# c0102089… — configs/task_health/tidmad.yaml's header claimed the file
# cannot state `aggregation`, which PR #357 made false. `_digest_file`
# hashes that document RAW, so the comment-only correction moves TIDMAD's
# composed identity. Deliberate: a composed workspace created before it
# fails its resume closed, and none exists outside TestPod.
TIDMAD_COMPOSITION_FINGERPRINT = "c0102089266b4c8c2ba53dcc5492e1063d5c4919f3ae4444fb5dae3b0cac8800"


#: The COMMITTED identity manifests — the honest scope authority. The Step-10
#: composition fixtures declare no `config:`, so their implementations hold no
#: manifest and cannot build a scope at all; that is a fixture limitation, not
#: a seam one, and it must not be mistaken for either.
_MANIFESTS = {
    "pets": ("manifest_path", "examples/oxford_iiit_pet/data/manifests/gate2_final.csv"),
    "davis": ("clips_path", "examples/davis_future_prediction/data/manifests/gate2_final.csv"),
}

#: Which commit re-authored each Step-10 fixture profile out of the fabricated
#: TIDMAD shape F-12d-4 condemned, or ``None`` while it is still owed. Kept as
#: DATA so the second landing moves ONE entry and the assertion below keeps its
#: shape — the two packs are authored in separate commits and neither may
#: silently relax the other's obligation.


def _manifest_backed_impl(task: str):
    from execute_tools.davis_data_path import DavisTaskDataPath
    from execute_tools.pets_data_path import PetsTaskDataPath

    key, rel = _MANIFESTS[task]
    cls = PetsTaskDataPath if task == "pets" else DavisTaskDataPath
    return cls(**{key: str(REPO_ROOT / rel)})


def _compose(task: str):
    from workflows.task_composition import compose_run_task_bindings

    return compose_run_task_bindings(str(FIXTURES / task / "composition.yaml"))


# ======================================================================
# The one claim no single seam can make
# ======================================================================


@pytest.mark.parametrize("task", ["pets", "davis"])
class TestAContrastRunTraversesEverySeam:
    """One composed pass, every seam D0-D4c touched, nothing falling back."""

    def test_the_composition_resolves_with_no_TIDMAD_identity_anywhere(self, task):
        """C-P56-1, at the composition boundary.

        Discrimination is by composition PRESENCE throughout; a task name may
        appear as a VALUE the task declared about itself, never as something
        the framework branched on.
        """
        composition = _compose(task)
        assert composition.task_data_path.task_data_path_id == (
            "oxford_iiit_pet" if task == "pets" else "davis_future_prediction"
        )
        assert composition.semantic_fingerprint != TIDMAD_COMPOSITION_FINGERPRINT
        assert composition.metric.spec.id == ("accuracy" if task == "pets" else "mse")

    def test_the_declared_metric_is_the_one_that_will_COMPUTE(self, task):
        """D4c's identity check, exercised on the real fixtures.

        Before D4c every one of these composed while bound to an
        implementation computing something else.
        """
        composition = _compose(task)
        claimed = type(composition.metric).IMPLEMENTS
        assert not claimed or composition.metric.spec.id in claimed
        for secondary in composition.secondary_metrics or ():
            secondary_claimed = type(secondary).IMPLEMENTS
            assert secondary_claimed, (
                f"{type(secondary).__name__} states no IMPLEMENTS, so binding it to "
                f"{secondary.spec.id!r} could never be checked"
            )
            assert secondary.spec.id in secondary_claimed

    def test_the_task_builds_its_OWN_scopes_and_they_round_trip(self, task):
        """Seam C — the scope ABI, which is what CAP-SCOPE bought.

        The digest is verified BEFORE deserialization, and the payload never
        goes on argv; here we assert the narrower property this checkpoint
        owns: a contrast task builds scopes the framework never interprets,
        and gets them back unchanged.
        """
        from execute_tools.task_data_path import ScopeBuildRequest, resolve_task_scope_capability

        capability = resolve_task_scope_capability(_manifest_backed_impl(task))
        scope = capability.build_eval_scope(
            ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
        )
        restored = capability.deserialize_scope(capability.serialize_scope(scope))
        assert restored == scope
        assert len(scope.rows) > 0

    def test_the_scoring_route_taken_is_TASK_OWNED_not_the_legacy_else(self, task):
        """Seam D — B4, on a real contrast composition.

        No contrast implementation declares trial anchoring, which is exactly
        why the pre-D4b `else` swallowed every one of them.
        """
        from execute_tools.task_data_path import ScopeBuildRequest, resolve_task_scope_capability
        from nodes.ml_hyperparameter_tune_agent.policy import (
            ScoringRoute,
            resolve_scoring_route,
        )

        scope = resolve_task_scope_capability(_manifest_backed_impl(task)).build_eval_scope(
            ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
        )

        class _Scopes:
            evaluation = scope

        assert resolve_scoring_route(None, _Scopes()) is ScoringRoute.TASK_OWNED

    def test_the_deliverable_is_named_by_the_TASK_and_naming_REFUSES(self, task):
        """Seam E — A4 and F-A4-1 together, on a real contrast composition."""
        from execute_tools.deliverable_spec import (
            DeliverableNamingNotApplicableError,
            resolve_deliverable_naming,
        )
        from execute_tools.task_data_path import (
            DeliverableWriteRequest,
            bind_task_data_path,
            task_declared_deliverable_name,
        )

        impl = _compose(task).task_data_path
        request = DeliverableWriteRequest(
            output_dir="/tmp", exp_id="e", run_name="r", model_type="m"
        )
        name = task_declared_deliverable_name(impl, request)
        assert name and not name.startswith("abra_validation_denoised"), (
            "the task's own codec must name the artifact; TIDMAD's template here "
            "would mean seam E fell back"
        )
        with bind_task_data_path(impl):
            with pytest.raises(DeliverableNamingNotApplicableError):
                resolve_deliverable_naming()

    def test_the_fixture_profile_carries_NO_fabricated_TIDMAD_VALUE(self, task):
        """Checkpoint A's own finding, now fully discharged.

        At Checkpoint A both Step-10 composition fixtures carried a full
        TIDMAD ``topology`` — ``psd_segment_length``, ``segments_per_file``
        and ``.h5`` shard patterns like
        ``pets_train_shard_{file_index:04d}.h5`` — for tasks that have neither
        PSD segments nor HDF5 shards. Those are the fabricated values
        **F-12d-4** condemned, and the checkpoint forbids using them to PASS
        it, so the property was asserted as an OBLIGATION on D5 and D6:
        *delete these values, do not carry them.*

        **Both discharged it**, in their own commits and by different means —
        D5 DELETED Pets' fixture profile so the fixture resolves the pack's
        own shipped declaration, and D6 RE-AUTHORED DAVIS' into the Q-12-4
        shape. So the obligation branch is gone and this is now the
        honest-shape assertion it was standing in for.

        Fails when a re-authored fixture regains any TIDMAD-physical field —
        which is the only way the fabrication could return, since neither
        pack has a second profile left to drift from.
        """
        import json as _json

        from execute_tools.dataset_config import declares_tidmad_topology

        profile = _compose(task).dataset_profile
        assert not declares_tidmad_topology(profile)
        flat = _json.dumps(profile.topology)
        for fabricated in (
            "psd_segment_length",
            "segments_per_file",
            "sampling_frequency",
            ".h5",
        ):
            assert fabricated not in flat, (
                f"the {task} fixture profile carries {fabricated!r} again"
            )

    def test_an_HONEST_Q_12_4_profile_traverses_seam_B(self, task):
        """Seam B — B11, on an honestly-shaped profile authored HERE.

        The generic property does not depend on the fixtures being fixed: a
        profile that declares no physical geometry must yield a DECLARED
        absence and a DECLINE, never an exception from inside
        `tidmad_topology`. That is what B11 cost the tuner.
        """
        from execute_tools.dataset_config import DatasetProfile, declares_tidmad_topology
        from execute_tools.deliverable_spec import derive_run_deliverable_spec
        from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
            TaskTopologyUnavailableError,
            project_attempt_topology_facts,
        )

        profile = DatasetProfile(
            partition_count=3 if task == "pets" else 2,
            anchor_selection_files=(0,),
            health_peek_files=(1,),
        )
        assert not declares_tidmad_topology(profile)
        assert derive_run_deliverable_spec(profile) is None

        facts = project_attempt_topology_facts(profile)
        assert facts.declares_physical_geometry is False
        with pytest.raises(TaskTopologyUnavailableError):
            facts.require_physical_dataset("a purpose that needs physical geometry")


# ======================================================================
# Checkpoint A's own finding — half discharged by D5, half still standing
# ======================================================================
#
# Checkpoint A forbade using the fabricated TIDMAD-shaped fixtures condemned in
# F-12d-4 to PASS it, so it asserted the OBLIGATION rather than the property:
# `test_the_step10_fixture_profile_is_STILL_TIDMAD_SHAPED` was parametrized
# over both contrast tasks and said, in as many words, that the day D5/D6
# delete those values it "must become the honest-shape assertion it is
# standing in for".
#
# D5 landed the Pets half, so that is what happened. The one test became two,
# because the two tasks are now in different states and a predicate true in
# both would witness neither. The generic seam-B property is asserted
# SEPARATELY above against an inline honest profile, so neither of these
# carries the checkpoint's real claim.


def test_the_pets_fixture_profile_is_NO_LONGER_TIDMAD_SHAPED():
    """FLIPPED by D5, and the flip is the evidence.

    Fails if anyone re-introduces TIDMAD physics into what a composed Pets run
    declares — a `topology` carrying `dataset`/`channels`/`encoding` is what
    `declares_tidmad_topology` names, and it is the shape that let the old
    fixture invent a `sampling_frequency` for an image classifier.
    """
    from execute_tools.dataset_config import declares_tidmad_topology

    profile = _compose("pets").dataset_profile
    assert not declares_tidmad_topology(profile)
    assert profile.partition_count == 370


# ======================================================================
# TIDMAD non-regression — the anchor every claim above depends on
# ======================================================================


class TestTidmadDidNotMove:
    def test_the_shipped_composition_fingerprint_is_unchanged(self):
        from workflows.task_composition import compose_run_task_bindings

        composition = compose_run_task_bindings(
            str(REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml")
        )
        assert composition.task_data_path.task_data_path_id == "tidmad"

    def test_TIDMAD_still_resolves_its_indexed_naming_and_physical_geometry(self):
        """The two things every contrast assertion above says are ABSENT."""
        from execute_tools.dataset_config import declares_tidmad_topology
        from execute_tools.deliverable_spec import (
            derive_run_deliverable_spec,
            resolve_deliverable_naming,
        )
        from workflows.task_composition import (
            bind_run_task_composition,
            compose_run_task_bindings,
        )

        composition = compose_run_task_bindings(
            str(REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml")
        )
        with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
            assert resolve_deliverable_naming().prefix == "abra_validation_denoised"
        assert declares_tidmad_topology(composition.dataset_profile)
        assert derive_run_deliverable_spec(composition.dataset_profile) is not None


# ======================================================================
# The three zero-counts, each re-proven with a PLANT
# ======================================================================


class TestTheThreeZeroCountsWithPlants:
    """A census that cannot fail is not evidence.

    Each count below is re-proven by planting the thing it forbids into a
    synthetic module and asserting the same detector fires — the shape
    F-12bc-6 exists to prevent, where a detector named a symbol and stayed
    green through the landing it was written to announce.
    """

    #: Generic runtime modules — the ones a task name must never reach.
    GENERIC_MODULES = (
        "execute_tools/task_data_path.py",
        "execute_tools/deliverable_spec.py",
        "execute_tools/generic_inference.py",
        "execute_tools/scope_artifact.py",
        "core/sandbox_executor.py",
        "core/subprocess_env.py",
        "nodes/ml_hyperparameter_tune_agent/policy.py",
        "nodes/ml_hyperparameter_tune_agent/scope_acquisition.py",
    )

    #: Task identities that must never appear as a BRANCH in generic code.
    TASK_NAMES = ("oxford_iiit_pet", "davis", "pets")

    @staticmethod
    def _task_name_branches(source: str, names) -> list[str]:
        """Comparisons or membership tests against a task identity literal."""
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.Compare, ast.If, ast.IfExp)):
                continue
            rendered = ast.unparse(node.test if isinstance(node, (ast.If, ast.IfExp)) else node)
            for name in names:
                if f'"{name}"' in rendered or f"'{name}'" in rendered:
                    found.append(rendered[:100])
        return found

    def test_zero_task_name_dispatch_in_generic_runtime(self):
        for module in self.GENERIC_MODULES:
            source = (REPO_ROOT / module).read_text(encoding="utf-8")
            assert self._task_name_branches(source, self.TASK_NAMES) == [], module

    def test_the_task_name_detector_FIRES_on_a_plant(self):
        planted = 'def f(task_id):\n    if task_id == "oxford_iiit_pet":\n        return 1\n    return 0\n'
        assert self._task_name_branches(planted, self.TASK_NAMES) != []

    def test_zero_production_imports_from_examples(self):
        """`examples/` is plugin SOURCE, loaded dynamically. Never imported."""
        offenders = []
        for path in REPO_ROOT.rglob("*.py"):
            rel = str(path.relative_to(REPO_ROOT))
            # `.claude/` holds git WORKTREES — full checkouts of this same
            # repository. Walking them makes the census report another
            # checkout's files as production offenders, and under a parallel
            # workstream it reports files that are not even on this branch.
            # The third census-blindness shape, in the WIDE direction: a file
            # set that includes things it does not own is as wrong as one that
            # omits things it does.
            if rel.startswith(
                (
                    "tests/",
                    "examples/",
                    "tools/",
                    ".venv/",
                    ".claude/",
                    "agent_generated/",
                )
            ):
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("examples"):
                    offenders.append(f"{rel}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    offenders += [
                        f"{rel}:{node.lineno}"
                        for alias in node.names
                        if alias.name.startswith("examples")
                    ]
        assert offenders == [], offenders

    def test_the_examples_import_detector_FIRES_on_a_plant(self):
        planted = ast.parse("from examples.oxford_iiit_pet.plugins import x\n")
        hits = [
            node
            for node in ast.walk(planted)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("examples")
        ]
        assert len(hits) == 1

    @classmethod
    def _task_rosters(cls, source: str) -> list[str]:
        """Literal collections naming two or more task identities.

        Reads the AST's string CONSTANTS rather than ``ast.unparse`` text. The
        first version matched ``f'"{name}"'`` against unparsed source — and
        ``ast.unparse`` emits SINGLE quotes, so it could never have fired. Its
        own plant caught it. That is the fourth census-blindness shape this PR
        has hit, and the cheapest one to avoid: compare VALUES, not rendered
        syntax.
        """
        rosters = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                continue
            literals = {
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
            if len(literals & set(cls.TASK_NAMES)) >= 2:
                rosters.append(ast.unparse(node)[:120])
        return rosters

    def test_zero_central_task_catalog(self):
        """No generic module may hold a collection enumerating task identities.

        The registry is keyed on binding PRESENCE and populated by
        declaration; a literal roster anywhere in generic code is the catalog
        this whole step exists to avoid.
        """
        for module in self.GENERIC_MODULES:
            source = (REPO_ROOT / module).read_text(encoding="utf-8")
            assert self._task_rosters(source) == [], module

    def test_the_catalog_detector_FIRES_on_a_plant(self):
        assert self._task_rosters('TASKS = ["oxford_iiit_pet", "davis", "tidmad"]') != []
        assert self._task_rosters("TASKS = ('davis', 'pets')") != [], (
            "quote style must not change the verdict"
        )
        assert self._task_rosters('X = ["davis"]') == [], "one name is not a roster"
