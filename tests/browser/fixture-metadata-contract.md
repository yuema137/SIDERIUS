# Browser fixture startup metadata

Scope: streaming startup records for Python console and offline-provider fixtures
in tests/browser. Production console output and completed-command JSON interfaces
(setup, headless, recover, preparation and inspection) are outside this protocol.

Owners: fixture_metadata.py::emit_metadata serializes a mapping to one flushed
stdout line with the exact prefix `SIDERIUS_BROWSER_METADATA ` and a JSON object.
fixture_metadata.mjs::waitForMetadata consumes that record from a child process.
Payload keys remain fixture-specific (`origin`, `token`, `endpoint`, source paths,
expected results); the transport does not infer readiness from any payload keys.
Attach the reader immediately after spawning, before awaiting other work.

The reader ignores all unmarked lines, including valid JSON. Node readline
handles chunk boundaries and CRLF. A marked malformed JSON value or non-object
payload rejects the startup promise. EOF, spawn failure, process close and startup
timeout also reject it. The default timeout is 30 seconds; existing explicit
harness deadlines remain caller options. Successful metadata receipt is not an
HTTP readiness probe; existing harness readiness checks remain responsible.

On success or failure, remove reader/process listeners and clear its timer. Keep
stdout draining so later logs cannot block the server. The caller owns process
termination and stderr diagnostics. Transport errors do not echo payloads because
metadata may contain fixture authentication tokens.

Validation: fixture_metadata_test.mjs exercises noisy stdout, an unmarked JSON
decoy, a chunked CRLF record, malformed JSON, non-object JSON, EOF, timeout, spawn
failure, listener cleanup and the Python emitter. All migrated witnesses must
also run against their corresponding emitters; no UI assertions are weakened.
