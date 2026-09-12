"""Yearly student count analytics page route (ECharts bar chart)."""

from __future__ import annotations

from flask import Response, jsonify, render_template
from flask.typing import ResponseReturnValue

from alt_web01 import api_client
from alt_web01.views import pages

#: JSON proxy path for the chart data feed.
_DATA_PATH = "/analytics/students-by-year/api/data"


@pages.get("/analytics/students-by-year")
def analytics_students_by_year() -> str:
    """Render the yearly student count page (ECharts bar chart)."""
    return render_template("analytics_students_by_year.html", data_url=_DATA_PATH)


@pages.get(_DATA_PATH)
def analytics_students_by_year_data() -> ResponseReturnValue:
    """Proxy the per-year student count statistic from the API server.

    Returns:
        JSON with ``items`` (``{year, count}`` buckets) for the chart, or an
        error payload with a mapped HTTP status.
    """
    try:
        items = api_client.stat_count_students_num()
    except api_client.APIClientError as exc:
        status = exc.status_code or 503
        if status < 400 or status > 599:
            status = 503
        return jsonify({"error": exc.message}), status
    except Exception as exc:  # noqa: BLE001 — surfaced as a 503 payload.
        return jsonify({"error": str(exc)}), 503
    return jsonify({"items": items})
