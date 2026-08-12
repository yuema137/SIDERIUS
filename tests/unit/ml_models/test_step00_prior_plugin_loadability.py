"""Step-00 PLG-1 — a REAL prior generated plugin loads through the full chain.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.3 / §15.1 (roadmap step 03 A-surface: "PRIOR ON-DISK GENERATED
PLUGINS remain loadable").

The fixture is a byte-identical copy of a real campaign-generated plugin
(``compact_wavenet_ce_coldstart_v1`` from the PR-G Gate run of
2026-08-10), stored as ``.py.txt`` DATA (review F5: a ``.py`` copy under
``tests/`` enters ruff's scope and reformatting would destroy the
byte-identity that IS the baseline). The test stages it to ``tmp_path``
under its real name and drives the REAL loader chain
(``extend_registries`` → registry population → config class → forward
contract) — before Step 00 no test loaded a committed real generated
plugin from disk.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import torch

from ml_models.plugin_loader import extend_registries

FIXTURE = Path(__file__).parent / "fixtures" / "compact_wavenet_ce_coldstart_v1.py.txt"
PLUGIN_NAME = "compact_wavenet_ce_coldstart_v1"


class TestPLG1PriorPluginLoadability:
    def test_real_generated_plugin_loads_and_honors_forward_contract(self, tmp_path, monkeypatch):
        staged = tmp_path / f"{PLUGIN_NAME}.py"
        shutil.copy(FIXTURE, staged)
        assert staged.read_bytes() == FIXTURE.read_bytes(), "staging must be byte-identical"

        # The loader resolves its scan dirs from SIDERIUS_PLUGIN_DIRS —
        # the same env transport production uses (core/subprocess_env.py).
        monkeypatch.setenv("SIDERIUS_PLUGIN_DIRS", str(tmp_path))
        model_registry: dict = {}
        config_registry: dict = {}
        loaded = extend_registries(model_registry, config_registry)

        assert loaded == [PLUGIN_NAME]
        assert PLUGIN_NAME in model_registry and PLUGIN_NAME in config_registry

        config_cls = config_registry[PLUGIN_NAME]
        model_cls = model_registry[PLUGIN_NAME]
        model = model_cls(config_cls())
        model.eval()
        with torch.no_grad():
            x = torch.zeros(1, 64, dtype=torch.int64)
            y = model(x)
        # The frozen plugin forward contract: [B, T] int -> [B, 256, T] float.
        assert y.shape == (1, 256, 64)
        assert y.dtype == torch.float32
