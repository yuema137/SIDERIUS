# Explicit environment preview contract

## Scope and entry points

`environment_settings.inspect_environment(EnvironmentPreviewRequest)` observes a
fresh standard single-iteration launch after a saved successful task-settings
check. `python -m tools.setup_review.inspect_environment` projects its CLI flags
into the same typed request. This is an opt-in observation API, not a runner,
readiness gate, immutable provenance mechanism or authentication test.

The request inherits `SnapshotOperation`: absolute `report`, exact
`expected_sha256`, new canonical absolute `output`, positive `input_max_bytes`.
`check_environment` defaults to false. The CLI supplies an explicit default of
1048576 bytes; the callable requires the bound to be declared. Input/output paths
must satisfy the existing saved-report reader/output-claim contracts.

## Owners and execution order

1. `snapshot_io.read_snapshot` reads one nonblocking, no-follow regular-file
   descriptor, enforces the requested byte bound, compares descriptor metadata
   and hashes the exact read bytes. It validates the inert consumed projection,
   not historical sandbox paths. Only a successful `SavedTaskCheckSnapshot` with
   `task_settings` is accepted here.
2. `inspection.inspect_parsed_declaration` reparses the saved request in its actual
   working directory. No `chdir` or reused Namespace occurs. Every declaration
   field except operation-specific output/credential observations must match.
   The command retains the actual `sys.executable` spelling. A new environment
   with a different interpreter must regenerate its check.
3. `composition_transport.manifest_digest` verifies selected manifest bytes.
   The existing `resolve_dataset_dir` validates directory existence; its return
   value, including relative spelling, is preserved in the launch projection.
   A separate absolute display path is recorded. No dataset contents are read.
4. `core.hardware_context.discover` supplies one current typed property
   observation. `get_or_create` is not called. Failures propagate; no synthetic
   CPU success replaces a failed observation.
5. `workflows.runtime_settings.resolve_watchdog_policy` receives the observed
   `device_name`, preserving profile precedence, required bindings, provenance
   and phase-deadline checks. Its optional keyword leaves ordinary omitted calls
   and the existing per-Namespace cache behavior unchanged. No second discovery
   or local-server profile fallback is introduced.
6. `build_standard_launch_config` projects the fresh normalized arguments after
   data/watchdog resolution, with empty restored-source paths and no fixed plan,
   as required by the supported scope. `validate_launch_trial_overrides` checks
   the actual transit object. All transit fields are serialized; only the two
   existing `FORMAL_DELTA_FIELDS` use lossless nonfinite strings. Other numeric
   serialization retains existing finite-value validation.
7. `claim_snapshot_output` claims a new directory. Existing write-once durable
   publication saves `report.json` followed by escaped `index.html`. No rollback
   deletes concurrent/user content. Partial output is possible after interruption.

`snapshot_io` owns the prior semantic-review reader/output helpers; old internal
aliases remain in `semantic_review` for unchanged call behavior. No alternate
snapshot parser, default table, task composer or scheduling authority is added.

## Result and interpretation

`EnvironmentPreviewReport` has schema `siderius.setup-environment/v1` and outcome
`settings_observed`. It records source bytes/digest/bound, the inert saved task
projection, the freshly parsed declaration, typed hardware/watchdog observations,
absolute data-directory display path, complete standard launch transit fields and
current limitations. Historical task/declared limitations remain historical;
they are not substituted for the current observation summary.

Task-dependent scope, Health configuration and model-route enablement remain saved
facts. Physical device properties and watchdog provenance are current facts.
Missing identity or collection errors remain explicit. An installed backend,
available device, implemented accounting adapter and qualified execution are
separate claims; this slice does not establish the latter two. In particular,
there is no vendor ban or implicit NVIDIA/local-machine default in this API.

The exact ordinary launch command is displayed with `cd ... && command` so a failed
working-directory change cannot run it elsewhere. The command does not consume
this report. Agent-chosen training parameters, dynamic node execution, complete
source freshness, data compatibility, Health execution, authentication, budget
enforcement and successful training remain unverified. No LLM review/skip is
created; prior semantic receipts bind only their earlier source bytes. The current
semantic reviewer does not accept the environment-report schema.

## Failure and security boundary

Digest/size/type/manifest/declaration mismatch, old/nonempty run workspace,
missing data directory, output collision, required-profile mismatch, invalid
launch schedule or hardware observation failure refuse without launching.
Early failures produce no new report. The CLI omits arbitrary exception values
from generic diagnostics; underlying standard required-profile refusals retain
that owner's actionable diagnostics. No provider credentials are inspected unless
name-presence checking was requested; values and dotenv are never collected.
User-authored advice/configuration text can still contain secrets. Escaping
prevents HTML execution, not disclosure of sensitive text supplied by the user.

Comparing selected inputs is not a complete dependency hash or a protection
against hostile writers. Source/plugin changes and time-of-check/time-of-use
races remain outside this preview's authority. Reviewed-launch binding is a
separate consuming-owner change; ordinary runner defaults are unchanged.
