"""University student count analytics page route (ECharts bar chart)."""

from __future__ import annotations

from typing import Any

from flask import current_app, jsonify, render_template
from flask.typing import ResponseReturnValue

from alt_web01 import score_stats
from alt_web01.views import pages

#: JSON proxy path for the chart data feed.
_DATA_PATH = "/analytics/students-by-university/api/data"


@pages.get("/analytics/students-by-university")
def analytics_students_by_university() -> str:
    """Render the university student count page (ECharts bar chart)."""
    return render_template(
        "analytics_students_by_university.html", data_url=_DATA_PATH
    )


@pages.get(_DATA_PATH)
def analytics_students_by_university_data() -> ResponseReturnValue:
    """Proxy the per-university student count statistic from web_db.

    Returns:
        JSON with ``items`` (one per university: name, nature, distinct
        student count, enrollment record count) plus a per-nature
        ``summary``, or an error payload with a mapped HTTP status.
    """
    try:
        payload: dict[str, Any] = score_stats.collect_university_student_counts(
            current_app.config
        )
    except score_stats.WebDBUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:  # noqa: BLE001 — surfaced as a 503 payload.
        return jsonify({"error": f"统计数据加载失败：{exc}"}), 503
    return jsonify(payload)
