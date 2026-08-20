"""Functional checks for the in-memory student workflow."""

from __future__ import annotations

import re
import unittest

from alt_web01 import create_app


class StudentWorkflowTests(unittest.TestCase):
    """Exercise generation, validation, and process-local saving."""

    def setUp(self) -> None:
        """Create an isolated application store for each test."""
        self.app = create_app()
        self.app.config.update(TESTING=True)
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


if __name__ == "__main__":
    unittest.main()
