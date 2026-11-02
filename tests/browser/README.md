# Browser witnesses

Most scripts exercise the console in a real browser using local Python fixtures.
The fixtures supply temporary projects and offline responses; no real provider or
GPU launch is needed.

Start from an installed development checkout (`uv sync --group dev --frozen`).
Set `EDITOR_PYTHON` to that checkout's `.venv/bin/python`,
`CONSOLE_PLAYWRIGHT_MODULE` to the installed Playwright module, and
`CONSOLE_BROWSER_EXECUTABLE` to Chromium. Scripts that save screenshots also need
`CONSOLE_EVIDENCE_DIR`, a fresh output directory. Check the selected script for
additional prerequisites; some capture scripts require a clean committed checkout.

Run a selected witness, for example `node tests/browser/circuit_ports.mjs`.
Exit status zero means its assertions passed; many witnesses also print `PASS`.
Screenshots are supporting evidence; assertions establish the result.

Fixture startup logs may appear before the server address. The shared metadata
reader waits for an explicitly marked record, so logs do not interrupt startup.
When adding a fixture, use the producer and reader described in the
[startup protocol](fixture-metadata-contract.md). The protocol regression witness
is `fixture_metadata_test.mjs` and needs only Node and `EDITOR_PYTHON`.

The advice retry witness needs only Node and this checkout’s `.venv/bin/python`:
run `node --test tests/browser/loop_resume_advice.mjs` after syncing the environment.
It executes the shipped controller against an in-memory page and API, and checks
its whitespace handling against Python. A passing run reports 39 passed tests;
it does not exercise browser rendering.
