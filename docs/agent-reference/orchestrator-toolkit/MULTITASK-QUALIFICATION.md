# Multi-task discovery and invocation qualification

This extends [discovery qualification](QUALIFICATION.md) with different task
interfaces, paired environment declarations and targeted follow-up checks.
It is evidence from bounded synthetic runs, not a success-rate estimate or
qualification of a scientific campaign.

## Design and identity

On 2026-09-18, six fresh Codex CLI 0.154.0 sessions used payload revision
`3f6271442bfd14492de977b812755994f1d2c7ea`. Each task had a sparse environment
declaration and a declaration with explicit paths and preparation status. Task
instructions and fixture files were byte-identical within each pair; resources
were available in both conditions. The extra facts did not supply an answer,
choose a native API or prescribe research order. No payload edits occurred
between these six launches and their completion.

Each session started from a nested `work/` directory with only this prompt:

> Complete the task described by this workspace task package and save the requested deliverables.

The actor and native nodes used OpenAI `gpt-5.6-sol`, medium reasoning. Each run
had one 480-second clock, CPU only, its checkout's frozen Python environment,
explicit capability ceilings and no training, scientific retrieval, GPU, cloud
operations or delegation. Actor sessions used `--ignore-user-config`,
`--ephemeral`, `--skip-git-repo-check`, `--approve-for-me` and JSON transcripts.
This is a host CLI qualification with authorized provider access, not a claim
that a production sandbox or private evaluator route has been qualified.

| Task | Scientific contract and objective | Native call ceiling |
| --- | --- | --- |
| Tabular | Quickstart binary classifier, float32 `[B,4] → [B,2]`; validate supplied 114-parameter model; existing composition and materialized data supplied | Two validator calls |
| Regression | Synthetic continuous estimates, float32 `[B,3] → [B,2]`; implement fixed width-5 tanh MLP, then check it; supplied ForwardContract, no dataset/composition required for this bounded objective | Two implementer and two validator calls |
| Image | Synthetic three-class classifier, float32 `[B,1,8,8] → [B,3]`; assess supplied two-logit candidate without repair | Two validator calls |

The expected image result is rejection. A negative scientific verdict is not a
wrapper failure. Conversely, shell exit zero or generated artifact paths do not
establish native validation success.

## Paired observations

| Task | Sparse declaration | Explicit environment facts |
| --- | --- | --- |
| Tabular | 200.1 s; first native validator passed; initial relative `input/` lookup failed and recovered | 187.8 s; first native validator passed, after setup errors for module-alias import, `Path` physical-data root and missing recording directory |
| Regression | 329.5 s; two implementations and two native validations; both native verdicts failed because generated tests imported from the wrong directory; caller later corrected only the test import and local pytest passed | 334.9 s; first native validation failed on the same import-path problem; native repair with aligned model/test directories followed by second native validation passed, 32 parameters |
| Image | 199.4 s; missing recording directory first; first native result included an invalid scalar-config projection and the real two-versus-three-logit defect; corrected second request still correctly failed the candidate | 169.6 s; one native validation correctly rejected the candidate without those setup errors |

All six traces show the ancestor lookup, run declaration, skill, selected agent
pages and corresponding schema inventory being read. Native request artifacts
validate against the installed Pydantic schemas. Carried model-I/O contracts
match their own task declarations; no task prose was substituted for human or
upstream expert advice. Both advice channels remained empty. Generated model
code came from the native implementer; the regression sparse actor's final
local test-import correction was recorded separately from the failed native
verdict. Its final changed test bytes have no passing native verdict.

All original package files remained unchanged. That alone did **not** prove
write-scope compliance: image sparse, image facts and tabular facts created
`.pytest_cache` at the package root, outside the authorized `work/` subtree.
The validator launches pytest as a child; pytest root discovery can select that
parent even when the caller's working directory is `work/`.

Explicit path facts did not consistently reduce rediscovery or errors. An
exploratory count of output characters from read-like shell commands was
154,492 versus 83,622 for tabular, 70,664 versus 83,645 for regression, and
45,150 versus 73,877 for image (sparse versus facts). This is neither token cost
nor a clean measure of necessary reading: mixed shell commands and tool output
are included. No efficiency claim or mandatory expanded declaration template
is justified by one pair per task.

## Changes selected from the observations

Only generic Markdown guidance changed:

1. Create an authorized recording directory before `set_run_context`; show the
   existing bridge's iteration and run-identity preconditions.
2. Pass the physical data root as a string in the task-binding example.
3. Explain the validator's scalar `config_fields` projection with a concrete
   example; keep model identity in its dedicated field.
4. Explain the existing implementer's `../models` test-generation assumption
   and a compatible caller-owned directory layout. Keep failed native results
   visible and distinguish a local post-edit test from native validation.
5. Document pytest cache placement for supplied tests outside writable storage,
   using existing process-local pytest configuration when authorized.

None of these chooses serial/parallel orchestration, changes scientific inputs,
adds a feature, adjusts an experiment budget or changes a native schema.

## Targeted retests

Three fresh sessions used the same facts-condition fixtures with the first four
Markdown corrections. Their copied payload was fixed during the tests.

| Task | Observed retest |
| --- | --- |
| Tabular | 153.5 s; created recording directories and passed a string physical-data root. First native invocation reached a DNS failure; an authorized second invocation passed, 114 parameters. Cache still escaped `work/`. |
| Regression | 227.9 s; selected sibling `candidate/models` and `candidate/tests`, created recording directory; one native implementer followed by one native validator passed, 32 parameters and three tests. No manual model/test repair. |
| Image | 148.3 s; numeric scalar config projection and existing recording directory; one native validator correctly rejected the unchanged candidate. An unnecessary git-status command still failed in the non-git package. |

The corrected examples were actually read and their directory/argument choices
appear in caller scripts. None of the four targeted invocation mistakes recurred
in these three witnesses. This observation does not isolate each prose change's
causal effect or prove general reliability. The passing native verdict in the
regression retest is distinct from the initial sparse case's local-only success.

The pytest cache issue then received its own documentation example. Two offline
checks called the real native validator's pytest subprocess on copies of the
passing tabular and failing image tests: both retained their original verdicts,
and all generated files stayed in the authorized subtree. No provider call was
needed for this mechanism check.

A final fresh tabular CLI session, 154.5 s, read the updated validator page and
used its existing `PYTEST_ADDOPTS` configuration before invoking the native node.
The validator passed on its first call; pytest reported
`work/validator_call_1/pytest-cache`, and the independent file audit found no new
file outside `work/`. This supplies an actual adoption witness, not merely a
syntactically valid example. Across all ten sessions, task input bytes are
identical between variants of the same task and all original files remain
unchanged. The earlier cache violations remain part of the evidence.

## Evidence and limits

Raw fixtures, before-file hashes, exact run declarations, request/output JSON,
JSONL transcripts, native records and final receipts are retained in the local
ignored plan archive `artifacts/multitask-20260918/`. The operator-side review
validates native artifacts and compares input hashes; the actor's final message
alone is not the witness. Payload hashes distinguish the initial, corrected and
cache-guidance conditions even though runtime source is identical.

| Session | Transcript SHA-256 |
| --- | --- |
| image-facts | `f8c71c01561950a39331ed9790a9674934bc3bf5125794280c23451f5f44b03c` |
| image-facts-retest | `9e21493c42863b6fd7858754045cfeaf179105c010a1f7042f8d15104dbc352c` |
| image-sparse | `797670b14c3b97fe462791df7f85d292557ee42c4310c2498b0f5c3afdea465c` |
| regression-facts | `ebb8ad57bf43885d5439109ce4ed65e3bd22a5f9e4edb196f0545dc21344607e` |
| regression-facts-retest | `2386f29182e6690d16a6a07316ebc92f0638e7c425fd8f475dfb265d7ec2e112` |
| regression-sparse | `2a7bcd27ed08692f7aee764d1c1841ea64706f1675a5af5c21743b5c0b035afd` |
| tabular-facts-cache | `5f265f531694074a74ca37abfa06bdaf0431ec1ad969b290a3e2ee677f8f0546` |
| tabular-facts | `3584a2aacdcc27baab96228db789d167b75072970ae742d1255eb2e42ba830b2` |
| tabular-facts-retest | `6fac5974b7e0dd91c467b6925fa7347b133632f2fbf4dc22d3eda86f3b15791c` |
| tabular-sparse | `da63ecd1324be201dad352b6e8ba12236083e5edd847e0f594bcf404f20e7b68` |

Residual failures include unnecessary source/schema inspection, compatibility
module-alias guessing despite existing import guidance, stale relative-path
assumptions after resolving the root, and attempts to use git status in a
non-git package. These remain reported; this round does not claim perfect
instruction following. Tests exercise two native capabilities across three
interfaces, not every capability on every task. Prior catalog/discovery checks
cover the broader documentation; live literature, Data Analysis, tuner training,
GPU operation, simultaneous registry writers, compaction recovery and an actual
scientific submission remain outside this evidence.
