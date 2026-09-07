"""Functional checks for the in-memory student workflow."""

from __future__ import annotations

import re
import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

from alt_web01 import create_app
from alt_web01.student_store import MySQLSettings, MySQLStudentStore
from alt_web01.views.student_add import _age_on


class RouteContractTests(unittest.TestCase):
    """Ensure modularization preserves every public page route."""

    def setUp(self) -> None:
        """Create an application with an isolated in-memory store."""
        self.app = create_app({"STUDENT_STORE": "memory", "TESTING": True})
        self.client = self.app.test_client()

    def test_page_endpoints_and_paths_are_unchanged(self) -> None:
        """All page endpoints should remain registered exactly once."""
        expected_routes = {
            ("pages.home", "/"),
            ("pages.student_add", "/students/add"),
            ("pages.student_import_small", "/students/import/small"),
            ("pages.student_import_large", "/students/import/large"),
            (
                "pages.student_import_large_start",
                "/students/import/large/start",
            ),
            (
                "pages.student_import_large_result",
                "/students/import/large/result",
            ),
            ("pages.university_add", "/universities/add"),
            ("pages.major_group_add", "/majors/add"),
            ("pages.university_generate", "/universities/generate"),
            ("pages.enrollment_manual", "/enrollment/manual"),
            ("pages.enrollment_automatic", "/enrollment/automatic"),
            (
                "pages.analytics_students_by_year",
                "/analytics/students-by-year",
            ),
            (
                "pages.analytics_students_by_university",
                "/analytics/students-by-university",
            ),
        }
        actual_routes = [
            (rule.endpoint, rule.rule)
            for rule in self.app.url_map.iter_rules()
            if rule.endpoint.startswith("pages.")
        ]

        self.assertEqual(len(actual_routes), len(expected_routes))
        self.assertEqual(set(actual_routes), expected_routes)

    def test_every_page_get_request_succeeds(self) -> None:
        """Each modularized page should still render successfully."""
        paths = [
            "/",
            "/students/add",
            "/students/import/small",
            "/students/import/large",
            "/universities/add",
            "/majors/add",
            "/universities/generate",
            "/enrollment/manual",
            "/enrollment/automatic",
            "/analytics/students-by-year",
            "/analytics/students-by-university",
        ]

        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)


class StudentWorkflowTests(unittest.TestCase):
    """Exercise generation, validation, and process-local saving."""

    def setUp(self) -> None:
        """Create an isolated application store for each test."""
        self.app = create_app({"STUDENT_STORE": "memory", "TESTING": True})
        self.client = self.app.test_client()

    def test_generate_returns_fictional_student_in_allowed_range(self) -> None:
        """The generator should populate all fields within 2000 through 2020."""
        response = self.client.post(
            "/students/add", data={"action": "generate"}
        )
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        birthday_match = re.search(
            r'id="birthday"[^>]*value="(\d{4}-\d{2}-\d{2})"', page
        )
        self.assertIsNotNone(birthday_match)
        assert birthday_match is not None
        self.assertGreaterEqual(birthday_match.group(1), "2000-01-01")
        self.assertLessEqual(birthday_match.group(1), "2020-12-31")
        self.assertRegex(page, r'<option value="[男女]" selected>')

    def test_save_redirects_and_displays_student(self) -> None:
        """A valid student should appear in the saved roster after redirect."""
        response = self.client.post(
            "/students/add",
            data={
                "action": "save",
                "name": "测试学生",
                "birthday": "2010-06-15",
                "gender": "女",
            },
            follow_redirects=True,
        )
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("学生保存成功", page)
        self.assertIn("测试学生", page)
        self.assertIn("2010-06-15", page)
        self.assertIn("id=\"students-table\"", page)
        self.assertIn("年龄", page)
        self.assertIn("保存时间", page)
        self.assertIn("new DataTable", page)

    def test_rejects_birthday_outside_allowed_range(self) -> None:
        """Server-side validation should reject dates outside the HTML limits."""
        response = self.client.post(
            "/students/add",
            data={
                "action": "save",
                "name": "越界学生",
                "birthday": "1999-12-31",
                "gender": "男",
            },
        )
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("生日必须在 2000 年至 2020 年之间", page)
        self.assertNotIn("<td class=\"student-name\">越界学生</td>", page)


class LargeImportWorkflowTests(unittest.TestCase):
    """Exercise the Celery-backed large student import workflow."""

    def setUp(self) -> None:
        """Create an application with an isolated in-memory store."""
        self.app = create_app({"STUDENT_STORE": "memory", "TESTING": True})
        self.client = self.app.test_client()

    def test_start_rejects_out_of_range_numbers(self) -> None:
        """Numbers below 1 or above 1 亿 must be rejected without dispatching."""
        for numbers in ("0", "-5", "100000001", "abc"):
            with self.subTest(numbers=numbers):
                response = self.client.post(
                    "/students/import/large/start", data={"numbers": numbers}
                )
                self.assertEqual(response.status_code, 400)

    def test_start_requires_paired_birthday_boundaries(self) -> None:
        """Birthday min/max must be provided together."""
        response = self.client.post(
            "/students/import/large/start",
            data={"numbers": "10", "birthday_min": "2000"},
        )
        self.assertEqual(response.status_code, 400)

    def test_start_rejects_invalid_birthday_format(self) -> None:
        """Only YYYY / YYYY-MM / YYYY-MM-DD boundaries are accepted."""
        response = self.client.post(
            "/students/import/large/start",
            data={"numbers": "10", "birthday_min": "2000-13-01", "birthday_max": "2010"},
        )
        self.assertEqual(response.status_code, 400)

    @patch("alt_web01.views.student_import_large.get_celery_app")
    def test_start_dispatches_platform_task(self, get_celery_app: MagicMock) -> None:
        """A valid request should publish the generate_many_students task."""
        celery = get_celery_app.return_value
        celery.send_task.return_value.id = "task-42"

        response = self.client.post(
            "/students/import/large/start",
            data={
                "numbers": "100",
                "birthday_min": "2000-01-01",
                "birthday_max": "2010-12-31",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["task_id"], "task-42")
        kwargs = celery.send_task.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["numbers"], 100)
        self.assertEqual(kwargs["birthday_min"], "2000-01-01")
        self.assertEqual(kwargs["birthday_max"], "2010-12-31")

    @patch("alt_web01.views.student_import_large.list_recent_students")
    @patch("alt_web01.views.student_import_large.get_celery_app")
    def test_result_reports_inserted_students(
        self, get_celery_app: MagicMock, list_recent: MagicMock
    ) -> None:
        """A successful task should expose the inserted count and roster."""
        async_result = get_celery_app.return_value.AsyncResult.return_value
        async_result.state = "SUCCESS"
        async_result.result = {"ok": True, "inserted": 5, "number_start": 1}
        list_recent.return_value = []

        response = self.client.get("/students/import/large/result?task_id=task-42")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["state"], "SUCCESS")
        self.assertEqual(data["inserted"], 5)

    @patch("alt_web01.views.student_import_large.get_celery_app")
    def test_result_reports_progress_state(
        self, get_celery_app: MagicMock
    ) -> None:
        """A running task should stay in the generating state."""
        async_result = get_celery_app.return_value.AsyncResult.return_value
        async_result.state = "PROGRESS"
        async_result.info = {"inserted": 1200}

        response = self.client.get("/students/import/large/result?task_id=task-42")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["state"], "PROGRESS")
        self.assertEqual(data["inserted"], 1200)


class MySQLStudentStoreTests(unittest.TestCase):
    """Check the MySQL safety boundary without requiring a live database."""

    def test_rejects_root_database_account(self) -> None:
        """The application must never connect to MySQL as root."""
        with self.assertRaisesRegex(RuntimeError, "non-root"):
            MySQLSettings.from_config(
                {
                    "MYSQL_HOST": "mysql-server",
                    "MYSQL_DATABASE": "test_db",
                    "MYSQL_USER": "root",
                    "MYSQL_PASSWORD": "not-used",
                }
            )

    @patch("alt_web01.student_store.pymysql.connect")
    def test_connection_uses_configured_non_root_account(
        self, connect: MagicMock
    ) -> None:
        """The store should pass only the configured app account to PyMySQL."""
        settings = MySQLSettings(
            host="mysql-server",
            port=3306,
            database="test_db",
            user="test_user",
            password="database-password",
        )
        store = MySQLStudentStore(settings)

        store._connect()

        connect.assert_called_once()
        call_kwargs = connect.call_args.kwargs
        self.assertEqual(call_kwargs["user"], "test_user")
        self.assertNotEqual(call_kwargs["user"], "root")

    @patch("alt_web01.student_store.pymysql.connect")
    def test_list_students_queries_latest_1000(self, connect: MagicMock) -> None:
        """The database query should cap and order records before rendering."""
        connection = connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        store = MySQLStudentStore(
            MySQLSettings("mysql-server", 3306, "test_db", "test_user", "pw")
        )

        self.assertEqual(store.list_students(), [])

        query = cursor.execute.call_args.args[0]
        self.assertIn("ORDER BY created_at DESC, id DESC", query)
        self.assertIn("LIMIT 1000", query)


class AgeCalculationTests(unittest.TestCase):
    """Verify the dynamic calculated age column."""

    def test_age_is_rounded_to_one_decimal_place(self) -> None:
        """Age should be fractional between adjacent birthdays."""
        age = _age_on(dt.date(2000, 1, 1), dt.date(2025, 7, 2))

        self.assertEqual(age, 25.5)


if __name__ == "__main__":
    unittest.main()
