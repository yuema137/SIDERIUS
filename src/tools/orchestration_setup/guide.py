"""Render concrete preparation and execution paths without scientific defaults."""

from pathlib import Path
from shlex import join


def render_guide(project: Path, python: str) -> str:
    profile = str(project / "sandbox.json")
    prefix = [python, "-m", "tools.workspace_sandbox"]
    check = join([*prefix, "check", profile])
    launch = join([*prefix, "run", profile, "--", python, str(project / "scripts/caller.py")])
    return f"""# Your orchestration project

The instructions have been installed in `{project}`. No task was validated,
no provider was called and no experiment was launched. This guide records the
Python selected during assembly: `{python}`. If you move this project or change
the installation, update the paths in your profile and saved commands.

## Prepare your files

1. Read `AGENTS.md` and `.agents/skills/siderius-toolkit/SKILL.md`.
2. Edit **this project's `SIDERIUS-RUN.md`**. It is now the authoritative run
   declaration; the file supplied to the assembler is only its source copy.
   Record the task/experiment paths, data and allowed partitions, enabled
   capabilities, model routing, shared budgets, advice and required outputs.
   Replace any UNCONFIGURED entries before an affected operation.
3. Author your task and experiment here, for example under `task/` and
   `experiment/`. These are suggested locations, not automatically created
   scientific configurations. Preparation can change your own files. Before
   execution, declare the selected frozen inputs under `sandbox.json`'s
   `read_only`; keep results writable.
4. Create `scripts/caller.py` using the toolkit's
   [native invocation guide](.agents/skills/siderius-toolkit/references/invocation.md).
   You choose capabilities and their order. Bind the generated library before
   node imports, construct native validated inputs, and save returned outputs.
   The assembler has not created this caller for you.
5. In `sandbox.json`, check all mounted paths, network/device access,
   credential **names**, and the per-command timeout. Export required secrets
   in the launching shell; never put their values in these files. Declare any
   calibration/configuration paths explicitly: the sandbox has a private home.

The optional setup-review skill is not a prerequisite. Ordinary native task and
runtime checks still apply. This file is not a review receipt or permission to
spend a provider/training budget.

## Check isolation, then launch your saved caller

This command tests imports and filesystem access only; it does not validate your
task, provider authentication or CUDA readiness:

```bash
{check}
```

After your caller and declarations are complete and execution is authorized,
run this exact command from any directory:

```bash
{launch}
```

It executes `{project / "scripts/caller.py"}` inside the declared sandbox with
`{project}` as its working directory. The caller and its descendants are
isolated; an outer agent using host tools remains outside that boundary. A
failed check does not fall back to running without isolation.

## Find and rerun your results

Choose an output directory in your caller and run declaration, such as
`{project / "results/run-001"}`. Pass it through the native node's storage or
workspace settings and persist its typed returned output. The sandbox does not
choose filenames or collect a result automatically. The temporary home and
`/tmp` disappear at exit, so do not store durable results there.

For another attempt, edit your project-owned task/experiment, record the new
configuration and select another result directory in the caller. Review frozen
input paths and rerun the check and launch above. Do not overwrite earlier
evidence or reset the shared budget merely by starting another process.

`.siderius-orchestration-assembly.json` records the initially installed file
hashes and source revision. It is installation provenance, not a freshness gate
or evidence of completed training. Re-running assembly refuses existing files;
edit your project copies rather than re-installing over them.
"""
