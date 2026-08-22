"""The provisional Deliverable Contract — what one attempt PERSISTS.

Step 05c, design ``docs/design/generic_framework_upgrade/
step_05c_tuner_execution_contracts.md`` §3, §3.1, §3.2a.

**The concept.** SIDERIUS reads an input dataset (Step 02's
:class:`~execute_tools.dataset_config.DatasetProfile`), runs a model whose
tensor semantics are declared by Step 03's ``ModelIOContract``, and then
*writes something*. That third thing — the artifact an attempt leaves on
disk, its name, and how its samples are stored — had **no owner**: the same
TIDMAD template was inlined at seven production sites, and the
channel-group names and the ``int8`` / ``+128`` storage representation were
re-stated independently of the profile that already declares them.

That TIDMAD happens to use int8 HDF5 for both its input and its deliverable
is a coincidence of one task, not evidence the two contracts are one. The
authority chain this module completes::

    input dataset decoding      -> DatasetProfile.encoding   (Step 02)
    model-output decoding       -> ModelIOContract           (Step 03)
    persisted deliverable       -> DeliverableSpec           (here)

**Deliberately PROVISIONAL, and deliberately small.** Ownership of the
Deliverable Contract is OPEN: 05c holds only the *producer* side, and Step 06
— which will hold the scorer/scoreability evidence 05c cannot see — is the
next mandatory ownership review. So this module owns exactly the facts the
migrated production sites consume, and no more:

===============================  =========================================
OWNED here                       NOT owned — left exactly where it is
===============================  =========================================
deliverable name resolution      the 5 instrument attrs per channel
cleanup / name matching          ``sampling_frequency`` metadata
channel-group identity           chunking and the ``N`` split mechanics
persisted storage dtype          the ``indexed`` suffix rule
persisted value offset           invalid-filename policy
                                 completeness and scoreability (Step 06)
                                 metric identity (Step 06)
                                 cleanup POLICY (Step 11)
===============================  =========================================

**Runtime-only.** This is a typed value constructed at run scope. It is NOT
user-authored, NOT persisted as its own artifact, and NOT serialized: under
the frozen §3.2a mechanism (**Option A, deterministic reconstruction**) the
spec never crosses a process boundary. Parent and child each call
:func:`derive_tidmad_deliverable_spec` over authorities that already cross —
``--dataset_profile_json`` — so they reconstruct an *equal* value from one
shared derivation rather than agreeing by two matching literals. There is no
new YAML, no new config block, no new CLI argument, and legacy runs need no
migration: a stored run's existing values construct the identical spec.

**Why two components in one spec.** The naming facts are frozen TIDMAD
*compatibility literals* keyed on identifiers, and are genuinely not derivable
from any declaration; the storage facts ARE derived, from
``DatasetProfile.channels`` and ``.encoding``. Splitting them lets the
parent-side consumers (path builder, cleanup, launcher) resolve a name
without holding a profile they have no other use for, while keeping ONE type,
ONE set of literals and ONE derivation. This mirrors ``DatasetProfile``'s own
"three declarations, one object" composition — it is not two authorities.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from execute_tools.dataset_config import DatasetProfile, resolve_dataset_profile

# The TIDMAD deliverable stem, extracted VERBATIM from the seven production
# sites it was inlined at. It is a frozen compatibility literal — files with
# this name already exist on disk and are read by the scorer, by the health
# peeks and by historical replay tooling — so it is declared once, here, and
# never re-stated.
TIDMAD_DELIVERABLE_PREFIX = "abra_validation_denoised"
TIDMAD_DELIVERABLE_EXTENSION = ".h5"
TIDMAD_DELIVERABLE_INDEX_WIDTH = 4

# Storage dtypes a deliverable can actually be written as. Deliberately the
# same set ``ValueEncoding``'s overflow check knows, so the input-side and
# output-side declarations cannot disagree about what a storage dtype is.
_WRITABLE_STORAGE_DTYPES = frozenset({"int8", "uint8", "int16"})


class DeliverableNaming(BaseModel):
    """How a deliverable is NAMED, and how names are matched back.

    Every accessor below composes from the SAME three fields. That is the
    whole point: before this existed, the qualified name, the fix-mode name,
    two differently-shaped cleanup globs and a file-index regex were five
    independent restatements of one template, and nothing made them move
    together. Renaming a deliverable meant finding all five — failure class 1
    is what happens when you find four.

    The defaults are the frozen TIDMAD values. Constructing
    ``DeliverableNaming()`` therefore yields the shipped default with no
    declaration needed, which is what "REQUIRED FOR LEGACY RUNS? NO" means
    mechanically.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    """``extra="forbid"`` added by Step 11 C6, and it is load-bearing.

    A composition DECLARES naming in its manifest, so a misspelled key —
    ``prefix_`` for ``prefix`` — would otherwise be silently ignored and the
    composed task would resolve the SHIPPED TIDMAD template: right-looking
    names, and a cleanup glob deleting files the run never wrote. That is
    the same reasoning `_MANIFEST_KEYS` uses one level up, and the same
    posture ``MetricSpec`` already takes."""

    prefix: str = Field(
        default=TIDMAD_DELIVERABLE_PREFIX,
        description="Leading stem shared by every deliverable name.",
    )
    extension: str = Field(
        default=TIDMAD_DELIVERABLE_EXTENSION,
        description="Filename extension, including the leading dot.",
    )
    index_width: int = Field(
        default=TIDMAD_DELIVERABLE_INDEX_WIDTH,
        gt=0,
        description="Zero-padded width of the file-index component.",
    )

    @field_validator("prefix")
    @classmethod
    def _prefix_is_usable(cls, value: str) -> str:
        """Reject a prefix that would resolve an empty or glob-degenerate name.

        An empty prefix does not fail at construction on its own — it silently
        produces names like ``_wavenet_run_exp_0000.h5`` and a cleanup glob of
        ``_*.h5``, which matches files this run never wrote. Checking here is
        the only place the value is visible before it reaches a filesystem
        operation that deletes things.
        """
        if not value or value.strip() != value:
            raise ValueError(
                f"prefix must be a non-empty string with no surrounding whitespace; got {value!r}. "
                f"An empty or padded prefix resolves a degenerate cleanup glob."
            )
        if "*" in value or "?" in value:
            raise ValueError(
                f"prefix must not contain glob metacharacters; got {value!r}. "
                f"A wildcard in the stem would make cleanup match artifacts this run never wrote."
            )
        return value

    @field_validator("extension")
    @classmethod
    def _extension_is_usable(cls, value: str) -> str:
        """Reject an extension that is not a real dotted suffix."""
        if not value.startswith(".") or len(value) < 2:
            raise ValueError(f"extension must start with '.' and name a suffix; got {value!r}.")
        return value

    def _index(self, file_index: int) -> str:
        return str(int(file_index)).zfill(self.index_width)

    def name(self, *, model_type: str, run_name: str, exp_id: str, file_index: int) -> str:
        """The fully qualified deliverable name.

        The shape every production producer, reader and cleanup consumer
        agrees on: ``<prefix>_<model>_<run>_<exp>_<index><ext>``.
        """
        return (
            f"{self.prefix}_{model_type}_{run_name}_{exp_id}_"
            f"{self._index(file_index)}{self.extension}"
        )

    def unqualified_name(self, *, model_type: str, file_index: int) -> str:
        """The legacy ``mode == "fix"`` name — model and index only.

        A genuinely different NAME SHAPE, not a different directory: the fix
        path predates run/exp scoping and omits both. Preserved rather than
        unified, because files with this name exist on disk.
        """
        return f"{self.prefix}_{model_type}_{self._index(file_index)}{self.extension}"

    def attempt_glob(self, *, model_type: str, run_name: str, exp_id: str) -> str:
        """Fully qualified match for ONE attempt's own outputs.

        Used by the watchdog's partial-artifact cleanup, which runs on the
        deadline-kill path: it must not touch a concurrent attempt's files.
        """
        return f"{self.prefix}_{model_type}_{run_name}_{exp_id}_*{self.extension}"

    def experiment_glob(self, *, exp_id: str) -> str:
        """Match every deliverable of one ``exp_id``, across model and run.

        Deliberately broader than :meth:`attempt_glob` — this is what
        ``--cleanup_denoised`` uses, so an artifact left by a different model
        or run name under the same experiment id is still reclaimed.
        """
        return f"{self.prefix}_*_{exp_id}_*{self.extension}"

    def any_glob(self) -> str:
        """Match any deliverable, for workspace-wide artifact audits."""
        return f"{self.prefix}_*{self.extension}"

    def file_index_of(self, name: str) -> int | None:
        """Parse the file index back out of a deliverable name.

        The INVERSE of :meth:`name`, and the reason it belongs here: an audit
        tool that re-derives the index with its own regex is a second
        restatement of the template, which is exactly the drift this contract
        exists to prevent.

        Returns ``None`` when ``name`` is not a deliverable of this spec.
        """
        match = re.fullmatch(
            rf"{re.escape(self.prefix)}_.*_(\d{{{self.index_width}}}){re.escape(self.extension)}",
            name.strip(),
        )
        return int(match.group(1)) if match else None


class DeliverableStorage(BaseModel):
    """How a deliverable's samples are STRUCTURED and STORED.

    Derived, never declared: the channel-group identity comes from
    ``DatasetProfile.channels`` and the storage representation from
    ``DatasetProfile.encoding``. That derivation is what makes the TIDMAD
    coincidence safe — the same ``128`` appears on the input-decode side and
    the output-encode side, and after this they agree *by derivation* instead
    of by two literals that happen to match.

    ``compute_dtype`` and ``num_classes`` are deliberately absent: they are
    input-decode and model-contract facts respectively, and importing them
    here would move an Input-Dataset-Contract fact into a producer contract.
    """

    model_config = ConfigDict(frozen=True)

    input_channel_group: str = Field(
        description="In-file group the model INPUT / denoised signal is written to.",
    )
    target_channel_group: str = Field(
        description="In-file group the TRUTH / injected signal is written to.",
    )
    storage_dtype: str = Field(
        description="NumPy dtype name persisted samples are stored as, e.g. 'int8'.",
    )
    value_offset: int = Field(
        description=(
            "Offset SUBTRACTED from a computed sample to return it to the stored "
            "representation — the inverse of the input decode's addition."
        ),
    )

    @field_validator("storage_dtype")
    @classmethod
    def _storage_dtype_is_writable(cls, value: str) -> str:
        """Reject a dtype the persisted buffers could not actually be allocated as.

        Not a declaration check: any ``str`` satisfies the annotation, and an
        unknown name does not fail until ``np.zeros(..., dtype=value)`` runs —
        which happens **after** training, inference and the whole GPU cost of
        an attempt have already been spent. Failing at construction moves that
        to run start.

        The accepted set mirrors the widths table
        :class:`~execute_tools.dataset_config.ValueEncoding` already uses, so
        the two declarations cannot drift into disagreeing about what a storage
        dtype is.
        """
        if value not in _WRITABLE_STORAGE_DTYPES:
            raise ValueError(
                f"storage_dtype={value!r} is not a supported persisted representation; "
                f"expected one of {sorted(_WRITABLE_STORAGE_DTYPES)}. An unrecognised "
                f"name would not fail until the buffers are allocated, after an "
                f"attempt's training and inference cost has already been spent."
            )
        return value

    @field_validator("target_channel_group")
    @classmethod
    def _distinct_groups(cls, value: str, info: ValidationInfo) -> str:
        """Reject writing both signals to one group.

        A single group would silently overwrite the denoised signal with the
        injected one and still produce a readable, plausible file.
        """
        other = info.data.get("input_channel_group")
        if other is not None and value == other:
            raise ValueError(
                f"input_channel_group and target_channel_group are both {value!r}. "
                f"Writing both signals to one group would overwrite the denoised "
                f"output with the injected truth."
            )
        return value


class DeliverableSpec(BaseModel):
    """The provisional Deliverable Contract: naming plus persisted storage.

    One value, two components, one derivation. Consumers that only resolve
    names may hold :attr:`naming` alone — it is the same object, not a copy.
    """

    model_config = ConfigDict(frozen=True)

    naming: DeliverableNaming = Field(
        description="Name resolution and name matching.",
    )
    storage: DeliverableStorage = Field(
        description="Channel-group identity and persisted storage representation.",
    )


_ACTIVE_DELIVERABLE_NAMING: ContextVar[DeliverableNaming | None] = ContextVar(
    "siderius_active_deliverable_naming", default=None
)


@contextmanager
def bind_deliverable_naming(naming: DeliverableNaming) -> Iterator[DeliverableNaming]:
    """Bind a composed run's DECLARED naming for the run scope. Step 11 C6.

    The Deliverable Contract remains the sole naming OWNER (R-11-3): what a
    composition supplies is a declaration, and it is this module's own
    :class:`DeliverableNaming` — with its own fail-closed validators — that
    turns it into a usable rule. Step 11 is a reader and a transporter.
    """
    token = _ACTIVE_DELIVERABLE_NAMING.set(naming)
    try:
        yield naming
    finally:
        _ACTIVE_DELIVERABLE_NAMING.reset(token)


def active_deliverable_naming() -> DeliverableNaming | None:
    """The bound naming, or ``None`` — no fallback. Step 11 C6."""
    return _ACTIVE_DELIVERABLE_NAMING.get()


def resolve_deliverable_naming() -> DeliverableNaming:
    """The naming in force: a composed run's declared one, else the shipped.

    Step 11 C6. Called at the two places a naming is CONSTRUCTED — the
    sandbox and :func:`derive_tidmad_deliverable_spec` — so both cleanup
    consumers pick up a composed task's template without a single call-site
    change. Before this, a contrast run's cleanup glob matched filenames it
    had never written.
    """
    bound = _ACTIVE_DELIVERABLE_NAMING.get()
    return bound if bound is not None else DeliverableNaming()


def default_deliverable_naming() -> DeliverableNaming:
    """The shipped TIDMAD naming, for consumers that need no profile.

    The path builder, both cleanup sites and the reconstruction tooling
    resolve names from identifiers alone; requiring them to hold a
    ``DatasetProfile`` would make them depend on a declaration they never
    read. This is the SAME literal the full derivation uses — one prefix,
    declared once, on :class:`DeliverableNaming`.
    """
    return resolve_deliverable_naming()


def default_deliverable_storage() -> DeliverableStorage:
    """The shipped storage representation, for callers that predate 05c.

    The Regime-A adapter for the writer: ``create_abra_file`` takes its channel
    identity as an argument, and every production call site supplies it, but a
    caller that never heard of the parameter must still write exactly the
    pre-05c file. Resolving it here — through Step 02's existing
    :func:`~execute_tools.dataset_config.resolve_dataset_profile` seam, which
    honours a bound profile and otherwise returns the shipped TIDMAD one — is
    what keeps ``array2h5`` free of a ``channel0001`` literal without making
    the parameter mandatory.

    This is NOT an ambient "current spec": nothing is cached, nothing is
    mutable, and it is consulted only when no argument was supplied.
    """
    return derive_tidmad_deliverable_spec(resolve_dataset_profile()).storage


def derive_tidmad_deliverable_spec(dataset_profile: DatasetProfile) -> DeliverableSpec:
    """THE shared derivation — one function, called identically on both sides.

    §3.2a, Option A: the spec does not cross the process boundary. The parent
    holds a profile and derives; the subprocess loads the profile it was given
    through ``--dataset_profile_json`` and derives the *equal* value. No third
    transport is introduced and no literal is reproduced at two sites.

    The Model-I/O contract is deliberately NOT a parameter. §2.2's per-literal
    audit leaves the model-output decode selector (``argmax`` vs pass-through,
    keyed on ``output_type`` via I15) with ``ModelIOContract``, so the
    deliverable spec has nothing to derive from it, and accepting it would
    imply an ownership 05c explicitly disclaims.

    Args:
        dataset_profile: The resolved profile in effect for this run. The
            channel identity and value encoding are read from it; nothing is
            read from ambient state.

    Returns:
        The deliverable spec for this run. Under TIDMAD this resolves the
        names, groups and storage representation the pre-05c literals produced.
    """
    return DeliverableSpec(
        # Step 11 C6 — a composed run's DECLARED naming when one is bound.
        naming=resolve_deliverable_naming(),
        storage=DeliverableStorage(
            input_channel_group=dataset_profile.channels.input_channel,
            target_channel_group=dataset_profile.channels.target_channel,
            storage_dtype=dataset_profile.encoding.storage_dtype,
            value_offset=dataset_profile.encoding.value_offset,
        ),
    )
