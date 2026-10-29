"""Outer ASGI admission, before FastAPI business parsing or body buffering."""

import hmac
import json
import logging

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .models import ConsoleConfig

BODY_LIMIT = 256 * 1024
HEADERS = [
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (
        b"content-security-policy",
        b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    ),
]


class RequestBoundary:
    def __init__(self, app: ASGIApp, *, config: ConsoleConfig, token: str):
        self.app, self.config, self.token = app, config, token.encode("ascii")
        self.hosts = {config.browser_origin.removeprefix("http://"), f"127.0.0.1:{config.port}"}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def secured_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                message = {**message, "headers": [*message.get("headers", []), *HEADERS]}
            await send(message)

        async def refuse(status: int, code: str, message: str) -> None:
            payload = json.dumps({"error": {"code": code, "message": message}}).encode()
            await secured_send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(payload)).encode()),
                    ],
                }
            )
            await secured_send({"type": "http.response.body", "body": payload})

        async def downstream(receiver: Receive) -> None:
            try:
                await self.app(scope, receiver, secured_send)
            except Exception as error:
                logging.getLogger(__name__).error(
                    "Console request failed (%s)", type(error).__name__
                )
                if not response_started:
                    await refuse(500, "internal", "local console could not complete the request")

        headers: dict[bytes, list[bytes]] = {}
        for name, value in scope["headers"]:
            headers.setdefault(name.lower(), []).append(value)
        forwarded = b"forwarded" in headers or any(k.startswith(b"x-forwarded-") for k in headers)
        if (
            len(headers.get(b"host", [])) != 1
            or headers[b"host"][0].decode("latin1") not in self.hosts
            or forwarded
        ):
            if (
                len(headers.get(b"host", [])) == 1
                and not forwarded
                and scope["method"] in {"GET", "HEAD"}
                and not scope["path"].startswith("/api/")
                and any(
                    item.split(b";", 1)[0].strip().lower() == b"text/html"
                    for value in headers.get(b"accept", [])
                    for item in value.split(b",")
                )
            ):
                response = PlainTextResponse(
                    "Request host is not allowed.\n"
                    f"Open http://{self.config.bind_host}:{self.config.port}/\n",
                    status_code=403,
                )
                await response(scope, receive, secured_send)
                return
            await refuse(403, "host", "request host is not allowed")
            return
        api = scope["path"].startswith("/api/")
        if not api:
            await downstream(receive)
            return
        auth = headers.get(b"authorization", [])
        if len(auth) != 1 or not hmac.compare_digest(auth[0], b"Bearer " + self.token):
            await refuse(401, "authentication", "enter the local access token")
            return
        mutation = scope["method"] not in {"GET", "HEAD", "OPTIONS"}
        origins = headers.get(b"origin", [])
        if (mutation or origins) and origins != [self.config.browser_origin.encode("ascii")]:
            await refuse(403, "origin", "request origin is not allowed")
            return
        if not mutation:
            await downstream(receive)
            return
        types = headers.get(b"content-type", [])
        if len(types) != 1 or types[0].split(b";", 1)[0].strip().lower() != b"application/json":
            await refuse(415, "content_type", "mutations require application/json")
            return
        payload = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(payload) + len(chunk) > BODY_LIMIT:
                await refuse(413, "body_limit", "request body exceeds 256 KiB")
                return
            payload.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(payload), "more_body": False}

        await downstream(replay)
