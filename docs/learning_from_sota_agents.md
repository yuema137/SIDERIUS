# Learning from SOTA Agent Frameworks: Architecture Insights for SIDERIUS

## Sources

1. [MLEvolve](https://github.com/InternScience/MLEvolve) — #1 on MLE-bench. Monte Carlo
   Graph Search with multiple specialized LLM agents for automated ML pipeline optimization.
2. [FM-Agent (Baidu)](https://github.com/baidubce/FM-Agent) — Multi-agent scientific
   research framework with hierarchical coordination and immutable round artifacts.
3. [AI-Build-AI](https://github.com/aibuildai/AI-Build-AI) — #1 on OpenAI MLE-Bench (75
   Kaggle competitions). Tree search over code space with metric-driven pruning.

## Key Takeaways

### 1. Multi-Specialist Agent Decomposition

**MLEvolve pattern**: Draft, Improve, Debug, Evolution, Fusion agents — each with a
focused persona and prompt. The search engine dispatches to the right agent based on
the current node state (root → draft, buggy → debug, success → improve, stagnation → fusion).

**SIDERIUS status**: Our graph already has 5 specialized nodes (interpret, propose,
implement, validate, tune). The tuner is the one that's overloaded — it does planning,
exploration tracking, constraint enforcement, and reflection all in one prompt.

**Future direction**: Break the tuner into sub-agents:
- **Planner agent**: decides WHAT to explore (reads memory, checklist, description)
- **Config agent**: produces the exact JSON config (given the plan)
- **Reflector agent**: analyzes results (already somewhat separate via `brain.reflect()`)
- **Strategy agent**: decides trial/formal mode and data volume

This is compatible with our pluggable infrastructure — each sub-agent follows the
same skill contract. The tuner becomes a mini-orchestrator over these sub-agents.

**Priority**: Medium — the current single-prompt tuner works but will scale poorly
as we add more model types with unique parameters.

---

### 2. Two-Stage Planning: Reason → Commit

**MLEvolve pattern**: The improve agent generates a structured JSON plan first
(which modules to modify, rationale, approach), THEN generates code in a separate
call. The plan constrains the code generation, preventing drift.

**SIDERIUS status**: Our proposal agent already uses this pattern (reasoning call →
commit call). But the tuner's planner does everything in ONE call — reasoning,
hypothesis, trial mode decision, AND full config JSON. The LLM often gets the
reasoning right but the config wrong (e.g., understands the gate vector is important
but doesn't include `static_v` in the JSON).

**Concrete improvement**: Split `brain.plan()` into two calls:
1. **Reasoning call** (free text): "Given the exploration checklist, model description,
   and past results, what are the top 3 parameters to explore next and why? What
   specific values should we try?"
2. **Config call** (strict JSON): "Given your reasoning above, produce the exact
   ExperimentPlan JSON."

The reasoning call forces the LLM to think about under-explored parameters BEFORE
committing to a config. The config call is constrained by the reasoning.

**Priority**: High — this directly addresses the "LLM ignores model-specific
parameters" problem. The reasoning call makes parameter selection explicit and
auditable.

---

### 3. Memory Retrieval Instead of Full History Dump

**MLEvolve pattern**: Uses BM25 + FAISS hybrid search to retrieve only the 2-3 most
relevant past records. Records are stored with plan summaries, code summaries, metrics,
and success/failure labels. The retrieval query is formed from the current context.

**SIDERIUS status**: We dump the ENTIRE experiment history as raw JSON into the prompt.
With 20 rounds, each record containing params, memory fields, timing, file_vector —
this is thousands of tokens. The LLM sees the full history but can't focus on what's
relevant. Important patterns (e.g., "every time we increase width, OOM happens") are
buried in noise.

**Concrete improvement**: Replace raw history dump with structured memory:
1. **Summary stats**: best score, worst score, total experiments, rounds remaining
2. **Parameter coverage table**: what values tried per parameter (the checklist does this)
3. **Top-K records**: only the best N experiments and most recent M experiments as full JSON
4. **Failure patterns**: extracted from error records ("width=64 → OOM 3 times")
5. **Trend analysis**: "score improved from 0.3 to 0.7 over rounds 1-6, plateaued since"

This can be implemented as a `summarize_memory()` function that replaces
`json.dumps(memory_history)` in the prompt builder. No schema changes needed.

**Optional future enhancement**: Use embedding-based retrieval (FAISS) to find
records most relevant to the current exploration direction. E.g., if the LLM
is planning to try `static_v`, retrieve past records that also tried `static_v`.

**Priority**: High — the raw history dump is the main reason our prompt grows
unboundedly and the LLM loses focus on important details.

---

### 4. Context Window Management

**MLEvolve pattern**: Multiple techniques:
- **Truncation**: `trim_long_string(s, threshold=5100, k=2500)` — keep first and last
  2500 chars of long outputs
- **Trajectory summarization**: limit to `max_steps` when showing the path from root
  to current node
- **Data preview capping**: dataset previews capped at 6000 chars
- **Hierarchical memory**: child memory (sibling summaries), parent memory (single
  summary), trajectory memory (step-by-step path)

**SIDERIUS status**: No truncation anywhere. The model description (4340 chars for
gated_fno), config manual (JSON schema), exploration checklist, round context, expert
advice, human advice, and full experiment history all get concatenated into one prompt.

**Concrete improvements**:
- **Move static content to system prompt**: model description, config manual, and
  exploration rules don't change between rounds. Put them in the system prompt (cached
  by the API) instead of the user prompt (re-sent every call).
- **Truncate experiment records**: only include the full JSON for the top-3 and
  most-recent-3 records. Summarize others as one-line entries.
- **Cap file_vector display**: instead of 20 floats, show "weak: files [0,1,2,3],
  strong: files [15,16,17,18,19]" — more actionable, fewer tokens.

**Priority**: Medium — not blocking now, but will become critical as we add more
models and run longer experiments (50+ rounds).

---

### 5. Adaptive Code Generation Strategies

**MLEvolve pattern**: Three code generation modes with fallback chain:
- **Stepwise**: multi-agent pipeline (data → model → training)
- **Diff**: SEARCH/REPLACE patches for minimal changes
- **Base**: full rewrite as single-shot

The system adaptively selects: diff for refinement, stepwise for drafts, base as
fallback when diff fails.

**SIDERIUS relevance**: Our implementor uses reasoning → code (two calls), which is
similar to MLEvolve's planner → coder pattern. We could adopt the diff mode for
the implementor's self-correction loop — instead of regenerating the entire plugin
on retry, generate a targeted patch.

**Priority**: Low — the implementor works well enough with full regeneration.

---

### 6. Stagnation Detection and Cross-Branch Learning

**MLEvolve pattern**: After 6 hours, if score improvement stagnates:
- 30% chance: **Fusion agent** merges techniques from different solution branches
- 70% chance: **Evolution agent** uses trajectory history to evolve

**SIDERIUS relevance**: Our Cross-Exploration Rule is a simpler version of this.
We could add explicit stagnation detection: "if best score hasn't improved by >5%
in the last N rounds, trigger a strategy change." Currently this is implicit in
the LLM's judgment, which is unreliable.

**Priority**: Low — nice to have for long runs but not blocking.

---

## Additional Insights from FM-Agent (Baidu)

### A. Distributed State via Files (Not Chat History)

**FM-Agent pattern**: Uses explicit context files (`CONTEXT.md`, `problem.md`,
`round-N-summary.md`) read by every agent before acting. State is **on disk**, not
in agent memory. This enables:
- Agent restarts without losing progress
- Distributed execution (agents in different processes/sessions)
- Auditability (all decisions in git)
- Decoupling agent token limits from task complexity

**SIDERIUS status**: We already store outputs as JSON files per node (interpretation,
proposal, etc.) — this is good. But the tuner's planner reads the entire history
in-memory each round. We should standardize on file-based context with explicit
read points.

**Priority**: Low — our current pattern works for the local case, but this is the
right model for distributed execution (e.g., Slurm).

### B. Local Validation Gate Before Expensive Execution

**FM-Agent pattern**: Before submitting any experiment to the cloud, run a mandatory
local validation:
```python
result = run_with_timeout(init.py)
assert result['validity'] == 1
assert result['combined_score'] != 0
assert result['error_info'] == ""
```
This catches bugs locally before consuming GPU/cloud quota.

**SIDERIUS status**: We have `evaluate_resource_skill` which checks VRAM before
training, but no functional smoke test on the actual config. The validator agent
does instantiation + gradient checks, but these run on dummy data (1×64), not the
real config the LLM proposed.

**Concrete improvement**: Before each training round, run the proposed config on
a tiny synthetic batch to catch shape errors, dimension mismatches, or numerical
issues. Faster than waiting for the training subprocess to crash.

**Priority**: Medium — would catch ~30% of failed rounds before they waste GPU time.

### C. Adaptive Config Tuning Based on Signals

**FM-Agent pattern**: The orchestrator monitors evolution signals and adjusts
hyperparameters of the search itself (not the model):

| Signal | Action |
|--------|--------|
| High validity=0 rate | Strengthen prompt constraints |
| Score plateau N rounds | Increase iterations / num_islands |
| High score variance | Lower temperature 0.7 → 0.5 |
| Early convergence | Increase num_islands for diversity |

**SIDERIUS status**: Our tuner has implicit phase transitions (Screening / Refinement /
Solidification) but doesn't dynamically adjust based on signals. The progressive
strategy is hardcoded by round percentage, not by score behavior.

**Priority**: Low — nice to have. Phase transition by progress is simpler and works
for single-model tuning.

### D. Snapshot-Per-Round Immutability

**FM-Agent pattern**: Each round saves uniquely-named artifacts (`round-1-best.py`,
`round-2-best.py`, ...) that are never overwritten. Combined with git commits,
this creates a complete audit trail.

**SIDERIUS status**: We already do this — each experiment record is uniquely named
with `exp_id`. The dashboard can replay any historical experiment. ✓

### E. Strict Role Boundaries (No Cross-Cutting Concerns)

**FM-Agent pattern**: Each agent has explicit ownership and scope. Model Developer
owns `init.py` only — Evaluator never modifies it. Evaluator owns metrics only —
never tweaks scoring logic. Prevents accidental score inflation and circular feedback.

**SIDERIUS status**: We follow this — each node has a Pydantic input/output schema
that's the only contract. Nodes can't read each other's internal state. ✓

---

## Additional Insights from AI-Build-AI

### F. Tree Search Over Linear Iteration (Major Architectural Difference)

**AI-Build-AI pattern**: Each hyperparameter config is a node in a solution tree.
Multiple branches evolve in parallel. Metric-based pruning discards underperforming
branches while guiding exploration toward promising ones. This is **fundamentally
different** from sequential round-by-round tuning.

**SIDERIUS status**: We do **linear sequential** tuning. Round N+1 only sees round N's
result. We can't backtrack to a promising earlier branch and explore it differently.
If round 5 was great but round 6 took a wrong turn, rounds 7-20 are stuck in the
wrong region.

**Concrete improvement**: This would be a major refactor. But the simpler version is
**branch-and-revisit**: at the start of each phase (Refinement, Solidification),
the LLM should explicitly select which past experiment to build from, not just
the most recent one. The proposal could include `parent_exp_id` to root the next
experiment from any past success.

**Priority**: High (architectural). This is the biggest missing piece. Sequential
tuning has a fundamental local-minimum problem that no amount of prompt engineering
can fix.

### G. Code-as-First-Class-Object with Tree Branching

**AI-Build-AI pattern**: Each tree node IS a full Python script. The LLM generates
patches that modify previous solutions. Verification is through actual execution,
not LLM self-evaluation. This makes the solution space concrete and searchable.

**SIDERIUS relevance**: For our tuner, the analog is treating each experiment's
**config** as a node, and proposing **diffs** rather than full configs. Currently
we always generate the full config from scratch each round, which loses incremental
context. With diff-based config evolution, the LLM could say "take exp_005 and
change static_v[0:16]=0" — much more focused than reproducing the entire JSON.

**Priority**: Medium — combines naturally with branch-and-revisit (point F).

### H. Skills Registry for Cross-Task Knowledge Transfer

**AI-Build-AI pattern**: `/advise` and `/retrospective` commands maintain a skills
registry across runs. After every experiment, knowledge is automatically captured
(failure modes, working configs, troubleshooting tips). The next experiment
queries this registry before planning.

**SIDERIUS status**: Each run is independent. Insights from yesterday's punet tuning
don't inform today's gated_fno tuning. The interpretation agent reads multiple model
results but only within a single workflow iteration.

**Concrete improvement**: Build a persistent "research memory" that accumulates
across runs. Could be as simple as:
- After each successful tuner run, write a summary to `research_memory/{model_type}/{run_name}.md`
- Before starting a new run, the planner reads the most relevant past summaries
  (filter by model_type or by parameter focus area)

**Priority**: Medium — high long-term value, low short-term urgency.

### I. Specificity Over Vagueness in Memory

**AI-Build-AI insight**: Generic memory entries like "pruning experiments" are
useless. Specific entries like "GRPO training with external vLLM server on
gemma-3-12b-it" are valuable. Failure documentation > success stories.

**SIDERIUS status**: Our `memory_update` field in records is often vague
("try different hyperparameters"). The reflector should be prompted to write
concrete, actionable lessons.

**Priority**: Low — easy fix, just tighten the reflector prompt.

---

## Implementation Roadmap

| Change | Priority | Effort | Impact | Source |
|--------|----------|--------|--------|--------|
| Two-stage planning (reason → commit) | High | 1 day | Fixes parameter exploration blind spots | MLEvolve |
| Memory summarization (replace raw dump) | High | 1 day | Reduces prompt size, improves focus | MLEvolve |
| Branch-and-revisit (parent_exp_id) | High | 2 days | Escapes local minima in linear tuning | AI-Build-AI |
| Move static content to system prompt | Medium | 2 hours | Better API caching, cleaner prompts | MLEvolve |
| Truncate experiment records to top-K | Medium | 2 hours | Reduces prompt size | MLEvolve |
| Local validation gate (smoke test config) | Medium | 4 hours | Catches ~30% of failed rounds early | FM-Agent |
| Persistent research memory (cross-run) | Medium | 1 day | Knowledge transfer across runs | AI-Build-AI |
| Break tuner into sub-agents | Medium | 3 days | Better separation of concerns | MLEvolve, FM-Agent |
| Diff-based config evolution | Medium | 1 day | More focused incremental changes | AI-Build-AI |
| Diff-based implementor correction | Low | 1 day | Faster self-correction | MLEvolve |
| Explicit stagnation detection | Low | 4 hours | Better long-run behavior | MLEvolve, FM-Agent |
| Adaptive search hyperparameters | Low | 1 day | Auto-adjust temperature/iterations | FM-Agent |
| Tighter reflector prompts (specificity) | Low | 1 hour | More actionable memory entries | AI-Build-AI |

## Top 3 Recommendations

If we implement only three things from this list:

1. **Branch-and-revisit** (AI-Build-AI). Sequential tuning is fundamentally limited.
   Adding `parent_exp_id` to the proposal lets the LLM build from any past success,
   not just the most recent. This single change would have the biggest impact on
   long-run quality.

2. **Two-stage planning** (MLEvolve). Splitting `brain.plan()` into reason → commit
   forces the LLM to think about under-explored parameters before committing to a
   config. Directly addresses the "ignores model-specific parameters" problem.

3. **Memory summarization** (MLEvolve). Replace the raw history dump with a
   structured summary (best/worst, parameter coverage, top-K records, failure
   patterns). Reduces prompt size and improves LLM focus on what matters.
