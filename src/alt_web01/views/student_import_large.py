"""Large student import page route backed by the Celery platform."""

from __future__ import annotations

import datetime as dt
from typing import Any

from flask import current_app, jsonify, render_template, request
from flask.typing import ResponseReturnValue
from sclog_lite import logger

from alt_web01.celery_client import (
    GENERATE_MANY_STUDENTS_TASK,
    MAX_STUDENTS,
    get_celery_app,
)
from alt_web01.views import pages
from alt_web01.web_db import list_recent_students

#: Maximum number of parts in an accepted birthday boundary string.
_BIRTHDAY_PARTS = 3


def _parse_birthday(value: str) -> tuple[int, int, int] | None:
    """Validate one birthday boundary string.

    Args:
        value: Raw user input, one of ``YYYY``, ``YYYY-MM``, ``YYYY-MM-DD``
            (matching the ``class_roster`` date contract).

    Returns:
        Tuple of ``(year, month, day)`` with omitted parts set to ``1`` so
        the boundaries can be compared, or ``None`` when invalid.
    """
    parts = value.split("-")
    if not 1 <= len(parts) <= _BIRTHDAY_PARTS:
        return None
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None
    year = numbers[0]
    month = numbers[1] if len(numbers) > 1 else 1
    day = numbers[2] if len(numbers) > 2 else 1
    try:
        dt.date(year, month, day)
    except ValueError:
        return None
    return year, month, day


@pages.get("/students/import/large")
def student_import_large() -> str:
    """Render the large student import page."""
    return render_template("student_import_large.html", max_students=MAX_STUDENTS)


@pages.post("/students/import/large/start")
def student_import_large_start() -> ResponseReturnValue:
    """Validate the request and dispatch the platform generation task.

    Returns:
        JSON with the Celery ``task_id`` on success, an ``error`` message
        with HTTP 400 when the input is invalid, or HTTP 503 when the
        Celery platform is unreachable.
    """
    raw_numbers = request.form.get("numbers", "").strip()
    birthday_min = request.form.get("birthday_min", "").strip()
    birthday_max = request.form.get("birthday_max", "").strip()

    try:
        numbers = int(raw_numbers)
    except ValueError:
        return jsonify({"error": "要生成的人数必须是正整数。"}), 400
    if not 1 <= numbers <= MAX_STUDENTS:
        return jsonify({"error": f"要生成的人数必须介于 1 和 {MAX_STUDENTS} 之间。"}), 400

    kwargs: dict[str, Any] = {"numbers": numbers}
    if bool(birthday_min) != bool(birthday_max):
        return jsonify({"error": "出生年月日区间的最小值和最大值必须同时填写。"}), 400
    if birthday_min and birthday_max:
        parsed_min = _parse_birthday(birthday_min)
        parsed_max = _parse_birthday(birthday_max)
        if parsed_min is None or parsed_max is None:
            return jsonify(
                {"error": "出生年月日必须形如 2000、2000-09 或 2000-09-01。"}
            ), 400
        if parsed_min > parsed_max:
            return jsonify({"error": "出生年月日区间的最小值不能大于最大值。"}), 400
        kwargs["birthday_min"] = birthday_min
        kwargs["birthday_max"] = birthday_max

    try:
        async_result = get_celery_app().send_task(
            GENERATE_MANY_STUDENTS_TASK, kwargs=kwargs, retry=False
        )
    except Exception as error:  # noqa: BLE001 — broker failures surface as 503.
        logger.bind(component="student_import_large").opt(exception=error).error(
            "批量生成学生任务投递失败"
        )
        return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503

    logger.bind(
        component="student_import_large",
        task_id=async_result.id,
        numbers=numbers,
    ).info("批量生成学生任务已投递")
    return jsonify({"task_id": async_result.id})


@pages.get("/students/import/large/result")
def student_import_large_result() -> ResponseReturnValue:
    """Poll the state of a previously dispatched generation task.

    Returns:
        JSON with ``state`` and, once the task succeeded, the number of
        generated students (``inserted``) plus the newest 1,000 students
        (``students``) read from the platform's ``web_db`` database.
    """
    task_id = request.args.get("task_id", "").strip()
    if not task_id:
        return jsonify({"error": "缺少任务编号。"}), 400

    try:
        async_result = get_celery_app().AsyncResult(task_id)
        state = async_result.state
    except Exception as error:  # noqa: BLE001 — backend outages surface as 503.
        logger.bind(component="student_import_large").opt(exception=error).error(
            "查询任务状态失败"
        )
        return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503

    payload: dict[str, Any] = {"state": state, "task_id": task_id}
    if state == "PROGRESS":
        meta = async_result.info
        if isinstance(meta, dict):
            payload["inserted"] = meta.get("inserted", 0)
        return jsonify(payload)

    if state != "SUCCESS":
        if state == "FAILURE":
            payload["error"] = "生成任务执行失败，请查看任务平台日志。"
        return jsonify(payload)

    try:
        result = async_result.result
    except Exception as error:  # noqa: BLE001 — backend outages surface as 503.
        logger.bind(component="student_import_large").opt(exception=error).error(
            "读取任务结果失败"
        )
        return jsonify({"error": "任务平台暂不可用，请稍后重试。"}), 503
    if not isinstance(result, dict) or not result.get("ok", False):
        message = (
            str(result.get("error", "生成任务未成功完成。"))
            if isinstance(result, dict)
            else "生成任务未成功完成。"
        )
        payload["error"] = message
        return jsonify(payload)

    payload["inserted"] = result.get("inserted", 0)
    payload["number_start"] = result.get("number_start")
    payload["number_end"] = result.get("number_end")
    payload["elapsed_seconds"] = result.get("elapsed_seconds")
    payload["students"] = [
        {
            "number": student.number,
            "name": student.name,
            "gender": student.gender,
            "birthday": student.birthday.isoformat(),
        }
        for student in list_recent_students(current_app.config, 1000)
    ]
    logger.bind(
        component="student_import_large",
        task_id=task_id,
        inserted=payload["inserted"],
    ).info("批量生成学生任务完成")
    return jsonify(payload)


__all__ = [
    "_parse_birthday",
    "student_import_large",
    "student_import_large_result",
    "student_import_large_start",
]
