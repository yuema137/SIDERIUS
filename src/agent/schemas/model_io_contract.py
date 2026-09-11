# agent/schemas/model_io_contract.py
"""The normalized Model-I/O contract — Step 03's semantic authority.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§2 (final effect), §3 (ownership), §4a + **§4a.1 AMENDMENT A-1** (dtype
admissibility), §4c (single input / single output), §4e (no relation
DSL), §4d (capability matrix), §21 (stop conditions).

**What this module is.** One structured input tensor and one structured
output tensor, with arbitrary rank, ordered axes, semantic axis roles,
dimension semantics and an input dtype **admissibility requirement**.
It replaces the four prose restatements of ``[B, 256, T]`` with one
declaration that the prose is DERIVED from.

**What it is deliberately NOT.**

- **Not multi-tensor.** Exactly one input and one output (§4c).
  ``inputs: [...]`` / ``outputs: [...]`` containers are the consumer-less
  seam roadmap §0 rule 8 forbids, and are a §21 stop condition.
- **Not a relation DSL** (§4e). Input↔output alignment is expressed by
  *sharing a symbolic dimension name* — ``T`` on both sides IS the
  alignment. There is no ``relationships:`` surface.
- **Not a concrete dtype per boundary.** See ``DtypeAdmissibility``.
- **Not a task config.** Dataset topology, encoding and cardinality
  belong to the Step-02 Dataset Profile; this contract *derives from and
  cross-validates against* it, never restates it (§4b).

**Every field here has a live production consumer.** A field without one
is a §21 stop condition, which is why there is no ``dtype`` on axes, no
layout/memory-format field, no device field and no tensor names: nothing
in this repository reads them today.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ml_models.models_format_sandbox import (
    DtypeAdmissibility,
    OutputSemantic,
    legacy_output_type_for,
)

# Re-exported so a reader of the contract finds every part of it here.
# `DtypeAdmissibility` lives in `ml_models` for the same layering reason as
# `OutputSemantic`: `agent` imports `ml_models` and not the reverse, and the
# builtin catalogue in `ml_models/models_sandbox.py` must be able to declare
# a model's admissibility.
__all__ = [
    "AxisRole",
    "Dimension",
    "DtypeAdmissibility",
    "ModelIOContract",
    "TensorAxis",
    "TensorContract",
]


class AxisRole(StrEnum):
    """The semantic role an axis plays, where a consumer actually reads it.

    Roles are what replace rank-specific branching (§4d): a consumer asks
    *"which axis is the class alphabet"*, never *"is this rank 3"*.
    Branching on rank, modality or preset label is a §21 stop condition.

    The vocabulary is **additive**. Exactly three roles exist because
    exactly three are read by production today:

    ==========  ====================================================
    role        production consumer
    ==========  ====================================================
    ``batch``   the leading axis in every rendered shape
    ``temporal``the renderer's per-timestep phrasing
                (``workflows/task_config.py:209``, audit row 7)
    ``class``   cardinality — the alphabet axis whose extent is the
                class count, cross-validated against the Dataset
                Profile's ``ValueEncoding.num_classes`` (§4b)
    ==========  ====================================================

    An axis with no semantic role leaves ``role`` unset. That is the
    honest representation for an axis nothing branches on, and it is what
    keeps arbitrary rank expressible without inventing roles that no
    consumer reads.
    """

    BATCH = "batch"
    TEMPORAL = "temporal"
    CLASS = "class"


class Dimension(BaseModel):
    """One axis extent: fixed, symbolic, or dynamic — exactly one.

    ``symbolic`` is the alignment mechanism (§4e). Two axes carrying the
    same symbol are the same extent; that is how *"the output is as long
    as the input"* is expressed without a relationship surface.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fixed: int | None = Field(
        default=None,
        gt=0,
        description="A concrete extent, e.g. 256 for a class alphabet. Renders as the integer.",
    )
    symbolic: str | None = Field(
        default=None,
        min_length=1,
        description="A named extent, e.g. 'B' or 'T'. The SAME name on an "
        "input and an output axis declares that they are equal — this is "
        "how alignment is expressed, instead of a relationship DSL (§4e). "
        "Renders as the name.",
    )
    dynamic: bool = Field(
        default=False,
        description="An unconstrained extent. Renders as '...'.",
    )

    @model_validator(mode="after")
    def _exactly_one_form(self) -> Dimension:
        """Reject a dimension that is neither, or more than one, of the three.

        Named in §16 as a Step-03 analogue of the ordering standard's
        "invalid file_order" case: a dimension that is neither fixed,
        symbolic nor dynamic is a machine-checkable invalid state and must
        fail closed rather than render as something plausible.
        """
        chosen = [
            name
            for name, present in (
                ("fixed", self.fixed is not None),
                ("symbolic", self.symbolic is not None),
                ("dynamic", self.dynamic),
            )
            if present
        ]
        if len(chosen) != 1:
            raise ValueError(
                "a Dimension must be exactly one of fixed / symbolic / dynamic, "
                f"got {chosen or 'none'}"
            )
        return self

    def render(self) -> str:
        """The token this dimension contributes to a rendered shape."""
        if self.fixed is not None:
            return str(self.fixed)
        if self.symbolic is not None:
            return self.symbolic
        return "..."


class TensorAxis(BaseModel):
    """One ordered axis: an optional semantic role plus an extent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension: Dimension = Field(description="The axis extent.")
    role: AxisRole | None = Field(
        default=None,
        description="Semantic role, where a consumer reads one. Unset for "
        "an axis nothing branches on — which is what keeps arbitrary rank "
        "expressible without inventing consumer-less roles.",
    )


class TensorContract(BaseModel):
    """One structured tensor: ordered axes plus a dtype admissibility."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    axes: tuple[TensorAxis, ...] = Field(
        min_length=1,
        description="Ordered axes. Order IS the shape order; rank is len(axes).",
    )
    dtype: DtypeAdmissibility = Field(
        description="Which concrete dtypes this tensor boundary accepts (A-1).",
    )

    @model_validator(mode="after")
    def _roles_are_unique(self) -> TensorContract:
        """A role answers 'which axis is the class alphabet'. Two axes
        claiming the same role make that question ambiguous, so a consumer
        would silently take the first — the failure §16 names as the
        'duplicate axis' analogue."""
        roles = [a.role for a in self.axes if a.role is not None]
        if len(set(roles)) != len(roles):
            raise ValueError(f"duplicate axis role in {[r.value for r in roles]}")
        return self

    @property
    def rank(self) -> int:
        return len(self.axes)

    def axis_with_role(self, role: AxisRole) -> TensorAxis | None:
        """The axis carrying ``role``, or ``None``. The role-based lookup
        that replaces positional/rank assumptions."""
        for axis in self.axes:
            if axis.role is role:
                return axis
        return None

    def render_shape(self) -> str:
        """``[B, 256, T]`` — the shape token of the LLM-facing prose.

        Byte-exact by construction: the separator, brackets and spacing
        are the ones already shipped in ``configs/task_config.yaml``, and
        A1's goldens are what prove it.
        """
        return "[" + ", ".join(a.dimension.render() for a in self.axes) + "]"

    def render(self) -> str:
        """``[B, 256, T] float32`` — shape plus the canonical dtype."""
        return f"{self.render_shape()} {self.dtype.canonical}"


class ModelIOContract(BaseModel):
    """The normalized Model-I/O contract: ONE input, ONE output (§4c).

    Multi-tensor containers are not merely absent — they are forbidden
    until a real production consumer exists (§4c, §21). The multiplicity
    bound is the whole point: *"one tensor"* is a multiplicity claim, not
    a shape claim, and rank/axes remain free.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: TensorContract = Field(description="The single input tensor.")
    output: TensorContract = Field(description="The single output tensor.")

    @model_validator(mode="after")
    def _shared_symbols_are_consistent(self) -> ModelIOContract:
        """Cross-validate the alignment that shared symbols express.

        A symbol used on both sides must mean one extent. Because a symbol
        carries no extent of its own, the check that is machine-decidable
        today is that a name is not simultaneously used as a symbol on one
        side and pinned to conflicting fixed extents on the other. Anything
        stronger would require the relationship DSL §4e forbids.
        """
        for axis in self.output.axes:
            symbol = axis.dimension.symbolic
            if symbol is None:
                continue
            matches = [a for a in self.input.axes if a.dimension.symbolic == symbol]
            if not matches:
                continue
            if any(
                a.role is not None and axis.role is not None and a.role is not axis.role
                for a in matches
            ):
                raise ValueError(
                    f"symbolic dimension {symbol!r} is shared between input and "
                    "output but the axes carry different semantic roles; a shared "
                    "symbol declares the SAME extent, so the roles must agree"
                )
        return self

    @property
    def output_semantic(self) -> OutputSemantic:
        """The canonical output semantic — **§8b's single authority**.

        DERIVED from the output tensor's axis roles, never declared, so
        normalized tensor semantics and output semantics cannot disagree:
        an output carrying a class-alphabet axis is categorical, and one
        that does not is continuous.

        The enum itself lives in ``ml_models.models_format_sandbox`` beside
        the loss frozensets it keys, because §8a re-keys that existing
        authority rather than creating a second one, and because ``agent``
        imports ``ml_models`` and not the reverse.

        Note there is no ``hybrid`` here and there never will be: §8c keeps
        ``hybrid`` a legacy builtin adapter value, and inventing tensor
        semantics for it is forbidden.
        """
        if self.output.axis_with_role(AxisRole.CLASS) is not None:
            return OutputSemantic.CATEGORICAL
        return OutputSemantic.CONTINUOUS

    @property
    def output_has_temporal_axis(self) -> bool:
        """Whether the output carries a ``temporal`` axis — **D2**.

        The one geometry fact the loss-availability authority needs: a loss
        that consumes PER-TIMESTEP class logits (``focal`` / ``focal_cw``)
        cannot run against an output that has no timestep axis. Expressed
        here, once, so the run-scoped accessor
        (``workflows.task_config.run_bound_output_has_temporal_axis``) and
        the resource pre-flight — which holds the contract directly — cannot
        answer the same question two ways.

        A ROLE question, never a rank question (§4d): asking *"which axis is
        the temporal one"* is exactly what the role vocabulary exists for,
        and branching on rank instead would be a §21 stop condition.
        """
        return self.output.axis_with_role(AxisRole.TEMPORAL) is not None

    @property
    def legacy_output_type(self) -> str:
        """The legacy ``output_type`` word, as a **derived projection** (§8b).

        A compatibility view for consumers that still speak the old
        alphabet. One-way: nothing writes back through it, and it is never
        the answer to *"what output semantics does this model have"* —
        :attr:`output_semantic` is.
        """
        return legacy_output_type_for(self.output_semantic)

    @property
    def class_cardinality(self) -> int | None:
        """The output class count, or ``None`` when not meaningful.

        ``None`` is the explicit *"cardinality is not applicable to this
        output semantic"* that §4b requires — the legacy ``num_classes = 0``
        magic sentinel is deliberately NOT promoted into this contract.

        Derived from the ``class``-role axis rather than declared, so there
        is no second configurable class count (§4b).
        """
        axis = self.output.axis_with_role(AxisRole.CLASS)
        if axis is None:
            return None
        return axis.dimension.fixed


def load_model_io_contract(path: str) -> ModelIOContract:
    """Load a resolved Model-I/O contract from JSON. **FAILS CLOSED.**

    The subprocess side of the parent→child transport, mirroring
    ``execute_tools.dataset_config.load_dataset_profile`` exactly — the
    established config-file + argv-flag mechanism, not a new one (§16 routes
    IPC to Step 11).

    The distinction that matters is the same one:

    * a path that is **missing, unreadable, not JSON or schema-invalid**
      raises, with a diagnostic naming the path;
    * it **never** falls back to the shipped task contract.

    *"the flag is present but the file is broken"* must fail loudly, because
    a silent fallback would feed a bound task TIDMAD's dtype and produce
    plausible, wrong tensors. *"an old caller has never heard of the flag"*
    is a different case entirely — that one keeps Regime A, and the caller
    handles it by not calling this function at all.
    """
    import json

    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError as exc:
        raise ValueError(f"model I/O contract unreadable at {path!r}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"model I/O contract at {path!r} is not valid JSON: {exc}") from exc
    try:
        return ModelIOContract(**payload)
    except Exception as exc:
        raise ValueError(f"model I/O contract at {path!r} is schema-invalid: {exc}") from exc
