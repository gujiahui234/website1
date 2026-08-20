"""Page routes for the demonstration website."""

from __future__ import annotations

import datetime as dt
from typing import cast

from class_roster import Student, simulate_class
from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue
from sclog_lite import logger

pages = Blueprint("pages", __name__)

BIRTHDAY_MIN = dt.date(2000, 1, 1)
BIRTHDAY_MAX = dt.date(2020, 12, 31)
VALID_GENDERS = {"男", "女"}


def render_page(page_name: str, page_kicker: str) -> str:
    """Render a named placeholder page.

    Args:
        page_name: Visible page title.
        page_kicker: Navigation group shown above the title.

    Returns:
        str: Rendered page HTML.
    """
    return render_template(
        "page.html", page_name=page_name, page_kicker=page_kicker
    )


@pages.get("/")
def home() -> str:
    """Render the home page."""
    return render_page("首页", "ALT · CAMPUS")


def _saved_students() -> list[Student]:
    """Return the current process-local student store."""
    return cast(list[Student], current_app.extensions["saved_students"])


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
    """Render the student form and the process-local saved roster."""
    return render_template(
        "student_add.html",
        values=values or {"name": "", "birthday": "", "gender": ""},
        error=error,
        saved=request.args.get("saved") == "1",
        students=_saved_students(),
        birthday_min=BIRTHDAY_MIN.isoformat(),
        birthday_max=BIRTHDAY_MAX.isoformat(),
    )


@pages.route("/students/add", methods=["GET", "POST"])
def student_add() -> ResponseReturnValue:
    """Generate, validate, and save fictional students in memory."""
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

    students = _saved_students()
    student = Student(
        number=len(students) + 1,
        name=values["name"],
        gender=values["gender"],
        birthday=birthday,
    )
    students.append(student)
    logger.bind(
        component="students",
        student_number=student.number,
    ).info("学生保存成功")
    return redirect(url_for("pages.student_add", saved="1"))


@pages.get("/students/import/small")
def student_import_small() -> str:
    """Render the small student import page."""
    return render_page("批量添加学生（小数据量）", "学生")


@pages.get("/students/import/large")
def student_import_large() -> str:
    """Render the large student import page."""
    return render_page("批量添加学生（大数据量）", "学生")


@pages.get("/universities/add")
def university_add() -> str:
    """Render the manual university creation page."""
    return render_page("手工添加大学", "大学")


@pages.get("/majors/add")
def major_group_add() -> str:
    """Render the manual major group creation page."""
    return render_page("手工添加专业组", "大学")


@pages.get("/universities/generate")
def university_generate() -> str:
    """Render the automatic university and major group page."""
    return render_page("自动添加大学和专业组", "大学")


@pages.get("/enrollment/manual")
def enrollment_manual() -> str:
    """Render the manual enrollment page."""
    return render_page("手动入学", "入学")


@pages.get("/enrollment/automatic")
def enrollment_automatic() -> str:
    """Render the automatic enrollment page."""
    return render_page("自动入学", "入学")


@pages.get("/analytics/students-by-year")
def analytics_students_by_year() -> str:
    """Render the yearly student count page."""
    return render_page("历年学生数量统计", "统计分析")


@pages.get("/analytics/students-by-university")
def analytics_students_by_university() -> str:
    """Render the university student count page."""
    return render_page("各大学学生数量统计", "统计分析")
