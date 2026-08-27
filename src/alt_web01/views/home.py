"""Home page route."""

from __future__ import annotations

from alt_web01.views import pages
from alt_web01.views.common import render_page


@pages.get("/")
def home() -> str:
    """Render the home page."""
    return render_page("首页", "ALT · CAMPUS")
