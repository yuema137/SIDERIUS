"""C12-P — the physical dataset root must be resolved once and reach the tuner.

**The failures these exist to prevent, both observed for real.**

PR-12d's TIDMAD attempts 5 and 6 were blocked by ONE defect with TWO
consumers: ``scripts/run_comparison.py`` never forwarded ``data_dir`` to the
tuner, so ``agent_input.data_dir`` arrived as ``None`` and runtime-control
refused — fail-closed, correctly, but only *after* a real LLM had generated,
validated and registered a candidate.

    armed time budget    -> core/runtime_control/probe_production.py
                            "no dataset directory was supplied to the probe"
    unarmed time budget  -> core/runtime_control/gpu_measurement_worker_main.py
                            "dataset directory unavailable for the measurement: None"

Arming the budget only chose which consumer reported it.

**Why a census, and not a third launcher-specific test.** This exact failure
string was already paid for once, in PR-04a, and
``tests/unit/sdsc_submission_scripts/test_gate_data_dir_resolution.py`` was
written to prevent it. That guard is correct and states the right invariant --
but it lives under ``sdsc_submission_scripts`` and therefore quantifies over
the SDSC launcher only, while ``scripts/run_comparison.py`` -- the launcher
CLAUDE.md documents as standard -- went unguarded. Adding a second
launcher-shaped test would leave launcher three exposed in the same way, so
the invariant is asserted over the *set* of launch boundaries instead.

The invariant, unchanged from the PR-04a guard that first stated it:

    launch configuration
      -> ONE existing authority for the physical dataset location
      -> resolved AND validated BEFORE any expensive work
      -> the same resolved value reaches every downstream consumer

Portability: no lab path is tracked. Every path here is a ``tmp_path``
fixture; the real location lives only in a gitignored per-machine config.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The ONE launch-boundary authority. Named, never re-implemented: it owns the
#: precedence (explicit override > machine-local config) and the fail-closed
#: refusal, and a second resolver would be a second convention.
AUTHORITY = "resolve_dataset_dir"

#: Every module that is a RUN LAUNCH ENTRY POINT -- where an operator starts a
#: run and where the physical root must therefore be resolved once, before any
#: expensive work. Declared explicitly rather than globbed: a census that
#: silently skipped a launcher would be the exact blindness this file exists to
#: correct (F-12bc-9 / F-P2b-4, and PR-04a's guard one launcher over).
LAUNCH_BOUNDARIES: tuple[str, ...] = (
    "scripts/run_comparison.py",
    "sdsc_submission_scripts/run_one_iteration.py",
)

#: The argv flag the resolved value travels on to the tuner.
DATA_DIR_FLAG = "--data_dir"


def _calls(rel: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            out.add(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            out.add(node.func.attr)
    return out


class TestEveryLaunchBoundaryResolvesThroughTheOneAuthority:
    @pytest.mark.parametrize("rel", LAUNCH_BOUNDARIES)
    def test_it_calls_the_authority(self, rel: str) -> None:
        """A launch entry point resolves the physical root before dispatching.

        DEFECT THIS TEST ALONE CATCHES
            A launcher that dispatches work without resolving the dataset
            root, so the value reaches the tuner as None and runtime-control
            refuses later -- PR-12d attempts 5/6, and PR-04a before them.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The named launcher stops calling `resolve_dataset_dir` and the
            assertion names it. Adding a launcher without the call also fails,
            once it is declared in LAUNCH_BOUNDARIES.
        """
        assert AUTHORITY in _calls(rel), (
            f"{rel} is a run launch boundary but never calls {AUTHORITY}(). "
            f"The physical dataset root must be resolved ONCE at launch, "
            f"through the single authority, and validated before any expensive "
            f"work. Without it the value reaches the tuner as None and "
            f"runtime-control refuses only after a real LLM has already "
            f"produced a candidate."
        )

    def test_the_census_file_set_is_real(self) -> None:
        """Non-vacuity: a census that cannot open its own file set is green for
        the wrong reason."""
        missing = [rel for rel in LAUNCH_BOUNDARIES if not (REPO_ROOT / rel).is_file()]
        assert missing == [], f"declared launch boundaries do not exist: {missing}"

    def test_the_authority_is_not_reimplemented_at_a_launcher(self) -> None:
        """The precedence and the refusal have ONE owner.

        DEFECT THIS TEST ALONE CATCHES
            A launcher that "resolves" the root itself -- reading the config,
            or defaulting to a path -- instead of calling the authority. That
            is how a second convention appears, and it is what 07c C4 removed
            from generic runtime-control in the first place.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            A launcher naming the module-level TIDMAD_DATA_DIR constant as a
            fallback for its own resolution turns this red.
        """
        for rel in LAUNCH_BOUNDARIES:
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "or TIDMAD_DATA_DIR" not in src, (
                f"{rel} appears to fall back to TIDMAD_DATA_DIR itself instead "
                f"of asking {AUTHORITY}(). The precedence belongs to the "
                f"authority; a launcher-local fallback is a second convention."
            )


class TestTheResolvedValueReachesTheTuner:
    def test_run_comparison_forwards_the_resolved_root(self) -> None:
        """The transport that was missing, pinned at the spawn site.

        DEFECT THIS TEST ALONE CATCHES
            PR-12d attempts 5 and 6 exactly: the launcher resolves the root
            (or would) but never puts it on the tuner's argv, so both
            runtime-control consumers still see None. Resolution without
            transport fixes nothing, and the census above cannot see it.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The flag disappears from the argv construction and the assertion
            names the file.
        """
        src = (REPO_ROOT / "scripts/run_comparison.py").read_text(encoding="utf-8")
        assert f'"{DATA_DIR_FLAG}"' in src, (
            f"scripts/run_comparison.py never places {DATA_DIR_FLAG} on the "
            f"tuner's argv. The resolved root does not reach the tuner, so "
            f"agent_input.data_dir is None and BOTH runtime-control consumers "
            f"refuse: probe_production.py ('no dataset directory was supplied') "
            f"and gpu_measurement_worker_main.py ('dataset directory "
            f"unavailable for the measurement: None')."
        )


class TestBothBlockedConsumersReadTheTransportedValue:
    """The two consumers reach the value by DIFFERENT paths, so both are pinned.

    A single assertion on one consumer would have passed while the other
    remained broken -- which is precisely how attempts 5 and 6 produced two
    different error strings from one missing transport.
    """

    def test_the_prephase_consumer_reads_agent_input_data_dir(self) -> None:
        """Consumer 2 (attempt 6): the pre-phase GPU measurement.

        DEFECT THIS TEST ALONE CATCHES
            The prephase measurement spec ceasing to source its data_dir from
            the tuner's input, which would silently re-introduce attempt 6's
            'dataset directory unavailable for the measurement: None' even
            after the launcher transport is repaired.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The read disappears from runtime.py and the assertion says so.
        """
        src = (REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/runtime.py").read_text(
            encoding="utf-8"
        )
        assert 'getattr(agent_input, "data_dir", None)' in src, (
            "the pre-phase GPU measurement no longer sources its dataset root "
            "from agent_input.data_dir; attempt 6's failure mode is no longer "
            "guarded by the launcher transport."
        )

    def test_the_probe_consumer_reads_the_bound_time_data_dir(self) -> None:
        """Consumer 1 (attempt 5): the bounded live probe.

        DEFECT THIS TEST ALONE CATCHES
            The probe lane ceasing to receive the run-scoped time_data_dir,
            re-introducing attempt 5's 'no dataset directory was supplied to
            the probe' independently of the launcher.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The threading disappears from execution.py and the assertion
            names it.
        """
        src = (REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/execution.py").read_text(
            encoding="utf-8"
        )
        assert "data_dir=time_data_dir" in src, (
            "the bounded live probe no longer receives time_data_dir; attempt "
            "5's failure mode is no longer guarded by the launcher transport."
        )


class TestMissingRootStaysLoud:
    def test_an_unresolvable_root_refuses_rather_than_defaulting(self, tmp_path) -> None:
        """The refusal is DELIBERATE and must survive this repair.

        DEFECT THIS TEST ALONE CATCHES
            A "fix" that makes the launcher tolerant by substituting a default
            or synthetic directory. 07c C4 removed exactly such a fallback from
            generic runtime-control because it was a task assumption that, on
            another task, resolved somebody else's dataset. Repairing the
            transport must not re-introduce it one layer up.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            resolve_dataset_dir returns a path instead of raising, and this
            test reports that a missing root was silently substituted.
        """
        from execute_tools.data_paths import DatasetDirectoryUnavailable, resolve_dataset_dir

        missing = tmp_path / "definitely-not-present"
        with pytest.raises(DatasetDirectoryUnavailable):
            resolve_dataset_dir(str(missing), purpose="a C12-P regression probe")

    def test_an_explicit_valid_root_is_returned_unchanged(self, tmp_path) -> None:
        """The other half: a real root is honoured, not overridden.

        DEFECT THIS TEST ALONE CATCHES
            An over-correction that refuses or rewrites a perfectly good
            operator-supplied path. Without this, "always raise" would satisfy
            the test above.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The returned value stops equalling the supplied directory.
        """
        from execute_tools.data_paths import resolve_dataset_dir

        real = tmp_path / "data_root"
        real.mkdir()
        assert resolve_dataset_dir(str(real), purpose="a C12-P regression probe") == str(real)
