"""The existing local operation control-record byte envelope and encoding."""

from pydantic import BaseModel

JSON_LIMIT = 4 * 1024 * 1024


class ControlOverflow(ValueError):
    """Encoded control bytes exceed the existing reader envelope."""


def encode_control(model: BaseModel) -> bytes:
    payload = (model.model_dump_json(indent=2) + "\n").encode()
    if len(payload) > JSON_LIMIT:
        raise ControlOverflow("JSON record exceeds 4 MiB")
    return payload
