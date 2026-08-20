"""Application factory for alt_web01."""

from __future__ import annotations

import atexit
from pathlib import Path
from time import perf_counter

from flask import Flask, Response, g, request
from sclog_lite import logger, setup_logger, shutdown
from werkzeug.exceptions import HTTPException

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


def create_app() -> Flask:
    """Create and configure the Flask application.

    Returns:
        Flask: A configured Flask application instance.
    """
    _configure_logging()
    app = Flask(__name__)
    app.extensions["saved_students"] = []

    from alt_web01.views import pages

    app.register_blueprint(pages)
    _register_logging_middleware(app)
    logger.bind(component="flask").info("alt_web01 应用已创建")
    return app
