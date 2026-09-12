# src/tools/claude_hooks

Optional developer continuity hooks live in `context_state.py`,
`inject_session_memory.py`, `precompact.py`, `stop.py`, `rescue.py`, and
`init_pr_handoff.py`; `templates/` contains their Markdown templates. See
[`docs/development/claude_context_continuity.md`](../../../docs/development/claude_context_continuity.md).
The template filename is the `TEMPLATE_BASENAME` authority in
[`context_state.py`](context_state.py).

See [the parent guide](../README.md) for child ownership and the focused validation route.
