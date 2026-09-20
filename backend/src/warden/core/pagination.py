from __future__ import annotations

import base64
import binascii
import json

from pydantic import BaseModel, Field

from warden.core.errors import WardenError

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class InvalidCursorError(WardenError):
    code = "invalid_cursor"


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = Field(
        default=None, description="Opaque cursor for the next page, absent on the last page."
    )


def encode_cursor(value: str | int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"k": value}).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> str | int | None:
    if not cursor:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError):
        raise InvalidCursorError("cursor is malformed") from None
    value = payload.get("k") if isinstance(payload, dict) else None
    if not isinstance(value, str | int):
        raise InvalidCursorError("cursor is malformed")
    return value


def decode_int_cursor(cursor: str | None) -> int | None:
    value = decode_cursor(cursor)
    if value is not None and not isinstance(value, int):
        raise InvalidCursorError("cursor is malformed")
    return value


def decode_str_cursor(cursor: str | None) -> str | None:
    value = decode_cursor(cursor)
    if value is not None and not isinstance(value, str):
        raise InvalidCursorError("cursor is malformed")
    return value
