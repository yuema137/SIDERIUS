# workflows/task_config.py
"""
Loader + renderer for the global task config (``configs/task_config.yaml``).

The task config is the single source of truth for two pieces of operator-facing
information — ``task_description`` and ``forward_contract`` — that used to be
hardcoded as string literals in agent system prompts. See
``docs/design/enable_global_task_config.md`` for the full design.

Public API:

  * :func:`load_task_config` — read and validate the YAML; fail-fast on a
    missing file, an empty ``task_description``, or a typo in any
    ``forward_contract`` key.
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

import os
from typing import Any

import yaml

from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_io_resolution import resolve_model_io_contract
from agent.schemas.task_config import ForwardContract

# Repo-relative default path. Resolved at call time (not import time) so a
# test that monkeypatches ``os.getcwd`` or chdirs into a fixture dir sees the
# updated cwd. The chain runner always invokes with cwd == repo root.
_DEFAULT_CONFIG_PATH = "configs/task_config.yaml"

# Module-level cache: ``load_task_config()`` short-circuits to the cached
# value on subsequent calls so the YAML is parsed once per process. Keyed by
# the absolute resolved path so distinct test fixtures don't collide.
_CACHE: dict[str, dict[str, Any]] = {}

# Remediation message shown when the canonical config file is missing.
# Kept in sync with the wording in
# docs/design/enable_global_task_config.md § "Backward compatibility".
_MISSING_FILE_REMEDIATION = (
    "{path} not found.\n"
    "  This file is required for all SIDERIUS agent runs.\n"
    "  If you deleted it accidentally, restore from git:\n"
    "      git checkout {path}\n"
    "  If you are setting up a new task, copy and edit:\n"
    "      cp configs/task_config.example.yaml {path}"
)


def _dataset_num_classes() -> int | None:
    """The bound Dataset Profile's class count, for the 3-E cross-check.

    Read at call time from the Step-02 authority
    (``ValueEncoding.num_classes``), never restated here — §4b keeps the
    dataset side as the single cardinality authority and Step 03 only
    derives from or cross-validates against it.

    Returns ``None`` if no profile can be resolved, so a caller in an
    environment without one is not blocked; the cross-check simply does not
    run. It must NEVER fall back to a literal, which would silently
    reintroduce TIDMAD's 256 as a default (§21).
    """
    from execute_tools.dataset_config import resolve_dataset_profile

    return resolve_dataset_profile().encoding.num_classes


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
            ``configs/task_config.yaml`` resolved relative to the current
            working directory.

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
    resolved = os.path.abspath(path or _DEFAULT_CONFIG_PATH)

    if resolved in _CACHE:
        return _CACHE[resolved]

    if not os.path.isfile(resolved):
        raise FileNotFoundError(_MISSING_FILE_REMEDIATION.format(path=path or _DEFAULT_CONFIG_PATH))

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
