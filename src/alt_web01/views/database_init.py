"""Database initialisation page backed by the Celery platform.

Thin producer: dispatches the destructive ``tasks.db.init_web_db`` task of
the alt_celery3 platform and polls its result. All business logic (dropping
and rebuilding ``web_db`` / ``log_db``, creating tables, migrations) lives on
the platform side; this module only forwards the request and reports the
outcome.

The operation is destructive, so the page must confirm it with a warning
dialog before dispatching.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify, render_template, request
from flask.typing import ResponseReturnValue
from sclog_lite import logger

from alt_web01.celery_client import INIT_WEB_DB_TASK, get_celery_app
from alt_web01.views import pages


@pages.get("/settings/database-init")
def database_init() -> str:
    """Render the database initialisation page.

    Returns:
        str: Rendered page HTML with the warning dialog and start button.
    """
    return render_template("database_init.html")


@pages.post("/settings/database-init/start")
def database_init_start() -> ResponseReturnValue:
    """Dispatch the platform ``init_web_db`` task.

    Returns:
        JSON with the Celery ``task_id`` on success, or HTTP 503 when the
        Celery platform is unreachable. The operation is destructive — the
        front end must show the warning dialog before calling this endpoint.
    """
    try:
        async_result = get_celery_app().send_task(
            INIT_WEB_DB_TASK, kwargs={}, retry=False
        )
    except Exception as error:  # noqa: BLE001 — broker failures surface as 503.
        logger.opt(exception=error).error("数据库初始化任务投递失败")
        return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503

    logger.bind(component="database_init", task_id=async_result.id).info(
        "数据库初始化任务已投递"
    )
    return jsonify({"task_id": async_result.id})


@pages.get("/settings/database-init/result")
def database_init_result() -> ResponseReturnValue:
    """Poll the state of a previously dispatched initialisation task.

    Returns:
        JSON with ``state`` and, once the task succeeded, the platform's
        summary: dropped/created databases and users, the created ``tables``
        list, whether ``enrollment_status`` was migrated in place and the
        UTC ``finished_at`` timestamp.
    """
    task_id = request.args.get("task_id", "").strip()
    if not task_id:
        return jsonify({"error": "缺少任务编号。"}), 400

    try:
        async_result = get_celery_app().AsyncResult(task_id)
        state = async_result.state
    except Exception as error:  # noqa: BLE001 — backend outages surface as 503.
        logger.opt(exception=error).error("查询数据库初始化任务状态失败")
        return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503

    payload: dict[str, Any] = {"state": state, "task_id": task_id}
    if state == "FAILURE":
        payload["error"] = "数据库初始化任务执行失败，请查看任务平台日志。"
    elif state == "SUCCESS":
        try:
            result = async_result.result
        except Exception as error:  # noqa: BLE001 — result read failures as 503.
            logger.opt(exception=error).error("读取数据库初始化任务结果失败")
            return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503
        if isinstance(result, dict):
            payload.update(result)
            if not result.get("ok", False):
                payload["error"] = result.get("error", "数据库初始化失败。")
    return jsonify(payload)
