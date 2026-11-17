"""Read-only MCP server exposing the Zammad API.

Two transports are supported:

    stdio            for local hosts such as opencode (default, unchanged behavior)
    streamable-http  for remote MCP clients such as Mistral connectors

Configuration (environment variables):
    ZAMMAD_TOKEN         required, the Zammad API bearer token
    ZAMMAD_BASE_URL      optional, defaults to https://support.cc.in2p3.fr
    ZAMMAD_MCP_TRANSPORT optional, 'stdio' (default) or 'streamable-http'
    ZAMMAD_MCP_HOST      optional, bind address for streamable-http, default 127.0.0.1
    ZAMMAD_MCP_PORT      optional, bind port for streamable-http, default 8000
    ZAMMAD_MCP_API_TOKEN optional but strongly recommended when exposing the
                         HTTP endpoint: clients must present it as a bearer
                         token on every request
"""

from __future__ import annotations

import hmac
import json
import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from zammad_mcp.client import DEFAULT_BASE_URL, ZammadClient, ZammadError

TOKEN_ENV = "ZAMMAD_TOKEN"
BASE_URL_ENV = "ZAMMAD_BASE_URL"
TRANSPORT_ENV = "ZAMMAD_MCP_TRANSPORT"
HOST_ENV = "ZAMMAD_MCP_HOST"
PORT_ENV = "ZAMMAD_MCP_PORT"
API_TOKEN_ENV = "ZAMMAD_MCP_API_TOKEN"
SEARCH_LIMIT = 100

mcp = MCPServer("zammad")


def _get_client() -> ZammadClient:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise ZammadError(f"{TOKEN_ENV} environment variable is not set")
    base_url = os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL)
    return ZammadClient(token, base_url)


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _search_assets(data: Any, asset_key: str) -> list[dict[str, Any]]:
    """Extract the list of records from a Zammad search response.

    Zammad changed the search response format in 6.5. We support every shape
    the API can return so the server keeps working across versions:

    * flat list (default since 6.5): ``[{...}, {...}]``
    * ``full=true`` / legacy: ``{"assets": {<asset_key>: {id: {...}}}}``
    * ``full=true`` with ``record_ids``: ``{"record_ids": [...], "assets": {...}}``
    """
    if isinstance(data, list):
        return list(data)
    if not isinstance(data, dict):
        return []
    assets = data.get("assets", {})
    if isinstance(assets, dict):
        records = assets.get(asset_key, {})
        if isinstance(records, dict):
            return list(records.values())
        if isinstance(records, list):
            return records
    # Fall back to a top-level list of ids (e.g. {"tickets": [1, 2]}).
    for key in (asset_key.lower() + "s", asset_key.lower()):
        if isinstance(data.get(key), list):
            return list(data[key])
    return []


@mcp.tool()
def search_tickets(query: str) -> str:
    """Search Zammad tickets using Zammad query syntax, e.g. 'group.id: 44 AND state.id: 2'.

    Returns matching tickets as JSON. Results are capped at 100; the response
    includes a 'truncated' flag when more results exist.
    """
    client = _get_client()
    try:
        data = client.search_tickets(query, limit=SEARCH_LIMIT + 1)
    finally:
        client.close()
    tickets = _search_assets(data, "Ticket")
    truncated = len(tickets) > SEARCH_LIMIT
    tickets = tickets[:SEARCH_LIMIT]
    return _dump({"count": len(tickets), "truncated": truncated, "tickets": tickets})


@mcp.tool()
def get_ticket(ticket_id: int) -> str:
    """Return the full detail of a single Zammad ticket by its numeric id."""
    client = _get_client()
    try:
        data = client.get_ticket(ticket_id)
    finally:
        client.close()
    return _dump(data)


@mcp.tool()
def get_ticket_articles(ticket_id: int) -> str:
    """Return all articles (messages/comments) of a Zammad ticket by its numeric id."""
    client = _get_client()
    try:
        data = client.get_ticket_articles(ticket_id)
    finally:
        client.close()
    return _dump(data)


@mcp.tool()
def get_user(user_id: int) -> str:
    """Return the detail of a single Zammad user/agent by its numeric id."""
    client = _get_client()
    try:
        data = client.get_user(user_id)
    finally:
        client.close()
    return _dump(data)


@mcp.tool()
def search_users(query: str) -> str:
    """Search Zammad users using Zammad query syntax, e.g. 'login: mainetti'.

    Returns matching users as JSON. Results are capped at 100; the response
    includes a 'truncated' flag when more results exist.
    """
    client = _get_client()
    try:
        data = client.search_users(query, limit=SEARCH_LIMIT + 1)
    finally:
        client.close()
    users = _search_assets(data, "User")
    truncated = len(users) > SEARCH_LIMIT
    users = users[:SEARCH_LIMIT]
    return _dump({"count": len(users), "truncated": truncated, "users": users})


@mcp.tool()
def list_groups() -> str:
    """Return all Zammad groups (queues) as JSON."""
    client = _get_client()
    try:
        data = client.list_groups()
    finally:
        client.close()
    return _dump(data)


@mcp.tool()
def get_me() -> str:
    """Return the profile of the authenticated Zammad user (the token owner)."""
    client = _get_client()
    try:
        data = client.get_me()
    finally:
        client.close()
    return _dump(data)


def _bearer_auth(app: Any, api_token: str) -> Any:
    """Wrap an ASGI app: require 'Authorization: Bearer <api_token>' except on /healthz."""

    async def wrapped(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope["path"] == "/healthz" or _authorized(scope, api_token):
            await app(scope, receive, send)
            return
        from starlette.responses import PlainTextResponse

        response = PlainTextResponse("Unauthorized", status_code=401)
        await response(scope, receive, send)

    return wrapped


def _authorized(scope: Any, api_token: str) -> bool:
    for key, value in scope.get("headers", []):
        if key == b"authorization" and hmac.compare_digest(value.decode(), f"Bearer {api_token}"):
            return True
    return False


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def healthz(request: Any) -> Any:
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok"})


def _serve_http() -> None:
    import uvicorn

    api_token = os.environ.get(API_TOKEN_ENV, "")
    if not api_token:
        raise SystemExit(
            f"{API_TOKEN_ENV} is required for streamable-http: "
            "the endpoint carries your Zammad data and must not be exposed without authentication"
        )
    host = os.environ.get(HOST_ENV, "127.0.0.1")
    port = int(os.environ.get(PORT_ENV, "8000"))
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host=host,
    )
    uvicorn.run(_bearer_auth(app, api_token), host=host, port=port)


def main() -> None:
    transport = os.environ.get(TRANSPORT_ENV, "stdio")
    if transport == "streamable-http":
        _serve_http()
    elif transport == "stdio":
        mcp.run(transport="stdio")
    else:
        raise SystemExit(
            f"Unknown {TRANSPORT_ENV}={transport!r}: expected 'stdio' or 'streamable-http'"
        )


if __name__ == "__main__":
    main()
