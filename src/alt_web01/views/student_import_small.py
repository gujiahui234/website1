"""Small student import page route."""

from __future__ import annotations

from alt_web01.views import pages
from alt_web01.views.common import render_page


@pages.get("/students/import/small")
def student_import_small() -> str:
    """Render the small student import page."""
    return render_page("批量添加学生（小数据量）", "学生")
