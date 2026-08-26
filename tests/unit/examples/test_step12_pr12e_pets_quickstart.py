"""Step 12 / PR-12e — the Oxford-IIIT Pet pack's ONE documented run command.

These tests own ONE property: **the command a user copies out of
`examples/oxford_iiit_pet/README.md` is the command that reaches the normal
SIDERIUS production launcher, bound to this pack's composition manifest, with
no machine-specific path baked into it** (design §V.2 entrypoint contract,
§V.3 self-contained boundary, §V.14c "reuse, do not invent").

Why each test here cannot be replaced by a static checker, Pydantic, ruff or
pyright: every claim is about a *shell script's runtime behaviour* and about
*agreement between prose and an executable*. No type system reads Markdown,
and no linter knows that `--task_composition` must end at `pets.yaml`.

Cost: two of these tests spawn `run_chain.sh --dry-run`, which the launcher
documents as "walk the chain, print exact commands, no side effects". No LLM
call, no GPU, no training, no workspace mutation — `run_chain` only creates
the workspace when `DRY_RUN` is 0 (`_chain_common.sh`). `--dry-run` is
APPENDED to the published command rather than substituted into it, so the
path under test is the published path right up to the exec point.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "examples" / "oxford_iiit_pet"
README = PACK / "README.md"
QUICKSTART = PACK / "quickstart.sh"

#: The two placeholders the README publishes. Named here as literals so a
#: rename in the README breaks these tests loudly instead of silently
#: leaving the substitution below pointing at nothing.
WORKSPACE_PLACEHOLDER = "/path/to/pets-quickstart-workspace"
DATA_DIR_PLACEHOLDER = "/path/to/oxford-iiit-pet/images"

#: Path prefixes that only exist on somebody's particular machine. A
#: published quickstart that contains one of these is unrunnable for every
#: other reader (design §V.1 F-12e-UX-1).
MACHINE_LOCAL_PREFIXES = ("/home/", "/Users/", "/expanse/", "/scratch/", "/workspace/")

OTHER_PACKS = ("tidmad", "davis_future_prediction")


def _fenced_blocks(markdown: str, language: str) -> list[str]:
    """Every ```<language> fenced block's body, in document order."""
    pattern = re.compile(rf"^```{language}\n(.*?)^```", re.MULTILINE | re.DOTALL)
    return [match.group(1) for match in pattern.finditer(markdown)]


def _published_run_command() -> str:
    """The single README code block that invokes the quickstart with a workspace.

    Deliberately strict: if the README ever grows a SECOND runnable
    quickstart invocation, this raises instead of silently picking one. That
    ambiguity is the exact failure §V.2 forbids — "there must not be a README
    command A, a CI helper B and a Gate script C".
    """
    blocks = [
        block
        for block in _fenced_blocks(README.read_text(encoding="utf-8"), "bash")
        if "quickstart.sh" in block and "--workspace" in block
    ]
    assert len(blocks) == 1, (
        f"expected exactly ONE published quickstart run command in {README}, found {len(blocks)}"
    )
    return blocks[0].strip()


def _argv_from(command: str) -> list[str]:
    """Split a published shell command (with `\\` line continuations) into argv."""
    return command.replace("\\\n", " ").split()


def _run_dry(argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Drive the entrypoint with `--dry-run` appended. Returns the completed run."""
    env = dict(os.environ)
    # Pin the interpreter the launcher resolves to the one running pytest, so
    # the probe exercises THIS checkout's environment rather than whichever
    # `.venv` happens to exist next to the script (CLAUDE.md portability).
    env["VIRTUAL_ENV"] = str(Path(sys.executable).resolve().parents[1])
    return subprocess.run(
        [*argv, "--dry-run"],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def _exec_lines(stdout: str) -> list[str]:
    """The launcher's dry-run lines naming the child it WOULD exec.

    `submit_iteration_lilab` prints `[DRY-RUN] would exec from <dir>:` and
    then the command on the NEXT line, so the child argv is the line after
    each marker. Everything else on stdout is plugin-loader noise.
    """
    lines = stdout.splitlines()
    return [
        lines[index + 1]
        for index, line in enumerate(lines)
        if "[DRY-RUN] would exec" in line and index + 1 < len(lines)
    ]


# ---------------------------------------------------------------------------
# The entrypoint exists and is runnable as published
# ---------------------------------------------------------------------------


def test_the_published_command_names_a_real_executable_entrypoint() -> None:
    """Defect caught: the README publishes a run command whose script does not
    exist, is not executable, or is not the file this pack ships — the "ONE
    obvious run entrypoint" is a promise a reader cannot act on.

    How it fails: the README's first command word is resolved against the
    repository root; a missing file, a non-executable bit, or a script path
    that stops matching `examples/oxford_iiit_pet/quickstart.sh` fails here.
    """
    assert QUICKSTART.is_file(), f"{QUICKSTART} does not exist"
    assert os.access(QUICKSTART, os.X_OK), f"{QUICKSTART} is not executable"

    argv = _argv_from(_published_run_command())
    assert argv[0] == "bash", f"published command should be driven with bash, got {argv[0]!r}"
    published_script = argv[1]
    assert published_script == "examples/oxford_iiit_pet/quickstart.sh", (
        f"the README publishes {published_script!r}; this test drives that exact path"
    )
    assert (REPO_ROOT / published_script).resolve() == QUICKSTART.resolve()

    # The placeholders the substitution below depends on.
    command = _published_run_command()
    assert WORKSPACE_PLACEHOLDER in command
    assert DATA_DIR_PLACEHOLDER in command


# ---------------------------------------------------------------------------
# Refusals — both required inputs, by name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("omitted", "supplied_flag"),
    [("--workspace", "--data_dir"), ("--data_dir", "--workspace")],
)
def test_entrypoint_refuses_by_name_when_a_required_input_is_missing(
    tmp_path: Path, omitted: str, supplied_flag: str
) -> None:
    """Defect caught: the entrypoint acquires a DEFAULT for the workspace or the
    data root. Both are machine-local; a default for either is how a published
    command silently works on exactly one machine (§V.1 F-12e-UX-1). A default
    would also push the refusal minutes downstream into the composition root,
    after the launcher has already started an iteration.

    How it fails: with one of the two flags omitted the script must exit
    non-zero AND name the missing flag on stderr. If a default is introduced,
    the run proceeds and the exit status is no longer 2.
    """
    result = subprocess.run(
        ["bash", str(QUICKSTART), supplied_flag, str(tmp_path)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2, f"expected refusal exit 2, got {result.returncode}"
    assert omitted in result.stderr, f"stderr must name {omitted}; got:\n{result.stderr}"
    assert "MISSING REQUIRED ARGUMENT" in result.stderr


def test_entrypoint_refuses_a_data_root_that_does_not_exist(tmp_path: Path) -> None:
    """Defect caught: the entrypoint accepts a data root that is not there and
    defers the failure into the training subprocess, where it surfaces as a
    missing-JPEG traceback per manifest row rather than as "you have not
    prepared the data yet".

    How it fails: pointing `--data_dir` at a non-existent path must exit 2 and
    say so. Drop the directory check and the script execs the launcher, which
    exits with a different status and a different message.
    """
    result = subprocess.run(
        [
            "bash",
            str(QUICKSTART),
            "--workspace",
            str(tmp_path / "ws"),
            "--data_dir",
            str(tmp_path / "definitely-not-prepared"),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2
    assert "DATA DIRECTORY NOT FOUND" in result.stderr
    assert "fetch_oxford_iiit_pet" in result.stderr, (
        "the refusal must point at the documented preparation command"
    )


# ---------------------------------------------------------------------------
# The published command reaches the real production launcher, composed
# ---------------------------------------------------------------------------


@pytest.fixture
def prepared_paths(tmp_path: Path) -> tuple[Path, Path]:
    """A workspace and a stand-in images root, both under `tmp_path`.

    The workspace is CREATED (empty) on purpose. `run_chain.sh` short-circuits
    auto-resume when the workspace does not exist yet, so a non-existent one
    would silently skip the resume path the entrypoint's `--start_iter` pin
    exists to bypass — the probe would then be green without ever exercising
    it. Empty rather than populated, so the launcher's stale-fresh guard
    still admits a fresh chain.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    images = tmp_path / "oxford-iiit-pet" / "images"
    images.mkdir(parents=True)
    return workspace, images


def test_the_published_command_reaches_run_chain_with_this_packs_composition(
    prepared_paths: tuple[Path, Path],
) -> None:
    """Defect caught: the README's command stops reaching the production chain
    launcher bound to THIS pack — e.g. the entrypoint drifts to the direct
    tuner node CLI, loses `--task_composition`, or binds another task's
    manifest. Any of those makes the pack's documented run either a different
    architecture or a different task, while still "working".

    Also guards **F-12d-26**: `--is_trial` does not mean "this round is a
    trial", it means trials are ALLOWED, and it is the only input that can
    yield a formal round. `run_one_iteration.py` defaults it TRUE; passing
    `--no-is_trial` drops the run into the legacy single-file TIDMAD path
    where the composed scope capability is never called and every bounded
    knob is silently ignored. The published command must never carry it.

    How it fails: the launcher's own `--dry-run` prints the exact child argv.
    If the entrypoint stops execing `run_chain.sh`, that line disappears; if
    the composition ref moves, the asserted suffix stops matching; if
    `--no-is_trial` is added, the membership assertion fires.
    """
    workspace, images = prepared_paths
    command = _published_run_command()
    argv = _argv_from(
        command.replace(WORKSPACE_PLACEHOLDER, str(workspace)).replace(
            DATA_DIR_PLACEHOLDER, str(images)
        )
    )

    result = _run_dry(argv, cwd=REPO_ROOT)
    assert result.returncode == 0, (
        f"dry-run failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
    )

    # ZERO exec lines is the failure mode this count exists for, and it is a
    # real one: with auto-resume against an existing workspace the launcher
    # captures the start iteration from `inspect_run_state.py`'s STDOUT, which
    # the plugin loader also writes to. On a machine whose plugin directory is
    # non-empty the capture is corrupted, `seq` receives the plugin banner
    # instead of an integer, the loop iterates over nothing, and the chain
    # still reports success. Dropping the entrypoint's `--start_iter` pin
    # reproduces exactly that (CLAUDE.md, Step 10 / P5+P6 carried debt).
    exec_lines = _exec_lines(result.stdout)
    assert len(exec_lines) == 1, (
        f"expected the chain to walk exactly ONE iteration, saw {len(exec_lines)}. "
        f"Zero means the iteration loop received an empty range — see the "
        f"`--start_iter` note in quickstart.sh."
    )
    child = exec_lines[0].split()

    # The real production runner, in THIS checkout — not the direct node CLI.
    runner = str(REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py")
    assert runner in child, f"child argv does not invoke {runner}:\n{exec_lines[0]}"
    assert not any("ml_hyperparameter_tune_agent" in part for part in child), (
        "the entrypoint must wrap run_chain.sh, not the direct tuner node CLI (F-12d-26)"
    )

    # Composed, against THIS pack's manifest.
    composition = child[child.index("--task_composition") + 1]
    assert composition.endswith("configs/task_composition/pets.yaml"), composition
    assert (
        Path(composition).resolve()
        == (REPO_ROOT / "configs" / "task_composition" / "pets.yaml").resolve()
    )

    # The data root the user supplied actually crosses to the child. Without
    # it a composed run falls back to the import-time TIDMAD_DATA_DIR.
    assert child[child.index("--data_dir") + 1] == str(images)

    # The README (§6) promises that BOTH blocking health gates fire and
    # invalidate the round — this pack's preserved Step-08 evidence. That
    # promise needs `healthgate_mode=blocking`, which the entrypoint
    # deliberately does NOT restate: it is the chain's default and is
    # forwarded unconditionally. Asserting it on the CHILD keeps the promise
    # owned by the run that is actually launched, so a change to the
    # launcher's default surfaces here rather than as a quickstart that
    # silently stops demonstrating the health system.
    assert child[child.index("--healthgate_mode") + 1] == "blocking"
    assert child[child.index("--result_authority") + 1] == "scientific"

    # F-12d-26: neither spelling of the flag may appear.
    assert "--no-is_trial" not in child
    assert "--is_trial" not in child, (
        "the chain must leave --is_trial at its True default; naming it here "
        "would pin a value the launcher deliberately does not pass"
    )

    # The bounded knobs that actually reach a composed task's scope
    # capability. `--data_scope` is refused by name for a task declaring no
    # TIDMAD topology, and `--target_files` is a chain-level no-op, so
    # neither may be how this run is bounded (§V.1 F-12e-UX-2).
    assert "--data_scope" not in child
    assert child[child.index("--start_iteration") + 1] == "1"
    for flag in ("--trial_portion", "--eval_portion", "--formal_portion"):
        assert child[child.index(flag) + 1] == "1.0", (
            f"{flag} must be pinned to 1.0: the chain defaults it to 0.1, which "
            f"cuts the 370-image bounded subset to 37 and stops the documented "
            f"37-class collapse from reproducing"
        )


def test_entrypoint_resolves_the_repository_from_its_own_location_not_the_cwd(
    prepared_paths: tuple[Path, Path],
) -> None:
    """Defect caught: the entrypoint resolves the repository (and therefore the
    launcher, the composition manifest and the LLM config) relative to the
    CALLER's working directory. It would work when run from the repo root —
    which is how everyone tests it — and bind nothing, or another clone's
    files, when run from anywhere else.

    How it fails: the script is invoked by ABSOLUTE path from a `tmp_path`
    cwd that contains no `configs/`. A cwd-relative script refuses at its own
    "TASK COMPOSITION MANIFEST NOT FOUND" check (exit 2); a location-relative
    one emits this checkout's manifest, which is what is asserted.
    """
    workspace, images = prepared_paths
    result = _run_dry(
        ["bash", str(QUICKSTART), "--workspace", str(workspace), "--data_dir", str(images)],
        cwd=images.parent,
    )
    assert result.returncode == 0, f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"

    exec_lines = _exec_lines(result.stdout)
    assert len(exec_lines) == 1
    child = exec_lines[0].split()
    composition = Path(child[child.index("--task_composition") + 1]).resolve()
    assert composition == (REPO_ROOT / "configs" / "task_composition" / "pets.yaml").resolve(), (
        f"resolved {composition} — the entrypoint used the caller's cwd, not its own location"
    )


# ---------------------------------------------------------------------------
# Self-containment of the published surface
# ---------------------------------------------------------------------------


def _published_surface() -> dict[Path, str]:
    """The pack files a user READS AND COPIES COMMANDS FROM.

    Deliberately not the whole pack: `STATUS.md` and `PROVENANCE.md` record
    the absolute workspaces of past real Gate runs, which is evidence
    provenance a reader is meant to see, and is nothing anyone types.
    """
    return {path: path.read_text(encoding="utf-8") for path in (README, QUICKSTART)}


def test_no_machine_local_path_appears_in_the_published_quickstart_surface() -> None:
    """Defect caught: the README or the entrypoint acquires an absolute path
    that exists on one developer's machine — the F-12e-UX-1 class, where a
    published quickstart is unrunnable for every other reader. This is how
    the previous published chain invocation embedded `/home/klz/Data/...`.

    How it fails: any `/home/`, `/Users/`, `/expanse/`, `/scratch/` or
    `/workspace/` prefix in the user-journey files is reported with its file
    and line. Placeholders (`/path/to/...`) and repo-relative paths pass.
    """
    offenders: list[str] = []
    for path, text in _published_surface().items():
        for lineno, line in enumerate(text.splitlines(), start=1):
            for prefix in MACHINE_LOCAL_PREFIXES:
                if prefix in line:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "machine-local paths in the published surface:\n" + "\n".join(offenders)


def test_the_pets_quickstart_does_not_depend_on_another_example_pack() -> None:
    """Defect caught: this pack's user journey starts referring to another
    example pack's files — a reader could then not run Pets from a checkout
    that contains only this pack's data, and the three packs stop being
    independent genericity evidence (§V.10 "no dependency on the other
    examples").

    How it fails: a mention of `examples/tidmad` or
    `examples/davis_future_prediction` anywhere in the published surface, or
    in the composition manifest this pack binds, is reported by name.
    """
    surfaces = dict(_published_surface())
    manifest = REPO_ROOT / "configs" / "task_composition" / "pets.yaml"
    surfaces[manifest] = manifest.read_text(encoding="utf-8")

    offenders = [
        f"{path.relative_to(REPO_ROOT)} references examples/{other}"
        for path, text in surfaces.items()
        for other in OTHER_PACKS
        if f"examples/{other}" in text
    ]
    assert not offenders, "\n".join(offenders)


# ---------------------------------------------------------------------------
# The rest of the journey: preparation in, report out
# ---------------------------------------------------------------------------


def test_the_readme_publishes_the_existing_fetch_tool_as_the_preparation_step() -> None:
    """Defect caught: the pack grows a SECOND data-acquisition path — a
    pack-local downloader duplicating `tools/example_packs/fetch_oxford_iiit_pet`,
    which already verifies both archives against committed SHA-256 pins. Two
    downloaders means one of them stops being the verified one.

    How it fails: the README must publish the existing module by its real
    import path, and that module must exist. A pack-local `fetch`/`download`/
    `prepare` script under `examples/oxford_iiit_pet/` fails the second half.
    """
    readme = README.read_text(encoding="utf-8")
    assert "tools.example_packs.fetch_oxford_iiit_pet" in readme
    assert (REPO_ROOT / "tools" / "example_packs" / "fetch_oxford_iiit_pet.py").is_file()

    rival = [
        entry.name
        for entry in PACK.iterdir()
        if entry.is_file()
        and entry.name != "quickstart.sh"
        and re.search(r"fetch|download|prepare|acquire", entry.name, re.IGNORECASE)
    ]
    assert not rival, f"a second data-acquisition entrypoint appeared in the pack: {rival}"


def test_the_readme_publishes_the_frozen_report_command() -> None:
    """Defect caught: the pack's inspect step drifts from the ONE report
    interface every example pack publishes, so each example grows its own
    result-viewing dialect.

    How it fails: the README must publish `python -m tools.run_report` with
    `--workspace` and `--out`. Once `tools/run_report` is merged, the module's
    presence is also asserted; until then that half is skipped rather than
    inverted, so this test tightens automatically at integration instead of
    needing an edit.
    """
    readme = README.read_text(encoding="utf-8")
    assert "python -m tools.run_report" in readme
    report_block = next(
        block for block in _fenced_blocks(readme, "bash") if "tools.run_report" in block
    )
    assert "--workspace" in report_block and "--out" in report_block

    if not (REPO_ROOT / "tools" / "run_report").exists():
        pytest.skip("tools/run_report is not merged yet (PR-12e reporting workstream)")
    assert (REPO_ROOT / "tools" / "run_report" / "__init__.py").is_file()


def test_the_readme_sets_the_expectation_that_the_health_gates_fail() -> None:
    """Defect caught: the README stops warning that this pack's reference model
    deterministically collapses to chance accuracy and trips both of its
    BLOCKING health gates. A new user then reads an invalidated round as a
    broken install, and the natural repair — tuning the collapse away — would
    destroy preserved Step-08 health evidence.

    How it fails: the collapse value, both gate ids and the word "invalidated"
    must all survive in the README. Hardcoded here, not read back from
    `declared/task_health.yaml`, so a change to either side is a conflict
    someone has to resolve deliberately.
    """
    readme = README.read_text(encoding="utf-8")
    assert "0.027" in readme, "the README must state the expected chance-level accuracy"
    for gate_id in ("pets_distinct_symbols_blocking", "pets_dominant_fraction_blocking"):
        assert gate_id in readme, f"the README must name the blocking gate {gate_id}"
    assert "invalidated" in readme.lower()


def test_the_readme_documents_the_journey_in_the_frozen_order() -> None:
    """Defect caught: the README reverts to a pack-IDENTITY document — the
    PR0-era shape that stated what the framework could not do and stopped —
    or reorders the journey so a reader meets the run command before knowing
    which data to prepare or where it must live.

    How it fails: the seven §V.3 stages must appear in the README in order.
    A missing or transposed stage reports the first offending pair.
    """
    readme = README.read_text(encoding="utf-8")
    stages = [
        ("repo-shipped assets", "What the repository already ships"),
        ("external data dependency", "What you must supply"),
        ("preparation command", "tools.example_packs.fetch_oxford_iiit_pet"),
        ("prepared-data location", "Where the prepared data goes"),
        ("run command", "bash examples/oxford_iiit_pet/quickstart.sh"),
        ("output location", "Where the output lands"),
        ("visualization command", "python -m tools.run_report"),
    ]
    positions: list[tuple[str, int]] = []
    for label, marker in stages:
        index = readme.find(marker)
        assert index != -1, f"the README no longer documents the {label!r} stage ({marker!r})"
        positions.append((label, index))
    for (earlier, first), (later, second) in pairwise(positions):
        assert first < second, f"{earlier!r} must precede {later!r} in the README"


def test_bash_is_available_for_the_probes() -> None:
    """Defect caught: this module's dry-run probes silently stop exercising the
    entrypoint because `bash` is absent, leaving the whole file green while
    proving nothing.

    How it fails: `shutil.which` returns None and this test — the only one
    here that would otherwise pass vacuously — reports it.
    """
    assert shutil.which("bash") is not None, "bash is required to drive quickstart.sh"
