"""Step 10 / P1 C0 — the pre-implementation census of the composition surface.

Every later P1 commit is measured against this module. It records, executably,
the state of the five implicit TIDMAD defaults (P1 design §2.1) and of the
subprocess transport BEFORE any composition exists, so that "the un-composed
path is unchanged" is a comparison rather than an assertion.

Defects only this module catches:

* **census A — the five default mechanisms.** Each family resolves TIDMAD
  today through a *specific* mechanism (a registry compatibility id, an
  ``or`` fallback, an omitted keyword, an unconditional derivation, a
  default-path constant). C1/C2 make each explicit on a COMPOSED run while
  leaving the un-composed mechanism intact. If a migration silently changes
  which mechanism the legacy path uses, no behavioural test fails — both the
  old and the new mechanism produce TIDMAD — but the bounded legacy adapter
  the design promises Step 12 would already be gone.

* **census B — transport non-emission.** ``transport_argv``
  (``execute_tools/task_data_path.py``) has zero production callers at C0,
  so every child takes its regime-A branch. C3 gives it its first emitters.
  Pinning zero here is what makes C3's "exactly these sites" meaningful; a
  census written only after the change cannot distinguish a new emitter from
  one that was always there.

* **census C — legacy child argv.** The three sandbox children receive no
  ``--task_data_path_id`` today. This is captured as the real argv vector,
  not as source text, because C3 must prove the un-composed vectors are
  byte-identical afterwards.

* **census D — the legacy lock key set.** ``run_invariants_lock.json``'s
  serialized key set is pinned so §5.9's "the composition key is ABSENT for
  an un-composed run, never ``null``" is checkable. A new optional Pydantic
  field would otherwise serialize as ``null`` and change the legacy bytes,
  which is exactly the failure the design forbids.

**Planted-offender evidence (P1 design C0, recorded 2026-08-20).** Census B
was proven load-bearing by adding ``transport_argv(impl)`` to the training
argv in ``core/sandbox_executor.py``: census B and census C both went RED
(B reported 1 emitter where 0 were expected; C reported the flag in the
training vector). The plant was reverted; both are green here.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The repository's own production directory set (the definition the Step-10
#: parent census uses, §3.8), so this census and the parent's speak about the
#: same tree.
PRODUCTION_DIRS = (
    "src/nodes",
    "src/agent",
    "src/core",
    "src/execute_tools",
    "src/ml_models",
    "src/workflows",
    "scripts",
    "src/dashboard",
    "sdsc_submission_scripts",
)


def _production_py_files() -> list[Path]:
    files: list[Path] = []
    for rel in PRODUCTION_DIRS:
        root = REPO_ROOT / rel
        if root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


# ---------------------------------------------------------------------------
# Census A — the five implicit defaults, one mechanism each
# ---------------------------------------------------------------------------


class TestCensusAFiveDefaultMechanisms:
    """Historical P1 census, updated as Step 12 retires implicit defaults."""

    def test_default_1_task_data_path_refuses_when_unbound(self):
        from execute_tools.task_data_path import (
            TaskDataPathResolutionError,
            resolve_bound_task_data_path,
        )

        with pytest.raises(TaskDataPathResolutionError, match="No task data path is bound"):
            resolve_bound_task_data_path()

    def test_default_3_run_invariants_omits_the_task_health_binding_keyword(self):
        """``materialize_effective_config`` HAS the parameter (08b) and
        ``build_run_invariants`` does not pass it, so the run resolves
        ``LEGACY_OMITTED``. C2 makes it a pass-through; the un-composed call
        must keep omitting it."""
        import core.run_invariants as ri
        from execute_tools.health_checks.config import materialize_effective_config

        assert "task_health_binding" in inspect.signature(materialize_effective_config).parameters

        tree = ast.parse(inspect.getsource(ri.build_run_invariants))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "materialize_effective_config"
        ]
        assert len(calls) == 1, "one materialization call site expected"
        assert "task_health_binding" not in {kw.arg for kw in calls[0].keywords}

    def test_default_4_the_tuner_has_exactly_one_declared_metric_acquisition_site(self):
        """The tuner resolves one bound metric and contains no task fallback."""
        source = (
            REPO_ROOT
            / "src/nodes"
            / "ml_hyperparameter_tune_agent"
            / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assignments = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign | ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "run_metric"
                for t in ([node.target] if isinstance(node, ast.AnnAssign) else list(node.targets))
            )
        ]
        assert len(assignments) == 1, "exactly one run-scoped metric acquisition expected"
        value = assignments[0].value
        assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
        assert value.func.id == "resolve_run_metric", (
            "the acquisition must go through the ONE resolver; a second way to "
            "obtain the run's metric is how two sources agree until they do not"
        )

        resolver = next(
            node
            for node in ast.walk(
                ast.parse((REPO_ROOT / "src/execute_tools" / "evaluation_metric.py").read_text())
            )
            if isinstance(node, ast.FunctionDef) and node.name == "resolve_run_metric"
        )
        called = [
            node.func.id
            for node in ast.walk(resolver)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert called.count("resolve_bound_run_metric") == 1
        assert "derive_tidmad_metric" not in called

    def test_default_5_both_interpretation_callers_pass_no_path(self):
        """Zero-arg ⇒ ``LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG``. The
        workflow caller becomes composition-aware in C2; the standalone node
        CLI deliberately stays legacy (Q-P1-1)."""
        expected = {
            "src/workflows/model_exploration.py": 1,
            "src/nodes/result_interpretation_agent/result_interpretation_agent.py": 1,
        }
        found: dict[str, int] = {}
        for rel in expected:
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            zero_arg = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "load_interpretation_task_blocks"
                and not node.args
                and not node.keywords
            ]
            found[rel] = len(zero_arg)
        assert found == expected


# ---------------------------------------------------------------------------
# Census B — transport_argv has no production emitter at C0
# ---------------------------------------------------------------------------


class TestCensusBTransportEmissionSites:
    def test_transport_argv_is_called_from_exactly_one_production_module(self):
        """At C0 this pinned ZERO emitters: the parent end was built, the
        child end was built and waiting, and nothing joined them (parent
        design §3.8). C3 joined them, and the census changed in the same
        commit as the behaviour — which is what makes the number evidence
        rather than decoration.

        What it pins now is EXACTLY ONE emitting module. A second emitter
        elsewhere would mean two answers to "which binding does this child
        get", reachable from different call paths, agreeing until they do
        not — and no behavioural test would see it, because each one alone
        produces a correct-looking argv."""
        offenders: dict[str, int] = {}
        for path in _production_py_files():
            if path.name == "task_data_path.py":
                continue  # its own definition site
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == "transport_argv")
                    or (isinstance(node.func, ast.Attribute) and node.func.attr == "transport_argv")
                )
            ]
            if calls:
                offenders[str(path.relative_to(REPO_ROOT))] = len(calls)
        assert offenders == {"src/core/sandbox_executor.py": 1}, (
            "transport_argv must be emitted from exactly ONE production module "
            f"(the sandbox executor's single argv helper); found {offenders}."
        )

    def test_the_measured_binding_topology_of_the_parent_process(self):
        """The asymmetry C2/C3 must respect, measured rather than assumed.

        MEASURED at C0 — and NOT what a first reading of the design suggests.
        Besides the three CHILDREN and the two hand-written Gate runners,
        exactly ONE parent-side production consumer of the binding already
        exists: the GPU warmup probe in
        ``agent/skills/evaluate_time_skill/wrapper.py``, which *resolves*
        (``resolve_bound_task_data_path()``, D14-1 C5) and therefore already
        honours a binding when one is active. What does NOT exist anywhere in
        the parent is a ``bind_task_data_path`` call — the workflow never
        establishes one, which is why every parent-side resolve falls through
        to the compatibility implementation today.

        The consequence for C3: emission must be conditional on an ACTIVE
        binding, never on ``resolve_bound_task_data_path()``, because that
        helper falls back — an unconditional parent emission would put
        ``--task_data_path_id tidmad`` into every legacy child argv and break
        the un-composed byte parity P1 must preserve.

        UPDATED AT C1, deliberately and with the reason recorded: the
        composition EDGE (``workflows/task_composition.py``) resolves through
        the registry when an id is already registered, so that re-composing a
        task in one process returns the REGISTERED object rather than a second
        instance of the same class. That is part of the single resolution
        §5.2a mandates, not a second one — which is why the invariant is
        expressed below as a per-site allowlist plus the sharp rule that
        ``model_exploration.py`` resolves NOTHING.
        """
        child_or_runner = {
            "src/execute_tools/train_engine_sandbox.py",
            "src/execute_tools/inference_single.py",
            "src/execute_tools/denoising_score_single.py",
        }
        #: Step 12 / PR-12d: exempt by ENCLOSING FUNCTION, not by file.
        #:
        #: `load_transported_scope` is CHILD-side code — all three children
        #: call it to rehydrate a transported scope — but since D4b it lives in
        #: `execute_tools/scope_artifact.py`, a module that ALSO holds the
        #: parent's writer. Adding that file to `child_or_runner` would have
        #: blinded this census to every future parent-side resolve in it,
        #: which is the file-set blindness F-12bc-9 already cost us once.
        #: Keyed on the function, a new parent-side resolve in the same module
        #: still trips.
        child_side_functions = {"load_transported_scope"}

        def _enclosing_function(tree, target):
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    node is target for node in ast.walk(fn)
                ):
                    return fn.name
            return None

        binds: dict[str, int] = {}
        resolves: dict[str, int] = {}
        for path in _production_py_files():
            rel = str(path.relative_to(REPO_ROOT))
            if rel in child_or_runner or path.name == "task_data_path.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                if node.func.id == "bind_task_data_path":
                    binds[rel] = binds.get(rel, 0) + 1
                elif node.func.id in {
                    "resolve_task_data_path",
                    "resolve_bound_task_data_path",
                    # Step 12 / PR-12bc: the composed-caller variant, which
                    # REFUSES the regime-A fallback. Tracked here too — a
                    # resolve that this census could not see would be a
                    # resolve the census does not constrain.
                    "require_bound_task_data_path",
                }:
                    if _enclosing_function(tree, node) in child_side_functions:
                        continue
                    resolves[rel] = resolves.get(rel, 0) + 1

        assert binds == {
            # C2: the composition edge's ExitStack — the ONE place a composed
            # run's authorities are activated. A second bind site anywhere
            # else would mean two answers to "what is this run bound to".
            "src/workflows/task_composition.py": 1
        }, f"an unexpected parent-side bind site appeared; found {binds}"
        assert resolves == {
            # Pre-existing (D14-1 C5), and already binding-aware.
            "src/agent/skills/evaluate_time_skill/wrapper.py": 1,
            # C1: the composition edge's own idempotent re-resolution.
            "src/workflows/task_composition.py": 1,
            # Step 12 / PR-12bc. EXTENDED deliberately, never exempted by name
            # (the Step-11 C9 rule). Two parent-side resolves were added, and
            # both are asking the BOUND implementation for something only it
            # can answer — which is the opposite of turning an id back into an
            # implementation, the thing this census exists to forbid:
            #
            #   B5  scope_acquisition — the composed run's scopes must be
            #       BUILT by the task; presence comes from the input
            #       projection first, so an un-composed run never resolves.
            #   B7  the tuner's trial-anchoring resolution — the task names
            #       its own anchor artifact instead of the tuner inlining
            #       TIDMAD's filename. Same presence-first rule.
            #   F2  the run binding carries the task codec to round-boundary
            #       Health without re-resolving it per candidate.
            #   #389 probe-data projection — the isolated resource worker
            #       must receive the active task's semantic inference-batch
            #       maximum instead of selecting from memory evidence alone.
            "src/nodes/ml_hyperparameter_tune_agent/scope_acquisition.py": 1,
            "src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py": 2,
            "src/nodes/ml_hyperparameter_tune_agent/probe_data.py": 1,
        }, f"an unexpected parent-side resolve appeared; found {resolves}"

    def test_the_workflow_itself_resolves_no_task_data_path(self):
        """§5.2a's sharp edge, stated where it can fail.

        ``run_workflow`` must CONSUME the resolved implementation the
        composition carries. The moment it turns an id back into an
        implementation, the composition has stopped being the single
        resolution and the object the parent binds can differ from the one
        the child resolves — a divergence every id comparison would still
        report as fine.
        """
        tree = ast.parse(
            (REPO_ROOT / "src/workflows" / "model_exploration.py").read_text(encoding="utf-8")
        )
        offenders = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"resolve_task_data_path", "resolve_bound_task_data_path"}
        ]
        assert offenders == [], (
            f"model_exploration.py resolves a task data path ({offenders}); it "
            "must consume RunTaskComposition.task_data_path instead."
        )

    def test_all_three_children_already_parse_the_flag(self):
        """The consumer side that the emission will land against. If a child
        stopped parsing it, C3's reachability proof would silently degrade
        into 'the parent emits into the void'."""
        from execute_tools.task_data_path import TASK_DATA_PATH_ARGV_FLAG

        for rel in (
            "src/execute_tools/train_engine_sandbox.py",
            "src/execute_tools/inference_single.py",
            "src/execute_tools/denoising_score_single.py",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert f'"{TASK_DATA_PATH_ARGV_FLAG}"' in text, f"{rel} stopped parsing the flag"


# ---------------------------------------------------------------------------
# Census C — the un-composed child argv vectors
# ---------------------------------------------------------------------------

EXP_ID = "c0exp"
RUN_NAME = "c0run"
MODEL_TYPE = "fcnet"
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}


def _mock_result(returncode: int = 0):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = "done\n"
    mock.stderr = ""
    return mock


@pytest.fixture
def sandbox(tmp_path):
    from core.sandbox_executor import TidmadSandbox

    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)


def _launch_ok(sandbox):
    def _side_effect(*_args, **_kwargs):
        os.makedirs(sandbox.dirs["models"], exist_ok=True)
        with open(os.path.join(sandbox.dirs["models"], f"_OK_{EXP_ID}"), "wb"):
            pass
        return _mock_result(), None

    return _side_effect


def capture_uncomposed_child_argv(sandbox, tmp_path) -> dict[str, list[str]]:
    """The three real argv vectors, normalized for machine-local paths.

    Shared with C3, which asserts these exact vectors are unchanged on the
    un-composed path after the emission lands.
    """
    root = os.path.abspath(str(tmp_path))

    def _norm(cmd: list[str]) -> list[str]:
        return [
            "<PYTHON>" if tok == sys.executable else str(tok).replace(root, "<WS>") for tok in cmd
        ]

    vectors: dict[str, list[str]] = {}

    with patch("core.sandbox_executor._run_observed_subprocess") as mock_run:
        mock_run.side_effect = _launch_ok(sandbox)
        sandbox.execute_training(EXP_ID, RUN_NAME, MODEL_TYPE, MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        (cmd,), _ = mock_run.call_args
        vectors["training"] = _norm(cmd)

    with patch("core.sandbox_executor._run_observed_subprocess") as mock_run:
        mock_run.side_effect = _launch_ok(sandbox)
        sandbox.execute_inference(EXP_ID, RUN_NAME, MODEL_TYPE, MODEL_CFG, LOSS_CFG)
        (cmd,), _ = mock_run.call_args
        vectors["inference"] = _norm(cmd)

    with patch("core.sandbox_executor.subprocess.run") as mock_run:
        mock_run.return_value = _mock_result()
        sandbox.execute_scoring(EXP_ID, RUN_NAME, MODEL_TYPE, MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        (cmd,), _ = mock_run.call_args
        vectors["scoring"] = _norm(cmd)

    return vectors


# ---------------------------------------------------------------------------
# The parity instrument itself must be discriminative
# ---------------------------------------------------------------------------


class TestParityManifestIsDiscriminative:
    """The mandatory parity evidence is only as strong as its reducer.

    A reducer that dropped a dimension would report PASS for a real
    LLM-facing change — the exact failure the design forbids being papered
    over. So each of the seven dimensions is mutated in turn and must be
    reported. This is the counterfactual for the C6 acceptance criterion,
    not decoration.
    """

    @staticmethod
    def _capture() -> dict:
        return {
            "terminated_with": None,
            "captures": [
                {
                    "method": "generate",
                    "label": "proposer.proposing",
                    "system": "SYSTEM-A",
                    "user": "USER-A",
                    "kwargs": {"schema": {"k": 1}},
                },
                {
                    "method": "generate_text",
                    "label": "interpretation.per_model",
                    "system": "SYSTEM-B",
                    "user": "USER-B",
                    "kwargs": {},
                },
            ],
        }

    def test_an_identical_capture_reports_no_differences(self):
        from tests.helpers.step10_p1_parity_manifest import build_manifest, diff_manifests

        base = build_manifest(self._capture())
        head = build_manifest(self._capture())
        assert diff_manifests(base, head) == []
        assert base["manifest_sha256"] == head["manifest_sha256"]

    @pytest.mark.parametrize(
        ("mutate", "dimension"),
        [
            (lambda c: c["captures"].append(dict(c["captures"][0])), "call count"),
            (lambda c: c["captures"][0].update(method="tool_call"), "method"),
            (lambda c: c["captures"][0].update(label="proposer.comparison"), "label"),
            (lambda c: c["captures"][0].update(system="SYSTEM-A "), "system_bytes"),
            (lambda c: c["captures"][0].update(system="SYSTEM-B"), "system_sha256"),
            (lambda c: c["captures"][0].update(user="USER-A!"), "user_bytes"),
            (lambda c: c["captures"][0].update(user="USER-Z"), "user_sha256"),
            (lambda c: c["captures"][0]["kwargs"].update(schema={"k": 2}), "kwargs_sha256"),
            (lambda c: c.update(terminated_with="RuntimeError"), "termination"),
            (
                lambda c: c["captures"].reverse(),
                "label",
            ),
        ],
    )
    def test_every_dimension_change_is_reported(self, mutate, dimension):
        from tests.helpers.step10_p1_parity_manifest import build_manifest, diff_manifests

        base = build_manifest(self._capture())
        mutated = self._capture()
        mutate(mutated)
        head = build_manifest(mutated)

        problems = diff_manifests(base, head)
        assert problems, f"a {dimension} change went unreported by the parity reducer"
        assert any(dimension in problem for problem in problems), (
            f"the reducer noticed a change but not as {dimension}: {problems}"
        )
        assert base["manifest_sha256"] != head["manifest_sha256"]


class TestParityBaselineArtifact:
    def test_the_committed_baseline_is_self_consistent(self):
        """The committed manifest's recorded sha256 is the digest of its own
        canonical content — so a hand-edited baseline cannot silently become
        the thing C6 compares against."""
        from tests.helpers.step10_p1_parity_manifest import _canonical, _sha

        payload = json.loads(
            (
                REPO_ROOT
                / "tests"
                / "unit"
                / "workflows"
                / "goldens"
                / "step10_p1_c0_llm_parity_baseline.json"
            ).read_text(encoding="utf-8")
        )
        recorded = payload.pop("manifest_sha256")
        assert _sha(_canonical(payload)) == recorded
        assert payload["call_count"] == 16


# ---------------------------------------------------------------------------
# Census D — the legacy run-invariants lock key set
# ---------------------------------------------------------------------------


class TestCensusDLegacyLockKeySet:
    def test_the_serialized_legacy_lock_has_exactly_these_keys(self, tmp_path):
        """§5.9's absent-key contract is about SERIALIZED BYTES. Recording the
        key set here is what makes 'the composition key is absent, never
        null' provable at C5 rather than merely intended."""
        from core.run_invariants import RunInvariants, write_run_invariants

        invariants = RunInvariants(
            resolved_data_scope=[0, 1],
            health_gate_enabled=False,
            health_config_sha256=None,
            runtime_estimator_identity="est-1",
            runtime_policy_identity="pol-1",
        )
        path = write_run_invariants(str(tmp_path / "ws"), invariants)
        payload = json.loads(Path(path).read_text(encoding="utf-8"))

        assert set(payload) == {
            "resolved_data_scope",
            "health_gate_enabled",
            "health_config_sha256",
            "ordering_override_strategy",
            "ordering_override_file_order",
            "structured_health_feedback_enabled",
            "health_feedback_history_window_iterations",
            "health_feedback_history_max_entries_per_model",
            "runtime_estimator_identity",
            "runtime_policy_identity",
            "created_at",
        }

    def test_the_canonical_equality_set_is_pinned(self):
        """A composed run's fingerprint joins this set. Pinning the set is what
        makes that addition visible as a deliberate change rather than an
        incidental one — and the census DID fire when C2 added it, which is
        the census working.

        Membership here is what makes a composed resume fail closed on a
        changed fingerprint: ``validate_run_invariants`` compares exactly
        these fields.

        DECLARED DELTA (arXiv U1/U3, #253/#254/#260; the census fired again
        at final integration — working as designed): four canonical fields
        joined — ``lit_review_enabled`` + ``lit_review_config_sha256`` (the
        run's workflow topology; a WITH/WITHOUT-arm resume must refuse to
        cross), ``experiment_arm`` (the OPAQUE label — canonical so two arms
        cannot be resumed into one another, never read for behaviour, ruling
        R2), and ``baseline_isolation`` (the WITHOUT arm's explicit behaviour
        flag; a toggle on one workspace is a different experiment). All four
        are omitted-at-default in the serialized lock, so every legacy lock
        file stays byte-identical.

        DECLARED DELTA (F-SCANH-1, wave2 R1; the census fired again —
        working as designed): ``task_config_sha256`` joined — the sha256 of
        the raw ``configs/task_config.yaml`` bytes an UN-COMPOSED run's
        prompt surfaces read. It was the ONE tracked config the lock did
        not pin, and ``_snapshot_task_config`` is first-writer-wins, so a
        mid-workspace operator edit reached the LLM with no refusal.
        ``None`` for composed runs (identity = the fingerprint) and legacy
        locks; omitted-at-``None`` in the serialized lock, so those bytes
        are unchanged.

        DECLARED DELTA (Gold campaign, advice-invariant; the census fired
        again — working as designed): ``advice_sha256`` joined — the
        OBSERVED sha256 of the advice-artifact bytes a run consumed. The
        campaign's arm LABEL was pinned while the treatment that label names
        was not, so two workspaces reading different advice compared as one
        experiment. Unlike ``task_config_sha256``, this field is OPTIONAL —
        a run that consumes no advice resolves ``None`` and a legacy lock
        parses to ``None``, so ordinary ``!=`` over ``str | None`` yields
        the operator's required table (absent/absent COMPATIBLE; A/A
        COMPATIBLE; A/B, A/absent and absent/A all REFUSE) and every
        no-advice workspace stays resumable. Its sibling ``advice_path`` is
        ``_PROVENANCE``, not here: path proves authority and reachability,
        the observed digest proves treatment identity.

        DECLARED DELTA (F-SCANF-1, D-FAIL-7 known_gap G4; the census fired
        again — working as designed): ``formal_eval_portion`` joined — the
        FRACTION of the eval scope a FORMAL round scores over. It was
        RECORDED as per-file-best provenance and existed as a CLI argument,
        but was a declared invariant nowhere, so two iterations whose formal
        evaluation covered different fractions of the data folded into one
        incumbent with no refusal. Aggregate scalars are only comparable
        within one evaluation scope, which is `resolved_data_scope`'s rule
        one axis over. It is the first NUMERIC canonical field, and its
        default is the framework's own full-eval 1.0 rather than a `None`
        sentinel: every entry point resolves a real float, so an optional
        declaration in the ``advice_sha256`` mould would refuse EVERY
        pre-existing workspace's resume. Omitted-at-1.0 in the serialized
        lock, so legacy and full-eval lock bytes are unchanged, and the new
        refusal is confined to workspaces declaring a NON-DEFAULT portion."""
        from core.run_invariants import RunInvariants

        assert RunInvariants._CANONICAL == (
            "resolved_data_scope",
            "health_gate_enabled",
            "health_config_sha256",
            "ordering_override_strategy",
            "ordering_override_file_order",
            "structured_health_feedback_enabled",
            "health_feedback_history_window_iterations",
            "health_feedback_history_max_entries_per_model",
            "runtime_estimator_identity",
            "runtime_policy_identity",
            "task_composition_fingerprint",
            # F-SCANH-1 — the declared delta documented above.
            "task_config_sha256",
            # arXiv U1/U3 — the declared delta documented above.
            "lit_review_enabled",
            "lit_review_config_sha256",
            "experiment_arm",
            "baseline_isolation",
            # Gold campaign — the declared delta documented above.
            "advice_sha256",
            # F-SCANF-1 — the declared delta documented above.
            "formal_eval_portion",
            # Workflow rules determine the executed plan and are compared.
            "workflow_parameter_rules",
            "trial_time_admission_source",
            "formal_time_admission_source",
        )
