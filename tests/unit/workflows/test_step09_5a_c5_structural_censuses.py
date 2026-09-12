"""Step 09.5a C5 — the closing structural censuses (design §33 C and F).

Two properties that no behavioural test can see, because in both cases the
program would still produce identical results:

* **C** — a compatibility wrapper re-exposing the old 99-argument surface. The
  frozen design forbids one in so many words: keeping the old signature alive
  would preserve, verbatim, the structural debt this milestone exists to
  remove, while every test stayed green.
* **F** — a task name entering the new structural surface. Step 12 must be able
  to bind a fourth, out-of-tree task through these carriers; a `tidmad` /
  `pets` / `davis` branch in one of them is the first step to a per-task
  workflow, and nothing would fail today.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The structural surface Step 09.5a created or reshaped. Task identity must
#: not appear in any of it.
NEW_STRUCTURAL_SURFACE = (
    "src/core/chain_state.py",
    "src/core/committed_digests.py",
    "src/workflows/run_bindings.py",
    "src/workflows/run_config.py",
    "src/workflows/strategy_modes.py",
)

TASK_NAMES = ("tidmad", "pets", "davis", "oxford")


class TestNoCompatibilityWrapper:
    def test_no_function_re_exposes_the_old_parameter_surface(self):
        """Design §13 / acceptance criterion 6.

        A wrapper is recognisable by shape, not by name: any function in the
        workflow package that declares a large slice of the retired transit
        configuration is the old signature wearing a new one.
        """
        from workflows.run_config import launch_config_field_names

        retired = launch_config_field_names()
        offenders: dict[str, int] = {}
        for rel in ("src/workflows/model_exploration.py", "src/workflows/run_bindings.py"):
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
                declared = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
                overlap = declared & retired
                if len(overlap) > 5:
                    offenders[f"{rel}::{fn.name}"] = len(overlap)
        assert not offenders, (
            f"a compatibility wrapper survived: {offenders}. Keeping the old "
            "argument surface alive preserves exactly the debt this milestone "
            "removes, and every test would stay green."
        )

    def test_run_workflow_declares_the_carrier_not_the_config(self):
        from workflows.model_exploration import run_workflow
        from workflows.run_config import launch_config_field_names

        params = set(inspect.signature(run_workflow).parameters)
        assert "launch" in params
        assert not (params & launch_config_field_names())

    def test_the_wrapper_detector_would_catch_one(self):
        """Anti-vacuity: the shape test must actually recognise the shape."""
        from workflows.run_config import launch_config_field_names

        retired = sorted(launch_config_field_names())[:8]
        planted = ast.parse(
            "def run_workflow_legacy(" + ", ".join(f"{p}=None" for p in retired) + "): pass"
        )
        fn = next(n for n in ast.walk(planted) if isinstance(n, ast.FunctionDef))
        declared = {a.arg for a in fn.args.args}
        assert len(declared & launch_config_field_names()) > 5


class TestNoTaskIdentityInTheNewSurface:
    @pytest.mark.parametrize("rel", NEW_STRUCTURAL_SURFACE)
    def test_no_task_name_appears_in_executed_code(self, rel):
        """Step 12 must bind a fourth task through these carriers unchanged.

        Docstrings and comments may name a task as an example; executed code
        may not, because that is where a per-task branch would live.
        """
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                for task in TASK_NAMES:
                    if task in node.value.lower():
                        offenders.append(f"{rel}:{node.lineno} {node.value[:60]!r}")
            if isinstance(node, ast.Name) and any(t in node.id.lower() for t in TASK_NAMES):
                offenders.append(f"{rel}:{node.lineno} name {node.id}")
        assert not offenders, offenders

    def test_the_scanned_surface_is_not_empty(self):
        """A renamed file would otherwise make this census vacuous."""
        for rel in NEW_STRUCTURAL_SURFACE:
            assert (REPO_ROOT / rel).is_file(), f"{rel} moved without updating this census"


class TestRunBindingsProductionAdoption:
    """Step 09.5a C3 — the carrier is a REAL production boundary.

    Defect only this class catches: `WorkflowRunBindings` frozen, guarded,
    unit-tested — and never constructed by production. That state passed every
    behavioural test in this PR and every structural census, because a class
    nobody calls changes no behaviour and appears in no diff of the code that
    runs. It was found by a Step-10 source audit, not by this suite, which is
    why the guard now exists.
    """

    def _run_workflow_source(self) -> tuple[str, str]:
        """(source before the carrier is constructed, source after)."""
        src = (REPO_ROOT / "src/workflows" / "model_exploration.py").read_text(encoding="utf-8")
        lines = src.splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.startswith("def run_workflow("))
        end = next(
            i
            for i, ln in enumerate(lines[start + 1 :], start=start + 1)
            if ln.startswith("def ") or ln.startswith("class ")
        )
        body = lines[start:end]
        cut = next(i for i, ln in enumerate(body) if "bindings = WorkflowRunBindings(" in ln)
        # The constructor's OWN arguments read the locals — that is what
        # construction is. The "after" region therefore begins once the call
        # closes, at the first line that is exactly the call's closing paren.
        close = next(i for i, ln in enumerate(body[cut:], start=cut) if ln.rstrip() == "    )")
        return "\n".join(body[: cut + 1]), "\n".join(body[close + 1 :])

    def test_the_carrier_is_constructed_in_production(self):
        before, after = self._run_workflow_source()
        assert "WorkflowRunBindings(" in before, (
            "run_workflow does not construct WorkflowRunBindings. A carrier "
            "with no production writer is a contract nobody keeps."
        )
        assert "WorkflowRunBindings(" not in after, (
            "the carrier is constructed exactly ONCE; a second construction "
            "later in the body would be a second source of truth"
        )

    def test_the_carrier_has_a_production_construction_site_at_all(self):
        """The bluntest form of the finding: grep production for a writer.

        Kept beside the structural test because it is the one that would have
        caught the real defect on day one — the class existed, the guard
        existed, the tests existed, and `grep -r 'WorkflowRunBindings(' --
        excluding tests` returned nothing.
        """
        sites = []
        sources = [*REPO_ROOT.glob("*.py")]
        for root in ("src", "scripts"):
            files = list((REPO_ROOT / root).rglob("*.py"))
            assert files, f"empty production scan: {root}"
            sources.extend(files)
        for path in sources:
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith(("tests/", ".venv/", "docs/")):
                continue
            if "WorkflowRunBindings(" in path.read_text(encoding="utf-8", errors="ignore"):
                sites.append(rel)
        assert sites, "no production module constructs WorkflowRunBindings"
        assert sites == ["src/workflows/model_exploration.py"], sites

    #: Authorities the carrier owns whose local name is identical to the field.
    #: Reading one as a bare local AFTER construction is a second source of
    #: truth for a value the carrier already owns.
    CARRIER_OWNED = (
        "workspace",
        "run_name",
        "run_dir",
        "chain_run_name",
        "run_id",
        "data_scope",
        "health_gate_enabled",
        "health_checks_config",
        "order_strategy_override",
        "enable_structured_health_feedback",
        "llm_config",
        "reasoning_pipeline",
    )

    @pytest.mark.parametrize("name", CARRIER_OWNED)
    def test_no_bare_local_read_survives_after_construction(self, name):
        """Design §13: from the construction line on, the carrier is THE
        source of truth. A bare local read is the drift this milestone exists
        to remove — and nothing behavioural can see it, because both spellings
        hold the same value on the day it is written."""
        import re

        _, after = self._run_workflow_source()
        offenders = []
        for lineno, line in enumerate(after.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"'):
                continue
            for m in re.finditer(r"(?<![\w.])" + re.escape(name) + r"(?![\w])", line):
                if re.match(r"\s*=(?!=)", line[m.end() :]):
                    continue  # keyword-argument NAME, not a value read
                offenders.append(f"+{lineno}: {stripped[:90]}")
        assert not offenders, (
            f"{name} is still read as a bare local after the carrier is constructed: {offenders}"
        )

    def test_the_detector_catches_a_planted_bare_read(self):
        """Anti-vacuity: the scanner must recognise the shape it forbids."""
        import re

        planted = "    print(workspace)\n    foo(run_name=run_name)\n"
        hits = []
        for m in re.finditer(r"(?<![\w.])workspace(?![\w])", planted):
            if not re.match(r"\s*=(?!=)", planted[m.end() :]):
                hits.append(m.start())
        assert hits, "the scanner would not catch a planted bare read"
        # and the keyword-NAME half must NOT be counted
        kw = [
            m
            for m in re.finditer(r"(?<![\w.])run_name(?![\w])", planted)
            if not re.match(r"\s*=(?!=)", planted[m.end() :])
        ]
        assert len(kw) == 1, "the value read is counted; the keyword name is not"
