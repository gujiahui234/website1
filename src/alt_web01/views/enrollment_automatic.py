"""Automatic enrollment page route."""

from __future__ import annotations

from alt_web01.views import pages
from alt_web01.views.common import render_page


@pages.get("/enrollment/automatic")
def enrollment_automatic() -> str:
    """Render the automatic enrollment page."""
    return render_page("自动入学", "入学")
