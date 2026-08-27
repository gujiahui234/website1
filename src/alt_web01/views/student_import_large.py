"""Large student import page route."""

from __future__ import annotations

from alt_web01.views import pages
from alt_web01.views.common import render_page


@pages.get("/students/import/large")
def student_import_large() -> str:
    """Render the large student import page."""
    return render_page("批量添加学生（大数据量）", "学生")
