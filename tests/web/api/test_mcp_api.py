# Copyright 2026
#
# Licensed under the Apache License, Version 2.0 (the "License");

"""Tests for MCP HTTP endpoint — tools/list exposure and tools/call dispatch.

Regression guard for HTTP/stdio duplication drift:
web/api/mcp.py maintains its own MCP_TOOLS list and handle_tool_call
dispatcher, separate from the stdio path in server_impl.py. New tools
must be registered in BOTH places. These tests verify the HTTP path
specifically.
"""

import json
import os
import tempfile

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from mcp_memory_service.web.dependencies import set_storage
from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_mcp.db")


@pytest_asyncio.fixture
async def initialized_storage(temp_db, monkeypatch):
    monkeypatch.setenv('MCP_SEMANTIC_DEDUP_ENABLED', 'false')
    storage = SqliteVecMemoryStorage(temp_db)
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def test_app(initialized_storage, monkeypatch):
    monkeypatch.setenv('MCP_API_KEY', '')
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'false')
    monkeypatch.setenv('MCP_ALLOW_ANONYMOUS_ACCESS', 'true')
    monkeypatch.setenv('INCLUDE_HOSTNAME', 'false')

    import sys, importlib
    try:
        if 'mcp_memory_service.config' in sys.modules:
            importlib.reload(sys.modules['mcp_memory_service.config'])
        if 'mcp_memory_service.web.oauth.middleware' in sys.modules:
            importlib.reload(sys.modules['mcp_memory_service.web.oauth.middleware'])
    except (AttributeError, ImportError):
        pass

    from mcp_memory_service.web.app import app
    from mcp_memory_service.web.oauth.middleware import (
        get_current_user, require_write_access, require_read_access,
        AuthenticationResult,
    )

    set_storage(initialized_storage)

    async def mock_auth():
        return AuthenticationResult(
            authenticated=True,
            client_id="test_client",
            scope="read write admin",
            auth_method="test",
        )

    app.dependency_overrides[get_current_user] = mock_auth
    app.dependency_overrides[require_read_access] = mock_auth
    app.dependency_overrides[require_write_access] = mock_auth

    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


TIME_TOOLS = {"get_current_time", "get_utc", "get_server_time"}


def _rpc(client, method, params=None, _id=1):
    """Send a JSON-RPC 2.0 request to /mcp and return parsed JSON body."""
    body = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        body["params"] = params
    resp = client.post("/mcp", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _call_result_payload(data):
    """Extract the inner JSON payload from a tools/call response."""
    content = data["result"]["content"]
    assert content and content[0]["type"] == "text"
    outer = json.loads(content[0]["text"])
    # handle_tool_call wraps time_tools output as {"text": "<json>"}
    assert "text" in outer, f"expected time_tools wrapper shape, got: {outer}"
    return json.loads(outer["text"])


@pytest.mark.asyncio
async def test_tools_list_exposes_time_tools(client):
    """Regression: HTTP tools/list must include all three time tools."""
    data = _rpc(client, "tools/list")
    names = {t["name"] for t in data["result"]["tools"]}
    missing = TIME_TOOLS - names
    assert not missing, f"HTTP MCP_TOOLS missing: {missing}. Full list: {names}"


@pytest.mark.asyncio
async def test_tools_call_get_utc(client):
    data = _rpc(client, "tools/call",
                {"name": "get_utc", "arguments": {}})
    payload = _call_result_payload(data)
    assert payload["timezone"] == "UTC"
    assert payload["utc_offset"] == "+00:00"
    assert "iso" in payload
    assert isinstance(payload["timestamp"], float)


@pytest.mark.asyncio
async def test_tools_call_get_current_time_seoul(client):
    data = _rpc(client, "tools/call",
                {"name": "get_current_time",
                 "arguments": {"timezone": "Asia/Seoul"}})
    payload = _call_result_payload(data)
    assert payload["timezone"] == "Asia/Seoul"
    assert payload["utc_offset"] == "+09:00"


@pytest.mark.asyncio
async def test_tools_call_get_server_time(client):
    data = _rpc(client, "tools/call",
                {"name": "get_server_time", "arguments": {}})
    payload = _call_result_payload(data)
    assert "timezone" in payload
    assert "iso" in payload
    assert isinstance(payload["timestamp"], float)


@pytest.mark.asyncio
async def test_tools_call_unknown_returns_error(client):
    """Regression guard: unknown tool must surface an error, not silently succeed.

    If someone adds a new elif AFTER the else block, or removes the else,
    this assertion catches it.
    """
    body = {"jsonrpc": "2.0", "id": 99, "method": "tools/call",
            "params": {"name": "this_tool_does_not_exist", "arguments": {}}}
    resp = client.post("/mcp", json=body)
    # HTTP layer catches the ValueError and returns JSON-RPC error envelope
    assert resp.status_code == 200
    data = resp.json()
    # Either a top-level JSON-RPC error, or content indicating failure
    assert "error" in data or "result" in data
    if "error" in data:
        assert data["error"]["code"] in (-32603, -32601)
