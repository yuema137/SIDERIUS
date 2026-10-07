# Run orchestration code in an explicit workspace sandbox

Use this optional Linux launcher when an orchestration caller needs to run code
while keeping the SIDERIUS installation and selected inputs read-only. It starts
exactly the command you supply. It does not choose agents, models, data splits,
training order or scientific policy, and existing workflow commands do not use
it automatically.

You need a frozen SIDERIUS environment, Linux with working user namespaces, and
`bubblewrap` (`bwrap` on `PATH`). If isolation cannot start, the command fails;
it never retries without the sandbox. This is basic execution isolation, not
the paper experiments' protected evaluation environment.

## Try it without API keys, data or a GPU

Run these commands from the SIDERIUS checkout you intend to use:

```bash
uv sync --group dev --frozen
infra_python="$(pwd)/.venv/bin/python"
demo_project="$(mktemp -d /tmp/siderius-orchestration.XXXXXX)"

"$infra_python" - "$demo_project" <<'PY'
import json
import sys
from pathlib import Path

project = Path(sys.argv[1]).resolve()
inputs = project / "inputs"
inputs.mkdir()
(inputs / "task.txt").write_text("Example read-only input.\n")
(project / "sandbox.json").write_text(json.dumps({
    "workspace": str(project),
    "read_only": [str(inputs)],
    "network": False,
    "devices": [],
    "environment_names": [],
    "timeout_seconds": 30
}, indent=2))
print(project / "sandbox.json")
PY

"$infra_python" -m tools.workspace_sandbox preview "$demo_project/sandbox.json"
"$infra_python" -m tools.workspace_sandbox check "$demo_project/sandbox.json"
"$infra_python" -m tools.workspace_sandbox run "$demo_project/sandbox.json" -- \
    "$infra_python" -c 'from pathlib import Path; Path("result.txt").write_text("completed\n")'
cat "$demo_project/result.txt"
```

`preview` describes the configuration and checks prerequisites without starting
a sandbox; its status is `not_run`. `check` actually starts the same Python
inside the declared mounts, verifies imports, read-only mounts and temporary
writes, then removes its probe files. It prints `status: passed` for those checks.
Neither command qualifies GPU access, provider authentication or a scientific
task. `run` executes the supplied command with the project as its working
directory. In this example it writes `result.txt` in the printed external project.

Keep the absolute `infra_python` and project paths for later shells. To launch
your caller, replace the example `-c` command with its saved script, such as
`"$infra_python" "$demo_project/scripts/caller.py"`. That script still needs the
[task context and native node inputs](../../../docs/agent-reference/orchestrator-toolkit/payload/.agents/skills/siderius-toolkit/references/invocation.md).
The launcher supplies isolation, not missing task configuration.

## What to configure before a real run

Edit **your external `sandbox.json`**, then run `check` again:

| Field | Meaning |
|---|---|
| `workspace` | Existing canonical absolute directory where caller code and results may be written. It cannot overlap the installed runtime. |
| `read_only` | Existing absolute files/directories to expose without write access. A selected task or experiment inside the workspace can be frozen this way. Paths retain their host names inside the sandbox. |
| `network` | Required explicit boolean. `false` isolates the network; `true` grants host-network access, including provider access. It does not filter destinations or authorize spending. |
| `devices` | Explicit character-device paths under `/dev`, for example the devices required by your qualified GPU setup. No GPU is exposed by default. This is access, not a GPU allocation or VRAM budget. |
| `environment_names` | Names to copy from the launching shell, such as `OPENAI_API_KEY` or a declared calibration setting. Missing/empty variables are reported by name before launch. Never put key values in this file or the command line. |
| `timeout_seconds` | Required positive finite wall-clock cap for this invocation. Timeout returns status `timed_out` and exit code 124; cleanup may add a short grace period. This does not reset or replace the experiment's shared API/training budgets. |

Minimal system libraries and the exact launching Python environment/source are
mounted read-only, including the base interpreter needed by a UV virtualenv.
Other external dependencies need explicit read-only roots. Use canonical paths;
ambiguous caller symlinks and mounts over reserved control paths are refused.
Do not use pre-existing writable hard links to protected input files: path
mounts cannot prevent writes through a separate writable inode alias. Prepare
a fresh workspace rather than treating hostile pre-existing contents as safe.

The caller gets a private temporary home and `/tmp`; they disappear at exit.
The launcher supplies the internal username `siderius` through `USER` and
`LOGNAME` so libraries can resolve per-user cache paths without the host account
database. These identity variables cannot be forwarded from the host. They do
not change the process's numeric permissions or create a host account.
Host home configuration, authentication files and caches are not inherited.
Declare calibration, model/strategy configuration or other required resources
explicitly, expose their paths read-only where appropriate, and forward only
the settings needed to select them. Write durable records under `workspace`.
All files under an exposed root are readable: use a source installation without
embedded credentials, and avoid mounting unrelated private directories.

Forwarded credentials are available to the caller and its descendants. The
launcher does not serialize their values, but arbitrary child code can print or
transmit values it receives. Child stdout/stderr pass through unchanged. The
JSON execution summary on stderr contains only status, exit code and elapsed time.

For GPU execution, validate the actual runtime libraries and selected device
mounts before training. The lightweight `check` does not establish CUDA readiness.
Host `/sys` is not implicitly exposed. Add `/sys` to `read_only` when your
hardware runtime needs that metadata. On the checked RTX 5090 host, explicitly
mounting its device nodes plus read-only `/sys` allowed an `nvidia-smi` device
query; device nodes alone did not. This is driver visibility evidence, not a
training qualification. Host `/proc` and its subtrees remain unavailable as
profile mounts; the sandbox retains its private PID view. Do not call a failed
environment check a model failure.

## What is inside the boundary

The command after `--` and its descendants run inside the sandbox. A caller
script launched this way is isolated; an outer coding agent still using host
execution tools is outside it. To isolate an entire agent session, its actual
agent process and command-execution tools must run through this entry as well,
with their executable/dependencies declared. `AGENTS.md` instructions alone do
not enforce filesystem restrictions.

The CLI preserves ordinary child exit codes and cleans up on timeout, Ctrl-C or
SIGTERM. PID namespaces also terminate detached descendants when their namespace
exits. A Python caller using `runner.run()` owns its own signal handling; exceptions
unwind the runner's cleanup. This facility is not a hostile-host boundary,
credential vault, memory quota, GPU scheduler or hidden-test evaluator.

## If the check fails

- `install bubblewrap`: install your operating system's bubblewrap package.
- Namespace permission error: use a Linux host/container that permits the
  required user, mount and PID namespaces. Ask its administrator to configure
  them; the tool does not change host permissions.
- Missing declared path or environment name: fix that external configuration or
  export the named variable in the same shell, then rerun `check`.
- Python/import error inside the sandbox: confirm the exact checkout's frozen
  environment and declare additional external dependencies. Do not borrow a
  different checkout's virtualenv or add a source tree through `PYTHONPATH`.

Real namespace regression checks, without API calls or training:

```bash
SIDERIUS_TEST_WORKSPACE_SANDBOX=1 .venv/bin/python -m pytest -q \
    tests/unit/tools/workspace_sandbox \
    tests/integration/tools/test_workspace_sandbox.py
```
