"""
Time utility MCP tools.

Ported from mcp-simple-timeserver (https://github.com/andybrandt/mcp-simple-timeserver)
so that a single MCP server deployment can cover both memory and basic time queries.

Three stateless tools:
- handle_get_current_time: current time in a specified IANA timezone
- handle_get_utc:           current UTC time
- handle_get_server_time:   current local time on the server host

Standard library only (datetime, zoneinfo) — no external dependencies.
"""

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp import types

logger = logging.getLogger(__name__)


def _format_utc_offset(dt: datetime) -> str | None:
    offset = dt.utcoffset()
    if offset is None:
        return None
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    hours, rem = divmod(abs(total_seconds), 3600)
    minutes = rem // 60
    return f"{sign}{hours:02d}:{minutes:02d}"


def _build_payload(dt: datetime, tz_label: str) -> dict:
    return {
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": tz_label,
        "utc_offset": _format_utc_offset(dt),
        "iso": dt.isoformat(),
        "timestamp": dt.timestamp(),
    }


def _text(payload: dict) -> List[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]


def _error(message: str) -> List[types.TextContent]:
    return [types.TextContent(type="text", text=f"Error: {message}")]


async def handle_get_current_time(arguments: dict) -> List[types.TextContent]:
    """Return the current time in the requested IANA timezone."""
    try:
        tz_name = arguments.get("timezone")
        if not tz_name or not isinstance(tz_name, str):
            return _error(
                "'timezone' argument is required (IANA name, e.g. 'Asia/Seoul' or 'UTC')."
            )

        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            return _error(
                f"Unknown timezone '{tz_name}'. Use an IANA timezone name (e.g. 'America/New_York')."
            )

        now = datetime.now(tz)
        return _text(_build_payload(now, tz_name))
    except Exception as e:
        logger.error(f"Error in get_current_time: {e}")
        logger.error(traceback.format_exc())
        return _error(f"Failed to get current time: {e}")


async def handle_get_utc(arguments: dict) -> List[types.TextContent]:
    """Return the current time in UTC."""
    try:
        now = datetime.now(timezone.utc)
        return _text(_build_payload(now, "UTC"))
    except Exception as e:
        logger.error(f"Error in get_utc: {e}")
        logger.error(traceback.format_exc())
        return _error(f"Failed to get UTC time: {e}")


async def handle_get_server_time(arguments: dict) -> List[types.TextContent]:
    """Return the current local time on the server host."""
    try:
        now = datetime.now().astimezone()
        tz_label = now.tzname() or "local"
        return _text(_build_payload(now, tz_label))
    except Exception as e:
        logger.error(f"Error in get_server_time: {e}")
        logger.error(traceback.format_exc())
        return _error(f"Failed to get server time: {e}")
