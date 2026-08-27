"""Manual major group creation page route and form helpers."""

from __future__ import annotations

import re
from typing import cast

from flask import current_app, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from sclog_lite import logger

from alt_web01.major_group_store import (
    DuplicateMajorGroupError,
    MajorGroupStore,
)
from alt_web01.university_store import SavedUniversity, UniversityStore
from alt_web01.views import pages


def _major_group_store() -> MajorGroupStore:
    """Return the configured major group persistence backend.

    Returns:
        MajorGroupStore: The application major group store.
    """
    return cast(MajorGroupStore, current_app.extensions["major_group_store"])


def _university_store() -> UniversityStore:
    """Return the configured university persistence backend.

    Returns:
        UniversityStore: The application university store.
    """
    return cast(UniversityStore, current_app.extensions["university_store"])


def _find_university(
    universities: list[SavedUniversity], university_number: int
) -> SavedUniversity | None:
    """Find a university by its saved identifier.

    Args:
        universities: Available university records.
        university_number: Identifier to locate.

    Returns:
        SavedUniversity | None: The matching university, if present.
    """
    return next(
        (
            university
            for university in universities
            if university.number == university_number
        ),
        None,
    )


def _parse_university_number(raw_number: str) -> int | None:
    """Parse a positive university identifier.

    Args:
        raw_number: Identifier received from a form or query string.

    Returns:
        int | None: Parsed identifier, or ``None`` when invalid.
    """
    try:
        university_number = int(raw_number)
    except ValueError:
        return None
    return university_number if university_number > 0 else None


def _major_group_form_values() -> dict[str, str]:
    """Read and normalize major group fields from the submitted form.

    Returns:
        dict[str, str]: Normalized form values.
    """
    return {
        "university_id": request.form.get("university_id", "").strip(),
        "name": request.form.get("name", "").strip(),
        "code": request.form.get("code", "").strip(),
    }


def _validate_major_group(values: dict[str, str]) -> str | None:
    """Validate submitted major group values.

    Args:
        values: Normalized major group form values.

    Returns:
        str | None: A validation message, or ``None`` when valid.
    """
    if not values["name"]:
        return "请输入专业组名称。"
    if len(values["name"]) > 100:
        return "专业组名称不能超过 100 个字符。"
    if re.fullmatch(r"[0-9]{2,5}", values["code"]) is None:
        return "专业组代码必须是二至五位数字。"
    return None


def _render_major_group_form(
    *,
    universities: list[SavedUniversity] | None = None,
    selected_university: SavedUniversity | None = None,
    values: dict[str, str] | None = None,
    error: str | None = None,
) -> str:
    """Render the form and groups belonging to the selected university.

    Args:
        universities: Available universities, loaded when omitted.
        selected_university: University whose groups should be displayed.
        values: Values to place back into the form.
        error: Optional validation or uniqueness error.

    Returns:
        str: Rendered major group page HTML.
    """
    available_universities = (
        universities
        if universities is not None
        else _university_store().list_universities()
    )
    if selected_university is None and error is None and available_universities:
        selected_university = available_universities[0]
    major_groups = (
        _major_group_store().list_major_groups(
            university_number=selected_university.number
        )
        if selected_university is not None
        else []
    )
    return render_template(
        "major_group_add.html",
        universities=available_universities,
        selected_university=selected_university,
        values=values or {"university_id": "", "name": "", "code": ""},
        error=error,
        saved=request.args.get("saved") == "1",
        major_groups=major_groups,
        persistent=current_app.config["STUDENT_STORE"] == "mysql",
    )


@pages.route("/majors/add", methods=["GET", "POST"])
def major_group_add() -> ResponseReturnValue:
    """Select a university, then validate and save one major group."""
    universities = _university_store().list_universities()
    if request.method == "GET":
        raw_number = request.args.get("university_id", "").strip()
        if not raw_number:
            return _render_major_group_form(universities=universities)
        university_number = _parse_university_number(raw_number)
        selected_university = (
            _find_university(universities, university_number)
            if university_number is not None
            else None
        )
        if selected_university is None:
            return _render_major_group_form(
                universities=universities,
                error="请选择有效的高校。",
            )
        return _render_major_group_form(
            universities=universities,
            selected_university=selected_university,
        )

    values = _major_group_form_values()
    university_number = _parse_university_number(values["university_id"])
    selected_university = (
        _find_university(universities, university_number)
        if university_number is not None
        else None
    )
    if selected_university is None:
        return _render_major_group_form(
            universities=universities,
            values=values,
            error="请选择有效的高校。",
        )

    error = _validate_major_group(values)
    if error is not None:
        logger.bind(component="major_groups", validation_error=error).warning(
            "专业组保存校验失败"
        )
        return _render_major_group_form(
            universities=universities,
            selected_university=selected_university,
            values=values,
            error=error,
        )

    try:
        major_group = _major_group_store().save_major_group(
            university_number=selected_university.number,
            university_name=selected_university.name,
            name=values["name"],
            code=values["code"],
        )
    except DuplicateMajorGroupError as duplicate_error:
        logger.bind(
            component="major_groups",
            university_number=selected_university.number,
        ).warning("高校内专业组名称或代码重复")
        return _render_major_group_form(
            universities=universities,
            selected_university=selected_university,
            values=values,
            error=str(duplicate_error),
        )

    logger.bind(
        component="major_groups",
        university_number=selected_university.number,
        major_group_number=major_group.number,
        major_group_code=major_group.code,
    ).info("专业组保存成功")
    return redirect(
        url_for(
            "pages.major_group_add",
            university_id=selected_university.number,
            saved="1",
        )
    )
