"""Automatic university generation page route."""

from __future__ import annotations

from alt_web01.views import pages
from alt_web01.views.common import render_page


@pages.get("/universities/generate")
def university_generate() -> str:
    """Render the automatic university and major group page."""
    return render_page("自动添加大学和专业组", "大学")
