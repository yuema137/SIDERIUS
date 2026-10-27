"""Keep provider construction and direct model requests inside the LLM gateway.

Import-aware AST inspection catches qualified calls and imported aliases without
matching comments or documentation. This is a static architecture guard, not a
sandbox: dynamic imports and runtime reassignment are outside its coverage.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_DIRS = ("src/agent", "src/nodes", "src/workflows")
CONSTRUCTOR_OWNERS = frozenset({"src/agent/llm_bridge.py", "src/agent/llm_transport/providers.py"})
REQUEST_OWNERS = frozenset({"src/agent/llm_transport/runtime.py"})
SDK_CONSTRUCTORS = frozenset(
    {
        "openai.OpenAI",
        "openai.AsyncOpenAI",
        "anthropic.Anthropic",
        "anthropic.AsyncAnthropic",
    }
)


def _qualified_name(node: ast.expr, imports: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return imports.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value, imports)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def _guarded_calls(source: str) -> list[tuple[int, str, frozenset[str]]]:
    """Return protected call sites and their explicit permitted file owners."""
    tree = ast.parse(source)
    imports: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imports[name] = alias.name if alias.asname else name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                imports[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _qualified_name(node.func, imports)
        if name in SDK_CONSTRUCTORS or (
            name.startswith(("pydantic_ai.models.", "pydantic_ai.providers."))
            and name.rsplit(".", 1)[-1].endswith(("Model", "Provider"))
        ):
            hits.append((node.lineno, name, CONSTRUCTOR_OWNERS))
        elif name.startswith("pydantic_ai.direct."):
            hits.append((node.lineno, name, REQUEST_OWNERS))
    return hits


def test_only_gateway_owners_construct_clients_or_request_models():
    """A node cannot bypass bridge retries/accounting via a new vendor SDK."""
    violations = []
    for directory in SCAN_DIRS:
        root = REPO_ROOT / directory
        sources = tuple(root.rglob("*.py"))
        assert root.is_dir() and sources, f"missing production scan subject: {root}"
        for path in sources:
            relative = path.relative_to(REPO_ROOT).as_posix()
            for line, name, owners in _guarded_calls(path.read_text(encoding="utf-8")):
                if relative not in owners:
                    violations.append(f"{relative}:{line}: {name}")
    assert not violations, "Route model access through LLMBridge:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from openai import OpenAI as Client\nClient()", "openai.OpenAI"),
        ("import openai as sdk\nsdk.AsyncOpenAI()", "openai.AsyncOpenAI"),
        ("import anthropic\nanthropic.Anthropic()", "anthropic.Anthropic"),
        (
            "from anthropic import AsyncAnthropic as Client\nClient()",
            "anthropic.AsyncAnthropic",
        ),
        (
            "from pydantic_ai.models.anthropic import AnthropicModel as Model\nModel('x')",
            "pydantic_ai.models.anthropic.AnthropicModel",
        ),
        (
            "import pydantic_ai.direct as direct\ndirect.model_request_sync(None, [])",
            "pydantic_ai.direct.model_request_sync",
        ),
        (
            "from pydantic_ai.direct import model_request as request\nrequest(None, [])",
            "pydantic_ai.direct.model_request",
        ),
        (
            "import pydantic_ai.models.openai\npydantic_ai.models.openai.OpenAIChatModel('x')",
            "pydantic_ai.models.openai.OpenAIChatModel",
        ),
    ],
)
def test_imported_aliases_cannot_hide_gateway_bypasses(source, expected):
    """The previous textual OpenAI-only scan missed these executable calls."""
    hits = _guarded_calls(source)
    assert len(hits) == 1
    assert hits[0][1] == expected


def test_documentation_and_unrelated_constructors_are_not_executable_bypasses():
    source = """
# OpenAI()
description = "anthropic.Anthropic() and OpenAI()"
from local_models import OpenAI
OpenAI()
"""
    assert _guarded_calls(source) == []


def test_request_permission_does_not_allow_provider_construction():
    """Runtime may issue Direct API requests but must use the provider owner."""
    calls = _guarded_calls(
        "from openai import AsyncOpenAI\n"
        "from pydantic_ai.direct import model_request_sync\n"
        "AsyncOpenAI()\nmodel_request_sync(None, [])"
    )
    constructor_owners, request_owners = (call[2] for call in calls)
    assert "src/agent/llm_transport/runtime.py" not in constructor_owners
    assert "src/agent/llm_transport/runtime.py" in request_owners
    assert "src/agent/llm_transport/providers.py" not in request_owners


def test_legacy_bridge_still_contains_a_guarded_constructor():
    """The production scan has a real positive subject, not only fixtures."""
    source = (REPO_ROOT / "src/agent/llm_bridge.py").read_text(encoding="utf-8")
    assert any(name == "openai.OpenAI" for _, name, _ in _guarded_calls(source))
