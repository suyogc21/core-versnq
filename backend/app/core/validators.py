"""Small reusable field validators."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def valid_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown timezone (use an IANA name like Asia/Kolkata)") from None
    return value
