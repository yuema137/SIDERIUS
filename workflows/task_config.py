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
    ForwardContract(**fc_raw)

    config = dict(raw)
    config["task_description"] = task_description
    _CACHE[resolved] = config
    return config


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
        descriptor = (
            f"Task type: {fc.task_type}"
            + (f" (per-timestep {fc.num_classes}-class)" if fc.num_classes else "")
            + "."
        )
        lines += ["", descriptor]

    return "\n".join(lines)
