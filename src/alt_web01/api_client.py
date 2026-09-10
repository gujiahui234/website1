"""HTTP client for the students API server (poc4-students-api).

This module is the single integration point with the external REST API
server that exposes CRUD operations for ``web_db.students``. The server
base URL is derived from the ``API_SERVER_JSON`` environment variable
(the OpenAPI schema URL, e.g. ``http://192.168.220.134:8001/openapi.json``).

The client never uses MCP tool discovery: it calls the RESTful endpoints
directly, as they are stable and already published.
"""

from __future__ import annotations

import threading
from typing import Any

import httpx

#: Per-request timeout for API server calls.
_REQUEST_TIMEOUT_SECONDS = 10.0

#: Page size used when aggregating search results (API hard limit is 100).
_PAGE_SIZE = 100

_client_lock = threading.Lock()
_client: httpx.Client | None = None


class APIClientError(Exception):
    """Raised when the API server returns an error or is unreachable.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status returned by the server, or ``None`` when
            the failure happened before a response was received.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description.
            status_code: HTTP status code associated with the failure.
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _base_url() -> str:
    """Derive the API server base URL from configuration.

    Returns:
        The base URL (scheme + host + port) without a trailing slash.

    Raises:
        APIClientError: If ``API_SERVER_JSON`` is not configured.
    """
    import os

    json_url = os.getenv("API_SERVER_JSON", "").strip()
    if not json_url:
        raise APIClientError(
            "API_SERVER_JSON 未配置，无法定位学生 API 服务器。"
        )
    return json_url.rsplit("/", 1)[0]


def get_api_client() -> httpx.Client:
    """Return the process-wide lazily created API server client.

    Returns:
        A shared :class:`httpx.Client` bound to the API server base URL.
    """
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                base_url=_base_url(),
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        return _client


def close_api_client() -> None:
    """Close the shared API client (used by tests and graceful shutdown)."""
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


def _request(method: str, path: str, *, json_body: Any = None,
             params: dict[str, Any] | None = None) -> httpx.Response:
    """Perform a request against the API server.

    Args:
        method: HTTP method name.
        path: Request path relative to the API base URL.
        json_body: Optional JSON request body.
        params: Optional query parameters.

    Returns:
        The :class:`httpx.Response` returned by the server.

    Raises:
        APIClientError: On network failure or unexpected transport errors.
    """
    try:
        return get_api_client().request(
            method, path, json=json_body, params=params
        )
    except httpx.HTTPError as exc:
        raise APIClientError(f"API 服务器连接失败：{exc}") from exc


def search_students(
    name: str | None = None,
    gender: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Search students with optional filters, aggregating up to ``limit`` rows.

    The upstream API caps a single page at 100 rows, so this helper walks
    through pages with ``offset`` until ``limit`` rows are collected or the
    server reports no more data.

    Args:
        name: Optional substring filter on student name.
        gender: Optional exact-match filter on gender (raw API value).
        limit: Maximum number of rows to return (1-1000).

    Returns:
        A dictionary with ``total`` and ``items`` keys mirroring the API
        response schema.

    Raises:
        APIClientError: On HTTP or network failure.
    """
    limit = max(1, min(limit, 1000))
    items: list[dict[str, Any]] = []
    total = 0
    offset = 0
    while len(items) < limit:
        response = _request(
            "GET",
            "/api/v1/students",
            params={
                "offset": offset,
                "limit": _PAGE_SIZE,
                **({"name": name} if name else {}),
                **({"gender": gender} if gender else {}),
            },
        )
        if response.status_code != 200:
            raise APIClientError(
                "查询学生列表失败。", status_code=response.status_code
            )
        payload = response.json()
        total = int(payload.get("total", 0))
        page = payload.get("items", [])
        items.extend(page)
        offset += _PAGE_SIZE
        if not page or offset >= total:
            break
    return {"total": total, "items": items[:limit]}


def get_student(student_id: int) -> dict[str, Any]:
    """Fetch one student by primary key.

    Args:
        student_id: Primary key of the student record.

    Returns:
        The student payload as returned by the API server.

    Raises:
        APIClientError: With ``status_code`` 404 when the student does not
            exist, or other HTTP/network failures.
    """
    response = _request("GET", f"/api/v1/students/{student_id}")
    if response.status_code != 200:
        message = (
            "学生不存在。"
            if response.status_code == 404
            else "查询学生失败。"
        )
        raise APIClientError(message, status_code=response.status_code)
    return response.json()


def update_student(student_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Partially update a student record.

    Args:
        student_id: Primary key of the student record.
        payload: Fields to update (``name``, ``gender``, ``birthday``).

    Returns:
        The updated student payload.

    Raises:
        APIClientError: With ``status_code`` 404/409 on validation conflicts,
            or other HTTP/network failures.
    """
    response = _request(
        "PATCH", f"/api/v1/students/{student_id}", json_body=payload
    )
    if response.status_code != 200:
        message = {
            404: "学生不存在。",
            409: "学号冲突，无法完成更新。",
        }.get(response.status_code, "更新学生失败。")
        raise APIClientError(message, status_code=response.status_code)
    return response.json()


def delete_student(student_id: int) -> None:
    """Delete a student record by primary key.

    Args:
        student_id: Primary key of the student record.

    Raises:
        APIClientError: With ``status_code`` 404 when the student does not
            exist, or other HTTP/network failures.
    """
    response = _request("DELETE", f"/api/v1/students/{student_id}")
    if response.status_code != 204:
        message = (
            "学生不存在。"
            if response.status_code == 404
            else "删除学生失败。"
        )
        raise APIClientError(message, status_code=response.status_code)
