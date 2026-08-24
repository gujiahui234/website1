"""Functional checks for the in-memory student workflow."""

from __future__ import annotations

import re
import datetime as dt
import unittest
from unittest.mock import MagicMock, patch

from alt_web01 import create_app
from alt_web01.student_store import MySQLSettings, MySQLStudentStore
from alt_web01.views import _age_on


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
