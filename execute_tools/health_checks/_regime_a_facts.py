# execute_tools/health_checks/_regime_a_facts.py
"""Regime-A derivation of a task's declared health facts.

Step 08a / C2. "Regime A" is the in-repo TIDMAD arrangement, where no task
health BINDING exists yet: the facts a check compares itself against are
derived from the two declarations that already own them —
:class:`~execute_tools.dataset_config.DatasetProfile` (topology, channel
identity, value encoding) and the Deliverable Contract
(:func:`~execute_tools.deliverable_spec.derive_tidmad_deliverable_spec`).

**Scope, deliberately narrow.** This module is the regime-A DEFAULT, not an
authority. When 08b introduces task-owned health config and run-scoped
plugin loading, the binding replaces the CALL SITE that chooses this
function — it does not replace or extend this function's contract, and it
does not add task branches here. There is no task name in this file and no
place for one: everything is read from the resolved profile.

**Presence-discriminated** (the D14 truth-table pattern): an axis this
derivation cannot honestly establish is left ABSENT rather than guessed. An
absent axis and a mismatched axis are different situations and produce
different inapplicability reasons.
"""

from __future__ import annotations

from execute_tools.dataset_config import (
    DatasetProfile,
    resolve_dataset_profile,
    tidmad_topology,
)
from execute_tools.deliverable_spec import DeliverableStorage, derive_tidmad_deliverable_spec
from execute_tools.health_checks.schemas import TaskHealthFacts

_SYMBOL_STREAM_DTYPES: frozenset[str] = frozenset({"int8", "uint8", "int16"})
"""Storage dtypes whose samples form a finite symbol alphabet.

Mirrors the widths table
:class:`~execute_tools.dataset_config.ValueEncoding` validates against, so
the two cannot drift into disagreeing about what an integer sample is. A
float storage dtype is not here: it has no alphabet, and the class-histogram
declaration would be meaningless for it."""


def _encoding_family(storage: DeliverableStorage) -> str | None:
    """Family identifier for how the deliverable's samples are encoded.

    Derived from the STORAGE dtype rather than declared, because in regime A
    nothing declares it: the deliverable's dtype is the only statement about
    the shape of an output sample that exists. Under TIDMAD this yields
    ``"int8_symbol_stream"``.

    Returns None for a dtype this function cannot classify — the honest
    answer when the profile says nothing that settles the question.
    """
    if storage.storage_dtype in _SYMBOL_STREAM_DTYPES:
        return f"{storage.storage_dtype}_symbol_stream"
    return None


def derive_health_facts(profile: DatasetProfile) -> TaskHealthFacts:
    """Derive the health facts implied by a resolved dataset profile.

    Args:
        profile: the profile in effect for this run. Nothing is read from
            ambient state; the caller decides which profile applies.

    Returns:
        The declared facts, with any axis this derivation cannot establish
        left absent.

    Axes and their sources::

        encoding_family        deliverable storage dtype (via the contract)
        symbol_cardinality     tidmad_topology(profile).encoding.num_classes, when symbolic
        file_group_size        profile.partition_count
        sampling_frequency_hz  tidmad_topology(profile).dataset.sampling_frequency
        value_scale_unit       ABSENT — see below

    ``value_scale_unit`` is deliberately NOT derived. The millivolt scale
    TIDMAD's dispersion checks apply (``_MV_PER_LSB = 40 / 128``) is a
    literal inside those check modules; no profile field declares it. Making
    it a derived fact here would be inventing a declaration the task never
    made, and requiring it in a check's declaration would flip TIDMAD's std
    checks to ``inapplicable`` — a parity break. The scale moves with the
    thresholds when 08b migrates ownership.
    """
    storage = derive_tidmad_deliverable_spec(profile).storage
    family = _encoding_family(storage)
    return TaskHealthFacts(
        encoding_family=family,
        # Guarded by the family: a cardinality without a family is rejected
        # by TaskHealthFacts, and would be meaningless besides.
        symbol_cardinality=tidmad_topology(profile).encoding.num_classes
        if family is not None
        else None,
        value_scale_unit=None,
        file_group_size=profile.partition_count,
        sampling_frequency_hz=tidmad_topology(profile).dataset.sampling_frequency,
    )


def resolve_health_facts() -> TaskHealthFacts:
    """The regime-A production default: facts for the currently bound profile.

    Thin by design — it exists so call sites do not each repeat the
    ``resolve_dataset_profile()`` hop, and so 08b has ONE function to
    replace when a task binding supplies facts directly.
    """
    return derive_health_facts(resolve_dataset_profile())
