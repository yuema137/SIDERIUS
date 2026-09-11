"""Step 10 / P1 C4 — a fourth task costs zero infrastructure edits.

Two halves of one claim, and neither is worth much without the other.

**The executable half** lives in C1/C2/C3: a synthetic task supplied entirely
by out-of-tree plugin FILES composes, binds, reaches every consumer seam and
transports to the subprocess. That proves a conforming task *can* be added.

**The structural half is here**: it proves nothing was added to SIDERIUS to
let it in. That is a different claim, and it is the one that decays silently.
A framework can absorb a task by growing a table entry, an import, an enum
member or an `if` — everything keeps working, every test stays green, and the
extension mechanism quietly becomes "edit the framework". So this module
censuses production source for the shapes that would mean that, and each
census is proven load-bearing by planting the offender it hunts.

**Why the oracle is an AST census and not `git diff`.** The obvious proof —
"look, the diff for the fourth task touches no framework file" — depends on
mutable working-tree state: it reads differently on a dirty tree, after a
commit, or on a branch that legitimately touched a framework file for an
unrelated reason. The frozen design rules it out as a semantic oracle for
exactly that reason (C4), and permits it only as ledger evidence.

**Why AST and not grep** (the anti-vacuity lesson the Step-10 parent records
at §3.8): a regex census flags a banner string like
``print("=== TIDMAD Agent Activated ===")`` and an implementation's own
self-check against a named constant, while missing a membership test hidden
in a tuple. The census below matches comparison, subscript, mapping-key and
match-case SHAPES, which is what "task identity selects behaviour" actually
looks like in source.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The repository's own production directory set (parent §3.8's definition).
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

TASK_NAMES = ("tidmad", "pets", "davis", "oxford_iiit_pet", "spectro_segmentation_v0")

#: The surfaces P1 created or reshaped. Task identity may not select behaviour
#: anywhere in production, but on THESE files it may not appear at all in a
#: behavioural position — they are the ones a future task-specific special
#: case would most naturally be added to.
P1_OWNED_SURFACE = (
    "src/workflows/task_composition.py",
    "src/workflows/run_bindings.py",
    "src/workflows/task_config.py",
)


def _production_py_files() -> list[Path]:
    files: list[Path] = []
    for rel in PRODUCTION_DIRS:
        root = REPO_ROOT / rel
        if root.is_dir():
            files.extend(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def _is_task_name(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in TASK_NAMES


def find_task_identity_dispatch(tree: ast.AST) -> list[tuple[int, str]]:
    """Every AST shape in which a TASK NAME selects behaviour.

    Shared with the plant-and-catch tests below, so the detector that reports
    "clean" is the same one proven able to report "dirty".
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # `x == "tidmad"`, `x != "pets"`, `x in ("tidmad", ...)`
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for operand in operands:
                if isinstance(operand, ast.Constant) and _is_task_name(operand.value):
                    hits.append((node.lineno, "comparison against a task name"))
                elif isinstance(operand, ast.Tuple | ast.List | ast.Set) and any(
                    isinstance(e, ast.Constant) and _is_task_name(e.value) for e in operand.elts
                ):
                    hits.append((node.lineno, "membership test over task names"))
        # `{"tidmad": ..., "pets": ...}` — a dispatch table
        elif isinstance(node, ast.Dict) and any(
            isinstance(k, ast.Constant) and _is_task_name(k.value) for k in node.keys if k
        ):
            hits.append((node.lineno, "mapping keyed on a task name"))
        # `TABLE["tidmad"]`
        elif isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and _is_task_name(index.value):
                hits.append((node.lineno, "subscript by a task name"))
        # `case "tidmad":`
        elif isinstance(node, ast.MatchValue):
            if isinstance(node.value, ast.Constant) and _is_task_name(node.value.value):
                hits.append((node.lineno, "match-case on a task name"))
    return hits


class TestNoTaskIdentityDispatchInProduction:
    def test_the_whole_production_tree_is_free_of_task_identity_dispatch(self):
        """Parent §3.8's class (b) = 0, re-measured after P1.

        Two known non-counterexamples, named so a future census does not
        rediscover them as findings: ``evaluation_metric.py``'s
        ``_SCOREABILITY_CONTRACT_TYPES`` is keyed on a CONTRACT id that
        happens to contain a task word (there is no sibling key for another
        task, and the lookup fails closed on an unknown id), and
        ``pets_data_path.py`` compares against its OWN named header constant
        inside the Pets implementation.
        """
        allowed = {
            "src/execute_tools/evaluation_metric.py",
        }
        offenders: dict[str, list[tuple[int, str]]] = {}
        for path in _production_py_files():
            rel = str(path.relative_to(REPO_ROOT))
            if rel in allowed:
                continue
            hits = find_task_identity_dispatch(
                ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            )
            if hits:
                offenders[rel] = hits
        assert offenders == {}, "task identity selects framework behaviour:\n" + "\n".join(
            f"  {rel}: {hits}" for rel, hits in sorted(offenders.items())
        )

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('if task == "tidmad":\n    pass\n', "comparison against a task name"),
            ('if name in ("pets", "davis"):\n    pass\n', "membership test over task names"),
            ('TABLE = {"tidmad": 1, "pets": 2}\n', "mapping keyed on a task name"),
            ('value = TABLE["davis"]\n', "subscript by a task name"),
            (
                'match task:\n    case "tidmad":\n        pass\n',
                "match-case on a task name",
            ),
        ],
    )
    def test_the_detector_catches_each_dispatch_shape(self, source, expected):
        """Plant-and-catch for the detector itself.

        A census that cannot report an offender is a census that always
        passes. Each shape is planted and must be reported AS that shape."""
        hits = find_task_identity_dispatch(ast.parse(source))
        assert any(kind == expected for _, kind in hits), f"{expected} went undetected: {hits}"

    def test_the_detector_does_NOT_flag_the_two_known_near_misses(self):
        """Anti-false-positive, and the reason this is AST rather than grep.

        A banner string and a comparison against a NAMED CONSTANT are not
        task dispatch. A regex census flags both; flagging them would train
        the next reader to ignore the census."""
        banner = 'print("=== TIDMAD Agent Activated ===")\n'
        constant_compare = "if lines[0] != PETS_MANIFEST_HEADER:\n    pass\n"
        assert find_task_identity_dispatch(ast.parse(banner)) == []
        assert find_task_identity_dispatch(ast.parse(constant_compare)) == []


class TestTheFourthTaskIsUnknownToTheFramework:
    def test_no_production_source_mentions_the_fourth_task_at_all(self):
        """Not "no branch on it" — no MENTION of it.

        The synthetic task exists, composes, binds and transports (C1 through C3).
        If SIDERIUS had to learn its name anywhere to make that work, the
        extension mechanism would be "edit the framework" and the whole
        claim would be false.
        """
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in _production_py_files()
            if "spectro_segmentation_v0" in path.read_text(encoding="utf-8", errors="ignore")
        ]
        assert offenders == [], f"the framework learned the fourth task's name: {offenders}"

    def test_it_is_absent_from_every_import_list_and_registry_bootstrap(self):
        """Registration happens because the TASK's own file ran.

        The built-in bootstraps (the data-path implementations, the Health
        check import list) are the built-ins' bootstrap, not the extension
        path — Step 08's sentence, which P1 must be able to repeat.
        """
        for rel in (
            "src/execute_tools/task_data_path.py",
            "src/execute_tools/health_checks/__init__.py",
            "src/execute_tools/evaluation_metric.py",
            "src/workflows/task_composition.py",
        ):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "spectro" not in text.lower(), f"{rel} names the fourth task"

    def test_composing_it_registers_it_without_any_central_table(self):
        """The positive half, restated at the registry boundary: the id is
        absent until the task's plugin runs, and present afterwards."""
        from execute_tools.task_data_path import registered_task_data_path_ids
        from workflows.task_composition import compose_run_task_bindings

        manifest = (
            REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task" / "composition.yaml"
        )
        composition = compose_run_task_bindings(str(manifest))
        assert composition.task_data_path_id in registered_task_data_path_ids()
        # ...and the framework's own registry module still contains no list
        # of known tasks — the ids in it are whatever registered themselves.
        registry_source = (REPO_ROOT / "src/execute_tools" / "task_data_path.py").read_text(
            encoding="utf-8"
        )
        assert "spectro_segmentation_v0" not in registry_source


class TestP1OwnedSurfacesCarryNoAmbientTaskAuthority:
    """§3's narrowed claim, made checkable on the surfaces P1 owns."""

    def test_no_p1_owned_surface_imports_a_task_dataset_singleton(self):
        """`model_exploration.py` used to import ``TIDMAD as _DATASET_CONFIG``
        and resolve the run's scope against it. The surviving framework
        surfaces take the value from the run.

        The import is the thing to forbid: while it exists, the next reader
        who needs "how many files are there" has a wrong answer within easy
        reach.

        **Step 12 / PR-12a C8 (F-12-6) widens the surface** to the two files
        the audit found excluded: `sdsc_submission_scripts/run_one_iteration.py`
        and `core/resume.py`. Both had ALREADY been migrated to
        `resolve_dataset_profile` — by Step-11 C8 (F-11-5) for resume, and by
        this PR's C1 for the iteration runner — so this widening records no new
        leak. It closes the gap that let those migrations be undone silently:
        the guard that would have caught the original defect did not look at
        the two files where the same defect lived longest.
        """
        surfaces = (
            *P1_OWNED_SURFACE,
            "src/workflows/model_exploration.py",
            "sdsc_submission_scripts/run_one_iteration.py",
            "src/core/resume.py",
        )
        offenders: dict[str, list[str]] = {}
        for rel in surfaces:
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            names: list[str] = []
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "execute_tools.dataset_config"
                ):
                    names.extend(
                        alias.name
                        for alias in node.names
                        if alias.name in {"TIDMAD", "TIDMAD_PROFILE"}
                    )
            if names:
                offenders[rel] = names
        assert offenders == {}, (
            f"a P1-owned surface imports a task dataset singleton: {offenders}. "
            "The run's own profile is the authority; an ambient import is how "
            "a composed run silently gets somebody else's topology."
        )
