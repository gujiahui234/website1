"""Automatic university generation page backed by the Celery platform.

Thin producer: all business logic (LLM call, de-duplication, persistence)
lives in the alt_celery3 platform task ``tasks.ai.get_un_groups``. This
module only dispatches the task by name and polls its result — the same
pattern as :mod:`alt_web01.views.student_import_large`.
"""

from __future__ import annotations

from typing import Any, cast

from flask import ResponseReturnValue, current_app, jsonify, render_template, request

from alt_web01.celery_client import GET_UN_GROUPS_TASK, get_celery_app
from alt_web01.university_store import UniversityStore
from alt_web01.views import pages

#: Maximum number of universities a single request may request from the LLM.
MAX_UNIVERSITIES = 20

#: Number of recently saved universities shown on the page.
RECENT_UNIVERSITIES_LIMIT = 20


def _university_store() -> UniversityStore:
    """Return the application university store.

    Returns:
        UniversityStore: The store registered on the Flask application.
    """
    return cast(UniversityStore, current_app.extensions["university_store"])


@pages.get("/universities/generate")
def university_generate() -> str:
    """Render the automatic university and major group page.

    Returns:
        str: Rendered page HTML including the most recently saved
        universities for quick reference.
    """
    recent = _university_store().list_universities()[:RECENT_UNIVERSITIES_LIMIT]
    return render_template(
        "university_generate.html",
        max_universities=MAX_UNIVERSITIES,
        recent=recent,
    )


@pages.post("/universities/generate/start")
def university_generate_start() -> ResponseReturnValue:
    """Validate the request and dispatch the platform collection task.

    Returns:
        JSON with the Celery ``task_id`` on success, an ``error`` message
        with HTTP 400 when the input is invalid, or HTTP 503 when the
        Celery platform is unreachable.
    """
    raw_count = request.form.get("count", "").strip()

    try:
        count = int(raw_count)
    except ValueError:
        return jsonify({"error": "要生成的高校数量必须是正整数。"}), 400
    if not 1 <= count <= MAX_UNIVERSITIES:
        return jsonify(
            {"error": f"要生成的高校数量必须介于 1 和 {MAX_UNIVERSITIES} 之间。"}
        ), 400

    try:
        async_result = get_celery_app().send_task(
            GET_UN_GROUPS_TASK, kwargs={"count": count}, retry=False
        )
    except Exception as error:  # noqa: BLE001 — broker failures surface as 503.
        current_app.logger.opt(exception=error).error("高校自动采集任务投递失败")
        return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503

    current_app.logger.bind(
        component="university_generate", task_id=async_result.id, count=count
    ).info("高校自动采集任务已投递")
    return jsonify({"task_id": async_result.id})


@pages.get("/universities/generate/result")
def university_generate_result() -> ResponseReturnValue:
    """Poll the state of a previously dispatched collection task.

    Returns:
        JSON with ``state`` and, once the task succeeded, the insertion and
        de-duplication counters plus the ``universities`` payload returned by
        the platform task.
    """
    task_id = request.args.get("task_id", "").strip()
    if not task_id:
        return jsonify({"error": "缺少任务编号。"}), 400

    try:
        async_result = get_celery_app().AsyncResult(task_id)
        state = async_result.state
    except Exception as error:  # noqa: BLE001 — backend outages surface as 503.
        current_app.logger.opt(exception=error).error("查询高校采集任务状态失败")
        return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503

    payload: dict[str, Any] = {"state": state, "task_id": task_id}
    if state == "FAILURE":
        payload["error"] = "高校采集任务执行失败，请查看任务平台日志。"
    elif state == "SUCCESS":
        try:
            result = async_result.result
        except Exception as error:  # noqa: BLE001 — result read failures as 503.
            current_app.logger.opt(exception=error).error("读取高校采集任务结果失败")
            return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503
        if isinstance(result, dict):
            payload.update(
                ok=result.get("ok", False),
                requested=result.get("requested"),
                fetched=result.get("fetched"),
                inserted_universities=result.get("inserted_universities", 0),
                inserted_major_groups=result.get("inserted_major_groups", 0),
                skipped_universities=result.get("skipped_universities", 0),
                skipped_major_groups=result.get("skipped_major_groups", 0),
                universities=result.get("universities", []),
            )
            if not result.get("ok", False):
                payload["error"] = result.get("error", "采集任务执行失败。")
    return jsonify(payload)
