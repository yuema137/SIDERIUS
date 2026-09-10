"""The shipped Health configuration contains framework dispositions only.

Scientific configuration and historical-byte oracles belong to the external
task repository. This static test does not claim composed-config parity;
composition/cache behavior has its own executable contract tests.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
HEALTH_YAML = REPO_ROOT / "configs" / "health_checks.yaml"


class TestHC1ShippedHealthConfig:
    """Keep the framework file free of executable task treatment."""

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
        assert "tidmad" not in str(raw).lower()
