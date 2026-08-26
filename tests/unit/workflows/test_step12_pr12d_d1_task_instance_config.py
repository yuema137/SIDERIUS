"""Step 12 / PR-12d — D1 (seam A): task-instance configuration.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §D.A / §M `D1`.

The failure class is F-12d-8: **the composition authority could not hand a
task its own scope authority.** ``PetsTaskDataPath`` and ``DavisTaskDataPath``
raised BY NAME at the first tuner attempt, telling the operator to declare a
``config:`` block under ``task_data_path:`` that the composition authority did
not implement — and the ONLY configured constructions in the whole repository
were in a test.

That last fact is why **every acceptance test here asserts THROUGH
``compose_run_task_bindings``**, the production entry point. A test that
constructed ``PetsTaskDataPath(manifest_path=…)`` directly would certify a
mechanism production does not use, which is the shape of the defect itself
(lesson L4, from ``G-12bc-C``).

What each class owns
--------------------

``TestSectionKeyRefusal``
    A misspelled sibling inside the section is REFUSED, not dropped.

``TestConfiguredConstruction``
    The declared config reaches the implementation's own constructor, and
    every malformed shape is a named refusal.

``TestRefEnvelope``
    A task DECLARES which of its own keys are manifest-relative refs, so a
    package composes identically whatever the cwd is — without the framework
    ever deciding which of a task's field names hold paths.

``TestProductionPathBuildsARealScope``
    The acceptance criterion: a configured Pets or DAVIS implementation
    obtained through the production composition path builds a real training
    scope without raising.

``TestSemanticIdentity``
    Ruling A1 — the registered bare instance ANCHORS the identity and is never
    returned in place of a configured one; the config enters the fingerprint;
    TIDMAD is byte-unchanged.
"""

from __future__ import annotations

import pathlib

import pytest

from execute_tools.task_data_path import ScopeBuildRequest
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MANIFEST_DIR = REPO_ROOT / "configs" / "task_composition"
SHIPPED_TIDMAD = MANIFEST_DIR / "tidmad.yaml"

TIDMAD_FINGERPRINT = "3fd178b532360c88d741d74748c34f915738b5202a84174b93f7e7816a2bfb56"

_SHIPPED_TASK_DATA_PATH_SECTION = (
    "task_data_path:\n"
    "  module: execute_tools.tidmad_data_path\n"
    "  symbol: TidmadTaskDataPath\n"
    "  id: tidmad"
)

PETS_SECTION = (
    "task_data_path:\n"
    "  module: execute_tools.pets_data_path\n"
    "  symbol: PetsTaskDataPath\n"
    "  config:\n"
    "    manifest_path:\n"
    "      ref: ../../examples/oxford_iiit_pet/data/manifests/gate2_train.csv"
)

DAVIS_SECTION = (
    "task_data_path:\n"
    "  module: execute_tools.davis_data_path\n"
    "  symbol: DavisTaskDataPath\n"
    "  config:\n"
    "    clips_path:\n"
    "      ref: ../../examples/davis_future_prediction/data/manifests/gate2_train.csv"
)


@pytest.fixture
def compose(request):
    """Compose a manifest whose ``task_data_path`` section is substituted.

    Written into the SHIPPED manifest's own directory, because refs resolve
    relative to the manifest — so the substituted copy exercises exactly the
    production resolution rules rather than a relaxed variant.
    """
    written: list[pathlib.Path] = []
    shipped = SHIPPED_TIDMAD.read_text(encoding="utf-8")
    assert _SHIPPED_TASK_DATA_PATH_SECTION in shipped, (
        "the shipped TIDMAD manifest's task_data_path section moved; this "
        "fixture substitutes it verbatim and must be re-anchored"
    )
    counter = iter(range(1000))

    def _compose(section: str):
        path = MANIFEST_DIR / f"_d1_{request.node.name[:40]}_{next(counter)}.yaml"
        path.write_text(shipped.replace(_SHIPPED_TASK_DATA_PATH_SECTION, section), encoding="utf-8")
        written.append(path)
        return compose_run_task_bindings(str(path))

    try:
        yield _compose
    finally:
        for path in written:
            path.unlink(missing_ok=True)


# ======================================================================


class TestSectionKeyRefusal:
    """A misspelled sibling is refused, not silently dropped."""

    def test_an_unknown_key_inside_the_section_is_refused_by_name(self, compose):
        with pytest.raises(TaskCompositionError, match="declares unknown key"):
            compose(
                "task_data_path:\n"
                "  module: execute_tools.tidmad_data_path\n"
                "  symbol: TidmadTaskDataPath\n"
                "  configs:\n"
                "    manifest_path: x"
            )

    def test_the_refusal_names_the_keys_the_section_does_define(self, compose):
        with pytest.raises(TaskCompositionError) as excinfo:
            compose(
                "task_data_path:\n"
                "  module: execute_tools.tidmad_data_path\n"
                "  symbol: TidmadTaskDataPath\n"
                "  typo_key: 1"
            )
        message = str(excinfo.value)
        assert "typo_key" in message
        for known in ("config", "file", "id", "module", "symbol"):
            assert known in message

    def test_the_shipped_manifest_still_composes(self):
        """The refusal must not have narrowed the section below what ships."""
        assert compose_run_task_bindings(str(SHIPPED_TIDMAD)).task_data_path.task_data_path_id == (
            "tidmad"
        )


class TestConfiguredConstruction:
    """The declared config reaches the implementation's OWN constructor."""

    def test_a_config_that_is_not_a_mapping_is_refused(self, compose):
        with pytest.raises(TaskCompositionError, match="config must be a mapping"):
            compose(
                "task_data_path:\n"
                "  module: execute_tools.pets_data_path\n"
                "  symbol: PetsTaskDataPath\n"
                "  config: [1, 2]"
            )

    def test_a_key_the_implementation_does_not_accept_is_refused_by_name(self, compose):
        with pytest.raises(TaskCompositionError, match="does not accept the declared config"):
            compose(
                "task_data_path:\n"
                "  module: execute_tools.pets_data_path\n"
                "  symbol: PetsTaskDataPath\n"
                "  config:\n"
                "    not_a_real_argument: 1"
            )

    def test_a_constructor_that_raises_is_refused_by_name(self, compose, tmp_path):
        plugin = tmp_path / "raising_data_path.py"
        plugin.write_text(
            "class RaisingDataPath:\n"
            "    task_data_path_id = 'raising'\n"
            "    def __init__(self, **kwargs):\n"
            "        raise RuntimeError('constructor exploded')\n",
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError, match="raised while being constructed"):
            compose(
                f"task_data_path:\n"
                f"  file: {plugin}\n"
                f"  symbol: RaisingDataPath\n"
                f"  config:\n"
                f"    anything: 1"
            )

    def test_config_against_an_already_built_instance_is_refused(self, compose, tmp_path):
        """Configuration happens AT construction; a composition never mutates."""
        plugin = tmp_path / "prebuilt_data_path.py"
        plugin.write_text(
            "class _Prebuilt:\n    task_data_path_id = 'prebuilt'\nPREBUILT = _Prebuilt()\n",
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError, match="already-constructed instance"):
            compose(
                f"task_data_path:\n  file: {plugin}\n  symbol: PREBUILT\n  config:\n    anything: 1"
            )

    def test_the_authority_routes_on_no_task_owned_config_key(self):
        """Task-agnosticism, asserted as EXECUTABLE string literals.

        ``manifest_path`` and ``clips_path`` are the two config keys the packs
        use. What would make the authority task-aware is *comparing against
        one of them* — ``if key == "manifest_path"`` — not mentioning one.

        The distinction is load-bearing rather than pedantic, and a plain
        substring census proves it: ``CompositionProvenance`` has had a field
        called ``manifest_path`` since Step 10, which is the framework's own
        vocabulary for "where the manifest is", and the docstring of the
        config seam shows ``manifest_path`` in its worked example. Neither is
        task knowledge. So this walks the AST and looks at string CONSTANTS in
        executable positions, skipping docstrings.
        """
        import ast

        module = ast.parse(
            (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        )
        docstrings = set()
        for node in ast.walk(module):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)
        offenders = [
            node.value
            for node in ast.walk(module)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in {"manifest_path", "clips_path"}
            and node.value not in docstrings
        ]
        assert offenders == [], (
            f"the composition authority uses a task-owned config key as an "
            f"executable literal: {offenders}. Config keys belong to the "
            f"implementation's constructor; this authority validates a SHAPE."
        )


class TestRefEnvelope:
    """The task declares which of its OWN keys are manifest-relative refs."""

    def test_a_ref_resolves_relative_to_the_manifest_not_the_cwd(self, compose, monkeypatch):
        monkeypatch.chdir("/")
        composition = compose(PETS_SECTION)
        assert composition.task_data_path.task_data_path_id == "oxford_iiit_pet"

    def test_a_plain_value_passes_through_verbatim(self, compose, tmp_path):
        plugin = tmp_path / "echo_data_path.py"
        plugin.write_text(
            # The four protocol methods are required: `register_task_data_path`
            # refuses a malformed implementation BEFORE any execution, and a
            # fixture that skipped them would be testing the registry's
            # refusal rather than the config passthrough.
            "class EchoDataPath:\n"
            "    task_data_path_id = 'echo'\n"
            "    def __init__(self, *, literal=None):\n"
            "        self.literal = literal\n"
            "    def training_dataset(self, scope, params): ...\n"
            "    def validation_dataset(self, scope, params): ...\n"
            "    def write_deliverable(self, items, request): ...\n"
            "    def read_evaluation_payload(self, request): ...\n",
            encoding="utf-8",
        )
        composition = compose(
            f"task_data_path:\n"
            f"  file: {plugin}\n"
            f"  symbol: EchoDataPath\n"
            f"  config:\n"
            f"    literal: ../not/resolved"
        )
        assert composition.task_data_path.literal == "../not/resolved"

    def test_a_ref_envelope_with_a_sibling_key_is_refused(self, compose):
        with pytest.raises(TaskCompositionError, match="declares a 'ref' alongside"):
            compose(
                "task_data_path:\n"
                "  module: execute_tools.pets_data_path\n"
                "  symbol: PetsTaskDataPath\n"
                "  config:\n"
                "    manifest_path:\n"
                "      ref: a.csv\n"
                "      reff: b.csv"
            )

    def test_an_empty_ref_is_refused(self, compose):
        with pytest.raises(TaskCompositionError, match="must be a non-empty string path"):
            compose(
                "task_data_path:\n"
                "  module: execute_tools.pets_data_path\n"
                "  symbol: PetsTaskDataPath\n"
                "  config:\n"
                "    manifest_path:\n"
                "      ref: ''"
            )


class TestProductionPathBuildsARealScope:
    """The D1 acceptance criterion, end to end through production."""

    REQUEST = ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)

    @pytest.mark.parametrize(
        ("section", "task_id", "scope_cls", "expected_rows"),
        [
            (PETS_SECTION, "oxford_iiit_pet", "PetsScope", 370),
            (DAVIS_SECTION, "davis_future_prediction", "DavisScope", 60),
        ],
    )
    def test_a_configured_implementation_builds_a_training_scope(
        self, compose, section, task_id, scope_cls, expected_rows
    ):
        implementation = compose(section).task_data_path
        assert implementation.task_data_path_id == task_id
        scope = implementation.build_training_scope(self.REQUEST)
        assert type(scope).__name__ == scope_cls
        assert len(scope.rows) == expected_rows, (
            "the scope must come from the DECLARED manifest, and its size is "
            "what proves the config actually reached the constructor"
        )

    def test_the_eval_leg_builds_too(self, compose):
        implementation = compose(PETS_SECTION).task_data_path
        assert len(implementation.build_eval_scope(self.REQUEST).rows) == 370

    def test_a_bare_instance_still_refuses_to_BUILD_by_name(self):
        """PRESERVED, not retired: this is the regime-A anchor A1 relies on.

        The registered module-level instance can materialize a scope it is
        HANDED and must keep refusing to build one from nothing — that refusal
        is what makes "the bare object must never be returned in place of a
        configured one" a meaningful rule rather than a preference.
        """
        from execute_tools.pets_data_path import PetsTaskDataPath

        with pytest.raises(ValueError, match="was asked to BUILD a scope"):
            PetsTaskDataPath().build_training_scope(self.REQUEST)


class TestSemanticIdentity:
    """Ruling A1, and the backward-compatibility anchors."""

    def test_the_configured_instance_is_returned_even_though_the_id_is_registered(self, compose):
        """The heart of A1.

        Every built-in registers at module import in all three children, so a
        bare instance ALWAYS exists first. Before D1 the composition returned
        that one, and a composed Pets run silently received the object that
        cannot build a scope.
        """
        from execute_tools.task_data_path import registered_task_data_path_ids

        assert "oxford_iiit_pet" in registered_task_data_path_ids(), (
            "the precondition: the bare instance is already registered"
        )
        implementation = compose(PETS_SECTION).task_data_path
        implementation.build_training_scope(
            ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)
        )

    def test_the_config_enters_the_semantic_fingerprint(self, compose):
        base = compose(PETS_SECTION).semantic_fingerprint
        other = compose(
            PETS_SECTION.replace("gate2_train.csv", "gate2_validation.csv")
        ).semantic_fingerprint
        assert base != other, (
            "changing which manifest a run trains on must change its identity, "
            "or a resume would silently accept a different scope"
        )

    def test_the_fingerprint_hashes_the_AUTHORED_ref_not_the_resolved_path(self, compose):
        """Q-P1-2: the same package at two checkout paths is ONE run.

        Hashing the resolved absolute path would make a relocated checkout a
        different run — the exclusion every other ref already gets.
        """
        first = compose(PETS_SECTION).semantic_fingerprint
        assert compose(PETS_SECTION).semantic_fingerprint == first
        composition = compose(PETS_SECTION)
        assert str(REPO_ROOT) not in str(composition.semantic_fingerprint)

    def test_an_absent_config_leaves_TIDMAD_byte_identical(self):
        assert compose_run_task_bindings(str(SHIPPED_TIDMAD)).semantic_fingerprint == (
            TIDMAD_FINGERPRINT
        )

    def test_an_absent_config_still_returns_the_REGISTERED_instance(self, compose):
        """The un-configured path is unchanged: one id, one object.

        A child resolves a transported id through the registry, so with no
        config the composition must keep returning the registered object —
        A1 narrows that rule, it does not delete it.
        """
        from execute_tools.task_data_path import TaskBindingContext, resolve_task_data_path

        composed = compose(_SHIPPED_TASK_DATA_PATH_SECTION).task_data_path
        assert composed is resolve_task_data_path(TaskBindingContext(task_data_path_id="tidmad"))
