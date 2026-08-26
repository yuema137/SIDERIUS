"""Node documentation cites protocols and CLIs that exist (issues #262, #263).

Four defects only these tests catch:

1. **A phantom protocol.** On master at `c991d6f6` the node docs and
   `docs/architecture.md` cited `proposal_to_implementor_v1`,
   `proposal_to_hyperparam_seeded_v1`, `interpretation_to_proposal_v1`,
   `implementor_to_validator_v1`, `hyperparam_to_interpretation_full_v1` and
   `validator_to_hyperparam_v1` — names defined nowhere. Every `…_to_…`
   token in the node docs must now resolve: a token in the protocol-module
   grammar (`ml_<x>_to_ml_<y>`) to a module under `agent/schemas/protocols/`
   (and its `::function`, when cited, to a `def` in that module); any other
   `…_to_…` identifier to a name defined in production source.
   `docs/architecture.md` was repaired by hand in the same PR but is NOT
   scanned here: the CI selector's own test uses it as the exemplar of "a
   doc nothing reads" (`tests/unit/tools/ci_selection/test_selection_model.py`,
   `test_a_doc_nothing_reads_selects_no_extra_suites`), and a literal read
   from this module would change what a docs-only PR selects. Widening the
   scan is a one-line change here once that exemplar is re-picked.
2. **A node doc lying about its CLI.** `**Node type**: standalone-capable`
   must coincide with an `if __name__ == "__main__":` guard in the node's
   main module, and `workflow-only` with its absence.
3. **A stale `main()` line in the agent reference.** The `CLI` column of
   `docs/agent-reference/README.md` cites `file:line`; that line must be a
   `def main`. (It WILL move when PR-12d lands and the tuner's `cli.py`
   changes — that is the point: the doc is then corrected, not left stale.)
4. **A protocol module the registry docstring does not name.** Every
   `*_to_*.py` under `agent/schemas/protocols/` must be listed in the
   package docstring — the registry said "five" for months while six existed.

How they fail: re-introduce `proposal_to_implementor_v1` in a node doc →
`test_every_protocol_token_in_node_docs_resolves` names it; flip a node's
type word → `test_node_type_matches_the_presence_of_a_main_guard` names the
node; move `main()` → `test_agent_reference_cli_column_points_at_def_main`
names the row. Each was plant-proven at authoring time (see the PR body).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOCOLS_DIR = REPO_ROOT / "agent" / "schemas" / "protocols"
PROTOCOLS_INIT = REPO_ROOT / "agent" / "schemas" / "protocols" / "__init__.py"
AGENT_REFERENCE_README = REPO_ROOT / "docs" / "agent-reference" / "README.md"

#: The node docs, literally — so the CI selector derives an edge from each
#: to this module, and so a new node must be registered here to be guarded
#: (`test_node_docs_tuple_matches_the_checkout` enforces that).
NODE_DOCS: tuple[str, ...] = (
    "nodes/ml_code_validator_agent/ml_code_validator_agent.md",
    "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md",
    "nodes/ml_literature_review/ml_literature_review.md",
    "nodes/ml_model_implementor/ml_model_implementor.md",
    "nodes/ml_model_proposal_agent/ml_model_proposal_agent.md",
    "nodes/result_interpretation_agent/result_interpretation_agent.md",
)

PRODUCTION_ROOTS = ("agent", "nodes", "core", "execute_tools", "workflows")

_PROTOCOL_MODULE = re.compile(r"^ml_[a-z0-9_]+_to_ml_[a-z0-9_]+$")
#: An identifier-shaped token containing `_to_`, optionally cited as
#: `path/module.py::function`. Prose never carries underscores, so this is
#: specific enough to run over whole files including fenced code.
_TO_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_/])((?:[a-z0-9_]+/)*[a-z][a-z0-9_]*_to_[a-z0-9_]+)(\.py)?(?:::([a-z_][a-z0-9_]*))?(?![A-Za-z0-9_])"
)
_NODE_TYPE = re.compile(r"\*\*Node type\*\*: \*\*(standalone-capable|workflow-only)\*\*")
_MAIN_GUARD = re.compile(r'^if __name__ == "__main__":', re.MULTILINE)
_CLI_CELL = re.compile(r"`(nodes/[A-Za-z0-9_/]+\.py):(\d+)`")


def _node_doc_paths_in_checkout() -> tuple[str, ...]:
    out: list[str] = []
    for md in sorted((REPO_ROOT / "nodes").glob("*/*.md")):
        if md.stem == md.parent.name:
            out.append(md.relative_to(REPO_ROOT).as_posix())
    return tuple(out)


def _production_identifiers() -> set[str]:
    """Every name production source DEFINES: functions, classes, module and
    class-level assignments (Pydantic fields included) and import aliases."""
    names: set[str] = set()
    for root in PRODUCTION_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - a broken module fails elsewhere
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    names.add(node.name)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
                elif isinstance(node, ast.alias):
                    names.add(node.asname or node.name.split(".")[-1])
    return names


def _protocol_modules() -> dict[str, set[str]]:
    """`{module stem: {function names}}` for every protocol module."""
    out: dict[str, set[str]] = {}
    for path in sorted(PROTOCOLS_DIR.glob("*_to_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out[path.stem] = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert out, "no protocol modules found — did agent/schemas/protocols/ move?"
    return out


def _tokens(text: str) -> list[tuple[str, str | None]]:
    """`(module_or_identifier, function_or_None)` for every `_to_` citation."""
    out: list[tuple[str, str | None]] = []
    for m in _TO_TOKEN.finditer(text):
        name = m.group(1).rsplit("/", 1)[-1]
        out.append((name, m.group(3)))
    return out


def _scanned_documents() -> list[str]:
    return list(NODE_DOCS)


# ---------------------------------------------------------------------------
# 0. The literal tuple is the checkout
# ---------------------------------------------------------------------------


def test_node_docs_tuple_matches_the_checkout() -> None:
    assert _node_doc_paths_in_checkout() == NODE_DOCS, (
        "a node doc was added, removed or renamed; update NODE_DOCS so the "
        "guard (and the CI selector's edge to it) covers the current checkout"
    )


# ---------------------------------------------------------------------------
# 1. Every protocol token resolves
# ---------------------------------------------------------------------------


def test_every_protocol_token_in_node_docs_resolves() -> None:
    modules = _protocol_modules()
    identifiers = _production_identifiers()
    problems: list[str] = []
    for rel in _scanned_documents():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for name, func in _tokens(text):
            if _PROTOCOL_MODULE.match(name):
                if name not in modules:
                    problems.append(
                        f"{rel}: `{name}` is not a module under agent/schemas/protocols/"
                    )
                elif func is not None and func not in modules[name]:
                    problems.append(f"{rel}: `{name}.py::{func}` — no such function in that module")
            elif name not in identifiers:
                problems.append(
                    f"{rel}: `{name}` is neither a protocol module nor an identifier "
                    "defined anywhere in production source (a phantom protocol name?)"
                )
    assert not problems, "\n".join(problems)


def test_the_token_scanner_sees_a_phantom_and_a_real_citation() -> None:
    """Oracle for the extractor: a cited phantom is produced as a token, a
    real `module.py::function` citation splits correctly, and a templated
    placeholder is not mistaken for a name."""
    text = (
        "via `proposal_to_implementor_v1` and "
        "`agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py::local_full_spec`; "
        "named `{source_code}_to_{target_code}.py`"
    )
    assert _tokens(text) == [
        ("proposal_to_implementor_v1", None),
        ("ml_model_propose_to_ml_model_impl", "local_full_spec"),
    ]


# ---------------------------------------------------------------------------
# 2. Node type <-> __main__ guard
# ---------------------------------------------------------------------------


def test_node_type_matches_the_presence_of_a_main_guard() -> None:
    problems: list[str] = []
    for rel in NODE_DOCS:
        doc = REPO_ROOT / rel
        declared = _NODE_TYPE.findall(doc.read_text(encoding="utf-8"))
        assert len(declared) == 1, (
            f"{rel}: expected exactly one **Node type** declaration, got {declared}"
        )
        module = doc.with_suffix(".py")
        has_main = bool(_MAIN_GUARD.search(module.read_text(encoding="utf-8")))
        if declared[0] == "standalone-capable" and not has_main:
            problems.append(
                f"{rel}: says standalone-capable, but {module.name} has no __main__ guard"
            )
        if declared[0] == "workflow-only" and has_main:
            problems.append(f"{rel}: says workflow-only, but {module.name} has a __main__ guard")
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------
# 3. The agent-reference CLI column
# ---------------------------------------------------------------------------


def test_agent_reference_cli_column_points_at_def_main() -> None:
    text = AGENT_REFERENCE_README.read_text(encoding="utf-8")
    cited = _CLI_CELL.findall(text)
    # Declared delta (#303/#305, landed 9f826731): the literature-review node
    # gained a CLI, so SIX nodes are standalone — the 5-count pin and the
    # workflow-only marker moved WITH that landing.
    assert len(cited) == 6, (
        f"expected six `file:line` CLI citations (all six nodes standalone, #303), got {cited}"
    )
    problems: list[str] = []
    for rel, line_no in cited:
        lines = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
        actual = lines[int(line_no) - 1] if int(line_no) <= len(lines) else "<past end of file>"
        if not actual.startswith("def main("):
            problems.append(f"{rel}:{line_no} is {actual!r}, not a `def main(` line")
    assert not problems, "\n".join(problems)
    # #303 removed the one asterisk: NO node may be marked workflow-only in
    # the CLI column any more — a reintroduced marker is the drift this pins.
    assert "ml_literature_review" in text
    assert "workflow-only; no `main()`" not in text


# ---------------------------------------------------------------------------
# 4. The registry docstring names every module
# ---------------------------------------------------------------------------


def test_protocol_registry_docstring_names_every_module() -> None:
    docstring = ast.get_docstring(ast.parse(PROTOCOLS_INIT.read_text(encoding="utf-8"))) or ""
    missing = sorted(stem for stem in _protocol_modules() if stem not in docstring)
    assert not missing, (
        f"protocol modules absent from agent/schemas/protocols/__init__.py's docstring: {missing}"
    )
