"""Validate inert operator resources without composing tasks or constructing clients."""

from pathlib import Path

from .files import canonical, private_bytes, token
from .models import ConsoleConfig


def validate_config(config: ConsoleConfig) -> ConsoleConfig:
    config = ConsoleConfig.model_validate_json(config.model_dump_json())
    store = config.operation_store
    canonical(store.state_root)
    for root in (*store.preparation_roots, *store.candidate_roots):
        if not canonical(root).is_dir():
            raise ValueError("configured output roots must exist")
    for task in config.tasks:
        for root, allowed in (
            (task.preparation_root, store.preparation_roots),
            (task.candidate_root, store.candidate_roots),
        ):
            path = canonical(root)
            if not path.is_dir() or not any(
                path.is_relative_to(Path(parent)) for parent in allowed
            ):
                raise ValueError("task output root is outside operation store roots")
        if not canonical(task.data_root).is_dir():
            raise ValueError("configured data root must exist")
        for name in (task.task_manifest, task.llm_config_file):
            if not canonical(name).is_file():
                raise ValueError("configured resource file must exist")
        for name in task.task_read_only:
            if not canonical(name).exists():
                raise ValueError("configured dependency must exist")
    token(config.auth_token_file)
    if config.credential_file is not None:
        # Validate private file facts and JSON shape, without selecting/printing values.
        from pydantic import TypeAdapter

        TypeAdapter(dict[str, str]).validate_json(
            private_bytes(config.credential_file), strict=True
        )
    return config


def load_config(path: str) -> ConsoleConfig:
    source = canonical(path)
    with source.open("rb") as stream:
        payload = stream.read(256 * 1024 + 1)
    if len(payload) > 256 * 1024:
        raise ValueError("console configuration exceeds limit")
    return validate_config(ConsoleConfig.model_validate_json(payload))
