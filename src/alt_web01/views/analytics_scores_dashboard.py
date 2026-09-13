"""Score analysis dashboard page route (ECharts dashboard, aggregated web_db stats)."""

from __future__ import annotations

from typing import Any

from flask import current_app, jsonify, render_template, request
from flask.typing import ResponseReturnValue

from alt_web01 import score_stats
from alt_web01.views import pages

#: JSON proxy path for the dashboard data feed.
_DATA_PATH = "/analytics/scores-dashboard/api/data"


@pages.get("/analytics/scores-dashboard")
def analytics_scores_dashboard() -> str:
    """Render the score analysis dashboard page (ECharts)."""
    return render_template("analytics_scores_dashboard.html", data_url=_DATA_PATH)


@pages.get(_DATA_PATH)
def analytics_scores_dashboard_data() -> ResponseReturnValue:
    """Aggregate all score metrics from web_db into one JSON payload.

    Query parameters:
        ``nature`` — optional university-nature filter (985/211/一本/其他).
        ``ncee_year`` — optional gaokao exam-year filter.

    Returns:
        JSON payload from :func:`score_stats.collect_score_stats`, or an
        error payload with a mapped HTTP status.
    """
    nature = request.args.get("nature", "").strip() or None
    if nature not in score_stats.NATURE_ORDER:
        nature = None

    ncee_year: int | None = None
    raw_year = request.args.get("ncee_year", "").strip()
    if raw_year.isdigit():
        ncee_year = int(raw_year)

    try:
        payload: dict[str, Any] = score_stats.collect_score_stats(
            current_app.config, nature=nature, ncee_year=ncee_year
        )
    except score_stats.WebDBUnavailableError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:  # noqa: BLE001 — surfaced as a 503 payload.
        return jsonify({"error": f"统计数据加载失败：{exc}"}), 503
    return jsonify(payload)
