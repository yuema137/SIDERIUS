"""Step 12 / PR-12a — deterministic capture of the tuner's RENDERED prompts.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C0 item 1 ("prompt bytes … for a pinned
pseudo run") and C7 ("legacy prompt bytes are byte-identical").

WHY A CAPTURING *STUB* AND NOT THE RECORDING DOUBLE
---------------------------------------------------
``RecordingLLMBridge`` is handed a prompt; it never renders one. A baseline
built from it would pin the test's own strings. ``StubLLMBridge`` is a real
:class:`~agent.llm_bridge.LLMBridge` subclass that overrides only the HTTP
seam (``_chat_json`` / ``generate_text``), so ``plan()`` and ``reflect()``
execute the PRODUCTION render paths and the bytes captured here are the bytes
a run would have sent. That is the difference between pinning the assembly and
pinning a fixture.

WHAT IS NORMALIZED, AND WHAT DELIBERATELY IS NOT
------------------------------------------------
Exactly one normalization: wall-clock timestamps. Two identical fresh
processes were diffed during C0 and the ONLY differing bytes were three
``"timestamp": "YYYY-MM-DD HH:MM:SS"`` fields inside the rendered research
memory. Nothing else is touched — not the workspace path (it does not appear;
verified), not model names, not scores, not ordering, not whitespace. A
fixture that normalized more would pass vacuously, which is the failure mode
C0 §6 names.

MACHINE-LOCAL STATE IS PINNED, NOT NORMALIZED
---------------------------------------------
The planner renders an AVAILABLE CUSTOM LOSSES block from the capability
registry, whose production default is ``agent_generated/_capability_index.json``
— gitignored, mutable, machine-local. Capturing it would make a committed sha
pass locally and fail on a fresh CI clone. So the capture PINS the registry to
an empty index instead of scrubbing the block: the block still renders through
the production path, it just renders the empty-registry content on every
machine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The Step-00 pre-flight capture every pseudo tuner run replays.
PREFLIGHT_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "unit"
    / "agent"
    / "tune_ml_hyperparam_agent"
    / "fixtures"
    / "step00_preflight_results.json"
)

#: The one normalization. See the module docstring for why it is the only one.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}")
_TIMESTAMP_PLACEHOLDER = "<TS>"


def normalize(text: str) -> str:
    """Replace wall-clock timestamps; change nothing else."""
    return _TIMESTAMP.sub(_TIMESTAMP_PLACEHOLDER, text)


def capturing_bridge_class() -> type:
    """A ``StubLLMBridge`` subclass that records every rendered prompt.

    Built lazily inside a function so importing this helper does not drag the
    LLM bridge (and its provider clients) into every test module's import
    graph.
    """
    from agent.llm_bridge import LLMBridge, StubLLMBridge

    class CapturingStubBridge(StubLLMBridge):
        """Records ``(method, label, system, user)`` then delegates to the stub."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.captures: list[dict[str, Any]] = []

        def _chat_json(
            self,
            client: Any,
            model_name: str,
            system_prompt: str,
            user_prompt: str,
            *,
            label: str = LLMBridge._DEFAULT_LABEL,
            provider: str | None = None,
            components: dict[str, int] | None = None,
        ) -> dict:
            self.captures.append(
                {
                    "method": "_chat_json",
                    "label": label,
                    "system": normalize(system_prompt),
                    "user": normalize(user_prompt),
                    "kwargs": {},
                }
            )
            return super()._chat_json(
                client,
                model_name,
                system_prompt,
                user_prompt,
                label=label,
                provider=provider,
                components=components,
            )

        def generate_text(
            self,
            system_prompt: str,
            user_prompt: str,
            *,
            label: str = LLMBridge._DEFAULT_LABEL,
            components: dict[str, int] | None = None,
        ) -> str:
            self.captures.append(
                {
                    "method": "generate_text",
                    "label": label,
                    "system": normalize(system_prompt),
                    "user": normalize(user_prompt),
                    "kwargs": {},
                }
            )
            return super().generate_text(
                system_prompt, user_prompt, label=label, components=components
            )

    return CapturingStubBridge


def capture_tuner_prompts(
    tmp_path,
    monkeypatch,
    *,
    input_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one bounded pseudo tuner iteration; return the parity manifest.

    The manifest is produced by ``tests.helpers.step10_p1_parity_manifest``
    — the SAME reducer the Step-10 P1 evidence used, deliberately reused
    rather than re-implemented, so a prompt-parity claim in this PR means
    exactly what it meant there (call count, order, labels, methods, system
    bytes+sha, user bytes+sha, structured-kwargs sha).

    The caller wraps this in ``bind_run_task_composition`` to capture the
    COMPOSED branch; calling it bare captures the LEGACY branch.
    """
    from execute_tools.health_checks.config import clear_health_gates_config_cache
    from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
    from tests.helpers.step10_p1_parity_manifest import build_manifest

    # A prompt-BYTE baseline must not depend on what ran earlier in the
    # process. `load_health_gates_config` caches its result for `path=None`
    # PROCESS-WIDE, and the reflector prompt renders per-check collapse advice
    # from that roster — so any earlier test that resolved the default path
    # under a bound composition leaves a cached roster behind and the "legacy"
    # capture renders someone else's. Observed while landing C2: the reflector
    # system prompt dropped 9,677 -> 5,581 bytes purely from test ORDER, with
    # no production change involved. Clearing the cache makes the capture
    # state-independent instead of order-lucky.
    clear_health_gates_config_cache()

    empty_index = tmp_path / "pinned_capability_index.json"
    # The index format is a top-level JSON ARRAY; a dict is rejected as
    # corruption by `CapabilityRegistry`.
    empty_index.write_text("[]", encoding="utf-8")

    bridge = capturing_bridge_class()()
    preflight = json.loads(PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
    run_bounded_pseudo_iteration(
        tmp_path,
        monkeypatch,
        preflight_results=preflight,
        input_overrides=input_overrides,
        bridge=bridge,
        capability_index_path=str(empty_index),
    )
    return build_manifest({"terminated_with": None, "captures": bridge.captures})


def legacy_rendered_template(which: str) -> str:
    """The planner/reflector template with its LEGACY task-science substituted.

    Step 12 / PR-12a C7 moved seven hardcoded blocks out of the templates and
    into the render authority, as named substitution tokens. Tests that used
    to assert a literal was present "in PLANNER_PROMPT" are asserting a
    property of what an UN-COMPOSED run renders, not of where the bytes are
    stored — so they ask this instead, and keep meaning what they meant.

    Only the C7 tokens are substituted. Every other placeholder is left alone,
    because these callers are asserting static content, not a full assembly.
    """
    from agent.prompt_templates.tuner import rendering as r
    from agent.prompts import PLANNER_PROMPT, REFLECTOR_PROMPT

    template = {"planner": PLANNER_PROMPT, "reflector": REFLECTOR_PROMPT}[which]
    return (
        template.replace("{AVAILABLE_MODELS_BLOCK}", r.LEGACY_AVAILABLE_MODELS_BLOCK)
        .replace("{PER_FILE_TABLE_PROTOCOL}", r.LEGACY_PER_FILE_TABLE_PROTOCOL)
        .replace("{TARGET_STRATEGY_IMPACT_NOTE}", r.LEGACY_TARGET_STRATEGY_IMPACT_NOTE)
        .replace("{SAMPLING_IMPACT_TRADEOFF}", r.LEGACY_SAMPLING_IMPACT_TRADEOFF)
        .replace("{PER_FILE_COMPARISON_BLOCK}", r.LEGACY_PER_FILE_COMPARISON_BLOCK)
        .replace("{SCORE_FIELD_NOUN}", "metric")
        .replace("{SCORE_DISPLAY_NOUN_UPPER}", "DENOISING SCORE")
        .replace("{SCORE_DISPLAY_NOUN}", "Denoising Score")
    )
