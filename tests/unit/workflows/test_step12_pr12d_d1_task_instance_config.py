"""Task-instance configuration is owned by the declared implementation.

The failure class is F-12d-8: the composition authority once had no way to
hand a task its own constructor configuration. Every acceptance assertion in
this module therefore enters through ``compose_run_task_bindings``. Directly
constructing the fixture implementation would bypass the production boundary
and could not catch the original defect.

The fixture is a temporary external task rather than a shipped scientific
task. It preserves five independent obligations:

* unknown declaration keys fail closed;
* constructor configuration is validated and delivered unchanged;
* a task-selected ``{ref: ...}`` value resolves relative to the manifest;
* a configured implementation can build real training and evaluation scopes;
* authored configuration participates in semantic identity without pinning an
  absolute checkout path.
"""

from __future__ import annotations

import ast
import copy
import pathlib

import pytest
import yaml

from execute_tools.task_data_path import (
    ScopeBuildRequest,
    TaskBindingContext,
    resolve_task_data_path,
)
from execute_tools.task_registration_scope import run_registration_scope
from workflows.task_composition import TaskCompositionError, compose_run_task_bindings

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
QUICKSTART_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"

_PLUGIN_SOURCE = """\
from pathlib import Path
from types import SimpleNamespace

from execute_tools.task_data_path import register_task_data_path


class ConfigurableScopeDataPath:
    task_data_path_id = "fixture_configurable_scope"

    def __init__(self, *, scope_path=None, literal=None):
        self.scope_path = scope_path
        self.literal = literal

    def training_dataset(self, scope, params):
        return ()

    def validation_dataset(self, scope, params):
        return ()

    def write_deliverable(self, items, request):
        return None

    def read_evaluation_payload(self, request):
        return None

    def _build_scope(self):
        if self.scope_path is None:
            raise ValueError("bare fixture was asked to BUILD a scope")
        rows = tuple(
            line.strip()
            for line in Path(self.scope_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        return SimpleNamespace(rows=rows)

    def build_training_scope(self, request):
        return self._build_scope()

    def build_eval_scope(self, request):
        return self._build_scope()


BARE = ConfigurableScopeDataPath()
register_task_data_path(BARE)
"""


def _absolute_quickstart_manifest() -> dict:
    """Return the framework example with refs independent of fixture location."""
    raw = yaml.safe_load(QUICKSTART_MANIFEST.read_text(encoding="utf-8"))
    base = QUICKSTART_MANIFEST.parent
    for section, key in (
        ("dataset_profile", "config"),
        ("metric", "declaration"),
        ("task_config", "config"),
        ("model_plugins", "dir"),
    ):
        raw[section][key] = str((base / raw[section][key]).resolve())
    raw["metric"]["implementation"]["file"] = str(
        (base / raw["metric"]["implementation"]["file"]).resolve()
    )
    return raw


@pytest.fixture
def task_package(tmp_path):
    """Create one relocatable external task package with task-owned config."""
    package = tmp_path / "task"
    package.mkdir(parents=True)
    plugin = package / "configurable_scope.py"
    plugin.write_text(_PLUGIN_SOURCE, encoding="utf-8")
    (package / "scope_rows.txt").write_text("row-a\nrow-b\nrow-c\n", encoding="utf-8")
    return package, plugin


@pytest.fixture
def compose(task_package):
    """Compose temporary manifests through the production authority."""
    package, plugin = task_package
    counter = iter(range(1000))

    def configured_section(
        *,
        plugin_path: pathlib.Path = plugin,
        scope_ref: str = "scope_rows.txt",
    ) -> dict:
        return {
            "file": str(plugin_path),
            "symbol": "ConfigurableScopeDataPath",
            "config": {"scope_path": {"ref": scope_ref}},
        }

    def do_compose(section: dict, *, manifest_dir: pathlib.Path = package):
        manifest_dir.mkdir(parents=True, exist_ok=True)
        raw = _absolute_quickstart_manifest()
        raw["task_data_path"] = copy.deepcopy(section)
        path = manifest_dir / f"composition_{next(counter)}.yaml"
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        return compose_run_task_bindings(str(path))

    with run_registration_scope():
        yield do_compose, configured_section


class TestSectionKeyRefusal:
    """A misspelled sibling is refused rather than silently dropped."""

    def test_an_unknown_key_inside_the_section_is_refused_by_name(self, compose):
        do_compose, configured = compose
        section = configured()
        section["configs"] = section.pop("config")
        with pytest.raises(TaskCompositionError, match="declares unknown key"):
            do_compose(section)

    def test_the_refusal_names_the_keys_the_section_does_define(self, compose):
        do_compose, configured = compose
        section = configured()
        section["typo_key"] = 1
        with pytest.raises(TaskCompositionError) as excinfo:
            do_compose(section)
        message = str(excinfo.value)
        assert "typo_key" in message
        for known in ("config", "file", "id", "module", "symbol"):
            assert known in message

    def test_the_framework_quickstart_manifest_still_composes(self):
        with run_registration_scope():
            assert (
                compose_run_task_bindings(str(QUICKSTART_MANIFEST)).task_data_path.task_data_path_id
                == "quickstart_tabular"
            )


class TestConfiguredConstruction:
    """The declared config reaches the implementation's own constructor."""

    def test_a_config_that_is_not_a_mapping_is_refused(self, compose):
        do_compose, configured = compose
        section = configured()
        section["config"] = [1, 2]
        with pytest.raises(TaskCompositionError, match="config must be a mapping"):
            do_compose(section)

    def test_a_key_the_implementation_does_not_accept_is_refused_by_name(self, compose):
        do_compose, configured = compose
        section = configured()
        section["config"] = {"not_a_real_argument": 1}
        with pytest.raises(TaskCompositionError, match="does not accept the declared config"):
            do_compose(section)

    def test_a_constructor_that_raises_is_refused_by_name(self, compose, tmp_path):
        do_compose, _configured = compose
        plugin = tmp_path / "raising_data_path.py"
        plugin.write_text(
            "class RaisingDataPath:\n"
            "    task_data_path_id = 'raising'\n"
            "    def __init__(self, **kwargs):\n"
            "        raise RuntimeError('constructor exploded')\n",
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError, match="raised while being constructed"):
            do_compose(
                {
                    "file": str(plugin),
                    "symbol": "RaisingDataPath",
                    "config": {"anything": 1},
                }
            )

    def test_config_against_an_already_built_instance_is_refused(self, compose, tmp_path):
        do_compose, _configured = compose
        plugin = tmp_path / "prebuilt_data_path.py"
        plugin.write_text(
            "class _Prebuilt:\n    task_data_path_id = 'prebuilt'\nPREBUILT = _Prebuilt()\n",
            encoding="utf-8",
        )
        with pytest.raises(TaskCompositionError, match="already-constructed instance"):
            do_compose({"file": str(plugin), "symbol": "PREBUILT", "config": {"anything": 1}})

    def test_the_authority_routes_on_no_task_owned_config_key(self):
        module = ast.parse(
            (REPO_ROOT / "src/workflows" / "task_composition.py").read_text(encoding="utf-8")
        )
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(module)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        }
        offenders = [
            node.value
            for node in ast.walk(module)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in {"scope_path", "literal"}
            and node.value not in docstrings
        ]
        assert offenders == []


class TestRefEnvelope:
    """The task declares which of its own keys are manifest-relative refs."""

    def test_a_ref_resolves_relative_to_the_manifest_not_the_cwd(self, compose, monkeypatch):
        do_compose, configured = compose
        monkeypatch.chdir("/")
        implementation = do_compose(configured()).task_data_path
        assert pathlib.Path(implementation.scope_path).name == "scope_rows.txt"

    def test_a_plain_value_passes_through_verbatim(self, compose):
        do_compose, configured = compose
        section = configured()
        section["config"] = {"literal": "../not/resolved"}
        assert do_compose(section).task_data_path.literal == "../not/resolved"

    def test_a_ref_envelope_with_a_sibling_key_is_refused(self, compose):
        do_compose, configured = compose
        section = configured()
        section["config"]["scope_path"]["reff"] = "other.txt"
        with pytest.raises(TaskCompositionError, match="declares a 'ref' alongside"):
            do_compose(section)

    def test_an_empty_ref_is_refused(self, compose):
        do_compose, configured = compose
        section = configured(scope_ref="")
        with pytest.raises(TaskCompositionError, match="must be a non-empty string path"):
            do_compose(section)


class TestProductionPathBuildsARealScope:
    """The configured external implementation builds both scope roles."""

    REQUEST = ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)

    def test_a_configured_implementation_builds_a_training_scope(self, compose):
        do_compose, configured = compose
        implementation = do_compose(configured()).task_data_path
        assert implementation.task_data_path_id == "fixture_configurable_scope"
        assert implementation.build_training_scope(self.REQUEST).rows == (
            "row-a",
            "row-b",
            "row-c",
        )

    def test_the_eval_leg_builds_too(self, compose):
        do_compose, configured = compose
        implementation = do_compose(configured()).task_data_path
        assert len(implementation.build_eval_scope(self.REQUEST).rows) == 3

    def test_a_bare_instance_still_refuses_to_build_by_name(self, compose):
        do_compose, configured = compose
        section = configured()
        section.pop("config")
        bare = do_compose(section).task_data_path
        with pytest.raises(ValueError, match="asked to BUILD a scope"):
            bare.build_training_scope(self.REQUEST)


class TestSemanticIdentity:
    """Configured instances preserve registry and semantic-identity rules."""

    REQUEST = ScopeBuildRequest(round_kind="formal", selection_strategy="snapshot", portion=1.0)

    def test_the_configured_instance_is_returned_even_when_a_bare_one_is_registered(self, compose):
        do_compose, configured = compose
        implementation = do_compose(configured()).task_data_path
        assert len(implementation.build_training_scope(self.REQUEST).rows) == 3

    def test_the_config_enters_the_semantic_fingerprint(self, compose):
        do_compose, configured = compose
        base = do_compose(configured()).semantic_fingerprint
        other = do_compose(configured(scope_ref="other_rows.txt"))
        assert other.semantic_fingerprint != base

    def test_the_fingerprint_hashes_the_authored_ref_not_the_resolved_path(self, compose, tmp_path):
        do_compose, configured = compose
        first = do_compose(configured()).semantic_fingerprint
        relocated = tmp_path / "relocated_manifest"
        relocated.mkdir()
        (relocated / "scope_rows.txt").write_text("row-a\nrow-b\nrow-c\n", encoding="utf-8")
        second = do_compose(configured(), manifest_dir=relocated).semantic_fingerprint
        assert second == first

    def test_an_absent_config_returns_the_registered_instance(self, compose):
        do_compose, configured = compose
        section = configured()
        section.pop("config")
        composed = do_compose(section).task_data_path
        resolved = resolve_task_data_path(
            TaskBindingContext(task_data_path_id="fixture_configurable_scope")
        )
        assert composed is resolved
