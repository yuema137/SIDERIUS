# Candidate-chain preview contract

## Scope, interfaces and ownership

`preview_workflow(WorkflowPreviewRequest) -> WorkflowPreview` is a read-only
inspection API. Python callers construct the request; JSON callers use
`WorkflowPreviewRequest.model_validate_json`. The function revalidates a JSON
serialization of the entire request to reject unchecked model copies, including
invalid nested declarations. Output supports `model_dump_json`. No CLI, server,
executor, task validator, advice binding or digest-pinning API is introduced.

The strict request contains `document: WorkflowDocument`, an explicit absolute
`project_root: str`, and optional `llm_config_file: str | None`. Definition v1
retains its existing three-stage form and additionally accepts the four-stage
[native training shape](../candidate_worker/candidate-worker-contract.md#fresh-native-training-schema-version-1).
`preview.py` requires exactly one `proposal`, `implementation`, `validation`,
and optionally one `tuning`. Proposal uses an `ExternalRequest`;
implementation uses `proposal-to-implementation` with that proposal's result;
validation uses `implementation-to-validation` with that implementation's result.
Native declaration validation still owns binding types and required arguments.
Other structurally valid graphs raise `ValueError("Unsupported preview: ...")`;
this does not reclassify them as invalid declarations. Optional protocol bindings
remain legal and opaque. Node list order and canvas positions do not select routes.

## Locations and observations

`files.py` resolves outer locations against `project_root`, independently of CWD,
and resolves symlinks before comparing paths. Absolute locations remain absolute.
URI schemes and network-path references are refused; only local paths are supported.
The project and data root must be existing directories. Data contents are not read.

The workspace must be absent or empty. It must not overlap data in either
containment direction, overlap the actual framework checkout or installed package
source directories, or contain any selected input file. An absent workspace whose
existing ancestor is a regular file is refused. The task's containing directory
and the project root are not prohibited wholesale: `project/task.yaml` with
`project/workspace` is valid. Installed-package checks protect SIDERIUS packages
under `core.layout.package_root()`, not the whole `site-packages` directory.
An editable checkout is identified by `core.layout.checkout_root()`.

All declared external files (including unused declarations), the task manifest,
and an optional LLM config file must be regular readable files. Each observation
contains its `reference`, canonical `path`, `sha256`, and `size_bytes`. Bytes are
captured once; the LLM config is parsed from the same bytes whose digest is
reported. Manifest and external bytes are never parsed, imported or evaluated.
A missing/unreadable/special file raises a contextual error without fallback.
Nonblocking open plus descriptor type checking avoids blocking on a FIFO.

Observations are not an atomic filesystem snapshot. Files, directories, aliases
and environment can change after observation. No dependency closure, data
identity, task fingerprint, run lock or time-of-use safety is established.
These checks do not create, reserve, clean or make a workspace safe for execution.

## Configuration and constructor routes

Omitting `llm_config_file` selects `WorkflowLLMConfig.default()`. An explicit file is JSON,
validated by the native `WorkflowLLMConfig`; omitted blocks retain native
constructor fallback behavior. `config.py` adds bounded unknown-key and duplicate
name/alias checks at the top level, active `implement`/`validate` leaf models,
`propose`, and its three stage leaves. Accepted keys derive from native fields
and aliases. Both `validate` and `validate_model` are accepted separately;
supplying both is refused. Native models own shapes, values and retry intent.
Known inactive role blocks retain native validation; they are not recursively
subjected to the active-role typo policy. No native model's extra-field policy changes.

`tools.setup_review.routes.node_llm_routes` projects one role without projecting
unrelated transports. It reuses `nodes.llm_settings`, `nodes.proposer_routing`
and `agent.llm_settings`. The existing `standard_llm_routes` delegates to that
helper while preserving its output fields, values and order.

`selected_constructor_routes` orders proposal comparison/reasoning/proposing,
implementation main, validation main. Each `LLMRoute.name` is `<node_id>.<stage>`.
Client-sharing references use only that same node instance's namespace; equal
settings in separate nodes do not imply shared clients. Proposer native cache
semantics, missing/explicit retry settings, model defaults and provider rules
are unchanged. All routes are conditional possibilities, not invocation counts,
stage activation, costs or reconciled native request values.

`inactive_roles` lists every native workflow role outside these three roles,
including unconfigured ones. No tuner, literature, interpretation or analysis
transport is projected. Transport resolvers are pure: preview does not read
credentials or SDK environment. `base_url=None` leaves endpoint selection to
later SDK/environment behavior; reported routes do not certify an effective
network destination or provider availability.

## Remaining checks and compatibility

Successful reports use `status="bindings_observed"` and cannot report
`execution_ready=true`. Pending checks explicitly include native payload
validation and reconciliation with selected routes/task/storage; task composition,
plugin/dependency identity; data contents and resource admission; provider and
SDK endpoint availability; lifecycle, persistence and resume. In particular,
protocol-supplied LLM fields and proposal payload storage/task fields may disagree
with this preview. This API does not decide their future execution precedence.

There are no provider clients, protocol calls, task imports, network requests,
training, subprocesses or writes in the inspection path. Pydantic may inspect its
own plugin configuration while building validators; task plugins remain inert.
Existing production launchers, native schemas, prompts, historical profiles and
scientific execution paths do not import this package and are unchanged.

Unit tests own path resolution/separation, observed-byte consistency, bounded
config typo rejection, selected-role reachability, namespace sharing, unsupported
subsets and absence of execution effects. Existing setup-review tests retain
independent native constructor witnesses. Ruff and Pyright own static properties. Gate 1 and Gate 2 are not required: no model-facing or
execution semantics changed. Automatic PR CI owns the final selected suites.

## Example document

Save this as `workflow.json` in the external project shown in the README. The
referenced files must exist, but their native payload validity is a later check.
The optional `llm.json` is a separate file; `{}` deliberately selects partial
configuration semantics rather than the complete first-run defaults.

```json
{
  "definition": {
    "schema_version": 1,
    "task": {"manifest": "task.yaml", "data_root": "data", "workspace": "workspace"},
    "externals": [
      {"id": "request", "contract": "proposal.input", "location": "proposal.json"},
      {"id": "storage", "contract": "storage", "location": "storage.json"}
    ],
    "nodes": [
      {"id": "candidate", "capability": "proposal", "request": {"kind": "external", "binding": "request"}},
      {
        "id": "coder", "capability": "implementation",
        "request": {
          "kind": "protocol", "protocol": "proposal-to-implementation",
          "arguments": [
            {"name": "output", "source": {"kind": "result", "node": "candidate"}},
            {"name": "storage", "source": {"kind": "external", "binding": "storage"}}
          ]
        }
      },
      {
        "id": "checker", "capability": "validation",
        "request": {
          "kind": "protocol", "protocol": "implementation-to-validation",
          "arguments": [
            {"name": "output", "source": {"kind": "result", "node": "coder"}},
            {"name": "storage", "source": {"kind": "external", "binding": "storage"}}
          ]
        }
      }
    ]
  }
}
```

`preview.observe_bindings(request, read_file=...) -> WorkflowBindings` is the
inert observation seam used by preparation reconciliation and its read-only
operation accessor. It observes selected files/routes and resolves project/data/
workspace locations without admitting workspace lifecycle. `preview_workflow`
still requires absent/empty, separated workspace and returns `WorkflowPreview`.
Observation reads now precede that final workspace check; they have no write or
execution effects. Semantic preview fields remain unchanged; JSON field ordering
is not an identity guarantee. An optional file reader lets the operation owner
apply its existing bounded no-follow read policy.

For four-stage declarations, tune routes delegate to the public `node_llm_routes`
role `tune`, preserving planner/reflector sharing and transport from standard
routing. Preview parses only the optional Health-file reference from settings,
observes its canonical project-relative/absolute path under
`training.health_checks_config`, and otherwise leaves full settings validation
to child-side native admission. No native task/plugin schema is imported for
this reference projection. Version-2 preparation may resolve source-declared training into this v1 path.
