# `proposal/`

Owns the proposer stage resources and task-guidance adapter. The three stages
(`causal_reasoning`, `comparison`, and `proposing`) each have explore and
exploit resources; for example, [`causal_reasoning_stage_explore.md`](causal_reasoning_stage_explore.md)
and its [`_exploit`](causal_reasoning_stage_exploit.md) sibling. The complete
set is visible in this directory; these named files are selected by proposal
rendering and `README.md` is not prompt content.

[`task_blocks.py`](task_blocks.py) validates task-owned prose as
`ProposalTaskBlocks` from [`agent.schemas.proposal`](../../schemas/proposal.py).
It is separate from implementor blocks even though both use
[`../_task_blocks_loader.py`](../_task_blocks_loader.py). Prompt behavior is
covered by [`test_step00_prompt_goldens.py`](../../../../tests/unit/agent/ml_model_proposal_agent/test_step00_prompt_goldens.py)
and the adapter by [`test_step12_pr12a_c7_proposal_blocks.py`](../../../../tests/unit/workflows/test_step12_pr12a_c7_proposal_blocks.py).

Literature reviews retain their separate headings, contributors, and claims.
Contribution IDs, contributor names, and citation source labels stay on one
display line. Labels containing line breaks or starting with a double quote
are displayed as JSON strings. For example, an ID with a newline between `a`
and `b` appears as `"a\nb"`; an ID containing those literal quote and backslash
characters appears as `"\"a\\nb\""`. The two reviews remain distinguishable.
Other single-line labels keep their existing text. Stored labels and evidence
prose, including multiline claims, stay unchanged.

The same rule covers the older Contributors and Expert Context blocks. It
applies to a contributor's name in its `### <name>` heading. It also applies to
an expert-context item's `source`, its `source_ref`, and any `kind` outside the
built-in groups, all shown in its `[KIND] (from ...)` line. For example, a
contributor named `reviewer`, then a newline, then `### forged` appears as
`### "reviewer\n### forged"` instead of opening a second heading. Card fields
such as `coverage`, and item `content`, keep their text. Duplicate items are
still matched on the stored `source_ref` before it is encoded for display.

Data Analysis evidence follows the same rule for its identifiers: the report
reference, each question and finding ID, each method ID on the `Methods:`
line, and each measurement's result key and unit. For example, a finding ID
`f1`, then a newline, then `### forged` appears as
`- Finding "f1\n### forged" [...]` instead of opening a heading. Summaries,
statements, measurement values and descriptions keep their text.
