"""Shared helpers for page view modules."""

from __future__ import annotations

from flask import render_template


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
