"""arXiv U3 (#260) — the bundled-baseline authority and the loader's refusal.

What only these tests catch:

* the ONE bundled set drifting: ``BUNDLED_MODEL_TYPES`` is compared against
  the six shipped baselines, hardcoded — a new directory quietly landing
  under ``ml_models/`` (or a baseline being dropped) changes the refusal
  surface and must be a deliberate act;
* the loader refusing / not refusing the wrong candidate under isolation:
  a bundled description resolving under isolation is R6's confound; a
  workspace PLUGIN description failing to resolve under isolation would
  break every isolated chain's second iteration.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ml_models.model_descriptions import (
    BUNDLED_MODEL_TYPES,
    get_model_description,
    is_bundled_model_type,
)

_REPO = Path(__file__).resolve().parents[3]

SHIPPED_SIX = frozenset({"fcnet", "gated_fno", "punet", "rnn", "transformer", "wavenet"})


class TestBundledAuthority:
    def test_the_bundled_set_is_exactly_the_six_shipped_baselines(self):
        assert BUNDLED_MODEL_TYPES == SHIPPED_SIX

    def test_the_predicate_answers_from_the_same_set(self):
        assert is_bundled_model_type("wavenet")
        assert not is_bundled_model_type("stub_arch_001_model")


class TestLoaderUnderIsolation:
    def test_non_isolated_loads_the_bundled_description(self):
        text = get_model_description("punet")
        assert text.startswith("# PUNet")

    def test_isolation_refuses_the_bundled_description_naming_the_path(self):
        with pytest.raises(FileNotFoundError) as exc:
            get_model_description("punet", baseline_isolation=True)
        msg = str(exc.value)
        assert "baseline_isolation" in msg
        assert "src/ml_models/punet/description.md" in msg.replace("\\", "/")

    def test_isolation_still_resolves_a_workspace_plugin_description(self, tmp_path, monkeypatch):
        plugin_dir = tmp_path / "plugins" / "iter_001" / "my_plugin_tcn"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "description.md").write_text("# my_plugin_tcn\nplugin body\n")
        monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(tmp_path))
        text = get_model_description("my_plugin_tcn", baseline_isolation=True)
        assert text == "# my_plugin_tcn\nplugin body\n"


class TestLoaderCallSitesForwardTheFlag:
    """A production loader call that drops ``baseline_isolation=`` silently
    reopens the bundled path under isolation — invisible to every
    behavioural test whose upstream refusals keep bundled types away."""

    @pytest.mark.parametrize(
        "rel",
        [
            "src/nodes/result_interpretation_agent/result_interpretation_agent.py",
            "src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
        ],
    )
    def test_every_production_loader_call_forwards_the_flag(self, rel):
        src = (_REPO / rel).read_text(encoding="utf-8")
        calls = [m.end() for m in re.finditer(r"get_model_description\(", src)]
        calls = [c for c in calls if "def get_model_description" not in src[c - 40 : c]]
        assert calls, f"{rel}: no loader call found"
        for end in calls:
            assert "baseline_isolation=" in src[end : end + 200], (
                f"{rel}: a get_model_description call does not forward baseline_isolation"
            )
