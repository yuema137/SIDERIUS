"""Locate and load canned pseudo-mode test data from ``tests/pseudo_data/``.

Used by ``RecordingLLMBridge.for_agent()`` and ``RecordingSandbox.for_model()``
to build pre-loaded recording fakes from JSON files on disk.

The pseudo-data tree is the single source of truth for "what does a canned
response from this agent's LLM call (or this model's training subprocess) look
like." Schema fidelity with the real API is maintained as a project invariant:
when an output schema changes, the corresponding JSON file must change in the
same commit.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict

# tests/helpers/_pseudo_data.py → tests/helpers/ → tests/ → tests/pseudo_data/
PSEUDO_DATA_ROOT = pathlib.Path(__file__).resolve().parent.parent / "pseudo_data"


def load_pseudo_data(category: str, name: str) -> dict[str, Any]:
    """Load all ``*.json`` files under ``tests/pseudo_data/{category}/{name}/``.

    Args:
        category: top-level pseudo-data category. Conventionally
            ``"api_call_outputs"`` (canned LLM responses) or
            ``"train_outputs"`` (canned subprocess results).
        name: agent or model identifier. For ``api_call_outputs`` this is the
            agent's CLAUDE.md taxonomy name (e.g. ``"ml_hyperparameter_tune_agent"``);
            for ``train_outputs`` it is a built-in model key (e.g. ``"punet"``).

    Returns:
        Dict mapping file stem (without ``.json``) to the parsed JSON contents.
        For example, if the directory contains ``generate.json`` and
        ``reflect.json``, the result is
        ``{"generate": {...}, "reflect": {...}}``.

    Raises:
        FileNotFoundError: if the target directory does not exist. Add canned
            outputs to ``tests/pseudo_data/{category}/{name}/`` before using
            ``RecordingLLMBridge.for_agent()`` or ``RecordingSandbox.for_model()``.
    """
    target_dir = PSEUDO_DATA_ROOT / category / name
    if not target_dir.is_dir():
        raise FileNotFoundError(
            f"No pseudo_data directory at {target_dir}. "
            f"Add canned outputs there before using for_agent/for_model. "
            f"See tests/pseudo_data/README or docs/pseudo_test_infra.md for the layout."
        )
    out: dict[str, Any] = {}
    for json_file in sorted(target_dir.glob("*.json")):
        with open(json_file) as f:
            out[json_file.stem] = json.load(f)
    return out
