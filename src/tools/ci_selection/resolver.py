"""Which unit-test modules a set of changed paths can affect.

Originated in Phase C of the test-architecture work
(`docs/design/pruning_test_rule.md`). Pull-request CI now consumes this authority
through `tools.ci`; master, scheduled runs, selector changes and unresolved
impact still run the full unit suite.

Never imported by production — same rule as `tools/example_packs/`.

WHY A DERIVED MODEL PLUS A MANIFEST, NOT ONE OR THE OTHER
---------------------------------------------------------
A pure manifest goes stale on every rename, and this repository has already
demonstrated the failure: the tuner node's 1,225-case suite lives at
`tests/unit/agent/tune_ml_hyperparam_agent/` — an *old name* for a node that is
now `nodes/ml_hyperparameter_tune_agent/`. A filename heuristic maps that to the
wrong owner, and `tests/unit/nodes/` (30 cases) is not the tuner's suite.

A pure derivation is blind to six categories this module cannot see and does not
pretend to: directory-scoped text reads through a non-constant root, runtime
registry/plugin dispatch, subprocess paths built from non-constants,
conftest-level imports, `importlib` with computed names, and package-prefix
over-approximation.

So: edges are derived from the AST, and the manifest carries only the
exceptions.

THE ONE RULE THAT MATTERS
-------------------------
**Fail closed.** Anything not understood selects the FULL suite. There is no
code path in this module that returns "run nothing" for a non-empty diff; the
only empty selection is for an empty diff.
"""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core.layout import checkout_root, require_checkout

REPO_ROOT = require_checkout(checkout_root())
TESTS_ROOT = REPO_ROOT / "tests" / "unit"

INSTALLED_PACKAGES = frozenset(
    {"agent", "nodes", "core", "execute_tools", "ml_models", "workflows", "dashboard", "tools"}
)

#: Top-level packages that count as "production" for edge purposes.
REPO_PACKAGES = frozenset(
    {
        "agent",
        "core",
        "nodes",
        "execute_tools",
        "ml_models",
        "workflows",
        "scripts",
        "dashboard",
        "tools",
        "examples",
        "agent_generated",
    }
)

#: `tests.helpers.*` is recorded as an edge too. It is not production, but it is
#: the INDIRECTION that hides production dependencies: a helper computes a root
#: the AST cannot resolve, and the modules importing it then look edgeless. The
#: helper's own production reach is declared in the manifest.
HELPER_PACKAGE = "tests.helpers"


@dataclass(frozen=True)
class Selection:
    """What to run, and — as importantly — why."""

    #: Test modules to run, repo-relative. Empty ONLY for an empty diff.
    modules: frozenset[str]
    #: True when the whole suite must run.
    full_suite: bool
    #: Human-readable justification, one line per triggering rule.
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def describe(self) -> str:
        head = "FULL SUITE" if self.full_suite else f"{len(self.modules)} modules"
        return head + "".join(f"\n  - {r}" for r in self.reasons)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _module_name(path: Path) -> str:
    return _rel(path).removeprefix("src/").removesuffix(".py").replace("/", ".")


def _imported_targets(tree: ast.AST, own_module: str) -> set[str]:
    """Repo-internal dotted targets this module imports.

    `from agent.schemas import hyperparam_tuning` binds the SUBMODULE, not just
    the package, so both are recorded — otherwise a change to one schema file
    would look like a change to the whole package and select far too much.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in REPO_PACKAGES or alias.name.startswith(
                    HELPER_PACKAGE
                ):
                    out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import; resolve against the owning module
                base = own_module.rsplit(".", node.level)[0] if own_module else ""
                mod = f"{base}.{node.module}" if node.module else base
            else:
                mod = node.module or ""
            if not mod or (
                mod.split(".")[0] not in REPO_PACKAGES and not mod.startswith(HELPER_PACKAGE)
            ):
                continue
            out.add(mod)
            for alias in node.names:
                out.add(f"{mod}.{alias.name}")
    return out


def _literal_path_references(tree: ast.AST, known_files: frozenset[str]) -> set[str]:
    """Repo files named by a literal string, or by a constant `Path(...) / "a"`
    chain, anywhere in the module.

    This is the edge type that catches a test spawning a production entry point
    by path, and a test reading a `.md` as an input — both of which are real in
    this repo and invisible to imports. Matching is by unique path SUFFIX, so a
    bare `"run_chain.sh"` resolves.
    """
    out: set[str] = set()
    literals: list[str] = [
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    # Constant BinOp chains (`ROOT / "a" / "b.py"`) contribute their pieces;
    # joining consecutive pieces catches multi-segment references.
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            pieces = [
                c.value
                for c in ast.walk(node)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
            ]
            if len(pieces) > 1:
                literals.append("/".join(pieces))
    for text in literals:
        cleaned = text.strip().lstrip("./")
        if not cleaned or " " in cleaned:
            continue
        for known in known_files:
            if known == cleaned or known.endswith("/" + cleaned):
                out.add(known)
    return out


def _resolved_import_paths(
    tree: ast.AST, own_module: str, known_files: AbstractSet[str]
) -> set[str]:
    """Tracked Python files imported by one parsed module."""
    out: set[str] = set()
    for dotted in _imported_targets(tree, own_module):
        prefix = "src/" if dotted.split(".")[0] in INSTALLED_PACKAGES else ""
        as_module = prefix + dotted.replace(".", "/") + ".py"
        as_package = prefix + dotted.replace(".", "/") + "/__init__.py"
        if as_module in known_files:
            out.add(as_module)
        if as_package in known_files:
            out.add(as_package)
    return out


@lru_cache(maxsize=1)
def _tracked_repository_files() -> frozenset[str]:
    """Repository inputs present in the candidate commit.

    Git is the inventory authority for the same reason it is in the execution
    harness: a filesystem walk admits ignored scratch files and misses tracked
    root documents when its directory list drifts. A failed inventory raises;
    both public wrappers convert that failure to the full suite.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return frozenset(item.decode("utf-8") for item in result.stdout.split(b"\0") if item)


@lru_cache(maxsize=1)
def _build_edges_cached() -> tuple[tuple[str, frozenset[str]], ...]:
    """Cached inner form. The scan parses ~600 files and is pure with respect to
    a checkout, so recomputing it per test turned this module into 100s of the
    very suite it exists to shrink."""
    return tuple((m, frozenset(t)) for m, t in _build_edges_uncached().items())


def build_edges() -> dict[str, set[str]]:
    """`{test module -> reachable production paths}`, cached per process."""
    return {m: set(t) for m, t in _build_edges_cached()}


def _build_edges_uncached() -> dict[str, set[str]]:
    """`{test module (repo-relative) -> {production paths it can reach}}`.

    Import targets are recorded as dotted names AND as the file they resolve
    to, so a caller can match either form.
    """
    known = _tracked_repository_files()
    edges: dict[str, set[str]] = {}
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test fails collection
            continue
        rel = _rel(path)
        dotted_targets = _imported_targets(tree, _module_name(path))
        targets = _resolved_import_paths(tree, _module_name(path), known)
        targets.update(dotted_targets)
        targets |= _literal_path_references(tree, known)
        edges[rel] = targets
    return edges


@lru_cache(maxsize=1)
def _build_source_edges_cached() -> tuple[tuple[str, frozenset[str]], ...]:
    return tuple((source, frozenset(targets)) for source, targets in _build_source_edges().items())


def build_source_edges() -> dict[str, set[str]]:
    """``{production file -> directly imported production files}``."""
    return {source: set(targets) for source, targets in _build_source_edges_cached()}


def _build_source_edges() -> dict[str, set[str]]:
    """Build the small static import graph used for affected-caller closure.

    This intentionally models only explicit Python imports. Dynamic/plugin and
    computed-path relationships remain manifest declarations; an AST is not
    presented as proof of every runtime dependency.
    """
    known = _tracked_repository_files()
    sources = sorted(
        rel
        for rel in known
        if rel.endswith(".py") and rel.removeprefix("src/").split("/", 1)[0] in REPO_PACKAGES
    )
    edges: dict[str, set[str]] = {}
    for rel in sources:
        path = REPO_ROOT / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            raise RuntimeError(f"cannot derive imports for {rel}: {exc}") from exc
        edges[rel] = _resolved_import_paths(tree, _module_name(path), known)
    return edges


def transitive_test_owners(
    changed: AbstractSet[str],
    test_edges: Mapping[str, AbstractSet[str]],
    source_edges: Mapping[str, AbstractSet[str]],
) -> set[str]:
    """Tests importing a changed source directly or through source callers.

    The fixed-point traversal is deliberately independent of repository I/O so
    its two-hop and cycle behavior can be proved with a tiny hand-built graph.
    """
    affected = set(changed)
    while True:
        callers = {source for source, targets in source_edges.items() if targets & affected}
        expanded = affected | callers
        if expanded == affected:
            break
        affected = expanded
    return {module for module, targets in test_edges.items() if targets & affected}


def _derived_owners(
    changed: str,
    test_edges: Mapping[str, AbstractSet[str]],
    source_edges: Mapping[str, AbstractSet[str]],
) -> set[str]:
    """Import-derived owners, preserving the package-prefix over-approximation."""
    owners = transitive_test_owners({changed}, test_edges, source_edges)
    dotted = changed.removeprefix("src/").removesuffix(".py").replace("/", ".")
    owners |= {
        module
        for module, targets in test_edges.items()
        if any(target == dotted or dotted.startswith(target + ".") for target in targets)
    }
    return owners


def select(changed_paths: list[str]) -> Selection:
    """The entry point. **Fail closed**: anything not understood runs everything.

    There is deliberately no branch that yields an empty selection for a
    non-empty diff. A selector that can answer "run nothing" is the one failure
    mode worse than no selector at all, because it produces a confident green.
    """
    from tools.ci_selection import manifest as mf

    if not changed_paths:
        return Selection(frozenset(), full_suite=False, reasons=("empty diff",))

    reasons: list[str] = []
    for changed in changed_paths:
        for trigger in mf.FULL_SUITE_TRIGGERS:
            if changed == trigger or changed.startswith(trigger):
                reasons.append(f"{changed}: infrastructure/selector trigger ({trigger})")
        for hub in mf.HUBS:
            if changed == hub or changed.startswith(hub):
                reasons.append(f"{changed}: declared hub ({hub}) — selecting would be a lie")
    if reasons:
        return Selection(frozenset(), full_suite=True, reasons=tuple(reasons))

    edges = build_edges()
    source_edges = build_source_edges()
    known_production = _tracked_repository_files()
    selected: set[str] = set()

    for always in mf.ALWAYS_ON:
        selected |= {m for m in edges if m == always or m.startswith(always)}
    reasons.append(f"always-on block: {len(selected)} modules")

    for changed in changed_paths:
        if changed.startswith("tests/"):
            # A changed test runs itself, and a conftest runs its directory.
            if changed.endswith("conftest.py"):
                scope = changed.rsplit("/", 1)[0] + "/"
                hit = {m for m in edges if m.startswith(scope)}
                selected |= hit
                reasons.append(f"{changed}: conftest scope -> {len(hit)} modules")
            elif changed in edges:
                selected.add(changed)
                reasons.append(f"{changed}: changed test module")
            # A changed helper selects every module importing it.
            owners = {m for m, t in edges.items() if changed in t}
            if owners:
                selected |= owners
                reasons.append(f"{changed}: imported by {len(owners)} modules")
            continue

        if changed not in known_production:
            return Selection(
                frozenset(),
                full_suite=True,
                reasons=(f"{changed}: no inbound edge and no manifest rule — failing closed",),
            )

        direct = _derived_owners(changed, edges, source_edges)
        for owner, scanned in mf.DIRECTORY_SCANS.items():
            if any(changed == s or changed.startswith(s) for s in scanned):
                direct.add(owner)
                direct |= {m for m, t in edges.items() if owner in t}
        # Area ownership is additive. One derived edge is not evidence that no
        # other test in the changed module's owning area exercises it through a
        # fixture, registry, subprocess, or computed path.
        area = next(
            (tests for prefix, tests in mf.AREA_OWNERS if changed.startswith(prefix)),
            None,
        )
        if area is not None:
            area_modules = {m for m in edges if any(m.startswith(t) for t in area)}
            if not area_modules:
                return Selection(
                    frozenset(),
                    full_suite=True,
                    reasons=(f"{changed}: area owner {area} matched no modules — failing closed",),
                )
            direct |= area_modules
            reasons.append(f"{changed}: additive area owner -> {len(area_modules)} modules")
        if not direct:
            if changed.endswith(mf.NON_IMPORTABLE_SUFFIXES):
                reasons.append(f"{changed}: not importable and read by no test — no suites")
                continue
            return Selection(
                frozenset(),
                full_suite=True,
                reasons=(f"{changed}: no edge and no area owner — failing closed",),
            )
        selected |= direct
        reasons.append(f"{changed}: {len(direct)} owning modules")

    return Selection(frozenset(selected), full_suite=False, reasons=tuple(reasons))


def gates_required(changed_paths: list[str]) -> tuple[str, ...]:
    """Advisory only. CI must NEVER trigger a Gate — they cost money and need
    operator approval (`docs/gates/gate_testing_standard.md:148`)."""
    from tools.ci_selection import manifest as mf

    out: set[str] = set()
    for changed in changed_paths:
        for area, gates in mf.GATE_REQUIREMENTS.items():
            if changed == area or changed.startswith(area):
                out.update(gates)
    return tuple(sorted(out))
