# Custom adaptor contract (manifest, supervised runner, admission)

**Owner**: `workflows/custom_adaptors/` (schema, runner, self-test, admission);
CLI `tools/adaptors/cli.py`; authority sets `workflows/definition/catalog.py`
(`CUSTOM_EMITTABLE`, `PROTECTED_FIELDS`).
**Status**: admission and inspection only. Workflow declarations cannot yet
reference a custom adaptor; preparation pinning, run-lock identity, workflow
execution, execution evidence and replay are later work (design B6-6a/b).

## Purpose

A user (or their coding agent) writes a small Python adaptor in the **external
project**, never in framework source. The framework fixes the basic rules:
typed inputs and outputs validated against native models, no authority over
scores, Health, validity, identity or storage, execution in a supervised child,
admission by content identity, and a static output count.

## Manifest: `siderius.adaptor-manifest/v1`

`AdaptorManifest` (`manifest.py`), Pydantic, `extra="forbid"`, frozen. Loaded
by `load_adaptor(path)`, which validates and then captures `members` once through
`core.local_code.capture_package` (no member is executed).

| field | type / rule |
|---|---|
| `schema_version` | `"siderius.adaptor-manifest/v1"` |
| `id` | `^[a-z][a-z0-9_.-]{2,99}$` |
| `version` | author label, 1..64 chars; readable, not identity |
| `role` | `combine` \| `select` \| `distribute` (the design's all-in-one `adaptor` role is not admitted in v1) |
| `inputs[]` | `name` (`^[a-z][a-z0-9_]{0,63}$`, unique), `contract` ∈ `READABLE_CONTRACT_TYPES`, `cardinality` `one`\|`many`, `min_items` ≥ 0 (default 1), `max_items` > 0 or absent; `one` means exactly 1 |
| `output` | `contract`, `count` 1..64 (default 1) |
| `entry` | `"<member>.py:<function>"`; member must be listed in `members` |
| `members` | relative Python files, `CodePackageDeclaration` rules (normalized, no collisions) |
| `parameters_model` | optional `"<member>.py:<PydanticModel>"`; without it, parameters must be empty |
| `deterministic` | must be `true` (operator decision B6-D7: deterministic adaptors only in v1) |
| `llm` | must be absent/`null` in v1 |
| `network` | `"none"` |
| `limits` | `timeout_seconds` (0, 3600], `max_input_bytes` (0, 256 MiB], `max_output_bytes` (0, 64 MiB] |
| `fixtures[]` | ≥ 1; `input`, `expected` paths relative to the manifest directory; may not escape it |

Role rules (validated at load, diagnostic `manifest_invalid`):

- `combine`: `output.contract` ∈ `CUSTOM_EMITTABLE` (B6-D3 = B):
  `optional.expert-context`, `optional.expert-advice`, `optional.text`,
  `proposal.output`, `literature.output`. `validation.output`, `tuning.output`,
  `interpretation.output`, every capability input, storage, constraint context,
  parameter rules and task references are refused: metric/score, Health,
  validity, identity and storage authority stay with the framework.
- `select` / `distribute`: exactly one input port; `output.contract` equals its
  contract. They return indices; the framework materialises values from its own
  copies, so they cannot alter a value.

`AdaptorManifest.digest` is the SHA-256 of the canonical JSON dump of the
validated manifest (whitespace and key order do not matter).

## Identity

`identity_sha256` = `PackageIdentity.digest` of the captured members
(`core.local_code`): every listed member's relative name and content hash, no
absolute paths. Editing any member, including a helper the entry imports,
changes identity. The manifest digest is recorded beside it, not inside it.

## Function interface

```python
def adapt(inputs: AdaptorInputs, params: P | None, ctx: AdaptorContext) -> ...
```

Types in `interface.py`. `inputs` is a read-only mapping port name →
`tuple[CustomInputItem, ...]`; `CustomInputItem.index` is the declared position
and `.value` the validated native model (or `str` for `optional.text`, a list
of `ExpertContextItem` for `optional.expert-context`). `params` is the
validated `parameters_model` instance or `None`. `AdaptorContext` exposes
`adaptor_id`, `llm=None` and `log(str)` (child log). The framework passes no
workspace or run path, clock or seed; the process environment is the
allowlist under "Supervised execution", not the caller's environment.

Return values by role (JSON-compatible; Pydantic models are serialized):

| role | return | parent validation (`runner.validate_output`) |
|---|---|---|
| `combine` | sequence of values of `output.contract` | native validation; 1 ≤ len ≤ `output.count`; protected fields (below) |
| `select` | `list[int]` | strict ints, unique, in range of the port, len ≤ `output.count` |
| `distribute` | `list[list[int]]` | exactly `output.count` groups, strict ints, in range, disjoint (an empty group is allowed) |

## Protected fields (`catalog.PROTECTED_FIELDS`)

Applied by `protected.stamp_protected` to the JSON dump of validated combine
values. Paths are dotted; `[]` addresses every list element. One path may carry
several rules.

| rule | meaning |
|---|---|
| `unset` | author leaves it absent/`None`/`""`/`[]`/`{}`; anything else is refused |
| `stamp-source` | as `unset`, then the framework writes `adaptor:<id>@<identity[:12]>` |
| `forbid-value` | the named value is refused |

| contract | protected fields |
|---|---|
| `optional.expert-context` | `[].source` stamp; `[].kind` ≠ `human`, ≠ `findings` (chain-mode union only) |
| `proposal.output` | `candidate_id`, `observed_prediction_reference`, `preflight_estimated_minutes`, `preflight_factor` unset; `proposed_discoveries[]` vocabulary rules |
| `literature.output` | `agent_card.agent_name` and `run_name` stamp; `agent_card.trust_level` ≠ `hard_limit` (constraint authority); `findings[]` as expert-context items; `new_vocab_candidates[]` vocabulary rules; `search_decisions` unset |
| `optional.text`, `optional.expert-advice` | none (no field can carry provenance; see B6-6 acceptance below) |

Vocabulary rules: `origin` stamp, `proposed_by_run` and `seen_in_runs` unset,
`tier` ≠ `canonical`. A test checks that every path names a real native field.

Author-set protected values are refused (`custom_invalid_output`), never
silently replaced. `CustomOutput.author` is the canonical author form;
`CustomOutput.stamped` is re-validated after stamping. `candidate_id` stays
unset here; minting a framework candidate identity for a custom
`proposal.output` belongs to workflow execution (B6-6), and such a proposal must
still pass implementation and validation before training.

## Supervised execution (`runner.py`, `process.py`, `child.py`)

1. `admit_inputs`: exact declared port set, item counts within bounds, every
   value validated against its contract (`custom_invalid_input`).
2. Canonical input size ≤ `max_input_bytes`; parameters require
   `parameters_model`. The control directory must not exist yet (no stale
   markers or outputs).
3. `core.local_code.transport.publish_transport` writes the immutable carrier
   under `<control_dir>/task_code/`; `invocation.json` (`CustomInvocation`)
   carries absolute locators, JSON inputs, parameters and `max_output_bytes`.
4. `process.launch` runs `python -P -s -m workflows.custom_adaptors.child`
   under `supervise_subprocess` in its own process group. `-P` keeps the
   working directory off `sys.path` (a module in the caller's directory cannot
   shadow framework imports before pin verification); `-s` drops user site.
   Environment allowlist (`process.child_env`): `PATH`, `VIRTUAL_ENV`, `LANG`,
   `LANGUAGE`, `LD_LIBRARY_PATH`, `LC_*`, `PYTHONHASHSEED` (the operator's value,
   else `core.subprocess_env.CHILD_HASH_SEED` = `0`), `PYTHONNOUSERSITE=1`, and private `HOME` and `TMPDIR`
   under the control directory. No provider credentials, plugin directories or
   inherited `SIDERIUS_TASK_CODE_*` transport reach the child; it needs none.
   The supervisor's watchdog notice is redirected to stderr.
5. The child routes its fd 1 and 2 through a pipe into `child.log`, keeping the
   first `MAX_LOG_BYTES` (64 KiB) and discarding the rest, and closes its only
   references to the parent's pipes, so the supervisor's in-memory capture
   stays small. It calls `bootstrap_code_package(carrier,
   digest)`, which verifies every member pin before any adaptor code runs, and
   validates inputs. It then creates the `entered` marker with `O_EXCL`
   immediately before the first member import. After that point adaptor code
   runs: member module bodies on import, the parameters model's validation, and
   the function call. Output is written only if it fits `max_output_bytes`.
6. Deadline (`process.EnteredDeadline`): before `entered`, a bounded startup
   allowance (`STARTUP_ALLOWANCE_SECONDS` = 120 s; interpreter and framework
   import, about 2 s with `torch`; no adaptor code runs in it). Once `entered`
   is observed, the author's `timeout_seconds` covers member module bodies,
   parameters validation and the call. Observation granularity is the 0.05 s poll.
7. The parent checks `max_output_bytes` again, parses JSON and applies the
   role rules.

Failure reporting: on any failure the child writes `failure.json`
(`ChildFailure`: `stage` ∈ `identity`, `input`, `parameters`, `adaptor`,
`output`) and exits 1. That file is a hint: adaptor code can write or delete any
control file. The parent classifies from its own observations. It reports
`custom_identity_mismatch` only for an `identity` hint when it never observed
`entered` (during polling or at exit) **and** an independent re-capture of the
declared members differs from the loaded pins. Exit codes carry no meaning
beyond zero/non-zero. Inputs are validated by the parent before launch, so a
child `input` hint is an internal inconsistency and reported as
`custom_exception`. Known limit: adaptor code that edits its own member files on
disk and then forges an `identity` hint is reported as an identity mismatch,
which is true of the bytes on disk at that point.

| reason | cause |
|---|---|
| `custom_timeout` | startup allowance or author timeout exceeded; the process group is terminated; the message says which phase |
| `custom_exception` | adaptor code raised or exited (including `SystemExit`/`os._exit`), a member import failed, parameters were refused by the author's model (message starts `parameters:`), or the child exited non-zero without a confirmed identity mismatch |
| `custom_identity_mismatch` | the child refused the pins before `entered`, and the parent's re-capture confirms the member bytes changed |
| `custom_invalid_output` | output not JSON-compatible or over `max_output_bytes` (child or parent), or contract, protected-field, index or count violation |
| `custom_invalid_input` | ports, counts, contracts, size or parameters-without-model refused by the parent before launch |

Parameters are validated in the child, not in the parent: the parameters model
is user code, and the parent never executes user code.

This is not a network or filesystem sandbox. `network: "none"` is the author's
declaration and is not enforced in v1 (`inspect` prints
`"none (declared, not enforced in v1)"`); `self-test` runs the adaptor as the
operator's user, so it can reach the network and read or write files the
operator can. Decision (c), recorded 2026-10-27: a shared isolation owner is
extracted from `agent/data_analysis/analysis_code_sandbox.py` (bubblewrap +
`unshare --net`) in its own PR before B6-6b, and the adaptor child moves into
it. That sandbox's current `execute` contract is specific to one generated
program file, its runner and `SkillPayload`, and it does not mount the editable
framework source this child imports, so it is not reused as-is. Custom adaptors
cannot run in workflows until B6-6. See `core/local_code/README.md` for the
reproducibility (not security) scope.

## Self-test (`self_test.py`)

Each fixture `input` file is `FixtureInput` `{"inputs": {port: [values]},
"parameters": {...}}`; `expected` holds the author-form return value (protected
fields unset; stamped labels contain the identity and would change with every
edit). Every fixture runs **twice** in separate children; the canonical raw
outputs must be byte-equal (`custom_nondeterministic`), then the output and the
expected value pass the same role validation and must be equal
(`fixture_mismatch`; an invalid expected file is `fixture_invalid`).
Determinism is established only under the child's fixed `PYTHONHASHSEED` and
this host; it is evidence, not a proof across hosts or library versions.
`SelfTestReport` records identity, manifest digest and per-fixture input,
expected and output SHA-256.

## Admission (`admission.py`, operator decision B6-D11)

`<project>/.siderius/adaptors/<id>/<identity_sha256>.admission.json`,
`AdaptorAdmissionRecord` (`siderius.adaptor-admission/v1`): id, version, role,
`deterministic`, manifest path relative to the project, manifest digest,
identity and member pins, self-test fixture digests, and `framework_revision`
(`resolve_git_sha`, `"unknown"` outside a git checkout; dirty state is not
recorded because no neutral provenance owner exposes it). No timestamp.

The location is checked before any fixture runs: a project inside the
framework checkout or installed packages, or a manifest outside the project,
is refused (`admission_location`). Records are published through
`core.durable_io`: `publish_bytes_write_once` by default (identical bytes are a
no-op; different bytes for the same identity are refused,
`admission_conflict`), `publish_bytes_atomically` with `--replace`. A consumer
(B6-6) must match **both** `identity_sha256` and `manifest_sha256`: the same
code under an edited manifest has the same identity but a different record.

## CLI

```text
python -m tools.adaptors inspect   --manifest PATH                     # no code execution
python -m tools.adaptors self-test --manifest PATH
python -m tools.adaptors admit     --manifest PATH --project DIR [--replace]
```

Run it as `python -P -m tools.adaptors ...`, or from a directory other than the
adaptor's: without `-P`, Python puts the working directory first on `sys.path`,
so a module there (for example the adaptor's own `pydantic.py`) could shadow the
CLI's own imports. The child always runs with `-P`.

Success prints exactly one JSON document on stdout, exit 0. Any refusal exits 2
with `[<reason>] <message>` on stderr and nothing on stdout; `OSError` maps to
`[io_error]` and `LocalCodeError` to `[package_unreadable]`. `self-test` and
`admit` use a temporary control directory that is removed on exit.

## B6-6 acceptance items carried from this PR

- Match both `identity_sha256` and `manifest_sha256` against the admission record.
- Carry the adaptor provenance label (`adaptor:<id>@<identity[:12]>`) for
  `optional.text` and `optional.expert-advice` outputs in the adaptor record and
  wherever the value is rendered, since neither contract has a field for it.
- Mint `ProposalOutput.candidate_id` for custom proposals; apply the run's
  sandbox policy and resource-ceiling owner to the child.

## Validation evidence

`tests/unit/workflows/test_custom_adaptor_manifest.py` (catalog paths vs native
schemas, contract types vs catalog strings, helper-edit identity, manifest
refusals, protected-field stamping/refusal through `validate_output`, literature
authority fields, write-once admission, index/partition rules) and
`tests/unit/tools/test_adaptors_cli.py` (real children: admission location,
nondeterminism with empty stdout, startup-independent timeout with a fast
control, environment allowlist and cwd shadowing, identity-mismatch forgery
from a module body, from the call and after unlinking `entered`, parameter
refusal, post-capture edit). Synthetic plugin:
`tests/fixtures/custom_adaptors/sibling_digest/`.

## Limitations

- No workflow reference, preparation pin, run lock, `CustomExecutionEvidence`
  or replay yet (B6-6a/b); no GUI (B6-7); no LLM adaptors (B6-8).
- No network or filesystem isolation (see above).
- The log cap: the child replaces fd 1 and 2 with its capped pipe and keeps no
  descriptor to the parent's stdout/stderr pipes, so adaptor code cannot write
  past the cap into the supervisor's capture (regression: writes to every fd
  3–64). It does not bound files on disk: adaptor code can still write to the
  open `child.log` descriptor or any file the operator can write. The parent
  reads only the log's tail.
- The child imports native schema modules, which import `torch`; each child
  start costs about 1.5–2 s on the development host.
