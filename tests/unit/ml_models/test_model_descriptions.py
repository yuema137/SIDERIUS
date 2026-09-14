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


def test_composed_policy_excludes_packaged_and_allows_authorized_absence(monkeypatch):
    """A composed run must not turn a bundled-only name into task prose."""
    monkeypatch.delenv("SIDERIUS_CHAIN_WORKSPACE", raising=False)
    assert (
        model_descriptions.get_model_description(
            "punet", source_policy=model_descriptions.DescriptionSourcePolicy.COMPOSED
        )
        is None
    )


def test_composed_policy_excludes_legacy_checkout_description_without_workspace(
    tmp_path, monkeypatch
):
    """Composed lookup must not consume checkout-global historical prose.

    This is the missing binding boundary: with no workspace binding, a legacy
    ``agent_generated`` file is present, but it is not owned by the composed
    task and must resolve as authorized absence rather than task input.
    """
    legacy = tmp_path / "legacy_models" / "punet"
    legacy.mkdir(parents=True)
    (legacy / "description.md").write_text("# stale task prose\n", encoding="utf-8")
    monkeypatch.setattr(
        model_descriptions, "_PLUGIN_DESCRIPTIONS_DIR", str(tmp_path / "legacy_models")
    )
    monkeypatch.delenv("SIDERIUS_CHAIN_WORKSPACE", raising=False)
    monkeypatch.delenv("SIDERIUS_GENERATED_LIBRARY_DIR", raising=False)

    assert (
        model_descriptions.get_model_description(
            "punet", source_policy=model_descriptions.DescriptionSourcePolicy.COMPOSED
        )
        is None
    )


def test_composed_policy_resolves_declared_pack_description(tmp_path, monkeypatch):
    """The declared task-pack root remains an authorized composed source."""
    root = tmp_path / "models" / "punet"
    root.mkdir(parents=True)
    body = "# task-owned architecture\n"
    (root / "description.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(
        model_descriptions, "_declared_pack_candidates", lambda _: [str(root / "description.md")]
    )
    assert (
        model_descriptions.get_model_description(
            "punet", source_policy=model_descriptions.DescriptionSourcePolicy.COMPOSED
        )
        == body
    )


def test_composed_loader_prefers_workspace_over_declared_pack(tmp_path, monkeypatch):
    """A staged workspace description outranks the pack's fallback copy.

    This catches the real contamination boundary: if candidate ordering is
    accidentally changed, a stale pack description can replace the prose for
    the model actually staged into this run.
    """
    workspace = tmp_path / "workspace"
    staged = workspace / "plugins" / "iter_002" / "shared_model"
    staged.mkdir(parents=True)
    (staged / "description.md").write_text("# workspace description\n", encoding="utf-8")
    monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(workspace))

    pack = tmp_path / "pack" / "shared_model"
    pack.mkdir(parents=True)
    (pack / "description.md").write_text("# pack description\n", encoding="utf-8")
    monkeypatch.setattr(
        model_descriptions, "_declared_pack_candidates", lambda _: [str(pack / "description.md")]
    )

    assert (
        model_descriptions.get_model_description(
            "shared_model", source_policy=model_descriptions.DescriptionSourcePolicy.COMPOSED
        )
        == "# workspace description\n"
    )


def test_composed_loader_prefers_bound_generated_library_over_declared_pack(tmp_path, monkeypatch):
    """A workspace-bound promoted description outranks the declared pack."""
    workspace = tmp_path / "workspace"
    generated = workspace / "generated_library" / "models" / "shared_model"
    generated.mkdir(parents=True)
    (generated / "description.md").write_text("# promoted workspace model\n", encoding="utf-8")
    monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(workspace))
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(workspace / "generated_library"))

    pack = tmp_path / "pack" / "shared_model"
    pack.mkdir(parents=True)
    (pack / "description.md").write_text("# pack fallback\n", encoding="utf-8")
    monkeypatch.setattr(
        model_descriptions, "_declared_pack_candidates", lambda _: [str(pack / "description.md")]
    )

    assert (
        model_descriptions.get_model_description(
            "shared_model", source_policy=model_descriptions.DescriptionSourcePolicy.COMPOSED
        )
        == "# promoted workspace model\n"
    )


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
