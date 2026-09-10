"""Manual student maintenance page backed by the students API server.

The page lists students from the external API server (poc4-students-api),
lets operators search by name/gender or fetch one student by id, and edit
(name/gender/birthday) or delete a record through a modal dialog.

All browser requests hit this Flask blueprint (same origin); the blueprint
proxies to the API server via :mod:`alt_web01.api_client`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from flask import Response, current_app, jsonify, render_template, request
from flask.typing import ResponseReturnValue

from alt_web01 import api_client
from alt_web01.views import pages

#: Hard upper bound of rows returned by one search (business requirement).
MAX_SEARCH_RESULTS = 1000

#: UI gender codes (M/F) mapped to the values stored in ``web_db.students``.
GENDER_TO_API = {"M": "男", "F": "女"}
GENDER_FROM_API = {"男": "M", "女": "F"}

#: Allowed request query parameter for gender filtering.
ALLOWED_GENDER_CODES = {"M", "F", ""}


def _gender_to_api(code: str) -> str | None:
    """Convert a UI gender code into the API storage value.

    Args:
        code: UI gender code (``M`` or ``F``); empty string means no filter.

    Returns:
        The matching API gender value, or ``None`` when there is no filter.

    Raises:
        ValueError: If the code is not a valid UI gender code.
    """
    if code not in GENDER_TO_API and code != "":
        raise ValueError("性别过滤条件必须是 M 或 F。")
    return GENDER_TO_API.get(code)


def _api_error_response(exc: api_client.APIClientError) -> Response:
    """Convert an :class:`APIClientError` into a JSON error response.

    Args:
        exc: The error raised by the API client.

    Returns:
        A JSON response carrying ``error`` and the mapped HTTP status.
    """
    status = exc.status_code or 503
    if status < 400 or status > 599:
        status = 503
    return jsonify({"error": exc.message}), status


@pages.route("/students/maintain", methods=["GET"])
def student_maintain() -> str:
    """Render the manual student maintenance page.

    Returns:
        The rendered ``student_maintain.html`` template.
    """
    return render_template(
        "student_maintain.html",
        max_results=MAX_SEARCH_RESULTS,
        api_docs_url=current_app.config.get("API_SERVER_DOCS", ""),
        api_redoc_url=current_app.config.get("API_SERVER_REDOC", ""),
        api_json_url=current_app.config.get("API_SERVER_JSON", ""),
    )


@pages.route("/students/maintain/api/students", methods=["GET"])
def student_maintain_search() -> ResponseReturnValue:
    """Search students via the API server.

    Query parameters: ``name`` (substring), ``gender`` (``M``/``F``),
    ``limit`` (1-1000, default 1000).

    Returns:
        JSON with ``total`` and ``items``, or an error payload.
    """
    name = request.args.get("name", "").strip() or None
    gender_code = request.args.get("gender", "").strip().upper()
    if gender_code not in ALLOWED_GENDER_CODES:
        return jsonify({"error": "性别过滤条件必须是 M 或 F。"}), 400
    try:
        gender = _gender_to_api(gender_code)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        limit = int(request.args.get("limit", MAX_SEARCH_RESULTS))
    except ValueError:
        return jsonify({"error": "limit 必须是整数。"}), 400
    limit = max(1, min(limit, MAX_SEARCH_RESULTS))

    try:
        data = api_client.search_students(name=name, gender=gender, limit=limit)
    except api_client.APIClientError as exc:
        return _api_error_response(exc)
    return jsonify(data)


@pages.route("/students/maintain/api/students/<int:student_id>", methods=["GET"])
def student_maintain_get(student_id: int) -> ResponseReturnValue:
    """Fetch a single student by id.

    Args:
        student_id: Primary key of the student record.

    Returns:
        JSON with the student payload, or an error payload.
    """
    try:
        student = api_client.get_student(student_id)
    except api_client.APIClientError as exc:
        return _api_error_response(exc)
    return jsonify(student)


@pages.route("/students/maintain/api/students/<int:student_id>", methods=["PATCH"])
def student_maintain_update(student_id: int) -> ResponseReturnValue:
    """Update the editable fields of one student.

    Accepts a JSON body with optional ``name``, ``gender`` (``M``/``F``)
    and ``birthday`` (ISO date) fields.

    Args:
        student_id: Primary key of the student record.

    Returns:
        JSON with the updated student payload, or an error payload.
    """
    body = request.get_json(silent=True) or {}
    payload: dict[str, Any] = {}

    if "name" in body:
        name = str(body["name"]).strip()
        if not name or len(name) > 64:
            return jsonify({"error": "姓名不能为空且不超过 64 个字符。"}), 400
        payload["name"] = name

    if "gender" in body:
        code = str(body["gender"]).strip().upper()
        if code not in GENDER_TO_API:
            return jsonify({"error": "性别必须是 M 或 F。"}), 400
        payload["gender"] = GENDER_TO_API[code]

    if "birthday" in body:
        try:
            payload["birthday"] = dt.date.fromisoformat(
                str(body["birthday"]).strip()
            ).isoformat()
        except ValueError:
            return jsonify({"error": "出生日期格式必须为 YYYY-MM-DD。"}), 400

    if not payload:
        return jsonify({"error": "没有需要更新的字段。"}), 400

    try:
        student = api_client.update_student(student_id, payload)
    except api_client.APIClientError as exc:
        return _api_error_response(exc)
    return jsonify(student)


@pages.route("/students/maintain/api/students/<int:student_id>", methods=["DELETE"])
def student_maintain_delete(student_id: int) -> ResponseReturnValue:
    """Delete one student by id.

    Args:
        student_id: Primary key of the student record.

    Returns:
        JSON confirmation, or an error payload.
    """
    try:
        api_client.delete_student(student_id)
    except api_client.APIClientError as exc:
        return _api_error_response(exc)
    return jsonify({"ok": True})
