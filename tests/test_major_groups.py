"""Functional and persistence checks for the major group workflow."""

from __future__ import annotations

import unittest
from typing import cast
from unittest.mock import MagicMock, patch

from pymysql.err import IntegrityError  # type: ignore[import-untyped]

from alt_web01 import create_app
from alt_web01.major_group_store import (
    DuplicateMajorGroupError,
    MajorGroupStore,
    MySQLMajorGroupStore,
)
from alt_web01.student_store import MySQLSettings
from alt_web01.university_store import SavedUniversity, UniversityStore


class MajorGroupWorkflowTests(unittest.TestCase):
    """Exercise university selection, validation, uniqueness, and filtering."""

    def setUp(self) -> None:
        """Create an isolated app and two saved universities."""
        self.app = create_app({"STUDENT_STORE": "memory", "TESTING": True})
        self.client = self.app.test_client()
        university_store = cast(
            UniversityStore, self.app.extensions["university_store"]
        )
        self.first_university = university_store.save_university(
            name="第一大学", code="10001", type="公办", nature="985"
        )
        self.second_university = university_store.save_university(
            name="第二大学", code="10002", type="民办", nature="其他"
        )

    def _save(
        self,
        university: SavedUniversity | None = None,
        /,
        **overrides: str,
    ):
        """Post one major group with optional field overrides.

        Args:
            university: Parent university, defaulting to the first one.
            **overrides: Form values that replace valid defaults.

        Returns:
            flask.testing.TestResponse: The major group page response.
        """
        parent = university or self.first_university
        values = {
            "university_id": str(parent.number),
            "name": "计算机类",
            "code": "01001",
        }
        values.update(overrides)
        return self.client.post(
            "/majors/add",
            data=values,
            follow_redirects=True,
        )

    def test_page_selects_university_and_contains_datatable(self) -> None:
        """The page should offer saved universities and initialize DataTable."""
        page = self.client.get("/majors/add").get_data(as_text=True)

        self.assertIn("10001 · 第一大学", page)
        self.assertIn("10002 · 第二大学", page)
        self.assertIn('name="name"', page)
        self.assertIn('name="code"', page)
        self.assertIn('id="major-groups-table"', page)
        self.assertIn('new DataTable("#major-groups-table"', page)

    def test_save_displays_group_for_selected_university(self) -> None:
        """A valid group should appear under its selected university."""
        response = self._save()
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("专业组保存成功", page)
        self.assertIn("计算机类", page)
        self.assertIn("01001", page)
        self.assertIn("第一大学 · 显示该校全部专业组", page)
        self.assertIn("1 个", page)

    def test_rejects_invalid_group_values_and_university(self) -> None:
        """Server-side validation should enforce every submitted field."""
        cases = [
            ({"name": ""}, "请输入专业组名称"),
            ({"code": "1"}, "专业组代码必须是二至五位数字"),
            ({"code": "123456"}, "专业组代码必须是二至五位数字"),
            ({"code": "12A"}, "专业组代码必须是二至五位数字"),
            ({"university_id": "999"}, "请选择有效的高校"),
        ]

        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                page = self._save(**overrides).get_data(as_text=True)
                self.assertIn(message, page)
                self.assertNotIn("专业组保存成功", page)

    def test_accepts_two_through_five_digit_group_codes(self) -> None:
        """Codes used by different provincial systems should be accepted."""
        for index, code in enumerate(("01", "101", "19801"), start=1):
            with self.subTest(code=code):
                response = self._save(name=f"专业组{index}", code=code)
                self.assertIn("专业组保存成功", response.get_data(as_text=True))

    def test_rejects_duplicate_name_and_code_within_university(self) -> None:
        """Name and code should each be unique within one university."""
        self._save()
        duplicate_name = self._save(code="01002").get_data(as_text=True)
        duplicate_code = self._save(name="电子信息类").get_data(as_text=True)

        self.assertIn("该高校内专业组名称或代码已存在", duplicate_name)
        self.assertIn("该高校内专业组名称或代码已存在", duplicate_code)
        self.assertIn("1 个", duplicate_code)

    def test_same_name_and_code_are_allowed_at_another_university(self) -> None:
        """University-scoped values may be reused by another university."""
        self._save()
        response = self._save(self.second_university)

        self.assertIn("专业组保存成功", response.get_data(as_text=True))

    def test_switching_university_filters_displayed_groups(self) -> None:
        """Changing the selected university should reload only its groups."""
        self._save(name="第一校专业组", code="01001")
        self._save(
            self.second_university,
            name="第二校专业组",
            code="02001",
        )

        first_page = self.client.get(
            f"/majors/add?university_id={self.first_university.number}"
        ).get_data(as_text=True)
        second_page = self.client.get(
            f"/majors/add?university_id={self.second_university.number}"
        ).get_data(as_text=True)

        self.assertIn("第一校专业组", first_page)
        self.assertNotIn("第二校专业组", first_page)
        self.assertIn("第二校专业组", second_page)
        self.assertNotIn("第一校专业组", second_page)


class EmptyUniversityMajorGroupTests(unittest.TestCase):
    """Check the empty-university prerequisite state."""

    def test_page_prompts_user_to_add_university_first(self) -> None:
        """No group can be added before at least one university exists."""
        app = create_app({"STUDENT_STORE": "memory", "TESTING": True})
        page = app.test_client().get("/majors/add").get_data(as_text=True)

        self.assertIn("暂无可选高校", page)
        self.assertIn("添加高校", page)


class MySQLMajorGroupStoreTests(unittest.TestCase):
    """Check MySQL relationships, scoped uniqueness, and parameterization."""

    def setUp(self) -> None:
        """Create a store with non-root test settings."""
        self.store = MySQLMajorGroupStore(
            MySQLSettings("mysql-server", 3306, "test_db", "test_user", "pw")
        )

    @patch("alt_web01.major_group_store.pymysql.connect")
    def test_schema_has_foreign_key_and_scoped_unique_keys(
        self, connect: MagicMock
    ) -> None:
        """Schema should link universities and scope both unique values."""
        cursor = connect.return_value.cursor.return_value.__enter__.return_value

        self.store.ensure_schema()

        schema = cursor.execute.call_args_list[0].args[0]
        self.assertIn("FOREIGN KEY (university_id)", schema)
        self.assertIn("(university_id, name)", schema)
        self.assertIn("(university_id, code)", schema)
        self.assertIn("code VARCHAR(5) NOT NULL", schema)
        migration = cursor.execute.call_args_list[1].args[0]
        self.assertIn("MODIFY COLUMN code VARCHAR(5) NOT NULL", migration)

    @patch("alt_web01.major_group_store.pymysql.connect")
    def test_list_filters_by_university(self, connect: MagicMock) -> None:
        """Listing should query all groups for exactly one university."""
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        self.assertEqual(
            self.store.list_major_groups(university_number=3), []
        )

        query, parameters = cursor.execute.call_args.args
        self.assertIn("WHERE major_groups.university_id = %s", query)
        self.assertEqual(parameters, (3,))
        self.assertNotIn("LIMIT", query)

    @patch("alt_web01.major_group_store.pymysql.connect")
    def test_save_uses_parameters_and_translates_duplicates(
        self, connect: MagicMock
    ) -> None:
        """Saving should parameterize values and translate duplicate keys."""
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.lastrowid = 9

        group = self.store.save_major_group(
            university_number=3,
            university_name="示例大学",
            name="计算机类",
            code="01001",
        )

        query, parameters = cursor.execute.call_args.args
        self.assertIn("VALUES (%s, %s, %s)", query)
        self.assertEqual(parameters, (3, "计算机类", "01001"))
        self.assertEqual(group.number, 9)

        cursor.execute.side_effect = IntegrityError(1062, "Duplicate entry")
        with self.assertRaises(DuplicateMajorGroupError):
            self.store.save_major_group(
                university_number=3,
                university_name="示例大学",
                name="计算机类",
                code="01001",
            )


if __name__ == "__main__":
    unittest.main()
