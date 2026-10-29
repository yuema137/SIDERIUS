# Model qualification evidence: 2026-10-28

## Provenance and scope

These are operator-run live smoke observations from the QPD consumer project,
transcribed from sanitized receipts committed there as `e0d28c4` and `14bef01`.
They test generic bridge behavior; no scientific data or model-training outputs
were sent. This document preserves the acceptance checks, configuration and
usage totals without depending on private machine paths or publishing credentials.

The framework revision was `b3f927ad0e8b1a275b74b08fc371b9e0061f4305`, with that
checkout's `uv.lock` and `pydantic-ai` dependency installed. Calls used explicit
provider/model IDs and official endpoints, with no reasoning-effort override.
The bridge settings were `max_output_tokens=4096`, `max_retries=1`,
`request_timeout=60`, `timeout_retries=0`. These are bridge settings, not a
whole-workflow budget. No fallback model was used.

## Requests and acceptance

| Path | System prompt | User prompt | Acceptance |
| --- | --- | --- | --- |
| Text | `Follow the instruction precisely.` | `Reply with exactly READY.` | Stripped output equals `READY`. |
| JSON | `Return the requested JSON object.` | `Return {"ok":true,"count":3}.` | Parsed object equals `{"ok": true, "count": 3}`. |
| Tool | `Select the requested tool; do not execute it.` | `Call inspect with name candidate.` | Tool name is `inspect`, arguments equal `{"name": "candidate"}`, call ID is nonempty. |

The sole tool was an OpenAI-format function definition named `inspect`, with
description `Select an item for inspection.` and this parameter schema:

```json
{
  "type": "object",
  "properties": {"name": {"type": "string"}},
  "required": ["name"],
  "additionalProperties": false
}
```

These are intentionally small payloads. They do not exercise full node business
schemas, generated-code quality, long contexts or end-to-end training.

## Successful call receipts

Requested and served model IDs agreed on all nine successful calls. Counts below
are the bridge's recorded prompt/completion totals; they do not separately
qualify cache or reasoning-token breakdowns.

| Provider | Served model | Label | Prompt tokens | Completion tokens | Total tokens |
| --- | --- | --- | ---: | ---: | ---: |
| `anthropic` | `claude-sonnet-5-5` | `smoke.text` | 30 | 4 | 34 |
| `anthropic` | `claude-sonnet-5-5` | `smoke.json` | 450 | 62 | 512 |
| `anthropic` | `claude-sonnet-5-5` | `smoke.tool` | 400 | 49 | 449 |
| `zai` | `glm-5.3` | `smoke.text` | 23 | 23 | 46 |
| `zai` | `glm-5.3` | `smoke.json` | 29 | 120 | 149 |
| `zai` | `glm-5.3` | `smoke.tool` | 175 | 151 | 326 |
| `moonshot` | `kimi-k3` | `smoke.text` | 106 | 30 | 136 |
| `moonshot` | `kimi-k3` | `smoke.json` | 159 | 46 | 205 |
| `moonshot` | `kimi-k3` | `smoke.tool` (separate retry) | 193 | 1931 | 2124 |

## Failed attempts and limits

- The original Moonshot credential returned HTTP 401 at international and
  regional model-list endpoints, and at the international bridge request.
  The operator reported a copy/paste error and replaced the key.
- The corrected key passed international model listing. `kimi-k2.5` returned
  HTTP 404; a subsequent smoke used the advertised `kimi-k3` model.
- Kimi K3 text and JSON succeeded. Its first tool request returned HTTP 429.
  A separate tool-only retry with the same model and settings succeeded.
- No successful-usage receipt was produced for these failed calls. Their token
  usage is unknown, not zero.
- A separate offline adapter-test invocation was interrupted while waiting on
  its first mocked request. It is not counted as a passing validation run.
- These records qualify only basic live connectivity and the three small output
  paths. They do not qualify every reasoning mode, sustained throughput,
  full workflows or scientific performance.
