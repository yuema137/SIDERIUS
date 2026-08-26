"""Lane E / F10 + F11b — the plugin model-config contract, across every
shipped exemplar.

**The defect.** A plugin model config is a plain ``BaseModel`` and therefore
inherits nothing from ``ml_models/models_format_sandbox.py::BaseConfig`` —
including ``model_type``, which every BUILT-IN config has and which the
planner consequently emits in every plan it produces. Nothing documented that
obligation, and the three shipped reference plugins disagreed: pets and davis
declared ``model_type``, the quickstart did not and additionally set
``extra="forbid"``.

The quickstart is the exemplar the README and ``docs/guides/define-a-task.md``
point new users at, and its own README §8 says *"copy the pack's shape"*.
Doing that produced a config that rejected EVERY plan: six consecutive
attempts, run aborted at ``max_fail_rounds``, zero rounds trained.

**Attributed correctly, because the obvious reading is wrong.** That incident
was caused by ``extra="forbid"`` ALONE. The FRAMEWORK injects
``model_config["model_type"]`` into every plan (``planning.py``), and a config
forbidding extras rejects the injected key. The MISSING ``model_type`` is a
second, INDEPENDENT defect with a quieter failure mode: under the permissive
``extra`` default the injected key is silently dropped and the run dies a
layer later, in the trainer, on ``model_cfg.model_type``. Two defects, two
layers — pinned separately below.

**Why it survived review** — and this is the fact worth keeping. Both of the
quickstart's omissions were invisible IN the quickstart, because the defaults
they fell back to happen to be correct for it:

* omitting ``model_type`` is survivable only if nothing sends you a plan
  containing it — and the quickstart's README records that a scored tuner
  round had never been witnessed for it;
* omitting ``PLUGIN_OUTPUT_TYPE`` takes the ``"classifier"`` default
  (``ml_models/plugin_loader.py``), and the quickstart *is* a classifier.

They detonate only on the first copy into a task that is not shaped like the
quickstart — which is precisely what the exemplar exists to be used for
(F11b's regression pack was refused at admission for declaring a class
alphabet its task does not have).

**These tests are a CENSUS, not a quickstart fix.** Per CLAUDE.md: a rule that
spans models needs one test naming the concept and asserting across every
model that declares it. A test pinning only the quickstart would go green the
moment a fourth exemplar drifted the same way.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"


def _module_level_assignments(path: pathlib.Path) -> set[str]:
    """Names bound at MODULE level, by AST.

    Not a substring scan. The first version excluded loss plugins with
    ``"PLUGIN_LOSS_TYPE" not in text``, which excludes any file that MENTIONS
    the name — a docstring saying "its objective is supplied separately as a
    PLUGIN_LOSS_TYPE plugin" was enough to vanish from the census entirely.
    A model plugin could then violate every rule here and stay green. The
    docstring claimed exclusion "by what they DECLARE"; this is much closer
    to true.

    NOT fully true, and the gap is stated rather than implied: production
    keys on ``hasattr``, while this walks only ``Assign``/``AnnAssign`` with
    ``Name`` targets. ``from x import PLUGIN_LOSS_TYPE``, a conditional or
    try-wrapped binding, and a tuple-target assignment all bind the attribute
    in production and are invisible here. The only effect of a miss is to
    SHRINK the census — a file that binds the name in one of those forms is
    treated as a model plugin and held to more rules, never fewer — so the
    residue is bounded and non-silencing. No shipped plugin uses those forms.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def _model_plugin_paths() -> list[pathlib.Path]:
    """Every sanctioned pack MODEL plugin.

    Discovered, never listed: a hardcoded roster would silently exempt the
    next pack, which is the failure mode this census exists to prevent.
    Underscore-prefixed files are pack-internal (the directory scanners skip
    them); loss plugins declare ``PLUGIN_LOSS_TYPE`` and are a different
    contract, so they are excluded by what they declare rather than by name.
    """
    found = []
    for path in sorted(EXAMPLES.glob("*/plugins/*.py")):
        if path.name.startswith("_"):
            continue
        assigned = _module_level_assignments(path)
        if "PLUGIN_MODEL_TYPE" in assigned and "PLUGIN_LOSS_TYPE" not in assigned:
            found.append(path)
    return found


def _load(path: pathlib.Path):
    name = f"lane_e_f10_probe_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


PLUGINS = _model_plugin_paths()


def test_a_mention_is_not_a_declaration(tmp_path):
    """C1 — the exclusion must key on what a file DECLARES, not what it says.

    The first version excluded loss plugins with
    ``"PLUGIN_LOSS_TYPE" not in text``. A MODEL plugin whose docstring merely
    mentions the name — "its objective is supplied separately as a
    PLUGIN_LOSS_TYPE plugin" — vanished from the census entirely and could
    then violate every rule here while the suite stayed green. Token
    blindness, in the census written to close a producer/consumer gap.
    """
    mentions = tmp_path / "mentions.py"
    mentions.write_text(
        '"""Objective supplied separately as a PLUGIN_LOSS_TYPE plugin."""\n'
        'PLUGIN_MODEL_TYPE = "m"\n',
        encoding="utf-8",
    )
    declares = tmp_path / "declares.py"
    declares.write_text('PLUGIN_LOSS_TYPE = "l"\nPLUGIN_MODEL_TYPE = "m"\n', encoding="utf-8")

    assert _module_level_assignments(mentions) == {"PLUGIN_MODEL_TYPE"}
    assert "PLUGIN_LOSS_TYPE" in _module_level_assignments(declares)


def test_the_census_actually_found_the_shipped_exemplars():
    """A census whose file set is empty passes vacuously. Pin that it sees
    all three packs — the shape of census blindness that has bitten this
    repository before."""
    names = {p.parent.parent.name for p in PLUGINS}
    assert names == {"quickstart", "oxford_iiit_pet", "davis_future_prediction"}, names


@pytest.mark.parametrize("path", PLUGINS, ids=lambda p: p.parent.parent.name)
class TestEveryShippedModelPluginDeclaresTheContract:
    def test_the_config_declares_model_type(self, path):
        """RED for the quickstart before the fix.

        The planner emits ``model_type`` in every plan because every built-in
        config inherits it from ``BaseConfig``. A plugin config inherits
        nothing, so it must declare the field itself.
        """
        module = _load(path)
        config_cls = module.PLUGIN_CONFIG_CLASS
        assert "model_type" in config_cls.model_fields, (
            f"{path.relative_to(REPO_ROOT)}: a plugin config must declare "
            "'model_type' — the planner emits it in every plan, and a config "
            "that does not model it silently drops the framework-injected "
            "key and fails later in the trainer on model_cfg.model_type"
        )

    def test_a_production_shaped_payload_validates(self, path):
        """The behavioural form of the rule, with a payload that actually
        exercises the ``extra`` path.

        The first version passed only ``model_type`` and ``batch_size`` —
        both modelled by all three packs — so it never touched ``extra`` and
        its docstring's claim to test that path was false. ``num_classes`` is
        the real unmodelled key: ``apply_contract_cardinality``
        (``execute_tools/model_input_dtype.py``) injects it from the resolved
        Model-I/O contract, and none of the three packs declares it. Under
        ``extra="forbid"`` this construction raises, which is the failure the
        incident actually produced.
        """
        module = _load(path)
        payload = {
            "model_type": module.PLUGIN_MODEL_TYPE,
            "batch_size": 2,
            "num_classes": 2,
        }
        instance = module.PLUGIN_CONFIG_CLASS(**payload)
        assert instance.model_type == module.PLUGIN_MODEL_TYPE

    def test_output_type_is_declared_not_defaulted(self, path):
        """RED for the quickstart before the fix.

        ``PLUGIN_OUTPUT_TYPE`` is optional and defaults to ``"classifier"``.
        An exemplar that omits it teaches the omission, and the default is
        silently wrong for every regression task that copies it (F11b).
        """
        module = _load(path)
        # N1 — the SHARED vocabulary, not a third hand-written copy. The
        # loader's own comment records incident #234, in which exactly this
        # pair diverged between two hand-written copies.
        from ml_models.plugin_loader import PLUGIN_LEGAL_OUTPUT_TYPES

        declared = getattr(module, "PLUGIN_OUTPUT_TYPE", None)
        assert declared in PLUGIN_LEGAL_OUTPUT_TYPES, (
            f"{path.relative_to(REPO_ROOT)}: an exemplar must DECLARE "
            "PLUGIN_OUTPUT_TYPE rather than inherit the 'classifier' default "
            "— a pack copying it inherits a class alphabet it may not have"
        )

    def test_the_plugin_key_is_a_usable_identity(self, path):
        """The registry keys everything off this string."""
        module = _load(path)
        assert isinstance(module.PLUGIN_MODEL_TYPE, str) and module.PLUGIN_MODEL_TYPE.strip()


@pytest.mark.parametrize("path", PLUGINS, ids=lambda p: p.parent.parent.name)
def test_a_default_constructed_config_carries_the_packs_own_key(path):
    """The two independently-authored declarations of one pack's key agree.

    **What this does NOT claim.** The default is not reachable as a production
    failure: ``planning.py`` injects ``model_type`` into every plan and
    ``sandbox_executor`` overwrites it again, so a disagreeing default is
    overwritten before it can resolve anything. This is hygiene — two hand-
    authored copies of one string that must not drift — and it CAN go red,
    which is why it is worth keeping. It is not a guard against a live
    failure path, and saying otherwise would assert a defect nobody can hit.

    **Why this is a real cross-check and not self-reference.** Every pack
    declares the same string TWICE, independently — once as the module
    constant, once as a literal field default (pets ``:21``/``:25``, davis
    ``:23``/``:30``, quickstart likewise). Either can be edited without the
    other, so comparing them can fail. This is why the quickstart's default
    is a literal rather than ``Field(default=PLUGIN_MODEL_TYPE)``: the
    constant-reference form would collapse both sides onto one object and
    make this vacuous for that pack alone.

    Constructed with NO arguments on purpose — that is what production gets
    when the planner omits the field, which is the case the default exists
    for.

    **Auto-discovered, deliberately.** An earlier version pinned a literal
    table of the three known keys. That protected nothing for a fourth pack
    nobody adds to the table, and it *failed* on a consistent rename of both
    declarations — a legitimate refactor, not a defect. This form has neither
    problem: no roster to maintain, no exemption for the next pack, and a
    rename that keeps the two in step passes as it should.
    """
    # C2 — the cross-check is only meaningful while the two sides are
    # SEPARATELY authored. `Field(default=PLUGIN_MODEL_TYPE)` collapses them
    # onto one object and makes this tautological, and the guardrail cannot
    # see that (it only detects `model_fields[...]`). A comment forbidding it
    # is not enough: the comment itself concedes the constant-reference form
    # is better engineering in isolation, so the next reader has an argument
    # for the change that guts the check. Asserted instead.
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))

    def _default_expressions(node: ast.AST) -> list[ast.expr]:
        """The default expression, HOWEVER SPELLED.

        The first version matched only ``Field(default=...)``, so
        ``model_type: str = "quickstart_reference_mlp"`` and
        ``Field("quickstart_reference_mlp")`` both failed with "no
        model_type Field(default=...) found" — a false refusal for two
        declarations that satisfy this test's stated purpose exactly. The
        property is "the default is a LITERAL", not "the default is written
        one way".
        """
        if not (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "model_type"
            and node.value is not None
        ):
            return []
        value = node.value
        if not isinstance(value, ast.Call):
            return [value]  # a bare default: `model_type: str = "..."`
        found = [kw.value for kw in value.keywords if kw.arg == "default"]
        if not found and value.args:
            found = [value.args[0]]  # positional: `Field("...")`
        return found

    defaults = [d for node in ast.walk(tree) for d in _default_expressions(node)]
    assert defaults, f"{path.relative_to(REPO_ROOT)}: no model_type default found"
    assert all(isinstance(d, ast.Constant) for d in defaults), (
        f"{path.relative_to(REPO_ROOT)}: model_type's default must be a LITERAL. "
        "Referencing PLUGIN_MODEL_TYPE makes the identity cross-check below "
        "compare a value to itself, which passes for any value."
    )

    module = _load(path)
    declared = module.PLUGIN_MODEL_TYPE
    defaulted = module.PLUGIN_CONFIG_CLASS().model_type
    assert defaulted == declared, (
        f"{path.relative_to(REPO_ROOT)}: the config defaults model_type to "
        f"{defaulted!r} while the plugin registers itself as {declared!r}; a "
        "plan that omits the field would resolve a model type the registry "
        "does not have"
    )


class TestTheExemplarsAgreeWithTheFramework:
    """Where shipped exemplars disagreed, the framework's own base is the
    tiebreaker — not whichever exemplar was written last."""

    def test_baseconfig_is_the_source_of_the_model_type_obligation(self):
        from ml_models.models_format_sandbox import BaseConfig

        assert "model_type" in BaseConfig.model_fields, (
            "if this ever stops being true the obligation this census "
            "enforces has moved, and the census must move with it"
        )

    def test_no_exemplar_forbids_extra_fields(self):
        """``BaseConfig`` and both contrast exemplars leave ``extra`` at
        Pydantic's permissive default. The quickstart forbade it, which turns
        any unmodelled planner field into a hard plan rejection — and a
        rejected plan does not consume an attempt, so the round budget burns
        without training once."""
        offenders = []
        for path in PLUGINS:
            module = _load(path)
            if module.PLUGIN_CONFIG_CLASS.model_config.get("extra") == "forbid":
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert not offenders, (
            "plugin configs receive LLM-planned payloads; extra='forbid' "
            f"converts a harmless unmodelled field into a burned round: {offenders}"
        )
