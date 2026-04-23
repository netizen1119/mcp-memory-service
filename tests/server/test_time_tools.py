"""Tests for time utility tools ported from mcp-simple-timeserver."""

import json
from datetime import datetime, timezone

import pytest

from mcp_memory_service.tools import time_tools


def _payload(result) -> dict:
    assert len(result) == 1
    assert result[0].type == "text"
    return json.loads(result[0].text)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_utc_returns_utc_payload():
    result = await time_tools.handle_get_utc({})
    payload = _payload(result)

    assert payload["timezone"] == "UTC"
    assert payload["utc_offset"] == "+00:00"
    parsed = datetime.fromisoformat(payload["iso"])
    assert parsed.utcoffset().total_seconds() == 0
    assert isinstance(payload["timestamp"], float)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_time_seoul_offset():
    result = await time_tools.handle_get_current_time({"timezone": "Asia/Seoul"})
    payload = _payload(result)

    assert payload["timezone"] == "Asia/Seoul"
    assert payload["utc_offset"] == "+09:00"
    parsed = datetime.fromisoformat(payload["iso"])
    assert parsed.utcoffset().total_seconds() == 9 * 3600


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_time_utc_alias():
    result = await time_tools.handle_get_current_time({"timezone": "UTC"})
    payload = _payload(result)

    assert payload["timezone"] == "UTC"
    assert payload["utc_offset"] == "+00:00"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_time_invalid_timezone():
    result = await time_tools.handle_get_current_time({"timezone": "Not/AZone"})
    assert len(result) == 1
    assert result[0].text.startswith("Error:")
    assert "Not/AZone" in result[0].text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_time_missing_timezone():
    result = await time_tools.handle_get_current_time({})
    assert result[0].text.startswith("Error:")
    assert "timezone" in result[0].text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_time_non_string_timezone():
    result = await time_tools.handle_get_current_time({"timezone": 42})
    assert result[0].text.startswith("Error:")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_server_time_returns_local():
    result = await time_tools.handle_get_server_time({})
    payload = _payload(result)

    assert payload["timezone"]
    # Server time must be tz-aware and parseable.
    parsed = datetime.fromisoformat(payload["iso"])
    assert parsed.tzinfo is not None
    # utc_offset string must match the parsed offset.
    expected_seconds = int(parsed.utcoffset().total_seconds())
    sign = "+" if expected_seconds >= 0 else "-"
    h, rem = divmod(abs(expected_seconds), 3600)
    m = rem // 60
    assert payload["utc_offset"] == f"{sign}{h:02d}:{m:02d}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_payload_datetime_string_format():
    """The human-readable 'datetime' field must be YYYY-MM-DD HH:MM:SS."""
    result = await time_tools.handle_get_utc({})
    payload = _payload(result)
    # Raises ValueError if the format is wrong.
    datetime.strptime(payload["datetime"], "%Y-%m-%d %H:%M:%S")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timestamp_roughly_matches_iso():
    """timestamp and iso fields must refer to the same instant."""
    result = await time_tools.handle_get_utc({})
    payload = _payload(result)
    parsed = datetime.fromisoformat(payload["iso"])
    assert abs(parsed.timestamp() - payload["timestamp"]) < 1.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timestamp_consistent_across_timezones():
    """Same moment queried via UTC vs Asia/Seoul must produce near-equal epoch values."""
    utc_payload = _payload(await time_tools.handle_get_utc({}))
    seoul_payload = _payload(
        await time_tools.handle_get_current_time({"timezone": "Asia/Seoul"})
    )
    # Same wall-clock instant, different zones — timestamps should be within a second.
    assert abs(utc_payload["timestamp"] - seoul_payload["timestamp"]) < 2.0
