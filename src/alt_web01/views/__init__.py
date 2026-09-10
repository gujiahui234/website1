"""Page blueprint and route module registration."""

from __future__ import annotations

from flask import Blueprint

pages = Blueprint("pages", __name__)

# Import every page module after creating the shared blueprint so their route
# decorators are registered before the application registers ``pages``.
from alt_web01.views import (  # noqa: E402, F401
    analytics_students_by_university,
    analytics_students_by_year,
    database_init,
    enrollment_automatic,
    enrollment_manual,
    home,
    major_group_add,
    student_add,
    student_import_large,
    student_import_small,
    student_maintain,
    university_add,
    university_generate,
)

__all__ = ["pages"]
