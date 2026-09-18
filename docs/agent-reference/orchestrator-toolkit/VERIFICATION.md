# Verification record — 2026-09-18

The generic documentation layer was checked against framework revision
`2df46e2298c017d9df850a85f870a55fbd40723d`. This is bounded interface and
coding-agent evidence, not qualification of a scientific campaign.

## Static and additive checks

- Skill Creator's `quick_validate.py`: passed.
- Seven single-call example blocks import successfully in this checkout's
  frozen Python 3.12.13 environment, with an isolated generated library.
- All 407 top-level fields across 14 native input/output classes are present
  in the inventories; native classes remain the validation authority.
- Twelve handoff functions were imported and their signatures inspected. Two
  draft descriptions were corrected: literature/analysis fan-in returns a
  rebuilt ProposalInput, not a detached evidence object.
- All relative Markdown links resolve. Final documentation contains 27 Python
  snippets; syntax checks passed. Constructor signatures are labelled text,
  not executable examples.
- The added task-context example ran inside a real Quickstart composition and
  returned its task description and typed forward contract. No training ran.
- Assembly of 26 payload Markdown files preserved both synthetic common input
  files byte-for-byte. The verifier rejected deliberate removed/changed-base
  controls. This checks the generic assembly mechanism, not parity against any
  deployed scientific baseline archive.

No existing tracked file or executable was changed. Validation scripts and raw
run records are local evidence, outside the distributable payload.

## Actual local Codex session

| Item | Observed value |
| --- | --- |
| CLI | codex-cli 0.154.0, real `codex exec` session |
| Controller | gpt-5.6-sol, medium reasoning |
| Framework provider routing | openai / gpt-5.6-sol / medium |
| Started | 2026-09-18 06:15:58 UTC |
| Duration / terminal status | 373.47 seconds; process exit 0; `turn.completed` |
| Task | Prepare a first proposal for the shipped synthetic Quickstart task and a schema-valid implementation request; report remaining prerequisites |
| Scope | CPU-side reasoning and handoffs; no implementation, training, scoring, retrieval or cloud actions |
| Ceiling | 10 minutes and two provider-backed node invocations, including failed invocations |
| Artifacts | Interpretation request/output, proposal request/output, task composition reference, implementation request, attempts and exception records |

The kickoff was:

> Use $siderius-toolkit to complete the task declared in SIDERIUS-RUN.md in this workspace. Read the applicable instructions and use the provided documentation to determine the existing interfaces you need. Make actual calls where supported, preserve their outputs, and report what you observed. Do not ask for a preferred workflow; choose it yourself within the declared limits.

The run declaration supplied the task paths, exact Python/revision, enabled
capabilities, routing, write boundaries and limits. It did not supply the
required schema fields, call sequence or expected proposal. The task's existing
Quickstart scientific instructions were supplied unchanged; they are separate
from the neutral skill.

### What the transcript establishes

| Observation | Evidence and interpretation |
| --- | --- |
| Entry and progressive reading | `item_1` actually read AGENTS.md, SIDERIUS-RUN.md, SKILL.md, invocation and artifact rules; `item_4` read handoffs; `item_5/6` read interpretation/proposer guides; `item_7` read evidence policy; `item_8/9` read their schema inventories. This is file-read evidence, not merely a self-report. |
| Independent orchestration | The agent selected cold-start interpretation, proposal, then a typed implementation projection. This is one observed strategy, not a recommended or universally expected sequence. |
| Interface recovery | An initial task-config import guess failed; the agent inspected source and found the correct module. |
| Binding recovery | Composition refused a missing physical data root before any node call. The agent materialized the four pinned synthetic shards and retried. |
| Real invocation | Two deterministic cold-start interpretation executions completed. The first proposer invocation failed on sandbox DNS after three transport attempts; the final allowed invocation succeeded through reviewed network access. |
| Actual provider work | Successful proposer stages `legacy_reasoning` and `legacy_commit` have native receipts: 4,560 and 6,124 tokens, respectively. One node invocation can contain multiple provider requests. |
| Typed handoff | Returned candidate `harmonic_bilinear_mlp` was projected with the existing protocol. Independent native validation confirmed matching candidate ID, model name and baseline configuration, and the task's `[B,4] float32 → [B,2] float32` forward contract. |
| Honest incompleteness | The native proposal's baseline_config was empty. The agent preserved it, produced a schema-valid implementation request and explicitly identified missing concrete starting configurations. It did not fabricate training evidence or claim implementation readiness. |
| Input preservation | All 29 initial runtime files were unchanged at independent review: 26 payload documents, two common input files and the added run declaration. |

The agent's final audit command validated all five request/output models and
lineage, then returned exit 128 for a Git check in the non-repository runtime
workspace. That audit command's nonzero status is retained; it does not undo the
preceding native validations. The parent independently checked the actual
framework worktree and output artifacts.

### Costs and scope limits

Native successful proposer usage was 10,684 tokens: 5,021 prompt and 5,663
completion. The Codex terminal event separately reported 1,124,084 input tokens
(1,061,376 cached) and 10,721 output tokens, including 2,337 reasoning output
tokens. These are different accounting surfaces; no comprehensive billing or
cost-efficiency claim follows. Failed transport has no successful usage receipt.

The test exercised real Codex, deterministic interpretation, a real proposer
provider call, and typed handoffs. It did not invoke the implementer, validator,
tuner, literature review or Data Analysis; import checks do not certify those
capabilities' runtime behavior. It did not test concurrent native execution or
context-compaction recovery. A single trajectory cannot establish general
instruction compliance or optimal scheduling.

### Evidence identities

| Artifact | SHA256 |
| --- | --- |
| interpretation_output.json | `e48a19ebbe7a694ee16e1292c11dd42ae1f43da4bd6d112088b77128f98c2017` |
| proposal_output.json | `cb4302a2093a7a6b8aef417f0715ee0fc99cfacb916bca2c1e92f5e211f777a7` |
| implementor_request.json | `08ffd03331f73baf445f97b4229034a5db8c512c327654ec07a0ada45e2694e0` |

Raw JSONL, before/after hashes, launch receipt, prompt, artifacts and local
validation scripts are retained in the ignored structured-coding plan for this
work. Credentials are excluded. The full trajectory is not an agent input.

## Changes after observation

Added the accurate `workflows.task_config` loader location and explicit data-root
requirement to shared invocation guidance. Corrected the implementer guide to
name input `forward_contract`; realized `model_io_contract` is an output used by
the validator. Those small changes passed targeted syntax/import and actual
bound-context checks. The real session used the prior payload snapshot, which
was not edited while it ran. No second real-session outcome is claimed.

An earlier launch command failed argument parsing because `--sandbox` and
`--approve-for-me` conflict in CLI 0.154.0; it never started an agent. The successful
run used `--approve-for-me`, which supplies workspace-write and approval review.
That preparation failure is preserved separately from the actual session.

## Reproduce the bounded observation

Use a fresh workspace assembled according to [ASSEMBLY.md](ASSEMBLY.md), with the
shipped Quickstart task instructions and a run declaration matching the table
above. Provide the exact checkout's frozen environment and required provider
credentials through the documented machine-owned credential mechanism. Check
only credential presence, never print values. Bind an empty run-owned generated
library before registry-bearing imports; do not reuse another run's cache.

The actual invocation shape was:

```bash
codex exec --ignore-user-config --ephemeral --skip-git-repo-check \
  --approve-for-me -m gpt-5.6-sol \
  -c 'model_reasoning_effort="medium"' \
  -c 'shell_environment_policy.inherit="all"' \
  -C "$QUALIFICATION_WORKSPACE" --json \
  -o "$QUALIFICATION_FINAL" - < "$QUALIFICATION_PROMPT" > "$QUALIFICATION_EVENTS"
```

The outer caller enforced the 600-second ceiling and recorded the process exit
status, terminating its process group on timeout. Repeating a run requires fresh
artifacts and its own bounded authorization; do not assume a matching trajectory
or proposal. Review actual reads, effects, exceptions and native output validity.
