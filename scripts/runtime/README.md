# `scripts/runtime/`

Maintained deterministic bookkeeping and runtime utility CLIs. Replay metadata
and plan operations are supported here; effectful runtime replay still has the
known #431 task-profile transport limitation. The former
`scripts/runtime_campaign.py` was a preserved historical driver and
is retired from the infra checkout; its exact source is archived by the paired
experiment repository. Generic campaign-control and probe functionality
remains owned by the maintained modules listed in this directory.
