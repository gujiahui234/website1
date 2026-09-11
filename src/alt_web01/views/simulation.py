"""Simulation pages of alt_web01 (高考 / 录取 / 日常考试 / 毕业).

Each page follows the same flow: pick a year (2018-2040), query the number
of eligible students for that year, dispatch the matching Celery
simulation task through the tasks API server and poll until the task
finishes, then display the result.

All browser requests hit this Flask blueprint (same origin); the blueprint
proxies to the tasks API server via :mod:`alt_web01.tasks_api_client`.
"""

from __future__ import annotations

from typing import Any

from flask import Response, jsonify, render_template, request
from flask.typing import ResponseReturnValue

from alt_web01 import tasks_api_client
from alt_web01.views import pages

#: Inclusive year range accepted by the simulation pages.
YEAR_MIN = 2018
YEAR_MAX = 2040

#: Year field accepted from the browser; mapped to the task payload key.
_YEAR_FIELD = "year"


class _SimulationSpec:
    """Declarative description of one simulation page.

    Attributes:
        slug: URL segment of the page (e.g. ``ncee``).
        title: Second-level menu / page title.
        kicker: Small caption shown above the title.
        intro: Page introduction sentence.
        year_label: Label of the year input field.
        eligible_desc: Description of the counted population.
        action_label: Label of the dispatch button.
        task_name: Canonical Celery task name.
        payload_key: Task payload field receiving the selected year.
        result_fields: Human labels for the keys of the final result dict.
    """

    def __init__(
        self,
        slug: str,
        title: str,
        kicker: str,
        intro: str,
        year_label: str,
        eligible_desc: str,
        action_label: str,
        task_name: str,
        payload_key: str,
        result_fields: dict[str, str],
    ) -> None:
        """Initialise the specification.

        Args:
            slug: URL segment of the page.
            title: Second-level menu / page title.
            kicker: Small caption shown above the title.
            intro: Page introduction sentence.
            year_label: Label of the year input field.
            eligible_desc: Description of the counted population.
            action_label: Label of the dispatch button.
            task_name: Canonical Celery task name.
            payload_key: Task payload field receiving the selected year.
            result_fields: Human labels for final result dictionary keys.
        """
        self.slug = slug
        self.title = title
        self.kicker = kicker
        self.intro = intro
        self.year_label = year_label
        self.eligible_desc = eligible_desc
        self.action_label = action_label
        self.task_name = task_name
        self.payload_key = payload_key
        self.result_fields = result_fields


#: The four simulation pages exposed under the ``模拟`` menu.
SIMULATIONS: dict[str, _SimulationSpec] = {
    spec.slug: spec
    for spec in (
        _SimulationSpec(
            slug="ncee",
            title="高考",
            kicker="模拟 · 高考评测",
            intro="模拟指定年份的高考评测：为适龄考生（未高考）生成高考成绩。",
            year_label="高考年份",
            eligible_desc="适龄考生（状态=0 未高考，考试当年 17-19 岁）",
            action_label="模拟高考",
            task_name="tasks.simu.ncee",
            payload_key="ncee_year",
            result_fields={
                "ncee_year": "高考年份",
                "examined": "完成评测人数",
                "status_updated": "状态更新人数",
                "exam_date": "考试日期",
                "elapsed_seconds": "耗时（秒）",
                "note": "说明",
            },
        ),
        _SimulationSpec(
            slug="admission",
            title="录取",
            kicker="模拟 · 高校录取",
            intro="模拟指定年份的高校录取：按分数梯队把已高考考生录取到大学。",
            year_label="高考年份",
            eligible_desc="待录取考生（状态=10 已高考未入学，且该年有高考成绩）",
            action_label="模拟录取",
            task_name="tasks.simu.admission",
            payload_key="ncee_year",
            result_fields={
                "ncee_year": "高考年份",
                "admitted": "录取人数",
                "status_updated": "状态更新人数",
                "admitted_by_nature": "按高校性质统计",
                "elapsed_seconds": "耗时（秒）",
                "note": "说明",
            },
        ),
        _SimulationSpec(
            slug="exam",
            title="日常考试",
            kicker="模拟 · 本科日常考试",
            intro="模拟指定学年的本科日常考试：为在读学生生成若干门课程成绩。",
            year_label="考试学年",
            eligible_desc="在读考生（状态=20 在读，学年 在[year-3, year] 内入学）",
            action_label="模拟考试",
            task_name="tasks.simu.exam",
            payload_key="academic_year",
            result_fields={
                "academic_year": "学年",
                "students_examined": "参考学生数",
                "exams_recorded": "考试场次",
                "elapsed_seconds": "耗时（秒）",
                "note": "说明",
            },
        ),
        _SimulationSpec(
            slug="graduate",
            title="毕业",
            kicker="模拟 · 本科毕业",
            intro="模拟指定年份的本科毕业：为入学满四年的在读学生计算 GPA 并毕业。",
            year_label="毕业年份",
            eligible_desc="可毕业考生（状态=20 在读，且录取学年=毕业年份-4）",
            action_label="模拟毕业",
            task_name="tasks.simu.graduate",
            payload_key="graduate_year",
            result_fields={
                "graduate_year": "毕业年份",
                "graduated": "毕业人数",
                "without_scores": "无成绩毕业生",
                "average_gpa": "平均绩点",
                "elapsed_seconds": "耗时（秒）",
                "note": "说明",
            },
        ),
    )
}


def _parse_year(raw: str) -> int | None:
    """Parse and range-check a year string from the browser.

    Args:
        raw: Raw year string.

    Returns:
        The parsed year, or ``None`` when invalid or out of range.
    """
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return None
    if not YEAR_MIN <= year <= YEAR_MAX:
        return None
    return year


def _api_error_response(exc: Exception) -> ResponseReturnValue:
    """Convert a tasks API client error into a JSON error response.

    Args:
        exc: The error raised by the tasks API client.

    Returns:
        A JSON response carrying ``error`` and a mapped HTTP status.
    """
    if isinstance(exc, LookupError):
        return jsonify({"error": str(exc)}), 404
    if isinstance(exc, ValueError):
        return jsonify({"error": str(exc)}), 400
    return jsonify({"error": str(exc)}), 503


def _register_simulation(spec: _SimulationSpec) -> None:
    """Register the page and JSON proxy routes of one simulation.

    Args:
        spec: The declarative specification of the simulation page.
    """
    page_endpoint = f"simulation_{spec.slug}"
    api_prefix = f"/simulations/{spec.slug}/api"

    @pages.route(f"/simulations/{spec.slug}", methods=["GET"], endpoint=page_endpoint)
    def simulation_page(spec: _SimulationSpec = spec) -> str:
        """Render the simulation page.

        Args:
            spec: Bound simulation specification.

        Returns:
            The rendered ``simulation.html`` template.
        """
        return render_template(
            "simulation.html",
            spec=spec,
            year_min=YEAR_MIN,
            year_max=YEAR_MAX,
            eligible_url=f"{api_prefix}/eligible",
            dispatch_url=f"{api_prefix}/dispatch",
            result_url=f"{api_prefix}/result",
        )

    @pages.route(
        f"{api_prefix}/eligible", methods=["GET"], endpoint=f"{page_endpoint}_eligible"
    )
    def simulation_eligible(spec: _SimulationSpec = spec) -> ResponseReturnValue:
        """Proxy the eligible-student count query.

        Args:
            spec: Bound simulation specification.

        Returns:
            JSON with ``eligible`` count, or an error payload.
        """
        year = _parse_year(request.args.get(_YEAR_FIELD, ""))
        if year is None:
            return jsonify(
                {"error": f"年份必须是 {YEAR_MIN}-{YEAR_MAX} 之间的整数。"}
            ), 400
        try:
            eligible = tasks_api_client.eligible_count(spec.task_name, year)
        except Exception as exc:  # noqa: BLE001 — mapped below.
            return _api_error_response(exc)
        return jsonify({"year": year, "eligible": eligible})

    @pages.route(
        f"{api_prefix}/dispatch",
        methods=["POST"],
        endpoint=f"{page_endpoint}_dispatch",
    )
    def simulation_dispatch(spec: _SimulationSpec = spec) -> ResponseReturnValue:
        """Proxy the task dispatch request.

        Accepts a JSON body ``{"year": N}`` and dispatches the simulation
        task with the mapped payload key.

        Args:
            spec: Bound simulation specification.

        Returns:
            JSON with ``task_id`` for polling, or an error payload.
        """
        body = request.get_json(silent=True) or {}
        year = _parse_year(str(body.get(_YEAR_FIELD, "")))
        if year is None:
            return jsonify(
                {"error": f"年份必须是 {YEAR_MIN}-{YEAR_MAX} 之间的整数。"}
            ), 400
        try:
            task_id = tasks_api_client.dispatch_task(
                spec.task_name, {spec.payload_key: year}
            )
        except Exception as exc:  # noqa: BLE001 — mapped below.
            return _api_error_response(exc)
        return jsonify({"task_id": task_id, "task_name": spec.task_name})

    @pages.route(
        f"{api_prefix}/result/<task_id>",
        methods=["GET"],
        endpoint=f"{page_endpoint}_result",
    )
    def simulation_result(spec: _SimulationSpec = spec, task_id: str = "") -> ResponseReturnValue:
        """Proxy the task result polling request.

        Args:
            spec: Bound simulation specification.
            task_id: Celery task id returned by the dispatch endpoint.

        Returns:
            JSON with the task state/progress/result, or an error payload.
        """
        try:
            data = tasks_api_client.get_task_result(spec.task_name, task_id)
        except Exception as exc:  # noqa: BLE001 — mapped below.
            return _api_error_response(exc)
        return jsonify(data)


for _spec in SIMULATIONS.values():
    _register_simulation(_spec)
