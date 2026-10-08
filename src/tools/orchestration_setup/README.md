# Prepare your own orchestration project

Use this tool to install the SIDERIUS agent instructions in **your external
project directory**. You then author your task, experiment and caller there.
The caller chooses which native capabilities to invoke and saves their results.
The tool adds no scientific defaults, scheduler or compulsory review step.

This first entry requires a SIDERIUS source checkout and its own frozen Python
environment. It copies documentation without importing your task, contacting a
provider, downloading data or starting training. Actual sandbox execution needs
Linux and bubblewrap; see the [sandbox guide](../workspace_sandbox/README.md).

## Install the instructions

From your selected SIDERIUS checkout, create a fresh external project and a
separate directory for the assembly inputs. This example deliberately leaves
scientific configuration unfinished:

```bash
uv sync --group dev --frozen
infra_python="$(pwd)/.venv/bin/python"
project_dir="$(mktemp -d /tmp/siderius-project.XXXXXX)"
setup_inputs="$(mktemp -d /tmp/siderius-setup-inputs.XXXXXX)"

"$infra_python" - "$project_dir" "$setup_inputs" <<'PY'
import json
import sys
from pathlib import Path

project = Path(sys.argv[1]).resolve()
inputs = Path(sys.argv[2])
(inputs / "sandbox.json").write_text(json.dumps({
    "workspace": str(project),
    "read_only": [],
    "network": False,
    "devices": [],
    "environment_names": [],
    "timeout_seconds": 30
}, indent=2))
(inputs / "run.md").write_text("""# Run declaration

Phase: preparation; execution is not yet configured or authorized.
Project: """ + str(project) + """
Task instructions and manifest: UNCONFIGURED
Experiment and allowed data/partitions: UNCONFIGURED
Enabled capabilities and model routing: UNCONFIGURED
Shared API/training/wall-time limits: UNCONFIGURED
Authorized evidence and advice files: UNCONFIGURED
Caller script and required result files: UNCONFIGURED
Qualified framework revision/environment: UNCONFIGURED

During preparation, author task and experiment files in this project.
Before execution, finish these declarations and protect selected inputs
through sandbox.json. Installing these instructions grants no run budget.
""")
print(project)
PY

"$infra_python" -m tools.orchestration_setup \
    --profile "$setup_inputs/sandbox.json" \
    --run-declaration "$setup_inputs/run.md"

cat "$project_dir/RUN-ORCHESTRATION.md"
```

The 30-second timeout above is for an initial isolation check, **not a training
budget**. Replace it with your authorized invocation limit before real work.
Keep the printed project path and exact Python path for later shells.

The new files are:

```text
your-project/
  AGENTS.md
  SIDERIUS-RUN.md                         edit this run declaration
  sandbox.json                            edit this isolation configuration
  RUN-ORCHESTRATION.md                     exact check/run commands and next steps
  .agents/skills/siderius-toolkit/         native capability guides
  .siderius-orchestration-assembly.json    installation inventory
```

No task, experiment or `scripts/caller.py` is generated. Their science and
execution choices belong to you and your agent. The example starts offline
without GPU access or forwarded secrets. Your run declaration and profile must
explicitly authorize/configure any later network, credentials and device access.

## Go from preparation to a run

Start your agent in the printed project directory and ask it to read `AGENTS.md`
and `SIDERIUS-RUN.md`. Supply your task description, data dictionary/location and
constraints. Follow `RUN-ORCHESTRATION.md` to author the task and experiment,
create `scripts/caller.py`, bind the native task context, configure result
storage, check isolation and execute the saved caller. It contains commands with
your actual paths, usable from another working directory.

Inspect **the copies inside your project** before launch. The original files in
`setup_inputs` are not loaded by those commands. Changing a model or budget in
one of those original files will not change the project copy. Advice, LLM
configuration and data must be named by the run/caller and exposed through the
profile when they live outside the project. Secret values belong in the launching
environment, never in the run declaration or configuration files.

The optional review skill may help inspect a setup; its receipt is not required
by this tool. Native schemas/runtime checks still apply. A successful assembly
means the documentation was installed, and a successful sandbox `check` means
basic imports/filesystem access worked. Neither establishes scientific readiness,
authentication, CUDA qualification or successful training. In particular, GPU
process attribution inside the sandbox still needs qualification.

## Preserve your work

Existing task/experiment files are left intact. If any destination instruction,
profile or inventory already exists, assembly refuses **before writing files**.
Do not re-run it as an update operation; edit the project copies or assemble in a
fresh directory. Symlinked output ancestors are refused. Use a directory you
control and do not concurrently replace its directories while assembling.

If a disk or permission error interrupts publication, already written files
remain and the completion inventory is absent. The error names the incomplete
project. Inspect it or choose a new directory; the tool never recursively deletes
your files. Individual writes are atomic, but the entire installation is not a
single filesystem transaction.

The inventory records initial file hashes, Python, source HEAD and whether the
source tree was dirty. It is not a complete environment lock or a stale-review
gate. Changing your own files after installation is expected. Keep experiment
version pins and run provenance in the experiment and resulting records.

## Professional and Assistant routes

Both routes recommend a coding agent. Professional users lead caller design and
direct the agent's implementation; Assistant users ask the agent to read the
installed toolkit and guide them through authoring the caller. Manual authoring
is possible, but is not the recommended starting route. Neither requires a
review receipt. The [optional setup review](../setup_review/README.md) can inspect
supported standard-workflow snapshots, but it does not review arbitrary Python
caller control flow or grant a caller-wide launch approval. Keep the caller and
run declaration explicit, and inspect the actual run outputs and status.
