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
    Relocating ``_SIDERIUS_ROOT`` also moves the built-in models_sandbox
    candidate to a missing path, which is fine here — every test targets the
    plugin candidates that precede it."""
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
        assert load_model_source("promoted_model") == "# promoted plugin source\n"

    def test_legacy_checkout_plugin_source_still_found(self, library_and_legacy):
        """Matrix F — compatibility READ. Defect caught: dropping the legacy
        candidates, which would blank the source excerpt for every model
        promoted before the migration."""
        _, legacy_models = library_and_legacy
        (legacy_models / "old_model.py").write_text("# legacy plugin source\n")
        assert load_model_source("old_model") == "# legacy plugin source\n"

    def test_resolved_library_wins_over_legacy_same_name(self, library_and_legacy):
        """Defect caught: candidate ordering flipped — a stale pre-migration
        copy would permanently shadow the promoted source in the prompt."""
        lib_models, legacy_models = library_and_legacy
        (lib_models / "shadowed_model.py").write_text("# resolved copy\n")
        (legacy_models / "shadowed_model.py").write_text("# legacy copy\n")
        assert load_model_source("shadowed_model") == "# resolved copy\n"
