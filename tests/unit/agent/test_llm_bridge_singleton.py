"""
Architectural invariant test: LLMBridge is the ONLY place in agent/,
nodes/, and workflows/ that constructs an OpenAI() client.

Why: LLMBridge is the universal API gateway for SIDERIUS. It owns the
retry policy, timeouts, provider routing, planner/reflector model
split, and any future cross-cutting concerns. If a future agent
silently sneaks in its own `OpenAI()` instance, it opts out of every
one of those guarantees, and the bug typically only surfaces in
production under load (e.g. unretried 503 from a transient API outage).

This test fails fast in CI if anyone bypasses the bridge.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCAN_DIRS = ["agent", "nodes", "workflows"]
ALLOWED_FILE = REPO_ROOT / "agent" / "llm_bridge.py"

# Match `OpenAI(` as a constructor call. Avoids matching `from openai import OpenAI`
# (no parenthesis) and string literals containing the word.
PATTERN = re.compile(r"\bOpenAI\s*\(")


def _scan_for_openai_constructors() -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for d in SCAN_DIRS:
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for py in root.rglob("*.py"):
            if py == ALLOWED_FILE:
                continue
            with open(py, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, start=1):
                    # Skip comments and string-only matches
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        continue
                    if PATTERN.search(line):
                        hits.append((py, lineno, line.rstrip()))
    return hits


def test_only_llm_bridge_constructs_openai_client():
    """Fail if any file outside agent/llm_bridge.py instantiates OpenAI()."""
    hits = _scan_for_openai_constructors()
    if hits:
        msg_lines = [
            "Architectural invariant violated: only agent/llm_bridge.py",
            "may construct an OpenAI() client. Found rogue constructors:",
            "",
        ]
        for path, lineno, line in hits:
            rel = path.relative_to(REPO_ROOT)
            msg_lines.append(f"  {rel}:{lineno}: {line.strip()}")
        msg_lines += [
            "",
            "Route the offending call through an LLMBridge instance instead.",
            "See agent/llm_bridge.py for the rationale.",
        ]
        raise AssertionError("\n".join(msg_lines))


def test_llm_bridge_itself_still_constructs_openai():
    """Sanity: the bridge file itself MUST contain OpenAI() (else the
    singleton check is meaningless)."""
    with open(ALLOWED_FILE, "r", encoding="utf-8") as f:
        text = f.read()
    assert PATTERN.search(text), (
        f"{ALLOWED_FILE} no longer constructs an OpenAI client — "
        f"the singleton invariant is meaningless without it."
    )
