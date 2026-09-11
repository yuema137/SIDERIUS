"""Step 11 — the structural tripwire, and what became of the C0 guards.

This module opened the PR carrying four **INVERTED GUARDS** — tests that
asserted a named defect was PRESENT — so that each fixing commit would
flip a named test rather than add an unanchored new one.

**All four are now resolved, and per R-11-10 none was twinned:**

===========  ================================================  ===========
defect       what replaced its guard                           flipped by
===========  ================================================  ===========
F-11-2       the derived `subprocess.Popen` env census in       C1
             `test_measurement_worker_plugin_transport.py`
F-11-1       the one-consuming-authority census below, plus     C2
             `test_step11_c2_host_oom_consumer.py`
malformed    `TestMalformedOverrideRefusesLoudly`, rewritten    C3
RSS override in place in `test_step11_c0_baselines.py`
F-11-8       `TestTheSpawnParentIsCensused` below               C9
===========  ================================================  ===========

What survives here is what still owns a property: the residual censuses,
and the structural budget.

**THE STRUCTURAL BUDGET** was never inverted. It records the R-11-11
measurement at the frozen base `c1caa609` so C9 can compare. It is a
tripwire, not a target: growth is the signal to extract a responsibility,
and shrinkage is the direction the rule wants.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


# ----------------------------------------------------------------------
# R-11-11 — structural baseline (NOT inverted; C9 compares against it)
# ----------------------------------------------------------------------

_SANDBOX = REPO_ROOT / "src/core" / "sandbox_executor.py"

# Frozen at base `c1caa609`. Reproduces §4a R-11-11 exactly.
#   name -> (stmts, branch, loc, params)
#
# Line numbers are deliberately NOT frozen. The C0 version of this file
# pinned them and the exact file LOC, which made every legitimate edit
# elsewhere in the module RED — C3 removed 35 lines of stale calibration
# prose and turned five of these tests red while changing no function's
# shape at all. That is a tripwire firing on the wrong signal.
#
# R-11-11's actual contract is a BUDGET, not a snapshot: *"if a commit
# would add a new branch family, a new schema resolution, or ~80-150 lines
# to one function, extract first."* Growth is the signal; shrinkage is
# always fine. C9 re-measures and records the real numbers.
STRUCTURAL_BASELINE: dict[str, tuple[int, int, int, int]] = {
    "TidmadSandbox.execute_training": (92, 39, 357, 14),
    "TidmadSandbox.execute_inference": (69, 28, 253, 9),
    "_run_observed_subprocess": (62, 27, 186, 9),
    "TidmadSandbox.__init__": (22, 6, 87, 12),
}

FILE_LOC_BASELINE = 2456

#: Growth beyond these deltas means "extract the responsibility first".
#: Derived from R-11-11's own wording: a "family" of branches is a group
#: rather than one `if`, and 80 is the lower bound it names for lines.
MAX_BRANCH_GROWTH = 3
MAX_LOC_GROWTH = 80
MAX_PARAM_GROWTH = 1
#: The file may absorb a bounded amount before the budget is a C9 decision.
MAX_FILE_LOC_GROWTH = 150

_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.IfExp,
    ast.Assert,
    ast.BoolOp,
    ast.comprehension,
    ast.Match,
    ast.match_case,
)


def measure(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, int, int, int]:
    """(stmts, branch, loc, params) for one function definition.

    ``stmts`` counts every statement in the subtree INCLUDING the ``def``
    itself and EXCLUDING nested definitions, which is the definition that
    reproduces §4a's published numbers. ``branch`` counts branching and
    context nodes. ``params`` counts every declared parameter including
    ``*args`` / ``**kwargs``.
    """
    stmts = 0
    branch = 0
    for node in ast.walk(fn):
        if node is not fn and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        if isinstance(node, ast.stmt):
            stmts += 1
        if isinstance(node, _BRANCH_NODES):
            branch += 1
    args = fn.args
    params = (
        len(args.posonlyargs)
        + len(args.args)
        + len(args.kwonlyargs)
        + (1 if args.vararg else 0)
        + (1 if args.kwarg else 0)
    )
    assert fn.end_lineno is not None
    return stmts, branch, fn.end_lineno - fn.lineno + 1, params


def _qualified_functions(path: pathlib.Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[f"{prefix}{child.name}"] = child

    visit(tree, "")
    return out


def current_structure() -> dict[str, tuple[int, int, int, int]]:
    """The live measurement, for C9's recorded comparison."""
    fns = _qualified_functions(_SANDBOX)
    return {name: measure(fns[name]) for name in STRUCTURAL_BASELINE}


class TestStructuralBudget:
    """R-11-11: `sandbox_executor.py` stays a launch CONSUMER.

    A tripwire, not a target. It fires on GROWTH — the signal that a
    responsibility should have been extracted into a sibling module before
    the code was added — and is silent on shrinkage, which is the
    direction the rule wants.
    """

    def test_the_file_has_not_grown_past_its_budget(self):
        current = len(_SANDBOX.read_text(encoding="utf-8").splitlines())
        assert current <= FILE_LOC_BASELINE + MAX_FILE_LOC_GROWTH, (
            f"core/sandbox_executor.py is {current} LOC vs the C0 baseline "
            f"{FILE_LOC_BASELINE}. R-11-11: extract the responsibility into a "
            f"sibling module instead of growing the launch consumer."
        )

    @pytest.mark.parametrize("name", sorted(STRUCTURAL_BASELINE))
    def test_no_function_grew_past_its_budget(self, name):
        # `stmts` is measured and reported by `current_structure()` for
        # C9's recorded comparison; the BUDGET is expressed over branch,
        # LOC and params, which is what R-11-11's wording names.
        _, branch, loc, params = current_structure()[name]
        _, base_branch, base_loc, base_params = STRUCTURAL_BASELINE[name]
        assert branch - base_branch <= MAX_BRANCH_GROWTH, (
            f"{name} gained {branch - base_branch} branch nodes "
            f"({base_branch} -> {branch}) — that is a new branch family. "
            f"Establish the boundary first (R-11-11)."
        )
        assert loc - base_loc <= MAX_LOC_GROWTH, (
            f"{name} grew {loc - base_loc} lines ({base_loc} -> {loc}). "
            f"R-11-11: extract before adding."
        )
        assert params - base_params <= MAX_PARAM_GROWTH, (
            f"{name} gained {params - base_params} parameters "
            f"({base_params} -> {params}); `execute_training` was already at 14."
        )

    def test_the_baseline_is_the_frozen_c0_measurement(self):
        """Pins the numbers §4a publishes, so the budget is measured against
        the design's own figures and not against a drifting snapshot.
        """
        assert STRUCTURAL_BASELINE["TidmadSandbox.execute_training"] == (92, 39, 357, 14)
        assert STRUCTURAL_BASELINE["TidmadSandbox.execute_inference"] == (69, 28, 253, 9)
        assert STRUCTURAL_BASELINE["_run_observed_subprocess"] == (62, 27, 186, 9)
        assert STRUCTURAL_BASELINE["TidmadSandbox.__init__"] == (22, 6, 87, 12)
        assert FILE_LOC_BASELINE == 2456

    def test_every_baselined_function_still_exists(self):
        """A budget over a function that was renamed away would pass by
        vacuously measuring nothing.
        """
        assert set(current_structure()) == set(STRUCTURAL_BASELINE)


# ----------------------------------------------------------------------
# F-11-1 — RESOLVED by C2; the guard was flipped, not duplicated
# ----------------------------------------------------------------------
#
# R-11-10: the pre-fix "nobody reads this status" census is GONE. Its
# permanent replacement is
# `tests/unit/agent/tune_ml_hyperparam_agent/test_step11_c2_host_oom_consumer.py`,
# which owns the consumer contract, the two production branch sites, the
# record classification and the Q-11-3 = A prompt-byte boundary.
#
# What stays here is the census's residual value: the producer side has
# exactly three sites and exactly ONE consuming authority, so a fourth
# independently-spelled comparison cannot creep back in.

_OOM_STATUS = "oom_host_ram"
_OOM_PRODUCER = REPO_ROOT / "src/core" / "sandbox_executor.py"
_TUNER_NODE = REPO_ROOT / "src/nodes" / "ml_hyperparameter_tune_agent"


def _code_string_literals(path: pathlib.Path) -> set[str]:
    """Every string CONSTANT in a module, minus docstrings.

    Comments never reach the AST at all, so prose about a status is
    excluded for free and no file needs to appear on an allow-list.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - defensive
        return set()
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


class TestTheHostOomStatusHasExactlyOneConsumingAuthority:
    """One producer module, one consumer authority — no third speller.

    The defect existed because producer and consumer never shared a name.
    """

    def test_the_producer_side_is_unchanged(self):
        src = _OOM_PRODUCER.read_text(encoding="utf-8")
        assert src.count(f'status = "{_OOM_STATUS}" if _is_oom_failure(e) else "error"') == 3

    def test_exactly_one_production_module_spells_the_status_in_code(self):
        """Scope, stated explicitly: every non-test `.py` under the
        production roots — the same walk the pre-fix census used, so the
        two are comparable.

        It counts the status as a **code literal**, excluding comments and
        docstrings, which is what makes the census exact rather than
        name-exempt: `failure_attribution.py` discusses the status in prose
        and needs no entry on any allow-list, and neither does the comment
        at the tuner's own branch site. A `== "oom_host_ram"` anywhere
        would be a code literal and would turn this RED.
        """
        namers: list[str] = []
        for root in (
            "src/core",
            "src/execute_tools",
            "src/agent",
            "src/nodes",
            "src/workflows",
            "src/dashboard",
        ):
            for path in sorted((REPO_ROOT / root).rglob("*.py")):
                if path == _OOM_PRODUCER:
                    continue
                if _OOM_STATUS in _code_string_literals(path):
                    namers.append(str(path.relative_to(REPO_ROOT)))
        assert namers == ["src/nodes/ml_hyperparameter_tune_agent/records.py"], (
            "the status must be spelled in exactly one consumer authority; a "
            f"second speller is how F-11-1 happened. Found: {namers}"
        )

    def test_the_tag_matcher_stays_device_oom_only(self):
        """`_is_cuda_oom` must never match a host OOM: that is what keeps
        the record out of the `_oom` family and the planner note unrendered
        (Q-11-3 = A). C2 must not blur the distinction it preserves.
        """
        from nodes.ml_hyperparameter_tune_agent.records import _is_cuda_oom

        assert _is_cuda_oom("CUDA out of memory") is True
        assert _is_cuda_oom("torch.cuda.OutOfMemoryError") is True
        assert _is_cuda_oom("[oom_host_ram] Host RAM exhaustion detected") is False


# ----------------------------------------------------------------------
# F-11-2 — RESOLVED by C1; the guard was flipped, not duplicated
# ----------------------------------------------------------------------
#
# R-11-10: this commit's inverted guard is GONE, not kept beside a
# post-fix twin. Its permanent replacement is the derived contract census
# in `tests/unit/core/test_measurement_worker_plugin_transport.py::
# TestEveryProductionWorkerSpawnerTransportsTheEnvironment`, which owns a
# strictly stronger property — EVERY production `subprocess.Popen` passes
# `env=`, derived by AST rather than enumerated — plus a behavioural
# assertion that the isolated pre-flight transports the RUN-SCOPED dirs
# and a signature assertion that the production entrypoint cannot omit
# them.
#
# The one fact worth keeping here is the reason the defect survived a
# guard that existed to catch it.


class TestWhyTheEnvTransportDefectSurvived:
    """The escaped-defect record, kept because it is the lesson.

    The pre-C1 guard asserted the substring ``"env=subprocess_env("`` in
    ONE file, addressed by path. A second production spawner one directory
    along had the exact omission, and the guard stayed green — the
    F-P2b-4 shape recorded in Step 10.
    """

    def test_the_replacement_census_is_derived_not_enumerated(self):
        src = (REPO_ROOT / "tests/unit/core/test_measurement_worker_plugin_transport.py").read_text(
            encoding="utf-8"
        )
        assert "_production_popen_sites" in src, (
            "the by-path assertion must not come back; the census walks the "
            "production roots and finds new spawners on its own"
        )
        assert "rglob(" in src


# ----------------------------------------------------------------------
# F-11-8 — RESOLVED by C9; the guard was flipped, not duplicated
# ----------------------------------------------------------------------


class TestTheSpawnParentIsCensused:
    """R-11-10: the C0 inverted guard is REPLACED, not twinned.

    Its predecessor asserted that `core/sandbox_executor.py` was ABSENT
    from the task-data-path surface — the module that decides what every
    child reads was the one place the repository's own guardrail could not
    look, while all three of its children were listed.
    """

    def test_the_spawn_parent_is_on_the_surface(self):
        from tests.unit.guardrails.test_task_data_path_census import _DATA_PATH_SURFACE

        assert "src/core/sandbox_executor.py" in _DATA_PATH_SURFACE

    def test_all_three_children_are_still_there_too(self):
        """Widening must not have traded one blind spot for another."""
        from tests.unit.guardrails.test_task_data_path_census import _DATA_PATH_SURFACE

        for child in (
            "src/execute_tools/train_engine_sandbox.py",
            "src/execute_tools/inference_single.py",
            "src/execute_tools/denoising_score_single.py",
        ):
            assert child in _DATA_PATH_SURFACE

    # The old third test required legacy task names to remain in production.
    # Their removal is the separation's purpose, not a guardrail failure.
    # Parent/child inclusion above and TestTaskIdentityGuardrail in
    # test_task_data_path_census own the surviving regression boundary.
