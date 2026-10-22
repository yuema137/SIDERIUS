"""#778 live sink witnesses: existing sources must not bypass component checks."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.unit.workflows.test_model_exploration import _make_proposal_output
from tests.unit.workflows.test_u6_impl_attempt_layout import _run_with_forced_retries
from workflows.model_exploration import (
    _promote_loss_to_global,
    _promote_model_to_global,
    _register_plugin,
)
from workflows.plugin_staging import stage_model_source


@pytest.mark.parametrize("sink", ["staging", "registration", "model_promotion", "loss_promotion"])
def test_direct_sink_rejects_before_copy_directory_or_registry(tmp_path, monkeypatch, sink):
    source = tmp_path / "source.py"
    source.write_text("# benign source\n")
    description = tmp_path / "description.md"
    description.write_text("Synthetic description\n")
    monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.setenv("SIDERIUS_CHAIN_WORKSPACE", str(tmp_path / "workspace"))
    output = SimpleNamespace(
        model_file_path=str(source),
        description_file_path=str(description),
        model_type="../escape" if sink == "model_promotion" else "safe_model",
        loss_provenance=SimpleNamespace(
            action="generated", loss_name="../escape", loss_file_path=str(source)
        ),
    )
    with pytest.raises(ValueError, match="filesystem component"):
        if sink == "staging":
            stage_model_source(
                str(source),
                str(description),
                "../escape",
                [str(tmp_path / "dest")],
                model_type="safe_model",
            )
        elif sink == "registration":
            _register_plugin(output, "safe_model", str(tmp_path / "dest"), str(tmp_path / "losses"))
        elif sink == "model_promotion":
            _promote_model_to_global(output)
        else:
            _promote_loss_to_global(output)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["description.md", "source.py"]


@pytest.mark.parametrize("fixed", [False, True])
def test_workflow_rejects_ordinary_and_fixed_names_before_rename_or_implement(
    tmp_path, fixed, capsys
):
    proposal = _make_proposal_output().model_copy(
        update={"model_name": "../escape", "candidate_id": "unsafe_candidate"}
    )
    overrides = (
        {"validation_fixed_candidate_plan": proposal.model_dump(mode="json")} if fixed else {}
    )
    with patch("workflows.model_exploration.os.rename", wraps=os.rename) as rename:
        result = _run_with_forced_retries(
            tmp_path, (True,), proposal_override=proposal, launch_overrides=overrides
        )
    assert not [
        call for call in rename.call_args_list if Path(call.args[0]).name.startswith("attempt_")
    ]
    assert result[2] == result[3] == result[4] == result[5] == []
    assert Path(result[0], "attempt_001").is_dir()
    assert not list(tmp_path.rglob("*escape*"))
    assert "filesystem component" in capsys.readouterr().out


def test_proposal_live_availability_rejects_without_archival_migration():
    proposal = _make_proposal_output().model_copy(update={"model_name": "../escape"})
    restored = type(proposal).model_validate_json(proposal.model_dump_json())
    with pytest.raises(ValueError, match="filesystem component"):
        restored.validate_model_name_availability([], [])
