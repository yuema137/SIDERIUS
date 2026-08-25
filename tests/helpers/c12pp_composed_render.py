"""C12-P-P / W1 — render the proposing prompt under a REAL composed binding.

WHY THIS EXISTS SEPARATELY FROM ``c12pp_prompt_capture``
--------------------------------------------------------
The original capture built a ``ProposalInput`` by hand and varied
``proposal_blocks``. That was enough to show the contamination, but it left
``forward_contract`` at its default-EMPTY value, so ``{forward_contract}``
rendered ``""`` — and P1-B's entire safety argument rests on that block being
present. A test built on those fixtures would certify a prompt production never
emits.

It also could not resolve a pack's ``task_config`` directly: doing so raises
``DatasetContradictionError``, because a pack's class cardinality is checked
against the AMBIENT dataset profile, which is TIDMAD's until something binds
otherwise.

Both problems have the same fix, and it is the production one: **bind the real
composition**, then read the task config through the ordinary loader.

    compose_run_task_bindings(configs/task_composition/<task>.yaml)
      -> bind_run_task_composition(comp, physical_data_root=<empty tmp dir>)
         -> load_task_config()            # returns the FOREIGN config
            -> ForwardContract(**cfg["forward_contract"])

Measured cost: under one second per task, with an EMPTY data root. No real
data, no training, no GPU, no network. That is what makes the aggregate
invariant affordable as an ordinary unit test.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: The shipped manifests. Landed PR-12d ships pets/davis beside tidmad; neither
#: foreign manifest declares a ``proposal_blocks:`` section, so
#: ``proposal_blocks`` is ``None`` — the production value, not a fixture guess.
MANIFESTS = {
    "tidmad": REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml",
    "pets": REPO_ROOT / "configs" / "task_composition" / "pets.yaml",
    "davis": REPO_ROOT / "configs" / "task_composition" / "davis.yaml",
}


@contextmanager
def composed_task(task: str, data_root: str):
    """Bind ``task``'s real composition for the enclosing scope.

    ``data_root`` may be an EMPTY directory: the binding requires a declared
    physical root (Step 11 R-11-8, so no child silently falls back to
    ``TIDMAD_DATA_DIR``) but nothing in prompt assembly reads a byte from it.
    """
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    manifest = MANIFESTS[task]
    composition = compose_run_task_bindings(str(manifest))
    with bind_run_task_composition(composition, physical_data_root=data_root) as bound:
        yield bound


def build_composed_proposal_input(composition: Any) -> Any:
    """A ``ProposalInput`` carrying the BOUND task's description and contract.

    Mirrors ``workflows/model_exploration.py``: the workflow sets
    ``task_description``, ``forward_contract`` and ``proposal_blocks`` on the
    input it hands the proposer. ``composition`` is the object
    :func:`composed_task` yields — the same value ``run_workflow`` passes to
    ``resolve_run_proposal_blocks``. Must be called inside the binding, because
    ``load_task_config()`` reads it.
    """
    import importlib.util

    from agent.schemas.task_config import ForwardContract
    from workflows.model_exploration import resolve_run_proposal_blocks
    from workflows.task_config import get_task_description, load_task_config

    script = REPO_ROOT / "scripts" / "render_proposer_prompts_for_audit.py"
    spec = importlib.util.spec_from_file_location("_c12pp_audit_helpers", script)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"could not load {script}")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)

    cfg = load_task_config()
    inp = helpers._build_proposal_input()
    return inp.model_copy(
        update={
            "task_description": get_task_description(cfg),
            "forward_contract": ForwardContract(**cfg["forward_contract"]),
            "proposal_blocks": resolve_run_proposal_blocks(composition),
        }
    )


def render_composed_prompts(task: str, data_root: str) -> list[tuple[str, str, str]]:
    """Every ``(label, system_prompt, user_prompt)`` for one composed task.

    Assembled by the production ``_run_pipeline``; the bridge is patched only at
    its two generate methods, so no request is issued.
    """
    from nodes.ml_model_proposal_agent import MLModelProposalAgent

    os.environ.setdefault("OPENAI_API_KEY", "sk-c12pp-dummy-not-a-real-key")

    with composed_task(task, data_root) as composition:
        inp = build_composed_proposal_input(composition)

        import importlib.util

        script = REPO_ROOT / "scripts" / "render_proposer_prompts_for_audit.py"
        spec = importlib.util.spec_from_file_location("_c12pp_audit_helpers2", script)
        assert spec is not None and spec.loader is not None
        helpers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helpers)

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
            MLModelProposalAgent(provider="openai", model_id="gpt-4o-mini").run(inp)

    return captured


def proposing_system_prompt(task: str, data_root: str) -> str:
    """The proposing-stage SYSTEM prompt — where every contamination marker lives."""
    for label, system_prompt, _user in render_composed_prompts(task, data_root):
        if "proposing" in label:
            return system_prompt
    raise AssertionError(
        f"no proposing stage was rendered for {task!r}; the pipeline produced "
        "a different stage set, which is itself a change worth failing on"
    )
