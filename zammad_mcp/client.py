"""Minimal read-only client for the Zammad API.

All methods are read-only GET requests. Authentication uses a bearer token.
"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "https://support.cc.in2p3.fr"
TIMEOUT = 15.0


class ZammadError(Exception):
    """Raised when the Zammad API returns an error or cannot be reached."""


class ZammadClient:
    """Thin wrapper around the Zammad REST API (read-only)."""

    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ZammadError(f"Timeout contacting Zammad at {url}") from exc
        except httpx.HTTPError as exc:
            raise ZammadError(f"Network error contacting Zammad: {exc}") from exc

        if resp.status_code == 401:
            raise ZammadError("Authentication failed: check ZAMMAD_TOKEN")
        if resp.status_code == 403:
            raise ZammadError("Forbidden: token lacks permission for this resource")
        if resp.status_code == 404:
            raise ZammadError(f"Not found: {path}")
        if resp.status_code >= 400:
            raise ZammadError(f"Zammad API error {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def search_tickets(self, query: str, limit: int | None = None) -> dict[str, Any]:
        """Search tickets using Zammad query syntax."""
        params: dict[str, Any] = {"query": query}
        if limit is not None:
            params["limit"] = limit
        return self._get("/api/v1/tickets/search", params)

    def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        """Return the full detail of a single ticket."""
        return self._get(f"/api/v1/tickets/{ticket_id}")

    def get_ticket_articles(self, ticket_id: int) -> list[dict[str, Any]]:
        """Return all articles (messages/comments) of a ticket."""
        return self._get(f"/api/v1/ticket_articles/by_ticket/{ticket_id}")

    def get_user(self, user_id: int) -> dict[str, Any]:
        """Return the detail of a single user/agent."""
        return self._get(f"/api/v1/users/{user_id}")

    def search_users(self, query: str, limit: int | None = None) -> dict[str, Any]:
        """Search users using Zammad query syntax."""
        params: dict[str, Any] = {"query": query}
        if limit is not None:
            params["limit"] = limit
        return self._get("/api/v1/users/search", params)

    def list_groups(self) -> list[dict[str, Any]]:
        """Return all groups (queues)."""
        return self._get("/api/v1/groups")

    def get_me(self) -> dict[str, Any]:
        """Return the authenticated user's own profile."""
        return self._get("/api/v1/users/me")

    def close(self) -> None:
        self._client.close()
