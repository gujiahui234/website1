"""Read-only, pre-aggregated score statistics for the scores dashboard.

Every metric on the score analysis dashboard is aggregated *inside* MySQL
(histograms by score bucket, per-year buckets, per-nature buckets,
correlation sums, sankey flows), so the browser never receives raw
per-student rows even when ``web_db`` holds tens of millions of them.

Table shapes (created by the alt_celery3 platform's ``init_web_db`` task):

- ``gaokao_scores(student_id, score, exam_date)``     — one row per student
- ``undergraduate_scores(student_id, academic_year, subject, score, exam_date)``
- ``graduation_scores(student_id, gpa, graduation_date)``
- ``enrollments(student_id, university_id, major_group_id, academic_year)``
- ``universities(id, name, code, type, nature)``      — nature: 985/211/一本/其他

The module degrades gracefully: when a table does not exist yet (the
platform tasks have never run) the affected metric simply comes back empty
instead of failing the whole dashboard.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, cast

import pymysql  # type: ignore[import-untyped]
from pymysql.cursors import DictCursor  # type: ignore[import-untyped]

#: MySQL error numbers that degrade into an empty metric instead of failing
#: the dashboard: table does not exist yet (1146) or column missing (1054).
_BENIGN_ERRORS = {1146, 1054}

#: Display order for university natures (matches ``universities.nature``).
NATURE_ORDER: tuple[str, ...] = ("985", "211", "一本", "其他")

#: Correlation matrix variables (order matters — mirrored by the frontend).
CORR_VARS: tuple[str, ...] = (
    "高考成绩",
    "本科平均成绩",
    "成绩波动 σ",
    "挂科占比",
    "考试次数",
    "GPA",
)


class WebDBUnavailableError(RuntimeError):
    """Raised when the ``MYSQL_WEB_*`` settings are incomplete or the DB is down."""


def _settings(config: Mapping[str, object]) -> dict[str, str | int]:
    """Build PyMySQL connection arguments from the Flask configuration."""
    host = str(config.get("MYSQL_WEB_HOST", "")).strip()
    user = str(config.get("MYSQL_WEB_USER", "")).strip()
    database = str(config.get("MYSQL_WEB_DATABASE", "")).strip()
    password = str(config.get("MYSQL_WEB_PASSWORD", ""))
    if not host or not user or not database:
        raise WebDBUnavailableError(
            "MYSQL_WEB_HOST、MYSQL_WEB_USER 和 MYSQL_WEB_DATABASE 必须配置"
        )
    try:
        port = int(str(config.get("MYSQL_WEB_PORT", 3306)))
    except (TypeError, ValueError) as error:
        raise WebDBUnavailableError("MYSQL_WEB_PORT 必须是整数") from error
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
    }


# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------

#: One enrollment row per student (the latest ``academic_year`` wins).
_LATEST_ENROLLMENT_SQL = """
SELECT e.student_id AS student_id,
       e.university_id AS university_id,
       e.academic_year AS academic_year
FROM enrollments e
JOIN (
    SELECT student_id, MAX(academic_year) AS max_year
    FROM enrollments
    GROUP BY student_id
) latest ON latest.student_id = e.student_id AND latest.max_year = e.academic_year
"""

#: Per-undergraduate-transcript aggregation (one row per student).
_UG_AGG_SQL = """
SELECT student_id,
       AVG(score)         AS ug_avg,
       STDDEV_SAMP(score) AS ug_std,
       COUNT(*)           AS ug_cnt,
       SUM(score < 60)    AS fail_cnt
FROM undergraduate_scores
GROUP BY student_id
"""


def _per_student_sql(
    nature: str | None, ncee_year: int | None
) -> tuple[str, list[Any]]:
    """Build the per-student base subquery plus its bound parameters.

    The subquery yields one row per student who sat the gaokao, carrying the
    gaokao score, the university nature (``NULL`` when not enrolled), and the
    aggregated undergraduate/graduation statistics.  ``nature`` and
    ``ncee_year`` filters are applied *inside* so every downstream metric
    shares the same population.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if nature:
        conditions.append("u.nature = %s")
        params.append(nature)
    if ncee_year:
        conditions.append("YEAR(g.exam_date) = %s")
        params.append(ncee_year)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
SELECT
    g.student_id        AS sid,
    g.score             AS ncee,
    YEAR(g.exam_date)   AS ncee_year,
    u.nature            AS nature,
    ug.ug_avg           AS ug_avg,
    ug.ug_std           AS ug_std,
    ug.ug_cnt           AS ug_cnt,
    ug.fail_cnt         AS fail_cnt,
    gs.gpa              AS gpa
FROM gaokao_scores g
LEFT JOIN (
    {_LATEST_ENROLLMENT_SQL}
) le ON le.student_id = g.student_id
LEFT JOIN universities u ON u.id = le.university_id
LEFT JOIN (
    {_UG_AGG_SQL}
) ug ON ug.student_id = g.student_id
LEFT JOIN graduation_scores gs ON gs.student_id = g.student_id{where}
"""
    return sql, params


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _i(value: object) -> int:
    """Coerce a DB value into an ``int`` (MySQL returns ``Decimal`` for sums)."""
    return int(value) if value is not None else 0


def _f(value: object) -> float | None:
    """Coerce a DB value into a ``float`` (JSON cannot serialise ``Decimal``)."""
    if value is None:
        return None
    return round(float(value), 4)


def _rows(cursor: DictCursor, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    """Execute a query, degrading benign schema errors into an empty result."""
    try:
        cursor.execute(sql, params)
        return cast(list[dict[str, Any]], cursor.fetchall())
    except pymysql.err.ProgrammingError as error:
        if error.args and error.args[0] in _BENIGN_ERRORS:
            return []
        raise


def _quantiles_from_hist(
    hist: list[tuple[float, int]], step: float
) -> tuple[float, float, float] | None:
    """Interpolate P25 / median / P75 from a bucket histogram.

    Args:
        hist: ``(bucket_lower_edge, count)`` pairs sorted by edge.
        step: Bucket width (5 points for gaokao, 1 for scores, 0.1 for GPA).
    """
    total = sum(count for _, count in hist)
    if not hist or total == 0:
        return None

    def quantile(p: float) -> float:
        target = p * total
        cumulative = 0
        for value, count in hist:
            if cumulative + count >= target:
                frac = (target - cumulative) / count if count else 0.0
                return value + frac * step
            cumulative += count
        return hist[-1][0]

    return quantile(0.25), quantile(0.50), quantile(0.75)


# ---------------------------------------------------------------------------
# Metric queries (all share the per-student base subquery)
# ---------------------------------------------------------------------------


def _kpi(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Headline KPI cards: counts, averages, pass rate, GPA."""
    row = _rows(
        cursor,
        f"""
SELECT COUNT(*)                                          AS ncee_count,
       AVG(ncee)                                         AS ncee_avg,
       STDDEV_SAMP(ncee)                                 AS ncee_std,
       SUM(ug_avg * ug_cnt) / NULLIF(SUM(ug_cnt), 0)     AS ug_avg_all,
       SUM(fail_cnt) / NULLIF(SUM(ug_cnt), 0)            AS fail_rate,
       COUNT(DISTINCT CASE WHEN ug_cnt IS NOT NULL THEN sid END) AS ug_students,
       AVG(gpa)                                          AS gpa_avg,
       COUNT(gpa)                                        AS grad_count
FROM ( {ps} ) ps
""",
        params,
    )
    row = row[0] if row else {}
    fail_rate = _f(row.get("fail_rate"))
    return {
        "ncee_count": _i(row.get("ncee_count")),
        "ncee_avg": _f(row.get("ncee_avg")),
        "ncee_std": _f(row.get("ncee_std")),
        "ug_avg": _f(row.get("ug_avg_all")),
        "pass_rate": round(1 - fail_rate, 4) if fail_rate is not None else None,
        "ug_students": _i(row.get("ug_students")),
        "gpa_avg": _f(row.get("gpa_avg")),
        "grad_count": _i(row.get("grad_count")),
    }


def _ncee_hist(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Gaokao score histogram in 5-point buckets (plus mean/σ for the curve)."""
    bins: list[tuple[float, int]] = []
    for row in _rows(
        cursor,
        f"""
SELECT FLOOR(ncee / 5) * 5 AS bin, COUNT(*) AS c
FROM ( {ps} ) ps
WHERE ncee IS NOT NULL
GROUP BY bin
ORDER BY bin
""",
        params,
    ):
        bins.append((float(_i(row["bin"])), _i(row["c"])))
    stat = _rows(
        cursor,
        f"SELECT AVG(ncee) m, STDDEV_SAMP(ncee) s FROM ( {ps} ) ps",
        params,
    )
    stat = stat[0] if stat else {}
    return {
        "bins": [int(b) for b, _ in bins],
        "counts": [c for _, c in bins],
        "total": sum(c for _, c in bins),
        "mean": _f(stat.get("m")),
        "std": _f(stat.get("s")),
    }


def _ncee_yearly_hist(
    cursor: DictCursor, ps: str, params: list[Any]
) -> dict[str, Any]:
    """Per-exam-year histogram (5-point buckets) for trend quantiles."""
    grouped: dict[int, dict[str, Any]] = {}
    for row in _rows(
        cursor,
        f"""
SELECT ncee_year AS y, FLOOR(ncee / 5) * 5 AS b, COUNT(*) AS c, SUM(ncee) AS s
FROM ( {ps} ) ps
WHERE ncee_year IS NOT NULL
GROUP BY y, b
ORDER BY y, b
""",
        params,
    ):
        year = _i(row["y"])
        bucket = grouped.setdefault(year, {"bins": [], "sum": 0, "count": 0})
        bucket["bins"].append((float(_i(row["b"])), _i(row["c"])))
        bucket["sum"] += _i(row["s"])
        bucket["count"] += _i(row["c"])

    years = sorted(grouped)
    trend: dict[str, list[Any]] = {"avg": [], "median": [], "p25": [], "p75": []}
    for year in years:
        data = grouped[year]
        trend["avg"].append(round(data["sum"] / data["count"], 1))
        quantiles = _quantiles_from_hist(sorted(data["bins"]), 5.0)
        for index, key in enumerate(("p25", "median", "p75")):
            trend[key].append(round(quantiles[index], 1) if quantiles else None)
    return {
        "years": years,
        "avg": trend["avg"],
        "median": trend["median"],
        "p25": trend["p25"],
        "p75": trend["p75"],
    }


def _ncee_bands(ncee_hist: dict[str, Any]) -> list[dict[str, Any]]:
    """Collapse the 5-point histogram into coarse admission bands."""
    band_edges = [(0, 400, "<400"), (400, 450, "400-449"), (450, 500, "450-499"),
                  (500, 550, "500-549"), (550, 600, "550-599"), (600, 10**9, "600+")]
    counts = [0] * len(band_edges)
    for bin_edge, count in zip(ncee_hist["bins"], ncee_hist["counts"]):
        for index, (lo, _hi, _label) in enumerate(band_edges):
            if bin_edge >= lo and bin_edge < _hi:
                counts[index] += count
                break
    return [
        {"label": label, "count": counts[index]}
        for index, (_lo, _hi, label) in enumerate(band_edges)
        if not (index == 0 and counts[0] == 0)  # hide the empty "<400" band
    ]


def _ug_band_dist(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Undergraduate score band distribution: exam count vs student count."""
    bands: dict[int, dict[str, int]] = {}
    for row in _rows(
        cursor,
        f"""
SELECT LEAST(GREATEST(FLOOR(us.score / 10), 0), 9) AS band,
       COUNT(*)                                   AS cnt,
       COUNT(DISTINCT us.student_id)              AS stu
FROM undergraduate_scores us
JOIN ( SELECT DISTINCT sid FROM ( {ps} ) ps ) f ON f.sid = us.student_id
GROUP BY band
ORDER BY band
""",
        params,
    ):
        bands[_i(row["band"])] = {"cnt": _i(row["cnt"]), "stu": _i(row["stu"])}
    if not bands:
        return {"bands": [], "counts": [], "students": [], "total_count": 0,
                "total_students": 0}
    first = min(bands)
    labels: list[str] = []
    counts: list[int] = []
    students: list[int] = []
    for band in range(first, 10):
        label = "90-100" if band == 9 else f"{band * 10}-{band * 10 + 9}"
        entry = bands.get(band, {"cnt": 0, "stu": 0})
        labels.append(label)
        counts.append(entry["cnt"])
        students.append(entry["stu"])
    return {
        "bands": labels,
        "counts": counts,
        "students": students,
        "total_count": sum(counts),
        "total_students": sum(students),
    }


def _grade_trend(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Average score per undergraduate year (大一→大四) with quantile band."""
    grouped: dict[int, dict[str, Any]] = {}
    for row in _rows(
        cursor,
        f"""
SELECT (us.academic_year - le.academic_year + 1) AS grade,
       FLOOR(us.score)                           AS s,
       COUNT(*)                                  AS c,
       SUM(us.score)                             AS total
FROM undergraduate_scores us
JOIN ( {_LATEST_ENROLLMENT_SQL} ) le ON le.student_id = us.student_id
JOIN ( SELECT DISTINCT sid FROM ( {ps} ) ps ) f ON f.sid = us.student_id
WHERE us.score BETWEEN 0 AND 100
  AND (us.academic_year - le.academic_year + 1) BETWEEN 1 AND 4
GROUP BY grade, s
""",
        params,
    ):
        grade = _i(row["grade"])
        bucket = grouped.setdefault(grade, {"bins": [], "sum": 0, "count": 0})
        bucket["bins"].append((float(_i(row["s"])), _i(row["c"])))
        bucket["sum"] += _f(row["total"]) or 0.0
        bucket["count"] += _i(row["c"])

    grade_labels = {1: "大一", 2: "大二", 3: "大三", 4: "大四"}
    grades = sorted(grouped)
    trend: dict[str, list[Any]] = {"avg": [], "median": [], "p25": [], "p75": []}
    for grade in grades:
        data = grouped[grade]
        trend["avg"].append(round(data["sum"] / data["count"], 2))
        quantiles = _quantiles_from_hist(sorted(data["bins"]), 1.0)
        for index, key in enumerate(("p25", "median", "p75")):
            trend[key].append(round(quantiles[index], 1) if quantiles else None)
    return {
        "grades": [grade_labels[grade] for grade in grades],
        "avg": trend["avg"],
        "median": trend["median"],
        "p25": trend["p25"],
        "p75": trend["p75"],
    }


def _nature_boxplot(
    cursor: DictCursor, ps: str, params: list[Any], column: str, step: float
) -> dict[str, Any]:
    """Approximate boxplot (min/Q1/median/Q3/max) of one metric per nature."""
    if column == "gpa":
        bucket_expr, scale = "FLOOR(gpa * 10)", 0.1
    else:
        bucket_expr, scale = "FLOOR(ug_avg)", 1.0
    grouped: dict[str, list[tuple[float, int]]] = {}
    for row in _rows(
        cursor,
        f"""
SELECT nature, {bucket_expr} AS b, COUNT(*) AS c
FROM ( {ps} ) ps
WHERE nature IS NOT NULL AND {column} IS NOT NULL
GROUP BY nature, b
""",
        params,
    ):
        grouped.setdefault(str(row["nature"]), []).append(
            (_i(row["b"]) * scale, _i(row["c"]))
        )
    natures = [n for n in NATURE_ORDER if n in grouped]
    boxes = []
    for nature in natures:
        hist = sorted(grouped[nature])
        quantiles = _quantiles_from_hist(hist, step)
        if quantiles is None:
            boxes.append(None)
            continue
        low_edge = hist[0][0]
        high_edge = hist[-1][0] + step
        boxes.append([
            round(low_edge, 2),
            round(quantiles[0], 2),
            round(quantiles[1], 2),
            round(quantiles[2], 2),
            round(high_edge, 2),
        ])
    return {"natures": natures, "boxes": boxes}


def _scatter_ug(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Gaokao score (5-point bucket) vs average undergraduate score."""
    points = [
        [_i(row["xb"]), _f(row["y"]), _i(row["n"])]
        for row in _rows(
            cursor,
            f"""
SELECT FLOOR(ncee / 5) * 5 AS xb, AVG(ug_avg) AS y, COUNT(*) AS n
FROM ( {ps} ) ps
WHERE ug_avg IS NOT NULL
GROUP BY xb
ORDER BY xb
""",
            params,
        )
    ]
    return {"points": points}


def _scatter_gpa(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Gaokao score (5-point bucket) vs graduation GPA, plus Pearson r."""
    points = [
        [_i(row["xb"]), _f(row["y"]), _i(row["n"])]
        for row in _rows(
            cursor,
            f"""
SELECT FLOOR(ncee / 5) * 5 AS xb, AVG(gpa) AS y, COUNT(*) AS n
FROM ( {ps} ) ps
WHERE gpa IS NOT NULL
GROUP BY xb
ORDER BY xb
""",
            params,
        )
    ]
    corr_row = _rows(
        cursor,
        f"""
SELECT (AVG(ncee * gpa) - AVG(ncee) * AVG(gpa))
       / NULLIF(STDDEV_SAMP(ncee) * STDDEV_SAMP(gpa), 0) AS r,
       COUNT(*) AS n
FROM ( {ps} ) ps
WHERE gpa IS NOT NULL
""",
        params,
    )
    corr = corr_row[0] if corr_row else {}
    return {"points": points, "r": _f(corr.get("r")), "n": _i(corr.get("n"))}


def _corr_matrix(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Pearson correlation matrix over six per-student variables (single pass)."""
    rows = _rows(
        cursor,
        f"""
SELECT COUNT(*)   AS n,
       SUM(x1)    AS s1, SUM(x2) AS s2, SUM(x3) AS s3,
       SUM(x4)    AS s4, SUM(x5) AS s5, SUM(x6) AS s6,
       SUM(x1*x1) AS s11, SUM(x2*x2) AS s22, SUM(x3*x3) AS s33,
       SUM(x4*x4) AS s44, SUM(x5*x5) AS s55, SUM(x6*x6) AS s66,
       SUM(x1*x2) AS s12, SUM(x1*x3) AS s13, SUM(x1*x4) AS s14,
       SUM(x1*x5) AS s15, SUM(x1*x6) AS s16, SUM(x2*x3) AS s23,
       SUM(x2*x4) AS s24, SUM(x2*x5) AS s25, SUM(x2*x6) AS s26,
       SUM(x3*x4) AS s34, SUM(x3*x5) AS s35, SUM(x3*x6) AS s36,
       SUM(x4*x5) AS s45, SUM(x4*x6) AS s46, SUM(x5*x6) AS s56
FROM (
    SELECT ncee             AS x1,
           ug_avg           AS x2,
           ug_std           AS x3,
           fail_cnt / ug_cnt AS x4,
           ug_cnt           AS x5,
           gpa              AS x6
    FROM ( {ps} ) ps
    WHERE ug_avg IS NOT NULL AND ug_std IS NOT NULL AND gpa IS NOT NULL AND ug_cnt > 0
) t
""",
        params,
    )
    row = rows[0] if rows else {}
    n = _i(row.get("n"))
    if n < 2:
        return {"vars": list(CORR_VARS), "matrix": []}
    sums = {index: float(row[f"s{index}"]) for index in range(1, 7)}
    squares = {index: float(row[f"s{index}{index}"]) for index in range(1, 7)}
    cross = {
        (i, j): float(row[f"s{i}{j}"])
        for i in range(1, 7)
        for j in range(i + 1, 7)
    }
    variance = {index: squares[index] - sums[index] ** 2 / n for index in range(1, 7)}

    def corr(i: int, j: int) -> float:
        if i == j:
            return 1.0
        pair = (i, j) if i < j else (j, i)
        cov = cross[pair] - sums[i] * sums[j] / n
        denom = math.sqrt(variance[i] * variance[j])
        return round(cov / denom, 2) if denom else 0.0

    return {
        "vars": list(CORR_VARS),
        "matrix": [[corr(i, j) for j in range(1, 7)] for i in range(1, 7)],
        "n": n,
    }


def _stability(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Student-average × score-σ grid (2-point cells) for the stability scatter."""
    points = [
        [_i(row["xb"]), _i(row["yb"]), _i(row["n"])]
        for row in _rows(
            cursor,
            f"""
SELECT FLOOR(ug_avg / 2) * 2 AS xb, FLOOR(ug_std / 2) * 2 AS yb, COUNT(*) AS n
FROM ( {ps} ) ps
WHERE ug_std IS NOT NULL
GROUP BY xb, yb
""",
            params,
        )
    ]
    return {"points": points}


def _sankey(cursor: DictCursor, ps: str, params: list[Any]) -> dict[str, Any]:
    """Flows: gaokao band → university nature → ug grade band → GPA band."""
    rows = _rows(
        cursor,
        f"""
SELECT CASE WHEN ncee >= 600 THEN '高考 600+'
            WHEN ncee >= 550 THEN '高考 550-599'
            WHEN ncee >= 500 THEN '高考 500-549'
            WHEN ncee >= 450 THEN '高考 450-499'
            ELSE '高考 <450' END                 AS seg1,
       nature                                    AS seg2,
       CASE WHEN ug_avg >= 90 THEN '本科 90+'
            WHEN ug_avg >= 80 THEN '本科 80-89'
            WHEN ug_avg >= 70 THEN '本科 70-79'
            WHEN ug_avg >= 60 THEN '本科 60-69'
            ELSE '本科 <60' END                  AS seg3,
       CASE WHEN gpa >= 3.5 THEN 'GPA 3.5+'
            WHEN gpa >= 3.0 THEN 'GPA 3.0-3.5'
            WHEN gpa >= 2.5 THEN 'GPA 2.5-3.0'
            ELSE 'GPA <2.5' END                 AS seg4,
       COUNT(*) AS n
FROM ( {ps} ) ps
WHERE ug_avg IS NOT NULL AND gpa IS NOT NULL AND nature IS NOT NULL
GROUP BY seg1, seg2, seg3, seg4
""",
        params,
    )
    return {"rows": [[str(r["seg1"]), str(r["seg2"]), str(r["seg3"]),
                      str(r["seg4"]), _i(r["n"])] for r in rows]}


# ---------------------------------------------------------------------------
# University student counts (各大学学生数量统计页)
# ---------------------------------------------------------------------------


def collect_university_student_counts(config: Mapping[str, object]) -> dict[str, Any]:
    """Count enrolled students per university from ``web_db``.

    Aggregates ``enrollments`` joined with ``universities``: for every
    university the number of distinct enrolled students (``学生人数``) and the
    number of enrollment records (``录取人次``, larger when a student appears
    in several academic years).  Results are sorted by student count.

    Args:
        config: Flask configuration holding the ``MYSQL_WEB_*`` settings.

    Returns:
        JSON-ready dictionary with ``items`` (one per university),
        per-nature ``summary``, and an ``empty`` flag.  Degrades to an empty
        payload when the tables do not exist yet or the DB is unreachable.
    """
    settings = _settings(config)  # raises WebDBUnavailableError when unconfigured
    connection: pymysql.connections.Connection | None = None
    try:
        connection = pymysql.connect(
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=5,
            read_timeout=60,
            **settings,  # type: ignore[arg-type]
        )
        with connection.cursor() as cursor:
            rows = _rows(
                cursor,
                """
SELECT u.name                        AS name,
       u.nature                      AS nature,
       COUNT(DISTINCT e.student_id)  AS students,
       COUNT(*)                      AS enrollments
FROM enrollments e
JOIN universities u ON u.id = e.university_id
GROUP BY u.id, u.name, u.nature
ORDER BY students DESC, enrollments DESC, u.name ASC
""",
                [],
            )
    except pymysql.err.OperationalError as error:
        raise WebDBUnavailableError(f"web_db 暂时无法连接：{error}") from error
    finally:
        if connection is not None:
            connection.close()

    items = [
        {
            "name": str(row["name"]),
            "nature": str(row["nature"] or "未标注"),
            "students": _i(row["students"]),
            "enrollments": _i(row["enrollments"]),
        }
        for row in rows
    ]

    summary: dict[str, dict[str, int]] = {}
    for item in items:
        agg = summary.setdefault(
            item["nature"], {"universities": 0, "students": 0, "enrollments": 0}
        )
        agg["universities"] += 1
        agg["students"] += item["students"]
        agg["enrollments"] += item["enrollments"]
    natures = [n for n in NATURE_ORDER if n in summary]
    natures += sorted(k for k in summary if k not in NATURE_ORDER)

    return {
        "ok": True,
        "items": items,
        "summary": [{"nature": n, **summary[n]} for n in natures],
        "empty": not items,
    }


def collect_score_stats(
    config: Mapping[str, object],
    nature: str | None = None,
    ncee_year: int | None = None,
) -> dict[str, Any]:
    """Collect every dashboard metric in one connection.

    Args:
        config: Flask configuration holding the ``MYSQL_WEB_*`` settings.
        nature: Optional university-nature filter (one of ``NATURE_ORDER``).
        ncee_year: Optional gaokao exam-year filter.

    Returns:
        A JSON-ready dictionary with every metric; individual metrics degrade
        to empty structures when their tables do not exist yet.
    """
    settings = _settings(config)  # raises WebDBUnavailableError when unconfigured
    ps, params = _per_student_sql(nature, ncee_year)

    connection: pymysql.connections.Connection | None = None
    try:
        connection = pymysql.connect(
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=5,
            read_timeout=120,
            **settings,  # type: ignore[arg-type]
        )
        with connection.cursor() as cursor:
            ncee_hist = _ncee_hist(cursor, ps, params)
            yearly = _ncee_yearly_hist(cursor, ps, params)
            payload: dict[str, Any] = {
                "ok": True,
                "filters": {"nature": nature, "ncee_year": ncee_year},
                "kpi": _kpi(cursor, ps, params),
                "ncee_hist": ncee_hist,
                "ncee_bands": _ncee_bands(ncee_hist),
                "ncee_trend": yearly,
                "available_years": yearly["years"],
                "ug_dist": _ug_band_dist(cursor, ps, params),
                "grade_trend": _grade_trend(cursor, ps, params),
                "nature_box_ug": _nature_boxplot(cursor, ps, params, "ug_avg", 1.0),
                "nature_box_gpa": _nature_boxplot(cursor, ps, params, "gpa", 0.1),
                "scatter_ug": _scatter_ug(cursor, ps, params),
                "scatter_gpa": _scatter_gpa(cursor, ps, params),
                "corr": _corr_matrix(cursor, ps, params),
                "stability": _stability(cursor, ps, params),
                "sankey": _sankey(cursor, ps, params),
            }
    except pymysql.err.OperationalError as error:
        # The web_db server may be temporarily unreachable.
        raise WebDBUnavailableError(f"web_db 暂时无法连接：{error}") from error
    finally:
        if connection is not None:
            connection.close()

    kpi = payload["kpi"]
    payload["empty"] = kpi["ncee_count"] == 0
    return payload
