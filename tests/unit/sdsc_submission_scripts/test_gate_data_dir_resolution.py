"""Explicit physical data-root validation at the supported launch boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from execute_tools.data_paths import DatasetDirectoryUnavailable, resolve_dataset_dir
from tests.helpers.launcher_bindings import effective_workflow_kwargs


def test_an_explicit_directory_is_accepted(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    assert resolve_dataset_dir(str(dataset)) == str(dataset)


def test_an_omitted_directory_refuses_with_remediation():
    with pytest.raises(DatasetDirectoryUnavailable) as exc:
        resolve_dataset_dir(None, purpose="the gate")
    assert "the gate" in str(exc.value)
    assert "--data_dir" in str(exc.value)


def test_a_nonexistent_directory_refuses_without_substitution(tmp_path):
    missing = tmp_path / "not-created"
    with pytest.raises(DatasetDirectoryUnavailable) as exc:
        resolve_dataset_dir(str(missing))
    assert str(missing) in str(exc.value)
    assert "--data_dir" in str(exc.value)


def test_a_file_is_not_a_directory(tmp_path):
    not_a_dir = tmp_path / "data.h5"
    not_a_dir.write_text("")
    with pytest.raises(DatasetDirectoryUnavailable):
        resolve_dataset_dir(str(not_a_dir))


class TestTheLaunchBoundary:
    @staticmethod
    def _argv(tmp_path, *extra):
        manifest = Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"
        return [
            "run_one_iteration.py",
            "--workspace",
            str(tmp_path / "ws"),
            "--run_name",
            "iter_001",
            "--start_iteration",
            "1",
            "--healthgate_mode",
            "blocking",
            "--result_authority",
            "scientific",
            "--task_composition",
            str(manifest),
            *extra,
        ]

    @staticmethod
    def _main(argv):
        from workflows import run_one_iteration as runner

        with patch.object(sys, "argv", argv):
            try:
                runner.main()
            except SystemExit as exc:
                return exc.code
        return 0

    def test_an_omitted_dataset_refuses_before_workflow(self, tmp_path, capsys):
        from workflows import run_one_iteration as runner

        with patch.object(runner, "run_workflow") as spy:
            code = self._main(self._argv(tmp_path))

        assert code == 2
        assert spy.call_count == 0
        assert "the following arguments are required: --data_dir" in capsys.readouterr().err

    def test_the_explicit_value_reaches_the_workflow_unchanged(self, tmp_path):
        dataset = tmp_path / "dataset"
        dataset.mkdir()
        from workflows import run_one_iteration as runner

        with patch.object(runner, "run_workflow", side_effect=SystemExit(0)) as spy:
            self._main(self._argv(tmp_path, "--data_dir", str(dataset)))

        assert spy.call_count == 1
        assert effective_workflow_kwargs(spy.call_args)["data_dir"] == str(dataset)


def test_no_machine_specific_dataset_path_is_tracked():
    repo = Path(__file__).resolve().parents[3]
    code_surfaces = [
        repo / "src/execute_tools/data_paths.py",
            repo / "src/workflows/run_one_iteration.py",
        repo / "scripts/launch/_chain_common.sh",
        repo / "scripts/launch/run_chain.sh",
    ]
    home_prefix = "/" + "home" + "/"
    offenders = [
        f"{path.name}:{line_number}: {line.strip()}"
        for path in code_surfaces
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if home_prefix in line and not line.lstrip().startswith("#")
    ]
    assert offenders == []
