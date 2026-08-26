"""Step 12 / PR-12e workstream D3 — the `davis_future_prediction` quickstart.

These guards protect ONE property that no static checker, schema or other test
can express: **the command a user copies out of this pack's README is the
command that reaches the normal SIDERIUS production launcher, bound to this
pack's task-composition manifest.**

Everything here is deterministic. Nothing trains, scores, calls an LLM or
touches a GPU: the launcher is exercised through its own ``--dry-run`` mode
(side-effect free by construction — ``_chain_common.sh::run_chain`` skips its
``mkdir`` and ``record_chain_stop`` returns early), and the repo-root
resolution is proved against a throwaway mirror checkout with a recording stub
in place of the launcher.

Each test names the defect only it can catch and how it fails.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "davis_future_prediction"
README = PACK / "README.md"
DATA_README = PACK / "data" / "README.md"
QUICKSTART = PACK / "quickstart.sh"
MANIFEST = REPO_ROOT / "configs" / "task_composition" / "davis.yaml"
LAUNCHER_RELPATH = "sdsc_submission_scripts/run_chain.sh"
RUNNER_BASENAME = "run_one_iteration.py"

#: Literal placeholders the README publishes, substituted with real temporary
#: paths before the published command is driven.
WORKSPACE_PLACEHOLDER = "/path/to/your/workspace"
DATA_PLACEHOLDER = "/path/to/DAVIS_2017"

#: Absolute roots that exist on one developer's machine. `/path/to/...` is the
#: established placeholder convention (root `README.md`), so a real one of these
#: in the published surface is always an accident.
MACHINE_LOCAL_ROOT = re.compile(r"(?<![\w.])/(home|Users|expanse|scratch)/")


# ---------------------------------------------------------------------------
# README parsing — the published surface is the source of every command below
# ---------------------------------------------------------------------------


def _published_block(marker: str, *, text: str | None = None) -> str:
    """The fenced code block immediately following ``<!-- {marker} -->``.

    The marker is an HTML comment, so it is invisible in rendered Markdown and
    the user still copies a clean command.
    """
    body = README.read_text(encoding="utf-8") if text is None else text
    needle = f"<!-- {marker} -->"
    assert needle in body, f"README no longer marks the {marker!r} block with {needle!r}"
    lines = body.split(needle, 1)[1].splitlines()
    opened = False
    collected: list[str] = []
    for line in lines:
        if line.startswith("```"):
            if opened:
                return "\n".join(collected)
            opened = True
            continue
        if opened:
            collected.append(line)
    raise AssertionError(f"no closed code fence follows {needle!r} in the README")


def _published_argv(marker: str) -> list[str]:
    """The marked block as an argv list, with line continuations folded away."""
    command = _published_block(marker).replace("\\\n", " ")
    return shlex.split(command)


def _substitute(argv: list[str], workspace: Path, data_dir: Path) -> list[str]:
    mapping = {WORKSPACE_PLACEHOLDER: str(workspace), DATA_PLACEHOLDER: str(data_dir)}
    return [mapping.get(token, token) for token in argv]


@pytest.fixture(scope="module")
def dry_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Drive the README's PUBLISHED run command with ``--dry-run`` appended.

    Module-scoped: one subprocess serves every assertion about what the
    published command actually reaches.

    The workspace is created and left EMPTY, deliberately. That is the only
    state in which the launcher's auto-resume branch is reachable: a
    non-existent workspace short-circuits to ``START_ITER=1`` at
    ``run_chain.sh:269``, which would make the start-iteration assertion below
    prove nothing. An existing-but-empty workspace forces
    ``resolve_start_iter`` to choose between the manual pin and the inspector,
    which is exactly the choice under test.
    """
    base = tmp_path_factory.mktemp("davis_quickstart_dry_run")
    workspace = base / "existing_empty_workspace"
    workspace.mkdir()
    data_dir = base / "DAVIS_2017"
    data_dir.mkdir()
    argv = _substitute(_published_argv("quickstart-command"), workspace, data_dir)
    proc = subprocess.run(
        [*argv, "--dry-run"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=300,
    )
    return {
        "proc": proc,
        "argv": argv,
        "workspace": workspace,
        "data_dir": data_dir,
        "output": proc.stdout + proc.stderr,
    }


# ---------------------------------------------------------------------------
# the entrypoint exists and is usable
# ---------------------------------------------------------------------------


def test_the_pack_ships_one_executable_shell_entrypoint() -> None:
    """Defect caught: the pack's single run entrypoint is missing, is not a
    shell script, or lands in git without its executable bit.

    How it fails: `quickstart.sh` absent, or committed mode 644 — `git`
    preserves the mode, so `./examples/davis_future_prediction/quickstart.sh`
    (the form users reach for after `ls`) dies with `Permission denied` while
    the README's `bash …` form keeps working, hiding the regression.

    Not covered by `test_pack_governance.py`: that guard forbids `.py` outside
    `plugins/`, which is WHY this entrypoint is a `.sh`; it asserts nothing
    about a shell entrypoint existing or being executable.
    """
    assert QUICKSTART.is_file(), f"{QUICKSTART} is the pack's only run entrypoint"
    assert QUICKSTART.suffix == ".sh"
    mode = QUICKSTART.stat().st_mode
    assert mode & stat.S_IXUSR, f"{QUICKSTART} is not executable (mode {oct(mode)})"
    first_line = QUICKSTART.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/env bash", f"unexpected shebang: {first_line!r}"


def test_the_manifest_the_entrypoint_binds_exists() -> None:
    """Defect caught: `quickstart.sh` points `--task_composition` at a manifest
    path that no longer exists (renamed, moved, or never landed).

    How it fails: the published command dies at launch with a composition
    resolution error. The dry-run test below proves the flag is EMITTED; only
    this one proves the target is real, and the two failures are different
    (emitted-but-dangling vs. never-emitted).
    """
    assert MANIFEST.is_file(), f"{MANIFEST} is what the pack's entrypoint binds"


# ---------------------------------------------------------------------------
# the published command IS the tested command, and it reaches production
# ---------------------------------------------------------------------------


def test_the_published_command_is_the_entrypoint_and_carries_no_lab_paths() -> None:
    """Defect caught: the README's published command drifts away from the
    pack's entrypoint — a second dialect, an inlined `run_chain.sh` invocation,
    or a machine-local `--workspace` baked into the copy-paste.

    How it fails: the parsed argv no longer starts with
    `bash examples/davis_future_prediction/quickstart.sh`, or a real absolute
    root appears in it. Every other test in this module drives THIS parsed
    argv, so a drifting README breaks them all — this one names why.
    """
    argv = _published_argv("quickstart-command")
    assert argv[0] == "bash"
    assert argv[1] == "examples/davis_future_prediction/quickstart.sh"
    assert WORKSPACE_PLACEHOLDER in argv, "the published command must name --workspace"
    assert DATA_PLACEHOLDER in argv, "the published command must name --data_dir"
    hit = MACHINE_LOCAL_ROOT.search(" ".join(argv))
    assert hit is None, f"published run command embeds a machine-local root: {hit!r}"


def test_the_published_command_reaches_the_production_chain_launcher(
    dry_run: dict[str, object],
) -> None:
    """Defect caught: the published command stops reaching the normal
    production path — `sdsc_submission_scripts/run_chain.sh` →
    `run_one_iteration.py` — or stops binding this pack's manifest.

    How it fails: the entrypoint is rewired to a different launcher, the
    manifest flag is dropped, or the data root stops being forwarded; the
    dry-run's printed child command then lacks the token asserted here and a
    real run would silently execute some other task's composition (or none).
    """
    proc = dry_run["proc"]
    assert isinstance(proc, subprocess.CompletedProcess)
    output = str(dry_run["output"])
    assert proc.returncode == 0, f"published command failed its dry run:\n{output}"
    assert LAUNCHER_RELPATH in output, "the production chain launcher was not invoked"
    assert RUNNER_BASENAME in output, "the launcher did not reach run_one_iteration.py"
    assert "--task_composition" in output
    assert "configs/task_composition/davis.yaml" in output, (
        "the run is not bound to this pack's task-composition manifest"
    )
    assert f"--data_dir {dry_run['data_dir']}" in output, (
        "the prepared data root did not reach the child command"
    )


def test_the_dry_run_creates_nothing(dry_run: dict[str, object]) -> None:
    """Defect caught: the documented `--dry-run` preview acquires a side effect
    (an iteration directory, a `chain_stopped.json` state record), so the
    README's "do this first on an unfamiliar machine" advice becomes false.

    How it fails: the workspace the dry run named is no longer empty
    afterwards. Emptiness rather than non-existence is the assertion because
    the fixture must pre-create the workspace to reach the auto-resume branch —
    which makes this the stronger check anyway: a preview that writes into an
    EXISTING workspace is the damaging case.
    """
    workspace = dry_run["workspace"]
    assert isinstance(workspace, Path)
    assert workspace.is_dir()
    assert list(workspace.iterdir()) == [], f"--dry-run wrote into {workspace}"


def test_the_published_command_never_reaches_the_gate_harness_or_the_node_cli(
    dry_run: dict[str, object],
) -> None:
    """Defect caught (F-12d-26, and the Gate-harness confusion beside it): the
    quickstart is re-pointed at `scripts/run_davis_gate2.py` or at the DIRECT
    tuner-node CLI, or it starts passing `--no-is_trial`.

    Why each is a real, silent failure — not style:
      * `run_davis_gate2.py` is an L3 real-execution EVIDENCE harness, not a
        way this task runs; wrapping it would publish a Gate script as a user
        entrypoint and bypass the composed production loop entirely.
      * on the direct node CLI `--is_trial` does not default on, and omitting
        it falls through to `single_file` — the LEGACY TIDMAD path. The
        composed scope capability is then never called, `file_index` is forced
        to TIDMAD's, scoring resolves the legacy subprocess route, and every
        bounded knob is ignored. The run looks GREEN while scoring a
        future-frame prediction through a 1-D denoising route.
      * `--no-is_trial` reads like "be more rigorous" and produces the same
        cascade through the chain launcher.

    How it fails: any of these tokens appears in the entrypoint's EXECUTABLE
    lines or in the argv the dry run actually built. Comment lines are stripped
    first and deliberately so — the script's prose explains why it does not
    wrap the Gate harness, and a guard that could not tell an invocation from
    an explanation would punish the documentation it wants.
    """
    script = "\n".join(
        line
        for line in QUICKSTART.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    output = str(dry_run["output"])
    published = " ".join(_published_argv("quickstart-command"))
    for surface, label in ((script, "quickstart.sh"), (output, "the dry-run argv")):
        assert "run_davis_gate2" not in surface, f"{label} reaches the Gate harness"
        assert "run_pets_gate2" not in surface, f"{label} reaches another pack's harness"
        assert "--no-is_trial" not in surface, f"{label} passes --no-is_trial (F-12d-26)"
    assert "--no-is_trial" not in published
    assert "run_davis_gate2" not in published
    # The direct tuner-node CLI, named by the module path the node CLI is
    # invoked through. Its absence is the point: the chain launcher is the only
    # entrypoint on which `--is_trial` defaults on.
    assert "nodes/ml_hyperparameter_tune_agent" not in script
    assert "nodes.ml_hyperparameter_tune_agent" not in script


def test_the_run_is_bounded_without_data_scope_and_without_seed_paths(
    dry_run: dict[str, object],
) -> None:
    """Defect caught: the quickstart is "bounded" with `--data_scope`, or it
    acquires `--seed_paths`.

    How each fails:
      * `--data_scope` is refused BY NAME for a composed task that declares no
        TIDMAD file topology (PR-12bc B7), so the published command would abort
        at launch — the flag cannot bound a DAVIS run at all. The bounding
        knobs that DO reach this task's scope capability are the portions and
        `--validation_max_samples`, asserted present here.
      * a seeded quickstart contradicts the cold-start rule for real runs and
        would make a first run depend on an artifact the user does not have.
    """
    output = str(dry_run["output"])
    child = output.split("[DRY-RUN] would exec", 1)
    assert len(child) == 2, f"dry run printed no child command:\n{output}"
    child_argv = child[1]
    assert "--data_scope" not in child_argv, "the quickstart bounds the run with --data_scope"
    assert "--seed_paths" not in child_argv, "the quickstart is not a cold start"
    for bounded in ("--trial_portion", "--formal_portion", "--validation_max_samples"):
        assert bounded in child_argv, f"{bounded} did not reach the child command"


def test_the_published_command_pins_the_start_iteration(
    dry_run: dict[str, object],
) -> None:
    """Defect caught: `--start_iter 1` is dropped, and the published command can
    then silently do nothing while announcing success.

    Why this is a correctness pin and not a knob. `--auto_resume` is ON by
    default (`run_chain.sh:42`, `_chain_common.sh:173`). Against a workspace
    that already EXISTS, `resolve_start_iter` (`run_chain.sh:277-278`) captures
    `START_ITER` from `scripts/inspect_run_state.py --next-iter`, and CLAUDE.md
    records that this capture is corrupted by plugin-loader stdout, naming
    `--start_iter N` as the workaround. When the capture is bad the loop walks
    ZERO iterations — and `run_chain.sh:336` prints
    "… ${NUM_ITERATIONS} iterations walked" from the REQUESTED count, not from
    what ran, so the chain exits 0 reporting a completed run. A user re-running
    the quickstart gets a silent no-op sold as success.

    How it fails, non-vacuously: the fixture's workspace EXISTS and is empty, so
    the auto-resume branch is genuinely taken. Deleting the flag makes the
    launcher print the inspector's line instead of the manual-pin line and this
    assertion goes red. The second assertion is the non-vacuity control: it
    proves the loop really walked iteration 1 rather than the whole command
    having been a no-op that happened to contain the right words.
    """
    output = str(dry_run["output"])
    assert "--start_iter manually pinned to 1" in output, (
        "the published command did not pin the start iteration — auto-resume "
        f"decided it instead:\n{output}"
    )
    assert "--start_iteration 1" in output, (
        "the chain walked no iteration at all; the dry run printed no child "
        f"command for iteration 1:\n{output}"
    )


def test_the_published_command_pins_per_node_llm_routing(
    dry_run: dict[str, object],
) -> None:
    """Defect caught: `--llm_config` is dropped, or it names a file that does
    not exist in the checkout.

    How each fails: the chain default is an empty `LLM_CONFIG` and
    `run_one_iteration.py --llm_config` defaults to `None`
    (`run_one_iteration.py:1030`), so an omitted flag silently degrades every
    node to the single `--llm_model` value with no per-node routing — a
    quality change no error announces. A flag pointing at a renamed or deleted
    routing file fails at startup instead, after the user has staged 833 MB of
    data. The path is checked against the filesystem here because the dry run
    forwards the string without opening it.
    """
    output = str(dry_run["output"])
    assert "--llm_config" in output, "per-node LLM routing did not reach the child command"
    match = re.search(r"--llm_config (\S+)", output)
    assert match is not None, output
    routing = Path(match.group(1))
    assert routing.is_file(), (
        f"the published command names a routing file that is absent: {routing}"
    )
    assert routing.parent == REPO_ROOT / "llm_configs", (
        f"routing file resolved outside the checkout's llm_configs/: {routing}"
    )


# ---------------------------------------------------------------------------
# portability: the entrypoint resolves its own repository, never the caller's
# ---------------------------------------------------------------------------


def test_the_entrypoint_resolves_the_repo_root_from_its_own_location(tmp_path: Path) -> None:
    """Defect caught: `quickstart.sh` resolves the repository root from the
    CALLER's working directory (`$PWD`, a relative `../..`, or a hardcoded
    absolute path) instead of from `${BASH_SOURCE[0]}`.

    How it fails: the byte-identical script is copied into a throwaway mirror
    checkout whose launcher is a recorder, and invoked BY ABSOLUTE PATH from an
    unrelated working directory. A cwd-derived root would reach the real
    checkout's launcher (or nothing) and the mirror's recorder would stay
    empty; a hardcoded root would record a path outside the mirror.

    This is the check CLAUDE.md's portability section asks for and the one the
    dry-run test structurally cannot make: that test runs from the real repo
    root, where cwd and the script's own location agree.
    """
    mirror = tmp_path / "mirror_checkout"
    pack = mirror / "examples" / "davis_future_prediction"
    pack.mkdir(parents=True)
    (mirror / "sdsc_submission_scripts").mkdir()
    shutil.copy2(QUICKSTART, pack / "quickstart.sh")
    recorded = mirror / "recorded_argv.txt"
    recorder = mirror / LAUNCHER_RELPATH
    recorder.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$(dirname "$0")/../recorded_argv.txt"\n',
        encoding="utf-8",
    )
    recorder.chmod(0o755)

    elsewhere = tmp_path / "an_unrelated_cwd"
    elsewhere.mkdir()
    proc = subprocess.run(
        [
            "bash",
            str(pack / "quickstart.sh"),
            "--workspace",
            str(tmp_path / "ws"),
            "--data_dir",
            str(tmp_path / "data"),
        ],
        capture_output=True,
        text=True,
        cwd=elsewhere,
        timeout=120,
    )
    assert proc.returncode == 0, f"rc={proc.returncode} stdout={proc.stdout} stderr={proc.stderr}"
    assert recorded.is_file(), (
        "the mirror's launcher was never invoked — the entrypoint did not "
        f"resolve its repo root from its own location. stdout={proc.stdout}"
    )
    argv = recorded.read_text(encoding="utf-8").splitlines()
    manifest_value = argv[argv.index("--task_composition") + 1]
    assert manifest_value == str(mirror / "configs" / "task_composition" / "davis.yaml"), (
        f"manifest resolved outside the mirror checkout: {manifest_value}"
    )


def test_missing_required_inputs_are_refused_by_name(tmp_path: Path) -> None:
    """Defect caught: `--workspace` or `--data_dir` acquires a default, or the
    refusal stops naming which one is missing.

    How it fails: a defaulted workspace writes a real run into whatever
    directory the default names (the published quickstart previously embedded
    one developer's `/home/klz/...` path); a defaulted data root sends a
    composed run to read another task's data. Both must be refused, non-zero,
    naming the flag — otherwise the failure surfaces minutes later inside a
    subprocess, if at all.
    """
    for args, expected in (
        ([], "--workspace"),
        (["--workspace", str(tmp_path / "ws")], "--data_dir"),
        (["--data_dir", str(tmp_path)], "--workspace"),
    ):
        proc = subprocess.run(
            ["bash", str(QUICKSTART), *args],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=120,
        )
        assert proc.returncode != 0, f"args={args} was accepted: {proc.stdout}"
        assert expected in proc.stderr, (
            f"args={args} refusal did not name {expected}: {proc.stderr}"
        )


# ---------------------------------------------------------------------------
# self-containedness
# ---------------------------------------------------------------------------


def test_the_published_user_surface_names_no_machine_local_path() -> None:
    """Defect caught: a path that exists on one machine leaks into the surface
    a new user copies from (F-12e-UX-1's failure class).

    Scope is deliberate. `README.md`, `data/README.md` and `quickstart.sh` are
    the user journey. `STATUS.md`, `PROVENANCE.md` and `expected/` are EVIDENCE
    records that legitimately cite the workspaces real Gate runs used — CLAUDE.md
    permits operator documentation to name known deployments, and forbids only
    implicit dependencies in executable code and published instructions.

    How it fails: a `/home/...`-rooted example is pasted back into the README or
    hardcoded as a default in the entrypoint, and the quickstart silently stops
    being runnable by anyone else.
    """
    for path in (README, DATA_README, QUICKSTART):
        hit = MACHINE_LOCAL_ROOT.search(path.read_text(encoding="utf-8"))
        assert hit is None, f"{path.relative_to(REPO_ROOT)} names a machine-local root: {hit!r}"


def test_the_quickstart_depends_on_no_other_example_pack() -> None:
    """Defect caught: this pack's run path reaches into `examples/tidmad/` or
    `examples/oxford_iiit_pet/` — through the entrypoint, the README, or a ref
    in the manifest it binds.

    How it fails: a manifest ref copy-pasted from a sibling pack still RESOLVES
    (both packs ship the same declaration filenames), so a composed DAVIS run
    would bind another task's declaration and nothing would raise. Only a
    per-ref containment check catches that; the acceptance rule is that an
    example must be runnable with no files from either other example.
    """
    siblings = ("examples/tidmad", "examples/oxford_iiit_pet")
    for path in (README, QUICKSTART):
        body = path.read_text(encoding="utf-8")
        for sibling in siblings:
            assert sibling not in body, f"{path.name} references {sibling}"

    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    refs: list[str] = []

    def _collect(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"ref", "config", "declaration", "file", "dir"} and isinstance(
                    value, str
                ):
                    refs.append(value)
                else:
                    _collect(value)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    _collect(payload)
    pack_refs = [r for r in refs if "examples/" in r]
    assert pack_refs, "the manifest resolves nothing into an example pack — check the ref keys"
    for ref in pack_refs:
        resolved = (MANIFEST.parent / ref).resolve()
        assert resolved.is_relative_to(PACK.resolve()), (
            f"the DAVIS manifest binds {resolved}, outside this pack"
        )


# ---------------------------------------------------------------------------
# the neighbouring published commands: prepare, and inspect
# ---------------------------------------------------------------------------


def test_the_published_preparation_command_matches_the_real_fetch_tool() -> None:
    """Defect caught: the README publishes a data-preparation invocation the
    shipped tool does not accept — a renamed module, or a flag that never
    existed or was removed.

    How it fails: the flags are read out of the tool's OWN `--help` at test
    time, so a rename in `tools/example_packs/fetch_davis.py` turns this red
    while the README still tells a new user to run the old form. A second
    downloader in the pack would show up here too, as a module name that is not
    the shipped one.
    """
    argv = _published_argv("prepare-command")
    assert argv[1] == "-m", f"the prepare command must run a module: {argv}"
    assert argv[2] == "tools.example_packs.fetch_davis", (
        f"the pack must publish the SHIPPED fetch tool, not a second one: {argv[2]}"
    )
    flags = [token for token in argv[3:] if token.startswith("--")]
    assert flags, "the published prepare command passes no flags"
    help_text = subprocess.run(
        [sys.executable, "-m", "tools.example_packs.fetch_davis", "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert help_text.returncode == 0, help_text.stderr
    for flag in flags:
        assert flag in help_text.stdout, f"{flag} is published but the tool does not accept it"


def test_the_published_report_command_matches_the_frozen_report_contract() -> None:
    """Defect caught: this pack publishes its own bespoke result-inspection
    command instead of the ONE frozen report entrypoint shared by all three
    example packs.

    How it fails: the published module name or flag pair drifts from
    `python -m tools.run_report --workspace <dir> --out <dir>`, and the three
    packs stop having one inspection story. The shape is asserted
    unconditionally because the contract is frozen; the executable half tightens
    automatically once the module lands (it is built by a sibling workstream).
    """
    argv = _published_argv("report-command")
    assert argv[1] == "-m"
    assert argv[2] == "tools.run_report"
    assert "--workspace" in argv and "--out" in argv

    if not (REPO_ROOT / "tools" / "run_report").exists():
        pytest.skip("tools/run_report is not present in this checkout yet")
    proc = subprocess.run(
        [sys.executable, "-m", "tools.run_report", "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    for flag in ("--workspace", "--out"):
        assert flag in proc.stdout, f"{flag} is published but tools.run_report does not accept it"


def test_the_readme_states_the_baseline_beside_the_reference_number() -> None:
    """Defect caught: the README quotes this task's reference MSE without the
    trivial baseline it must be read against.

    How it fails: `0.017290` alone is unreadable — a user cannot tell a working
    run from a broken one, because a lower-is-better score has no natural scale.
    The last-frame-copy baseline `0.017392` is what makes the number mean
    something, and the two must stay together. Values are hardcoded here from
    the preserved Gate evidence recorded in `STATUS.md`, never read back from
    the README.
    """
    body = README.read_text(encoding="utf-8")
    assert "0.017290" in body, "the reference MSE is no longer published"
    assert "0.017392" in body, "the last-frame-copy baseline is no longer published beside it"
    assert "lower" in body.lower(), "the README must say which direction is better"


def test_the_readme_publishes_exactly_one_run_command() -> None:
    """Defect caught: a second run entrypoint appears in the README — a raw
    `run_chain.sh` invocation a user could copy, or a `pytest` line offered as
    the way to "try" the pack.

    How it fails: PR-12e exists to remove the "copy a command out of a unit
    test" experience. If more than one runnable command is published, the
    guarded one stops being the one users take, and the drift this module
    protects against becomes invisible. `pytest` is allowed to appear only
    where the README labels it a developer check.
    """
    body = README.read_text(encoding="utf-8")
    fences = re.findall(r"```bash\n(.*?)```", body, flags=re.DOTALL)
    runnable = [
        block
        for block in fences
        if "quickstart.sh" in block or "run_chain.sh" in block or "run_one_iteration" in block
    ]
    assert runnable, "the README publishes no run command at all"
    for block in runnable:
        assert "quickstart.sh" in block, (
            f"the README publishes a second, unguarded run path:\n{block}"
        )
    assert "developer" in body, "the README must label the pytest line as a developer check"


def test_the_readme_keeps_its_governance_citations() -> None:
    """Defect caught: the quickstart rewrite drops a citation another guard
    depends on, and that guard's failure reads as unrelated.

    How it fails: `test_pack_governance.py` guard (e) needs the roadmap
    filename plus §22.9/§22.23, and the Step-07a rung needs `R1`/`R2`/`R3`.
    Asserting them HERE, in the module that owns the rewrite, is what makes the
    breakage self-explanatory instead of surfacing three files away.
    """
    body = README.read_text(encoding="utf-8")
    assert "siderius_generic_framework_upgrade.md" in body
    assert "§22.9" in body or "§22.23" in body
    for rung in ("R1", "R2", "R3"):
        assert rung in body, f"the README must still state the {rung} training-history rung"


def test_the_quickstart_is_not_shadowed_by_a_python_entrypoint() -> None:
    """Defect caught: someone "improves" this entrypoint by adding a `.py`
    beside it, which `test_pack_governance.py` guard (b) forbids outside
    `plugins/`.

    How it fails: guard (b) would catch it repo-wide, but the failure would
    read as a governance violation with no explanation of WHY this pack's
    entrypoint is a shell script. This test carries that reason next to the
    entrypoint it constrains: the pack's run surface must stay a `.sh`.
    """
    stray = [
        p for p in PACK.rglob("*.py") if p.parent != PACK / "plugins" and not p.name.startswith(".")
    ]
    assert stray == [], f"{stray} would violate the examples/ governance pin"
    assert os.path.isfile(QUICKSTART)
