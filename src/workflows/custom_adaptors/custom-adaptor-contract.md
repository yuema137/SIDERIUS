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
`adaptor_id`, `llm=None` and `log(str)` (child stderr). There is no path,
workspace, environment, clock or seed; the child runs with
`PYTHONHASHSEED=0` from `core.subprocess_env.subprocess_env`.

Return values by role (JSON-compatible; Pydantic models are serialized):

| role | return | parent validation (`runner.validate_output`) |
|---|---|---|
| `combine` | sequence of values of `output.contract` | native validation; 1 ≤ len ≤ `output.count`; protected fields (below) |
| `select` | `list[int]` | strict ints, unique, in range of the port, len ≤ `output.count` |
| `distribute` | `list[list[int]]` | exactly `output.count` groups, strict ints, in range, disjoint (an empty group is allowed) |

## Protected fields (`catalog.PROTECTED_FIELDS`)

Applied by `protected.stamp_protected` to the JSON dump of validated combine
values. Paths are dotted; `[]` addresses every list element.

| rule | meaning |
|---|---|
| `unset` | author leaves it absent/`None`/`""`/`[]`/`{}`; anything else is refused |
| `stamp-source` | as `unset`, then the framework writes `adaptor:<id>@<identity[:12]>` |
| `forbid-value` | the named value is refused |

Current table: `optional.expert-context` `[].source` (stamp), `[].kind` ≠
`human`; `proposal.output` `candidate_id`, `observed_prediction_reference`,
`preflight_estimated_minutes`, `preflight_factor` unset, and
`proposed_discoveries[]` vocabulary rules; `literature.output`
`agent_card.agent_name` and `findings[].source` (stamp), `findings[].kind` ≠
`human`, `new_vocab_candidates[]` vocabulary rules, `search_decisions` unset.
Vocabulary rules: `origin` stamp, `proposed_by_run` and `seen_in_runs` unset,
`tier` ≠ `canonical`. A test checks that every path names a real native field.

Author-set protected values are refused (`custom_invalid_output`), never
silently replaced. `CustomOutput.author` is the canonical author form;
`CustomOutput.stamped` is re-validated after stamping. `candidate_id` stays
unset here; minting a framework candidate identity for a custom
`proposal.output` belongs to workflow execution (B6-6), and such a proposal must
still pass implementation and validation before training.

## Supervised execution (`runner.py`, `child.py`)

1. `admit_inputs`: exact declared port set, item counts within bounds, every
   value validated against its contract (`custom_invalid_input`).
2. Canonical input size ≤ `max_input_bytes`; parameters require
   `parameters_model`.
3. `core.local_code.transport.publish_transport` writes the immutable carrier
   under `<control_dir>/task_code/`; `invocation.json` (`CustomInvocation`)
   carries absolute locators, JSON inputs and parameters.
4. `supervise_subprocess([python, -m, workflows.custom_adaptors.child, ...])`
   with the manifest timeout as deadline, its own process group, captured
   stdout/stderr. Inherited `SIDERIUS_TASK_CODE_*` transport is removed from the
   child environment; the child receives only its explicit carrier.
5. The child calls `bootstrap_code_package(carrier, digest)`, which verifies
   every member pin before any adaptor code runs, imports the entry and
   parameters model from captured bytes, calls the function once and writes
   `output.json`.
6. The parent checks `max_output_bytes`, parses JSON and applies the role rules.

Failure reasons (`errors.CustomAdaptorReason`), never retried, no fallback:

| reason | cause |
|---|---|
| `custom_timeout` | deadline exceeded; the process group is terminated |
| `custom_exception` | adaptor code raised (including `SystemExit`): child exit 1 |
| `custom_identity_mismatch` | member bytes differ from the captured pins: child exit 78 |
| `custom_invalid_output` | oversized/unreadable output, contract, protected-field, index or count violation |
| `custom_invalid_input` | ports, counts, contracts, size or parameters refused before launch |

This is reproducibility machinery, not a security sandbox
(`core/local_code/README.md`). The run's sandbox policy and resource-ceiling
cap apply when workflow execution lands (B6-6).

## Self-test (`self_test.py`)

Each fixture `input` file is `FixtureInput` `{"inputs": {port: [values]},
"parameters": {...}}`; `expected` holds the author-form return value (protected
fields unset; stamped labels contain the identity and would change with every
edit). Every fixture runs **twice** in separate children; the canonical raw
outputs must be byte-equal (`custom_nondeterministic`), then the output and the
expected value pass the same role validation and must be equal
(`fixture_mismatch`; an invalid expected file is `fixture_invalid`).
`SelfTestReport` records identity, manifest digest and per-fixture input,
expected and output SHA-256.

## Admission (`admission.py`, operator decision B6-D11)

`<project>/.siderius/adaptors/<id>/<identity_sha256>.admission.json`,
`AdaptorAdmissionRecord` (`siderius.adaptor-admission/v1`): id, version, role,
`deterministic`, manifest path relative to the project, manifest digest,
identity and member pins, self-test fixture digests, and `framework_revision`
(`resolve_git_sha`, `"unknown"` outside a git checkout). No timestamp, so
re-admitting unchanged inputs produces identical bytes. The location is checked
before any fixture runs: a project inside the framework checkout or installed
packages, or a manifest outside the project, is refused (`admission_location`).
Re-admitting the same identity atomically replaces the record.

## CLI

```text
python -m tools.adaptors inspect   --manifest PATH                # no code execution
python -m tools.adaptors self-test --manifest PATH
python -m tools.adaptors admit     --manifest PATH --project DIR
```

One JSON document on stdout; exit 0, or 2 with `[<reason>] <message>` on stderr.
`self-test` and `admit` use a temporary control directory that is removed on exit.

## Validation evidence

`tests/unit/workflows/test_custom_adaptor_manifest.py` (catalog paths vs native
schemas, contract types vs catalog strings, helper-edit identity, manifest
refusals, protected-field stamping/refusal, index/partition rules) and
`tests/unit/tools/test_adaptors_cli.py` (real children: admission location,
nondeterminism, timeout, post-capture edit). Synthetic plugin:
`tests/fixtures/custom_adaptors/sibling_digest/`.

## Limitations

- No workflow reference, preparation pin, run lock, `CustomExecutionEvidence`
  or replay yet (B6-6a/b); no GUI (B6-7); no LLM adaptors (B6-8).
- The child imports native schema modules, which import `torch`; each child
  start costs about 1.5 s on the development host.
