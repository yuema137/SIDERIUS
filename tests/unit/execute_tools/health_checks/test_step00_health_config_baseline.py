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

import json
from pathlib import Path

import pytest
import yaml

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
    """Step 08b C5 split this into the two claims it was making at once.

    The golden was re-captured, and a re-captured baseline proves nothing on
    its own — so the claim it USED to carry (the shipped values are these) is
    now asserted separately against a capture taken BEFORE the migration.
    """

    def test_the_shipped_framework_file_is_policy_only(self):
        """The forbidden failure mode, on the file itself.

        The framework config must never become `tidmad: … / pets: …`
        (parent §6a.4). After C5 it declares dispositions and nothing else —
        no roster, no threshold, no peek set, no task identity.
        """
        raw = yaml.safe_load(HEALTH_YAML.read_text())

        assert set(raw) == {"health_policy"}
        assert set(raw["health_policy"]) == {"blocking", "recording"}
        # Inspects the PARSED document, not the file text: the comments
        # explain the rule and must be free to name the task they are about.
        assert "tidmad" not in json.dumps(raw).lower()

    def test_resolved_shipped_config_deep_equal(self):
        """The COMPOSED config — framework policy + the task's roster.

        "Resolved" now means composed, which is what a run actually
        evaluates. The values in this golden are proven equal to the
        pre-migration ones by
        `test_composition.TestTidmadOwnershipMigrationPreservesExecutedSemantics`,
        which compares field-by-field against a golden captured at the C4
        head — that is what stops this from being a baseline re-pointed at
        whatever the code now produces.
        """
        cfg = load_health_gates_config(str(HEALTH_YAML))
        assert_json_golden(
            cfg.model_dump(mode="json"),
            GOLDENS / "hc1_health_checks_resolved.json",
            surface="HC-1 resolved shipped health-checks config",
        )
