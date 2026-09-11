# Environment diagnostics

These opt-in source-checkout tools diagnose local environment setup. They are
not packaged entry points, offline smoke tests, or scientific qualification.

`check_agent_environment.py` loads the checkout-root `.env` without overriding
values already exported in the environment. It checks OpenAI, Gemini, and
DeepSeek in that order. For every configured provider it lists available models
and sends the prompt `say ok`, so running it can make network requests and incur
provider usage. Missing keys and provider errors are printed as failures.

Run it from any working directory with this checkout's interpreter:

```bash
/path/to/SIDERIUS/.venv/bin/python \
    /path/to/SIDERIUS/scripts/diagnostics/check_agent_environment.py
```

The former command was `.venv/bin/python env_validation/test_agent_env.py`.
That path is retired; there is no forwarding shim. The diagnostic currently
prints all, partial, or critical failure summaries but exits zero even when no
provider succeeds. Treat its printed summary—not the exit status—as the result.

Tests under `tests/unit/scripts/test_agent_environment_diagnostic.py` replace
the provider boundary and use synthetic dotenv files; they never read the
checkout `.env` or make provider requests.
