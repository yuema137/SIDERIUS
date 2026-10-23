"""Stage generated model source; retain current declared package members."""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING

from core.generated_artifact_name import validate_generated_artifact_name
from ml_models.plugin_binding import (
    active_run_model_plugins,
    declared_package_model,
    require_declared_model_source,
)
from ml_models.plugin_loader import register_model_in_memory

if TYPE_CHECKING:
    from agent.schemas.implementor import ImplementorOutput


def _save_forensic_source(source: str, model_name: str) -> None:
    """Keep source before construction can OOM (2026-06-24 v15 incident).

    The workspace-root sentinel survives iteration cleanup; failures remain
    best-effort diagnostics and never block ordinary generated registration.
    """
    try:
        root = os.environ.get("SIDERIUS_CHAIN_WORKSPACE", os.path.dirname(os.path.dirname(source)))
        directory = os.path.join(root, "plugin_source_sentinel")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{model_name}.py")
        shutil.copy2(source, path)
        print(f"    [DEBUG] Plugin source saved to sentinel: {path}", flush=True)
    except Exception as exc:
        print(f"    [DEBUG] Plugin source sentinel write skipped ({type(exc).__name__}: {exc})")


def _copy_generated_model(source: str, model_name: str, destinations: list[str]) -> str | None:
    _save_forensic_source(source, model_name)
    primary = None
    for directory in destinations:
        os.makedirs(directory, exist_ok=True)
        target = os.path.join(directory, f"{model_name}.py")
        shutil.copy2(source, target)
        if primary is None:
            primary = target
        print(f"    Plugin registered → {target}")
    return primary


def _copy_description(source: str, model_name: str, destinations: list[str]) -> None:
    if not os.path.isfile(source):
        print(f"    Warning: description not found at {source}, skipping registration")
        return
    for directory in destinations:
        target_dir = os.path.join(directory, model_name)
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, "description.md")
        shutil.copy2(source, target)
        print(f"    Description registered → {target}")


def stage_model_source(
    source: str, description: str, model_name: str, destinations: list[str], *, model_type: str
) -> tuple[bool, str | None]:
    """Return source presence/path; an empty destination list is not missing source."""
    validate_generated_artifact_name(model_name, field="model_name")
    declared = declared_package_model(model_type, active_run_model_plugins())
    if declared is not None:
        require_declared_model_source(declared, source)
        primary = declared.absolute_path
    elif not os.path.isfile(source):
        print(f"    Warning: plugin file not found at {source}, skipping registration")
        return False, None
    else:
        primary = _copy_generated_model(source, model_name, destinations)
    _copy_description(description, model_name, destinations)
    return True, primary


def stage_native_plugins(
    impl_output: ImplementorOutput,
    model_name: str,
    dest_plugin_dirs: list[str] | str,
    dest_loss_dirs: list[str] | str | None = None,
) -> None:
    """
    Mirror validated plugin files to one or more destination dirs.

    Two destinations are typical in chain mode:

      * **Tuner-scoped** dir at ``{tuning_dir}/plugins/{run_name}/`` — the
        training/inference/scoring subprocess discovers plugins here via
        ``SIDERIUS_PLUGIN_DIRS`` (docs/run_scoped_plugins.md, Phase 4).
      * **Chain-canonical** dir at ``{workspace}/plugins/{run_name}/`` —
        ``core.resume.restore_prior_state`` looks here when later iters of
        the chain re-register prior plugins, and
        ``ml_models.model_descriptions.get_model_description`` walks
        ``{workspace}/plugins/iter_*/{model_type}/description.md`` to
        resolve agent-generated model descriptions on the next iter.

    Both dests receive identical files:

      - ``{model_file_path}``       → ``{dest}/{model_name}.py``
      - ``{description_file_path}`` → ``{dest}/{model_name}/description.md``

    The first dest in the list is treated as the primary; its ``.py`` is
    used to extend the in-process ``MODEL_REGISTRY`` /
    ``PLUGIN_CONFIG_REGISTRY`` so the tuner's planner (same Python process
    as the workflow) resolves the new model type without a re-scan.

    Accepts a single string for back-compat with older call sites and tests.

    L6a — loss-plugin propagation. When ``dest_loss_dirs`` is provided AND
    ``impl_output.loss_provenance.action == "generated"``, the loss plugin
    file at ``loss_provenance.loss_file_path`` is mirrored to each dest as
    ``{dest}/{loss_name}.py``. Callers typically pass both a tuner-scoped
    ``get_loss_dir(tuning_dir, run_name)`` (so the training subprocess's
    ``SIDERIUS_LOSS_DIRS`` resolves the plugin) and a chain-canonical
    ``get_loss_dir(workspace, run_name)`` (so resume / cross-iter Branch B
    reuse can find the same plugin without re-traversing the per-attempt
    tree). Pre-L6a, the implementor wrote the loss file to a per-attempt
    ``{attempt_dir}/losses/`` directory that no subsequent code copied
    anywhere, so training subprocesses could never load it. Defaults to
    ``None`` for back-compat with all existing call sites and unit tests.
    Skipped silently when ``loss_provenance is None`` (built-in loss path)
    or when ``loss_provenance.action == "reused"`` (the chain-canonical
    copy from the originating iter is expected to still exist).

    Skips gracefully if source files don't exist (e.g. unit tests with mocks).
    """
    loss_prov = getattr(impl_output, "loss_provenance", None)
    if dest_loss_dirs is not None and loss_prov is not None and loss_prov.action == "generated":
        validate_generated_artifact_name(loss_prov.loss_name, field="loss_provenance.loss_name")
    if isinstance(dest_plugin_dirs, str):
        dest_plugin_dirs = [dest_plugin_dirs]

    source_available, primary_plugin = stage_model_source(
        impl_output.model_file_path,
        impl_output.description_file_path,
        model_name,
        dest_plugin_dirs,
        model_type=getattr(impl_output, "model_type", model_name),
    )
    if not source_available:
        return

    # L6a — loss plugin propagation. Only mirror on "generated" so reused
    # losses (Branch B) don't double-copy onto themselves on every iter.
    loss_prov = getattr(impl_output, "loss_provenance", None)
    if dest_loss_dirs is not None and loss_prov is not None and loss_prov.action == "generated":
        if isinstance(dest_loss_dirs, str):
            loss_dest_list = [dest_loss_dirs]
        else:
            loss_dest_list = list(dest_loss_dirs)
        if not os.path.isfile(loss_prov.loss_file_path):
            print(
                f"    Warning: loss plugin file not found at "
                f"{loss_prov.loss_file_path}, skipping loss registration"
            )
        else:
            for d in loss_dest_list:
                os.makedirs(d, exist_ok=True)
                dest_loss = os.path.join(d, f"{loss_prov.loss_name}.py")
                shutil.copy2(loss_prov.loss_file_path, dest_loss)
                print(f"    Loss plugin registered → {dest_loss}")
            # L6c — also register in-memory so in-process pre-flight
            # (evaluate_vram_skill, evaluate_time_skill) resolves the plugin
            # without depending on SIDERIUS_LOSS_DIRS. First dest is
            # sufficient — same file regardless of dest. See
            # docs/design/enable_loss_inventory.md § L6c.
            from ml_models.loss_models_sandbox import register_loss_in_memory

            # L6c bug-fix — loss_dest_list[0] is a DIRECTORY; the plugin
            # file is at ``{dir}/{loss_name}.py``. Passing the directory
            # caused ``spec_from_file_location`` to return None silently,
            # leaving LOSS_REGISTRY empty and breaking every custom-loss
            # pre-flight (in-process callers fell through to filesystem
            # with no SIDERIUS_LOSS_DIRS set). Reconstruct the file path.
            _loss_file_for_registry = os.path.join(loss_dest_list[0], f"{loss_prov.loss_name}.py")
            _registered_loss = register_loss_in_memory(
                _loss_file_for_registry,
                loss_prov.contract_snapshot,
            )
            if _registered_loss is not None:
                print(f"    Loss '{_registered_loss}' added to in-memory LOSS_REGISTRY")

    if primary_plugin is None:
        # ``dest_plugin_dirs`` was empty after normalization — the copy loop
        # never ran, so there is nothing to register. Defensive guard; also
        # narrows ``primary_plugin`` from ``str | None`` to ``str`` for the
        # call below.
        return

    registered: str | None = None
    try:
        # Step 12 / PR-12a C6 — the PUBLIC registration authority.
        # `workflows._add_plugin_to_registries` was a private duplicate of it:
        # same `_load_plugin`, same three registries, same `model_type | None`
        # return. Its only behavioural difference was the absence of the
        # re-registration warning, which is strictly less visible.
        registered = register_model_in_memory(primary_plugin)
        if registered:
            print(f"    Model '{model_name}' added to registries (model_type='{registered}')")
    except Exception as e:
        from core.local_code.failure import raise_if_code_package_failure

        raise_if_code_package_failure(e)
        print(f"    Warning: could not extend registries: {e}")
