"""Ancestor reference-source section shared by every model implementation call.

``ImplementorInput.reference_code`` carries the complete source of the earlier
models a proposal inherits from. The implementor's reasoning, code and repair
calls are separate, stateless LLM requests, so each one that must reproduce or
repair inherited code needs its own copy of that source (issue #1530). This
module is the single renderer of that section; the prompt builders embed its
output unchanged.

Size behaviour: the section is rendered once per call and is never repeated in
the repair error history, so a call grows by exactly the bytes the reasoning
call already carries. Sources are never truncated: a partial source would
reproduce the failure this section exists to prevent (a kept helper the code
call cannot see).

Rendering boundary: ``implementor.reference_code`` is a published prompt
boundary, so an experiment-owned prompt profile can supply a historical
rendering per ``stage``. The builders enter it only when a source is supplied;
an empty mapping renders nothing and never enters the boundary, leaving prompts
without ancestors byte-identical under native and historical profiles alike.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from agent.prompt_rendering import prompt_boundary

ReferenceStage = Literal["reasoning", "code", "repair"]

_REFERENCE_PREAMBLE = (
    "## Reference Code (from ancestor models)",
    "",
    "The proposal builds on the earlier models below. Their complete source is",
    "repeated in every implementation step because each step is a separate request.",
    "",
    "How to use it:",
    "",
    "1. Where the description keeps parts of an ancestor, carry those parts over",
    "   from this source and change only what the proposal changes. Otherwise use",
    "   it for architectural ideas (block structure, dilation schedules,",
    "   skip-connection topology).",
    "",
    "2. Names defined in a reference (helper classes and functions such as",
    "   `CausalConv1d`, `WaveNetBlock`, `DoubleConv` or `PositionalEncoding`) are",
    "   NOT available in your plugin's runtime: the plugin loader imports neither",
    "   `ml_models/models_sandbox.py` nor another plugin. Write whatever you carry",
    "   over into your own code sections using only the allowed primitives",
    "   (torch, torch.nn, torch.nn.functional). Referencing such a name without",
    "   writing its logic into your sections produces `NameError` at smoke-test",
    "   time.",
    "",
    "3. The `self.config = config` + `self.config.X` access pattern that some",
    "   reference samples use is FORBIDDEN in your plugin. The `config` object",
    "   is only in scope during `__init__`. Store every value you need as a",
    "   plain attribute on `self` (e.g. `self.channels = config.channels`)",
    "   inside `init_body`, then reference `self.channels` in `forward_body`.",
    "",
)


def reference_code_section(reference_code: Mapping[str, str], stage: ReferenceStage) -> str:
    """The section for one implementation call, or ``""`` when no source is supplied.

    Prompt builders call this, never the boundary directly, so an absent
    ancestor neither adds bytes nor requires a profile to declare the boundary.
    """
    if not reference_code:
        return ""
    return render_reference_code_section(dict(reference_code), stage)


@prompt_boundary("implementor.reference_code")
def render_reference_code_section(reference_code: dict[str, str], stage: ReferenceStage) -> str:
    """Render the ancestor-source section natively; identical for every ``stage``.

    ``stage`` names the calling request (reasoning, code or repair) so that a
    profile can render each one differently. Entries keep the mapping's order;
    each source is embedded whole in a fenced block under its ``model_type``
    heading. The result carries no leading or trailing blank line, so each
    prompt builder owns its own separators.
    """
    del stage  # The native rendering is stage-independent by design (#1530).
    lines = list(_REFERENCE_PREAMBLE)
    for model_type, source in reference_code.items():
        lines += [
            f"### {model_type} (ancestor source)",
            "```python",
            source,
            "```",
            "",
        ]
    return "\n".join(lines).rstrip("\n")
