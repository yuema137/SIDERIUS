# Troubleshooting

**Answers**: where to look, what the symptom means, and what actually fixes it.

Two tables already cover deliberate refusals and are not repeated here:
[operating a run — failures and refusals](operating-a-run.md#failures-and-refusals)
for run-time outcomes, and
[define a task — when it refuses](define-a-task.md#when-it-refuses) for
composition problems. This page covers everything around them: environment
faults, stalls, and how to locate the evidence.

---

## Where to look, in order

1. **The launcher output.** In `--mode lilab` the chain runs in the foreground;
   the failure is on your terminal. In `--mode sdsc` each iteration is a Slurm
   job — read that job's log (by default Slurm writes `slurm-<jobid>.out` in
   the directory the launcher submits from, unless your site redirects it).
2. **`{workspace}/iter_NNN/manifest.json`** — one per iteration, written at
   iteration end. The most recent one tells you how far the chain got and with
   what status.
3. **The newest node record.** Records appear in stage order under
   `{workspace}/iter_NNN/iteration_001/` — interpretation, then per-attempt
   `proposal`/`implementor`/`validation`, then the tuner's directory. The last
   file written names the stage that stopped. See
   [workspaces and resume](workspaces-and-resume.md) for the full layout.
4. **The tuner's records** under `iteration_001/{model_name}/` — per-round
   statuses, failure types and health-gate results live here.
5. **Re-launch with `--dry-run`** to print the exact child commands without
   executing anything, when you suspect the command line itself.

Two cheap triage tools, both free of GPU and API cost:

```bash
.venv/bin/python scripts/diagnostics/check_agent_environment.py  # opt-in; calls provider APIs
.venv/bin/python -m pytest tests/unit/ -q    # is the checkout itself sound?
```

And a $0 end-to-end wiring smoke: `--is_pseudo_llm --is_pseudo_training` swap
the LLM bridge and the sandbox for canned stubs, so the whole chain executes in
seconds with no key and no GPU. If pseudo-mode works and a real run does not,
the problem is in your keys, data or GPU — not the wiring.

## Environment and install

| symptom | cause → fix |
|---|---|
| `SyntaxError` on an f-string, or errors mentioning Python 3.8 | you ran the system `python3`. Use the project venv: `source .venv/bin/activate` or `.venv/bin/python`. The chain launcher guards this itself (it refuses Python < 3.10) — standalone scripts do not |
| `ModuleNotFoundError` for a project package | run from the repository root with the venv active; re-run `uv sync` |
| LLM auth errors at startup | keys missing from `.env` — see [installation](../getting-started/installation.md#api-keys) |
| **Gemini auth errors although you only configured OpenAI** | you launched without `--llm_config`. The legacy default silently routes every stage to Gemini. Always pass an explicit routing config — `--llm_config configs/llm/openai_tiered_pro.json` is the canonical example |
| `check_agent_environment.py` reports one provider failed | that provider's key or network path; the run only needs the providers your `--llm_config` JSON routes to. Read the printed summary: the diagnostic currently exits zero even when checks fail |

## The run seems hung

| symptom | what is actually happening |
|---|---|
| stopped mid-LLM-call, no error, retry lines in the log | **quota/billing exhaustion is retried indefinitely by design.** The bridge waits and retries rather than crashing a long campaign; top up the account and the run continues on its own |
| a training/inference child was killed at a deadline | the runtime watchdog (`--runtime_watchdog`, off by default) enforced its deadline. The record names the phase; budgets and safety factors are operator surface — see [operating a run](operating-a-run.md) |
| long silence during a formal round | formal rounds are sized to be long. Check the time budgets you launched with before assuming a hang |

## Memory failures

Out-of-memory has three distinct shapes; the record tells you which you got:

| record status / failure | meaning |
|---|---|
| `skipped_oom_risk` | the *pre-flight measurement* refused admission before training — the plan did not fit the VRAM budget. Consumes an attempt; not a crash |
| an OOM inside training/inference | the child hit a real limit. Host-RAM ceilings are enforced per role (training / inference / scoring) so the kernel's OOM killer is converted into a recorded, structured failure instead of a dead machine |
| the host itself swapping or killing processes | the global override `SIDERIUS_SUBPROCESS_RSS_GB` exists for hosts whose RAM cannot fit the declared role ceilings — an operator decision, not a first resort |

## Resume problems

| symptom | cause → fix |
|---|---|
| startup refusal naming a mismatched invariant | you changed scope / health settings against an existing workspace. That is the guard working — use a new workspace. See [workspaces and resume](workspaces-and-resume.md) |
| a resume starts at the wrong iteration | the launcher's automatic `START_ITER` capture can be corrupted by plugin-loader output on stdout. Pin it: `--start_iter N` |
| "all iterations complete", exits immediately | not an error — auto-resume found nothing left to do. Raise `--num_iterations` to continue |
| the launcher halts saying it cannot compute the next iteration | the resume inspector could not read the workspace state; it fails closed and shows both signals rather than guessing |

## Results look wrong

| symptom | first question to ask |
|---|---|
| every round of a model is invalidated | read the health-gate results in the tuner records — a real collapse is *supposed* to look like this. [Health gates](../concepts/health-gates.md) |
| a score is `not_scoreable` | the metric's scoreability contract refused before arithmetic; check the deliverable exists and is readable |
| scores across two runs disagree "for the same settings" | are they the same scope and the same health config? Aggregates are only comparable within one lock identity |
| the dashboard shows nothing | usually a data-root or layout mismatch, not a failed run — see [the dashboard guide](dashboard.md#when-the-page-is-empty) |

## When it is actually a bug

If a failure is not a named refusal, not an environment fault, and not
reproduced by pseudo-mode, collect: the launcher command line, the newest
`manifest.json`, the failing stage's record, and the child log — that set is
what a maintainer needs to reproduce it.

---

## Next

- [Operating a run](operating-a-run.md) — the refusal table and steering flags
- [Workspaces and resume](workspaces-and-resume.md) — layout and the lock
- [Dashboard](dashboard.md) — browsing what happened
