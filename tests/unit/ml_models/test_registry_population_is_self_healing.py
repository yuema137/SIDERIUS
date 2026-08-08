"""V21 PR C2 — a registry reader must not depend on someone else's import.

The failure family, in one sentence: **a registry is populated by an import
side effect, and some path reads it without executing the populating
import.** That is the V20 defect, and it took two PRs to close:

    #184  the worker spawned without ``env=``, so SIDERIUS_PLUGIN_DIRS never
          reached the child. Fixed the transport. Attempt 3 still produced
          zero formal records.
    #185  ``get_config_class`` reads PLUGIN_CONFIG_REGISTRY, which is filled
          by ``ml_models.models_sandbox``'s module tail. ``build_production_
          components`` imported it and resolved; ``validate_candidate_
          configs`` did not and returned None. Two paths in one file, one
          import apart, disagreeing about whether a model exists.

#185 fixed the *call site*. C2's audit found the *function* was still
vulnerable: measured in a clean process importing only
``models_format_sandbox``, ``get_config_class`` saw **0 of 82** plugins and
returned ``None`` — silently — for a plugin registered perfectly well on
disk. Every production entry point measured (the tuner,
``workflows.model_exploration``, ``core.sandbox_executor``) showed the same
empty registry at import time.

These tests run in **real spawned subprocesses**. An in-process test cannot
express the property at all: by the time pytest has collected this file,
something in the session has already imported ``models_sandbox``, so the
registry is populated and every assertion would pass vacuously.

Portability: the plugin is written to a ``tmp_path`` and exposed via
``SIDERIUS_PLUGIN_DIRS``. Nothing here reads ``agent_generated/models``,
which is gitignored and empty on CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

_PLUGIN_SOURCE = textwrap.dedent(
    '''
    """Minimal agent-generated plugin used to probe registry population."""

    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "c2_registry_probe_model"
    PLUGIN_OUTPUT_TYPE = "regressor"


    class C2RegistryProbeConfig(BaseModel):
        model_type: str = "c2_registry_probe_model"
        segmentation_size: int = 64


    class C2RegistryProbeModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.emb = nn.Embedding(256, 4)
            self.head = nn.Conv1d(4, 1, 1)

        def forward(self, x):
            return self.head(self.emb(x).transpose(1, 2)).squeeze(1)


    PLUGIN_CONFIG_CLASS = C2RegistryProbeConfig
    PLUGIN_MODEL_CLASS = C2RegistryProbeModel
    '''
)

_MODEL_TYPE = "c2_registry_probe_model"


@pytest.fixture
def plugin_dir(tmp_path: Path) -> Path:
    """A run-scoped plugin directory containing exactly one plugin."""
    d = tmp_path / "plugins"
    d.mkdir()
    (d / f"{_MODEL_TYPE}.py").write_text(_PLUGIN_SOURCE)
    return d


def _run_in_clean_subprocess(plugin_dir: Path, body: str) -> str:
    """Execute ``body`` in a fresh interpreter that sees only ``plugin_dir``.

    Returns the subprocess's last stdout line, so the caller asserts on a
    value produced by a process that genuinely started empty.
    """
    env = dict(os.environ)
    env["SIDERIUS_PLUGIN_DIRS"] = str(plugin_dir)
    env["PYTHONPATH"] = str(REPO_ROOT)
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=180,
    )
    assert completed.returncode == 0, (
        f"probe subprocess failed:\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
    )
    return completed.stdout.strip().splitlines()[-1]


def test_get_config_class_resolves_without_the_populating_import(plugin_dir):
    """The #185 defect, fixed at the function instead of at one call site.

    The subprocess imports **only** ``models_format_sandbox``. Before C2 the
    last line was ``RESULT None``; the plugin was on disk, valid, and
    invisible.

    Fails if: the self-healing import inside ``get_config_class`` is removed
    or moved above the built-in lookup in a way that stops running.
    """
    last = _run_in_clean_subprocess(
        plugin_dir,
        """
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            from ml_models.models_format_sandbox import get_config_class
            cls = get_config_class("c2_registry_probe_model")
        print("RESULT", cls.__name__ if cls is not None else None)
        """,
    )
    assert last == "RESULT C2RegistryProbeConfig"


def test_importing_sandbox_executor_populates_the_plugin_registry(plugin_dir):
    """``core.sandbox_executor`` reads the registry directly, twice.

    ``_validate_configs`` and the training-side validation both test
    ``model_type in PLUGIN_CONFIG_REGISTRY`` rather than calling
    ``get_config_class``, so the fix above does not cover them. With an
    empty registry a plugin model fails that membership test and falls
    through to the **built-in** branch, producing a confusing config error
    rather than using its own config class.

    Fails if: the side-effect import at the top of ``sandbox_executor`` is
    removed as "unused" — which is exactly how it would look to a reader or
    an autofixer, hence the ``noqa`` and the comment there.
    """
    last = _run_in_clean_subprocess(
        plugin_dir,
        """
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            import core.sandbox_executor  # noqa: F401
            from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
            present = "c2_registry_probe_model" in PLUGIN_CONFIG_REGISTRY
        print("RESULT", present)
        """,
    )
    assert last == "RESULT True"


def test_get_output_type_was_already_self_healing(plugin_dir):
    """Records the asymmetry C2's audit found, so it cannot silently regress.

    ``get_output_type`` lazily imports ``BUILTIN_OUTPUT_TYPES`` from
    ``models_sandbox``, which triggers population as a side effect — so it
    resolved correctly even before C2 while its sibling
    ``get_config_class`` did not. Two lookup helpers over the same plugin
    load, one immune and one not, is the asymmetry that let #185 hide.

    This pins the immunity as intentional rather than lucky: if someone
    "optimises" that lazy import into a module-level constant, this fails.
    """
    last = _run_in_clean_subprocess(
        plugin_dir,
        """
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            from ml_models.plugin_loader import get_output_type
            got = get_output_type("c2_registry_probe_model")
        print("RESULT", got)
        """,
    )
    # The plugin declares "regressor" — proving the value came from the
    # plugin file and not from C1's built-in table or any default.
    assert last == "RESULT regressor"


def test_an_unregistered_name_still_fails_closed_in_a_clean_process(plugin_dir):
    """C1 and C2 compose: population is automatic, absence is still loud.

    A self-healing lookup must not become a *forgiving* one. After the
    registry has been populated from the real plugin directory, a name that
    is genuinely absent must still raise rather than acquire a default.
    """
    last = _run_in_clean_subprocess(
        plugin_dir,
        """
        import contextlib, io
        from ml_models.plugin_loader import (
            UnknownOutputContractError,
            get_output_type,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                get_output_type("c2_name_that_is_not_in_the_plugin_dir")
                outcome = "RETURNED-A-DEFAULT"
            except UnknownOutputContractError:
                outcome = "RAISED"
        print("RESULT", outcome)
        """,
    )
    assert last == "RESULT RAISED"
