"""The launch-time dataset-directory resolution preflight.

**The failure this exists to prevent**, observed for real during PR 04a's
Gate validation: a canonical Gate launch omits ``--data_dir`` (which is
correct — the chain shell deliberately stopped injecting a hardcoded path),
the value travels to the tuner as ``None``, and the pre-phase GPU measurement
fails closed with *"dataset directory unavailable for the measurement: None"*
— **after** a real LLM had already generated, validated and registered a
candidate. Roughly ten minutes of paid work, discarded, for a fact knowable at
launch.

The invariant these tests pin:

    launch configuration
      -> ONE existing authority for the physical dataset location
      -> resolved AND validated BEFORE any expensive work
      -> the same resolved value reaches every downstream consumer

Two things are deliberately NOT re-decided here. The precedence
(explicit override > machine-local config) is the one
``core/runtime_control/probe_production.py`` already documents as **F-1a**,
and the "shell omits the flag so the Python layer resolves it" contract is
already asserted by ``test_chain_data_dir_portability.py``. What was missing
was any code performing that resolution on the launch path.

Portability: every path here is a ``tmp_path`` fixture. No lab path is
tracked — the real location lives only in a gitignored per-machine config.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from execute_tools.data_paths import (
    DatasetDirectoryUnavailable,
    resolve_dataset_dir,
)

# ---------------------------------------------------------------------------
# A. RESOLUTION — the authority answers when no override is given
# ---------------------------------------------------------------------------


def test_the_machine_local_config_answers_when_no_override(tmp_path):
    """With no ``--data_dir``, ``TIDMAD_DATA_DIR`` is the source.

    Fails when: the resolver stops consulting the single source of truth —
    which is precisely the state that produced ``data_dir=None`` downstream.
    """
    configured = tmp_path / "configured_dataset"
    configured.mkdir()
    with patch("execute_tools.data_paths.TIDMAD_DATA_DIR", str(configured)):
        assert resolve_dataset_dir(None) == str(configured)


def test_an_explicit_override_wins(tmp_path):
    """C. Explicit operator override takes precedence — the F-1a ordering.

    Fails when: the precedence inverts, so an operator pointing a run at a
    second copy of the data is silently ignored.
    """
    configured = tmp_path / "configured"
    override = tmp_path / "override"
    configured.mkdir()
    override.mkdir()
    with patch("execute_tools.data_paths.TIDMAD_DATA_DIR", str(configured)):
        assert resolve_dataset_dir(str(override)) == str(override)


# ---------------------------------------------------------------------------
# D/E. MISSING and INVALID location — fail closed, with an actionable message
# ---------------------------------------------------------------------------


def test_an_unset_authority_refuses(tmp_path):
    with patch("execute_tools.data_paths.TIDMAD_DATA_DIR", ""):
        with pytest.raises(DatasetDirectoryUnavailable) as exc:
            resolve_dataset_dir(None, purpose="the gate")
    message = str(exc.value)
    assert "the gate" in message
    assert "--data_dir" in message, "the message must say how to supply one"


def test_a_nonexistent_directory_refuses_and_names_the_source(tmp_path):
    """E. The resolved path must actually be a readable directory.

    The message has to name WHICH authority produced the bad value, because
    "not a readable directory" is useless if the operator cannot tell whether
    their override or the machine config is at fault.
    """
    missing = tmp_path / "not_created"
    with patch("execute_tools.data_paths.TIDMAD_DATA_DIR", str(missing)):
        with pytest.raises(DatasetDirectoryUnavailable) as exc:
            resolve_dataset_dir(None)
    assert "tidmad_data_config.yaml" in str(exc.value)

    with pytest.raises(DatasetDirectoryUnavailable) as exc:
        resolve_dataset_dir(str(missing))
    assert "--data_dir" in str(exc.value)


def test_a_file_is_not_a_directory(tmp_path):
    not_a_dir = tmp_path / "data.h5"
    not_a_dir.write_text("")
    with pytest.raises(DatasetDirectoryUnavailable):
        resolve_dataset_dir(str(not_a_dir))


def test_the_template_fallback_is_named_in_the_message(tmp_path):
    """A fresh clone gets the tracked TEMPLATE's placeholder path.

    That is the single most confusing way this can fail — the value looks
    like a real path but nobody ever set it. The message must say so.

    Fails when: the template case degrades to a bare "not a directory".
    """
    import execute_tools.data_paths as dp

    missing = tmp_path / "placeholder"
    with (
        patch.object(dp, "TIDMAD_DATA_DIR", str(missing)),
        patch.object(dp, "_active_config_path", dp._EXAMPLE_CONFIG_PATH),
    ):
        with pytest.raises(DatasetDirectoryUnavailable) as exc:
            resolve_dataset_dir(None)
    assert "TEMPLATE" in str(exc.value)


# ---------------------------------------------------------------------------
# F. NO SILENT FALLBACK
# ---------------------------------------------------------------------------


def test_it_never_substitutes_a_different_directory(tmp_path):
    """A bad override is refused, NOT quietly replaced by the config value.

    Fails when: the resolver "helpfully" falls back to the machine config
    after an explicit override fails — which would run a chain against data
    the operator did not select, and is exactly the silent-substitution class
    F-1a forbids.
    """
    good = tmp_path / "configured"
    good.mkdir()
    bad = tmp_path / "operator_typo"
    with patch("execute_tools.data_paths.TIDMAD_DATA_DIR", str(good)):
        with pytest.raises(DatasetDirectoryUnavailable):
            resolve_dataset_dir(str(bad))


# ---------------------------------------------------------------------------
# B + the expensive boundary — the whole point of the maintenance
# ---------------------------------------------------------------------------


class TestTheLaunchBoundary:
    """``main()`` must resolve/refuse before any LLM or workflow work."""

    @staticmethod
    def _argv(tmp_path, *extra):
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
            *extra,
        ]

    def _main(self, argv):
        from sdsc_submission_scripts import run_one_iteration as runner

        with patch.object(sys, "argv", argv):
            try:
                runner.main()
            except SystemExit as exc:
                return exc.code
        return 0

    def test_an_unresolvable_dataset_refuses_BEFORE_any_workflow_call(self, tmp_path, capsys):
        """**The reachability proof this PR exists for.**

        With nothing resolvable, ``main()`` must exit non-zero and
        ``run_workflow`` — the function behind every LLM call, candidate
        generation and training subprocess — must never be invoked.

        Fails when: the refusal moves after the expensive work, restoring the
        exact failure PR 04a hit.
        """
        missing = tmp_path / "nope"
        from sdsc_submission_scripts import run_one_iteration as runner

        with (
            patch("execute_tools.data_paths.TIDMAD_DATA_DIR", str(missing)),
            patch.object(runner, "run_workflow") as spy,
        ):
            code = self._main(self._argv(tmp_path))

        assert code == 2
        assert spy.call_count == 0, "expensive work started despite an unusable dataset"
        assert "LAUNCH REFUSED" in capsys.readouterr().err

    def test_the_resolved_value_replaces_None_on_the_way_to_the_tuner(self, tmp_path):
        """B. TRANSPORT, by value.

        The launcher must hand ``run_workflow`` the RESOLVED directory, not
        the ``None`` it was invoked with. A distinguishable tmp path is used
        so a silently substituted default would fail this.
        """
        configured = tmp_path / "resolved_here"
        configured.mkdir()
        from sdsc_submission_scripts import run_one_iteration as runner

        with (
            patch("execute_tools.data_paths.TIDMAD_DATA_DIR", str(configured)),
            # Stop the moment the value has been observed: everything after
            # run_workflow is manifest bookkeeping this test does not assert.
            patch.object(runner, "run_workflow", side_effect=SystemExit(0)) as spy,
        ):
            self._main(self._argv(tmp_path))

        assert spy.call_count == 1
        assert spy.call_args.kwargs["data_dir"] == str(configured)

    def test_an_explicit_override_reaches_the_tuner_unchanged(self, tmp_path):
        configured = tmp_path / "configured"
        override = tmp_path / "override"
        configured.mkdir()
        override.mkdir()
        from sdsc_submission_scripts import run_one_iteration as runner

        with (
            patch("execute_tools.data_paths.TIDMAD_DATA_DIR", str(configured)),
            patch.object(runner, "run_workflow", side_effect=SystemExit(0)) as spy,
        ):
            self._main(self._argv(tmp_path, "--data_dir", str(override)))

        assert spy.call_args.kwargs["data_dir"] == str(override)


# ---------------------------------------------------------------------------
# G. PORTABILITY
# ---------------------------------------------------------------------------


def test_no_machine_specific_dataset_path_is_tracked():
    """No lab-specific absolute path may become the dataset MECHANISM.

    The point of resolving through a gitignored per-machine config is that
    the fix does not bake one host's layout into the repository. This guards
    the surfaces that could reintroduce that: the resolver, the launcher, the
    chain shell, and any ``--data_dir`` example in the Gate standard.

    **Deliberately NOT a blanket ban on absolute paths in documentation.**
    The Gate standard keeps two historical ``--seed_paths`` values under a
    heading that reads *"historical reference — DO NOT USE for new tests"*,
    retained so old gate logs stay interpretable. CLAUDE.md allows operator
    documentation to name known deployments; what it forbids is an implicit
    machine dependency in executable code and tests. Those seed lines are
    neither, and they are out of this PR's scope — so the assertion targets
    the dataset mechanism, not every string that looks like a path.

    Fails when: someone "fixes" a future data-dir problem by pasting a real
    path into the resolver, the launcher, the chain shell, or the canonical
    Gate command.
    """
    import pathlib
    import re

    repo = pathlib.Path(__file__).resolve().parents[3]
    # Assembled at runtime so this guard does not itself contain the literals
    # it forbids — otherwise it could only ever fail on itself.
    home = "/" + "home" + "/"

    code_surfaces = [
        repo / "execute_tools" / "data_paths.py",
        repo / "sdsc_submission_scripts" / "run_one_iteration.py",
        repo / "sdsc_submission_scripts" / "_chain_common.sh",
        repo / "sdsc_submission_scripts" / "run_chain.sh",
    ]
    offenders = [
        f"{p.name}:{i}: {line.strip()}"
        for p in code_surfaces
        if p.exists()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if home in line and not line.lstrip().startswith("#")
    ]

    # The Gate standard: only ``--data_dir`` usages are in scope here.
    standard = repo / "docs" / "gates" / "gate_testing_standard.md"
    if standard.exists():
        offenders += [
            f"gate_testing_standard.md:{i}: {line.strip()}"
            for i, line in enumerate(standard.read_text(encoding="utf-8").splitlines(), 1)
            if "--data_dir" in line and re.search(re.escape(home) + r"\S", line)
        ]

    assert not offenders, f"machine-specific dataset path entered tracked source: {offenders}"
