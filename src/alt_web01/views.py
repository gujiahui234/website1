"""Page routes for the demonstration website."""

from flask import Blueprint, render_template

pages = Blueprint("pages", __name__)


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


@pages.get("/students/add")
def student_add() -> str:
    """Render the manual student creation page."""
    return render_page("手工添加学生", "学生")


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

