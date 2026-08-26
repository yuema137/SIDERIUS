"""Step 12 / PR-12e — the TIDMAD example pack's ONE documented run command.

What this module owns, and nothing else: the claim that an external user can
clone the repository, read `examples/tidmad/README.md`, and run the command it
publishes — and that this command is the SAME command exercised here.

The frozen requirement (PR-12e §V.2) is *"the command a user copies from the
README is the command the example's regression test exercises"*. There must
not be a README command A, a CI helper B and a Gate script C traversing subtly
different paths. This module enforces that by PARSING the command out of the
README instead of restating it: if the two ever drift, these tests drive the
README's version and fail.

Nothing here runs a real chain. `run_chain.sh --dry-run` walks the real
argument-resolution path and prints the exact child command with no side
effects, which is what makes a deterministic proof of "reaches the production
launcher" possible at zero cost.

Every test states the defect only it catches and how it fails when the
behaviour breaks. The checkout root is derived from ``__file__``
(CLAUDE.md portability); no absolute repository path is written down.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPO_ROOT / "examples" / "tidmad"
README = PACK_ROOT / "README.md"
QUICKSTART = PACK_ROOT / "quickstart.sh"

#: The placeholders the README uses, following the convention the repository's
#: other published commands already use. Asserted to be PRESENT before
#: substitution, so a README that stops using them fails loudly instead of
#: silently launching against a literal `/path/to/...`.
WORKSPACE_PLACEHOLDER = "/path/to/your/workspace"
DATA_DIR_PLACEHOLDER = "/path/to/tidmad/data"
REPORT_PLACEHOLDER = "/path/to/report"

#: Anchors in the README that mark the published commands. They exist so the
#: parse is exact rather than "the first bash block we find".
PREVIEW_ANCHOR = "<!-- QUICKSTART-PREVIEW-COMMAND -->"
RUN_ANCHOR = "<!-- QUICKSTART-RUN-COMMAND -->"
REPORT_ANCHOR = "<!-- QUICKSTART-REPORT-COMMAND -->"

#: Absolute paths that exist on one developer's machine or one cluster. A
#: published quickstart that names any of them is not runnable by anyone else.
MACHINE_SPECIFIC_PREFIXES = (
    "/home/klz/",
    "/home/tidmad/",
    "/home/yuema137/",
    "/expanse/",
    "/workspace/REPO/",
)

#: The other two persistent packs. This pack must stand alone.
OTHER_PACK_NAMES = ("oxford_iiit_pet", "davis_future_prediction")

_SUBPROCESS_TIMEOUT = 180


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _published_command(anchor: str) -> list[str]:
    """The argv published in the README's fenced block following ``anchor``.

    Line continuations are joined, then `shlex` splits exactly as a shell
    would, so what comes back is what a user's shell would execute.
    """
    text = README.read_text(encoding="utf-8")
    start = text.index(anchor)
    fence = re.search(r"```(?:bash|sh)\n(.*?)```", text[start:], re.DOTALL)
    assert fence is not None, f"no fenced command block follows {anchor!r} in {README}"
    return shlex.split(fence.group(1).replace("\\\n", " "))


def _venv_env(**overrides: str) -> dict[str, str]:
    """The environment `run_chain.sh` needs, derived from the RUNNING
    interpreter — never from a hardcoded path.

    `run_chain.sh` resolves its interpreter as `$VIRTUAL_ENV` → the checkout's
    `.venv` → `uv run` → system `python3`, then enforces a >= 3.10 floor. A
    git worktree usually has no `.venv` of its own, so the running venv is
    handed over explicitly.
    """
    if sys.prefix == sys.base_prefix:
        pytest.skip(
            "not running inside a virtualenv, so the chain launcher's "
            "interpreter resolution cannot be satisfied portably"
        )
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = sys.prefix
    env.update(overrides)
    return env


def _run(argv: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
    )


@pytest.fixture
def noisy_inspector_venv(tmp_path: Path) -> Path:
    """A venv whose interpreter pollutes `inspect_run_state.py`'s stdout.

    This PLANTS the documented hazard instead of hoping for it. The real
    pollution comes from the plugin loader printing to stdout while the
    auto-resume inspector runs, and `agent_generated/models/` is gitignored —
    so on a fresh checkout (CI) the corruption does not occur, and a test that
    merely *hoped* to observe it would pass for the wrong reason and could
    never go red.

    The shim answers the inspector call with a polluted line followed by a
    valid integer — the exact observed shape — and delegates everything else
    (notably the launcher's Python >= 3.10 version guard) to the real
    interpreter, so nothing else about the launch changes.
    """
    fake = tmp_path / "fake_venv"
    (fake / "bin").mkdir(parents=True)
    shim = fake / "bin" / "python"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        "    *inspect_run_state.py)\n"
        "      echo \"[PluginLoader] Loaded plugin: 'planted' from planted.py\"\n"
        "      echo 1\n"
        "      exit 0 ;;\n"
        "  esac\n"
        "done\n"
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return fake


@pytest.fixture
def staged_data(tmp_path: Path) -> Path:
    """A directory shaped like a prepared TIDMAD data root (empty files)."""
    data = tmp_path / "tidmad_data"
    data.mkdir()
    (data / "abra_training_0000.h5").touch()
    (data / "abra_validation_0000.h5").touch()
    return data


def _substituted(argv: list[str], *, workspace: Path, data_dir: Path) -> list[str]:
    """The README's argv with its two documented placeholders bound."""
    assert WORKSPACE_PLACEHOLDER in argv, (
        f"the README command no longer names {WORKSPACE_PLACEHOLDER!r}; "
        "update this test together with the README's placeholder convention"
    )
    assert DATA_DIR_PLACEHOLDER in argv, (
        f"the README command no longer names {DATA_DIR_PLACEHOLDER!r}; "
        "update this test together with the README's placeholder convention"
    )
    mapping = {
        WORKSPACE_PLACEHOLDER: str(workspace),
        DATA_DIR_PLACEHOLDER: str(data_dir),
    }
    return [mapping.get(token, token) for token in argv]


# ---------------------------------------------------------------------------
# the entrypoint exists as a runnable artifact
# ---------------------------------------------------------------------------


def test_the_pack_ships_an_executable_entrypoint() -> None:
    """Defect caught: the pack's entrypoint disappears, or lands without its
    executable bit in the git index (the mode is what survives a fresh clone;
    a local `chmod` does not).

    Fails as: a missing-file assertion naming `quickstart.sh`, or a git mode
    that is `100644` instead of `100755`.

    Why `.sh` and not `.py`: `tests/unit/examples/test_pack_governance.py`
    guard (b) forbids any `.py` under `examples/` outside
    `examples/<pack>/plugins/`, checked on the filesystem AND in `git
    ls-files`. The entrypoint form is constrained by that rule, not chosen.
    """
    assert QUICKSTART.is_file(), f"the pack has no run entrypoint at {QUICKSTART}"
    assert os.access(QUICKSTART, os.X_OK), f"{QUICKSTART} is not executable"

    listing = subprocess.run(
        ["git", "ls-files", "-s", "--", "examples/tidmad/quickstart.sh"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if listing.returncode != 0:  # not a git checkout (e.g. a source tarball)
        pytest.skip(f"not a git checkout: {listing.stderr.strip()}")
    assert listing.stdout.strip(), "the entrypoint is untracked — a clone would not receive it"
    assert listing.stdout.split()[0] == "100755", (
        f"the entrypoint's tracked mode is {listing.stdout.split()[0]}, not 100755"
    )


# ---------------------------------------------------------------------------
# ONE command, ONE path
# ---------------------------------------------------------------------------


def test_the_readme_publishes_one_command_and_its_dry_run_twin() -> None:
    """Defect caught: the README grows a second, divergent way to run this
    pack — the "README command A / CI helper B / Gate script C" split PR-12e
    §V.2 forbids. Specifically, the preview command and the real command drift
    apart, so a user previews one thing and runs another.

    Fails as: an inequality between the run command and the preview command
    with `--dry-run` removed, printing both argvs.

    Not caught elsewhere: no static checker reads Markdown, and every other
    test in this module consumes whatever the README says rather than judging
    whether the README says one thing.
    """
    preview = _published_command(PREVIEW_ANCHOR)
    run = _published_command(RUN_ANCHOR)

    assert preview[:2] == ["bash", "examples/tidmad/quickstart.sh"], preview
    assert run[:2] == ["bash", "examples/tidmad/quickstart.sh"], run
    assert preview[-1] == "--dry-run", preview
    assert preview[:-1] == run, (
        "the previewed command and the real command are not the same command:\n"
        f"  preview: {preview}\n  run:     {run}"
    )


def test_the_published_command_reaches_the_production_launcher_with_this_manifest(
    tmp_path: Path, staged_data: Path
) -> None:
    """Defect caught: the entrypoint stops reaching the normal production
    launcher with THIS pack's composition manifest — for example it grows its
    own orchestration, loses `--task_composition` (silently falling back to
    the legacy un-composed path), or points at another pack's manifest.

    Fails as: the dry-run transcript not containing
    `sdsc_submission_scripts/run_one_iteration.py`, or not containing
    `--task_composition <this checkout>/configs/task_composition/tidmad.yaml`.

    The command driven here is parsed from the README, so a README that
    publishes something else is what gets tested — and fails.
    """
    argv = _substituted(
        _published_command(PREVIEW_ANCHOR),
        workspace=tmp_path / "workspace",
        data_dir=staged_data,
    )
    result = _run(argv, cwd=REPO_ROOT, env=_venv_env())
    transcript = result.stdout + result.stderr
    assert result.returncode == 0, transcript

    manifest = REPO_ROOT / "configs" / "task_composition" / "tidmad.yaml"
    assert manifest.is_file(), f"this pack's shipped manifest is missing: {manifest}"

    assert "run_one_iteration.py" in transcript, transcript
    assert f"--task_composition {manifest}" in transcript, transcript
    # The launcher, not a copy of it.
    assert str(REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py") in transcript


def test_the_quickstart_bounds_the_run_with_task_agnostic_knobs(
    tmp_path: Path, staged_data: Path
) -> None:
    """Defect caught: the quickstart's bounded posture is expressed with
    `--data_scope` (or stops being bounded at all).

    `--data_scope` is a partition-index concept from TIDMAD's own topology and
    is refused BY NAME for a composed task that declares no such topology
    (PR-12bc B7), so it cannot be the shared quickstart mechanism across the
    example packs. A future editor "simplifying" the defaults to
    `--data_scope` would leave TIDMAD green and make the shape unusable for
    Pets, DAVIS and any fourth task — a defect invisible from within this pack.

    Fails as: `--data_scope` appearing in the resolved child argv, or one of
    the four bounding values not reaching it.
    """
    argv = _substituted(
        _published_command(PREVIEW_ANCHOR),
        workspace=tmp_path / "workspace",
        data_dir=staged_data,
    )
    result = _run(argv, cwd=REPO_ROOT, env=_venv_env())
    transcript = result.stdout + result.stderr
    assert result.returncode == 0, transcript

    child = transcript.split("[DRY-RUN] would exec from")[-1]
    assert "--data_scope" not in child, child
    for expected in (
        "--max_rounds 1",
        "--max_epochs 1",
        "--trial_portion 0.02",
        "--formal_portion 0.02",
    ):
        assert expected in child, f"{expected!r} did not reach the child argv:\n{child}"


def test_the_published_command_pins_iteration_1_against_a_corrupted_auto_resume(
    tmp_path: Path, staged_data: Path, noisy_inspector_venv: Path
) -> None:
    """Defect caught: the quickstart loses `--start_iter 1`, and a re-run on an
    EXISTING workspace silently does nothing while reporting success.

    Auto-resume is ON by default. On an existing workspace the launcher
    captures its start iteration from `scripts/inspect_run_state.py
    --next-iter` — a capture CLAUDE.md records as corrupted by plugin-loader
    stdout, naming `--start_iter N` as the workaround. The corrupted value
    reaches `seq`, which rejects it, so the iteration loop body never runs;
    the launcher then prints "<N> iterations walked" computed from the
    REQUESTED count rather than the walked one, and exits 0. Nothing about the
    exit status or the closing banner distinguishes that from a real run.

    Fails as: no "[DRY-RUN] would exec from" line in the transcript — i.e. the
    chain walked ZERO iterations — even though the process exited 0.

    Two fixture details are load-bearing and were both got wrong once:
      * the workspace must EXIST and be EMPTY. A non-existent workspace
        short-circuits to `START_ITER=1` before the inspector is ever
        consulted, which makes the assertion vacuous; a non-empty one is
        refused by the stale-fresh guard.
      * the corruption is PLANTED (see `noisy_inspector_venv`), because
        `agent_generated/models/` is gitignored and a clean checkout produces
        no pollution at all.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()  # exists and is empty -> the auto-resume path is taken

    argv = _substituted(
        _published_command(PREVIEW_ANCHOR), workspace=workspace, data_dir=staged_data
    )
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(noisy_inspector_venv)

    result = _run(argv, cwd=REPO_ROOT, env=env)
    transcript = result.stdout + result.stderr
    assert "would exec from" in transcript, (
        "the chain walked ZERO iterations and still reported success:\n" + transcript
    )
    assert "--start_iteration 1" in transcript, transcript


def test_the_published_command_pins_per_node_model_routing(
    tmp_path: Path, staged_data: Path
) -> None:
    """Defect caught: the quickstart loses `--llm_config`, or names a routing
    file that a clean checkout does not contain.

    The chain default is an empty `LLM_CONFIG` and the application default is
    `None`, so a missing flag does not fail — it silently falls back to the
    single `--llm_model` default with no per-node routing at all. A user
    following the README would then run every node on one model and have no
    signal that the documented posture was not applied.

    Fails as: the resolved child argv not carrying `--llm_config <repo>/
    llm_configs/openai_tiered_pro.json`, or that file not existing.
    """
    routing = REPO_ROOT / "llm_configs" / "openai_tiered_pro.json"
    assert routing.is_file(), f"the quickstart's routing file is missing: {routing}"

    argv = _substituted(
        _published_command(PREVIEW_ANCHOR),
        workspace=tmp_path / "workspace",
        data_dir=staged_data,
    )
    result = _run(argv, cwd=REPO_ROOT, env=_venv_env())
    transcript = result.stdout + result.stderr
    assert result.returncode == 0, transcript

    child = transcript.split("[DRY-RUN] would exec from")[-1]
    assert f"--llm_config {routing}" in child, child


def test_the_published_command_never_selects_the_legacy_single_file_path(
    tmp_path: Path, staged_data: Path
) -> None:
    """Defect caught: F-12d-26 — the quickstart acquires `--no-is_trial`, or is
    switched to the direct tuner-node CLI.

    `--is_trial` does not mean "this round is a trial"; it means "trials are
    ALLOWED", and it is the only input that can yield `mode="formal"`.
    Omitting it on the DIRECT node CLI falls through to `single_file`, the
    legacy TIDMAD path: the composed scope capability is never called, the
    file index is forced to TIDMAD's, scoring resolves the legacy subprocess
    route, and every `--formal_*` knob is silently ignored — while the run
    looks green. `run_one_iteration.py` defaults the flag to True, which is
    why wrapping `run_chain.sh` is safe and why passing `--no-is_trial` (which
    reads like "more rigorous") would not be.

    Fails as: `--no-is_trial` found in the published command, in the
    entrypoint's source, or in the resolved child argv; or the entrypoint
    invoking `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`.
    """
    script = QUICKSTART.read_text(encoding="utf-8")
    assert "--no-is_trial" not in script
    assert "ml_hyperparameter_tune_agent" not in script
    for anchor in (PREVIEW_ANCHOR, RUN_ANCHOR):
        assert "--no-is_trial" not in _published_command(anchor)

    argv = _substituted(
        _published_command(PREVIEW_ANCHOR),
        workspace=tmp_path / "workspace",
        data_dir=staged_data,
    )
    result = _run(argv, cwd=REPO_ROOT, env=_venv_env())
    transcript = result.stdout + result.stderr
    assert result.returncode == 0, transcript
    child = transcript.split("[DRY-RUN] would exec from")[-1]
    assert "--no-is_trial" not in child, child


# ---------------------------------------------------------------------------
# portability
# ---------------------------------------------------------------------------


def test_the_repo_root_is_resolved_from_the_script_location_not_the_cwd(
    tmp_path: Path, staged_data: Path
) -> None:
    """Defect caught: the entrypoint resolves the repository from `$PWD` (or
    from a relative path) instead of from its own location — CLAUDE.md's shell
    portability rule. A user who runs the published command from anywhere but
    the checkout root would then launch something else, or nothing.

    A plain "run it from another directory" check is not sufficient: it would
    merely fail to find a launcher. This plants a DECOY checkout at the
    working directory — a `sdsc_submission_scripts/run_chain.sh` that writes a
    marker, plus a matching `configs/task_composition/tidmad.yaml` — so a
    cwd-relative implementation succeeds loudly and is caught.

    Fails as: the decoy marker file existing after the run.
    """
    decoy = tmp_path / "decoy_checkout"
    (decoy / "sdsc_submission_scripts").mkdir(parents=True)
    (decoy / "configs" / "task_composition").mkdir(parents=True)
    marker = tmp_path / "decoy_launcher_ran.txt"
    (decoy / "sdsc_submission_scripts" / "run_chain.sh").write_text(
        f'#!/usr/bin/env bash\necho ran > "{marker}"\n', encoding="utf-8"
    )
    (decoy / "configs" / "task_composition" / "tidmad.yaml").write_text("{}\n", encoding="utf-8")

    argv = _substituted(
        _published_command(PREVIEW_ANCHOR),
        workspace=tmp_path / "workspace",
        data_dir=staged_data,
    )
    # The one documented deviation from the published command: an absolute
    # path to the entrypoint, because the point of this test is that the cwd
    # is NOT the checkout.
    argv[1] = str(QUICKSTART)

    result = _run(argv, cwd=decoy, env=_venv_env())
    transcript = result.stdout + result.stderr
    assert not marker.exists(), (
        "the entrypoint executed the DECOY launcher found in the working "
        f"directory instead of the one beside itself:\n{transcript}"
    )
    assert result.returncode == 0, transcript
    assert str(REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py") in transcript


def test_the_pack_publishes_no_machine_specific_absolute_path() -> None:
    """Defect caught: a path that exists on one developer's machine or one
    cluster is written into this pack's published surface — the class of
    defect F-12e-UX-1 recorded, where the documented chain invocation embedded
    `/home/klz/Data/...`.

    Fails as: a report of `<file>:<line>` for every offending occurrence.

    Scope is the pack's own tracked text (the two sibling packs carry recorded
    Gate-evidence paths in their PROVENANCE/STATUS, which are deliberate
    citations of a specific deployment and are not this pack's business).
    """
    offenders: list[str] = []
    for path in sorted(PACK_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in (".md", ".sh", ".yaml", ".yml", ".json"):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for prefix in MACHINE_SPECIFIC_PREFIXES:
                if prefix in line:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {prefix}")
    assert offenders == [], offenders


def test_the_pack_depends_on_no_other_example_pack() -> None:
    """Defect caught: this pack's entrypoint or documentation starts requiring
    a file from `examples/oxford_iiit_pet/` or
    `examples/davis_future_prediction/` — an external user following this
    README would then need a pack they never asked about, and the packs would
    stop being independent regression assets.

    Fails as: a report naming the file and the sibling pack it referenced.

    Comparative prose is allowed: only a `examples/<other_pack>` PATH counts,
    which is what an actual dependency looks like.
    """
    offenders: list[str] = []
    for path in sorted(PACK_ROOT.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for other in OTHER_PACK_NAMES:
            if f"examples/{other}" in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} -> examples/{other}")
    assert offenders == [], offenders


# ---------------------------------------------------------------------------
# refusals — the inputs that have no safe default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("omit", "expected_flag"),
    [("--workspace", "--workspace"), ("--data_dir", "--data_dir")],
    ids=["workspace", "data_dir"],
)
def test_a_missing_required_input_is_refused_by_name(
    tmp_path: Path, staged_data: Path, omit: str, expected_flag: str
) -> None:
    """Defect caught: the entrypoint acquires a DEFAULT for the workspace or
    the data root — the exact shape of F-12e-UX-1, where a published command
    silently depended on one machine's directory. A default here would make
    the quickstart appear to work while writing into, or reading from, a
    location the user never named.

    Fails as: a zero exit status (the run was delegated with an unstated
    input), or a refusal whose message does not name the missing flag, which
    is what turns a refusal into a usable instruction.
    """
    argv = ["bash", str(QUICKSTART)]
    if omit != "--workspace":
        argv += ["--workspace", str(tmp_path / "workspace")]
    if omit != "--data_dir":
        argv += ["--data_dir", str(staged_data)]
    argv.append("--dry-run")

    result = _run(argv, cwd=tmp_path, env=_venv_env())
    assert result.returncode != 0, result.stdout + result.stderr
    assert expected_flag in result.stderr, result.stderr


def test_a_data_root_holding_no_tidmad_files_is_refused_before_launch(tmp_path: Path) -> None:
    """Defect caught: the entrypoint delegates a launch whose `--data_dir`
    points at a real but WRONG directory. Pointing at the wrong directory is
    the most common first-run mistake, and without this check it surfaces only
    after the chain has already spent an LLM call — the launcher's own
    resolution validates that the directory EXISTS, not that it holds this
    task's files.

    Fails as: a zero exit status, or a message that does not name the expected
    file family, leaving the user without a next step.
    """
    empty = tmp_path / "wrong_directory"
    empty.mkdir()
    argv = [
        "bash",
        str(QUICKSTART),
        "--workspace",
        str(tmp_path / "workspace"),
        "--data_dir",
        str(empty),
        "--dry-run",
    ]
    result = _run(argv, cwd=tmp_path, env=_venv_env())
    assert result.returncode != 0, result.stdout + result.stderr
    assert "abra_" in result.stderr, result.stderr


# ---------------------------------------------------------------------------
# the inspection step (implemented by the report workstream)
# ---------------------------------------------------------------------------


def test_the_readme_report_command_matches_the_report_module() -> None:
    """Defect caught: the README publishes an inspection command whose flags
    the report module does not accept — a user's final step failing on a typo
    that no other test would see, because the README and the module are
    written by different workstreams.

    Fails as: a `--help` transcript missing `--workspace` or `--out` after the
    module exists.

    Skips cleanly while `tools/run_report` is absent: this pack does not own
    that module, and a hard failure here would report someone else's
    unfinished work as this pack's defect.
    """
    argv = _published_command(REPORT_ANCHOR)
    assert argv[:3] == ["python", "-m", "tools.run_report"], argv
    assert WORKSPACE_PLACEHOLDER in argv and REPORT_PLACEHOLDER in argv, argv

    if not (REPO_ROOT / "tools" / "run_report").exists():
        pytest.skip("tools/run_report does not exist yet (owned by the report workstream)")

    result = subprocess.run(
        [sys.executable, "-m", "tools.run_report", "--help"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
    )
    transcript = result.stdout + result.stderr
    assert "--workspace" in transcript, transcript
    assert "--out" in transcript, transcript
