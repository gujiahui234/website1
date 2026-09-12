"""HTTP client for the alt_celery3 tasks API server.

This module is the integration point with the Celery task platform's
FastAPI service. The server location is taken from the
``API_SERVER_TASKS`` environment variable, e.g.
``http://192.168.220.134:8001/api/tasks``; the base URL is derived by
stripping the ``/api/tasks`` suffix.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import httpx

#: Per-request timeout for tasks API server calls.
_REQUEST_TIMEOUT_SECONDS = 10.0

_client_lock = threading.Lock()
_client: httpx.Client | None = None


def _base_url() -> str:
    """Derive the tasks API base URL from configuration.

    Returns:
        The base URL (scheme + host + port) without a trailing slash.

    Raises:
        RuntimeError: If ``API_SERVER_TASKS`` is not configured.
    """
    tasks_url = os.getenv("API_SERVER_TASKS", "").strip().rstrip("/")
    if not tasks_url:
        raise RuntimeError("API_SERVER_TASKS 未配置，无法定位任务 API 服务器。")
    suffix = "/api/tasks"
    if tasks_url.endswith(suffix):
        tasks_url = tasks_url[: -len(suffix)]
    return tasks_url


def get_tasks_api_client() -> httpx.Client:
    """Return the process-wide lazily created tasks API client.

    Returns:
        A shared :class:`httpx.Client` bound to the tasks API base URL.
    """
    global _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                base_url=_base_url(),
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        return _client


def close_tasks_api_client() -> None:
    """Close the shared tasks API client (used by tests and shutdown)."""
    global _client
    with _client_lock:
        if _client is not None:
            _client.close()
            _client = None


def _request(
    method: str,
    path: str,
    *,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    """Perform a request against the tasks API server.

    Args:
        method: HTTP method name.
        path: Request path relative to the tasks API base URL.
        json_body: Optional JSON request body.
        params: Optional query parameters.

    Returns:
        The :class:`httpx.Response` returned by the server.

    Raises:
        RuntimeError: When the API server is unreachable.
    """
    try:
        return get_tasks_api_client().request(
            method, path, json=json_body, params=params
        )
    except httpx.HTTPError as exc:
        client = get_tasks_api_client()
        raise RuntimeError(
            f"任务 API 服务器连接失败（{client.base_url}）：{exc}"
        ) from exc


def eligible_count(task_name: str, year: int) -> int:
    """Count the students eligible for one simulation task in a year.

    Args:
        task_name: Canonical task name, e.g. ``tasks.simu.ncee``.
        year: Simulation year.

    Returns:
        The eligible student count.

    Raises:
        RuntimeError: On network failure.
        LookupError: When the task has no count rule (HTTP 404).
    """
    response = _request(
        "GET",
        f"/api/tasks/{task_name}/eligible-count",
        params={"year": year},
    )
    if response.status_code == 404:
        raise LookupError(f"任务 {task_name} 没有参与人数统计规则。")
    if response.status_code != 200:
        raise RuntimeError("查询参与人数失败。")
    return int(response.json()["eligible"])


def dispatch_task(task_name: str, payload: dict[str, Any]) -> str:
    """Dispatch a task to the Celery platform.

    Args:
        task_name: Canonical task name, e.g. ``tasks.simu.ncee``.
        payload: Task payload fields (validated by the API server).

    Returns:
        The Celery task id for later polling.

    Raises:
        RuntimeError: On network failure or server-side rejection.
        LookupError: When the task is not registered (HTTP 404).
        ValueError: When the payload is invalid (HTTP 422).
    """
    response = _request(
        "POST", f"/api/tasks/{task_name}/dispatch", json_body=payload
    )
    if response.status_code == 404:
        raise LookupError(f"任务 {task_name} 未注册。")
    if response.status_code == 422:
        raise ValueError("任务参数校验失败，请检查年份等输入。")
    if response.status_code != 200:
        raise RuntimeError("任务派发失败。")
    return str(response.json()["task_id"])


def get_task_result(task_name: str, task_id: str) -> dict[str, Any]:
    """Poll the execution state and result of one dispatched task.

    Args:
        task_name: Canonical task name the task was dispatched under.
        task_id: Celery task id returned by :func:`dispatch_task`.

    Returns:
        The result payload with ``state``, ``ready`` and either ``result``
        or ``progress`` fields.

    Raises:
        RuntimeError: On network failure.
    """
    response = _request("GET", f"/api/tasks/{task_name}/result/{task_id}")
    if response.status_code != 200:
        raise RuntimeError("查询任务结果失败。")
    return response.json()
