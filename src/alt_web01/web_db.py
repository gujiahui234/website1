"""Read access to the alt_celery3 platform's ``web_db.students`` table.

The ``generate_many_students`` task persists its output into the ``students``
table of the ``web_db`` business database. After a task finishes, this module
loads the most recently inserted rows so the large-import page can show the
latest 1,000 generated students.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Mapping, cast

import pymysql  # type: ignore[import-untyped]
from pymysql.cursors import DictCursor  # type: ignore[import-untyped]

#: MySQL error numbers that degrade into an empty result instead of failing
#: the page: the table does not exist yet (1146, the platform task has never
#: run) or a column is missing (1054, schema changed under us).
_BENIGN_ERRORS = {1146, 1054}


@dataclass(frozen=True)
class GeneratedStudent:
    """One generated student row from ``web_db.students``."""

    number: int
    name: str
    gender: str
    birthday: dt.date


class WebDBUnavailableError(RuntimeError):
    """Raised when the ``MYSQL_WEB_*`` settings are incomplete."""


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


def list_recent_students(config: Mapping[str, object], limit: int = 1000) -> list[GeneratedStudent]:
    """Return the newest ``limit`` students stored in ``web_db.students``.

    Args:
        config: Flask configuration holding the ``MYSQL_WEB_*`` settings.
        limit: Maximum number of rows to return (default 1,000).

    Returns:
        The newest students ordered by primary key descending. Returns an
        empty list when the table does not exist yet or the database is
        unreachable, so the page degrades gracefully instead of failing.
    """
    try:
        settings = _settings(config)
    except WebDBUnavailableError:
        return []

    connection: pymysql.connections.Connection | None = None
    try:
        connection = pymysql.connect(
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=5,
            **settings,  # type: ignore[arg-type]
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, gender, birthday "
                "FROM students ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            rows = cast(list[dict[str, object]], cursor.fetchall())
    except pymysql.err.OperationalError:
        # The web_db server may be temporarily unreachable.
        return []
    except pymysql.err.ProgrammingError as error:
        if error.args and error.args[0] in _BENIGN_ERRORS:
            # The generation task has not created the table yet.
            return []
        raise
    finally:
        if connection is not None:
            connection.close()

    return [
        GeneratedStudent(
            number=cast(int, row["id"]),
            name=str(row["name"]),
            gender=str(row["gender"]),
            birthday=cast(dt.date, row["birthday"]),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class PlatformUniversity:
    """One university row from the platform's ``web_db.universities`` table."""

    name: str
    code: str
    type: str
    nature: str


def list_platform_universities(
    config: Mapping[str, object], limit: int = 20
) -> list[PlatformUniversity]:
    """Return the newest ``limit`` universities stored by the platform.

    The ``get_un_groups`` task persists its output into the ``universities``
    table of ``web_db``; this helper loads the most recently inserted rows so
    the automatic-collection page can show what the platform already holds.

    Args:
        config: Flask configuration holding the ``MYSQL_WEB_*`` settings.
        limit: Maximum number of rows to return (default 20).

    Returns:
        The newest universities ordered by primary key descending. Returns an
        empty list when the table does not exist yet or the database is
        unreachable, so the page degrades gracefully instead of failing.
    """
    try:
        settings = _settings(config)
    except WebDBUnavailableError:
        return []

    connection: pymysql.connections.Connection | None = None
    try:
        connection = pymysql.connect(
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=5,
            **settings,  # type: ignore[arg-type]
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT name, code, type, nature "
                "FROM universities ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            rows = cast(list[dict[str, object]], cursor.fetchall())
    except pymysql.err.OperationalError:
        # The web_db server may be temporarily unreachable.
        return []
    except pymysql.err.ProgrammingError as error:
        if error.args and error.args[0] in _BENIGN_ERRORS:
            # The collection task has not created the table yet.
            return []
        raise
    finally:
        if connection is not None:
            connection.close()

    return [
        PlatformUniversity(
            name=str(row["name"]),
            code=str(row["code"]),
            type=str(row["type"]),
            nature=str(row["nature"]),
        )
        for row in rows
    ]


def count_platform_data(config: Mapping[str, object]) -> dict[str, int]:
    """Count the platform-collected rows in ``web_db``.

    Args:
        config: Flask configuration holding the ``MYSQL_WEB_*`` settings.

    Returns:
        Dictionary with ``universities`` and ``major_groups`` row counts.
        Both keys are ``0`` when the tables do not exist yet or the database
        is unreachable, so the page degrades gracefully instead of failing.
    """
    empty: dict[str, int] = {"universities": 0, "major_groups": 0}
    try:
        settings = _settings(config)
    except WebDBUnavailableError:
        return empty

    connection: pymysql.connections.Connection | None = None
    try:
        connection = pymysql.connect(
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=5,
            **settings,  # type: ignore[arg-type]
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM universities")
            universities = int(cast("int", cursor.fetchone()["n"]))  # type: ignore[union-attr]
            cursor.execute("SELECT COUNT(*) AS n FROM major_groups")
            major_groups = int(cast("int", cursor.fetchone()["n"]))  # type: ignore[union-attr]
    except pymysql.err.OperationalError:
        # The web_db server may be temporarily unreachable.
        return empty
    except pymysql.err.ProgrammingError as error:
        if error.args and error.args[0] in _BENIGN_ERRORS:
            # The collection task has not created the tables yet.
            return empty
        raise
    finally:
        if connection is not None:
            connection.close()

    return {"universities": universities, "major_groups": major_groups}
