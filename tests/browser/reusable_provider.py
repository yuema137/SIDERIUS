"""Loopback-only deterministic OpenAI-compatible provider for offline browser evidence."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from tests.unit.tools.candidate_worker.test_native import Provider


def provider(root: Path) -> None:
    (root / "provider-calls.jsonl").write_text("")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            model = body["model"]
            reject = (root / "reject").exists()
            # Persist call identity only, never prompts, headers or credentials.
            with (root / "provider-calls.jsonl").open("a") as stream:
                stream.write(json.dumps({"model": model, "reject": reject}) + "\n")
            if model == "offline-review":
                # Leave a bounded window to close browser/server during native work.
                deadline = time.monotonic() + 45
                while (root / "hold-review").exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert not (root / "hold-review").exists(), "browser did not release fake response"
            fake = Provider()
            fake.reject = reject
            if not body.get("response_format"):
                content = fake.generate_text("", "")
            else:
                label = {
                    "offline-implement": "implementor.code",
                    "offline-review": "validator.code_review",
                }.get(model, "proposal")
                content = json.dumps(fake.generate("", "", label=label))
            payload = json.dumps(
                {
                    "id": str(uuid4()),
                    "object": "chat.completion",
                    "created": 0,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"endpoint": f"http://127.0.0.1:{server.server_port}/v1"}), flush=True)
    server.serve_forever()
