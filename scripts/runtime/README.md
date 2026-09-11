# `scripts/runtime/`

Maintained deterministic bookkeeping and runtime utility CLIs. Replay metadata
and plan operations are supported here; effectful runtime replay still has the
known #431 task-profile transport limitation. The historical
`runtime_campaign.py` remains outside this grouping pending paired experiment
preservation work; no campaign semantics are changed here.
