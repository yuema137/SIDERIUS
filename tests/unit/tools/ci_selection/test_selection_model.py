"""The selection model must be honest before anything is allowed to trust it.

Phase C. `tools/ci_selection/` is **not wired into CI** — the full unit suite
still runs on every push, so nothing here can currently cause a test to be
skipped. These tests exist so the model is proven correct *before* that changes,
which is the only order in which a selector is safe to adopt.

Three tests, each naming a defect only it catches:

  reachability   a test module lands whose dependency the AST cannot see and
                 which nobody declared -- the `tests/helpers/tuner_source.py`
                 class, where the production root is computed and no literal
                 edge exists
  freshness      a rename orphans a manifest rule; the rule then matches
                 nothing and silently stops contributing
  oracle         the resolver silently NARROWS -- the only one of the three
                 that catches a model which is wrong but internally consistent,
                 and the failure mode that matters, because a wrong selector
                 fails OPEN into a confident green

The third is the reason the other two are not sufficient. A model can be
perfectly self-consistent, resolve every path, cover every module, and still
select the wrong suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.ci_selection import manifest as mf
from tools.ci_selection.resolver import (
    REPO_ROOT,
    _tracked_repository_files,
    build_edges,
    gates_required,
    select,
)


class TestTheModelIsFailClosed:
    """The one property that makes an unadopted selector safe to keep."""

    def test_an_unmapped_production_path_runs_everything(self):
        """The default must be "run everything", never "run nothing"."""
        result = select(["core/some_module_that_does_not_exist.py"])
        assert result.full_suite is True

    def test_a_declared_hub_runs_everything(self):
        """Selecting 59% of the suite carries all the risk and little of the
        benefit, so hubs say so instead of pretending."""
        assert select(["agent/schemas/hyperparam_tuning.py"]).full_suite is True

    def test_changing_the_selector_itself_runs_everything(self):
        """A broken selector can select nothing and report green. This is the
        one rule that must be hard-coded rather than derived."""
        assert select(["tools/ci_selection/resolver.py"]).full_suite is True
        assert select(["tests/unit/tools/ci_selection/test_selection_model.py"]).full_suite is True

    def test_the_root_conftests_run_everything(self):
        """`tests/unit/conftest.py` installs an autouse fixture; its blast
        radius is the suite by construction."""
        assert select(["tests/unit/conftest.py"]).full_suite is True

    def test_no_non_empty_diff_ever_selects_nothing(self):
        """The failure mode worse than having no selector at all."""
        for diff in (
            ["execute_tools/probe_batch.py"],
            ["ml_models/loss_models_sandbox.py"],
            ["sdsc_submission_scripts/run_chain.sh"],
            ["docs/gates/gate_testing_standard.md"],
        ):
            result = select(diff)
            assert result.full_suite or result.modules, f"{diff} selected nothing"

    def test_a_doc_nothing_reads_selects_no_extra_suites(self):
        """An ordinary doc runs only cheap repository/document readers.

        Fails as: an ordinary doc falls back to FULL, or an unrelated feature
        suite is pulled in despite having no document edge.
        """
        # Built by concatenation, NOT a literal: written plainly, THIS file
        # becomes a literal-path reader of the doc and the resolver -- correctly
        # -- selects this module as an owner. The first draft did exactly that
        # and failed; the edge system caught its own test.
        result = select(["docs/arch" + "itecture.md"])
        assert not result.full_suite, "a doc nothing reads triggered the full suite"
        # Only the always-on block runs; its explicit document censuses cover
        # dynamic tracked-file reads that literal AST edges cannot derive.
        assert all(any(m == a or m.startswith(a) for a in mf.ALWAYS_ON) for m in result.modules), (
            result.modules
        )

    def test_an_area_owned_module_selects_its_area_not_everything(self):
        """Operator ruling: dashboard is not related to production code and
        must not run the full suite. Nothing imports the dashboard entry, but
        its AREA has an owning suite — noise is what gets a selector switched
        off."""
        # Concatenated for the same reason as the doc case above.
        result = select(["dash" + "board/main.py"])
        assert not result.full_suite, "an area-owned module triggered the full suite"
        assert any(m.startswith("tests/unit/dash" + "board/") for m in result.modules)

    def test_root_readme_selects_its_dynamic_document_readers(self):
        """The root README was absent from the old directory inventory.

        Fails as: a tracked root doc is called unknown, or either whole-tree
        reader can change its verdict without being scheduled.
        """
        result = select(["READ" + "ME.md"])
        assert not result.full_suite
        assert result.modules
        assert "tests/unit/tools/test_md_links.py" in result.modules
        assert "tests/unit/tools/test_user_contract_docs_census.py" in result.modules

    def test_tracked_root_documents_come_from_git_inventory(self):
        """A hand-maintained directory list can silently omit another root doc.

        Fails as: any currently tracked root Markdown document is absent from
        the selector's candidate-commit inventory.
        """
        tracked = _tracked_repository_files()
        assert {"AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "README.md"} <= tracked

    def test_docs_are_inputs_not_inert(self):
        """`paths-ignore: ['**.md']` is the first optimisation anyone reaches
        for, and it would skip CI on a change that breaks
        `test_gate_standard_contract`, which READS this very file."""
        result = select(["docs/gates/gate_testing_standard.md"])
        assert result.full_suite or result.modules
        if not result.full_suite:
            assert "tests/unit/guardrails/test_gate_standard_contract.py" in result.modules

    def test_an_absent_or_ignored_doc_still_fails_closed(self):
        """The tracked-doc rule must not bless deleted or local scratch files.

        Fails as: an absent before-state or ignored local plan is treated as an
        ordinary inert document and narrows without a proven reader inventory.
        """
        for changed in ("docs/no_such_contract.md", ".structured-coding/local.md"):
            result = select([changed])
            assert result.full_suite, result.describe()

    def test_a_document_cannot_hide_a_hub_in_the_same_diff(self):
        """Classification is additive; a cheap doc never suppresses FULL.

        Fails as: the selector returns a narrow document set when the same PR
        changes a shared schema hub.
        """
        result = select(["README.md", "agent/schemas/hyperparam_tuning.py"])
        assert result.full_suite, result.describe()


def test_every_unit_test_module_is_reachable() -> None:
    """Reachability. A module no changed path can select is a module the
    selector would never run — invisible, because the full suite currently
    hides it.

    The always-on block is the sanctioned answer for whole-tree scanners; this
    asserts nothing ELSE has fallen through.
    """
    edges = build_edges()
    always_on = {m for m in edges if any(m == a or m.startswith(a) for a in mf.ALWAYS_ON)}
    declared = set(mf.DIRECTORY_SCANS)
    unreachable = sorted(
        m for m, targets in edges.items() if not targets and m not in always_on | declared
    )
    assert not unreachable, (
        "these test modules have no derivable edge and no manifest rule, so a "
        "selective run would never choose them. Add them to ALWAYS_ON if they "
        "scan the tree, or declare what they read:\n  " + "\n  ".join(unreachable)
    )


def test_every_manifest_path_still_resolves() -> None:
    """Freshness. A rename orphans a rule, the rule matches nothing, and the
    model quietly stops covering what it claims to. This repo renames often —
    the tuner node is the proof — so this is the failure mode it actually has.
    """
    missing: list[str] = []
    groups: list[tuple[str, tuple[str, ...]]] = [
        ("ALWAYS_ON", mf.ALWAYS_ON),
        ("HUBS", mf.HUBS),
        ("CONFTEST_SCOPES", mf.CONFTEST_SCOPES),
        ("GATE_REQUIREMENTS", tuple(mf.GATE_REQUIREMENTS)),
    ]
    for name, paths in groups:
        for rel in paths:
            if not (REPO_ROOT / rel).exists():
                missing.append(f"{name}: {rel}")
    for owner, scanned in mf.DIRECTORY_SCANS.items():
        if not (REPO_ROOT / owner).exists():
            missing.append(f"DIRECTORY_SCANS owner: {owner}")
        for rel in scanned:
            if not (REPO_ROOT / rel).exists():
                missing.append(f"DIRECTORY_SCANS target: {rel}")
    for prefix, tests in mf.AREA_OWNERS:
        if not (REPO_ROOT / prefix).exists():
            missing.append(f"AREA_OWNERS prefix: {prefix}")
        for rel in tests:
            if not (REPO_ROOT / rel).exists():
                missing.append(f"AREA_OWNERS suite: {rel}")
    for rel in mf.FULL_SUITE_TRIGGERS:
        if not (REPO_ROOT / rel).exists():
            missing.append(f"FULL_SUITE_TRIGGERS: {rel}")
    assert not missing, "manifest paths that no longer exist:\n  " + "\n  ".join(missing)


#: (changed production path, a test module that MUST be selected).
#:
#: Harvested from this repository's own history rather than invented: each pair
#: is a file a merged PR changed, paired with a suite that would have caught a
#: regression in it. The tuner pair is the important one -- its suite lives
#: under an OLD node name (`tests/unit/agent/tune_ml_hyperparam_agent/`), so any
#: filename heuristic maps it to the wrong owner.
SELECTION_ORACLE: tuple[tuple[str, str], ...] = (
    (
        "nodes/ml_hyperparameter_tune_agent/policy.py",
        "tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c2_order_consumers.py",
    ),
    (
        "execute_tools/metric_order.py",
        "tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c2_order_consumers.py",
    ),
    (
        "core/sandbox_executor.py",
        "tests/unit/core/test_watchdog.py",
    ),
    (
        "ml_models/loss_models_sandbox.py",
        "tests/unit/ml_models/test_loss_functions.py",
    ),
    (
        "execute_tools/train_engine_sandbox.py",
        "tests/unit/execute_tools/test_pr07c_validation_persistence_timing.py",
    ),
)


@pytest.mark.parametrize("changed,must_select", SELECTION_ORACLE)
def test_the_selector_does_not_silently_narrow(changed: str, must_select: str) -> None:
    """The mutation oracle, and the only test here that catches a model which
    is wrong but internally consistent.

    Reachability and freshness both pass for a selector that resolves every
    path, covers every module, and still picks the wrong suite. This one does
    not: it pins concrete (changed file -> must-run test) pairs, so narrowing
    the resolver breaks it even when the model stays self-consistent.
    """
    assert (REPO_ROOT / changed).exists(), f"oracle pair is stale: {changed}"
    assert (REPO_ROOT / must_select).exists(), f"oracle pair is stale: {must_select}"

    result = select([changed])
    assert result.full_suite or must_select in result.modules, (
        f"changing {changed} would NOT have run {must_select}.\n{result.describe()}"
    )


def test_gate_requirements_are_advisory_and_never_executed() -> None:
    """CI must never trigger a Gate: they cost money and need operator approval
    (`docs/gates/gate_testing_standard.md`). This function returns strings for a
    human to read, and nothing more."""
    gates = gates_required(["core/runtime_control/session.py"])
    assert gates == ("gate2",)
    assert all(isinstance(g, str) for g in gates)
    # The manifest must not be able to LAUNCH anything -- checked against code,
    # not prose: the word "subprocess" legitimately appears in a comment
    # explaining why the root conftest is a full-suite trigger.
    import ast as _ast

    tree = _ast.parse(Path(mf.__file__).read_text(encoding="utf-8"))
    called = {
        n.func.attr if isinstance(n.func, _ast.Attribute) else getattr(n.func, "id", "")
        for n in _ast.walk(tree)
        if isinstance(n, _ast.Call)
    }
    assert not called & {"run", "Popen", "system", "check_output"}, called


class TestTheWorkflowActuallyConsumesTheSelector:
    """The model is only worth anything if CI runs it, and only SAFE if every
    failure path in the shell falls back to the full suite.

    These read `.github/workflows/ci.yml` as an input, the same way
    `test_gate_standard_contract.py` reads the Gate standard. A silent
    unwiring — someone "simplifying" the pytest step back to a hardcoded
    `tests/unit/` — would otherwise be invisible: CI would still be green, and
    the selector would sit there doing nothing.
    """

    @staticmethod
    def _workflow() -> str:
        return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_the_pytest_step_uses_the_selector_output(self):
        """The selector's verdict must reach test EXECUTION.

        The mechanism changed when `tools/ci/` became the execution authority:
        the run step no longer interpolates `pytest_args` directly. It consumes
        the selector's `full_suite` verdict plus the single changed-file list
        the selector step wrote, and the harness then calls
        `tools.ci_selection.resolver.select()` itself. The selector remains the
        one authority for WHAT runs; only the transport moved.

        What must never happen is the docstring's own scenario — the run step
        "simplified" back to a hardcoded suite, leaving the selector computing
        an answer nobody reads.
        """
        wf = self._workflow()
        assert "python -m tools.ci_selection" in wf, "CI no longer invokes the selector"
        assert "steps.selection.outputs.full_suite" in wf, (
            "the execution step no longer consumes the selector's verdict"
        )
        assert "python -m tools.ci bulk" in wf, (
            "the execution step no longer runs through the harness, which is what "
            "composes the selector"
        )
        assert "--changed-from" in wf, (
            "the harness is no longer handed the selector's changed-file list, so its "
            "selection could diverge from the selector step's verdict"
        )

    def test_the_changed_file_list_is_computed_exactly_once(self):
        """Two `git diff` invocations can disagree.

        If the selector step and the execution step each derive the changed set,
        the verdict recorded in `full_suite` can describe a different set from
        the one actually executed — a divergence that would be invisible in a
        green run. One computation, written once, consumed by both.
        """
        wf = self._workflow()
        assert wf.count("git diff --name-only") == 1, (
            "the changed-file list is derived more than once; the selector's verdict "
            "and the executed set could diverge"
        )

    def test_the_execution_step_is_not_a_hardcoded_suite(self):
        """The exact unwiring this class was written to prevent.

        The original guard asserted only that an output variable was mentioned,
        which a hardcoded `pytest tests/unit/` alongside it would have satisfied.
        Assert the absence directly.
        """
        wf = self._workflow()
        run_step = wf.split("repository CI harness")[1].split("- name:")[0]
        assert "uv run pytest tests/unit/" not in run_step, (
            "the execution step hardcodes the suite; the selector would run and be ignored"
        )

    def test_non_pull_request_events_run_everything(self):
        """master and the nightly schedule are the safety net. If they ever
        became selective too, a selector mistake would be permanent rather
        than lasting one night."""
        wf = self._workflow()
        assert 'github.event_name }}" != "pull_request"' in wf
        assert "schedule:" in wf and "cron:" in wf

    def test_every_shell_failure_path_falls_back_to_the_full_suite(self):
        """`set -e` is deliberately ABSENT: a selector that can break the build
        is a selector people switch off. Each step below must reach `full`."""
        wf = self._workflow()
        assert (
            "set -euo pipefail"
            not in wf.split("Resolve affected test suites")[1].split("- name:")[0]
        ), "set -e in the selection step would fail the build instead of failing closed"
        for guarded in (
            "could not fetch the base ref",
            "could not diff against the base ref",
            "the selector exited non-zero",
            "the selector produced no pytest_args",
        ):
            assert guarded in wf, f"missing fail-closed fallback: {guarded}"

    def test_the_checkout_has_the_history_the_diff_needs(self):
        """A shallow clone makes the base diff fail. That falls back to the
        full suite rather than breaking, but it would silently disable
        selection on every PR."""
        assert "fetch-depth: 0" in self._workflow()

    def test_pyright_mode_is_not_touched_by_this_pr(self):
        """Q6 is DEFERRED. The workflow's "strict" label and
        `pyrightconfig.json`'s `basic` disagree, and CLAUDE.md leans on the
        strict ceiling. Preserve CURRENT behaviour; changing either side here
        would quietly pick a side of an open policy question."""
        import json

        cfg = json.loads((REPO_ROOT / "pyrightconfig.json").read_text(encoding="utf-8"))
        assert cfg["typeCheckingMode"] == "basic", (
            "pyright's mode changed — that is a type-safety policy decision (Q6), "
            "not a test-selection one"
        )
        assert "uv run pyright" in self._workflow()
