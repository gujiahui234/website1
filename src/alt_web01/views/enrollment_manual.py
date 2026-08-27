"""Manual enrollment page route."""

from __future__ import annotations

from alt_web01.views import pages
from alt_web01.views.common import render_page


@pages.get("/enrollment/manual")
def enrollment_manual() -> str:
    """Render the manual enrollment page."""
    return render_page("手动入学", "入学")
