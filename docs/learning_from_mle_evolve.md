# Learning from MLEvolve: Architecture Insights for SIDERIUS

## Source

[MLEvolve](https://github.com/InternScience/MLEvolve) — #1 on MLE-bench. Uses Monte Carlo
Graph Search with multiple specialized LLM agents for automated ML pipeline optimization.

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

## Implementation Roadmap

| Change | Priority | Effort | Impact |
|--------|----------|--------|--------|
| Two-stage planning (reason → commit) | High | 1 day | Fixes parameter exploration blind spots |
| Memory summarization (replace raw dump) | High | 1 day | Reduces prompt size, improves focus |
| Move static content to system prompt | Medium | 2 hours | Better API caching, cleaner prompts |
| Truncate experiment records to top-K | Medium | 2 hours | Reduces prompt size |
| Break tuner into sub-agents | Medium | 3 days | Better separation of concerns |
| Diff-based implementor correction | Low | 1 day | Faster self-correction |
| Explicit stagnation detection | Low | 4 hours | Better long-run behavior |
