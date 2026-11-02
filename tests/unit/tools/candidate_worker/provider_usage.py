"""Explicit offline usage reporting shared by inherited and exec-created providers."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest


def install_reporting(patch: pytest.MonkeyPatch, owner: type[Any], witness: Path) -> None:
    """Wrap each provider method once, reporting to its bound production run ledger."""

    def reporting(method: Any) -> Any:
        def call(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = method(self, *args, **kwargs)
            report(self.context, witness, str(kwargs.get("label", "")))
            return result

        return call

    for name in ("generate", "generate_text"):
        if name in vars(owner):
            patch.setattr(owner, name, reporting(vars(owner)[name]))


def report(context: dict[str, Any] | None, witness: Path, label: str) -> None:
    """Record only fixture usage and process evidence, never environment values generally."""
    assert context is not None, "provider called without a bound run context"
    row = {
        "ts": "2026-10-27T10:00:00Z",
        "run_id": context["run_id"],
        "run_name": context["run_name"],
        "label": "response",
        "provider": "openai",
        "model": "fixture-model",
        "served_model": None,
        "tokens": {"prompt": 11, "completion": 2, "total": 13},
        "chars": {"system": 0, "user": 0, "total": 0},
    }
    with (Path(context["workspace"]) / "token_usage.jsonl").open("a") as ledger:
        ledger.write(json.dumps(row) + "\n")
    with witness.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "label": label,
                    "iteration": context["iter"],
                    "pid": os.getpid(),
                    "safe_path": sys.flags.safe_path,
                    "hash_seed": os.environ.get("PYTHONHASHSEED"),
                }
            )
            + "\n"
        )
