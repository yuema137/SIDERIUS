"""Legacy provider construction must not import the optional Direct API library."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_missing_optional_library_preserves_legacy_route_and_explains_opt_in_failure():
    """A fresh interpreter witnesses absence even when CI installs the extra."""
    source = """
import importlib.abc
import sys

class BlockOptionalLibrary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pydantic_ai" or fullname.startswith("pydantic_ai."):
            raise ModuleNotFoundError("optional dependency deliberately unavailable")

sys.meta_path.insert(0, BlockOptionalLibrary())
from agent.llm_bridge import LLMBridge

legacy = LLMBridge(provider="openai", model_id="test-model", api_key="offline-test-key")
assert legacy.client is legacy.reflect_client
assert legacy.model_name == "test-model"
assert not any(name == "pydantic_ai" or name.startswith("pydantic_ai.") for name in sys.modules)
legacy.client.close()

try:
    LLMBridge(provider="anthropic", model_id="test-model", api_key="offline-test-key")
except ImportError as error:
    assert "siderius[pydantic-ai]" in str(error), str(error)
else:
    raise AssertionError("Optional route must explain its missing dependency")
print("legacy constructed; optional route refused with installation guidance")
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "legacy constructed; optional route refused with installation guidance" in result.stdout
