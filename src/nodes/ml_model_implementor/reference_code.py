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

Inherited components (#1540): the same owner renders the proposal's
``inherited_components`` (which component, from which source, and why) next to
the ancestor source, through the separate boundary
``implementor.inherited_components``. It is entered only when the proposal
inherits something. The validator's regex patterns are deliberately not
rendered: showing the verifier's pattern would invite code written to match the
pattern rather than to carry the component over.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from agent.prompt_rendering import prompt_boundary
from agent.schemas.proposal import InheritedComponent

ReferenceStage = Literal["reasoning", "code", "repair"]

_REFERENCE_PREAMBLE = (
    "## Reference Code (from ancestor models)",
    "",
    "The proposal builds on the earlier models below. Their complete source is",
    "repeated in every implementation step because each step is a separate request.",
    "",
    "How to use it:",
    "",
    "1. Where the description keeps parts of an ancestor, carry their computation",
    "   over from this source (inlined as rule 2 requires) and change only what the",
    "   proposal changes. Otherwise use it for architectural ideas (block",
    "   structure, dilation schedules, skip-connection topology).",
    "",
    "2. Helper classes and functions defined in a reference (e.g. `CausalConv1d`,",
    "   `WaveNetBlock`, `DoubleConv`, `PositionalEncoding`, `Down`, `Up`) are NOT",
    "   available in your plugin's runtime: the plugin loader imports neither",
    "   `ml_models/models_sandbox.py` nor another plugin, and the template has no",
    "   slot for class definitions. Do NOT define or reference these helper",
    "   classes. Inline their logic in `init_body` and `forward_body` with",
    "   nn.ModuleList, nn.Sequential and the allowed primitives (torch, torch.nn,",
    "   torch.nn.functional). Referencing a helper name produces `NameError` at",
    "   smoke-test time.",
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
    This is the single ordering owner: entries are sorted by ``model_type``
    before the boundary, so native and profile renderings of several ancestors
    are reproducible across processes whatever the mapping's insertion order.
    """
    if not reference_code:
        return ""
    return render_reference_code_section(dict(sorted(reference_code.items())), stage)


@prompt_boundary("implementor.reference_code")
def render_reference_code_section(reference_code: dict[str, str], stage: ReferenceStage) -> str:
    """Render the ancestor-source section natively; identical for every ``stage``.

    ``stage`` names the calling request (reasoning, code or repair): the native
    text does not depend on it, but a profile may render each one differently.
    Entries render in the order received (``reference_code_section`` sorts
    them); each source is embedded whole in a fenced block under its
    ``model_type`` heading. The result carries no leading or trailing blank
    line, so each prompt builder owns its own separators.
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


_SOURCE_KIND = {
    "experiment": "experiment",
    "external_agent": "external agent",
    "human": "human directive",
}


def inherited_components_section(
    components: Sequence[InheritedComponent],
    supplied_sources: Iterable[str],
    stage: ReferenceStage,
) -> str:
    """The inherited-components section for one call, or ``""`` without any (#1540).

    ``supplied_sources`` are the ``model_type`` keys whose ancestor source the
    call also carries (``reference_code``), so each experiment component says
    whether its source is below. Prompt builders call this, never the boundary
    directly, so a proposal that inherits nothing neither adds bytes nor
    requires a profile to declare the boundary.
    """
    if not components:
        return ""
    return render_inherited_components_section(
        list(components), sorted(set(supplied_sources)), stage
    )


@prompt_boundary("implementor.inherited_components")
def render_inherited_components_section(
    components: list[InheritedComponent], supplied_sources: list[str], stage: ReferenceStage
) -> str:
    """Render the claimed components in proposal order; identical for every ``stage``.

    No leading or trailing blank line; each prompt builder owns its separators.
    """
    del stage  # The native rendering is stage-independent by design (#1540).
    lines = [
        "## Inherited Components (declared by the proposal)",
        "",
        "The proposal states that the new model carries over the components below.",
        "Keep each one in your implementation (written into your own code sections",
        "under the plugin rules) and change only what the proposal changes.",
        "",
    ]
    for item in components:
        origin = f"from {_SOURCE_KIND[item.source_type]} `{item.source_id}`"
        notes = []
        if item.from_run:
            notes.append(f"run `{item.from_run}`")
        if item.source_type == "experiment":
            notes.append(
                "ancestor source below"
                if item.source_id in supplied_sources
                else "ancestor source not available"
            )
        detail = f" ({'; '.join(notes)})" if notes else ""
        lines.append(f"- `{item.component}`, {origin}{detail}: {item.contribution_evidence}")
    return "\n".join(lines)
