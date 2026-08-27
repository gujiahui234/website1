"""Functional and persistence checks for the university workflow."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pymysql.err import IntegrityError  # type: ignore[import-untyped]

from alt_web01 import create_app
from alt_web01.student_store import MySQLSettings
from alt_web01.university_store import (
    DuplicateUniversityError,
    MySQLUniversityStore,
)


class UniversityWorkflowTests(unittest.TestCase):
    """Exercise university validation, uniqueness, saving, and listing."""

    def setUp(self) -> None:
        """Create an isolated application store for each test."""
        self.app = create_app({"STUDENT_STORE": "memory", "TESTING": True})
        self.client = self.app.test_client()

    def _save(self, **overrides: str):
        """Post one university with optional field overrides.

        Args:
            **overrides: Form values that replace the valid defaults.

        Returns:
            flask.testing.TestResponse: The university page response.
        """
        values = {
            "name": "示例大学",
            "code": "10001",
            "type": "公办",
            "nature": "985",
        }
        values.update(overrides)
        return self.client.post(
            "/universities/add",
            data=values,
            follow_redirects=True,
        )

    def test_page_contains_form_and_datatable(self) -> None:
        """The page should expose every field and initialize DataTable."""
        page = self.client.get("/universities/add").get_data(as_text=True)

        self.assertIn('name="name"', page)
        self.assertIn('name="code"', page)
        self.assertIn('name="type"', page)
        self.assertIn('name="nature"', page)
        self.assertIn('id="universities-table"', page)
        self.assertIn('new DataTable("#universities-table"', page)

    def test_save_displays_university_in_complete_list(self) -> None:
        """A valid university should appear after the success redirect."""
        response = self._save()
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("高校保存成功", page)
        self.assertIn("示例大学", page)
        self.assertIn("10001", page)
        self.assertIn("公办", page)
        self.assertIn("985", page)
        self.assertIn("1 所", page)

    def test_rejects_non_five_digit_code(self) -> None:
        """Server-side validation should require exactly five ASCII digits."""
        response = self._save(code="1234A")
        page = response.get_data(as_text=True)

        self.assertIn("高校代码必须是五位数字", page)
        self.assertNotIn("高校保存成功", page)

    def test_rejects_missing_or_unknown_choices(self) -> None:
        """Server-side validation should reject every unsupported field value."""
        cases = [
            ({"name": ""}, "请输入高校名称"),
            ({"type": "未知"}, "请选择有效的高校类型"),
            ({"nature": "双一流"}, "请选择有效的高校性质"),
        ]

        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                page = self._save(**overrides).get_data(as_text=True)
                self.assertIn(message, page)
                self.assertNotIn("高校保存成功", page)

    def test_rejects_duplicate_name(self) -> None:
        """A saved university name cannot be reused with another code."""
        self._save()
        response = self._save(code="10002")
        page = response.get_data(as_text=True)

        self.assertIn("高校名称或代码已存在", page)
        self.assertIn("1 所", page)

    def test_rejects_duplicate_code(self) -> None:
        """A saved university code cannot be reused with another name."""
        self._save()
        response = self._save(name="另一所大学")
        page = response.get_data(as_text=True)

        self.assertIn("高校名称或代码已存在", page)
        self.assertIn("1 所", page)


class MySQLUniversityStoreTests(unittest.TestCase):
    """Check MySQL schema, parameterization, and duplicate translation."""

    def setUp(self) -> None:
        """Create a store with non-root test settings."""
        self.store = MySQLUniversityStore(
            MySQLSettings("mysql-server", 3306, "test_db", "test_user", "pw")
        )

    @patch("alt_web01.university_store.pymysql.connect")
    def test_schema_has_unique_name_and_code(self, connect: MagicMock) -> None:
        """The database schema should enforce both uniqueness rules."""
        cursor = connect.return_value.cursor.return_value.__enter__.return_value

        self.store.ensure_schema()

        schema = cursor.execute.call_args_list[0].args[0]
        self.assertIn("UNIQUE KEY uq_universities_name (name)", schema)
        self.assertIn("UNIQUE KEY uq_universities_code (code)", schema)
        self.assertIn("code CHAR(5) NOT NULL", schema)
        migration = cursor.execute.call_args_list[1].args[0]
        self.assertIn("MODIFY COLUMN code CHAR(5) NOT NULL", migration)
        connect.return_value.commit.assert_called_once()

    @patch("alt_web01.university_store.pymysql.connect")
    def test_save_uses_parameters(self, connect: MagicMock) -> None:
        """University values should be passed as SQL parameters."""
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.lastrowid = 7

        university = self.store.save_university(
            name="示例大学", code="10001", type="公办", nature="985"
        )

        query, parameters = cursor.execute.call_args.args
        self.assertIn("VALUES (%s, %s, %s, %s)", query)
        self.assertEqual(parameters, ("示例大学", "10001", "公办", "985"))
        self.assertEqual(university.number, 7)
        connect.return_value.commit.assert_called_once()

    @patch("alt_web01.university_store.pymysql.connect")
    def test_list_returns_all_universities(self, connect: MagicMock) -> None:
        """The university listing query should not impose a row limit."""
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        self.assertEqual(self.store.list_universities(), [])

        query = cursor.execute.call_args.args[0]
        self.assertIn("ORDER BY created_at DESC, id DESC", query)
        self.assertNotIn("LIMIT", query)

    @patch("alt_web01.university_store.pymysql.connect")
    def test_duplicate_integrity_error_is_translated(
        self, connect: MagicMock
    ) -> None:
        """A database unique-key violation should become a domain error."""
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = IntegrityError(1062, "Duplicate entry")

        with self.assertRaises(DuplicateUniversityError):
            self.store.save_university(
                name="示例大学", code="10001", type="公办", nature="985"
            )

        connect.return_value.rollback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
