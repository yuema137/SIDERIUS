"""Unit tests for ml_models.model_descriptions.get_model_description.

Covers the three search tiers, with emphasis on the chain-workspace
plugin tree resolution that broke in Gate 2 Run-4 — the regex
``^iter_\\d{3}$`` filter rejected the test's ``stage2_iter_001`` run
directory, so plugin descriptions were never found and iter 2's
interpretation agent crashed at the iter-1 → iter-2 boundary.
"""

import os
import textwrap
from pathlib import Path

import pytest

from ml_models import model_descriptions


@pytest.fixture
def chain_workspace(tmp_path: Path, monkeypatch) -> Path:
    """Create a fake chain workspace and point the env var at it."""
    workspace = tmp_path / "exploration_smoke"
    (workspace / "plugins").mkdir(parents=True)
    monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(workspace))
    return workspace


def _write_plugin_description(workspace: Path, run_name: str, model_type: str, body: str) -> Path:
    dest = workspace / "plugins" / run_name / model_type / "description.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    return dest


def test_finds_builtin_model_description():
    text = model_descriptions.get_model_description("punet")
    assert text.strip(), "built-in punet description should not be empty"


def test_finds_chain_plugin_with_run_scoped_dirname(chain_workspace):
    """Gate 2 Run-4 regression guard: run_name like ``stage2_iter_001``
    that doesn't match the legacy ``iter_NNN`` regex must still be
    discoverable under the chain plugin tree."""
    body = "# positional_gated_tcn\nGate 2 plugin description.\n"
    _write_plugin_description(chain_workspace, "stage2_iter_001", "positional_gated_tcn", body)
    assert model_descriptions.get_model_description("positional_gated_tcn") == body


def test_finds_chain_plugin_with_iter_dirname(chain_workspace):
    """Production V9 chain naming (``iter_001``) must still resolve."""
    body = "# spectral_skip_cyclic_tcn\nV9 chain plugin description.\n"
    _write_plugin_description(chain_workspace, "iter_002", "spectral_skip_cyclic_tcn", body)
    assert model_descriptions.get_model_description("spectral_skip_cyclic_tcn") == body


def test_newest_run_wins_when_model_registered_in_multiple_runs(chain_workspace):
    """If a model is re-registered across runs, the highest-sorted dir
    name wins — this lets a later iter override an earlier definition."""
    _write_plugin_description(chain_workspace, "iter_001", "shared_model", "old description\n")
    _write_plugin_description(chain_workspace, "iter_005", "shared_model", "new description\n")
    assert model_descriptions.get_model_description("shared_model") == "new description\n"


def test_missing_model_raises_with_searched_paths(chain_workspace):
    with pytest.raises(FileNotFoundError) as exc:
        model_descriptions.get_model_description("nonexistent_arch_xyz")
    msg = str(exc.value)
    assert "nonexistent_arch_xyz" in msg
    assert "Searched" in msg


def test_chain_lookup_is_noop_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("SIDERIUS_CHAIN_WORKSPACE", raising=False)
    assert model_descriptions._chain_workspace_candidates("anything") == []


def test_chain_lookup_skips_run_dir_without_matching_model(chain_workspace):
    """A subdir under plugins/ with no ``{model_type}/description.md``
    must not produce a candidate — robustness against partial registrations."""
    other_run = chain_workspace / "plugins" / "stage2_iter_001" / "other_model"
    other_run.mkdir(parents=True)
    (other_run / "description.md").write_text("unrelated\n", encoding="utf-8")
    assert model_descriptions._chain_workspace_candidates("missing_model") == []


def test_resolved_library_description_wins_over_legacy_and_workspace(tmp_path, monkeypatch):
    """arXiv P1 — the resolved generated-library description slots between
    the bundled built-ins and the legacy checkout dir. Defect caught either
    way the chain breaks: the resolved-library candidate missing entirely
    (post-migration promoted descriptions unreachable — prompts would fall
    back to stale legacy/workspace copies or raise), or ordered after the
    legacy candidate (a pre-migration description permanently shadowing the
    promoted one)."""
    from ml_models import model_descriptions

    lib_models = tmp_path / "lib" / "models"
    (lib_models / "promo_desc_model").mkdir(parents=True)
    (lib_models / "promo_desc_model" / "description.md").write_text("# resolved library copy\n")
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))

    legacy = tmp_path / "legacy_models"
    (legacy / "promo_desc_model").mkdir(parents=True)
    (legacy / "promo_desc_model" / "description.md").write_text("# legacy checkout copy\n")
    monkeypatch.setattr(model_descriptions, "_PLUGIN_DESCRIPTIONS_DIR", str(legacy))
    monkeypatch.delenv("SIDERIUS_CHAIN_WORKSPACE", raising=False)

    assert (
        model_descriptions.get_model_description("promo_desc_model") == "# resolved library copy\n"
    )


def test_legacy_checkout_description_still_resolves(tmp_path, monkeypatch):
    """arXiv P1 compatibility READ (matrix F): a description promoted into
    the checkout before the migration keeps resolving when the resolved
    library has none. Defect caught: dropping the legacy candidate — every
    pre-migration plugin description would raise FileNotFoundError in the
    interpretation/proposal prompts."""
    from ml_models import model_descriptions

    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib_empty"))
    legacy = tmp_path / "legacy_models"
    (legacy / "old_plugin_model").mkdir(parents=True)
    (legacy / "old_plugin_model" / "description.md").write_text("# legacy checkout copy\n")
    monkeypatch.setattr(model_descriptions, "_PLUGIN_DESCRIPTIONS_DIR", str(legacy))
    monkeypatch.delenv("SIDERIUS_CHAIN_WORKSPACE", raising=False)

    assert (
        model_descriptions.get_model_description("old_plugin_model") == "# legacy checkout copy\n"
    )
