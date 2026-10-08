# Optional reviewed standard launch contract

Scope: fresh standard single iteration only. The public `tools.setup_review.launch`
CLI and `launch_reviewed(ReviewedLaunchRequest)` consume an environment report,
semantic receipt and explicit finding dispositions. Ordinary standard main calls
have `reviewed_setup=None` and never read review artifacts or require a clean Git
checkout. There is no generic orchestration approval, scheduler or skill registry.

## Owners and flow

- `snapshot_io.read_verified_json` reads bounded regular/no-follow saved bytes;
  the caller supplies expected SHA and no child-returned path is followed.
- `environment_settings` adds optional `launch_binding` only for `bind_launch=True`.
  `reviewed_launch_binding` records clean installation identity and finite explicit
  configuration-file identities with shared `core.file_identity/stream_identity`.
  The byte limit is per file, not a hard time limit on blocked parent IO.
- `semantic_packet` explicitly selects environment fields for v3. Older declaration
  and task-check packet branches retain v1/v2. Saved paths are not reopened by review.
- `prepare_reviewed_launch` checks receipt-to-report and packet linkage, requires
  passed task/settings evidence and review/skip outcome, then validates dispositions.
  Every error/warning requires one exact index/content digest and nonblank reason.
  Information is optional, but supplied entries must still match. A changed input
  requires new evidence, not an acknowledgement exception.
- The ordinary parser revalidates supported scope/current declarations. The optional
  context then checks actual composition/package, watchdog/hardware/aggregate policy,
  resolved LLM/launch identity and existing run invariants. `run_one_iteration` passes
  the same checked launch object and composed authorities into `run_workflow`.
- `formal_delta` is the shared lossless JSON codec for the two owner-permitted
  nonfinite formal-policy fields. It adds no new execution default or acceptance rule.
- `watchdog_profile.selected_profile_source` locates a selected profile using that
  resolver's filename authority; no duplicated host/device naming rule.
- `core.durable_io` publishes a write-once launch-check receipt before workflow
  execution. Early input errors need not produce a receipt. Initialization can write
  workspace/Health files before a late mismatch; no recursive rollback occurs.

Explicit file inputs are manifest, LLM JSON, Health override, advice, selected
literature configuration, runtime profile and finite declaration files named by
task provenance. Plugin directory roots are excluded. The task-config owner records
the SHA of the same bytes it parsed alongside its existing cache. A populated cache
with stale or missing source evidence refuses reviewed launch with a restart and
regenerate instruction; ordinary cache lifetime and dictionary identity are unchanged. Analysis source directives and
workflow parameter rules are inline values, not filenames. Task/plugin identity
uses existing composition/code-package owners, not a recursive directory hash.
Installation identity covers source checkout/head and interpreter/prefix/version;
it is not complete attestation of every third-party dependency.

## Refusal and limits

Malformed schemas, digest mismatches, unsupported/advisory-only reports, missing or
foreign dispositions, changed inputs and identity/policy mismatches refuse before
workflow execution. A model finding cannot override deterministic failure. Named
safe refusal messages are shown without raw supplied configuration/provider errors.
Native failure records remain under the native runner. `matched` records only this
check; a later workflow failure retains the native exception and matched receipt,
without claiming that authorization never happened or that the run succeeded.

No timestamp, free-memory reading or host-name heuristic establishes device identity.
Missing observations remain gaps. Hardware/configuration can change after the check;
normal admission and runtime protection still apply. Same-user concurrent mutation,
arbitrary plugin behavior, complete data validation and authentication are outside
this receipt's authority. Saved sandbox wrappers remain historical; this operation
does not reconstruct them or change mounts/network/device permissions.

Custom orchestration may use native toolkit operations and inspect supported
snapshots, but cannot use this standard receipt as caller-wide authorization.

## Request recipe

After inspecting `receipt.json` and its findings, create an external
`reviewed-launch.json`:

```json
{
  "report": "/home/alex/project/environment/report.json",
  "expected_sha256": "<SHA-256 of environment/report.json>",
  "receipt": "/home/alex/project/review/receipt.json",
  "receipt_sha256": "<SHA-256 of review/receipt.json>",
  "output": "/home/alex/project/launch-check-001",
  "input_max_bytes": 1048576,
  "dispositions": []
}
```

For an explicit skip or a review with no error/warning findings, the empty list is
sufficient. Otherwise include one entry per error/warning: `index` (zero-based),
`finding_sha256`, `action: "acknowledge"`, and your nonblank `reason`. Information
findings remain visible without requiring individual acknowledgements. Compute
an entry's digest with the typed owner, without changing its text:

```python
import hashlib
from pathlib import Path
from tools.setup_review.semantic_models import SemanticReviewReceipt

receipt = SemanticReviewReceipt.model_validate_json(Path("review/receipt.json").read_bytes())
if receipt.judgement is not None:
    for index, finding in enumerate(receipt.judgement.findings):
        print(index, finding.severity,
              hashlib.sha256(finding.model_dump_json().encode()).hexdigest())
```

Run from the working directory recorded in the original declaration, using the
same qualified checkout interpreter:

```bash
/path/to/SIDERIUS/.venv/bin/python -m tools.setup_review.launch \
  --request /home/alex/project/reviewed-launch.json
```

