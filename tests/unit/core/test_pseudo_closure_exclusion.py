"""Pseudo-only modules stay outside every paper-facing source closure (#1498).

``core-contract.md`` states that ``core/stub_sandbox.py`` and its pseudo helpers
``core/pseudo_deliverables.py`` and ``core/pseudo_scoring.py`` are outside every
assembly digest closure, so a pseudo-only edit moves no identity that
siderius-exp qualifies (#1475). The owners covered are the four assembly
digests, ``runtime_environment_identity`` and the planner strategy assembly
(``PlannerStrategyIdentity.assembly_sha256``, pinned by siderius-exp
planner_compat). Each owner builds its file list inline,
so this test records the source files the owner actually reads while computing
its value instead of copying the lists. If a closure gains a pseudo-only file,
``test_pseudo_only_modules_outside_closure`` names the owner and the file.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import agent.planner_strategy as planner_strategy
import agent.prompt_rendering as prompt_rendering
from agent.data_analysis.generated_programs import runtime_environment_identity
from core.planner_strategy_identity import PlannerStrategyIdentity
from core.preflight_estimation import estimation_assembly_digest
from core.runtime_control.gpu_protection import protection_mechanism_digest
from core.runtime_control.verifier_provider import verifier_assembly_digest

SRC_ROOT = Path(prompt_rendering.__file__).resolve().parents[1]

PSEUDO_ONLY_MODULES = frozenset(
    {
        "core/stub_sandbox.py",
        "core/pseudo_deliverables.py",
        "core/pseudo_scoring.py",
    }
)


def planner_strategy_assembly() -> str:
    """Pin a stub strategy; the assembly digest ignores the strategy's own content."""
    stub = planner_strategy.PlannerStrategy(
        identity=PlannerStrategyIdentity(name="stub", version="0", content_sha256="0" * 64),
        system_template="",
        user_renderer=lambda *_args, **_kwargs: "",
        uses_timing_context=False,
    )
    pinned = planner_strategy._with_assembly_identity(stub, expected=None)  # pyright: ignore[reportPrivateUsage]
    assert pinned.identity.assembly_sha256 is not None
    return pinned.identity.assembly_sha256


# Each owner hashes its own module, which proves the read capture saw the closure.
CLOSURE_OWNERS: tuple[tuple[str, Callable[[], str], str], ...] = (
    (
        "rendering_assembly_digest",
        prompt_rendering.rendering_assembly_digest,
        "agent/prompt_rendering.py",
    ),
    (
        "estimation_assembly_digest",
        estimation_assembly_digest,
        "core/preflight_estimation.py",
    ),
    (
        "protection_mechanism_digest",
        protection_mechanism_digest,
        "core/runtime_control/gpu_protection.py",
    ),
    (
        "verifier_assembly_digest",
        verifier_assembly_digest,
        "core/runtime_control/verifier_provider.py",
    ),
    (
        "runtime_environment_identity",
        runtime_environment_identity,
        "agent/data_analysis/generated_programs.py",
    ),
    (
        "planner_strategy_assembly",
        planner_strategy_assembly,
        "agent/planner_strategy.py",
    ),
)


def _closure_files(monkeypatch: pytest.MonkeyPatch, owner: Callable[[], str]) -> set[str]:
    """Return the src-relative files whose bytes ``owner`` reads."""
    original = Path.read_bytes
    read: set[str] = set()

    def recording_read_bytes(path: Path) -> bytes:
        resolved = path.resolve()
        if resolved.is_relative_to(SRC_ROOT):
            read.add(resolved.relative_to(SRC_ROOT).as_posix())
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", recording_read_bytes)
        owner()
    return read


def test_pseudo_only_modules_exist() -> None:
    """A rename would otherwise make the exclusion assertion pass vacuously."""
    missing = sorted(name for name in PSEUDO_ONLY_MODULES if not (SRC_ROOT / name).is_file())
    assert not missing, f"pseudo-only module moved; update this guard: {missing}"


@pytest.mark.parametrize(
    ("name", "owner", "own_module"), CLOSURE_OWNERS, ids=[o[0] for o in CLOSURE_OWNERS]
)
def test_pseudo_only_modules_outside_closure(
    monkeypatch: pytest.MonkeyPatch, name: str, owner: Callable[[], str], own_module: str
) -> None:
    closure = _closure_files(monkeypatch, owner)
    assert own_module in closure, f"{name} read capture missed its own module: {sorted(closure)}"
    leaked = sorted(closure & PSEUDO_ONLY_MODULES)
    assert not leaked, f"{name} hashes pseudo-only module(s) {leaked}"
