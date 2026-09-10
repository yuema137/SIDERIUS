# workflows/task_config.py
"""
Loader + renderer for a caller-owned task configuration.

The task config is the single source of truth for two pieces of operator-facing
information — ``task_description`` and ``forward_contract`` — that used to be
hardcoded as string literals in agent system prompts. See
``docs/design/enable_global_task_config.md`` for the full design.

Public API:

  * :func:`load_task_config` — read and validate the YAML; fail-fast on a
    missing file, an empty ``task_description``, or a typo in any
    ``forward_contract`` key.
  * :func:`task_config_file_sha256` — sha256 of the raw file bytes, the
    run-invariants lock pin of the config the prompt surfaces read
    (F-SCANH-1).
  * :func:`render_forward_contract` — render a populated
    :class:`~agent.schemas.task_config.ForwardContract` into the multi-line
    block that gets substituted into the ``{FORWARD_CONTRACT}`` placeholder.
  * :func:`get_task_description` — extract the stripped ``task_description``
    string from a parsed config dict.

Internal callers in the workflow + agent nodes always go through
:func:`load_task_config`; the renderer + getter are exported separately so
test code can construct a synthetic ``ForwardContract`` / dict without round-
tripping through the filesystem.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import yaml

from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_io_resolution import resolve_model_io_contract
from agent.schemas.task_config import ForwardContract

# F-SCANA-2 — repository root, derived from this file's own location (the
# established root-derivation idiom, same as
# ``workflows/model_exploration.py::SIDERIUS_ROOT``). The canonical config
# used to be resolved against the CALLER'S CWD here while the workspace
# snapshot (``model_exploration._snapshot_task_config``) resolved against
# SIDERIUS_ROOT, with a comment asserting "the chain runner always invokes
# with cwd == repo root" instead of enforcing it. From a foreign cwd the
# read (and the F-SCANH-1 lock pin, which mirrors the read) could therefore
# address a DIFFERENT file than the one the snapshot preserves. One
# root-anchored resolution authority now serves all three; tests that need
# a fixture config monkeypatch ``_SIDERIUS_ROOT`` instead of chdir'ing.
_SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_task_config_path() -> str:
    """The canonical ``configs/task_config.yaml`` location (F-SCANA-2).

    The ONE resolution authority for the file: :func:`load_task_config`
    (the read), :func:`task_config_file_sha256` (the run-invariants lock
    pin) and ``workflows.model_exploration._snapshot_task_config`` (the
    workspace snapshot) all address the canonical file through this
    function, so they cannot diverge by construction. SIDERIUS_ROOT-
    anchored — independent of the caller's working directory. Resolved at
    call time so a test redirecting ``_SIDERIUS_ROOT`` is honoured.

    Returns:
        Absolute path of the canonical task-config file.
    """
    return os.path.join(_SIDERIUS_ROOT, "configs", "task_config.yaml")


# Module-level cache: ``load_task_config()`` short-circuits to the cached
# value on subsequent calls so the YAML is parsed once per process. Keyed by
# the absolute resolved path so distinct test fixtures don't collide.
_CACHE: dict[str, dict[str, Any]] = {}

# Remediation message shown when the canonical config file is missing.
# Kept in sync with the wording in
# docs/design/enable_global_task_config.md § "Backward compatibility".
_MISSING_FILE_REMEDIATION = (
    "{path} not found.\n"
    "  Supply the task through --task_composition, or pass an explicit "
    "task-config path. SIDERIUS does not select a scientific task by default."
)


def _dataset_num_classes() -> int | None:
    """The bound Dataset Profile's class count, for the 3-E cross-check.

    Read at call time from the Step-02 authority
    (``ValueEncoding.num_classes``), never restated here — §4b keeps the
    dataset side as the single cardinality authority and Step 03 only
    derives from or cross-validates against it.

    Returns ``None`` if no class count can be resolved, so a caller without
    one is not blocked; the cross-check simply does not run. It must NEVER
    fall back to a literal, which would silently reintroduce TIDMAD's 256 as
    a default (§21).

    **Step 12 / PR-12d (F-12d-4) — the body now implements that promise.**
    It read ``resolve_tidmad_topology()`` unconditionally, which RAISES for a
    profile that declares no TIDMAD topology. So a composed Pets or DAVIS run
    whose ``task_config`` declared ``model_io`` failed at composition, inside
    the very ``bind_dataset_profile`` that ``_compose_task_config`` wraps
    around this call so the cross-check would see the composed profile.

    A task with no ``ValueEncoding`` has no class count — that is a DECLARED
    ABSENCE, and ``None`` is exactly how this function's contract already
    says to express it. The cross-check then has nothing to compare against,
    which is honest; the contract's own shape validation is untouched, and
    the TIDMAD answer is unchanged.
    """
    from execute_tools.dataset_config import (
        declares_tidmad_topology,
        resolve_dataset_profile,
        tidmad_topology,
    )

    profile = resolve_dataset_profile()
    if not declares_tidmad_topology(profile):
        return None
    return tidmad_topology(profile).encoding.num_classes


_BOUND_TASK_CONFIG: ContextVar[dict[str, Any] | None] = ContextVar(
    "siderius_bound_task_config", default=None
)
"""The COMPOSED run's task configuration, when one is bound (Step 10 / P1).

Why an override here rather than a value threaded to each consumer: the
task description reaches five consumer families — planner, literature
review, proposer, implementor, interpreter — and every one of them calls
``load_task_config()`` itself, at its own depth (a bridge, a renderer, a
node). There is no single injection point to thread a string through, so
the authority moves to the composition at the ONE place all five already
funnel through.

This is what demotes the module-level YAML cache below from *the* authority
to a legacy compatibility adapter: still the way an un-composed run obtains
its values, never the authority for a composed one. Step 12 supplies the
same bound value from an external package without touching any consumer.
"""


@contextmanager
def bind_task_config(values: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Bind a composed run's task configuration for the duration of the block.

    ContextVar + token reset, the ``bind_dataset_profile`` idiom: sequential
    and nested runs in one process never observe each other's values, and an
    exception cannot strand a composed task description where the next run
    would read it.

    The bound mapping is the SAME shape ``load_task_config`` returns
    (``task_description`` + a dumped ``forward_contract`` + any extra keys),
    so no consumer needs to know whether the run was composed.
    """
    token = _BOUND_TASK_CONFIG.set(values)
    try:
        yield values
    finally:
        _BOUND_TASK_CONFIG.reset(token)


def resolve_bound_task_config() -> dict[str, Any] | None:
    """The composed run's task configuration, or ``None`` when un-composed."""
    return _BOUND_TASK_CONFIG.get()


def _clear_cache_for_tests() -> None:
    """Test-only helper. Drop the module-level cache so a test can swap the
    fixture file under a single path without seeing stale parsed data.
    """
    _CACHE.clear()


def load_task_config(path: str | None = None) -> dict[str, Any]:
    """Load + validate ``configs/task_config.yaml`` (or the provided path).

    Returns a dict with the shape::

        {
            "task_description": "<non-empty stripped string>",
            "forward_contract": {<ForwardContract field name>: <value>, ...},
            ...any extra YAML top-level keys, passed through verbatim...
        }

    The ``forward_contract`` sub-dict is round-tripped through
    :class:`ForwardContract` for validation — a missing key (or a typo such
    as ``input_shapes`` plural) raises a ``ValidationError`` rather than a
    silent empty rendering downstream.

    Args:
        path: Optional override for the YAML location. Defaults to
            :func:`default_task_config_path` — the canonical
            SIDERIUS_ROOT-anchored ``configs/task_config.yaml``,
            independent of the caller's working directory (F-SCANA-2).

    Returns:
        Parsed and validated YAML dict.

    Raises:
        FileNotFoundError: When the YAML file does not exist on disk. The
            error message carries the operator-facing remediation text
            documented in the design doc.
        ValueError: When the parsed YAML is empty / ``None``, when
            ``task_description`` is missing or empty after stripping, or
            when the ``forward_contract`` block is missing entirely.
        pydantic.ValidationError: Propagated as-is from
            ``ForwardContract(**fc_dict)`` when a required forward-contract
            key is missing or a value violates a field constraint.
    """
    # Step 10 / P1: a composed run's values win, and they win for every
    # consumer at once. An EXPLICIT ``path`` still reads that file — the
    # composition edge itself loads the task's config this way, and a caller
    # naming a file is asking for that file, not for the run's binding.
    if path is None:
        bound = _BOUND_TASK_CONFIG.get()
        if bound is not None:
            return bound
        raise ValueError(
            "no task configuration is bound. Supply --task_composition or "
            "pass an explicit task-config path; SIDERIUS has no scientific "
            "task default."
        )

    resolved = os.path.abspath(path or default_task_config_path())

    if resolved in _CACHE:
        return _CACHE[resolved]

    if not os.path.isfile(resolved):
        raise FileNotFoundError(_MISSING_FILE_REMEDIATION.format(path=resolved))

    with open(resolved, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None or not isinstance(raw, dict):
        raise ValueError(
            f"{resolved}: parsed YAML is empty or not a mapping. "
            f"The file must define top-level keys 'task_description' "
            f"and 'forward_contract'."
        )

    # task_description: required, non-empty after stripping.
    task_description = str(raw.get("task_description") or "").strip()
    if not task_description:
        raise ValueError(
            f"{resolved}: 'task_description' is missing or empty. "
            f"This field is required — it is injected into every agent "
            f"system prompt's {{TASK_DESCRIPTION}} placeholder."
        )

    # forward_contract: required block, validated via Pydantic.
    fc_raw = raw.get("forward_contract")
    if fc_raw is None:
        raise ValueError(
            f"{resolved}: 'forward_contract' block is missing. "
            f"See configs/task_config.example.yaml for the expected shape."
        )
    if not isinstance(fc_raw, dict):
        raise ValueError(
            f"{resolved}: 'forward_contract' must be a mapping, got {type(fc_raw).__name__}."
        )
    # Pydantic raises ValidationError on missing required key or extra key.
    # Round-trip validation only — we keep the dict shape in the returned
    # config so downstream callers can rebuild ForwardContract themselves.
    contract = ForwardContract(**fc_raw)

    # Step 03 M2 — resolve the normalized declaration HERE, at the production
    # entry point every agent path funnels through, and at CALL time rather
    # than import time (§16). A preset or a dataset contradiction therefore
    # fails before any consumer sees the config — which is the "before any
    # LLM request is constructed" property Step-01 §6A.5 deferred as D13.
    #
    # Only reached when a task declares `model_io`. A legacy prose-only
    # contract (Regime A) resolves nothing and behaves exactly as before.
    if contract.model_io is not None:
        resolve_model_io_contract(
            contract.model_io,
            preset=contract.preset,
            dataset_num_classes=_dataset_num_classes(),
        )

    config = dict(raw)
    config["task_description"] = task_description
    # Return the RESOLVED contract, not the raw YAML block. When `model_io`
    # is declared the prose fields are derived during validation, so handing
    # back the raw mapping would give every caller something LESS resolved
    # than what was validated here — `cfg["forward_contract"]["num_classes"]`
    # would simply vanish for a migrated task. Round-trips: the dump revalidates
    # through `ForwardContract(**...)`, and the derivation is idempotent
    # because the dumped values already equal the derived ones.
    # `mode="json"` so the returned mapping is JSON-native — a caller
    # serializing the config must not meet a tuple or a StrEnum, and the
    # round-trip back through `ForwardContract(**...)` coerces them back.
    config["forward_contract"] = contract.model_dump(mode="json")
    _CACHE[resolved] = config
    return config


def task_config_file_sha256(path: str | None = None) -> str:
    """sha256 hexdigest of the raw bytes of the task-config FILE.

    F-SCANH-1 — this is the run-invariants lock pin of the file the prompt
    surfaces read through :func:`load_task_config`: an operator edit to
    ``configs/task_config.yaml`` mid-workspace changes what the LLM reads,
    and the lock comparison over this digest is what refuses the resume.
    A COMPOSED run never calls it — its task config arrives via
    :func:`bind_task_config` and its identity is owned by the lock's
    ``task_composition_fingerprint``.

    Resolution mirrors :func:`load_task_config` exactly
    (``os.path.abspath(path or default_task_config_path())`` — the one
    SIDERIUS_ROOT-anchored authority, F-SCANA-2, so the pinned sha is
    always computed over the same file the loader reads and the workspace
    snapshot preserves). The digest is
    computed over the raw file bytes on EVERY call — deliberately no
    caching, because the lock pin must see fresh bytes at every startup;
    the loader's parse cache is a separate concern (it serves parsed
    values, not file identity).

    Args:
        path: Optional override for the YAML location, resolved exactly as
            the loader resolves it. Production omits it.

    Returns:
        sha256 hexdigest of the file bytes.

    Raises:
        FileNotFoundError: When the file does not exist on disk, carrying
            the same operator-facing remediation text as the loader.
    """
    resolved = os.path.abspath(path or default_task_config_path())
    if not os.path.isfile(resolved):
        raise FileNotFoundError(_MISSING_FILE_REMEDIATION.format(path=resolved))
    with open(resolved, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_bound_model_io_contract(path: str | None = None) -> ModelIOContract | None:
    """The Model-I/O declaration THIS RUN is bound to, or ``None``.

    **One acquisition point, so "cannot diverge" is structural.** Every
    subprocess a run launches is already given exactly this value: the
    sandbox executor materializes it to ``--model_io_json`` for the training
    child (``core/sandbox_executor.py``) and for the inference child, and
    both fail closed on a broken file while omitting the flag entirely when
    the task declares no ``model_io``. Step 05b needs the same value for the
    resource pre-flight, and two sites computing it independently would rest
    on "happens to agree" — the defect shape Steps 02a/02b/05a removed
    elsewhere. So the expression lives here, once, and both callers use it.

    Resolution is NOT repeated here. ``load_task_config`` already runs
    ``resolve_model_io_contract`` at the single production entry point every
    agent path funnels through, and memoizes the parsed result per absolute
    path — so this returns the same validated object every caller in the
    process sees, not a second reading of the same file.

    Args:
        path: Optional override for the YAML location, forwarded verbatim to
            :func:`load_task_config`. Production omits it.

    Returns:
        The normalized contract, or ``None`` when the task declares no
        ``model_io``. ``None`` is the legacy prose-only form and is a
        supported task shape, never an error: consumers take their legacy
        no-contract path.
    """
    return ForwardContract(**load_task_config(path)["forward_contract"]).model_io


def run_bound_output_has_temporal_axis(path: str | None = None) -> bool | None:
    """Whether THIS RUN's declared OUTPUT tensor carries a temporal axis.

    **D2.** The one fact ``ml_models``' loss-availability authority needs in
    order to refuse ``focal`` / ``focal_cw`` for a task whose output is not
    per-timestep, rather than letting the pairing crash inside the loss's
    ``permute``. It is expressed here, once, because
    :func:`run_bound_model_io_contract` is the single acquisition point for
    the run's contract and a caller re-deriving this from the contract at
    each site would make "training and validation agree" a coincidence — the
    same reason ``_write_model_io_config`` gives for not restating it.

    The predicate itself belongs to the contract
    (``ModelIOContract.output_has_temporal_axis``); what is added here is the
    RUN BINDING around it, so the resource pre-flight — which already holds
    the contract object — and this accessor cannot answer differently.

    Args:
        path: Optional override for the YAML location, forwarded verbatim to
            :func:`run_bound_model_io_contract`. Production omits it.

    Returns:
        ``True`` / ``False`` when the task declares a normalized Model-I/O
        contract; ``None`` when it does not. ``None`` is the legacy
        prose-only form and means *"no declared geometry to rule on"* — the
        authority then preserves its shipped verdicts exactly. It is
        deliberately NOT collapsed into ``False``: absence of a declaration
        is not a declaration of absence.
    """
    contract = run_bound_model_io_contract(path)
    if contract is None:
        return None
    return contract.output_has_temporal_axis


def get_task_description(config: dict[str, Any]) -> str:
    """Return the stripped ``task_description`` from a parsed config dict.

    ``load_task_config`` already strips and rejects empty, so for
    canonically-loaded configs this is equivalent to
    ``config["task_description"]``. The helper exists so test code that
    constructs synthetic configs without going through
    ``load_task_config`` can still call into the same extraction path.

    Args:
        config: Dict returned by ``load_task_config`` (or a synthetic
            equivalent constructed in tests).

    Returns:
        Stripped task description. Empty string only when the caller
        bypassed ``load_task_config`` and built a dict with a missing or
        empty ``task_description`` field.
    """
    return str(config.get("task_description") or "").strip()


def render_forward_contract(fc: ForwardContract) -> str:
    """Render a :class:`ForwardContract` into the multi-line block that
    gets substituted into the ``{FORWARD_CONTRACT}`` placeholder.

    The rendered shape mirrors the example block in
    ``docs/design/enable_global_task_config.md`` § "Rendered forward
    contract format" — one fixed-format ``input:`` / ``output:`` pair,
    then any populated optional notes appended as plain paragraphs.

    A default-constructed ``ForwardContract()`` (every field empty)
    returns ``""``. This is only reachable from a caller that bypassed
    ``load_task_config`` and built one manually for tests; the production
    loader path rejects an empty contract upstream.

    Args:
        fc: Validated ForwardContract instance.

    Returns:
        Rendered block, ready to drop into the placeholder.
    """
    if fc.is_empty():
        return ""

    lines: list[str] = [
        "The model must satisfy this forward contract (non-negotiable):",
        f"    input:  {fc.input_shape}   — {fc.input_description}".rstrip(" —"),
        f"    output: {fc.output_shape}  — {fc.output_description}".rstrip(" —"),
    ]

    if fc.embedding_note:
        lines += ["", fc.embedding_note.strip()]
    if fc.output_head_note:
        lines += ["", fc.output_head_note.strip()]
    if fc.task_note:
        lines += ["", fc.task_note.strip()]
    if fc.task_type:
        # Step 03 §1 row 7: the class clause asserts a TEMPORAL axis, so it is
        # licensed by axis ROLES rather than by a cardinality being truthy.
        # `renders_per_timestep_class_clause` derives that from the normalized
        # contract when one is declared and preserves the legacy truthiness
        # test when one is not. Under TIDMAD both paths agree, so these bytes
        # are unchanged.
        descriptor = (
            f"Task type: {fc.task_type}"
            + (
                f" (per-timestep {fc.num_classes}-class)"
                if fc.renders_per_timestep_class_clause()
                else ""
            )
            + "."
        )
        lines += ["", descriptor]

    return "\n".join(lines)
