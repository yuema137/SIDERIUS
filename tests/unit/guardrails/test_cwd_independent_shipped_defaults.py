# tests/unit/guardrails/test_cwd_independent_shipped_defaults.py
"""A shipped-config default must resolve to THIS checkout, from ANY cwd.

**The defect only this file catches** (release remediation N-1). The Health
config's ``SIDERIUS_ROOT`` docstring claimed, in prose, that "every sibling
authority in the repository already anchors this way; these two were the
stragglers". It was false. The three ``LEGACY_DEFAULT_TASK_*_CONFIG``
constants whose own comments name that constant as the idiom they copy —
proposal, implementor, interpretation — were still built from a bare
``os.path.join("configs", …)``, i.e. resolved against the caller's working
directory. Their loaders are fail-closed, and
``workflows/model_exploration.py`` calls all three ZERO-ARG on the
un-composed branch, so an un-composed chain launched from anywhere but the
repo root died in the proposer, the implementor and the interpreter. No
launcher under ``sdsc_submission_scripts/`` or ``scripts/`` cd's to the repo
root, so that is not a hypothetical geometry — it is the one that produced
the original F-7 failure.

The per-adapter suites could not see it. Each one imports its constant and
calls its loader from pytest's rootdir, which IS the repo root, so a
cwd-relative path resolves and every assertion passes. The property is
cross-module and cwd-shaped; no per-field test can express it.

**Why this file DISCOVERS rather than lists.** A prose claim about "every
sibling" stops being true the moment a fourth adapter is added, and nobody
notices — which is exactly what happened. :data:`_DISCOVERED` is an AST
census over the production packages, and :data:`ZERO_ARG_DEFAULT_LOADERS`
must cover it exactly: a new ``LEGACY_DEFAULT_*`` constant turns
``test_the_census_covers_every_declared_default`` RED until its author says
which production entry point resolves it. That is the census's file set
widening by construction instead of by memory.

**Two legitimate shapes, one property.** A default may be ABSOLUTE at the
declaration (the ``LEGACY_DEFAULT_*`` constants) or RELATIVE at the
declaration and anchored by a resolver at consumption (the lit-review config
path, whose resolver had no test at all). Both are correct; both are checked
here through the PRODUCTION entry point, because what matters is whether the
file opens, not which of the two spellings was chosen.
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Production packages scanned for shipped-config default constants. The
#: original census's blindness was its FILE SET, so this names directories
#: rather than the two modules the defect happened to live in.
PRODUCTION_PACKAGES = (
    "agent",
    "core",
    "dashboard",
    "execute_tools",
    "ml_models",
    "nodes",
    "scripts",
    "sdsc_submission_scripts",
    "tools",
    "workflows",
)

_LEGACY_DEFAULT = re.compile(r"^LEGACY_DEFAULT_[A-Z0-9_]+$")


def _module_level_constants(path: Path) -> list[str]:
    """Module-level assignment target names matching the census pattern."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        elif isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        else:
            continue
        names.extend(
            t.id for t in targets if isinstance(t, ast.Name) and _LEGACY_DEFAULT.match(t.id)
        )
    return names


def _discover() -> dict[str, Path]:
    """``constant name -> declaring file``, over the production packages."""
    found: dict[str, Path] = {}
    for package in PRODUCTION_PACKAGES:
        for path in sorted((REPO_ROOT / package).rglob("*.py")):
            for name in _module_level_constants(path):
                found[name] = path
    return found


_DISCOVERED = _discover()


def _health_default() -> str:
    from execute_tools.health_checks._composition import LEGACY_DEFAULT_TASK_HEALTH_CONFIG

    return LEGACY_DEFAULT_TASK_HEALTH_CONFIG


def _proposal_default() -> str:
    from agent.prompt_templates.proposal.task_blocks import LEGACY_DEFAULT_TASK_PROPOSAL_CONFIG

    return LEGACY_DEFAULT_TASK_PROPOSAL_CONFIG


def _implementor_default() -> str:
    from agent.prompt_templates.implementor.task_blocks import (
        LEGACY_DEFAULT_TASK_IMPLEMENTOR_CONFIG,
    )

    return LEGACY_DEFAULT_TASK_IMPLEMENTOR_CONFIG


def _interpretation_default() -> str:
    from agent.prompt_templates.interpretation.task_blocks import (
        LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG,
    )

    return LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG


def _load_health() -> object:
    from execute_tools.health_checks.config import load_health_gates_config

    return load_health_gates_config()


def _load_proposal() -> object:
    from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks

    return load_proposal_task_blocks()


def _load_implementor() -> object:
    from agent.prompt_templates.implementor.task_blocks import load_implementor_task_blocks

    return load_implementor_task_blocks()


def _load_interpretation() -> object:
    from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks

    return load_interpretation_task_blocks()


#: ``constant name -> (read the constant, resolve it through production)``.
#:
#: The loader half is deliberately the PRODUCTION zero-argument entry point,
#: not ``open(constant)``: a test that opened the constant itself would pass
#: even if the loader joined it onto something else, and the whole failure
#: class here is "the value read is not the value opened".
ZERO_ARG_DEFAULT_LOADERS: dict[str, tuple[Callable[[], str], Callable[[], object]]] = {
    "LEGACY_DEFAULT_TASK_HEALTH_CONFIG": (_health_default, _load_health),
    "LEGACY_DEFAULT_TASK_PROPOSAL_CONFIG": (_proposal_default, _load_proposal),
    "LEGACY_DEFAULT_TASK_IMPLEMENTOR_CONFIG": (_implementor_default, _load_implementor),
    "LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG": (_interpretation_default, _load_interpretation),
}


class TestTheCensusSeesEveryDeclaredDefault:
    def test_the_scanner_is_not_blind(self):
        """A census that finds nothing passes every other test in this file.

        Fails as: an empty or shrunken discovery set — a moved package, a
        renamed constant family, or a scanner that stopped parsing.
        """
        assert len(_DISCOVERED) >= 4, _DISCOVERED

    def test_the_census_covers_every_declared_default(self):
        """Fails as: a fifth ``LEGACY_DEFAULT_*`` with no entry below.

        This is the widening. The N-1 defect was three constants that named
        the fixed one as their idiom and were never checked against it; a
        hand-listed census would have grown the same blind spot again.
        """
        assert set(_DISCOVERED) == set(ZERO_ARG_DEFAULT_LOADERS), {
            "declared but not covered": sorted(set(_DISCOVERED) - set(ZERO_ARG_DEFAULT_LOADERS)),
            "covered but not declared": sorted(set(ZERO_ARG_DEFAULT_LOADERS) - set(_DISCOVERED)),
        }


@pytest.mark.parametrize("constant", sorted(ZERO_ARG_DEFAULT_LOADERS))
class TestEveryShippedDefaultIsAnchoredToThisCheckout:
    def test_the_constant_is_absolute_and_inside_this_checkout(self, constant):
        """Absolute is not enough — it must be THIS tree.

        A path anchored to some other clone would satisfy a cwd-independence
        test while validating the wrong repository, which is the failure
        CLAUDE.md's portability section records.

        Fails as: a relative path (the N-1 defect), or an absolute path that
        does not live under this checkout.
        """
        value = Path(ZERO_ARG_DEFAULT_LOADERS[constant][0]())

        assert value.is_absolute(), f"{constant} is cwd-relative: {value}"
        assert value.is_relative_to(REPO_ROOT), f"{constant} names another checkout: {value}"
        assert value.is_file(), f"{constant} names no file in this checkout: {value}"

    def test_the_production_loader_opens_it_from_an_unrelated_cwd(
        self, constant, tmp_path, monkeypatch
    ):
        """The behavioural half, and the one that reproduces the incident.

        Fails as: ``FileNotFoundError`` naming a bare ``configs/…`` path —
        which is exactly what an un-composed chain launched from a
        ``sdsc_submission_scripts`` working directory saw, in the proposer,
        the implementor and the interpreter.
        """
        monkeypatch.chdir(tmp_path)

        assert ZERO_ARG_DEFAULT_LOADERS[constant][1]() is not None


class TestARelativeDefaultIsAnchoredByItsResolver:
    """The second legal shape: relative at the declaration, anchored on read.

    ``WorkflowLaunchConfig.lit_review_config_path`` is deliberately the
    relative string ``configs/lit_review_config.yaml``, and
    ``resolve_lit_review_config_path`` anchors it. That is correct — and it
    had NO test, so nothing stood between it and the N-1 defect one file
    over. Both production readers are checked, because they are two separate
    anchorings of the same shipped default and either could lose it alone.
    """

    def test_the_workflow_resolver_anchors_the_shipped_relative_default(
        self, tmp_path, monkeypatch
    ):
        """Fails as: a resolved path that does not exist from a foreign cwd."""
        from workflows.model_exploration import resolve_lit_review_config_path
        from workflows.run_config import WorkflowLaunchConfig

        default = WorkflowLaunchConfig().lit_review_config_path
        assert not os.path.isabs(default), (
            "this test exists because the default is RELATIVE; an absolute "
            "default belongs in the census above instead"
        )
        monkeypatch.chdir(tmp_path)

        resolved = Path(resolve_lit_review_config_path(default))

        assert resolved.is_absolute() and resolved.is_file(), resolved
        assert resolved.is_relative_to(REPO_ROOT), resolved

    def test_an_absolute_path_is_taken_as_is(self, tmp_path):
        """The other half: anchoring must not corrupt an operator's own path.

        Fails as: a resolver that joins unconditionally, which would silently
        redirect every externally-supplied config into the checkout.
        """
        from workflows.model_exploration import resolve_lit_review_config_path

        elsewhere = tmp_path / "operator" / "lit_review.yaml"

        assert resolve_lit_review_config_path(str(elsewhere)) == str(elsewhere)

    def test_the_node_cli_anchors_the_same_default(self, tmp_path, monkeypatch):
        """The CLI is a SECOND anchoring of the same value, in another module.

        Fails as: ``_SIDERIUS_ROOT`` drifting off this checkout — the node
        file moving one directory changes ``parents[2]`` and nothing else
        would notice.
        """
        from nodes.ml_literature_review.ml_literature_review import _SIDERIUS_ROOT
        from workflows.run_config import WorkflowLaunchConfig

        monkeypatch.chdir(tmp_path)
        anchored = Path(_SIDERIUS_ROOT) / WorkflowLaunchConfig().lit_review_config_path

        assert anchored.is_file(), anchored
        assert Path(_SIDERIUS_ROOT) == REPO_ROOT, _SIDERIUS_ROOT
