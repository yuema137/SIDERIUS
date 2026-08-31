"""Framework prompt adapters contain no implicit task-default authority."""

from pathlib import Path


def test_task_block_adapters_define_no_legacy_task_default() -> None:
    root = Path(__file__).resolve().parents[3] / "agent" / "prompt_templates"
    sources = "\n".join(path.read_text() for path in sorted(root.rglob("task_blocks.py")))
    assert "LEGACY_DEFAULT_TASK_" not in sources
