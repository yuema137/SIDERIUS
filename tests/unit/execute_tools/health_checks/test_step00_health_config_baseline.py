"""Step-00 HC-1 — shipped health-checks config baseline.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.2 / §15.1 (roadmap step 08 A-surface).

Deep-equal (Type 2) of ``load_health_gates_config()`` over the SHIPPED
``configs/health_checks.yaml``. Before Step 00 only the LEGACY
(gate_role-stripped) body sha256s were pinned; the CURRENT resolved config
body was pinned nowhere. Values (thresholds, peek triplet, ordering) are
MIGRATION PARITY — TIDMAD-empirical task semantics that roadmap step 08
moves into task health config; the load/resolve MECHANISM is a required
surface.

Hazards honored (design §13.2, review F9): the loader's default path is
cwd-relative and the result is process-cached — this test passes an
EXPLICIT absolute path and clears the cache on both sides.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from execute_tools.health_checks.config import (
    clear_health_gates_config_cache,
    load_health_gates_config,
)
from tests.helpers.golden import assert_json_golden

REPO_ROOT = Path(__file__).resolve().parents[4]
HEALTH_YAML = REPO_ROOT / "configs" / "health_checks.yaml"
GOLDENS = Path(__file__).parent / "goldens"


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_health_gates_config_cache()
    yield
    clear_health_gates_config_cache()


class TestHC1ShippedHealthConfig:
    def test_resolved_shipped_config_deep_equal(self):
        cfg = load_health_gates_config(str(HEALTH_YAML))
        assert_json_golden(
            cfg.model_dump(mode="json"),
            GOLDENS / "hc1_health_checks_resolved.json",
            surface="HC-1 resolved shipped health-checks config",
        )
