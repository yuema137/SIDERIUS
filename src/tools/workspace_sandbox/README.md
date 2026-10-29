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

## Check that bubblewrap works

The browser console runs task code through this sandbox, so check it once on
each machine. Run:

```bash
bwrap --unshare-all --ro-bind / / true
```

Success: the command prints nothing and exits with status 0 (`echo $?` shows
`0`). It creates the same user, mount, PID and network namespaces the sandbox
uses, with the host filesystem read-only. An error such as `No permissions to
creating new namespace` or `bwrap: command not found` means the sandbox cannot
start; see [If the check fails](#if-the-check-fails).

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
| `devices` | Explicit character-device paths under `/dev`. No GPU is exposed by default. Listing a `/dev/nvidia<N>` node also mounts read-only `/sys` and the host's NVIDIA control nodes ([GPU tasks](#gpu-tasks)). This is access, not a GPU allocation or VRAM budget. |
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
mounts before training. The lightweight `check` does not establish CUDA readiness;
see [GPU tasks](#gpu-tasks). Host `/proc` and its subtrees remain unavailable as
profile mounts; the sandbox retains its private PID view. Do not call a failed
environment check a model failure.

### GPU tasks

A `/dev/nvidia<N>` device node alone does not let CUDA start: without host
`/sys`, PyTorch reports `cudaGetDeviceCount` error 304. So when `devices` lists
at least one `/dev/nvidia<N>` node, the sandbox adds two things itself
([`gpu.py`](gpu.py)); you do not configure them:

- **All of host `/sys`, read-only.** The process can read the host's hardware
  and kernel metadata: PCI devices, CPU and NUMA topology, loaded modules and
  their parameters, block and network device names, cgroup and power
  information. It cannot change any of it. Docker mounts sysfs read-only in
  containers and Apptainer binds host `/sys`; Flatpak binds selected `/sys`
  subdirectories. On the checked RTX 5090 host a smaller set
  (the GPU's PCI directory plus `/sys/module/nvidia*`) was also enough. The
  sandbox mounts all of `/sys` so that other drivers and library versions that
  read more metadata keep working.
- **The NVIDIA control nodes present on this host**: `/dev/nvidiactl`,
  `/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools`, `/dev/nvidia-modeset` and
  `/dev/nvidia-caps/*` (MIG). Nodes you already listed are not passed twice.

A profile without a `/dev/nvidia<N>` node gets neither, so its sandbox command is
unchanged. A profile that already lists `/sys` (or a `/sys` subdirectory) in
`read_only` keeps working; `/sys` is mounted once. A declared
`/dev/nvidia<N>` that this machine does not have is refused before launch with
`GPU device /dev/nvidia<N> is not present on this machine`.

The sandbox applies no seccomp filter. The NVIDIA driver uses `memfd_create`
during CUDA initialization, so a seccomp profile added later must allow it.

To confirm a console task's GPU starts inside this sandbox, run
`python -m tools.candidate_console check --gpu --config <console.json>` (see the
[console README](../candidate_console/README.md)). To find which host paths a
new driver needs, a host qualification can run the same CUDA probe through
`build_command` with progressively larger read-only sets. Do this by hand on the
GPU machine; it is not a CI test.

### GPU headroom and current execution limits

The private PID namespace can hide other GPU processes while the device still
reports their memory usage. The launcher therefore supplies the reserved
`SIDERIUS_GPU_PROCESS_VISIBILITY=namespace_limited` declaration to its children.
Do not forward or override this variable in `environment_names`.

For native GPU phase admission, SIDERIUS counts known external memory **plus
unattributed memory** as a conservative upper bound on outside occupancy. The
new worker's authoritative measured requirement plus **all current device
occupancy**, including retained parent-process memory, must fit both the
configured aggregate ceiling and the device capacity. For example, if the
existing parent process tree holds 516 MiB and device usage is 2779 MiB, the outside bound is
2263 MiB even when the process list reports no outsiders. Admission adds the
new worker requirement to the full 2779 MiB: the existing parent memory does
not disappear when that worker starts. Those residual bytes remain
unattributed in the saved evidence; the calculation does not invent owners.

When the visibility declaration is valid and a current typed GPU snapshot has
available telemetry, a device UUID, no sampling error, and complete, coherent
accounting, missing authoritative phase requirements use the ordinary phase
policy. Trial mode proceeds without a safety claim. Formal mode
refuses with `policy_unavailable`; `observe_only` records `would_refuse` and
proceeds, while `enforce` stops. A measured requirement that does not fit returns
`insufficient_headroom` and stops in every enforcement mode, including
`observe_only`. This measured-demand rule retains precedence over the phase
posture. Saved missing-requirement decisions retain `process_visibility` and
`effective_execution_conditions`; proceeding does not certify a global process view.

Missing or inconsistent accounting, invalid visibility declarations, missing GPU
identity, ceiling-resolution failures, and admission policy exceptions still stop with
`environment_headroom_unproven`, including in `observe_only`. Only explicit CPU
availability permits the missing-GPU-identity path to proceed. Repair the
execution evidence before retrying; this refusal is not advice to shrink the
model or batch. Unattributed bytes never establish clean process visibility.
There is no staleness guard beyond sampling immediately before phase admission.

To obtain separate training and inference measurements and enable runtime
protection, select the
[measured GPU execution policy](../../core/runtime_control/README.md#protecting-a-native-gpu-attempt).
The native tuner accepts this policy in its typed input; the standard
single-iteration CLI accepts `--gpu_execution_policy_json`. Choose its measurement
budget and other limits for your task and hardware; the sandbox profile does not
choose them for you.

Training measurements cannot substitute for inference measurements. The selected
policy uses bounded preparation to obtain evidence before the corresponding
phase; it does not prove an upper bound for unmeasured data or guarantee that
memory can never exceed a sampled limit. See the
[execution contract](../../core/runtime_control/native-gpu-execution.md) for the
supported native scopes and checkpoint path. Actual GPU onboarding qualification
is separate from configuration or a successful device query.
A direct native CPU caller inside the selected sandbox must pass the validated
`HardwareContext.device_available=False` fact as `device_available` when
constructing its executor. The tuner transports this fact automatically. Missing
GPU identity plus unknown, malformed, or true availability stops before launch;
the executor never guesses a device or repeats hardware discovery. Pseudo
executors that launch no process retain their override behavior.
Own-process memory measurements and conservative OOM attribution remain usable;
hidden external processes cannot establish an idle-device claim.

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
