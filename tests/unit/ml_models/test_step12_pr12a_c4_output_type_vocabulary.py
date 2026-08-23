"""Step 12 / PR-12a — C4: issue #234, output-type fail-open closed.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C4 (D-12a-3).

#234 is the canonical GRADUATION FALSIFIER: an external package's model plugin
with a novel or malformed output declaration must refuse, never silently train
as a classifier. Two defects, one commit:

    fail-open   an unrecognised `PLUGIN_OUTPUT_TYPE` was rewritten to
                "classifier" with a warning, so a metadata defect became
                wrong science with nothing downstream able to tell
    3-vs-2      the loader accepted {classifier, regressor, hybrid} while the
                validator accepted {classifier, regressor} — a plugin legal at
                LOAD time was refused at VALIDATION time

THE TWO SETS ARE GENUINELY DIFFERENT, which is why one constant cannot serve
both. `OUTPUT_TYPE_VOCABULARY` is what the framework can INTERPRET and includes
the legacy builtin adapter value `hybrid`; `PLUGIN_LEGAL_OUTPUT_TYPES` is what
a PLUGIN may declare. `hybrid` reaches the registry through the builtin table
(`fcnet`), never through a plugin file, and real consumers branch on it — so it
stays in the vocabulary and out of the plugin-legal subset.

EVIDENCE FOR THE SUBSET (audited, not asserted): across the 109 generated
plugins on record the distribution is 106 `classifier` + 3 `regressor` and
ZERO `hybrid`; the implementor template emits one of the two; the validator has
enforced exactly this pair since V21 PR A.

ON OMISSION — decided by evidence, recorded either way (design §5-C4 item 6):
an OMITTED declaration keeps its legacy default. The validator's matching
`_DEFAULT_OUTPUT_TYPE` is a legacy-read path with its OWN reachability test
guarding it against silent removal, so refusing omission in the loader would
recreate exactly the loader/validator divergence this commit removes. #234 is
about a declaration that is PRESENT and unrecognised; that is what fails closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ml_models.plugin_loader import (
    OUTPUT_TYPE_VOCABULARY,
    PLUGIN_LEGAL_OUTPUT_TYPES,
    UnknownOutputContractError,
    _load_plugin,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

_PLUGIN = '''\
"""A minimal model plugin declaring output type {declared!r}."""


class Cfg:
    pass


class Model:
    pass


PLUGIN_MODEL_TYPE = "{model_type}"
PLUGIN_CONFIG_CLASS = Cfg
PLUGIN_MODEL_CLASS = Model
{line}
'''


def _write_plugin(directory: Path, declared: str | None, model_type: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    line = "" if declared is None else f"PLUGIN_OUTPUT_TYPE = {declared!r}"
    path = directory / f"{model_type}.py"
    path.write_text(
        _PLUGIN.format(declared=declared, model_type=model_type, line=line), encoding="utf-8"
    )
    return str(path)


class TestTheVocabularyIsOneAuthority:
    def test_the_validator_reads_the_SAME_object(self):
        """Not "the same value" — the same object. A second literal that
        happened to agree today is exactly what produced the 3-vs-2 split."""
        from nodes.ml_code_validator_agent.ml_code_validator_agent import _LEGAL_OUTPUT_TYPES

        assert _LEGAL_OUTPUT_TYPES is PLUGIN_LEGAL_OUTPUT_TYPES

    def test_the_validator_BINDS_the_authority_rather_than_re_declaring_it(self):
        """The mutation-proof form of the row above: planting
        ``_LEGAL_OUTPUT_TYPES = ("classifier", "regressor")`` back into the
        validator turns this RED even though the value would still be equal —
        agreement by coincidence is exactly what has to be impossible.

        Targeted at the DECLARATION, not at any occurrence of the literal. The
        validator legitimately iterates ``("classifier", "regressor")``
        elsewhere to render its two prompt SHAPE tokens
        (``{CLASSIFIER_SHAPE}`` / ``{REGRESSOR_SHAPE}``); that loop is coupled
        to those two template names, not to this vocabulary, and binding it to
        the set would create a silent mismatch the day the set grew.
        """
        import ast

        validator = ast.parse(
            (
                REPO_ROOT / "nodes" / "ml_code_validator_agent" / "ml_code_validator_agent.py"
            ).read_text(encoding="utf-8")
        )
        bindings = [
            node.value
            for node in ast.walk(validator)
            if isinstance(node, ast.AnnAssign | ast.Assign)
            for target in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
            if isinstance(target, ast.Name) and target.id == "_LEGAL_OUTPUT_TYPES"
        ]
        assert len(bindings) == 1
        assert isinstance(bindings[0], ast.Name), (
            "the validator must BIND the imported authority; a tuple literal "
            "here is a second declaration, which is how the 3-vs-2 split began"
        )
        assert bindings[0].id == "PLUGIN_LEGAL_OUTPUT_TYPES"

    def test_the_loader_declares_each_set_exactly_once(self):
        loader = (REPO_ROOT / "ml_models" / "plugin_loader.py").read_text(encoding="utf-8")
        assert loader.count('("classifier", "regressor")') == 1
        assert loader.count('("classifier", "regressor", "hybrid")') == 1

    def test_the_plugin_legal_set_is_a_strict_subset_of_the_vocabulary(self):
        assert set(PLUGIN_LEGAL_OUTPUT_TYPES) < set(OUTPUT_TYPE_VOCABULARY)
        assert set(OUTPUT_TYPE_VOCABULARY) - set(PLUGIN_LEGAL_OUTPUT_TYPES) == {"hybrid"}


class TestAnUnrecognisedDeclarationRefuses:
    """The #234 fix. HOW IT FAILS IF THE BEHAVIOUR BREAKS: restore the coercion
    and the first row loads a segmentation model as a 256-class classifier."""

    @pytest.mark.parametrize("declared", ["segmentation_masks", "hybrid", "", "Classifier"])
    def test_it_is_refused_and_never_coerced(self, declared, tmp_path, capsys):
        loaded = _load_plugin(_write_plugin(tmp_path, declared, "c4_probe"))

        assert loaded is None
        printed = capsys.readouterr().out
        assert "is not a legal plugin output contract" in printed
        assert repr(declared) in printed

    def test_a_legal_declaration_still_loads(self, tmp_path):
        """The contrast case: the refusal must not be "refuse everything"."""
        for declared in PLUGIN_LEGAL_OUTPUT_TYPES:
            loaded = _load_plugin(_write_plugin(tmp_path / declared, declared, "c4_ok"))
            assert loaded is not None
            assert loaded["output_type"] == declared

    def test_an_omitted_declaration_keeps_its_legacy_default(self, tmp_path):
        """The recorded evidence decision (module docstring). Changing this is
        a contract change, not a tidy-up: the validator's twin default has a
        dedicated reachability test standing against its silent removal."""
        loaded = _load_plugin(_write_plugin(tmp_path, None, "c4_legacy"))
        assert loaded is not None
        assert loaded["output_type"] == "classifier"


class TestHybridStaysLoadBearingForBuiltins:
    def test_fcnet_is_still_hybrid(self):
        from ml_models.models_sandbox import BUILTIN_OUTPUT_TYPES

        assert BUILTIN_OUTPUT_TYPES["fcnet"] == "hybrid"

    def test_get_output_type_still_answers_hybrid_for_it(self):
        from ml_models.plugin_loader import get_output_type

        assert get_output_type("fcnet") == "hybrid"

    def test_a_real_consumer_still_branches_on_it(self):
        """Reachability for the reason `hybrid` stays in the vocabulary: it is
        not decoration, it routes regression in the inference child."""
        source = (REPO_ROOT / "execute_tools" / "inference_single.py").read_text(encoding="utf-8")
        assert 'output_type == "hybrid"' in source


class TestARequiredMalformedPluginFailsTheRunClosed:
    """The operator's end-to-end reachability addition (design §0.1 item +).

    A loader-level named skip is only half a guarantee. What must be true is
    that a run which EXPLICITLY REQUIRES the malformed plugin — its
    `model_type` IS the run's selected model — cannot silently fall back to
    another model and succeed.
    """

    MODEL_TYPE = "c4_required_external_model"

    def _scan(self, tmp_path, monkeypatch, declared):
        from ml_models.plugin_loader import extend_registries

        plugin_dir = tmp_path / "plugins"
        _write_plugin(plugin_dir, declared, self.MODEL_TYPE)
        monkeypatch.setenv("SIDERIUS_PLUGIN_DIRS", str(plugin_dir))

        model_registry: dict = {}
        config_registry: dict = {}
        loaded = extend_registries(model_registry, config_registry)
        return loaded, model_registry, config_registry

    def test_the_malformed_plugin_never_enters_any_registry(self, tmp_path, monkeypatch):
        loaded, model_registry, config_registry = self._scan(
            tmp_path, monkeypatch, "segmentation_masks"
        )

        assert loaded == []
        assert self.MODEL_TYPE not in model_registry
        assert self.MODEL_TYPE not in config_registry
        from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY

        assert self.MODEL_TYPE not in PLUGIN_OUTPUT_TYPE_REGISTRY

    def test_resolving_the_required_model_then_FAILS_CLOSED_naming_it(self, tmp_path, monkeypatch):
        """No fallback, no default, and the error names the model the run
        asked for — so the operator learns which plugin was refused rather
        than watching a different model train."""
        _loaded, model_registry, _config = self._scan(tmp_path, monkeypatch, "segmentation_masks")

        from ml_models.plugin_loader import get_output_type

        with pytest.raises(UnknownOutputContractError) as excinfo:
            get_output_type(self.MODEL_TYPE)
        assert self.MODEL_TYPE in str(excinfo.value)

        with pytest.raises(KeyError):
            model_registry[self.MODEL_TYPE]

    def test_no_OTHER_model_was_substituted_for_it(self, tmp_path, monkeypatch):
        """The 'silent fallback' half, stated positively: the scan of a
        directory holding only the malformed plugin registers NOTHING. A run
        cannot end up training some other architecture under this name."""
        _loaded, model_registry, config_registry = self._scan(
            tmp_path, monkeypatch, "segmentation_masks"
        )
        assert model_registry == {}
        assert config_registry == {}

    def test_the_same_plugin_declared_legally_DOES_register(self, tmp_path, monkeypatch):
        """Anti-vacuity: the three rows above would all pass if the harness
        simply never loaded anything."""
        loaded, model_registry, config_registry = self._scan(tmp_path, monkeypatch, "regressor")

        assert loaded == [self.MODEL_TYPE]
        assert self.MODEL_TYPE in model_registry
        assert self.MODEL_TYPE in config_registry
