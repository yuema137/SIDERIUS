"""AST census of RNG use in ``src/**/*.py`` (issue #983 S8, seed contract §8.4).

Kept test-side: a pure reader of the checkout's own source tree. Every finding
is keyed by ``(module, function, call)`` so an allowlist entry names one site.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src"

_PY_RANDOM = frozenset(
    {
        "random",
        "randint",
        "randrange",
        "choice",
        "choices",
        "shuffle",
        "sample",
        "uniform",
        "gauss",
        "normalvariate",
        "seed",
        "Random",
        "getrandbits",
        "triangular",
        "betavariate",
    }
)
_NP_RANDOM_OK = frozenset({"Generator", "PCG64", "BitGenerator", "SeedSequence"})
_TORCH = frozenset(
    {
        "rand",
        "randn",
        "randint",
        "randperm",
        "rand_like",
        "randn_like",
        "randint_like",
        "manual_seed",
        "Generator",
        "normal",
        "bernoulli",
        "multinomial",
        "poisson",
    }
)
_HASH_SCOPES = ("execute_tools/", "nodes/")
_ENTRY_SEEDERS = frozenset({"seed_process", "apply_process_seeds", "seeded_scope"})
_ALIASED = ("random", "numpy", "numpy.random", "torch", "secrets")


@dataclass(frozen=True, order=True)
class Site:
    module: str
    function: str
    call: str


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _flag(dotted: str, node: ast.Call, module: str) -> str | None:
    parts = dotted.split(".")
    head, last = parts[0], parts[-1]
    if head == "random" and len(parts) == 2 and last in _PY_RANDOM:
        return dotted
    if head in {"np", "numpy"} and len(parts) == 3 and parts[1] == "random":
        return None if last in _NP_RANDOM_OK else dotted
    if head == "torch" and (
        (len(parts) == 2 and last in _TORCH)
        or (parts[1:] in (["cuda", "manual_seed"], ["cuda", "manual_seed_all"]))
    ):
        return dotted
    if head == "secrets":
        return dotted
    if dotted == "hash" and module.startswith(_HASH_SCOPES):
        return "hash"
    if last == "DataLoader":
        shuffle = {k.arg: k.value for k in node.keywords}
        value = shuffle.get("shuffle")
        unseeded = "generator" not in shuffle
        if (
            unseeded
            and value is not None
            and not (isinstance(value, ast.Constant) and value.value is False)
        ):
            return "DataLoader(shuffle) without generator"
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: str, aliases: dict[str, str]) -> None:
        self.module = module
        self.aliases = aliases
        self.stack: list[str] = []
        self.sites: set[Site] = set()
        self.calls: set[str] = set()

    def _scope(self, node) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        if dotted is not None:
            first, _, rest = dotted.partition(".")
            if first in self.aliases:  # e.g. ``from numpy.random import default_rng``
                dotted = self.aliases[first] + ("." + rest if rest else "")
            self.calls.add(dotted.split(".")[-1])
            flagged = _flag(dotted, node, self.module)
            if flagged is not None:
                self.sites.add(Site(self.module, ".".join(self.stack) or "<module>", flagged))
        self.generic_visit(node)


def _aliases(tree: ast.Module) -> dict[str, str]:
    """Local names bound to RNG modules or their members, as canonical dotted names."""
    canonical = {"numpy": "np"}
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _ALIASED:
            base = ".".join(canonical.get(p, p) for p in node.module.split("."))
            for alias in node.names:
                found[alias.asname or alias.name] = f"{base}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _ALIASED and alias.asname:
                    found[alias.asname] = ".".join(
                        canonical.get(p, p) for p in alias.name.split(".")
                    )
    found.pop("np", None)
    return found


def _imports_torch(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "torch" for a in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "torch":
            return True
    return False


def _is_entry(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return True
        if isinstance(node, ast.If) and "__name__" in ast.unparse(node.test):
            return True
    return False


def census(root: Path = SRC) -> tuple[set[Site], set[str]]:
    """RNG call sites, and torch-importing process entries that never seed."""
    sites: set[Site] = set()
    entries: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        module = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _Visitor(module, _aliases(tree))
        visitor.visit(tree)
        sites |= visitor.sites
        if _is_entry(tree) and _imports_torch(tree) and not visitor.calls & _ENTRY_SEEDERS:
            entries.add(module)
    return sites, entries
