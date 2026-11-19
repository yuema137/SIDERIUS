"""``nodes.proposal_helpers.load_model_source`` — plugin source lookup.

arXiv P1: the agent-plugin candidates resolve against the generated-library
models dir FIRST, then the legacy checkout ``agent_generated/models``
(read-only compatibility). The workspace ``plugins/iter_*`` tree remains the
primary source at the CALLER (exploration-mode resolver); this function is
the global-library fallback the proposer's source-excerpt block leans on.
"""

from __future__ import annotations

import pytest

from nodes import proposal_helpers
from nodes.proposal_helpers import load_model_source


@pytest.fixture
def library_and_legacy(tmp_path, monkeypatch):
    """Pin the resolved library env AND relocate the legacy checkout root to
    tmp (matrix F: seeded fake legacy artifacts, never the real checkout).
    The installed built-in source stays independent of this legacy root;
    these tests target plugin candidates that precede it."""
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))
    monkeypatch.setattr(proposal_helpers, "_SIDERIUS_ROOT", str(tmp_path / "fake_root"))
    lib_models = tmp_path / "lib" / "models"
    lib_models.mkdir(parents=True)
    legacy_models = tmp_path / "fake_root" / "agent_generated" / "models"
    legacy_models.mkdir(parents=True)
    return lib_models, legacy_models


class TestLoadModelSourceLibraryLookup:
    def test_resolved_library_plugin_source_is_found(self, library_and_legacy):
        """Defect caught: the source-excerpt fallback never learning the
        resolved library — a model promoted post-migration would render NO
        source excerpt in the proposer prompt even though its plugin is
        loadable, because the only global dir searched was the checkout."""
        lib_models, _ = library_and_legacy
        (lib_models / "promoted_model.py").write_text("# promoted plugin source\n")
        assert (
            load_model_source("promoted_model", baseline_isolation=False)
            == "# promoted plugin source\n"
        )

    def test_legacy_checkout_plugin_source_still_found(self, library_and_legacy):
        """Matrix F — compatibility READ. Defect caught: dropping the legacy
        candidates, which would blank the source excerpt for every model
        promoted before the migration."""
        _, legacy_models = library_and_legacy
        (legacy_models / "old_model.py").write_text("# legacy plugin source\n")
        assert (
            load_model_source("old_model", baseline_isolation=False) == "# legacy plugin source\n"
        )

    def test_resolved_library_wins_over_legacy_same_name(self, library_and_legacy):
        """Defect caught: candidate ordering flipped — a stale pre-migration
        copy would permanently shadow the promoted source in the prompt."""
        lib_models, legacy_models = library_and_legacy
        (lib_models / "shadowed_model.py").write_text("# resolved copy\n")
        (legacy_models / "shadowed_model.py").write_text("# legacy copy\n")
        assert load_model_source("shadowed_model", baseline_isolation=False) == "# resolved copy\n"


class TestBaselineIsolationExcludesBundledSource:
    """#1541: under baseline isolation no bundled built-in source leaves the loader."""

    @pytest.mark.parametrize(
        "model_type", ["fcnet", "gated_fno", "punet", "rnn", "transformer", "wavenet"]
    )
    def test_bundled_source_is_withheld_only_under_isolation(self, model_type):
        """Fails if an isolated run can read a shipped baseline's source (the
        models_sandbox fallback), or if a non-isolated run loses it."""
        assert load_model_source(model_type, baseline_isolation=False)
        assert load_model_source(model_type, baseline_isolation=True) is None

    def test_bundled_name_is_withheld_even_if_a_plugin_shadows_it(self, library_and_legacy):
        """Fail-closed: isolation excludes the bundled NAME before any lookup,
        so a plugin file named like a baseline cannot reintroduce it."""
        lib_models, _ = library_and_legacy
        (lib_models / "wavenet.py").write_text("# plugin named like a baseline\n")
        assert load_model_source("wavenet", baseline_isolation=True) is None

    def test_generated_plugins_still_load_under_isolation(self, library_and_legacy):
        lib_models, _ = library_and_legacy
        (lib_models / "promoted_model.py").write_text("# promoted plugin source\n")
        assert load_model_source("promoted_model", baseline_isolation=True) == (
            "# promoted plugin source\n"
        )

    def test_candidate_enrichment_withholds_bundled_source_under_isolation(self):
        """The proposer's candidate source block uses the same owner."""
        from nodes.proposal_helpers import enrich_candidates_with_source

        isolated = enrich_candidates_with_source([{"model_type": "punet"}], baseline_isolation=True)
        assert isolated[0]["source_code"] is None
        plain = enrich_candidates_with_source([{"model_type": "punet"}], baseline_isolation=False)
        assert "class PositionalUNet" in plain[0]["source_code"]
