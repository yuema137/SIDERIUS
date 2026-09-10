"""F-SCANI-2 — "initialise every consumed shell variable" is an ENTRY
CONDITION of ``_chain_common.sh``, not a cleanup step performed by callers.

The defect this file closes, exactly as the frozen row states it:
``_chain_common.sh`` sets ``-e`` and ``-o pipefail`` but not ``-u``; five
``VALIDATION_*`` variables were read as ``"${VAR:-}"`` inside
``build_app_args`` and assigned NOWHERE, unlike every other knob. An
exported value — a stale ``.bashrc`` line, a tmux session that once ran a
validation posture — therefore reached ``APP_ARGS`` directly. The sharp
edge: ``launch_prior_baseline_experiment.sh`` REFUSES
``--validation_fixed_candidate_plan`` as a flag, and that flag BYPASSES
THE PROPOSER, substituting one fixed candidate plan for the whole
campaign. The environment route went around a refusal already written.

Each test names the defect only it catches.

* ``TestEntryConditionCensus`` — the STRUCTURAL guard. It derives every
  variable ``build_app_args`` reads straight from the shell source and
  every variable the library assigns at source time, and fails when the
  first set is not covered by the second. Deleting one of the five
  initialisations, or landing a SIXTH ``"${NEW_VAR:-}"`` read with no
  default, turns it RED — which no behavioural test can do, because a
  variable nobody exports behaves identically whether or not it has a
  default. Mutation-proven against ``origin/master``: at the base commit
  the census reports exactly the five names.
* ``TestEnvironmentRouteIsClosed`` — the BEHAVIOURAL witness, driving the
  production ``build_app_args`` in a bash subprocess. Exporting all five
  variables must put none of their flags on the child argv. Fails by
  finding a ``--validation_*`` token that no flag asked for.
* ``TestFlagRouteStillWorks`` — the discrimination case. The fix closes an
  injection route; it must not remove the feature. ``parse_chain_args
  --validation_fixed_candidate_plan PLAN`` must still forward the flag and
  its value. Fails when an over-eager "initialise" clobbers the parser's
  own assignment (e.g. a default written after parsing instead of before).
* ``TestDeclaredEnvironmentInputs`` — the one name that legitimately
  arrives from the environment is DECLARED. ``CHAIN_STOP_FILE`` is a
  documented operator override (``docs/running_chain_test.md``, with its
  own regression test in ``test_c13_stop_semantics.py``), so the roster
  makes the exception explicit and bounded. Fails when a second name is
  quietly added to it — the census's escape hatch must never grow silently.

No GPU, no Python iteration, no launch: bash subprocesses and source text.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMON = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"

#: The five variables the frozen row names. Hardcoded on purpose: reading
#: them back out of the shell source would compare the file to itself and
#: pass for any file.
VALIDATION_VARS = frozenset(
    {
        "VALIDATION_FIXED_CANDIDATE_PLAN",
        "VALIDATION_MAX_PORTION",
        "VALIDATION_MAX_TRAIN_SAMPLES",
        "VALIDATION_MAX_SAMPLES",
        "VALIDATION_MAX_PHASE_SECONDS",
    }
)

#: Their child-argv spellings, likewise hardcoded.
VALIDATION_FLAGS = frozenset(
    {
        "--validation_fixed_candidate_plan",
        "--validation_max_portion",
        "--validation_max_train_samples",
        "--validation_max_samples",
        "--validation_max_phase_seconds",
    }
)

#: Names assigned at source time: a top-level ``NAME=`` at column 0. Every
#: such line executes when the library is sourced, i.e. BEFORE
#: ``parse_chain_args`` — which is what makes initialisation an entry
#: condition rather than a cleanup step.
_TOP_LEVEL_ASSIGNMENT = re.compile(r"(?m)^([A-Z][A-Z0-9_]*)=")

#: A read of an upper-case shell variable: ``$NAME``, ``${NAME}``,
#: ``${NAME:-}``, ``${#NAME[@]}`` … The leading ``#`` of the length form is
#: skipped by the optional group so array-length reads are seen too.
_VARIABLE_READ = re.compile(r"\$\{?#?([A-Z][A-Z0-9_]*)\b")


def _source_text() -> str:
    return COMMON.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    """The body of a top-level shell function, by its column-0 header."""
    lines = _source_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start + 1 : end])


def _initialised_at_entry() -> set[str]:
    return {m.group(1) for m in _TOP_LEVEL_ASSIGNMENT.finditer(_source_text())}


def _reads_in(function_name: str) -> set[str]:
    return {m.group(1) for m in _VARIABLE_READ.finditer(_function_body(function_name))}


def _run_bash(script: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, **env),
    )


def _app_args(*parse_args: str, **env: str) -> list[str]:
    """Drive the PRODUCTION ``build_app_args`` and return the child argv."""
    parsed = " ".join(f"'{a}'" for a in parse_args)
    result = _run_bash(
        f"source '{COMMON}'\n"
        f"parse_chain_args --workspace /ws --run_name r {parsed}\n"
        "build_app_args 1\n"
        'printf "%s\\n" "${APP_ARGS[@]}"\n',
        **env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


class TestEntryConditionCensus:
    def test_the_five_validation_variables_are_initialised_at_entry(self):
        """Positive membership, name by name: each of the five the row
        names must be assigned at source time. Fails by naming whichever
        initialisation was deleted."""
        initialised = _initialised_at_entry()
        missing = sorted(VALIDATION_VARS - initialised)
        assert not missing, (
            f"{missing} are read by build_app_args but assigned nowhere at "
            "entry, so an exported value reaches the child argv (F-SCANI-2)"
        )

    def test_the_census_can_actually_see_the_five(self):
        """Non-vacuity for the census below. A read-extractor that matched
        nothing would make 'no uninitialised reads' true for free; this
        pins that the five ARE in the population the census inspects."""
        reads = _reads_in("build_app_args")
        assert VALIDATION_VARS <= reads, sorted(VALIDATION_VARS - reads)

    def test_no_variable_the_argv_builder_reads_is_uninitialised(self):
        """The standing guard. build_app_args decides the child argv; a
        name it reads without an entry-time default is an environment
        injection route. Fails by naming the new variable."""
        uninitialised = sorted(_reads_in("build_app_args") - _initialised_at_entry())
        assert not uninitialised, (
            f"{uninitialised} reach build_app_args from the environment: "
            "initialise them in the defaults block (F-SCANI-2 entry condition)"
        )

    def test_the_seed_and_advice_builders_hold_the_same_condition(self):
        """The two sibling builders on the same launch path. Same rule,
        stated once per surface so a new uninitialised read in either is
        named rather than inherited by silence."""
        for builder in ("build_source_paths", "load_advice_file"):
            uninitialised = sorted(_reads_in(builder) - _initialised_at_entry())
            assert not uninitialised, f"{builder}: {uninitialised}"


class TestEnvironmentRouteIsClosed:
    def test_exported_validation_variables_do_not_reach_the_child_argv(self):
        """THE witness. All five exported, none passed as a flag: the child
        argv must carry no validation token. Before the entry condition
        this printed --validation_fixed_candidate_plan /tmp/evil.json —
        the proposer bypassed for the whole campaign, from a .bashrc."""
        argv = _app_args(
            VALIDATION_FIXED_CANDIDATE_PLAN="/tmp/evil_plan.json",
            VALIDATION_MAX_PORTION="0.9",
            VALIDATION_MAX_TRAIN_SAMPLES="7",
            VALIDATION_MAX_SAMPLES="7",
            VALIDATION_MAX_PHASE_SECONDS="7",
        )
        injected = sorted(VALIDATION_FLAGS.intersection(argv))
        assert not injected, f"environment-injected tokens on the child argv: {injected}"
        assert "/tmp/evil_plan.json" not in argv


class TestFlagRouteStillWorks:
    def test_the_declared_flag_still_reaches_the_child_argv(self):
        """Discrimination: the entry condition closes an injection route,
        it does not remove the seam. --fixed-candidate depends on this.
        Fails when a default is written AFTER parsing and clobbers it."""
        argv = _app_args(
            "--validation_fixed_candidate_plan",
            "/tmp/declared_plan.json",
            "--validation_max_portion",
            "0.25",
        )
        assert "--validation_fixed_candidate_plan" in argv
        assert argv[argv.index("--validation_fixed_candidate_plan") + 1] == (
            "/tmp/declared_plan.json"
        )
        assert "--validation_max_portion" in argv
        assert argv[argv.index("--validation_max_portion") + 1] == "0.25"

    def test_the_flag_beats_a_conflicting_export(self):
        """Precedence, stated rather than assumed: an operator's flag wins
        over any ambient export of the same name."""
        argv = _app_args(
            "--validation_fixed_candidate_plan",
            "/tmp/declared_plan.json",
            VALIDATION_FIXED_CANDIDATE_PLAN="/tmp/evil_plan.json",
        )
        assert argv[argv.index("--validation_fixed_candidate_plan") + 1] == (
            "/tmp/declared_plan.json"
        )


class TestDeclaredEnvironmentInputs:
    def test_the_declared_environment_input_roster_is_exactly_the_stop_file(self):
        """The census's ONLY escape hatch, pinned to one hardcoded name.
        CHAIN_STOP_FILE is a documented operator override with its own
        regression test; anything else added here would be an injection
        route wearing a declaration. Fails by naming the new member."""
        match = re.search(
            r"(?m)^CHAIN_DECLARED_ENV_INPUTS=\(([^)]*)\)",
            _source_text(),
        )
        assert match is not None, "the declared-environment-input roster is missing"
        declared = set(match.group(1).split())
        assert declared == {"CHAIN_STOP_FILE"}, declared

    def test_the_declared_input_is_not_one_of_the_five(self):
        """The roster must never be used to re-open the row it closes."""
        assert not VALIDATION_VARS.intersection({"CHAIN_STOP_FILE"})
