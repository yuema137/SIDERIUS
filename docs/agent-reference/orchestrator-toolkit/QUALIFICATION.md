# Discovery and native-use qualification

Date: 2026-09-18. Runtime: `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`.
This extends the earlier [single-proposer witness](VERIFICATION.md); that
historical record retains its original runtime and results.

## What was tested

Real Codex CLI 0.154.0, `gpt-5.6-sol`, medium reasoning, fresh isolated workspace
per case, normal sandbox with automatic approval review, and an external
480-second watchdog per session. Native provider calls used the same model and
effort with explicit per-case invocation ceilings. Only synthetic Quickstart
assets were used; no scientific campaign, remote machine or GPU was involved.
Credentials were injected with a name-only presence check and were not copied
into inputs or evidence.

Each kickoff requested a task without naming the skill. The actual ancestor
AGENTS.md and installed `.agents/skills/` payload provided discovery. The catalog
case intentionally requested broad coverage; operation cases needed only their
relevant references. Some tasks requested native artifacts explicitly; the
separate neutral candidate-check case did not require a native output format.
The run declaration still disclosed enabled modules and call ceilings. This is
not a blind preference comparison against an agent unaware of SIDERIUS.

External records include initial file hashes, exact prompt and arguments,
stdout JSONL command/output events, final text, terminal receipt and independent
artifact validation. Read commands count as evidence only with their returned
contents; index loading alone does not establish reading child pages. Native
API calls, persisted schema-valid results and provider records provide stronger
evidence than an agent's claim that it used the toolkit.

## Observed cases

| Case | Observation | Limits or failure retained |
| --- | --- | --- |
| Complete catalog | Read all seven agent guides and schema inventories, six CLI inventories, invocation, handoffs and shared effects; produced a source-cited map with correct constructor/input routing, disabled/unbound analysis, unsupported database protocols and API-versus-CLI distinctions | Repeated reads and source searches were costly; this is not proof of exhaustive understanding or efficient execution |
| Nested-cwd validator | Followed the index to validator/schema/invocation references; used native `MLCodeValidatorAgent.run`, then caller-side CSV formatting; result passed, 114 parameters, supplied test passed | First lookup assumed cwd; recovered ancestor paths. First native call failed DNS; an approval rejection was resolved by proving the payload was shipped synthetic source, then the second call succeeded |
| Persisted proposal recovery | Validated saved `ProposalOutput`, rejected stale database-handoff advice, used native `local_full_spec`, preserved candidate identity and empty baseline; explained isolated paths or serial ownership for colliding jobs | Correctly reported schema validity as insufficient for implementation. No provider call or actual concurrent execution |
| One-attempt implementation | Read implementation/validation contracts and made the allowed native implementer call | DNS failed; respected the one-call ceiling, did not handwrite a replacement or claim validation |
| Discovery correction / disabled analysis | Found the ancestor package, distinguished disabled/unbound Data Analysis from an available validator missing its candidate, and resolved installed source | A recommended `find_spec` lookup failed on a node compatibility alias; agent recovered with class inspection. It also wrote a scratch script outside the declared workspace: an instruction-following defect, despite unchanged input hashes |
| Implementation with retry | Native implementer generated plugin, tests and description; native implementation-to-validation projection preserved identity; validator passed, 58 parameters, three generated tests passed | One DNS failure then one successful implementation invocation and one validation invocation. Caller glue initially mislabeled `SystemExit(0)` as failure; agent corrected it without repeating native work, reconstructed invocation history, and the external transcript retains the original failure |
| Discovery retest | Correctly reported disabled/unbound analysis and missing validator prerequisites; produced report inside the workspace without provider calls or scratch files outside it | Initial cwd lookup still failed and recovered. It resolved source paths directly; this does not prove every new documentation sentence was read |
| Neutral candidate check | With no required native output format, read the capability/selection/schema pages, chose the native validator, and formatted its successful 114-parameter result as report/CSV | First call failed DNS, second succeeded through the authorized route. No handwritten replacement validator |

Native outputs for the standalone validator, implementation and subsequent
validator were independently revalidated with installed Pydantic classes.
Candidate identity and the implementation-to-validation model I/O contract were
compared across artifacts. The recovery projection retained the original empty
baseline instead of guessing missing scientific values.

## Documentation changes supported by this evidence

- State native-agent preference at both entry and skill level, with a linked
  selection guide distinguishing an absent capability, a missing prerequisite,
  a failed attempt and caller-side formatting/invocation code.
- Resolve links relative to their owning document and locate ancestor entry
  files when starting below the package root.
- Distinguish Python import names from checkout paths under `src/`. For source
  inspection use the documented imported class and `inspect.getfile`; node
  compatibility aliases can make dotted `find_spec` fail.
- Explicitly include scratch scripts in the run's declared writable-path limit.

These are documentation changes only. They add no scheduler, executor,
permission enforcement, schema or node behavior. A preference does not select
serial versus parallel work, impose branch counts or authorize extra resources.

## Repeating a meaningful qualification

Use fresh workspaces and pin the runtime, document payload hashes, CLI/model,
run declaration, fixtures and per-case limits. Retain unsuccessful trajectories.
Give the agent an objective and raw artifacts; do not supply the expected API,
missing-field diagnosis or corrective answer in the kickoff. A neutral task can
still disclose actual capability permissions and invocation ceilings.

Inspect the whole trace for reads, calls, retries and writes; separately validate
outputs, identity and unchanged common inputs. Check whether handcrafted code
only assembles typed calls or replaces a supported scientific operation. A
normal exit, schema validity, intact input hashes or self-reported compliance
alone is insufficient. Assess mistakes and recovery separately from discretionary
workflow choices. Repeat only cases affected by a concrete remaining risk.

## Scope of confidence

These are bounded behavioral witnesses, not an adherence guarantee or measured
success rate. Markdown and skills can be skipped or misapplied; the nested-cwd
retry shows that even explicit prose does not eliminate all lookup mistakes.
Filesystem/access/resource enforcement remains the supplied execution
environment's responsibility.

All seven interfaces were inspected, but this phase did not run live literature
retrieval, Data Analysis, tuning/training, GPU execution, concurrent native
writers, automatic context compaction or final scientific submission. A fresh
session recovering a saved proposal is not an automatic-compaction test. The
prior witness covered a native proposer. These limits remain explicit rather
than treating broad documentation coverage as runtime coverage.

The schema/protocol source trees are unchanged from the previous reference
revision. Targeted static checks cover seven callable examples, fourteen native
models / 407 top-level fields, Python snippet syntax, links and skill metadata.
They complement the observed behavior; they do not substitute for it.

## Evidence identities

Raw prompts, document snapshots, transcripts, receipts, outputs and review
utilities are retained under the ignored local work plan's
`artifacts/qualification-20260918/`. They are not research-agent inputs.
Each session exited normally; this includes the intentionally stopped failed
implementation and does **not** mean every task or boundary passed. Original
input/document hashes were unchanged in all eight cases; the separately observed
scratch-path violation is recorded above.

| Case | Elapsed seconds | Completed command events | Transcript SHA256 |
| --- | ---: | ---: | --- |
| catalog | 257.37 | 38 | `69659646c5e27c5f6c9a2c32b770bff7e5eaf16937cbb004a80bc1271cb15d63` |
| discovery | 125.24 | 19 | `9fb90df468977e2d4cefb6c3b3da6ca7939e8f41968732f9983f621e7f299f24` |
| discovery_retest | 72.73 | 8 | `75ee8a7bc9f6a8e26d8a061d31b72b6582ef1c302fddb161bd6f694e23900ec0` |
| implementation | 176.12 | 22 | `0ed1e9af17570bc2b9164219e169d77399c3e2ab12d834e10b54da3036a461c3` |
| implementation_retry | 221.61 | 32 | `abedaffa81644653738491c22df1c64714ec38bc0e9bbafc223bb45851483e1a` |
| native_choice | 196.30 | 24 | `9023545e85b67a6169c79f1d9b88e088d6797dab8f5dbb9b1a8274fc12c21dcb` |
| recovery | 202.84 | 29 | `aa9607d95d1667b1500e43cf004e1867edc3b0fa1bd0f93a0b49793c22272079` |
| validator | 232.66 | 22 | `d925eb77dbc0a1bed49c7c4e851ac22ff57ba9e943451a528fe4f4229ab35170` |

Controller token usage is retained from each terminal JSONL event, including
cached input tokens. It must not be reported as native-agent usage. The
standalone validator's native receipt reports 2,239 tokens (2,124 prompt and
115 completion); complete native usage receipts were not emitted by every
caller in this phase, so no aggregate cost or efficiency claim is made.

## Follow-up: reduce observed mistakes, not demand perfect compliance

A subsequent audit found a context-provenance error in the original witnesses:
the first validator request put task prose in `expert_advice`; the neutral
candidate check put ordinary checking instructions in `human_advice`. Neither
introduced new scientific facts, but these fields misrepresented the source.
The original successful native verdicts therefore do not establish complete
information-treatment fidelity. Original transcripts and requests are retained.

The refinement adds an executable ancestor-root example inside Markdown,
a source-to-field map for request context, and focused reference-reading
instructions. It preserves native upstream expert guidance instead of treating
all advice-like fields as initial human advice. No native API, runtime script,
workflow strategy, task package or permission changes.

Two fresh sessions reused the prior objectives, fixtures, model/effort and call
ceilings. Runtime HEAD was `90a48ce0e8bfdb1b283f53fd29dd2eec41ba3dbf`, whose
production tree is identical to the earlier runtime pin. Only the copied
Markdown payload changed. Both first commands used the ancestor-root example
successfully; both preserved all original inputs.

| Retest | Seconds | Actual result | Transcript SHA256 |
| --- | ---: | --- | --- |
| native_choice | 177.57 | Native validator passed; human_advice=None and expert_advice empty, independently schema-validated | `dc7542a98925fa7d8d83b4339075abc0e0664513c39e4a89041d32b33721fe20` |
| discovery_retest | 92.92 | Correct disabled/unbound analysis and missing-candidate readiness; no provider call | `b9223edd04f885fc638899a4548623ed14f8fd2a0a570295e1a21a3a7eb4ded0` |

The validator retest also exposed an incomplete documentation surface: the agent
guessed `node_name` for `bridge.set_run_context`, failed before invoking the
validator, inspected the real signature and recovered. The guide now lists all
four exact keyword arguments for bridge and tuner recording. Both signatures
were checked directly with Python signature binding; this final signature
addition was not itself exercised in another real-agent session.

The ancestor example also passed local checks for multiple child levels, paths
containing spaces and a missing root. Advice provenance and candidate identity
were independently checked in the actual native request/result. Evidence is in
the ignored work plan's `artifacts/refinement-20260918/`.

Residual observations: broad source scans persisted (the validator read a
rendered Quickstart HTML page); no reading-efficiency improvement is claimed.
The readiness session used system `python3` once for file metadata despite the
declared exact interpreter, then used the correct environment for native
inspection. That remains a minor environment-instruction deviation, not a
scientific result. The operator assembly guide now asks for explicit prerequisite
locations/preparation routes and an interpreter for helper commands; that
provisioning improvement is guidance, not a measured deployment result.


## Manual coverage and context continuity acceptance

The operator clarified the boundary: qualify whether the manual is complete,
reachable and usable across continued work. Do not turn every observed failure
to follow an already-read rule into another instruction or runtime feature.
Classify each witness separately:

| Observation | Interpretation |
| --- | --- |
| Needed capability or prerequisite route has no reachable documentation | Manual coverage/discovery defect; fix the smallest missing route. |
| Guide was read but its example/field description prevents a valid call | Interface guidance defect; compare against the installed schema/source. |
| Correct rule and usable interface were read, but actor ignores them | Actor adherence deviation; retain it without claiming the manual enforces behavior. |
| Provider/environment unavailable | Infrastructure limitation; no behavioral pass or failure inferred for unfinished work. |

Inspect actual returned file contents, typed artifacts and source references,
not only the actor's claimed familiarity. Cover a broad catalog, focused tasks,
nested working directories and a fresh continuation with an actor-written
handoff. A fresh continuation tests recovery from that supplied handoff, not
automatic compaction or guaranteed retention over an arbitrarily long session.
Record whether the handoff preserves the toolkit entrypoints and active operation
without prescribing the next scientific strategy. Test fixtures and environment
limits remain separate from unchanged frozen task packages.


## Manual/context batch results

Five fresh Codex gpt-5.6-sol / medium sessions tested payload commit
`3fe3b6987a76bfdd19ac3c1a834a456d9e13cd3a` with runtime `49330e46`.
The exact instruction commit passed CI 35393285426. Each session had a 180-second
cap, with no native provider invocation, candidate execution, training or scoring.
Synthetic fixtures only; no real task package or private evaluator was supplied.

| Case | Observed result | Limit retained |
| --- | --- | --- |
| Catalog | Read all seven capability guides and schema/CLI inventories; produced a cited catalog. Independent comparison verified all 14 models / 407 fields and existing source links. | Stopped at the cap after writing artifacts; no final CLI completion. Report initialization remained late. |
| Nested restored regression | Native restoration protocol, artifact hashes, candidate identity/config/I/O verified; produced an actual continuation with toolkit/skill/guide and result paths. Normal exit at 133.25 sec. | No native validator executed; historical verdict remains historical. |
| Different synthetic scope | Serialized ProposalInput resolves to [4,5,6,7,8,9] in 20 partitions, independently verified; no 0-3 carryover. | Stopped at cap after request/check; readiness remained preparing and final report/handoff was absent. |
| Nested missing classifier tests | Located validator guide; validated a request, reported missing tests and no acceptance, with zero native calls. Normal exit at 132.15 sec. | Static inspection is not executed model/test evidence. |
| Fresh continuation | Received the restore actor's unchanged handoff; reopened toolkit/guide and verified prior artifacts, then produced a native request retaining identity/config/I/O. Normal exit at 117.23 sec. | Supplied-handoff recovery, not automatic compaction. No new outgoing continuation file was written. |

Returned read contents establish skill and invocation-guide reading in every
case. Frozen input inventories and copied payload hashes are unchanged in all
five cases; terminal receipts show zero surviving test processes. The two capped
runs received kill signals at 180.02 seconds (poll/scheduler latency); receipt
reaping completed later. The broad catalog and recovery witnesses establish
reachable interface guidance and useful context pointers, not exhaustive semantic
understanding or a guaranteed adherence rate.

Reporting deviations persist despite reading the relevant rule. Under the
operator's clarified boundary, retain these as actor adherence observations;
do not add another generic instruction for each missed update. Early and updated
reports were observed in some focused cases; no universal checkpoint guarantee
is claimed. Cache suppression was also configured by the test harness, so any
absence of cache writes is not attributed solely to the new prose.

Evidence (input/payload hashes, actual returned read contents, requests, report
observations, terminal receipts and independent audits) is retained after known
credential-value scanning in ignored local `artifacts/manual-context-20260918/`.
No new runtime feature, scientific strategy or frozen-task edit was introduced.
The tested manual changes are sufficient for this bounded documentation scope;
automatic context compaction and full scientific execution remain untested here.

| Case | Transcript SHA-256 |
| --- | --- |
| catalog | `f57cc962d5ef94bda67818411d12081045c6437fc09e30ffdee0ae2a89ed10fa` |
| restore | `d44bc6c2d1273b35f938f46e297b0b0acd5b5d6caa76fd796069de02d32ce4b6` |
| scope | `d86358ead41780007eca4e39c72b6f8042c2f24db55890ae7e021c7f40feae5d` |
| missing | `bb3b965f4533de858eb72d1a599716d194b572963424ecaec273eeb0a79af1ac` |
| continuation | `1ff25894480e878e9a689eb1bc6fcdff42f1834901edf37873391e18c38c7c1a` |


## Protected inputs and actual compaction witness

The operator narrowed wrapper write protection to infra and the frozen task;
other scratch/cache locations have no additional blanket wrapper restriction.
Pre-existing task rules remain intact. Updated instruction payload `34a38d00`
was tested with runtime `49330e46` and the existing synthetic restoration task.
No production checkout permissions were changed. A process-local `bwrap` mount
made the isolated runtime (including its virtualenv), actual Git metadata and
whole input tree read-only; in-process create probes returned EROFS for all
three roots. The normal CLI approval route remained enabled.

One fresh gpt-5.6-sol / medium session exited 0 at 294.654 seconds within a
360-second cap. The installed CLI accepted strict configuration with
`model_auto_compact_token_limit=8000` and scope `body_after_prefix`, documented in
the [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
These are diagnostic settings, not a production recommendation. No custom
compaction prompt or injected continuation summary was used.

The persisted session rollout contains **five actual compacted records**.
After compaction the actor reopened the toolkit/run/task instructions, used the
native implementation-to-validator protocol, and wrote a serialized ValidatorInput.
Independent checks verified native validation, unchanged candidate identity,
configuration and Model-I/O, restored artifact hashes and empty advice fields.
The request check timestamp is later than the fourth compaction; a fifth
compaction occurred after preparation and before the final response. JSON/Markdown
readiness, request/check, report and continuation artifacts exist. No native
provider call, candidate/test execution, training or scoring occurred.

Before/after inventories show unchanged frozen inputs and tracked infra files;
no test processes survived. This combines preventive mounts in the tested launch
with artifact checks; it is not a claim that ordinary Markdown protects a host.
Formal deployments must supply and verify their own equivalent protected roots.

A residual actor error remains: its continuation lists `references/validator.md`
instead of the existing `references/agents/validator.md`, despite reading the
correct guide earlier. The recorded continuation is not repaired after the test.
It also recovered from an incorrect schema import before preparing the valid
request. These are actor path/recall mistakes, not missing manual pages. This
witness shows useful recovery across real compaction, not perfect preservation,
a guaranteed success rate, or complete scientific execution.

Exact input/payload hashes, mount probes, session rollout, requests, terminal
receipt and operator audit are archived after known-credential scanning in the
ignored local `artifacts/protected-compaction-20260918/`. This supersedes the
prior 'automatic compaction untested' limitation only for this bounded case.
Deployment integration remains separate: isolated repair qualification does not
change the frozen package's dependency or merge/deploy the open repair PR.

| Evidence | SHA-256 |
| --- | --- |
| `operator-audit.json` | `b681b862f811829c078b7aee9611d5ced223136b28f2d7945859736be4d0d05b` |
| `evidence/receipt.json` | `604ba775d4dfe1958059c313a6ea275f2598154dfd172e6cd95a4d19ce3f1f9b` |
| `evidence/session-rollout.jsonl` | `2b2115bba0aa7e876305d1bfcaea7266d131c40cfe36435afbc1e21b8cf876b7` |
| `work/validator-request.json` | `56235729622ea3692b894339acd2d26aedeec96dc292a5d00c9b79f835136a8a` |
