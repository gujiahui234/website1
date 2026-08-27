"""Manual student creation page route and form helpers."""

from __future__ import annotations

import datetime as dt
from typing import cast

from class_roster import simulate_class
from flask import current_app, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from sclog_lite import logger

from alt_web01.student_store import StudentStore
from alt_web01.views import pages

BIRTHDAY_MIN = dt.date(2000, 1, 1)
BIRTHDAY_MAX = dt.date(2020, 12, 31)
VALID_GENDERS = {"男", "女"}


def _birthday_in_year(birthday: dt.date, year: int) -> dt.date:
    """Return the birthday anniversary in a year, mapping Feb 29 to Feb 28."""
    try:
        return birthday.replace(year=year)
    except ValueError:
        return dt.date(year, 2, 28)


def _age_on(birthday: dt.date, as_of: dt.date) -> float:
    """Calculate fractional age between adjacent birthday anniversaries."""
    anniversary = _birthday_in_year(birthday, as_of.year)
    if as_of >= anniversary:
        completed_years = as_of.year - birthday.year
        previous_birthday = anniversary
        next_birthday = _birthday_in_year(birthday, as_of.year + 1)
    else:
        completed_years = as_of.year - birthday.year - 1
        previous_birthday = _birthday_in_year(birthday, as_of.year - 1)
        next_birthday = anniversary

    elapsed_days = (as_of - previous_birthday).days
    year_days = (next_birthday - previous_birthday).days
    return round(completed_years + elapsed_days / year_days, 1)


def _student_store() -> StudentStore:
    """Return the configured student persistence backend."""
    return cast(StudentStore, current_app.extensions["student_store"])


def _student_form_values() -> dict[str, str]:
    """Read and normalize student fields from the submitted form."""
    return {
        "name": request.form.get("name", "").strip(),
        "birthday": request.form.get("birthday", "").strip(),
        "gender": request.form.get("gender", "").strip(),
    }


def _validate_student(values: dict[str, str]) -> tuple[dt.date | None, str | None]:
    """Validate submitted student values and return a parsed birthday."""
    if not values["name"]:
        return None, "请输入学生姓名。"
    if values["gender"] not in VALID_GENDERS:
        return None, "请选择有效的性别。"

    try:
        birthday = dt.date.fromisoformat(values["birthday"])
    except ValueError:
        return None, "请输入有效的生日。"

    if not BIRTHDAY_MIN <= birthday <= BIRTHDAY_MAX:
        return None, "生日必须在 2000 年至 2020 年之间。"
    return birthday, None


def _render_student_form(
    values: dict[str, str] | None = None,
    error: str | None = None,
) -> str:
    """Render the student form and the saved roster."""
    students = _student_store().list_students()
    today = dt.date.today()
    return render_template(
        "student_add.html",
        values=values or {"name": "", "birthday": "", "gender": ""},
        error=error,
        saved=request.args.get("saved") == "1",
        students=students,
        student_rows=[
            (student, _age_on(student.birthday, today)) for student in students
        ],
        age_as_of=today.isoformat(),
        persistent=current_app.config["STUDENT_STORE"] == "mysql",
        birthday_min=BIRTHDAY_MIN.isoformat(),
        birthday_max=BIRTHDAY_MAX.isoformat(),
    )


@pages.route("/students/add", methods=["GET", "POST"])
def student_add() -> ResponseReturnValue:
    """Generate, validate, and save fictional students."""
    if request.method == "GET":
        return _render_student_form()

    action = request.form.get("action")
    if action == "generate":
        generated = simulate_class(
            size=1,
            birth_start=BIRTHDAY_MIN,
            birth_end=BIRTHDAY_MAX,
        ).students[0]
        return _render_student_form(
            {
                "name": generated.name,
                "birthday": generated.birthday.isoformat(),
                "gender": generated.gender,
            }
        )

    values = _student_form_values()
    birthday, error = _validate_student(values)
    if error is not None or birthday is None:
        logger.bind(component="students", validation_error=error).warning(
            "学生保存校验失败"
        )
        return _render_student_form(values, error)

    student = _student_store().save_student(
        name=values["name"],
        gender=values["gender"],
        birthday=birthday,
    )
    logger.bind(
        component="students",
        student_number=student.number,
    ).info("学生保存成功")
    return redirect(url_for("pages.student_add", saved="1"))
