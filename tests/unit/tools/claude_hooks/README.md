# tests/unit/tools/claude_hooks

Hook tests pin auto-failsafe continuation, context-state persistence, and
precompact/stop guards using temporary fixture repositories; they do not invoke
Claude or a remote service.

## Source and route


## Focused route

`.venv/bin/python -m pytest tests/unit/tools/claude_hooks/test_auto_failsafe.py -q`

Owner: `src/tools/claude_hooks/`; see the [tools map](../README.md).
