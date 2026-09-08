"""Celery producer client for dispatching alt_celery3 platform tasks.

The web application acts as a pure producer: it never runs the heavy
generation work itself. Instead it publishes the ``generate_many_students``
task of the alt_celery3 platform through the Redis message broker configured
in the ``.env`` file and later polls the result backend for the outcome.
"""

from __future__ import annotations

import os
from pathlib import Path

from celery import Celery  # type: ignore[import-untyped]
from dotenv import load_dotenv

#: Canonical name of the bulk student generation task published by the
#: alt_celery3 platform (see ``app/config.py`` of alt_celery3).
GENERATE_MANY_STUDENTS_TASK = "tasks.db.generate_many_students"

#: Canonical name of the automatic university + major-group collection task
#: (SiliconFlow LLM powered, see ``app/tasks/ai_tasks.py`` of alt_celery3).
GET_UN_GROUPS_TASK = "tasks.ai.get_un_groups"

#: Hard upper bound of students a single request may generate (1 亿).
MAX_STUDENTS = 100_000_000

#: Seconds a finished result stays in the Redis result backend.
RESULT_EXPIRES = 86_400

_celery_app: Celery | None = None


def _load_dotenv_once() -> None:
    """Load the project ``.env`` file when the broker URL is not set yet."""
    if os.getenv("CELERY_BROKER_URL"):
        return
    project_root = Path(__file__).resolve().parents[2]
    for candidate in (Path.cwd() / ".env", project_root / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


def get_celery_app() -> Celery:
    """Return the shared Celery producer application.

    The instance is created lazily so that importing this module never
    requires a configured broker (keeps unit tests and tooling cheap).

    Returns:
        A Celery application bound to the broker and result backend taken
        from the ``CELERY_BROKER_URL`` / ``CELERY_RESULT_BACKEND`` variables.

    Raises:
        RuntimeError: When the broker or backend URL is missing.
    """
    global _celery_app
    if _celery_app is None:
        _load_dotenv_once()
        broker = os.getenv("CELERY_BROKER_URL", "").strip()
        backend = os.getenv("CELERY_RESULT_BACKEND", "").strip()
        if not broker or not backend:
            raise RuntimeError(
                "CELERY_BROKER_URL 和 CELERY_RESULT_BACKEND 必须在 .env 中配置"
            )
        _celery_app = Celery("alt_web01", broker=broker, backend=backend)
        _celery_app.conf.update(
            result_expires=RESULT_EXPIRES,
            task_track_started=True,
            # Keep socket timeouts short so that an unreachable platform
            # degrades into a fast 503 instead of hanging the web worker.
            broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
            result_backend_transport_options={
                "socket_connect_timeout": 3,
                "socket_timeout": 3,
                "retry_policy": {"timeout": 2.0},
            },
        )
    return _celery_app


def reset_celery_app() -> None:
    """Drop the cached Celery application (used by unit tests)."""
    global _celery_app
    _celery_app = None
