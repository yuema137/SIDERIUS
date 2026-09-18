# Evidence integrity and recovery qualification

This follows the [multi-task checks](MULTITASK-QUALIFICATION.md). The goal is to
check evidence interpretation and actual native handoff use, including a normal
reuse case that should not be blocked by guidance for new candidates.

## Setup

Initial payload: `3a862ee7b1f673d1b9c46ad1b7df2cd32fe84b73`. Runtime source is
unchanged from the toolkit's interface reference `1c68bc81`. Fresh Codex CLI
0.154.0 sessions used OpenAI `gpt-5.6-sol`, medium reasoning, a nested `work/`
start, the checkout's frozen environment and a shared 480-second ceiling.
The neutral opening prompt was the same as the preceding qualification.
No scientific training, scoring, GPU, external retrieval or private evaluator
was used. The operator explicitly authorized transmission of generic toolkit
instructions, necessary framework interfaces/source and synthetic artifacts to
that model service; credential values and real scientific data were excluded.
One launch was initially rejected by automatic approval review; it proceeded
only after that explicit authorization. Rejected launches are not test results.

Fixtures use the earlier Quickstart classifier and actual native regression
implementation/validation artifacts. Restored files have an explicit path/hash
manifest; old absolute paths are provenance, not authorized input locations.
The stale-model case deliberately changes `torch.tanh` to `torch.relu` while
retaining the old real passing verdict, shape and parameter count. The original
records are not rewritten to claim they validated the changed model.

## Initial observations

| Case | Actual observation | Interpretation |
| --- | --- | --- |
| New classifier, missing required test | 160.8 s; one native validator returned `passed=True`, `tests_passed=True`, and a `Skipped:` test explanation. Actor reported not ready because the required suite never executed. | Native booleans do not prove executed-test evidence. No actor false acceptance occurred. |
| Changed restored regressor with old passing verdict | 151.2 s; actor compared hashes/source, found ReLU in the tanh model and rejected old verdict applicability. Its one permitted native call hit a DNS failure; internal transport retries did not become a new invocation. | No stale acceptance and no fabricated fresh validator result. Current native verdict was unavailable. |
| Unchanged restored implementation, request only | 131.4 s; actor verified hashes and produced a correct `ValidatorInput`, but manually copied fields and never called `local_all_fields`. | Correct final content, but missed reuse of an existing protocol. Schema-valid output alone would have hidden this routing miss. |

The request-only actor read the skill and validator/schema material, but did not
follow the handoff reference for this recovery. Its script, not its final
message, establishes the absence of the protocol call. It neither called the
unimplemented database protocol nor executed candidate code or invoked a provider-backed native agent.

Independent offline native checks reproduced `tests_passed=True` plus `Skipped:`
for empty, nonexistent and directory test paths; native input validation also
accepted a missing path. These checks made no provider calls. They separately
confirmed that the supported implementation-to-validation protocol preserves
candidate identity, config and model-I/O, and that its database alternative
raises `NotImplementedError`.

## Documentation changes

Only three payload Markdown pages changed:

- The skill explicitly routes saved-output recovery and artifact-path relocation
  to the handoff reference.
- The handoff page says to use a covering native projection before caller-owned
  adjustments and demonstrates typed implementation recovery with path-only
  overrides. Supplied candidates without native upstream output may still need
  direct input construction. This is no prescribed research sequence.
- The validator page links this recovery example and documents the native
  skipped-test behavior. Native results stay unchanged; task acceptance gaps
  are reported separately. Existing authorized model reuse remains allowed.

The skipped-test caveat addresses a demonstrated native semantic trap, not an
observed actor false positive. No additional stale-verdict rule was added: the
existing instructions worked in that case. Runtime behavior, native schemas,
task policies and budgets are unchanged.

## Revised-payload witnesses

| Case | Actual revised-payload observation |
| --- | --- |
| Missing required test | 138.2 s; read the new caveat, invoked the native validator once, retained its true/Skipped result, and correctly reported task acceptance false. No replacement test was created. |
| Restored implementation | 119.9 s; read the handoff page and actually executed `local_all_fields`, then revalidated only the three restored paths. Final saved request independently matches that native projection. No candidate execution or native provider call. |
| Authorized historical reuse | 93.3 s; validated the actual prior records, matched current model/config/I-O, distinguished their three executed passing tests from a skipped stage, and accepted historical reuse under the explicit task policy. No new validation was claimed or executed. |

The initial and revised recovery requests both have correct contents. The
observed improvement is actual native-protocol use, not an invented improvement
in scientific results. Their traces and caller scripts distinguish the routes.
The new-candidate and historical-reuse cases demonstrate different decisions
under their different task acceptance policies; no universal fresh-test gate
was added.

All six sessions ended normally with original input/package bytes unchanged
and no newly added files outside `work/`. Same-case task fixtures are
byte-identical across initial and revised conditions. Native typed requests
preserve empty human/expert advice channels. An unnecessary git-status command
in the revised recovery trace still reports that the package is not a git repo;
this harmless residual is retained, not counted as a solved failure mode.

## Evidence and limits

All initial and revised sessions retain raw JSONL traces, original-file hashes,
run declarations, caller scripts, typed native artifacts, summaries and terminal
receipts in the ignored local plan's `artifacts/integrity-20260918/` archive.
Payload hashes distinguish tested document versions. The audit checks artifact
contents and actual executed caller scripts; a mention of a protocol in read
source or a final answer is not proof that it was called.

| Session | Transcript SHA-256 |
| --- | --- |
| missing-initial | `7594d9c34a1c9b8651387fba9f8925a32e5e4a54ed40c3e7a6c234756b82b2c3` |
| missing-revised | `55d9dc542ef0f2f339dc69f210bed4008891624ec4fa612a308b08e7df4bd42e` |
| recovery-initial | `4d4469b9c9375e61ce492c907ceaac42c90d19acb65ba493b9c677742c95c5c6` |
| recovery-revised | `b77634b7124bac5a2de9ebc969d2807d9050408175228b8f801b29fde6ca5ab5` |
| reuse-revised | `1bc3233eba948e0770a282d8107b06780541a4b2997217a13ddbe6c73f3f11df` |
| stale-initial | `12226384b297cdddc44e5cbf59d4f3433b714778c014ee26ac4b42c09888945b` |

These bounded task instructions explicitly distinguish new-candidate acceptance
from historical reuse. The evidence is not a universal adherence rate, an
adversarial robustness claim, or new qualification of training and other native
agents. The changed-model witness had no fresh typed validator verdict because
of its provider transport failure. No broader live module coverage is claimed.
