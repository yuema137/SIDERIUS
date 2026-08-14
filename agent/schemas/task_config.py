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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.model_io_contract import AxisRole, ModelIOContract


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

    preset: str | None = Field(
        default=None,
        description="Optional Model-I/O preset label — authoring convenience "
        "ONLY. Read exactly once, by "
        "``agent.schemas.model_io_resolution.resolve_model_io_contract``, and "
        "never carried into the resolved contract, so no runtime consumer can "
        "branch on it (Step 03 §21).",
    )

    model_io: ModelIOContract | None = Field(
        default=None,
        description="The normalized Model-I/O contract (Step 03). When "
        "present it is THE authority: ``input_shape``, ``output_shape`` and "
        "``num_classes`` are DERIVED from it and must not be independently "
        "authored. When absent the prose fields are authored directly — the "
        "legacy Regime-A form, preserved unchanged.",
    )

    @model_validator(mode="after")
    def _derive_prose_from_the_normalized_contract(self) -> ForwardContract:
        """Make the normalized contract the single authority when present.

        Step 03 §21 forbids duplicate authority, and §5's Regime-A inventory
        requires *"a ``ForwardContract`` authored in the old prose form"* to
        keep working. Both hold here:

        * ``model_io is None`` — Regime A. Nothing is derived, nothing is
          checked, the prose is authored exactly as it has always been.
        * ``model_io`` present — the prose is DERIVED. An author who also
          writes a prose field gets a typed failure if it disagrees, never a
          silent overwrite and never two disagreeing authorities (§21).

        ``num_classes`` keeps its legacy ``0`` for *"not applicable"*: that
        is the compatibility PROJECTION direction, which §4b allows. What
        §4b forbids is promoting the ``0`` sentinel INTO the normalized
        contract, and ``ModelIOContract.class_cardinality`` uses ``None``.
        """
        if self.model_io is None:
            return self

        derived = {
            "input_shape": self.model_io.input.render(),
            "output_shape": self.model_io.output.render(),
            "num_classes": self.model_io.class_cardinality or 0,
        }
        empty = {"input_shape": "", "output_shape": "", "num_classes": 0}
        conflicts = [
            f"{field}: authored {getattr(self, field)!r} vs derived {value!r}"
            for field, value in derived.items()
            if getattr(self, field) != empty[field] and getattr(self, field) != value
        ]
        if conflicts:
            raise ValueError(
                "the forward contract declares `model_io` AND contradicting "
                "prose fields; `model_io` is the authority, so remove the "
                "prose or correct it — it is not silently overwritten. " + "; ".join(conflicts)
            )
        for field, value in derived.items():
            object.__setattr__(self, field, value)
        return self

    def renders_per_timestep_class_clause(self) -> bool:
        """Whether the rendered task-type descriptor carries the class clause.

        Audit row 7: the shipped renderer appends
        ``" (per-timestep {num_classes}-class)"`` whenever a class count
        exists — asserting a TEMPORAL axis from a CARDINALITY fact, which is
        only true by TIDMAD coincidence.

        With a normalized contract the claim is derived from the axis ROLES
        that actually license it: the output must carry both a class axis and
        a temporal axis. Under TIDMAD both are present, so the rendered bytes
        are unchanged. Without a normalized contract the legacy truthiness
        test is preserved verbatim (Regime A).
        """
        if self.model_io is None:
            return bool(self.num_classes)
        output = self.model_io.output
        return (
            output.axis_with_role(AxisRole.CLASS) is not None
            and output.axis_with_role(AxisRole.TEMPORAL) is not None
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
