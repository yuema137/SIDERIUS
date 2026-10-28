"""Compose the optional ``judge_blocks:`` and ``rubrics:`` manifest sections.

Called only by :func:`workflows.task_composition.compose_run_task_bindings`,
which owns manifest reading, ref resolution and error wrapping. This module owns
the two sections' shapes and loads each declaration file through the shared
fail-closed task-blocks mechanics. Schemas live in ``agent.schemas.judge_task``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agent.prompt_templates._task_blocks_loader import load_task_blocks_declaration
from agent.schemas.judge_task import JudgeTaskBlocks, JudgeTaskDeclarations, RubricSpec


@dataclass(frozen=True, slots=True)
class ComposedJudgeTask:
    declarations: JudgeTaskDeclarations | None
    source_paths: dict[str, str]
    """Declaration-file roles: ``judge_blocks`` and ``rubric[<index>]``."""


def _config_ref(entry: object, where: str) -> str:
    if not isinstance(entry, Mapping):
        raise ValueError(f"{where} must be a mapping; got {type(entry).__name__}")
    unknown = sorted(set(entry) - {"config"})
    if unknown:
        raise ValueError(f"{where} declares unknown key(s) {unknown}")
    ref = entry.get("config")
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError(f"{where} requires a non-empty string 'config'; got {ref!r}")
    return ref


def _compose_blocks(
    section: object, resolve_ref: Callable[[str], str]
) -> tuple[JudgeTaskBlocks | None, str | None]:
    if section is None:
        return None, None
    if isinstance(section, Mapping) and section.get("none") is True and set(section) == {"none"}:
        return None, None
    path = resolve_ref(_config_ref(section, "section 'judge_blocks'"))
    return load_task_blocks_declaration(JudgeTaskBlocks, path=path, kind="judge"), path


def _compose_rubrics(
    section: object, resolve_ref: Callable[[str], str]
) -> tuple[tuple[RubricSpec, ...], dict[str, str]]:
    if section is None:
        return (), {}
    if not isinstance(section, list):
        raise ValueError(f"section 'rubrics' must be a list; got {type(section).__name__}")
    specs: list[RubricSpec] = []
    paths: dict[str, str] = {}
    for index, entry in enumerate(section):
        path = resolve_ref(_config_ref(entry, f"rubrics[{index}]"))
        specs.append(load_task_blocks_declaration(RubricSpec, path=path, kind="rubric"))
        paths[f"rubric[{index}]"] = path
    return tuple(specs), paths


def compose_judge_task(
    raw: Mapping[str, Any], resolve_ref: Callable[[str], str]
) -> ComposedJudgeTask:
    """Resolve both optional sections. Absent, ``none: true`` or empty ⇒ ``None``.

    Raises ``ValueError`` / ``FileNotFoundError`` on any malformed section or
    declaration file, including duplicate criterion names within a rubric and a
    rubric ``(id, version)`` declared twice.
    """
    blocks, blocks_path = _compose_blocks(raw.get("judge_blocks"), resolve_ref)
    rubrics, source_paths = _compose_rubrics(raw.get("rubrics"), resolve_ref)
    if blocks_path is not None:
        source_paths["judge_blocks"] = blocks_path
    if blocks is None and not rubrics:
        return ComposedJudgeTask(declarations=None, source_paths=source_paths)
    return ComposedJudgeTask(
        declarations=JudgeTaskDeclarations(blocks=blocks, rubrics=rubrics),
        source_paths=source_paths,
    )
