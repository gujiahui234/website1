"""Manual university creation page route and form helpers."""

from __future__ import annotations

import re
from typing import cast

from flask import current_app, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from sclog_lite import logger

from alt_web01.university_store import (
    DuplicateUniversityError,
    UniversityStore,
)
from alt_web01.views import pages

VALID_TYPES = {"民办", "公办"}
VALID_NATURES = {"985", "211", "一本", "其他"}


def _university_store() -> UniversityStore:
    """Return the configured university persistence backend.

    Returns:
        UniversityStore: The application university store.
    """
    return cast(UniversityStore, current_app.extensions["university_store"])


def _university_form_values() -> dict[str, str]:
    """Read and normalize university fields from the submitted form.

    Returns:
        dict[str, str]: Normalized form values.
    """
    return {
        "name": request.form.get("name", "").strip(),
        "code": request.form.get("code", "").strip(),
        "type": request.form.get("type", "").strip(),
        "nature": request.form.get("nature", "").strip(),
    }


def _validate_university(values: dict[str, str]) -> str | None:
    """Validate submitted university values.

    Args:
        values: Normalized university form values.

    Returns:
        str | None: A validation message, or ``None`` when valid.
    """
    if not values["name"]:
        return "请输入高校名称。"
    if len(values["name"]) > 100:
        return "高校名称不能超过 100 个字符。"
    if re.fullmatch(r"[0-9]{5}", values["code"]) is None:
        return "高校代码必须是五位数字。"
    if values["type"] not in VALID_TYPES:
        return "请选择有效的高校类型。"
    if values["nature"] not in VALID_NATURES:
        return "请选择有效的高校性质。"
    return None


def _render_university_form(
    values: dict[str, str] | None = None,
    error: str | None = None,
) -> str:
    """Render the university form and all saved universities.

    Args:
        values: Values to place back into the form.
        error: Optional validation or uniqueness error.

    Returns:
        str: Rendered university page HTML.
    """
    universities = _university_store().list_universities()
    return render_template(
        "university_add.html",
        values=values or {"name": "", "code": "", "type": "", "nature": ""},
        error=error,
        saved=request.args.get("saved") == "1",
        universities=universities,
        persistent=current_app.config["STUDENT_STORE"] == "mysql",
    )


@pages.route("/universities/add", methods=["GET", "POST"])
def university_add() -> ResponseReturnValue:
    """Validate and save a university, then render the complete list."""
    if request.method == "GET":
        return _render_university_form()

    values = _university_form_values()
    error = _validate_university(values)
    if error is not None:
        logger.bind(component="universities", validation_error=error).warning(
            "高校保存校验失败"
        )
        return _render_university_form(values, error)

    try:
        university = _university_store().save_university(
            name=values["name"],
            code=values["code"],
            type=values["type"],
            nature=values["nature"],
        )
    except DuplicateUniversityError as duplicate_error:
        logger.bind(component="universities").warning("高校名称或代码重复")
        return _render_university_form(values, str(duplicate_error))

    logger.bind(
        component="universities",
        university_number=university.number,
        university_code=university.code,
    ).info("高校保存成功")
    return redirect(url_for("pages.university_add", saved="1"))
