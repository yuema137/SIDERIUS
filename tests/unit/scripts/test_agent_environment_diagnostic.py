"""Behavioral parity tests for the opt-in provider environment diagnostic.

Defects uniquely owned here: relocation must still resolve the checkout-root
``.env``; importing must not contact a provider; exported keys must retain
precedence over dotenv values; and the three provider-specific call, display,
failure, ordering, and summary behaviors must not drift. Static tools cannot
observe those runtime effects, and a real-provider test would be unsafe and
nondeterministic.

The assertions fail on a wrong parent depth, an eager bridge construction,
changed provider/prompt/order/model filtering, changed exception result, dotenv
override, or a newly nonzero all-failed exit policy. All provider boundaries
are replaced before the script is evaluated, so collection cannot use a key or
network accidentally.
"""

from __future__ import annotations

import contextlib
import io
import os
import runpy
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import pytest
from dotenv import load_dotenv as real_load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "diagnostics" / "check_agent_environment.py"
KEYS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY")
SYSTEM_PROMPT = "You are a helpful assistant."


class BridgeDouble:
    """Record the diagnostic's actual provider calls without external I/O."""

    trace: ClassVar[list[tuple[object, ...]]] = []
    failures: ClassVar[set[str]] = set()

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.model_name = f"{provider}-model"
        self.trace.append(("init", provider))

    def list_models(self) -> list[str]:
        self.trace.append(("list_models", self.provider))
        if self.provider in self.failures:
            raise RuntimeError(f"{self.provider}-boom")
        return {
            "openai": ["oa-0", "oa-1", "oa-2", "oa-3", "oa-4", "oa-5"],
            "gemini": ["alpha", "gemini-one", "xgemini-two"],
            "deepseek": ["deep-a", "deep-b"],
        }[self.provider]

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        self.trace.append(("generate", self.provider, system_prompt, user_prompt))
        return f"{self.provider}-ok"


def _run_script(
    monkeypatch: pytest.MonkeyPatch,
    *,
    keys: tuple[str, ...] = (),
    failures: frozenset[str] = frozenset(),
    as_main: bool = False,
    script: Path = SCRIPT,
    cwd: Path | None = None,
    dotenv_loader: Callable[..., bool] | None = None,
) -> tuple[dict[str, object], list[tuple[object, ...]], str]:
    trace: list[tuple[object, ...]] = []
    BridgeDouble.trace = trace
    BridgeDouble.failures = set(failures)

    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    for key in keys:
        monkeypatch.setenv(key, "exported-value")
    if cwd is not None:
        monkeypatch.chdir(cwd)

    dotenv_module = types.ModuleType("dotenv")

    def record_dotenv(*, dotenv_path: Path) -> bool:
        trace.append(("dotenv", Path(dotenv_path)))
        return False

    dotenv_module.load_dotenv = dotenv_loader or record_dotenv
    bridge_module = types.ModuleType("agent.llm_bridge")
    bridge_module.LLMBridge = BridgeDouble
    monkeypatch.setitem(sys.modules, "dotenv", dotenv_module)
    monkeypatch.setitem(sys.modules, "agent.llm_bridge", bridge_module)

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        namespace = runpy.run_path(
            str(script),
            run_name="__main__" if as_main else "agent_environment_diagnostic_test",
        )
    return namespace, trace, output.getvalue()


def _assert_repo_dotenv(trace: list[tuple[object, ...]], repo_root: Path = REPO_ROOT) -> None:
    assert trace == [("dotenv", repo_root / ".env")]


def test_import_resolves_repo_dotenv_from_unrelated_cwd_and_symlink_without_provider_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Catch ``parents[1]``, CWD lookup, symlink lookup, and eager requests."""
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _namespace, direct_trace, _output = _run_script(monkeypatch, cwd=unrelated)

    link = tmp_path / "check-agent-environment"
    link.symlink_to(SCRIPT)
    _namespace, symlink_trace, _output = _run_script(monkeypatch, script=link, cwd=unrelated)

    _assert_repo_dotenv(direct_trace)
    _assert_repo_dotenv(symlink_trace)


def test_wrong_parent_depth_is_rejected_by_the_root_assertion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A copied ``parents[1]`` mutation resolves to ``scripts/.env`` and fails."""
    synthetic_root = tmp_path / "synthetic-checkout"
    copied_script = synthetic_root / "scripts" / "diagnostics" / SCRIPT.name
    copied_script.parent.mkdir(parents=True)
    source = SCRIPT.read_text(encoding="utf-8")
    mutated = source.replace('parents[2] / ".env"', 'parents[1] / ".env"', 1)
    assert mutated != source
    copied_script.write_text(mutated, encoding="utf-8")

    _namespace, trace, _output = _run_script(monkeypatch, script=copied_script)

    assert trace == [("dotenv", synthetic_root / "scripts" / ".env")]
    with pytest.raises(AssertionError):
        _assert_repo_dotenv(trace, synthetic_root)


def test_missing_keys_return_false_without_constructing_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace, trace, output = _run_script(monkeypatch)

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        results = [namespace[name]() for name in ("test_openai", "test_gemini", "test_deepseek")]
    output += captured.getvalue()

    assert results == [False, False, False]
    assert trace == [("dotenv", REPO_ROOT / ".env")]
    assert "OPENAI_API_KEY not found in .env" in output
    assert "GEMINI_API_KEY not found in .env" in output
    assert "DEEPSEEK_API_KEY not found in .env" in output


def test_success_calls_all_providers_with_exact_prompts_and_preserves_model_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace, trace, output = _run_script(monkeypatch, keys=KEYS)

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        results = [namespace[name]() for name in ("test_openai", "test_gemini", "test_deepseek")]
    output += captured.getvalue()

    assert results == [True, True, True]
    assert trace == [
        ("dotenv", REPO_ROOT / ".env"),
        ("init", "openai"),
        ("list_models", "openai"),
        ("generate", "openai", SYSTEM_PROMPT, "say ok"),
        ("init", "gemini"),
        ("list_models", "gemini"),
        ("generate", "gemini", SYSTEM_PROMPT, "say ok"),
        ("init", "deepseek"),
        ("list_models", "deepseek"),
        ("generate", "deepseek", SYSTEM_PROMPT, "say ok"),
    ]
    assert "  - oa-4" in output and "  - oa-5" not in output
    assert "  ... (Total 6 models found)" in output
    assert "  - gemini-one" in output and "  - xgemini-two" in output
    assert "  - alpha" not in output
    assert "  - deep-a" in output and "  - deep-b" in output
    assert "OpenAI Response: openai-ok" in output
    assert "Gemini (gemini-model) Response: gemini-ok" in output
    assert "DeepSeek (deepseek-model) Response: deepseek-ok" in output


@pytest.mark.parametrize(
    ("provider", "function_name", "failure_line"),
    [
        ("openai", "test_openai", "OpenAI failed: openai-boom"),
        ("gemini", "test_gemini", "Gemini failed: gemini-boom"),
        ("deepseek", "test_deepseek", "DeepSeek failed: deepseek-boom"),
    ],
)
def test_configured_provider_exceptions_return_false_without_generation(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    function_name: str,
    failure_line: str,
) -> None:
    namespace, trace, output = _run_script(monkeypatch, keys=KEYS, failures=frozenset({provider}))

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        result = namespace[function_name]()
    output += captured.getvalue()

    assert result is False
    assert ("init", provider) in trace
    assert ("list_models", provider) in trace
    assert not any(item[:2] == ("generate", provider) for item in trace)
    assert failure_line in output


@pytest.mark.parametrize(
    ("keys", "failures", "summary", "providers"),
    [
        (KEYS, frozenset(), "RESULT: All brains are online!", ["openai", "gemini", "deepseek"]),
        (
            KEYS,
            frozenset({"gemini"}),
            "RESULT: Partial success. Online: OpenAI, DeepSeek",
            ["openai", "gemini", "deepseek"],
        ),
        (
            (),
            frozenset(),
            "RESULT: Critical failure. Check API keys and network.",
            [],
        ),
    ],
)
def test_main_preserves_provider_order_summaries_and_zero_exit_behavior(
    monkeypatch: pytest.MonkeyPatch,
    keys: tuple[str, ...],
    failures: frozenset[str],
    summary: str,
    providers: list[str],
) -> None:
    _namespace, trace, output = _run_script(monkeypatch, keys=keys, failures=failures, as_main=True)

    assert [item[1] for item in trace if item[0] == "init"] == providers
    assert summary in output
    # runpy returned normally: the script still raises no SystemExit, including
    # the all-failed case, so direct execution keeps process exit status zero.


def test_dotenv_uses_real_default_precedence_and_tolerates_absent_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    synthetic = tmp_path / "synthetic.env"
    synthetic.write_text("OPENAI_API_KEY=file-value\nGEMINI_API_KEY=file-gemini\n")
    seen: list[Path] = []

    def load_synthetic(*, dotenv_path: Path) -> bool:
        seen.append(Path(dotenv_path))
        return real_load_dotenv(dotenv_path=synthetic)

    _namespace, _trace, _output = _run_script(
        monkeypatch,
        keys=("OPENAI_API_KEY",),
        dotenv_loader=load_synthetic,
    )

    assert seen == [REPO_ROOT / ".env"]
    assert os.environ["OPENAI_API_KEY"] == "exported-value"
    assert os.environ["GEMINI_API_KEY"] == "file-gemini"

    def load_absent(*, dotenv_path: Path) -> bool:
        seen.append(Path(dotenv_path))
        return real_load_dotenv(dotenv_path=tmp_path / "absent.env")

    _namespace, trace, _output = _run_script(monkeypatch, dotenv_loader=load_absent)
    assert trace == []
    assert seen[-1] == REPO_ROOT / ".env"
    assert "DEEPSEEK_API_KEY" not in os.environ
