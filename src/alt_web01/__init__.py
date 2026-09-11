"""Application factory for alt_web01."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
from time import perf_counter

from flask import Flask, Response, g, request
from sclog_lite import logger, setup_logger, shutdown
from werkzeug.exceptions import HTTPException

from alt_web01.major_group_store import (
    MajorGroupStore,
    MemoryMajorGroupStore,
    MySQLMajorGroupStore,
)
from alt_web01.student_store import (
    MemoryStudentStore,
    MySQLSettings,
    MySQLStudentStore,
    StudentStore,
)
from alt_web01.university_store import (
    MemoryUniversityStore,
    MySQLUniversityStore,
    UniversityStore,
)

_logging_configured = False


def _configure_logging() -> None:
    """Configure the shared application logger once per process."""
    global _logging_configured
    if _logging_configured:
        return

    setup_logger(
        console=True,
        file=True,
        log_dir=Path("logs"),
        file_options={"rotation": "10 MB", "retention": "7 days"},
    )
    atexit.register(shutdown)
    _logging_configured = True


def _register_logging_middleware(app: Flask) -> None:
    """Attach request, response, and exception logging to a Flask app."""

    @app.before_request
    def log_request_start() -> None:
        g.request_started_at = perf_counter()
        logger.bind(method=request.method, path=request.path).info(
            "Flask 请求开始"
        )

    @app.after_request
    def log_request_end(response: Response) -> Response:
        started_at = getattr(g, "request_started_at", perf_counter())
        logger.bind(
            method=request.method,
            path=request.path,
            status_code=response.status_code,
            elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
        ).info("Flask 请求完成")
        return response

    @app.errorhandler(Exception)
    def log_request_error(error: Exception) -> HTTPException | tuple[str, int]:
        log = logger.bind(method=request.method, path=request.path)
        if isinstance(error, HTTPException):
            log.warning("Flask 请求异常：{error}", error=error)
            return error

        log.opt(exception=error).error("Flask 请求发生未处理异常")
        return "服务器内部错误", 500


def create_app(test_config: dict[str, object] | None = None) -> Flask:
    """Create and configure the Flask application.

    Returns:
        Flask: A configured Flask application instance.
    """
    _configure_logging()
    app = Flask(__name__)
    app.config.from_mapping(
        STUDENT_STORE=os.getenv("STUDENT_STORE", "memory"),
        MYSQL_HOST=os.getenv("MYSQL_HOST", ""),
        MYSQL_PORT=os.getenv("MYSQL_PORT", "3306"),
        MYSQL_DATABASE=os.getenv("MYSQL_DATABASE", ""),
        MYSQL_USER=os.getenv("MYSQL_USER", ""),
        MYSQL_PASSWORD=os.getenv("MYSQL_PASSWORD", ""),
        # Celery 平台 web_db 业务库（批量生成结果所在库）。
        MYSQL_WEB_HOST=os.getenv("MYSQL_WEB_HOST", ""),
        MYSQL_WEB_PORT=os.getenv("MYSQL_WEB_PORT", "3306"),
        MYSQL_WEB_DATABASE=os.getenv("MYSQL_WEB_DATABASE", "web_db"),
        MYSQL_WEB_USER=os.getenv("MYSQL_WEB_USER", ""),
        MYSQL_WEB_PASSWORD=os.getenv("MYSQL_WEB_PASSWORD", ""),
        # 学生 API 服务器（poc4-students-api）调试与文档地址。
        API_SERVER_DOCS=os.getenv("API_SERVER_DOCS", ""),
        API_SERVER_REDOC=os.getenv("API_SERVER_REDOC", ""),
        API_SERVER_JSON=os.getenv("API_SERVER_JSON", ""),
        # Celery 任务平台 API 服务器（alt_celery3）任务目录地址。
        API_SERVER_TASKS=os.getenv("API_SERVER_TASKS", ""),
    )
    if test_config is not None:
        app.config.update(test_config)

    store_mode = str(app.config["STUDENT_STORE"]).strip().casefold()
    student_store: StudentStore
    university_store: UniversityStore
    major_group_store: MajorGroupStore
    if store_mode == "mysql":
        # Tables are created by the Celery platform's ``init_web_db`` task
        # (系统设置 → 数据库初始化); this app no longer runs any DDL itself.
        settings = MySQLSettings.from_config(app.config)
        student_store = MySQLStudentStore(settings)
        university_store = MySQLUniversityStore(settings)
        major_group_store = MySQLMajorGroupStore(settings)
    elif store_mode == "memory":
        student_store = MemoryStudentStore()
        university_store = MemoryUniversityStore()
        major_group_store = MemoryMajorGroupStore()
    else:
        raise RuntimeError("STUDENT_STORE must be either 'memory' or 'mysql'")
    app.extensions["student_store"] = student_store
    app.extensions["university_store"] = university_store
    app.extensions["major_group_store"] = major_group_store

    from alt_web01.views import pages

    app.register_blueprint(pages)
    _register_logging_middleware(app)
    logger.bind(component="flask", student_store=store_mode).info(
        "alt_web01 应用已创建"
    )
    return app
