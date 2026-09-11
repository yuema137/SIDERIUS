# `scripts/runtime/`

Maintained deterministic bookkeeping and runtime utility CLIs. Replay metadata
and plan operations are supported here; effectful campaign execution remains
the #431 boundary and is not enabled or redesigned. The historical
`runtime_campaign.py` remains outside this grouping pending paired experiment
preservation work; no campaign semantics are changed here.
