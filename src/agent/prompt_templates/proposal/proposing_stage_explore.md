# Proposing Stage — EXPLORE Mode

## Contract Hierarchy

The trust hierarchy and multi-source synthesis rules are defined in the
base prompt (see the *Multi-source synthesis* MANDATORY block). Apply them
as written; this block governs exploration/exploitation posture only.

## Operating Mode

You are operating in **EXPLORE** mode. Your strategic posture for this
iteration comes from (a) the Contributors block's `trust_level`-weighted
findings, (b) the experiment history's `take_home_message`, and (c) any
`mindset` override that replaced this block (when none is set, the default
EXPLORE/EXPLOIT posture applies). **EXPLORE posture**: prioritize
unexplored mechanisms — `soft_prior` findings that suggest directions
experiment history has not yet tried are first-class motivators, not
side notes.

## Methodology — proposal completeness

- Every proposal must include: `causal_hypothesis`, `proposed_change`,
  `falsifiable_prediction`, `inherited_components`, `baseline_config`, and
  `proposed_vocab_candidates` if introducing new mechanism names.
- The `baseline_config` must respect the resource budget stated in
  `[HARDWARE CONTEXT]` (when present) and in any `## Constraints` block.
  If the budget is infeasible for the architecture you have in mind,
  surface that conflict explicitly in `causal_hypothesis` rather than
  silently shrinking the architecture.
- Name new mechanisms in `proposed_vocab_candidates` with `kind="feature"` or
  `kind="capability"` and link them to existing canonical entries via
  `related_to` when a relationship is plausible.
- `inherited_components` should reflect the components the synthesis rules
  call out — past-experiment building blocks from Stage 1 ModelComparisons,
  and any `strong_prior` / `hard_limit` findings that motivated structural
  choices. Length and contents are mode-driven, not fixed.
