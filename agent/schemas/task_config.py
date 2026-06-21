# agent/schemas/task_config.py
"""
Typed schemas for the global task config (``configs/task_config.yaml``).

The task config is the single source of truth for two pieces of operator-facing
information that used to live as hardcoded strings inside Python and Markdown
prompts across the codebase:

  * ``task_description`` — plain-English description of the research task,
    injected into the ``{TASK_DESCRIPTION}`` placeholder in agent system
    prompts. Carried as a plain ``str`` (no schema wrapper needed).
  * ``forward_contract`` — typed shape/dtype contract that model plugins must
    satisfy. Carried as a :class:`ForwardContract` Pydantic instance so that
    a typo in a YAML key name produces a ``ValidationError`` rather than a
    silent empty rendering downstream.

The loader/renderer module ``workflows/task_config.py`` is the canonical
consumer — it reads ``configs/task_config.yaml``, instantiates
``ForwardContract(**yaml_dict["forward_contract"])``, and exposes
``render_forward_contract(fc)`` which produces the rendered multi-line block
substituted into system prompts.

See ``docs/design/enable_global_task_config.md`` for the full design.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ForwardContract(BaseModel):
    """Typed forward-pass contract for the model plugin interface.

    Every field defaults to an empty string / zero so a bare
    ``ForwardContract()`` is constructible for tests. Production callers
    always populate via ``ForwardContract(**yaml_dict)`` after
    ``load_task_config()``, where a missing or misnamed key surfaces as a
    ``ValidationError`` — never as silent empty rendering.

    Fields mirror the keys of the ``forward_contract:`` block in
    ``configs/task_config.yaml``. When adding a new field here, also add it
    to the YAML file and to the rendered string format in
    ``workflows/task_config.render_forward_contract``.
    """

    # Forbid extra keys so a YAML typo (e.g. ``input_shapes`` plural)
    # raises rather than silently dropping the value.
    model_config = ConfigDict(extra="forbid")

    input_shape: str = Field(
        default="",
        description="Tensor shape + dtype of the model input, formatted "
        'for human reading (e.g. ``"[B, T] int64"``).',
    )
    input_description: str = Field(
        default="",
        description="One-line description of what the input represents "
        '(e.g. ``"raw signal, integer class indices 0-255"``).',
    )
    output_shape: str = Field(
        default="",
        description='Tensor shape + dtype of the model output (e.g. ``"[B, 256, T] float32"``).',
    )
    output_description: str = Field(
        default="",
        description="One-line description of what the output represents "
        '(e.g. ``"per-timestep logits over 256 denoising classes"``).',
    )
    num_classes: int = Field(
        default=0,
        ge=0,
        description="Number of output classes for classifier tasks. Set "
        "to 0 for regressor or hybrid tasks; the implementor / proposer "
        "prompt reads this to anchor any embedding-table size.",
    )
    embedding_note: str = Field(
        default="",
        description="Optional guidance on how to ingest the input — e.g. "
        "an ``nn.Embedding`` for integer class indices. Rendered verbatim "
        "into the implementor prompt.",
    )
    output_head_note: str = Field(
        default="",
        description="Optional guidance on the output head — e.g. final "
        "``Conv1d(channels, num_classes, 1)``. Rendered verbatim.",
    )
    task_type: str = Field(
        default="",
        description="High-level task category for prompt framing. "
        'Conventional values: ``"classification"``, ``"regression"``, '
        '``"hybrid"``. Free-form — consumers should treat unknown values '
        "as opaque labels.",
    )
    task_note: str = Field(
        default="",
        description="Optional constraint or framing note appended to the "
        'rendered contract (e.g. ``"Offline denoising — output at '
        'position t may depend on all positions."``).',
    )

    def is_empty(self) -> bool:
        """Return True when every field is at its zero/empty default.

        Used by :func:`workflows.task_config.render_forward_contract` to
        short-circuit to an empty string on default-constructed instances —
        the only path that reaches the renderer with an empty contract is a
        caller that bypassed ``load_task_config`` and built one manually for
        tests.
        """
        return (
            not self.input_shape
            and not self.input_description
            and not self.output_shape
            and not self.output_description
            and self.num_classes == 0
            and not self.embedding_note
            and not self.output_head_note
            and not self.task_type
            and not self.task_note
        )
