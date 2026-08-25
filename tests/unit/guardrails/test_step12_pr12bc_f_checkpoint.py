"""Step 12 / PR-12bc — the §F B→C checkpoint's two censuses, made permanent.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §F items 8 and 9; ledger §Q.F.

The §F checkpoint is a one-time gate between the phases, but two of its ten
proofs are properties that must keep holding for the rest of the PR — and for
everything after it. A checkpoint verified once and never again is a claim,
not a guard, so both are censuses here:

* **item 8** — no UNCONDITIONAL TIDMAD scope construction remains where
  Phase B owns it;
* **item 9** — no hidden task/scope identity dispatch was introduced.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: Every production site that constructs a `TidmadScope`, and WHY each is
#: legitimate. A new site not on this list fails the census — which is the
#: point: "unconditional" is a property of the SITE, so the sites are named.
SANCTIONED_TIDMAD_SCOPE_SITES = {
    # TIDMAD's own module. Its capability BUILDS TidmadScopes; that is the
    # whole point of B3, and a task constructing its own scope type is not a
    # framework assumption.
    "execute_tools/tidmad_data_path.py",
    # The engine's two regime-A fallbacks. Both are `is None`-guarded, so a
    # transported scope is never overwritten — asserted below.
    "execute_tools/train_engine_sandbox.py",
    # The measurement path's regime-A construction, reached only after B7's
    # topology guard has confirmed the run declares TIDMAD's geometry.
    "agent/skills/evaluate_time_skill/wrapper.py",
}


def _production_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.split()
    return [f for f in out if not f.startswith("tests/")]


class TestItem8NoUnconditionalTidmadScopeConstruction:
    def test_the_construction_sites_are_exactly_the_sanctioned_ones(self):
        found = set()
        for rel in _production_files():
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            if "TidmadScope(" not in src:
                continue
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "TidmadScope"
                ):
                    found.add(rel)
        assert found == SANCTIONED_TIDMAD_SCOPE_SITES, (
            f"the set of TidmadScope construction sites changed: {sorted(found)}. "
            f"A new site is a new place the framework can assume TIDMAD's scope "
            f"shape — name it here with its reason, or remove it."
        )

    def test_both_engine_fallbacks_are_guarded_by_scope_ABSENCE(self):
        """The substantive half of item 8. A transported scope must never be
        overwritten by the regime-A construction, and `is None` is what makes
        that true rather than hoped for.

        Step 12 / PR-12d F-12d-34: this census used to COUNT `if <scope> is
        None:` blocks whose body TEXT contained ``TidmadScope(``, and expect
        exactly 2. Extracting one construction into ``_regime_a_train_scope``
        — a behaviour-preserving change that left the guard exactly where it
        was — turned it RED, because what it actually asserted was a SYNTACTIC
        LOCATION, not the invariant.

        The invariant is *every* regime-A construction is reachable only when
        the transported scope is ABSENT. So each construction is now proven
        dominated by such a guard in one of two ways: lexically inside the
        guard's body, or inside a helper whose EVERY call site is. A helper
        with one unguarded call site fails — which is the hole an "or it's in
        a helper" relaxation would have opened.
        """
        src = (REPO_ROOT / "execute_tools" / "train_engine_sandbox.py").read_text(encoding="utf-8")
        tree = ast.parse(src)

        def _is_scope_absence_guard(node: ast.AST) -> bool:
            if not isinstance(node, ast.If):
                return False
            test = node.test
            return (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id in {"task_scope", "task_eval_scope"}
                and isinstance(test.ops[0], ast.Is)
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value is None
            )

        # Every node that sits inside the body of a scope-absence guard.
        guarded_nodes: set[int] = set()
        for node in ast.walk(tree):
            if _is_scope_absence_guard(node):
                for stmt in node.body:
                    guarded_nodes.update(id(d) for d in ast.walk(stmt))

        # Enclosing function of every node, so a construction can name its owner.
        enclosing: dict[int, ast.FunctionDef] = {}
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in ast.walk(fn):
                    enclosing.setdefault(id(d), fn)

        def _calls_to(name: str) -> list[ast.Call]:
            return [
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
            ]

        constructions = _calls_to("TidmadScope")
        assert len(constructions) == 2, (
            f"expected exactly 2 regime-A TidmadScope constructions in the training "
            f"engine; found {len(constructions)}. A new one is a new place the "
            f"framework can overwrite a transported scope."
        )

        for call in constructions:
            if id(call) in guarded_nodes:
                continue  # dominated lexically
            owner = enclosing.get(id(call))
            assert owner is not None, (
                "a module-level TidmadScope construction is reachable unconditionally"
            )
            call_sites = _calls_to(owner.name)
            assert call_sites, (
                f"{owner.name} constructs a TidmadScope but is never called from this "
                f"module — an unreachable fallback is not a guarded one"
            )
            unguarded = [c for c in call_sites if id(c) not in guarded_nodes]
            assert not unguarded, (
                f"{owner.name} constructs a regime-A TidmadScope and has "
                f"{len(unguarded)} call site(s) NOT inside an `if <scope> is None:` "
                f"guard. Every path to it must first establish that no scope was "
                f"transported, or a composed run's scope is silently overwritten."
            )

    def test_the_measurement_path_checks_the_topology_first(self):
        """The third site. It builds a TidmadScope only after confirming the
        run's profile actually declares TIDMAD's geometry — otherwise it
        refuses with a NAMED reason rather than measuring the wrong thing.

        DEFECT THIS TEST ALONE CATCHES
            The measurement path constructing a regime-A ``TidmadScope`` for a
            run whose profile never declared TIDMAD's geometry, or doing so
            without leaving a named reason behind when it declines.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            Deleting the membership test, or moving it below the construction,
            makes ``membership < build`` false. Removing the refusal's named
            reason empties ``reasons``.

        C12-P / F-C12P-12BC-1 — re-anchored, deliberately NOT weakened.
        This used to read::

            guard = src.index("tidmad_topology(profile)")
            assert "measurement SKIPPED" in src[guard : guard + 600]

        Two independent defects, both of the "census matches a token exactly"
        shape this repository has been burned by before:

        1. ``declares_tidmad_topology(profile)`` — the MEMBERSHIP authority
           C12-P introduced — *contains* the substring ``tidmad_topology(
           profile)``. So ``str.index`` silently stopped anchoring on the
           raising call it was written for and began anchoring on the
           membership test that now precedes it. The guard was passing, but
           measuring something other than what it names. Had the membership
           test later been removed, the window would have slid BACK to the
           raising call and the guard could have gone green for the wrong
           reason — the dangerous direction.
        2. It pinned one PROSE SENTENCE. C12-P's frozen taxonomy renamed the
           semantic-non-membership refusal to ``NOT APPLICABLE`` (absent =>
           NOT_APPLICABLE; malformed => loud ERROR). The concept the guard
           exists to protect was unchanged; only the vocabulary moved.

        The load-bearing property — *the refusal precedes the construction it
        protects* — is unchanged and still asserted. What is no longer
        asserted is one particular English sentence.
        """
        src = (REPO_ROOT / "agent" / "skills" / "evaluate_time_skill" / "wrapper.py").read_text(
            encoding="utf-8"
        )
        build = src.index("TidmadScope(")

        # Anchor on the MEMBERSHIP authority explicitly, so the anchor cannot
        # drift onto a different call whose text happens to contain it.
        membership = src.index("declares_tidmad_topology(profile)")
        assert membership < build, (
            "the topology membership test must precede the TidmadScope construction it protects"
        )

        # The named reason, asserted as a CONCEPT rather than as one sentence:
        # the refusal must say the measurement is not being performed AND why.
        window = src[membership : membership + 600]
        reasons = [
            phrase for phrase in ("NOT APPLICABLE", "measurement SKIPPED") if phrase in window
        ]
        assert reasons, (
            "the measurement path declines without a named reason. It must "
            "state that it is not measuring and why; a silent early return is "
            "the exact harm this guard exists to prevent."
        )
        assert "topology" in window or "psd_segment_length" in window, (
            "the refusal names no cause. A reason that does not say WHICH "
            "declaration was missing cannot be acted on by the operator."
        )


#: The generic tree. TIDMAD's own module, the contrast tasks' own modules and
#: the task-owned packs are excluded BY OWNERSHIP: a task naming itself is not
#: dispatch, it is a declaration.
#: **F-12bc-9** — `execute_tools/` was missing here, and the omission was
#: self-evidencing: `TASK_OWNED` below exempts three `execute_tools/` files,
#: and those exemptions could never fire, because nothing under that directory
#: was ever scanned. An exclusion list that cannot exclude anything is a
#: statement about what the author meant to scan.
#:
#: It matters more than a coverage gap. `execute_tools/` is where the scope ABI
#: lives — `scope_artifact.py`, `task_data_path.py` — so the single most
#: important generic surface in this PR was the one this census could not see.
#: Found at BC-FINAL by planting `"tidmad_scope_v1"` into `scope_artifact.py`
#: and watching every census stay green.
#:
#: The landed tree is clean under the wider scope: 52 additional files, zero
#: offenders in all three checks. Nothing is exempted to make that true.
GENERIC_PREFIXES = ("core/", "workflows/", "nodes/", "agent/", "execute_tools/")
TASK_OWNED = (
    "execute_tools/tidmad_data_path.py",
    "execute_tools/pets_data_path.py",
    "execute_tools/davis_data_path.py",
)
TASK_NAMES = {"tidmad", "oxford_iiit_pet", "davis_future_prediction", "pets", "davis"}


class TestItem9NoHiddenTaskOrScopeIdentityDispatch:
    def test_no_generic_module_compares_against_a_task_name(self):
        offenders: list[str] = []
        for rel in _production_files():
            if not rel.startswith(GENERIC_PREFIXES) or rel in TASK_OWNED:
                continue
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    for comparator in node.comparators:
                        if isinstance(comparator, ast.Constant) and comparator.value in TASK_NAMES:
                            offenders.append(f"{rel}:{node.lineno}")
        assert offenders == [], (
            f"{offenders} branch on a TASK NAME. Discrimination is by "
            f"composition PRESENCE or by what the task DECLARES — never by "
            f"who the task is."
        )

    def test_no_central_task_mapping_table_exists(self):
        """The `{"tidmad": ..., "pets": ...}` catalog, forbidden by
        construction. A dict LITERAL keyed by two or more task names is a
        central catalog however it is spelled.
        """
        offenders: list[str] = []
        for rel in _production_files():
            if not rel.startswith(GENERIC_PREFIXES) or rel in TASK_OWNED:
                continue
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    keys = {
                        k.value
                        for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
                    if len(keys & TASK_NAMES) >= 2:
                        offenders.append(f"{rel}:{node.lineno}")
        assert offenders == [], f"{offenders} declare a central task mapping table."

    def test_no_scope_kind_dispatch_in_generic_core(self):
        """Each task's payload is self-identifying so IT can refuse a foreign
        one. The FRAMEWORK must never branch on that tag — doing so would make
        the transport aware of the shapes it exists to stay ignorant of.
        """
        offenders: list[str] = []
        for rel in _production_files():
            if not rel.startswith(GENERIC_PREFIXES) or rel in TASK_OWNED:
                continue
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for kind in ("tidmad_scope_v1", "pets_scope_v1", "davis_scope_v1"):
                if kind in src:
                    offenders.append(f"{rel}: {kind}")
        assert offenders == [], f"{offenders} name a scope KIND in generic core."

    def test_the_scope_transport_never_inspects_a_payload(self):
        """The ABI's own opacity, re-asserted at the checkpoint: the framework
        handles bytes and a hash.
        """
        tree = ast.parse(
            (REPO_ROOT / "execute_tools" / "scope_artifact.py").read_text(encoding="utf-8")
        )
        called = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "loads" not in called and "load" not in called


@pytest.mark.parametrize(
    ("rel", "needle", "label"),
    [
        (
            "workflows/task_composition.py",
            "if declared in registered_task_data_path_ids():",
            "F-12-3 early return",
        ),
        (
            "execute_tools/task_data_path.py",
            "_REGISTRY: dict[str, TaskDataPath] = {}",
            "the registry",
        ),
        (
            "execute_tools/task_data_path.py",
            "is already registered with DIFFERENT",
            "duplicate refusal (C1: two-phase — identical content is idempotent)",
        ),
        (
            "tests/unit/workflows/test_step10_p1_c1_composition.py",
            "def test_recomposing_in_one_process_yields_the_REGISTERED_object",
            "F-12bc-3 pinning test",
        ),
        (
            "tests/unit/guardrails/test_task_data_path_census.py",
            "def test_task_implementation_imports_on_the_surface_are_the_declared_set",
            "F-12bc-4 bootstrap census",
        ),
    ],
)
def test_item10_phase_c_anchors_still_exist(rel, needle, label):
    """§F item 10 — Phase C's assumptions, re-audited against the ACTUAL
    Phase-B implementation rather than against pre-B source.

    Anchored on CONTENT, not line numbers: Phase B moved several of these
    (the registry went from `:219` to `:570` as `task_data_path.py` grew), and
    a line-number assertion would fail for a reason that has nothing to do
    with the property.
    """
    assert needle in (REPO_ROOT / rel).read_text(encoding="utf-8"), (
        f"{label} is gone from {rel} — Phase C's plan assumes it is there."
    )
