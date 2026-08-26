"""Lane E / F11 — an out-of-tree pack can ship its model's description.

**The defect.** ``get_model_description`` searched four roots, all inside the
checkout or the generated library. A model plugin declared by the manifest's
``model_plugins:`` section had nowhere to put a ``description.md``: the only
writable candidates were ``<checkout>/ml_models/...`` and
``<checkout>/agent_generated/models/...``, so supplying one meant writing into
the framework's own tree — exactly what the package contract exists to
prevent.

The failure was SILENT. The tuner's read is non-fatal despite the message
saying *"must"*, so every out-of-tree task simply ran with a thinner planner
prompt, forever, with no error to notice.

**The fix adds no declaration surface.** ``model_plugins:`` already declares
where a pack's models live; the description search now reads those same roots
through ``active_run_model_plugin_roots()`` — the same ``active_*`` accessor
the subprocess transport uses — and applies the layout every other candidate
already uses.
"""

from __future__ import annotations

import pytest


def _binding(*roots: str):
    """A minimal binding declaring ``roots``.

    ``required_model_types`` and ``plugins`` are empty because this suite
    exercises DESCRIPTION resolution only; the loading/provenance halves are
    owned by their own tests and asserting them here would couple this
    witness to an unrelated contract.
    """
    from ml_models.plugin_binding import RunModelPluginBinding

    return RunModelPluginBinding(roots=tuple(roots), required_model_types=(), plugins=())


@pytest.fixture
def pack(tmp_path):
    """An out-of-tree pack root holding one model's description."""
    root = tmp_path / "my_pack" / "plugins"
    (root / "packmodel").mkdir(parents=True)
    (root / "packmodel" / "description.md").write_text(
        "# packmodel\n\nA pack-declared architecture.\n", encoding="utf-8"
    )
    return root


class TestTheDeclaredRootIsSearched:
    def test_a_pack_description_resolves_when_the_run_declares_the_root(self, pack):
        """RED before the fix: FileNotFoundError, because none of the four
        candidate roots could ever be the pack."""
        from ml_models.model_descriptions import get_model_description
        from ml_models.plugin_binding import bind_run_model_plugins

        with bind_run_model_plugins(_binding(str(pack))):
            assert "A pack-declared architecture." in get_model_description("packmodel")

    def test_the_failure_message_names_the_declared_root(self, pack):
        """A miss must be diagnosable. If the pack root is searched but the
        file is absent, the operator has to see WHERE we looked — the
        original report's whole difficulty was a searched-path list that
        could not contain the answer."""
        from ml_models.model_descriptions import get_model_description
        from ml_models.plugin_binding import bind_run_model_plugins

        with bind_run_model_plugins(_binding(str(pack))):
            with pytest.raises(FileNotFoundError) as excinfo:
                get_model_description("absent_model")

        assert str(pack) in str(excinfo.value)


class TestLegacyResolutionIsUnchanged:
    """An un-composed run must behave byte-identically."""

    def test_no_binding_adds_no_candidates(self):
        from ml_models.model_descriptions import _declared_pack_candidates

        assert _declared_pack_candidates("anything") == []

    def test_a_builtin_still_resolves_with_no_binding(self):
        from ml_models.model_descriptions import BUNDLED_MODEL_TYPES, get_model_description

        model_type = sorted(BUNDLED_MODEL_TYPES)[0]
        assert get_model_description(model_type).strip()

    def test_an_unresolvable_model_still_raises_filenotfound(self):
        from ml_models.model_descriptions import get_model_description

        with pytest.raises(FileNotFoundError):
            get_model_description("no_such_model_type_anywhere")


class TestPrecedence:
    def test_a_pack_does_not_shadow_a_workspace_registration(self, pack, tmp_path, monkeypatch):
        """The workspace copy is what the run actually staged and promoted;
        a pack description must not override it. Pinning the ORDER, because
        'both resolve' would hide a silent swap of which prose reached the
        planner."""
        from ml_models.model_descriptions import get_model_description
        from ml_models.plugin_binding import bind_run_model_plugins

        workspace = tmp_path / "ws"
        staged = workspace / "plugins" / "iter_001" / "packmodel"
        staged.mkdir(parents=True)
        staged.joinpath("description.md").write_text("# staged copy\n", encoding="utf-8")
        monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(workspace))

        with bind_run_model_plugins(_binding(str(pack))):
            assert "staged copy" in get_model_description("packmodel")

    def test_baseline_isolation_refuses_the_bundled_FILE_not_the_name(self, pack, tmp_path):
        """What `baseline_isolation` actually guarantees — stated correctly.

        An earlier version of this test claimed the fifth root "cannot become
        a bypass" of arXiv U3 / #260. **That claim was false**, and the test
        could not detect it: its fixture shipped only `packmodel/`, so under
        isolation the pack had no file for a bundled model TYPE and the
        FileNotFoundError came from an unrelated absence. It passed for the
        wrong reason, and the only defect it could catch — deletion of the
        refusal — is already caught by
        `tests/unit/ml_models/test_arxiv_u3_bundled_isolation.py`.

        The real behaviour, verified by running it: with a pack root bound and
        `{root}/{bundled_type}/description.md` present, isolation returns THE
        PACK'S FILE. That is correct and deliberate. `baseline_isolation`
        refuses ONE candidate — the BUNDLED prose shipped under `ml_models/`,
        which is what #260 exists to keep out of an LLM-facing prompt. It has
        never refused candidates 2-4 (generated library, legacy checkout,
        chain workspace), and the pack root is symmetric with those: a pack's
        own prose about its own model is not shipped baseline prose, whatever
        the model happens to be called.

        So this pins the two halves separately: the bundled FILE stays
        unreachable, and a same-named pack file is reachable like any other
        non-bundled candidate.
        """
        from ml_models.model_descriptions import BUNDLED_MODEL_TYPES, get_model_description
        from ml_models.plugin_binding import bind_run_model_plugins

        model_type = sorted(BUNDLED_MODEL_TYPES)[0]
        bundled_text = get_model_description(model_type, baseline_isolation=False)

        # Nothing declared for this type anywhere -> isolation has nothing left.
        with bind_run_model_plugins(_binding(str(pack))):
            with pytest.raises(FileNotFoundError):
                get_model_description(model_type, baseline_isolation=True)

        # The pack DOES declare it -> resolved, and it is the pack's prose,
        # not the bundled prose.
        packed = tmp_path / "with_bundled_name" / "plugins"
        (packed / model_type).mkdir(parents=True)
        (packed / model_type / "description.md").write_text(
            "PACK PROSE, NOT THE SHIPPED BASELINE\n", encoding="utf-8"
        )
        with bind_run_model_plugins(_binding(str(packed))):
            got = get_model_description(model_type, baseline_isolation=True)

        assert got.strip() == "PACK PROSE, NOT THE SHIPPED BASELINE"
        assert got != bundled_text, "the BUNDLED file must still be unreachable"
