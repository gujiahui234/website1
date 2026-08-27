"""Yearly student count analytics page route."""

from __future__ import annotations

from alt_web01.views import pages
from alt_web01.views.common import render_page


@pages.get("/analytics/students-by-year")
def analytics_students_by_year() -> str:
    """Render the yearly student count page."""
    return render_page("历年学生数量统计", "统计分析")
