"""Step 12 / PR-12d — DP (seam P): run-scoped model-plugin availability.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §D.P / §M `DP`.

This module owns the POSITIVE contracts whose inverted counterparts D0's
``TestInvertedGuardA5`` recorded and DP retired (R-11-10). The failure class
is *a composed run cannot obtain, and cannot prove, its task's model plugin*.

What each class owns
--------------------

``TestDeclaredModelPlugins``
    The declaration IS the operator surface: a task names its own plugin
    root and the model types that root must produce. Every malformed shape
    is a named refusal, and an unmet requirement refuses rather than
    resolving a same-named implementation from somewhere the run never
    declared (**falsifier 2**).

``TestUnionPropagation``
    The parent's roots reach every relevant child as the SAME semantic set,
    asserted PER CHILD rather than once, and a child default ADDS instead of
    replacing (**falsifier 1**).

``TestCrossRootCollision``
    A ``model_type`` produced by two scanned directories REFUSES rather than
    letting scan order decide (**falsifier 3**).

``TestPluginProvenance``
    The identity of what executed is recoverable from a persisted artifact,
    not from a log line — and it is the identity CAPTURED at resolution, not
    a fresh read (F-12bc-7).

``TestLegacyUnchanged``
    Every un-composed caller resolves and transports byte-identically.

``TestRealChildProcess``
    The integration witness the design requires: one synthetic tiny plugin,
    parent composition → a REAL child process → the child resolves that exact
    plugin, EXECUTES it, and reports an identity the parent can verify.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

from core.subprocess_env import PLUGIN_DIRS_ENV_VAR, subprocess_env
from ml_models.plugin_binding import (
    ModelPluginResolutionError,
    ResolvedModelPlugin,
    RunModelPluginBinding,
    active_run_model_plugin_roots,
    active_run_model_plugins,
    bind_run_model_plugins,
    resolve_declared_model_plugins,
    union_plugin_roots,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: A minimal but REAL model plugin: the four `PLUGIN_*` symbols the loader
#: requires, a Pydantic config and an `nn.Module` the child can instantiate.
SYNTHETIC_PLUGIN = textwrap.dedent(
    '''
    """A synthetic pack model plugin — DP's transport witness."""

    import torch.nn as nn
    from pydantic import BaseModel

    PLUGIN_MODEL_TYPE = "{model_type}"
    PLUGIN_OUTPUT_TYPE = "classifier"


    class {cls}Config(BaseModel):
        width: int = {width}


    class {cls}(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.width = config.width
            self.layer = nn.Linear(config.width, config.width)

        def forward(self, x):
            return self.layer(x)


    PLUGIN_CONFIG_CLASS = {cls}Config
    PLUGIN_MODEL_CLASS = {cls}
    '''
)


def write_plugin(directory: pathlib.Path, model_type: str, *, width: int = 4) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    cls = "".join(part.title() for part in model_type.split("_"))
    path = directory / f"{model_type}.py"
    path.write_text(
        SYNTHETIC_PLUGIN.format(model_type=model_type, cls=cls, width=width), encoding="utf-8"
    )
    return path


@pytest.fixture(autouse=True)
def _clean_registries():
    """Model registration is PROCESS-GLOBAL; restore it around every test.

    Without this a synthetic plugin registered here leaks into an unrelated
    module's registry and the failure surfaces as test ORDER — the exact
    F-12bc-8 shape (an import-registration lifetime defect masquerading as a
    census result).
    """
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY

    saved = (
        dict(MODEL_REGISTRY),
        dict(PLUGIN_CONFIG_REGISTRY),
        dict(PLUGIN_OUTPUT_TYPE_REGISTRY),
    )
    try:
        yield
    finally:
        for live, original in zip(
            (MODEL_REGISTRY, PLUGIN_CONFIG_REGISTRY, PLUGIN_OUTPUT_TYPE_REGISTRY),
            saved,
            strict=True,
        ):
            live.clear()
            live.update(original)


# ======================================================================
# The declaration — the surface, and every refusal
# ======================================================================


class TestDeclaredModelPlugins:
    """A task declares its own plugin root; the framework holds no catalog."""

    def test_a_declared_root_resolves_and_pins_what_it_produced(self, tmp_path):
        plugin = write_plugin(tmp_path / "plugins", "dp_reference_net")
        binding = resolve_declared_model_plugins(
            configured_ref="plugins",
            root=str(tmp_path / "plugins"),
            required_model_types=("dp_reference_net",),
        )
        assert binding.roots == (str(tmp_path / "plugins"),)
        assert binding.required_model_types == ("dp_reference_net",)
        assert [p.model_type for p in binding.plugins] == ["dp_reference_net"]
        expected = hashlib.sha256(plugin.read_bytes()).hexdigest()
        assert binding.plugins[0].content_sha256 == expected
        assert binding.plugins[0].configured_ref == "plugins"
        assert binding.plugins[0].member == "dp_reference_net.py"

    def test_the_declared_implementation_is_actually_registered(self, tmp_path):
        """Resolution is not bookkeeping — production can construct the model."""
        write_plugin(tmp_path / "plugins", "dp_registered_net", width=7)
        resolve_declared_model_plugins(
            configured_ref="plugins",
            root=str(tmp_path / "plugins"),
            required_model_types=("dp_registered_net",),
        )
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.models_sandbox import MODEL_REGISTRY

        assert "dp_registered_net" in MODEL_REGISTRY
        model = MODEL_REGISTRY["dp_registered_net"](PLUGIN_CONFIG_REGISTRY["dp_registered_net"]())
        assert model.width == 7

    def test_a_missing_root_refuses_by_name(self, tmp_path):
        with pytest.raises(ModelPluginResolutionError, match="does not exist at"):
            resolve_declared_model_plugins(
                configured_ref="plugins",
                root=str(tmp_path / "absent"),
                required_model_types=("anything",),
            )

    def test_an_unmet_requirement_refuses_and_never_falls_back(self, tmp_path):
        """FALSIFIER 2. The plugin the run needs is absent; something else is
        present. The run must refuse, not resolve the something else."""
        write_plugin(tmp_path / "plugins", "dp_some_other_net")
        with pytest.raises(ModelPluginResolutionError) as excinfo:
            resolve_declared_model_plugins(
                configured_ref="plugins",
                root=str(tmp_path / "plugins"),
                required_model_types=("dp_required_net",),
            )
        message = str(excinfo.value)
        assert "dp_required_net" in message
        assert "dp_some_other_net" in message, "the refusal states what WAS there"
        assert "REFUSES" in message

    def test_a_broken_required_plugin_is_caught_by_the_requirement_not_by_the_scan(self, tmp_path):
        """Scan tolerance is not declared-binding tolerance (08b's rule).

        A member that fails to import is SKIPPED — that is right for a scan.
        What makes it safe is that the requirement then goes unmet.
        """
        plugins = tmp_path / "plugins"
        write_plugin(plugins, "dp_healthy_net")
        (plugins / "dp_broken_net.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
        ok = resolve_declared_model_plugins(
            configured_ref="plugins",
            root=str(plugins),
            required_model_types=("dp_healthy_net",),
        )
        assert [p.model_type for p in ok.plugins] == ["dp_healthy_net"]
        with pytest.raises(ModelPluginResolutionError, match="dp_broken_net"):
            resolve_declared_model_plugins(
                configured_ref="plugins",
                root=str(plugins),
                required_model_types=("dp_broken_net",),
            )

    def test_two_files_declaring_one_model_type_refuse(self, tmp_path):
        plugins = tmp_path / "plugins"
        write_plugin(plugins, "dp_twin_net")
        (plugins / "aaa_copy.py").write_text(
            SYNTHETIC_PLUGIN.format(model_type="dp_twin_net", cls="DpTwinNetCopy", width=4),
            encoding="utf-8",
        )
        with pytest.raises(ModelPluginResolutionError, match="more than one file"):
            resolve_declared_model_plugins(
                configured_ref="plugins",
                root=str(plugins),
                required_model_types=("dp_twin_net",),
            )

    def test_the_module_names_no_task(self):
        """Zero task-name dispatch, asserted on the authority's own source."""
        source = (REPO_ROOT / "ml_models" / "plugin_binding.py").read_text(encoding="utf-8")
        lowered = source.lower()
        for task in ("tidmad", "pets", "oxford", "davis"):
            assert task not in lowered, f"seam P's authority names the task {task!r}"


# ======================================================================
# The manifest section — composition-level refusals
# ======================================================================


def _manifest(tmp_path: pathlib.Path, model_plugins_yaml: str) -> pathlib.Path:
    """A TIDMAD-shaped manifest with a substituted ``model_plugins`` section.

    Built from the SHIPPED manifest so the test exercises the production
    composition path rather than a hand-rolled minimal one (L4: a test that
    constructs the mechanism directly certifies something production does
    not use).
    """
    shipped = (REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml").read_text(
        encoding="utf-8"
    )
    rewritten = []
    for line in shipped.splitlines():
        if line.startswith(("  ", "#")) or not line.strip():
            rewritten.append(line)
            continue
        rewritten.append(line)
    body = "\n".join(rewritten)
    # Refs in the shipped manifest are relative to ITS directory, so the
    # rewritten copy is written back into that same directory.
    target = REPO_ROOT / "configs" / "task_composition" / f"_dp_tmp_{tmp_path.name}.yaml"
    target.write_text(f"{body}\n\n{model_plugins_yaml}\n", encoding="utf-8")
    return target


class TestManifestSection:
    """The optional section, resolved by the production composition path."""

    @pytest.fixture
    def compose(self):
        from workflows.task_composition import compose_run_task_bindings

        written: list[pathlib.Path] = []

        def _compose(tmp_path: pathlib.Path, section: str):
            path = _manifest(tmp_path, section)
            written.append(path)
            return compose_run_task_bindings(str(path))

        try:
            yield _compose
        finally:
            for path in written:
                path.unlink(missing_ok=True)

    def test_an_absent_section_binds_nothing_and_keeps_the_fingerprint(self):
        from workflows.task_composition import compose_run_task_bindings

        composition = compose_run_task_bindings(
            str(REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml")
        )
        assert composition.model_plugins is None
        assert composition.semantic_fingerprint == (
            "9125bf587fea5bae1493800e9b50bafbb63164ff72ec1bfe3b08520ae1e72aac"
        )

    def test_an_explicit_none_binds_nothing_and_keeps_the_fingerprint(self, compose, tmp_path):
        composition = compose(tmp_path, "model_plugins:\n  none: true")
        assert composition.model_plugins is None
        assert composition.semantic_fingerprint == (
            "9125bf587fea5bae1493800e9b50bafbb63164ff72ec1bfe3b08520ae1e72aac"
        )

    def test_a_declared_section_resolves_through_the_production_path(self, compose, tmp_path):
        write_plugin(tmp_path / "plugins", "dp_manifest_net")
        composition = compose(
            tmp_path,
            f"model_plugins:\n  dir: {tmp_path / 'plugins'}\n  require: [dp_manifest_net]",
        )
        binding = composition.model_plugins
        assert binding is not None
        assert [p.model_type for p in binding.plugins] == ["dp_manifest_net"]

    def test_a_declared_section_MOVES_the_semantic_fingerprint(self, compose, tmp_path):
        """The plugin's CONTENT digest joins the composition identity, so an
        edited pack plugin fails a resume closed rather than silently running
        different code under an unchanged declaration."""
        write_plugin(tmp_path / "plugins", "dp_fp_net", width=4)
        section = f"model_plugins:\n  dir: {tmp_path / 'plugins'}\n  require: [dp_fp_net]"
        first = compose(tmp_path, section).semantic_fingerprint
        assert first != "9125bf587fea5bae1493800e9b50bafbb63164ff72ec1bfe3b08520ae1e72aac"
        write_plugin(tmp_path / "plugins", "dp_fp_net", width=5)
        assert compose(tmp_path, section).semantic_fingerprint != first

    @pytest.mark.parametrize(
        ("section", "expected"),
        [
            ("model_plugins: []", "must be a mapping"),
            ("model_plugins:\n  none: true\n  dir: /tmp", "both 'none: true' and a 'dir'"),
            ("model_plugins:\n  require: [x]", "requires a non-empty string 'dir'"),
            ("model_plugins:\n  dir: /tmp", "requires a non-empty list 'require'"),
            ("model_plugins:\n  dir: /tmp\n  require: []", "requires a non-empty list 'require'"),
            ("model_plugins:\n  dir: /tmp\n  require: [3]", "only non-empty strings"),
        ],
    )
    def test_every_malformed_shape_is_refused_by_name(self, compose, tmp_path, section, expected):
        from workflows.task_composition import TaskCompositionError

        with pytest.raises(TaskCompositionError, match=expected):
            compose(tmp_path, section)


# ======================================================================
# Propagation — falsifier 1
# ======================================================================

#: Every production spawn helper that hands a child its plugin environment.
#: Asserted PER CHILD, not once (§M DP acceptance).
SPAWN_HELPERS = ("execute_training", "execute_inference", "execute_scoring")


class TestUnionPropagation:
    """The parent's roots reach every relevant child, and nothing drops them."""

    def test_the_merge_authority_is_order_stable_and_deduplicating(self):
        assert union_plugin_roots(["/a", "/b"], "/b:/c", ["", "  ", "/a"]) == ("/a", "/b", "/c")
        assert union_plugin_roots(None, (), "") == ()

    def test_a_child_default_ADDS_rather_than_replacing(self):
        """FALSIFIER 1, and the exact asymmetry D0 recorded."""
        binding = RunModelPluginBinding(
            roots=("/declared/pack",), required_model_types=("x",), plugins=()
        )
        with bind_run_model_plugins(binding):
            env = subprocess_env(plugin_dir="/child/default")
        roots = env[PLUGIN_DIRS_ENV_VAR].split(os.pathsep)
        assert "/declared/pack" in roots, "the child default must never DROP the parent's binding"
        assert "/child/default" in roots, "and it must still ADD its own"
        assert roots.index("/child/default") < roots.index("/declared/pack")

    def test_an_inherited_root_survives_a_hop_that_supplies_no_default(self, monkeypatch):
        """What makes the property TRANSITIVE — WITHOUT unioning ambient state.

        A process that received roots from ITS parent carries no binding
        object, only the environment. `os.environ.copy()` already carries it,
        so no union is needed for the hop to work.

        **An earlier draft DID union the ambient value into every spawn, and
        that was wrong.** It changed legacy behaviour — an ambient value that
        used to be REPLACED by an explicit `plugin_dir` would suddenly
        survive — which breaks seam P's own "legacy resolution observably
        unchanged" requirement. A real-training test found it: the child
        scanned a directory it had never scanned, plugin imports consumed
        RNG, and the trained weights moved. The frozen rule protects the
        parent's BINDING, not ambient state.
        """
        monkeypatch.setenv(PLUGIN_DIRS_ENV_VAR, "/inherited/pack")
        assert subprocess_env()[PLUGIN_DIRS_ENV_VAR] == "/inherited/pack"

    def test_an_explicit_default_still_REPLACES_an_ambient_value(self, monkeypatch):
        """The legacy shape, preserved exactly.

        Only the run-scoped BINDING is additive. Ambient state has never been
        the authority and does not become one here.
        """
        monkeypatch.setenv(PLUGIN_DIRS_ENV_VAR, "/ambient/leak")
        assert subprocess_env(plugin_dir="/child/default")[PLUGIN_DIRS_ENV_VAR] == (
            "/child/default"
        )

    @pytest.mark.parametrize("helper", SPAWN_HELPERS)
    def test_every_spawn_site_builds_its_environment_through_the_one_helper(self, helper):
        """Asserted PER CHILD: three call sites, one transport authority.

        A future spawn site that assembled `os.environ` itself would reach a
        child with the run's roots missing, and nothing else here would see
        it.
        """
        import ast as _ast

        source = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        tree = _ast.parse(source)
        target = next(
            node
            for node in _ast.walk(tree)
            if isinstance(node, _ast.FunctionDef) and node.name == helper
        )
        body = _ast.unparse(target)
        assert "_subprocess_env(" in body, f"{helper} does not build its env through the helper"

    def test_the_loader_consumes_the_binding(self, tmp_path):
        from ml_models.plugin_loader import _resolve_plugin_dirs

        binding = RunModelPluginBinding(
            roots=(str(tmp_path),), required_model_types=("x",), plugins=()
        )
        with bind_run_model_plugins(binding):
            assert _resolve_plugin_dirs()[0] == str(tmp_path)

    def test_the_binding_unwinds(self, tmp_path):
        binding = RunModelPluginBinding(
            roots=(str(tmp_path),), required_model_types=("x",), plugins=()
        )
        assert active_run_model_plugins() is None
        with bind_run_model_plugins(binding):
            assert active_run_model_plugin_roots() == (str(tmp_path),)
        assert active_run_model_plugins() is None
        assert active_run_model_plugin_roots() == ()


class TestEveryChildReceivesTheSameSet:
    """PER CHILD, behaviourally — not once, and not only structurally.

    Step 11's `F-11-C10-a` is the reason this is asserted three times: two
    surfaces that were supposed to read one authority disagreed, and only a
    real run noticed. A structural check that all three spawn sites call the
    same helper cannot see a site that calls it and then overwrites the
    result.
    """

    DECLARED_ROOT = "/declared/pack/plugins"

    def _binding(self):
        return RunModelPluginBinding(
            roots=(self.DECLARED_ROOT,), required_model_types=("dp_x",), plugins=()
        )

    def _assert_carries_both(self, env, sandbox):
        roots = env[PLUGIN_DIRS_ENV_VAR].split(os.pathsep)
        assert self.DECLARED_ROOT in roots, "the run's declared root did not reach this child"
        assert sandbox.plugin_dir in roots, "the child's own workspace dir was dropped"

    def test_the_training_child(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from core.sandbox_executor import TidmadSandbox

        sandbox = TidmadSandbox(run_name="dp", workspace=str(tmp_path), progress_bar=False)
        with patch("core.sandbox_executor._run_observed_subprocess") as run:

            def _ok(*_args, **_kwargs):
                os.makedirs(sandbox.dirs["models"], exist_ok=True)
                open(os.path.join(sandbox.dirs["models"], "_OK_dp_exp"), "wb").close()
                result = MagicMock()
                result.returncode, result.stdout, result.stderr = 0, "done\n", ""
                return result, None

            run.side_effect = _ok
            with bind_run_model_plugins(self._binding()):
                sandbox.execute_training(
                    "dp_exp",
                    "dp",
                    "fcnet",
                    {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]},
                    {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                    {"loss_type": "ce"},
                    sample_set={0: [1]},
                )
        self._assert_carries_both(run.call_args.kwargs["env"], sandbox)

    def test_the_inference_child(self, tmp_path):
        from unittest.mock import MagicMock, patch

        from core.sandbox_executor import TidmadSandbox

        sandbox = TidmadSandbox(run_name="dp", workspace=str(tmp_path), progress_bar=False)
        cfg_dir = sandbox.dirs["configs"]
        os.makedirs(cfg_dir, exist_ok=True)
        for name in ("model_config_dp_exp.json", "loss_config_dp_exp.json"):
            (pathlib.Path(cfg_dir) / name).write_text("{}", encoding="utf-8")
        open(os.path.join(sandbox.dirs["models"], "model_fcnet_dp_exp_agent.pth"), "w").close()
        with patch("core.sandbox_executor._run_observed_subprocess") as run:
            result = MagicMock()
            result.returncode, result.stdout, result.stderr = 0, "done\n", ""
            run.return_value = (result, None)
            with bind_run_model_plugins(self._binding()):
                sandbox.execute_inference(
                    "dp_exp",
                    "dp",
                    "fcnet",
                    {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]},
                    {"loss_type": "ce"},
                    sample_set={0: [1]},
                )
        self._assert_carries_both(run.call_args.kwargs["env"], sandbox)

    def test_the_scoring_child(self, tmp_path):
        from unittest.mock import MagicMock, mock_open, patch

        from core.sandbox_executor import TidmadSandbox

        sandbox = TidmadSandbox(run_name="dp", workspace=str(tmp_path), progress_bar=False)
        with patch("core.sandbox_executor.subprocess.run") as run:
            result = MagicMock()
            result.returncode, result.stdout, result.stderr = 0, "done\n", ""
            run.return_value = result
            with (
                patch("builtins.open", mock_open(read_data=json.dumps({"denoising_score": 0.9}))),
                patch("os.path.exists", return_value=True),
                patch("os.remove"),
                bind_run_model_plugins(self._binding()),
            ):
                sandbox.execute_scoring(
                    "dp_exp",
                    "dp",
                    "fcnet",
                    {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]},
                    {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"},
                    {"loss_type": "ce"},
                )
        self._assert_carries_both(run.call_args.kwargs["env"], sandbox)


# ======================================================================
# Cross-root collision — falsifier 3
# ======================================================================


class TestCrossRootCollision:
    """Scan order must never decide which implementation runs."""

    def test_one_model_type_from_two_directories_refuses(self, tmp_path, monkeypatch):
        from ml_models.plugin_loader import extend_registries

        first, second = tmp_path / "pack", tmp_path / "generated"
        write_plugin(first, "dp_collide_net", width=4)
        write_plugin(second, "dp_collide_net", width=99)
        monkeypatch.setenv(PLUGIN_DIRS_ENV_VAR, os.pathsep.join([str(first), str(second)]))
        with pytest.raises(ModelPluginResolutionError, match="more than one scanned plugin"):
            extend_registries({}, {})

    def test_a_single_directory_keeps_the_legacy_warn_and_overwrite(self, tmp_path, monkeypatch):
        """Legacy cannot reach the refusal: with one directory a model_type
        has exactly one origin, so the pre-DP behaviour is untouched."""
        from ml_models.plugin_loader import extend_registries

        plugins = tmp_path / "only"
        write_plugin(plugins, "dp_single_net")
        monkeypatch.setenv(PLUGIN_DIRS_ENV_VAR, str(plugins))
        registry: dict = {}
        assert extend_registries(registry, {}) == ["dp_single_net"]
        # A second scan re-registers over itself and must NOT refuse.
        assert extend_registries(registry, {}) == ["dp_single_net"]

    def test_two_directories_without_a_collision_are_fine(self, tmp_path, monkeypatch):
        from ml_models.plugin_loader import extend_registries

        write_plugin(tmp_path / "a", "dp_alpha_net")
        write_plugin(tmp_path / "b", "dp_beta_net")
        monkeypatch.setenv(
            PLUGIN_DIRS_ENV_VAR, os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])
        )
        assert sorted(extend_registries({}, {})) == ["dp_alpha_net", "dp_beta_net"]


# ======================================================================
# Provenance
# ======================================================================


class TestPluginProvenance:
    """Which implementation executed, from a persisted artifact."""

    def test_canonical_identity_excludes_the_host_path(self, tmp_path):
        write_plugin(tmp_path / "plugins", "dp_identity_net")
        binding = resolve_declared_model_plugins(
            configured_ref="plugins",
            root=str(tmp_path / "plugins"),
            required_model_types=("dp_identity_net",),
        )
        identity = binding.plugins[0].canonical_identity()
        assert set(identity) == {"configured_ref", "member", "model_type", "content_sha256"}
        assert str(tmp_path) not in json.dumps(identity), (
            "the same pack at two absolute paths must pin ONE identity"
        )

    def test_the_lock_RECORDS_the_identities_and_never_compares_them(self):
        from core.run_invariants import RunInvariants

        assert "model_plugin_identities" in RunInvariants._PROVENANCE
        assert "model_plugin_identities" not in RunInvariants._CANONICAL

    def test_an_unbound_run_writes_no_key(self, tmp_path):
        """A legacy lock stays byte-identical rather than gaining a null."""
        from core.run_invariants import RunInvariants, write_run_invariants

        invariants = RunInvariants(
            resolved_data_scope=[0],
            health_gate_enabled=False,
            health_config_sha256=None,
            runtime_estimator_identity="e",
            runtime_policy_identity="p",
        )
        path = write_run_invariants(str(tmp_path), invariants)
        assert "model_plugin_identities" not in json.loads(pathlib.Path(path).read_text())

    def test_a_bound_run_records_the_identities_it_resolved(self, tmp_path):
        from core.run_invariants import RunInvariants, write_run_invariants

        binding = RunModelPluginBinding(
            roots=("/pack/plugins",),
            required_model_types=("dp_recorded_net",),
            plugins=(
                ResolvedModelPlugin(
                    configured_ref="plugins",
                    member="dp_recorded_net.py",
                    model_type="dp_recorded_net",
                    content_sha256="a" * 64,
                    absolute_path="/pack/plugins/dp_recorded_net.py",
                ),
            ),
        )
        invariants = RunInvariants(
            resolved_data_scope=[0],
            health_gate_enabled=False,
            health_config_sha256=None,
            runtime_estimator_identity="e",
            runtime_policy_identity="p",
            model_plugin_identities=binding.canonical_identities(),
        )
        payload = json.loads(
            pathlib.Path(write_run_invariants(str(tmp_path), invariants)).read_text()
        )
        assert payload["model_plugin_identities"] == [
            {
                "configured_ref": "plugins",
                "member": "dp_recorded_net.py",
                "model_type": "dp_recorded_net",
                "content_sha256": "a" * 64,
            }
        ]

    def test_the_recorded_digest_is_the_one_CAPTURED_at_resolution(self, tmp_path):
        """F-12bc-7, applied here rather than inherited as a slogan.

        The identity must be the value captured when the plugin was READ. A
        surface that re-derived it later would follow the very edit it exists
        to catch — which is exactly how ``G-12bc-C`` failed its first launch.
        """
        plugin = write_plugin(tmp_path / "plugins", "dp_capture_net", width=4)
        binding = resolve_declared_model_plugins(
            configured_ref="plugins",
            root=str(tmp_path / "plugins"),
            required_model_types=("dp_capture_net",),
        )
        captured = binding.canonical_identities()
        plugin.write_text(plugin.read_text() + "\n# edited after resolution\n", encoding="utf-8")
        assert binding.canonical_identities() == captured, (
            "the binding re-read the file — a pinned identity that follows the "
            "edit cannot detect the edit"
        )
        assert hashlib.sha256(plugin.read_bytes()).hexdigest() != captured[0]["content_sha256"], (
            "the fixture must actually have changed the bytes"
        )


# ======================================================================
# Legacy
# ======================================================================


class TestLegacyUnchanged:
    """Every un-composed caller behaves exactly as it did before seam P."""

    def test_no_binding_and_no_ambient_leaves_the_variable_unset(self, monkeypatch):
        monkeypatch.delenv(PLUGIN_DIRS_ENV_VAR, raising=False)
        assert PLUGIN_DIRS_ENV_VAR not in subprocess_env()

    def test_no_binding_transports_exactly_the_supplied_directory(self, monkeypatch):
        monkeypatch.delenv(PLUGIN_DIRS_ENV_VAR, raising=False)
        assert subprocess_env(plugin_dir="/legacy/dir")[PLUGIN_DIRS_ENV_VAR] == "/legacy/dir"

    def test_no_binding_and_no_ambient_resolves_the_global_library_dirs(self, monkeypatch):
        """Seam-P concern preserved: with NO run-scoped binding and NO env
        var, the scan must resolve to the GLOBAL library — never to a
        declared root that isn't there. arXiv P1 amended what "the global
        library" is: the resolved generated-library models dir first, then
        the legacy checkout AGENT_GENERATED_DIR as read-only compatibility.
        The binding-absence property this class owns is unchanged — the
        list still contains no declared roots."""
        from core.generated_library import generated_models_dir
        from ml_models.plugin_loader import AGENT_GENERATED_DIR, _resolve_plugin_dirs

        monkeypatch.delenv(PLUGIN_DIRS_ENV_VAR, raising=False)
        assert _resolve_plugin_dirs() == [generated_models_dir(), AGENT_GENERATED_DIR]

    def test_an_ambient_list_still_suppresses_the_legacy_global_dir(self, monkeypatch):
        from ml_models.plugin_loader import AGENT_GENERATED_DIR, _resolve_plugin_dirs

        monkeypatch.setenv(PLUGIN_DIRS_ENV_VAR, "/a::/b:")
        assert _resolve_plugin_dirs() == ["/a", "/b"]
        assert AGENT_GENERATED_DIR not in _resolve_plugin_dirs()

    def test_the_loss_transport_is_untouched(self, monkeypatch):
        from core.subprocess_env import LOSS_DIRS_ENV_VAR

        monkeypatch.delenv(LOSS_DIRS_ENV_VAR, raising=False)
        assert subprocess_env(loss_dir="/loss/dir")[LOSS_DIRS_ENV_VAR] == "/loss/dir"


# ======================================================================
# The real-child witness
# ======================================================================

_CHILD_PROGRAM = textwrap.dedent(
    """
    import hashlib, inspect, json, sys
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY

    name = sys.argv[1]
    cls = MODEL_REGISTRY[name]
    model = cls(PLUGIN_CONFIG_REGISTRY[name]())
    source_file = inspect.getsourcefile(cls)
    with open(source_file, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    print("SIDERIUS_DP_RESULT " + json.dumps({
        "model_type": name,
        "executed_width": int(model.width),
        "source_file": source_file,
        "content_sha256": digest,
        "registry_size": len(MODEL_REGISTRY),
    }))
    """
)


@pytest.mark.allow_real_subprocess
class TestRealChildProcess:
    """DP's integration witness: a REAL child resolves and EXECUTES the plugin.

    Deliberately NOT a training child: the failure class is *availability and
    provenance across a process boundary*, and it is fully observable at the
    point the child constructs the model. Requiring a training run would blur
    it into `G-12d`'s class and duplicate its cost (§14a.0's "stop at the
    witness").
    """

    def _run_child(self, env, model_type):
        result = subprocess.run(
            [sys.executable, "-c", _CHILD_PROGRAM, model_type],
            env=env,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        return result

    def test_a_real_child_resolves_executes_and_identifies_the_declared_plugin(self, tmp_path):
        plugin = write_plugin(tmp_path / "pack_plugins", "dp_child_net", width=11)
        binding = resolve_declared_model_plugins(
            configured_ref="pack_plugins",
            root=str(tmp_path / "pack_plugins"),
            required_model_types=("dp_child_net",),
        )
        workspace_dir = tmp_path / "workspace_plugins"
        workspace_dir.mkdir()
        with bind_run_model_plugins(binding):
            env = subprocess_env(plugin_dir=str(workspace_dir))

        # The transported set carries BOTH — the child's own workspace dir
        # and the run's declared pack root.
        assert set(env[PLUGIN_DIRS_ENV_VAR].split(os.pathsep)) == {
            str(workspace_dir),
            str(tmp_path / "pack_plugins"),
        }

        result = self._run_child(env, "dp_child_net")
        assert result.returncode == 0, f"child failed:\n{result.stdout}\n{result.stderr}"
        line = next(ln for ln in result.stdout.splitlines() if ln.startswith("SIDERIUS_DP_RESULT "))
        payload = json.loads(line[len("SIDERIUS_DP_RESULT ") :])

        assert payload["model_type"] == "dp_child_net"
        assert payload["executed_width"] == 11, "the child EXECUTED the declared implementation"
        assert payload["source_file"] == str(plugin), (
            "the child resolved THAT file, not a same-named one elsewhere"
        )
        assert payload["content_sha256"] == binding.plugins[0].content_sha256, (
            "the identity the parent pinned is the identity that executed"
        )

    def test_a_real_child_without_the_declared_root_cannot_resolve_it(self, tmp_path):
        """The counterfactual that makes the test above non-vacuous.

        Same child, same plugin on disk — only the transport removed. If this
        passed, the positive result would prove nothing about propagation.
        """
        write_plugin(tmp_path / "pack_plugins", "dp_absent_net")
        env = subprocess_env(plugin_dir=str(tmp_path / "empty"))
        (tmp_path / "empty").mkdir()
        result = self._run_child(env, "dp_absent_net")
        assert result.returncode != 0
        assert "KeyError" in result.stderr


def test_this_module_and_the_authority_agree_on_one_merge_implementation():
    """No duplicated child-side merge logic (§E.2's explicit prohibition)."""
    loader = (REPO_ROOT / "ml_models" / "plugin_loader.py").read_text(encoding="utf-8")
    transport = (REPO_ROOT / "core" / "subprocess_env.py").read_text(encoding="utf-8")
    for source in (loader, transport):
        assert "union_plugin_roots" in source
    merge_definitions = [
        node.name
        for node in ast.walk(ast.parse((REPO_ROOT / "ml_models" / "plugin_binding.py").read_text()))
        if isinstance(node, ast.FunctionDef) and node.name == "union_plugin_roots"
    ]
    assert merge_definitions == ["union_plugin_roots"], "exactly one merge authority"
