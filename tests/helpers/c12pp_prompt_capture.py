"""C12-P-P — byte-exact capture of the PROPOSER prompts, per task regime.

WHAT THIS IS FOR
----------------
C12-P-P investigates whether a FOREIGN composed task receives TIDMAD-specific
scientific constraints merely because it traverses the shared proposer prompt
path. Answering that requires the *bytes* a real run's LLM would see, for both
regimes, produced by the PRODUCTION assembly path — not by a re-implementation.

THE RENDERING PATH IS PRODUCTION, NOT INVENTED
----------------------------------------------
This module reuses the exact technique of the landed
``scripts/render_proposer_prompts_for_audit.py`` (Checkpoint P): build a real
:class:`~agent.schemas.proposal.ProposalInput` through the production protocol
``local_full_context``, then run ``MLModelProposalAgent.run`` with
``LLMBridge.generate`` / ``generate_text`` patched to CAPTURE the
``(system_prompt, user_prompt)`` pair and return a canned reply. Every prompt
byte is therefore assembled by ``_run_pipeline`` exactly as in production.

Zero LLM calls. Zero network. Zero GPU. ``OPENAI_API_KEY`` must be set to any
non-empty value because the OpenAI *client object* is constructed eagerly; no
request is ever issued, since both generate methods are patched.

THE TWO REGIMES, AND WHY THEY DIFFER BY EXACTLY ONE FIELD
---------------------------------------------------------
``workflows/model_exploration.py::resolve_run_proposal_blocks`` is the
production authority for the proposer's task-owned science::

    task_composition is None   -> load_proposal_task_blocks()   (Regime A, TIDMAD)
    composed                   -> task_composition.proposal_blocks
                                  (``None`` when the task declares none)

A composed foreign task that declares no ``proposal_blocks:`` section therefore
reaches the proposer with ``proposal_blocks=None``. That single field IS the
composed/un-composed fork at this node, which is why the two captures below
differ in nothing else: any other difference would be a difference this
harness invented rather than one production makes.

REPRODUCE
---------
    cd <this worktree>
    OPENAI_API_KEY=sk-c12pp-dummy-not-a-real-key \
    PYTHONPATH=<this worktree> \
    <venv>/bin/python -m tests.helpers.c12pp_prompt_capture

Writes/overwrites the baselines under ``tests/fixtures/c12pp_prompt_baselines/``.
Re-running with no source change must leave the files byte-identical; that is
what makes them usable as a parity baseline.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Where the captured baselines live. A directory rather than one file so a
#: diff names the stage that moved.
BASELINE_DIR = REPO_ROOT / "tests" / "fixtures" / "c12pp_prompt_baselines"

#: Regime labels used as the baseline filename prefix.
REGIME_TIDMAD = "tidmad_regime_a"
REGIME_FOREIGN = "foreign_composed"


def _load_audit_helpers() -> Any:
    """Import ``scripts/render_proposer_prompts_for_audit.py`` as a module.

    Reused deliberately: its ``_build_proposal_input`` already drives the
    production protocol and is the repository's established way of producing a
    realistic proposer input. Re-authoring one here would risk diverging from
    the input shape production actually builds.
    """
    import importlib.util

    script = REPO_ROOT / "scripts" / "render_proposer_prompts_for_audit.py"
    spec = importlib.util.spec_from_file_location("_c12pp_audit_helpers", script)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_prompts(proposal_blocks: Any) -> list[tuple[str, str, str]]:
    """Capture every ``(label, system_prompt, user_prompt)`` for one regime.

    ``proposal_blocks`` is placed on the input exactly as
    ``resolve_run_proposal_blocks`` places it in ``run_workflow``.
    """
    helpers = _load_audit_helpers()
    from nodes.ml_model_proposal_agent import MLModelProposalAgent

    inp = helpers._build_proposal_input()
    inp = inp.model_copy(update={"proposal_blocks": proposal_blocks})

    captured: list[tuple[str, str, str]] = []

    def _fake_generate(system_prompt: str, user_prompt: str, **kwargs: Any) -> Any:
        label = kwargs.get("label", "")
        captured.append((label, system_prompt, user_prompt))
        return helpers._canned_response_for(label)

    def _fake_generate_text(system_prompt: str, user_prompt: str, **kwargs: Any) -> str:
        label = kwargs.get("label", "")
        captured.append((label, system_prompt, user_prompt))
        return ""

    with (
        patch("agent.llm_bridge.LLMBridge.generate", side_effect=_fake_generate),
        patch("agent.llm_bridge.LLMBridge.generate_text", side_effect=_fake_generate_text),
    ):
        agent = MLModelProposalAgent(provider="openai", model_id="gpt-4o-mini")
        agent.run(inp)

    return captured


def tidmad_regime_a_blocks() -> Any:
    """The Regime-A (un-composed) value — production's ``task_composition is None`` leg."""
    from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks

    return load_proposal_task_blocks()


def foreign_composed_blocks() -> None:
    """A composed task that declares no ``proposal_blocks:`` section.

    Returns ``None`` — production's composed leg for such a task, verbatim.
    """
    return None


def baseline_path(regime: str, index: int, label: str, kind: str) -> Path:
    """Deterministic baseline filename: regime, call order, stage label, prompt kind."""
    safe = "".join(c if c.isalnum() else "_" for c in label) or "unlabelled"
    return BASELINE_DIR / f"{regime}__{index:02d}_{safe}__{kind}.txt"


def write_baselines(regime: str, captures: list[tuple[str, str, str]]) -> list[Path]:
    """Write one file per captured prompt; return the paths written."""
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, (label, system_prompt, user_prompt) in enumerate(captures, start=1):
        for kind, text in (("system", system_prompt), ("user", user_prompt)):
            path = baseline_path(regime, index, label, kind)
            path.write_text(text, encoding="utf-8")
            written.append(path)
    return written


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY must be set to any non-empty value (client construction only; "
            "no request is issued because both generate methods are patched).",
            file=sys.stderr,
        )
        return 2

    total: list[Path] = []
    for regime, blocks in (
        (REGIME_TIDMAD, tidmad_regime_a_blocks()),
        (REGIME_FOREIGN, foreign_composed_blocks()),
    ):
        captures = capture_prompts(blocks)
        written = write_baselines(regime, captures)
        total.extend(written)
        print(f"{regime}: {len(captures)} prompt pairs -> {len(written)} files")

    print(f"Wrote {len(total)} baseline files under {BASELINE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
