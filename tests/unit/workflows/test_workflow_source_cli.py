"""Real offline CLI I/O witnesses from an external directory, no runtime launch."""

import subprocess
import sys

import pytest

from tests.unit.workflows.test_workflow_source import GOLDEN, SMALL_SOURCE, small_document
from workflows.definition import WorkflowDocument
from workflows.definition.source import MAX_INPUT_BYTES


def run_cli(directory, command, path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "workflows.definition", command, "--input", str(path), *extra],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )


def test_real_cli_both_directions_preserve_literal_references_without_resources(tmp_path):
    """Wrong entrypoint/binding/rebasing or project writes breaks output/bytes/files."""
    source = tmp_path / "workflow.py"
    source.write_text(SMALL_SOURCE)
    result = run_cli(tmp_path, "to-json", source)
    assert (result.returncode, result.stderr) == (0, "")
    assert WorkflowDocument.model_validate_json(result.stdout) == small_document()
    encoded = tmp_path / "workflow.json"
    encoded.write_text(small_document().model_dump_json())
    result = run_cli(tmp_path, "to-python", encoded)
    assert (result.returncode, result.stderr, result.stdout) == (0, "", GOLDEN)
    assert source.read_text() == SMALL_SOURCE
    assert encoded.read_text() == small_document().model_dump_json()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["workflow.json", "workflow.py"]
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    "command,content,family",
    [
        ("to-json", (SMALL_SOURCE + "print('SENTINEL_PRIVATE')\n").encode(), "unsupported"),
        ("to-json", SMALL_SOURCE.replace('binding="seed"', "binding=)").encode(), "syntax"),
        (
            "to-json",
            SMALL_SOURCE.replace('binding="seed"', 'binding="SENTINEL_PRIVATE"').encode(),
            "validation",
        ),
        ("to-json", b"\xff", "encoding"),
        ("to-json", b"#" * (MAX_INPUT_BYTES + 1), "limit"),
        ("to-python", b'{"SENTINEL_PRIVATE":', "validation"),
        ("to-python", b"\xff", "encoding"),
        ("to-python", b" " * (MAX_INPUT_BYTES + 1), "limit"),
        (
            "to-python",
            small_document()
            .model_dump_json()
            .replace('"binding":"seed"', '"binding":"SENTINEL_PRIVATE"')
            .encode(),
            "validation",
        ),
        (
            "to-python",
            small_document()
            .model_dump_json()
            .replace('"positions":[]', '"positions":[],"SENTINEL_PRIVATE":0')
            .encode(),
            "validation",
        ),
    ],
    ids=[
        "extra-statement",
        "syntax",
        "binding",
        "source-encoding",
        "source-size",
        "json-syntax",
        "json-encoding",
        "json-size",
        "json-binding",
        "json-extra",
    ],
)
def test_cli_failures_are_sanitized_empty_stdout_and_leave_input_bytes(
    tmp_path, command, content, family
):
    """Premature stdout or raw validation/syntax text leaks fail precise assertions."""
    source = tmp_path / "input"
    source.write_bytes(content)
    result = run_cli(tmp_path, command, source)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith(family)
    assert "SENTINEL_PRIVATE" not in result.stderr
    assert "Traceback" not in result.stderr
    assert source.read_bytes() == content
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_cli_file_failures_have_no_converted_output(tmp_path, kind):
    """Missing/non-file input must be an I/O refusal, not a traceback or partial JSON."""
    path = tmp_path / "input"
    if kind == "directory":
        path.mkdir()
    result = run_cli(tmp_path, "to-json", path)
    assert (result.returncode, result.stdout) == (2, "")
    assert result.stderr.startswith("io:")


def test_cli_rejects_output_path_option(tmp_path):
    """An accidental writer flag must not create an overwrite surface."""
    source = tmp_path / "workflow.py"
    source.write_text(SMALL_SOURCE)
    output = tmp_path / "output.py"
    result = run_cli(tmp_path, "to-json", source, "--output", str(output))
    assert (result.returncode, result.stdout) == (2, "")
    assert not output.exists()
    assert source.read_text() == SMALL_SOURCE
